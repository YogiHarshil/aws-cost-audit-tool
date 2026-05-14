"""Jinja2 HTML rendering and matplotlib cost chart for audit reports."""

from __future__ import annotations

import base64
import logging
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, Dict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from jinja2 import Environment, FileSystemLoader, select_autoescape

from models.report import Report

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def _money(value: float, decimals: int = 2) -> str:
    return f"${float(value):,.{decimals}f}"


def _money_int(value: float) -> str:
    return f"${float(value):,.0f}"


def extract_daily_cost_series(cost_trends: Dict[str, Any]) -> Dict[str, float]:
    """Build an ordered date-keyed series for charting from ``Report.cost_trends``."""
    if not isinstance(cost_trends, dict):
        return {}
    raw = cost_trends.get("daily_costs")
    if isinstance(raw, dict) and raw:
        out: Dict[str, float] = {}
        for k, v in raw.items():
            try:
                out[str(k)] = float(v)
            except (TypeError, ValueError):
                continue
        if out:
            return dict(sorted(out.items()))

    groups = cost_trends.get("groups")
    if not (isinstance(groups, list) and groups):
        spend = cost_trends.get("spend_90d")
        if isinstance(spend, dict):
            nested = spend.get("groups")
            groups = nested if isinstance(nested, list) else []
        else:
            groups = []

    if isinstance(groups, list) and groups:
        by_key: Dict[str, float] = {}
        for g in groups:
            if not isinstance(g, dict):
                continue
            period = g.get("period") or {}
            start = period.get("Start")
            amt = g.get("amount")
            if start is None or amt is None:
                continue
            key = str(start)[:7]
            try:
                by_key[key] = by_key.get(key, 0.0) + float(amt)
            except (TypeError, ValueError):
                continue
        if by_key:
            return dict(sorted(by_key.items()))

    end = date.today()
    return {(end - timedelta(days=i)).isoformat(): 0.0 for i in range(29, -1, -1)}


def generate_cost_chart(cost_data: Dict[str, float]) -> str:
    """Render a line chart as a PNG data URL (``data:image/png;base64,...``)."""
    labels = list(cost_data.keys())
    values = [float(cost_data[k]) for k in labels]

    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.plot(range(len(values)), values, linewidth=2, color="#0066cc", marker="o", markersize=4)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Cost ($)", fontsize=11, color="#333333")
    ax.set_title("Cost trend (daily or monthly points)", fontsize=13, fontweight="bold", color="#1a3a5c")
    ax.grid(True, alpha=0.3, linestyle="--")
    ax.set_facecolor("#f8fafc")
    fig.patch.set_facecolor("#ffffff")
    plt.tight_layout()

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("ascii")
    plt.close(fig)
    return f"data:image/png;base64,{b64}"


def render_html(report: Report, *, template_name: str = "report.html") -> str:
    """Render the audit ``report`` to HTML using Jinja2 (includes embedded cost chart)."""
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.filters["money"] = _money
    env.filters["money_int"] = _money_int

    cost_series = extract_daily_cost_series(report.cost_trends)
    chart_src = generate_cost_chart(cost_series)

    if report.executive_summary:
        executive_summary_display = report.executive_summary
    else:
        executive_summary_display = (
            "AI summaries were not generated for this report "
            "(--skip-ai, missing API key, or generation unavailable)."
        )

    tpl = env.get_template(template_name)
    return tpl.render(
        report=report,
        client_name=report.client_name,
        account_id=report.account_id,
        account_alias=report.account_alias,
        report_date=report.scan_date.strftime("%Y-%m-%d %H:%M UTC"),
        total_savings=report.total_savings,
        executive_summary_display=executive_summary_display,
        cost_chart_src=chart_src,
        findings=report.findings,
        recommendations=report.recommendations or [],
        regions_label=", ".join(report.regions_scanned),
        scan_duration_seconds=report.scan_duration_seconds,
        findings_by_severity=report.findings_by_severity,
        findings_by_type=report.findings_by_type,
        findings_count=report.findings_count,
    )
