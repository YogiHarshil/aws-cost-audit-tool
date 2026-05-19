"""NAT Gateway scanner - detects idle and high-cost NAT Gateways.

NAT Gateways are often the #1 surprise cost on AWS bills:
- $0.045/hour ($32.40/month) fixed cost per gateway
- $0.045/GB data processing fee

Common issues:
- Idle gateways with no traffic (forgot to delete after migration)
- Multiple gateways per AZ when one would suffice
- High data transfer that could use VPC endpoints instead
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from botocore.exceptions import ClientError

from models.finding import Finding
from scanners.base import BaseScanner

logger = logging.getLogger(__name__)

# NAT Gateway pricing (us-east-1 baseline, varies slightly by region)
_HOURLY_COST = 0.045  # $0.045/hour
_DATA_COST_PER_GB = 0.045  # $0.045/GB processed
_HOURS_PER_MONTH = 730.0
_MONTHLY_FIXED_COST = _HOURLY_COST * _HOURS_PER_MONTH  # ~$32.85

# Thresholds
_IDLE_DAYS = 14  # Consider idle if no traffic for 14 days
_HIGH_DATA_GB_MONTHLY = 100  # Flag if >100GB/month (potential VPC endpoint savings)


class NATGatewayScanner(BaseScanner):
    """Detect idle NAT Gateways and high data transfer costs.

    Checks for:
    1. Idle gateways (0 bytes processed in 14 days) - full monthly cost recoverable
    2. High data transfer gateways - recommend VPC endpoints for S3/DynamoDB
    """

    def scan(self) -> List[Finding]:
        """Scan for NAT Gateway cost optimization opportunities."""
        findings: List[Finding] = []
        findings.extend(self._scan_idle_gateways())
        findings.extend(self._scan_high_data_transfer())
        return findings

    def _scan_idle_gateways(self) -> List[Finding]:
        """Find NAT Gateways with zero traffic in the past 14 days."""
        findings: List[Finding] = []
        ec2 = self.session.client("ec2", region_name=self.region)
        cw = self.session.client("cloudwatch", region_name=self.region)

        try:
            response = ec2.describe_nat_gateways(
                Filters=[{"Name": "state", "Values": ["available"]}]
            )
        except ClientError as exc:
            logger.warning("NAT Gateway describe failed in %s: %s", self.region, exc)
            return findings

        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(days=_IDLE_DAYS)

        for nat in response.get("NatGateways", []):
            nat_id = nat.get("NatGatewayId", "")
            tags = nat.get("Tags")

            if self._tags_excluded(tags):
                continue

            # Check bytes out (primary indicator of usage)
            bytes_out = self._get_metric_sum(
                cw, nat_id, "BytesOutToDestination", start_time, end_time
            )
            bytes_in = self._get_metric_sum(
                cw, nat_id, "BytesInFromDestination", start_time, end_time
            )

            total_bytes = (bytes_out or 0) + (bytes_in or 0)

            if total_bytes == 0:
                # Completely idle - full cost recovery
                vpc_id = nat.get("VpcId", "unknown")
                subnet_id = nat.get("SubnetId", "unknown")
                create_time = nat.get("CreateTime")

                age_days = None
                if create_time:
                    age_days = (end_time - create_time).days

                findings.append(
                    Finding(
                        resource_id=nat_id,
                        resource_type="NAT Gateway",
                        region=self.region,
                        issue_type="idle",
                        description=(
                            f"NAT Gateway with 0 bytes processed in {_IDLE_DAYS} days. "
                            f"Fixed cost: ${_MONTHLY_FIXED_COST:.2f}/month"
                        ),
                        monthly_savings=round(_MONTHLY_FIXED_COST, 2),
                        severity="High",
                        details={
                            "vpc_id": vpc_id,
                            "subnet_id": subnet_id,
                            "state": nat.get("State"),
                            "bytes_out_14d": bytes_out or 0,
                            "bytes_in_14d": bytes_in or 0,
                            "age_days": age_days,
                            "hourly_cost": _HOURLY_COST,
                            "tags": tags or [],
                        },
                    )
                )

        return findings

    def _scan_high_data_transfer(self) -> List[Finding]:
        """Find NAT Gateways with high data transfer that could use VPC endpoints."""
        findings: List[Finding] = []
        ec2 = self.session.client("ec2", region_name=self.region)
        cw = self.session.client("cloudwatch", region_name=self.region)

        try:
            response = ec2.describe_nat_gateways(
                Filters=[{"Name": "state", "Values": ["available"]}]
            )
        except ClientError as exc:
            logger.warning("NAT Gateway describe failed in %s: %s", self.region, exc)
            return findings

        # Use 30-day window for data transfer analysis
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(days=30)

        for nat in response.get("NatGateways", []):
            nat_id = nat.get("NatGatewayId", "")
            tags = nat.get("Tags")

            if self._tags_excluded(tags):
                continue

            bytes_out = self._get_metric_sum(
                cw, nat_id, "BytesOutToDestination", start_time, end_time
            )
            bytes_in = self._get_metric_sum(
                cw, nat_id, "BytesInFromDestination", start_time, end_time
            )

            if bytes_out is None and bytes_in is None:
                continue

            total_bytes = (bytes_out or 0) + (bytes_in or 0)
            total_gb = total_bytes / (1024 ** 3)

            # Skip if already flagged as idle or below threshold
            if total_gb < _HIGH_DATA_GB_MONTHLY:
                continue

            # Calculate data transfer cost
            data_cost = total_gb * _DATA_COST_PER_GB
            total_monthly = _MONTHLY_FIXED_COST + data_cost

            # VPC endpoints for S3/DynamoDB are FREE and can save 50-80% of NAT data costs
            # Estimate 60% of traffic could be S3/DynamoDB
            estimated_savings = data_cost * 0.6

            if estimated_savings < 10:  # Not worth flagging if savings < $10
                continue

            findings.append(
                Finding(
                    resource_id=nat_id,
                    resource_type="NAT Gateway",
                    region=self.region,
                    issue_type="high_data_transfer",
                    description=(
                        f"NAT Gateway processed {total_gb:.1f}GB in 30 days. "
                        f"Consider VPC endpoints for S3/DynamoDB to reduce data costs."
                    ),
                    monthly_savings=round(estimated_savings, 2),
                    severity="Medium",
                    details={
                        "vpc_id": nat.get("VpcId", "unknown"),
                        "subnet_id": nat.get("SubnetId", "unknown"),
                        "bytes_out_30d": bytes_out or 0,
                        "bytes_in_30d": bytes_in or 0,
                        "total_gb_30d": round(total_gb, 2),
                        "data_transfer_cost": round(data_cost, 2),
                        "fixed_cost": round(_MONTHLY_FIXED_COST, 2),
                        "total_monthly_cost": round(total_monthly, 2),
                        "recommendation": "Add VPC Gateway Endpoints for S3 and DynamoDB (free)",
                        "tags": tags or [],
                    },
                )
            )

        return findings

    def _get_metric_sum(
        self,
        cw: Any,
        nat_id: str,
        metric_name: str,
        start_time: datetime,
        end_time: datetime,
    ) -> Optional[float]:
        """Get sum of CloudWatch metric for NAT Gateway."""
        try:
            response = cw.get_metric_statistics(
                Namespace="AWS/NATGateway",
                MetricName=metric_name,
                Dimensions=[{"Name": "NatGatewayId", "Value": nat_id}],
                StartTime=start_time,
                EndTime=end_time,
                Period=86400 * 14,  # 14-day period for aggregation
                Statistics=["Sum"],
            )
            datapoints = response.get("Datapoints", [])
            if not datapoints:
                return None
            return sum(dp.get("Sum", 0) for dp in datapoints)
        except ClientError as exc:
            logger.debug("CloudWatch metric %s unavailable for %s: %s", metric_name, nat_id, exc)
            return None
