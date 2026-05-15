"""EC2 instance scanner (stopped >7d, low CPU utilization)."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from botocore.exceptions import ClientError

from models.finding import Finding
from scanners.base import BaseScanner
from utils.pricing import get_ebs_volume_price, get_ec2_instance_price

logger = logging.getLogger(__name__)

_STOP_DATE_RE = re.compile(r"\((\d{4}-\d{2}-\d{2})")
_HOURS_PER_MONTH = 730.0
_CPU_LOW_PCT = 5.0
_STOPPED_MIN_DAYS = 7


def _days_since_embedded_date(reason: Optional[str]) -> Optional[float]:
    """Parse first YYYY-MM-DD inside EC2 ``StateTransitionReason`` / similar."""
    if not reason:
        return None
    m = _STOP_DATE_RE.search(reason)
    if not m:
        return None
    try:
        day = datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    now = datetime.now(timezone.utc)
    return (now - day).total_seconds() / 86400.0


class EC2Scanner(BaseScanner):
    """Detect costly EC2 usage patterns."""

    def scan(self) -> List[Finding]:
        return self._scan_stopped_instances() + self._scan_low_utilization_instances()

    def _scan_stopped_instances(self) -> List[Finding]:
        findings: List[Finding] = []
        ec2 = self.session.client("ec2", region_name=self.region)
        try:
            paginator = ec2.get_paginator("describe_instances")
            for page in paginator.paginate(
                Filters=[{"Name": "instance-state-name", "Values": ["stopped"]}]
            ):
                for reservation in page.get("Reservations", []):
                    for inst in reservation.get("Instances", []):
                        tags = inst.get("Tags")
                        if self._tags_excluded(tags):
                            continue
                        reason = inst.get("StateTransitionReason", "")
                        days = _days_since_embedded_date(reason)
                        if days is None or days < _STOPPED_MIN_DAYS:
                            continue
                        iid = inst.get("InstanceId", "")
                        itype = inst.get("InstanceType", "t3.micro")

                        # Calculate actual EBS storage cost (not compute cost)
                        attached_volumes = self._get_attached_volume_costs(ec2, inst)
                        ebs_monthly = sum(v["monthly_cost"] for v in attached_volumes)

                        # Compute cost is informational only (what it WOULD cost if started)
                        hourly = self._hourly_price(itype)
                        compute_monthly = hourly * _HOURS_PER_MONTH

                        # Savings = EBS cost only (stopped instances have zero compute cost)
                        sev = "High" if ebs_monthly >= 50 else "Medium" if ebs_monthly >= 10 else "Low"
                        findings.append(
                            Finding(
                                resource_id=iid,
                                resource_type="EC2",
                                region=self.region,
                                issue_type="stopped",
                                description=(
                                    f"Instance stopped ~{int(days)}d (>{_STOPPED_MIN_DAYS}d); "
                                    f"no compute charges; attached EBS volumes cost ${ebs_monthly:.2f}/month"
                                ),
                                monthly_savings=round(ebs_monthly, 2),
                                severity=sev,
                                details={
                                    "instance_type": itype,
                                    "state_transition_reason": reason,
                                    "days_stopped": round(days, 1),
                                    "attached_volumes": attached_volumes,
                                    "compute_cost_when_running": round(compute_monthly, 2),
                                    "tags": tags or [],
                                },
                            )
                        )
        except ClientError as exc:
            logger.warning("EC2 stopped scan failed in %s: %s", self.region, exc)
        return findings

    def _get_attached_volume_costs(
        self, ec2: Any, instance: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Get EBS volume details and costs for all attached volumes."""
        volumes: List[Dict[str, Any]] = []
        block_mappings = instance.get("BlockDeviceMappings", [])
        if not block_mappings:
            return volumes

        volume_ids = [
            m["Ebs"]["VolumeId"]
            for m in block_mappings
            if m.get("Ebs", {}).get("VolumeId")
        ]
        if not volume_ids:
            return volumes

        try:
            resp = ec2.describe_volumes(VolumeIds=volume_ids)
            for vol in resp.get("Volumes", []):
                vol_id = vol.get("VolumeId", "")
                vol_type = vol.get("VolumeType", "gp3")
                size_gb = int(vol.get("Size", 0))
                try:
                    gb_month_price = get_ebs_volume_price(
                        self.pricing_client,
                        self.pricing_cache,
                        vol_type,
                        self.region,
                    )
                except Exception as exc:
                    logger.warning("EBS pricing failed for %s: %s", vol_id, exc)
                    gb_month_price = 0.0
                monthly_cost = size_gb * gb_month_price
                volumes.append({
                    "volume_id": vol_id,
                    "volume_type": vol_type,
                    "size_gb": size_gb,
                    "monthly_cost": round(monthly_cost, 2),
                })
        except ClientError as exc:
            logger.warning("describe_volumes failed: %s", exc)
        return volumes

    def _hourly_price(self, instance_type: str) -> float:
        try:
            return get_ec2_instance_price(
                self.pricing_client,
                self.pricing_cache,
                instance_type,
                self.region,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("EC2 pricing failed for %s: %s", instance_type, exc)
            return 0.0

    def _scan_low_utilization_instances(self) -> List[Finding]:
        findings: List[Finding] = []
        ec2 = self.session.client("ec2", region_name=self.region)
        cw = self.session.client("cloudwatch", region_name=self.region)
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=14)
        try:
            paginator = ec2.get_paginator("describe_instances")
            for page in paginator.paginate(
                Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
            ):
                for reservation in page.get("Reservations", []):
                    for inst in reservation.get("Instances", []):
                        tags = inst.get("Tags")
                        if self._tags_excluded(tags):
                            continue
                        iid = inst.get("InstanceId", "")
                        itype = inst.get("InstanceType", "t3.micro")
                        avg_cpu = self._avg_cpu_utilization(cw, iid, start, end)
                        if avg_cpu is None:
                            continue
                        if avg_cpu >= _CPU_LOW_PCT:
                            continue
                        hourly = self._hourly_price(itype)
                        monthly = hourly * _HOURS_PER_MONTH
                        sev = "Medium" if monthly >= 50 else "Low"
                        findings.append(
                            Finding(
                                resource_id=iid,
                                resource_type="EC2",
                                region=self.region,
                                issue_type="low_utilization",
                                description=(
                                    f"Average CPU {avg_cpu:.1f}% over 14d (<{_CPU_LOW_PCT}%); "
                                    "consider rightsizing or stopping non-prod"
                                ),
                                monthly_savings=round(monthly * 0.5, 2),
                                severity=sev,
                                details={
                                    "instance_type": itype,
                                    "avg_cpu_14d": round(avg_cpu, 2),
                                    "tags": tags or [],
                                },
                            )
                        )
        except ClientError as exc:
            logger.warning("EC2 utilization scan failed in %s: %s", self.region, exc)
        return findings

    @staticmethod
    def _avg_cpu_utilization(
        cw: Any,
        instance_id: str,
        start: datetime,
        end: datetime,
    ) -> Optional[float]:
        try:
            resp = cw.get_metric_statistics(
                Namespace="AWS/EC2",
                MetricName="CPUUtilization",
                Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
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
            logger.debug("CPU metric unavailable for %s: %s", instance_id, exc)
            return None
