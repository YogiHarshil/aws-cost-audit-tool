"""S3 bucket scanner (lifecycle, large buckets without Intelligent-Tiering)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

from botocore.exceptions import ClientError

from models.finding import Finding
from scanners.base import BaseScanner

logger = logging.getLogger(__name__)

_LARGE_BYTES = 100 * 1024 * 1024 * 1024  # 100 GiB


class S3Scanner(BaseScanner):
    """Detect buckets missing lifecycle rules or large standard storage without tiering."""

    def scan(self) -> List[Finding]:
        return self._scan_missing_lifecycle() + self._scan_large_buckets_no_tiering()

    def _bucket_region(self, s3: Any, name: str) -> Optional[str]:
        try:
            loc = s3.get_bucket_location(Bucket=name).get("LocationConstraint")
        except ClientError as exc:
            logger.debug("get_bucket_location failed for %s: %s", name, exc)
            return None
        if loc is None or loc == "":
            return "us-east-1"
        return loc

    def _bucket_tags(self, s3: Any, name: str) -> List[dict]:
        try:
            resp = s3.get_bucket_tagging(Bucket=name)
            return resp.get("TagSet", [])
        except ClientError:
            return []

    def _scan_missing_lifecycle(self) -> List[Finding]:
        findings: List[Finding] = []
        s3 = self.session.client("s3", region_name=self.region)
        cw = self.session.client("cloudwatch", region_name=self.region)
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=2)
        try:
            resp = s3.list_buckets()
            for bkt in resp.get("Buckets", []):
                name = bkt.get("Name")
                if not name:
                    continue
                br = self._bucket_region(s3, name)
                if br != self.region:
                    continue
                tags = self._bucket_tags(s3, name)
                if self._tags_excluded(tags):
                    continue
                try:
                    s3.get_bucket_lifecycle_configuration(Bucket=name)
                except ClientError as exc:
                    code = exc.response.get("Error", {}).get("Code", "")
                    if code in ("NoSuchLifecycleConfiguration", "LifecycleConfigurationNotFound"):
                        # Get actual bucket size from CloudWatch
                        size_bytes = self._get_bucket_size_bytes(cw, name, start, end)
                        size_gb = size_bytes / (1024**3) if size_bytes else None

                        if size_gb is not None and size_gb > 100:
                            # Large bucket: estimate 40% savings from tiering to S3-IA
                            current_cost = size_gb * 0.023  # S3 Standard $/GB/month
                            savings = current_cost * 0.40
                            severity = "Medium"
                            description = (
                                f"Bucket ({size_gb:.0f} GB) has no lifecycle policy. "
                                f"Tiering objects >30d to S3-IA saves ~${savings:.2f}/month"
                            )
                        elif size_gb is not None:
                            # Small bucket: flag for hygiene, minimal savings
                            savings = 0.0
                            severity = "Low"
                            description = (
                                f"Bucket ({size_gb:.1f} GB) has no lifecycle policy. "
                                f"Objects accumulate indefinitely."
                            )
                        else:
                            # Size unavailable
                            savings = 0.0
                            severity = "Low"
                            description = (
                                "Bucket has no lifecycle policy. Size unavailable via CloudWatch."
                            )

                        findings.append(
                            Finding(
                                resource_id=name,
                                resource_type="S3",
                                region=self.region,
                                issue_type="missing_lifecycle",
                                description=description,
                                monthly_savings=round(savings, 2),
                                severity=severity,
                                details={
                                    "bucket_name": name,
                                    "size_gb": round(size_gb, 2) if size_gb else None,
                                    "size_source": "cloudwatch" if size_gb else "unavailable",
                                    "estimated_current_monthly_cost": round(size_gb * 0.023, 2) if size_gb else None,
                                    "creation_date": bkt.get("CreationDate").isoformat() if bkt.get("CreationDate") else None,
                                    "tags": tags,
                                },
                            )
                        )
                    else:
                        logger.debug("Lifecycle check skipped for %s: %s", name, exc)
        except ClientError as exc:
            logger.warning("S3 lifecycle scan failed in %s: %s", self.region, exc)
        return findings

    @staticmethod
    def _get_bucket_size_bytes(
        cw: Any,
        bucket: str,
        start: datetime,
        end: datetime,
    ) -> Optional[float]:
        """Get bucket size from CloudWatch BucketSizeBytes metric."""
        try:
            resp = cw.get_metric_statistics(
                Namespace="AWS/S3",
                MetricName="BucketSizeBytes",
                Dimensions=[
                    {"Name": "BucketName", "Value": bucket},
                    {"Name": "StorageType", "Value": "StandardStorage"},
                ],
                StartTime=start,
                EndTime=end,
                Period=86400,
                Statistics=["Average"],
            )
            pts = resp.get("Datapoints") or []
            if not pts:
                return None
            # Return most recent datapoint
            sorted_pts = sorted(pts, key=lambda p: p.get("Timestamp", start))
            return sorted_pts[-1].get("Average")
        except ClientError as exc:
            logger.debug("BucketSizeBytes unavailable for %s: %s", bucket, exc)
            return None

    def _scan_large_buckets_no_tiering(self) -> List[Finding]:
        findings: List[Finding] = []
        s3 = self.session.client("s3", region_name=self.region)
        cw = self.session.client("cloudwatch", region_name=self.region)
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=14)
        try:
            resp = s3.list_buckets()
            for bkt in resp.get("Buckets", []):
                name = bkt.get("Name")
                if not name:
                    continue
                br = self._bucket_region(s3, name)
                if br != self.region:
                    continue
                tags = self._bucket_tags(s3, name)
                if self._tags_excluded(tags):
                    continue
                if self._has_intelligent_tiering(s3, name):
                    continue
                size_bytes = self._avg_bucket_size_bytes(cw, name, start, end)
                if size_bytes is None or size_bytes < _LARGE_BYTES:
                    continue
                gib = size_bytes / (1024**3)
                findings.append(
                    Finding(
                        resource_id=name,
                        resource_type="S3",
                        region=self.region,
                        issue_type="large_bucket_no_tiering",
                        description=(
                            f"Large bucket (~{gib:.0f} GiB avg Standard storage in 14d) "
                            "without Intelligent-Tiering configuration"
                        ),
                        monthly_savings=25.0,
                        severity="Medium",
                        details={"approx_size_gib": round(gib, 1), "tags": tags},
                    )
                )
        except ClientError as exc:
            logger.warning("S3 tiering scan failed in %s: %s", self.region, exc)
        return findings

    @staticmethod
    def _has_intelligent_tiering(s3: Any, bucket: str) -> bool:
        try:
            resp = s3.list_bucket_intelligent_tiering_configurations(Bucket=bucket)
            return bool(resp.get("IntelligentTieringConfigurationList"))
        except ClientError:
            return False

    @staticmethod
    def _avg_bucket_size_bytes(
        cw: Any,
        bucket: str,
        start: datetime,
        end: datetime,
    ) -> Optional[float]:
        try:
            resp = cw.get_metric_statistics(
                Namespace="AWS/S3",
                MetricName="BucketSizeBytes",
                Dimensions=[
                    {"Name": "BucketName", "Value": bucket},
                    {"Name": "StorageType", "Value": "StandardStorage"},
                ],
                StartTime=start,
                EndTime=end,
                Period=86400,
                Statistics=["Average"],
            )
            pts = resp.get("Datapoints") or []
            if not pts:
                return None
            return sum(p["Average"] for p in pts) / len(pts)
        except ClientError as exc:
            logger.debug("BucketSizeBytes unavailable for %s: %s", bucket, exc)
            return None
