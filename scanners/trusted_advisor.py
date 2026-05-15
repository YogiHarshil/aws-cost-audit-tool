"""AWS Trusted Advisor cost optimization scanner.

Retrieves cost optimization recommendations from AWS Trusted Advisor.
Requires AWS Business or Enterprise Support plan.

See: https://docs.aws.amazon.com/trustedadvisor/latest/APIReference/API_ListRecommendations.html
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from botocore.exceptions import ClientError

from models.finding import Finding

logger = logging.getLogger(__name__)


def scan_trusted_advisor(session: Any) -> List[Finding]:
    """Scan AWS Trusted Advisor for cost optimization recommendations.

    Args:
        session: boto3 Session object.

    Returns:
        List of findings from Trusted Advisor cost_optimizing pillar.
        Returns empty list if Trusted Advisor is not accessible (no Business Support).
    """
    findings: List[Finding] = []

    try:
        client = session.client("trustedadvisor", region_name="us-east-1")
    except Exception as exc:
        logger.warning("Failed to create Trusted Advisor client: %s", exc)
        return findings

    # Get cost optimization recommendations with warning or error status
    recommendations = _get_cost_recommendations(client)
    if not recommendations:
        return findings

    # Convert to findings
    for rec in recommendations:
        finding = _recommendation_to_finding(rec)
        if finding:
            findings.append(finding)

    return findings


def _get_cost_recommendations(client: Any) -> List[Dict[str, Any]]:
    """Get cost optimization recommendations from Trusted Advisor.

    Only retrieves recommendations with 'warning' or 'error' status.
    Gracefully handles accounts without Business/Enterprise Support.
    """
    recommendations: List[Dict[str, Any]] = []

    # Statuses that indicate actionable findings
    actionable_statuses = ["warning", "error"]

    for status in actionable_statuses:
        try:
            # Use pagination to get all recommendations
            next_token: Optional[str] = None

            while True:
                kwargs: Dict[str, Any] = {
                    "pillar": "cost_optimizing",
                    "status": status,
                    "maxResults": 100,
                }
                if next_token:
                    kwargs["nextToken"] = next_token

                response = client.list_recommendations(**kwargs)
                recs = response.get("recommendationSummaries", [])
                recommendations.extend(recs)

                next_token = response.get("nextToken")
                if not next_token:
                    break

        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")

            # Expected errors for accounts without Business/Enterprise Support
            if error_code in (
                "SubscriptionRequiredException",
                "AccessDeniedException",
                "UnauthorizedAccess",
            ):
                logger.info(
                    "Trusted Advisor requires Business/Enterprise Support plan - skipping"
                )
                return []

            # Other errors - log and continue
            logger.warning("Trusted Advisor list_recommendations failed: %s", exc)
            return []

        except Exception as exc:
            logger.warning("Unexpected error in Trusted Advisor scan: %s", exc)
            return []

    return recommendations


def _recommendation_to_finding(rec: Dict[str, Any]) -> Optional[Finding]:
    """Convert a Trusted Advisor recommendation to a Finding."""
    rec_id = rec.get("id", "")
    if not rec_id:
        return None

    name = rec.get("name", "Unknown Check")
    status = rec.get("status", "warning")
    pillar = rec.get("pillar", "cost_optimizing")

    # Get estimated savings if available
    monthly_savings = 0.0
    pillar_aggregates = rec.get("pillarSpecificAggregates", {})
    cost_optimizing = pillar_aggregates.get("costOptimizing", {})
    estimated_savings = cost_optimizing.get("estimatedMonthlySavings", 0.0)
    if estimated_savings:
        try:
            monthly_savings = float(estimated_savings)
        except (ValueError, TypeError):
            pass

    # Determine severity based on status
    severity = "High" if status == "error" else "Medium"

    # Get check category/source
    check_identifier = rec.get("checkArn", "").split("/")[-1] if rec.get("checkArn") else ""
    source = rec.get("source", "aws_config")
    rec_type = rec.get("type", "standard")

    # Get resource counts
    resources_aggregates = rec.get("resourcesAggregates", {})
    ok_count = resources_aggregates.get("okCount", 0)
    warning_count = resources_aggregates.get("warningCount", 0)
    error_count = resources_aggregates.get("errorCount", 0)

    description = f"Trusted Advisor: {name}"
    if warning_count > 0 or error_count > 0:
        description += f" ({warning_count} warnings, {error_count} errors)"
    if monthly_savings > 0:
        description += f" Est. savings: ${monthly_savings:.2f}/month."

    return Finding(
        resource_id=f"ta-{rec_id[:16]}",
        resource_type="TrustedAdvisor",
        region="global",
        issue_type="cost_optimization",
        description=description,
        monthly_savings=round(monthly_savings, 2),
        severity=severity,
        details={
            "source": "AWS Trusted Advisor",
            "check_name": name,
            "check_id": check_identifier or rec_id,
            "pillar": pillar,
            "status": status,
            "type": rec_type,
            "recommendation": f"Review in AWS Console: Check ID {check_identifier or rec_id}",
            "aws_console_url": "https://console.aws.amazon.com/trustedadvisor/home",
            "requires_business_support": True,
            "resources": {
                "ok": ok_count,
                "warning": warning_count,
                "error": error_count,
            },
        },
    )
