"""Cost Explorer scanner (service spend and simple month-over-month trend)."""

from __future__ import annotations

import logging
from calendar import monthrange
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from botocore.exceptions import ClientError

from models.finding import Finding

logger = logging.getLogger(__name__)


class CostExplorerScanner:
    """Account-level cost signals (does not inherit :class:`BaseScanner`)."""

    def __init__(self, session: Any) -> None:
        self.session = session
        self.ce = session.client("ce", region_name="us-east-1")

    def scan(self) -> List[Finding]:
        """Return findings when spend trend crosses simple thresholds."""
        findings: List[Finding] = []
        try:
            trend = self.get_month_over_month_trend()
            if trend.get("increase_pct") is not None and trend["increase_pct"] > 20:
                findings.append(
                    Finding(
                        resource_id="account-spend-trend",
                        resource_type="Cost Explorer",
                        region="global",
                        issue_type="spend_increase",
                        description=(
                            f"Estimated month-to-date spend up ~{trend['increase_pct']:.0f}% "
                            "vs same-length prior month window"
                        ),
                        monthly_savings=0.0,
                        severity="Medium",
                        details=trend,
                    )
                )
        except ClientError as exc:
            logger.warning("Cost Explorer trend scan failed: %s", exc)
        return findings

    def get_90_day_spend(self) -> Dict[str, Any]:
        """Return blended cost grouped by SERVICE for the last ~90 days."""
        end = date.today()
        start = end - timedelta(days=90)
        try:
            resp = self.ce.get_cost_and_usage(
                TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
                Granularity="MONTHLY",
                Metrics=["BlendedCost"],
                GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
            )
        except ClientError as exc:
            logger.warning("get_cost_and_usage failed: %s", exc)
            return {"groups": [], "error": str(exc)}
        groups: List[Dict[str, Any]] = []
        for period in resp.get("ResultsByTime", []):
            for group in period.get("Groups", []):
                amount = group["Metrics"]["BlendedCost"].get("Amount", "0")
                groups.append(
                    {
                        "service": group["Keys"][0] if group.get("Keys") else "Unknown",
                        "amount": float(amount),
                        "period": period.get("TimePeriod", {}),
                    }
                )
        return {"groups": groups}

    def get_month_over_month_trend(self) -> Dict[str, Any]:
        """Compare current month-to-date blended cost vs previous month same-length window."""
        today = date.today()
        this_month_start = date(today.year, today.month, 1)
        days_elapsed = (today - this_month_start).days + 1
        prev_month_last = this_month_start - timedelta(days=1)
        prev_month_start = date(prev_month_last.year, prev_month_last.month, 1)
        _, dim = monthrange(prev_month_last.year, prev_month_last.month)
        anchor_day = min(days_elapsed, dim)
        prev_window_end = date(prev_month_last.year, prev_month_last.month, anchor_day)
        try:
            cur = self._blended_sum(this_month_start, today + timedelta(days=1))
            prev = self._blended_sum(prev_month_start, prev_window_end + timedelta(days=1))
        except ClientError as exc:
            logger.warning("MTD cost comparison failed: %s", exc)
            return {"current_mtd": None, "prior_window": None, "increase_pct": None, "error": str(exc)}
        if prev is None or prev <= 0 or cur is None:
            return {
                "current_mtd": cur,
                "prior_window": prev,
                "increase_pct": None,
            }
        increase = (cur - prev) / prev * 100.0
        return {
            "current_mtd": round(cur, 2),
            "prior_window": round(prev, 2),
            "increase_pct": round(increase, 1),
            "days_compared": days_elapsed,
        }

    def _blended_sum(self, start: date, end_exclusive: date) -> Optional[float]:
        """Sum blended cost over [start, end_exclusive)."""
        if start >= end_exclusive:
            return None
        resp = self.ce.get_cost_and_usage(
            TimePeriod={
                "Start": start.isoformat(),
                "End": end_exclusive.isoformat(),
            },
            Granularity="MONTHLY",
            Metrics=["BlendedCost"],
        )
        total = 0.0
        for period in resp.get("ResultsByTime", []):
            amt = period.get("Total", {}).get("BlendedCost", {}).get("Amount")
            if amt is not None:
                total += float(amt)
        return total
