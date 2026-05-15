"""Savings Plans coverage and utilization scanner.

Checks for:
1. Low coverage - significant on-demand spend not covered by Savings Plans
2. Low utilization - existing Savings Plans not being fully used

See: https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_GetSavingsPlansCoverage.html
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from botocore.exceptions import ClientError

from models.finding import Finding

logger = logging.getLogger(__name__)

# Thresholds for generating findings
_MIN_COVERAGE_PCT = 50.0  # Flag if <50% of eligible spend is covered
_MIN_UTILIZATION_PCT = 80.0  # Flag if existing SPs are <80% utilized
_MIN_MONTHLY_SPEND = 500.0  # Only flag if monthly on-demand spend > $500
_SAVINGS_FACTOR = 0.30  # Assume ~30% savings from Savings Plans vs on-demand


def scan_savings_plans(session: Any) -> List[Finding]:
    """Scan Savings Plans coverage and utilization.

    Args:
        session: boto3 Session object.

    Returns:
        List of findings for coverage gaps or underutilization.
    """
    findings: List[Finding] = []

    try:
        ce = session.client("ce", region_name="us-east-1")
    except Exception as exc:
        logger.warning("Failed to create Cost Explorer client: %s", exc)
        return findings

    # Calculate date range (last 30 days, ending yesterday)
    today = datetime.now(timezone.utc).date()
    end_date = today - timedelta(days=1)
    start_date = end_date - timedelta(days=30)

    time_period = {
        "Start": start_date.strftime("%Y-%m-%d"),
        "End": end_date.strftime("%Y-%m-%d"),
    }

    # Check coverage (Case A)
    coverage_finding = _check_coverage(ce, time_period)
    if coverage_finding:
        findings.append(coverage_finding)

    # Check utilization (Case B)
    utilization_finding = _check_utilization(ce, time_period)
    if utilization_finding:
        findings.append(utilization_finding)

    return findings


def _check_coverage(ce: Any, time_period: Dict[str, str]) -> Optional[Finding]:
    """Check if Savings Plans coverage is below threshold.

    Returns a finding if coverage is low and on-demand spend is significant.
    """
    try:
        response = ce.get_savings_plans_coverage(
            TimePeriod=time_period,
            Granularity="MONTHLY",
        )
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code in ("AccessDeniedException", "DataUnavailableException"):
            logger.info("Savings Plans coverage data not available: %s", error_code)
            return None
        logger.warning("get_savings_plans_coverage failed: %s", exc)
        return None
    except Exception as exc:
        logger.warning("Unexpected error in get_savings_plans_coverage: %s", exc)
        return None

    coverages = response.get("SavingsPlansCoverages", [])
    if not coverages:
        logger.debug("No Savings Plans coverage data returned")
        return None

    # Aggregate coverage data across the period
    total_on_demand = 0.0
    total_covered = 0.0

    for item in coverages:
        coverage = item.get("Coverage", {})
        try:
            on_demand = float(coverage.get("OnDemandCost", "0") or "0")
            covered = float(coverage.get("SpendCoveredBySavingsPlans", "0") or "0")
            total_on_demand += on_demand
            total_covered += covered
        except (ValueError, TypeError):
            continue

    # Calculate coverage percentage
    total_spend = total_on_demand + total_covered
    if total_spend < _MIN_MONTHLY_SPEND:
        logger.debug(
            "Total eligible spend $%.2f below threshold $%.2f",
            total_spend,
            _MIN_MONTHLY_SPEND,
        )
        return None

    coverage_pct = (total_covered / total_spend * 100) if total_spend > 0 else 0.0

    if coverage_pct >= _MIN_COVERAGE_PCT:
        logger.debug("Coverage %.1f%% above threshold %.1f%%", coverage_pct, _MIN_COVERAGE_PCT)
        return None

    # Calculate potential savings
    uncovered_spend = total_on_demand
    potential_savings = uncovered_spend * _SAVINGS_FACTOR

    severity = "High" if potential_savings > 200 else "Medium"

    return Finding(
        resource_id="savings-plans-coverage",
        resource_type="SavingsPlans",
        region="global",
        issue_type="low_coverage",
        description=(
            f"Only {coverage_pct:.0f}% of EC2/Fargate spend is covered by Savings Plans. "
            f"Uncovered on-demand spend: ${uncovered_spend:.2f}/month. "
            f"Consider purchasing a Compute Savings Plan - estimated savings: ${potential_savings:.2f}/month."
        ),
        monthly_savings=round(potential_savings, 2),
        severity=severity,
        details={
            "coverage_percentage": round(coverage_pct, 1),
            "uncovered_monthly_spend": round(uncovered_spend, 2),
            "covered_monthly_spend": round(total_covered, 2),
            "total_eligible_spend": round(total_spend, 2),
            "recommendation": (
                f"Purchase a Compute Savings Plan (1-year no-upfront) for ~30% savings on uncovered spend. "
                f"Review usage patterns in Cost Explorer before committing."
            ),
            "recommendation_type": "Compute Savings Plan (most flexible)",
            "commitment_options": ["1-year no upfront", "1-year partial upfront", "3-year"],
        },
    )


def _check_utilization(ce: Any, time_period: Dict[str, str]) -> Optional[Finding]:
    """Check if existing Savings Plans are being fully utilized.

    Returns a finding if utilization is below threshold.
    """
    try:
        response = ce.get_savings_plans_utilization(
            TimePeriod=time_period,
            Granularity="MONTHLY",
        )
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code in ("AccessDeniedException", "DataUnavailableException"):
            logger.info("Savings Plans utilization data not available: %s", error_code)
            return None
        logger.warning("get_savings_plans_utilization failed: %s", exc)
        return None
    except Exception as exc:
        logger.warning("Unexpected error in get_savings_plans_utilization: %s", exc)
        return None

    total = response.get("Total", {})
    utilization = total.get("Utilization", {})

    if not utilization:
        # No Savings Plans exist - this is not an error
        logger.debug("No Savings Plans utilization data (likely no SPs exist)")
        return None

    try:
        utilization_pct = float(utilization.get("UtilizationPercentage", "0") or "0")
        total_commitment = float(utilization.get("TotalCommitment", "0") or "0")
        unused_commitment = float(utilization.get("UnusedCommitment", "0") or "0")
    except (ValueError, TypeError):
        logger.warning("Failed to parse utilization values")
        return None

    # If no commitment, no SPs exist
    if total_commitment <= 0:
        logger.debug("No Savings Plans commitment found")
        return None

    if utilization_pct >= _MIN_UTILIZATION_PCT:
        logger.debug(
            "Utilization %.1f%% above threshold %.1f%%",
            utilization_pct,
            _MIN_UTILIZATION_PCT,
        )
        return None

    return Finding(
        resource_id="savings-plans-utilization",
        resource_type="SavingsPlans",
        region="global",
        issue_type="low_utilization",
        description=(
            f"Existing Savings Plans are only {utilization_pct:.0f}% utilized. "
            f"Unused commitment: ${unused_commitment:.2f}/month. "
            f"Review workloads - instance types/regions may have changed."
        ),
        monthly_savings=0.0,  # This is waste, not potential savings
        severity="High",
        details={
            "utilization_percentage": round(utilization_pct, 1),
            "total_commitment": round(total_commitment, 2),
            "unused_commitment": round(unused_commitment, 2),
            "note": "This finding indicates waste, not a savings opportunity",
        },
    )
