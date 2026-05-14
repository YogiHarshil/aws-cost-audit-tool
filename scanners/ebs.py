"""EBS volume scanner (unattached volumes)."""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from botocore.exceptions import ClientError

from models.finding import Finding
from scanners.base import BaseScanner
from utils.pricing import get_ebs_volume_price

logger = logging.getLogger(__name__)


class EBSScanner(BaseScanner):
    """Detect EBS volumes in ``available`` state (unattached)."""

    def scan(self) -> List[Finding]:
        return self._scan_unattached_volumes()

    def _scan_unattached_volumes(self) -> List[Finding]:
        findings: List[Finding] = []
        ec2 = self.session.client("ec2", region_name=self.region)
        try:
            paginator = ec2.get_paginator("describe_volumes")
            for page in paginator.paginate(
                Filters=[{"Name": "status", "Values": ["available"]}]
            ):
                for vol in page.get("Volumes", []):
                    tags = vol.get("Tags")
                    if self._tags_excluded(tags):
                        continue
                    findings.extend(self._finding_for_volume(vol))
        except ClientError as exc:
            logger.warning("EBS scan failed in %s: %s", self.region, exc)
        return findings

    def _finding_for_volume(self, vol: dict) -> List[Finding]:
        vid = vol.get("VolumeId", "")
        size_gib = int(vol.get("Size", 0))
        vtype = vol.get("VolumeType", "gp3")
        tags = vol.get("Tags")
        try:
            gb_month = get_ebs_volume_price(
                self.pricing_client,
                self.pricing_cache,
                vtype,
                self.region,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("EBS pricing lookup failed for %s: %s", vid, exc)
            gb_month = 0.0
        monthly = size_gib * gb_month
        sev = "High" if monthly >= 50 else "Medium" if monthly >= 10 else "Low"
        return [
            Finding(
                resource_id=vid,
                resource_type="EBS",
                region=self.region,
                issue_type="unattached",
                description=f"Unattached {vtype} volume ({size_gib} GiB) in available state",
                monthly_savings=round(monthly, 2),
                severity=sev,
                details={
                    "volume_type": vtype,
                    "size_gib": size_gib,
                    "encrypted": vol.get("Encrypted", False),
                    "tags": tags or [],
                },
            )
        ]
