"""EBS snapshot scanner (orphaned snapshots with no volume or AMI)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Set

from botocore.exceptions import ClientError

from models.finding import Finding
from scanners.base import BaseScanner

logger = logging.getLogger(__name__)

_SNAPSHOT_PRICE_PER_GB_MONTH = 0.05  # $0.05/GB/month for EBS snapshots
_MIN_ORPHAN_AGE_DAYS = 30  # Only flag snapshots older than 30 days


class SnapshotScanner(BaseScanner):
    """Detect orphaned EBS snapshots (no associated volume or AMI)."""

    def scan(self) -> List[Finding]:
        return self._scan_orphaned_snapshots()

    def _scan_orphaned_snapshots(self) -> List[Finding]:
        findings: List[Finding] = []
        ec2 = self.session.client("ec2", region_name=self.region)

        try:
            # Step 1: Get all existing volume IDs in this region
            existing_volume_ids = self._get_existing_volume_ids(ec2)

            # Step 2: Get all snapshot IDs that back AMIs (do NOT flag these)
            ami_snapshot_ids = self._get_ami_snapshot_ids(ec2)

            # Step 3: Scan all snapshots owned by this account
            paginator = ec2.get_paginator("describe_snapshots")
            for page in paginator.paginate(OwnerIds=["self"]):
                for snap in page.get("Snapshots", []):
                    finding = self._evaluate_snapshot(
                        snap, existing_volume_ids, ami_snapshot_ids
                    )
                    if finding:
                        findings.append(finding)

        except ClientError as exc:
            logger.warning("Snapshot scan failed in %s: %s", self.region, exc)

        return findings

    def _get_existing_volume_ids(self, ec2: Any) -> Set[str]:
        """Get all current volume IDs in this region."""
        volume_ids: Set[str] = set()
        try:
            paginator = ec2.get_paginator("describe_volumes")
            for page in paginator.paginate():
                for vol in page.get("Volumes", []):
                    vol_id = vol.get("VolumeId")
                    if vol_id:
                        volume_ids.add(vol_id)
        except ClientError as exc:
            logger.warning("describe_volumes failed in %s: %s", self.region, exc)
        return volume_ids

    def _get_ami_snapshot_ids(self, ec2: Any) -> Set[str]:
        """Get all snapshot IDs that back AMIs (should not be deleted)."""
        ami_snapshot_ids: Set[str] = set()
        try:
            paginator = ec2.get_paginator("describe_images")
            for page in paginator.paginate(Owners=["self"]):
                for image in page.get("Images", []):
                    for mapping in image.get("BlockDeviceMappings", []):
                        snap_id = mapping.get("Ebs", {}).get("SnapshotId")
                        if snap_id:
                            ami_snapshot_ids.add(snap_id)
        except ClientError as exc:
            logger.warning("describe_images failed in %s: %s", self.region, exc)
        return ami_snapshot_ids

    def _evaluate_snapshot(
        self,
        snap: Dict[str, Any],
        existing_volume_ids: Set[str],
        ami_snapshot_ids: Set[str],
    ) -> Finding | None:
        """Evaluate a single snapshot and return Finding if orphaned."""
        snap_id = snap.get("SnapshotId", "")
        volume_id = snap.get("VolumeId", "")
        start_time = snap.get("StartTime")
        size_gb = int(snap.get("VolumeSize", 0))
        tags = snap.get("Tags")

        # Skip if this snapshot backs an AMI
        if snap_id in ami_snapshot_ids:
            return None

        # Skip if source volume still exists
        if volume_id in existing_volume_ids:
            return None

        # Skip special volume IDs (created from other sources)
        if volume_id in ("vol-ffffffff", ""):
            return None

        # Skip if excluded by tags
        if self._tags_excluded(tags):
            return None

        # Calculate age
        if not start_time:
            return None
        age_days = (datetime.now(timezone.utc) - start_time).days

        # Only flag snapshots older than threshold
        if age_days < _MIN_ORPHAN_AGE_DAYS:
            return None

        # Calculate monthly cost
        monthly_cost = size_gb * _SNAPSHOT_PRICE_PER_GB_MONTH

        # Determine severity based on size
        if size_gb > 200:
            severity = "High"
        elif size_gb > 50:
            severity = "Medium"
        else:
            severity = "Low"

        # Get name from tags
        name = ""
        if tags:
            for t in tags:
                if t.get("Key") == "Name":
                    name = t.get("Value", "")
                    break

        return Finding(
            resource_id=snap_id,
            resource_type="EBS Snapshot",
            region=self.region,
            issue_type="orphaned_snapshot",
            description=(
                f"Snapshot ({size_gb} GB, {age_days}d old) has no associated volume or AMI. "
                f"Source volume {volume_id} no longer exists."
            ),
            monthly_savings=round(monthly_cost, 2),
            severity=severity,
            details={
                "snapshot_id": snap_id,
                "volume_id": volume_id,
                "size_gb": size_gb,
                "age_days": age_days,
                "start_time": start_time.isoformat() if start_time else None,
                "description": snap.get("Description", ""),
                "encrypted": snap.get("Encrypted", False),
                "name": name,
                "tags": tags or [],
            },
        )
