"""Elastic IP scanner (unassociated addresses)."""

from __future__ import annotations

import logging
from typing import List

from botocore.exceptions import ClientError

from models.finding import Finding
from scanners.base import BaseScanner

logger = logging.getLogger(__name__)

_EIP_MONTHLY_USD = 3.60


class EIPScanner(BaseScanner):
    """Detect Elastic IPs that are not associated with a running resource."""

    def scan(self) -> List[Finding]:
        return self._scan_unassociated_ips()

    def _scan_unassociated_ips(self) -> List[Finding]:
        findings: List[Finding] = []
        ec2 = self.session.client("ec2", region_name=self.region)
        try:
            # describe_addresses is not a boto3 paginator; use API pagination via NextToken when present.
            next_token: str | None = None
            while True:
                kwargs: dict = {}
                if next_token:
                    kwargs["NextToken"] = next_token
                page = ec2.describe_addresses(**kwargs)
                for addr in page.get("Addresses", []):
                    if addr.get("AssociationId"):
                        continue
                    tags = addr.get("Tags")
                    if self._tags_excluded(tags):
                        continue
                    eip = addr.get("AllocationId") or addr.get("PublicIp", "unknown")
                    findings.append(
                        Finding(
                            resource_id=str(eip),
                            resource_type="EIP",
                            region=self.region,
                            issue_type="unassociated",
                            description="Elastic IP allocated but not associated",
                            monthly_savings=round(_EIP_MONTHLY_USD, 2),
                            severity="Medium",
                            details={
                                "public_ip": addr.get("PublicIp"),
                                "domain": addr.get("Domain", "vpc"),
                                "tags": tags or [],
                            },
                        )
                    )
                raw_next = page.get("NextToken")
                if isinstance(raw_next, str) and raw_next.strip():
                    next_token = raw_next
                else:
                    break
        except ClientError as exc:
            logger.warning("EIP scan failed in %s: %s", self.region, exc)
        return findings
