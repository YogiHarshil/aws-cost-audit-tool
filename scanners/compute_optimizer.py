"""AWS Compute Optimizer scanner for EC2 rightsizing recommendations.

Retrieves ML-based rightsizing recommendations from AWS Compute Optimizer.
Requires opt-in and 14+ days of CloudWatch data.

See: https://docs.aws.amazon.com/compute-optimizer/latest/ug/requirements.html
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from botocore.exceptions import ClientError

from models.finding import Finding

logger = logging.getLogger(__name__)

# Only recommend instances with low performance risk (0-2 scale, out of 0-4)
_MAX_PERFORMANCE_RISK = 2.0
# Minimum monthly savings to create a finding
_MIN_MONTHLY_SAVINGS = 10.0


def scan_compute_optimizer(session: Any) -> List[Finding]:
    """Scan AWS Compute Optimizer for EC2 rightsizing recommendations.

    Args:
        session: boto3 Session object.

    Returns:
        List of findings for over-provisioned instances.
        Returns empty list if Compute Optimizer is not enabled or not accessible.
    """
    findings: List[Finding] = []

    try:
        client = session.client("compute-optimizer", region_name="us-east-1")
    except Exception as exc:
        logger.warning("Failed to create Compute Optimizer client: %s", exc)
        return findings

    # Step 1: Check if Compute Optimizer is opted in
    if not _is_opted_in(client):
        return findings

    # Step 2: Get EC2 recommendations
    try:
        recommendations = _get_all_recommendations(client)
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code in ("AccessDeniedException", "OptInRequiredException"):
            logger.info("Compute Optimizer access denied: %s", error_code)
            return findings
        logger.warning("get_ec2_instance_recommendations failed: %s", exc)
        return findings
    except Exception as exc:
        logger.warning("Unexpected error getting recommendations: %s", exc)
        return findings

    # Step 3: Convert to findings
    for rec in recommendations:
        finding = _recommendation_to_finding(rec)
        if finding:
            findings.append(finding)

    return findings


def _is_opted_in(client: Any) -> bool:
    """Check if Compute Optimizer is enabled for this account."""
    try:
        response = client.get_enrollment_status()
        status = response.get("status", "")
        if status != "Active":
            logger.info(
                "Compute Optimizer status is '%s' (not Active) - skipping",
                status,
            )
            return False
        return True
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code in ("AccessDeniedException", "OptInRequiredException"):
            logger.info("Compute Optimizer not available: %s", error_code)
            return False
        logger.warning("get_enrollment_status failed: %s", exc)
        return False
    except Exception as exc:
        logger.warning("Unexpected error checking enrollment status: %s", exc)
        return False


def _get_all_recommendations(client: Any) -> List[Dict[str, Any]]:
    """Get all EC2 instance recommendations using pagination."""
    recommendations: List[Dict[str, Any]] = []
    next_token: Optional[str] = None

    while True:
        kwargs: Dict[str, Any] = {"maxResults": 100}
        if next_token:
            kwargs["nextToken"] = next_token

        response = client.get_ec2_instance_recommendations(**kwargs)
        recs = response.get("instanceRecommendations", [])
        recommendations.extend(recs)

        next_token = response.get("nextToken")
        if not next_token:
            break

    return recommendations


def _recommendation_to_finding(rec: Dict[str, Any]) -> Optional[Finding]:
    """Convert a Compute Optimizer recommendation to a Finding.

    Only creates findings for OVER_PROVISIONED instances with low risk.
    """
    finding_type = rec.get("finding", "")

    # Only process over-provisioned instances (downsizing opportunities)
    if finding_type != "Overprovisioned":
        return None

    # Get instance info
    instance_arn = rec.get("instanceArn", "")
    if not instance_arn:
        return None

    # Parse ARN: arn:aws:ec2:region:account:instance/instance-id
    arn_parts = instance_arn.split(":")
    if len(arn_parts) < 6:
        return None

    region = arn_parts[3]
    instance_id = instance_arn.split("/")[-1] if "/" in instance_arn else ""
    if not instance_id:
        return None

    current_type = rec.get("currentInstanceType", "unknown")

    # Get recommendation options
    options = rec.get("recommendationOptions", [])
    if not options:
        return None

    # Use the top recommendation (rank 1)
    top_option = options[0]
    recommended_type = top_option.get("instanceType", "")
    if not recommended_type:
        return None

    # Check performance risk
    performance_risk = top_option.get("performanceRisk", 5.0)
    if performance_risk > _MAX_PERFORMANCE_RISK:
        logger.debug(
            "Skipping %s: performance risk %.1f > threshold %.1f",
            instance_id,
            performance_risk,
            _MAX_PERFORMANCE_RISK,
        )
        return None

    # Get savings from Compute Optimizer's estimate
    savings_opportunity = top_option.get("savingsOpportunity", {})
    estimated_savings = savings_opportunity.get("estimatedMonthlySavings", {})
    monthly_savings = estimated_savings.get("value", 0.0)

    # Also try the after-discounts savings if available
    savings_after_discounts = top_option.get("savingsOpportunityAfterDiscounts", {})
    if savings_after_discounts:
        after_discount_savings = savings_after_discounts.get("estimatedMonthlySavings", {})
        discounted_value = after_discount_savings.get("value", 0.0)
        if discounted_value > 0:
            monthly_savings = discounted_value

    if monthly_savings < _MIN_MONTHLY_SAVINGS:
        logger.debug(
            "Skipping %s: savings $%.2f < threshold $%.2f",
            instance_id,
            monthly_savings,
            _MIN_MONTHLY_SAVINGS,
        )
        return None

    # Get utilization metrics
    utilization_metrics = rec.get("utilizationMetrics", [])
    cpu_utilization = None
    for metric in utilization_metrics:
        if metric.get("name") == "Cpu":
            cpu_utilization = metric.get("value")
            break

    # Build description
    cpu_desc = f"{cpu_utilization:.1f}% avg CPU" if cpu_utilization else "low utilization"

    # Get instance name from tags if available
    instance_name = _get_name_tag(rec.get("tags", []))
    resource_name = instance_name or instance_id

    # Risk level description
    risk_desc = "LOW" if performance_risk <= 1 else "MEDIUM"

    return Finding(
        resource_id=instance_id,
        resource_type="EC2",
        region=region,
        issue_type="over_provisioned",
        description=(
            f"Over-provisioned: {current_type} with {cpu_desc}. "
            f"Compute Optimizer recommends {recommended_type}. "
            f"Est. savings: ${monthly_savings:.2f}/mo. Risk: {risk_desc}."
        ),
        monthly_savings=round(monthly_savings, 2),
        severity="Medium",
        details={
            "source": "AWS Compute Optimizer",
            "recommendation": (
                f"Downsize from {current_type} to {recommended_type}. "
                f"Test in staging before applying."
            ),
            "current_instance_type": current_type,
            "recommended_instance_type": recommended_type,
            "performance_risk": performance_risk,
            "migration_effort": top_option.get("migrationEffort", "Unknown"),
            "lookback_period_days": rec.get("lookBackPeriodInDays", 14),
            "utilization_metrics": {
                m.get("name", ""): m.get("value", 0.0)
                for m in utilization_metrics
                if m.get("name")
            },
            "finding_reason_codes": rec.get("findingReasonCodes", []),
            "inferred_workload_types": rec.get("inferredWorkloadTypes", []),
        },
    )


def _get_name_tag(tags: List[Dict[str, str]]) -> Optional[str]:
    """Extract Name tag value from tags list."""
    for tag in tags:
        if tag.get("key", "").lower() == "name":
            return tag.get("value")
    return None
