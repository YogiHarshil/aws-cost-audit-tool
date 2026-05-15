"""Reserved Instance coverage scanner (on-demand instances without RI coverage)."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Set, Tuple

from botocore.exceptions import ClientError

from models.finding import Finding
from utils.aws_client import discover_regions
from utils.pricing import get_ec2_instance_price, PricingCache

logger = logging.getLogger(__name__)

_HOURS_PER_MONTH = 730.0
_MIN_RUNNING_DAYS = 30  # Only flag instances running 30+ days
_MIN_INSTANCE_COUNT = 2  # Only recommend RIs for 2+ instances of same type
_RI_SAVINGS_FACTOR = 0.37  # 1-year no-upfront RI is ~37% cheaper than on-demand


class ReservationScanner:
    """Detect on-demand EC2 instances without Reserved Instance coverage.

    This scanner runs ONCE globally (not per-region) and identifies opportunities
    to purchase Reserved Instances for stable workloads.
    """

    def __init__(
        self,
        session: Any,
        pricing_client: Any,
        pricing_cache: PricingCache,
    ) -> None:
        self.session = session
        self.pricing_client = pricing_client
        self.pricing_cache = pricing_cache

    def scan(self) -> List[Finding]:
        """Scan all regions for RI coverage opportunities."""
        findings: List[Finding] = []

        try:
            # Step 1: Get all active Reserved Instances (region-scoped, so check all regions)
            covered = self._get_ri_coverage()

            # Step 2: Get all running on-demand instances across all regions
            running_ondemand = self._get_running_ondemand_instances()

            # Step 3: Find uncovered instances that could benefit from RIs
            findings = self._find_ri_opportunities(covered, running_ondemand)

        except ClientError as exc:
            logger.warning("Reservation scan failed: %s", exc)

        return findings

    def _get_ri_coverage(self) -> Dict[str, int]:
        """Get count of active RIs by instance type (regional scope).

        Returns dict: {instance_type: covered_count}
        """
        covered: Dict[str, int] = defaultdict(int)

        # RIs can be regional or AZ-specific; we aggregate by instance type
        regions = discover_regions(self.session)

        for region in regions:
            try:
                ec2 = self.session.client("ec2", region_name=region)
                resp = ec2.describe_reserved_instances(
                    Filters=[{"Name": "state", "Values": ["active"]}]
                )
                for ri in resp.get("ReservedInstances", []):
                    instance_type = ri.get("InstanceType", "")
                    count = ri.get("InstanceCount", 0)
                    if instance_type and count:
                        covered[instance_type] += count
            except ClientError as exc:
                logger.debug("RI lookup failed in %s: %s", region, exc)

        return dict(covered)

    def _get_running_ondemand_instances(self) -> Dict[str, Dict[str, Any]]:
        """Get on-demand instances running 30+ days, grouped by instance type.

        Returns dict: {instance_type: {"count": N, "regions": {region: count}, "sample_ids": [...]}}
        """
        running: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "regions": defaultdict(int), "sample_ids": []}
        )

        threshold = datetime.now(timezone.utc) - timedelta(days=_MIN_RUNNING_DAYS)
        regions = discover_regions(self.session)

        for region in regions:
            try:
                ec2 = self.session.client("ec2", region_name=region)
                paginator = ec2.get_paginator("describe_instances")
                for page in paginator.paginate(
                    Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
                ):
                    for reservation in page.get("Reservations", []):
                        for inst in reservation.get("Instances", []):
                            # Skip Spot instances (they have SpotInstanceRequestId)
                            if inst.get("SpotInstanceRequestId"):
                                continue

                            # Check if running 30+ days
                            launch_time = inst.get("LaunchTime")
                            if not launch_time or launch_time > threshold:
                                continue

                            instance_type = inst.get("InstanceType", "")
                            instance_id = inst.get("InstanceId", "")
                            if not instance_type:
                                continue

                            running[instance_type]["count"] += 1
                            running[instance_type]["regions"][region] += 1
                            if len(running[instance_type]["sample_ids"]) < 5:
                                running[instance_type]["sample_ids"].append(instance_id)

            except ClientError as exc:
                logger.debug("Instance lookup failed in %s: %s", region, exc)

        return dict(running)

    def _find_ri_opportunities(
        self,
        covered: Dict[str, int],
        running_ondemand: Dict[str, Dict[str, Any]],
    ) -> List[Finding]:
        """Find instance types that would benefit from RI purchases."""
        findings: List[Finding] = []

        for instance_type, data in running_ondemand.items():
            ondemand_count = data["count"]
            covered_count = covered.get(instance_type, 0)
            uncovered = ondemand_count - covered_count

            # Only recommend RIs for stable workloads (2+ instances of same type)
            if uncovered < _MIN_INSTANCE_COUNT:
                continue

            # Get on-demand pricing (use us-east-1 as baseline)
            try:
                hourly_ondemand = get_ec2_instance_price(
                    self.pricing_client,
                    self.pricing_cache,
                    instance_type,
                    "us-east-1",
                )
            except Exception as exc:
                logger.debug("Pricing failed for %s: %s", instance_type, exc)
                continue

            if hourly_ondemand <= 0:
                continue

            # Calculate potential savings with 1-year no-upfront RI
            hourly_ri = hourly_ondemand * (1 - _RI_SAVINGS_FACTOR)
            monthly_savings_per_instance = (hourly_ondemand - hourly_ri) * _HOURS_PER_MONTH
            total_monthly_savings = monthly_savings_per_instance * uncovered

            # Skip if savings are trivial
            if total_monthly_savings < 10:
                continue

            # Determine severity based on savings
            if total_monthly_savings >= 200:
                severity = "High"
            elif total_monthly_savings >= 50:
                severity = "Medium"
            else:
                severity = "Low"

            findings.append(
                Finding(
                    resource_id=f"ri-opportunity-{instance_type}",
                    resource_type="Reserved Instance",
                    region="global",
                    issue_type="ri_opportunity",
                    description=(
                        f"{uncovered}x {instance_type} running on-demand for 30+ days "
                        f"without RI coverage. 1-year no-upfront RI saves 37%."
                    ),
                    monthly_savings=round(total_monthly_savings, 2),
                    severity=severity,
                    details={
                        "instance_type": instance_type,
                        "ondemand_count": ondemand_count,
                        "covered_by_ri": covered_count,
                        "uncovered_count": uncovered,
                        "hourly_ondemand_rate": round(hourly_ondemand, 4),
                        "estimated_ri_rate": round(hourly_ri, 4),
                        "savings_per_instance_monthly": round(monthly_savings_per_instance, 2),
                        "regions": dict(data["regions"]),
                        "sample_instance_ids": data["sample_ids"],
                    },
                )
            )

        # Sort by savings descending
        findings.sort(key=lambda f: f.monthly_savings, reverse=True)
        return findings
