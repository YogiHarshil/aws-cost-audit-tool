"""Load Balancer scanner - detects idle and orphaned ALB/NLB/CLB.

Load Balancers have minimum monthly costs even with no traffic:
- ALB: ~$16.20/month + LCU charges
- NLB: ~$16.20/month + LCU charges
- CLB: ~$18.00/month + data charges

Common issues:
- Orphaned load balancers after service deletion
- Load balancers with no healthy targets
- Load balancers with zero request count
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from botocore.exceptions import ClientError

from models.finding import Finding
from scanners.base import BaseScanner

logger = logging.getLogger(__name__)

# Load Balancer pricing (us-east-1 baseline)
_ALB_HOURLY = 0.0225  # $0.0225/hour
_NLB_HOURLY = 0.0225  # $0.0225/hour
_CLB_HOURLY = 0.025   # $0.025/hour
_HOURS_PER_MONTH = 730.0

_ALB_MONTHLY = _ALB_HOURLY * _HOURS_PER_MONTH  # ~$16.43
_NLB_MONTHLY = _NLB_HOURLY * _HOURS_PER_MONTH  # ~$16.43
_CLB_MONTHLY = _CLB_HOURLY * _HOURS_PER_MONTH  # ~$18.25

# Thresholds
_IDLE_DAYS = 14  # Consider idle if no requests for 14 days


class LoadBalancerScanner(BaseScanner):
    """Detect idle and orphaned load balancers (ALB, NLB, CLB).

    Checks for:
    1. Load balancers with no healthy targets
    2. Load balancers with zero request count over 14 days
    3. Classic Load Balancers (recommend migration to ALB/NLB)
    """

    def scan(self) -> List[Finding]:
        """Scan for load balancer cost optimization opportunities."""
        findings: List[Finding] = []
        findings.extend(self._scan_application_load_balancers())
        findings.extend(self._scan_network_load_balancers())
        findings.extend(self._scan_classic_load_balancers())
        return findings

    def _scan_application_load_balancers(self) -> List[Finding]:
        """Scan ALBs for idle or orphaned instances."""
        findings: List[Finding] = []
        elbv2 = self.session.client("elbv2", region_name=self.region)
        cw = self.session.client("cloudwatch", region_name=self.region)

        try:
            paginator = elbv2.get_paginator("describe_load_balancers")
            for page in paginator.paginate():
                for lb in page.get("LoadBalancers", []):
                    if lb.get("Type") != "application":
                        continue

                    finding = self._check_elbv2(elbv2, cw, lb, "ALB", _ALB_MONTHLY)
                    if finding:
                        findings.append(finding)

        except ClientError as exc:
            logger.warning("ALB describe failed in %s: %s", self.region, exc)

        return findings

    def _scan_network_load_balancers(self) -> List[Finding]:
        """Scan NLBs for idle or orphaned instances."""
        findings: List[Finding] = []
        elbv2 = self.session.client("elbv2", region_name=self.region)
        cw = self.session.client("cloudwatch", region_name=self.region)

        try:
            paginator = elbv2.get_paginator("describe_load_balancers")
            for page in paginator.paginate():
                for lb in page.get("LoadBalancers", []):
                    if lb.get("Type") != "network":
                        continue

                    finding = self._check_elbv2(elbv2, cw, lb, "NLB", _NLB_MONTHLY)
                    if finding:
                        findings.append(finding)

        except ClientError as exc:
            logger.warning("NLB describe failed in %s: %s", self.region, exc)

        return findings

    def _scan_classic_load_balancers(self) -> List[Finding]:
        """Scan Classic Load Balancers (ELB) for idle instances."""
        findings: List[Finding] = []
        elb = self.session.client("elb", region_name=self.region)
        cw = self.session.client("cloudwatch", region_name=self.region)

        try:
            response = elb.describe_load_balancers()
        except ClientError as exc:
            logger.warning("CLB describe failed in %s: %s", self.region, exc)
            return findings

        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(days=_IDLE_DAYS)

        for lb in response.get("LoadBalancerDescriptions", []):
            lb_name = lb.get("LoadBalancerName", "")

            # Get tags for exclusion check
            try:
                tag_resp = elb.describe_tags(LoadBalancerNames=[lb_name])
                tags = []
                for desc in tag_resp.get("TagDescriptions", []):
                    tags.extend(desc.get("Tags", []))
                if self._tags_excluded(tags):
                    continue
            except ClientError:
                tags = []

            # Check if CLB has any registered instances
            instances = lb.get("Instances", [])
            if not instances:
                findings.append(
                    Finding(
                        resource_id=lb_name,
                        resource_type="Classic Load Balancer",
                        region=self.region,
                        issue_type="no_targets",
                        description=(
                            f"Classic Load Balancer has no registered instances. "
                            f"Fixed cost: ${_CLB_MONTHLY:.2f}/month"
                        ),
                        monthly_savings=round(_CLB_MONTHLY, 2),
                        severity="High",
                        details={
                            "dns_name": lb.get("DNSName"),
                            "vpc_id": lb.get("VPCId"),
                            "created_time": str(lb.get("CreatedTime")),
                            "scheme": lb.get("Scheme"),
                            "recommendation": "Delete unused CLB or migrate to ALB/NLB",
                            "tags": tags,
                        },
                    )
                )
                continue

            # Check request count
            request_count = self._get_clb_request_count(cw, lb_name, start_time, end_time)
            if request_count == 0:
                findings.append(
                    Finding(
                        resource_id=lb_name,
                        resource_type="Classic Load Balancer",
                        region=self.region,
                        issue_type="idle",
                        description=(
                            f"Classic Load Balancer with 0 requests in {_IDLE_DAYS} days. "
                            f"Consider migration to ALB (cheaper, more features)"
                        ),
                        monthly_savings=round(_CLB_MONTHLY, 2),
                        severity="Medium",
                        details={
                            "dns_name": lb.get("DNSName"),
                            "vpc_id": lb.get("VPCId"),
                            "instance_count": len(instances),
                            "request_count_14d": request_count,
                            "recommendation": "Delete or migrate to ALB",
                            "tags": tags,
                        },
                    )
                )

        return findings

    def _check_elbv2(
        self,
        elbv2: Any,
        cw: Any,
        lb: Dict[str, Any],
        lb_type: str,
        monthly_cost: float,
    ) -> Optional[Finding]:
        """Check ALB/NLB for idle status or no healthy targets."""
        lb_arn = lb.get("LoadBalancerArn", "")
        lb_name = lb.get("LoadBalancerName", "")

        # Extract the ARN suffix for CloudWatch (app/name/id or net/name/id)
        arn_suffix = self._get_lb_arn_suffix(lb_arn)

        # Get tags for exclusion check
        try:
            tag_resp = elbv2.describe_tags(ResourceArns=[lb_arn])
            tags = []
            for desc in tag_resp.get("TagDescriptions", []):
                tags.extend(desc.get("Tags", []))
            if self._tags_excluded(tags):
                return None
        except ClientError:
            tags = []

        # Check target groups for healthy targets
        try:
            tg_resp = elbv2.describe_target_groups(LoadBalancerArn=lb_arn)
            target_groups = tg_resp.get("TargetGroups", [])
        except ClientError as exc:
            logger.debug("Target group describe failed for %s: %s", lb_name, exc)
            target_groups = []

        has_healthy_targets = False
        total_targets = 0

        for tg in target_groups:
            tg_arn = tg.get("TargetGroupArn", "")
            try:
                health_resp = elbv2.describe_target_health(TargetGroupArn=tg_arn)
                targets = health_resp.get("TargetHealthDescriptions", [])
                total_targets += len(targets)
                for target in targets:
                    if target.get("TargetHealth", {}).get("State") == "healthy":
                        has_healthy_targets = True
                        break
            except ClientError:
                pass

        # No targets at all - orphaned load balancer
        if total_targets == 0:
            return Finding(
                resource_id=lb_name,
                resource_type=lb_type,
                region=self.region,
                issue_type="no_targets",
                description=(
                    f"{lb_type} has no registered targets. "
                    f"Fixed cost: ${monthly_cost:.2f}/month"
                ),
                monthly_savings=round(monthly_cost, 2),
                severity="High",
                details={
                    "arn": lb_arn,
                    "dns_name": lb.get("DNSName"),
                    "vpc_id": lb.get("VpcId"),
                    "state": lb.get("State", {}).get("Code"),
                    "created_time": str(lb.get("CreatedTime")),
                    "target_group_count": len(target_groups),
                    "total_targets": 0,
                    "tags": tags,
                },
            )

        # Has targets but none healthy
        if not has_healthy_targets:
            return Finding(
                resource_id=lb_name,
                resource_type=lb_type,
                region=self.region,
                issue_type="no_healthy_targets",
                description=(
                    f"{lb_type} has {total_targets} targets but none are healthy. "
                    f"Traffic cannot be served."
                ),
                monthly_savings=round(monthly_cost, 2),
                severity="High",
                details={
                    "arn": lb_arn,
                    "dns_name": lb.get("DNSName"),
                    "vpc_id": lb.get("VpcId"),
                    "total_targets": total_targets,
                    "healthy_targets": 0,
                    "target_group_count": len(target_groups),
                    "tags": tags,
                },
            )

        # Check request count for ALB (NLB doesn't have RequestCount metric)
        if lb_type == "ALB" and arn_suffix:
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(days=_IDLE_DAYS)
            request_count = self._get_alb_request_count(cw, arn_suffix, start_time, end_time)

            if request_count == 0:
                return Finding(
                    resource_id=lb_name,
                    resource_type=lb_type,
                    region=self.region,
                    issue_type="idle",
                    description=(
                        f"{lb_type} with 0 requests in {_IDLE_DAYS} days but has healthy targets. "
                        f"Verify if still needed."
                    ),
                    monthly_savings=round(monthly_cost * 0.8, 2),  # 80% savings (might still need)
                    severity="Medium",
                    details={
                        "arn": lb_arn,
                        "dns_name": lb.get("DNSName"),
                        "request_count_14d": request_count,
                        "total_targets": total_targets,
                        "has_healthy_targets": has_healthy_targets,
                        "tags": tags,
                    },
                )

        return None

    def _get_lb_arn_suffix(self, arn: str) -> Optional[str]:
        """Extract ARN suffix for CloudWatch dimension (app/name/id or net/name/id)."""
        # ARN format: arn:aws:elasticloadbalancing:region:account:loadbalancer/app/name/id
        if "/loadbalancer/" in arn:
            parts = arn.split("/loadbalancer/")
            if len(parts) == 2:
                return parts[1]
        return None

    def _get_alb_request_count(
        self,
        cw: Any,
        arn_suffix: str,
        start_time: datetime,
        end_time: datetime,
    ) -> int:
        """Get total request count for ALB over time period."""
        try:
            response = cw.get_metric_statistics(
                Namespace="AWS/ApplicationELB",
                MetricName="RequestCount",
                Dimensions=[{"Name": "LoadBalancer", "Value": arn_suffix}],
                StartTime=start_time,
                EndTime=end_time,
                Period=86400 * _IDLE_DAYS,
                Statistics=["Sum"],
            )
            datapoints = response.get("Datapoints", [])
            return int(sum(dp.get("Sum", 0) for dp in datapoints))
        except ClientError as exc:
            logger.debug("ALB RequestCount metric unavailable: %s", exc)
            return -1  # Unknown, don't flag

    def _get_clb_request_count(
        self,
        cw: Any,
        lb_name: str,
        start_time: datetime,
        end_time: datetime,
    ) -> int:
        """Get total request count for Classic Load Balancer."""
        try:
            response = cw.get_metric_statistics(
                Namespace="AWS/ELB",
                MetricName="RequestCount",
                Dimensions=[{"Name": "LoadBalancerName", "Value": lb_name}],
                StartTime=start_time,
                EndTime=end_time,
                Period=86400 * _IDLE_DAYS,
                Statistics=["Sum"],
            )
            datapoints = response.get("Datapoints", [])
            return int(sum(dp.get("Sum", 0) for dp in datapoints))
        except ClientError as exc:
            logger.debug("CLB RequestCount metric unavailable: %s", exc)
            return -1
