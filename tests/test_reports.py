"""Tests for report HTML rendering and PDF generation."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from models.finding import Finding
from models.report import Report
from reports.generator import (
    extract_daily_cost_series,
    generate_cost_chart,
    render_html,
)
from reports.pdf import generate_pdf


def _sample_report(**kwargs: object) -> Report:
    findings = [
        Finding(
            resource_id="i-test123",
            resource_type="EC2",
            region="us-east-1",
            issue_type="stopped",
            description="Stopped instance",
            monthly_savings=42.5,
            severity="High",
            details={"instance_type": "t3.small"},
            ai_explanation="Shut down when not needed.",
        ),
        Finding(
            resource_id="vol-abc",
            resource_type="EBS",
            region="us-east-1",
            issue_type="unattached",
            description="Unattached volume",
            monthly_savings=12.0,
            severity="Medium",
            details={},
        ),
    ]
    base = dict(
        account_id="123456789012",
        account_alias="test-alias",
        client_name="Contoso Labs",
        scan_date=datetime(2026, 5, 13, 14, 30, tzinfo=timezone.utc),
        regions_scanned=["us-east-1"],
        findings=findings,
        total_savings=54.5,
        cost_trends={
            "daily_costs": {
                "2026-05-01": 100.0,
                "2026-05-02": 105.5,
                "2026-05-03": 98.0,
            }
        },
        executive_summary="Waste is concentrated in compute and storage.",
        recommendations=[
            {
                "title": "Rightsize EC2",
                "impact": 42.5,
                "difficulty": "Low",
                "description": "Terminate or resize stopped instances.",
            }
        ],
        scan_duration_seconds=12.3,
        scan_metadata={"tool_version": "1.0.0"},
    )
    base.update(kwargs)
    return Report(**base)  # type: ignore[arg-type]


def test_render_html_contains_client_and_findings() -> None:
    html = render_html(_sample_report())
    assert "Contoso Labs" in html
    assert "i-test123" in html
    assert "vol-abc" in html
    assert "Waste is concentrated" in html
    assert "Rightsize EC2" in html
    assert "AI note:" in html and "Shut down when not needed." in html


def test_render_html_ai_disabled_placeholder() -> None:
    r = _sample_report(executive_summary=None)
    html = render_html(r)
    assert "AI summaries were not generated" in html


def test_generate_cost_chart_returns_data_url() -> None:
    src = generate_cost_chart({"2026-01-01": 1.0, "2026-01-02": 2.0})
    assert src.startswith("data:image/png;base64,")
    assert len(src) > 200


def test_extract_daily_series_prefers_daily_costs() -> None:
    s = extract_daily_cost_series({"daily_costs": {"b": 2, "a": 1}})
    assert list(s.keys()) == ["a", "b"]


def test_extract_daily_series_from_ce_groups() -> None:
    trends = {
        "groups": [
            {"service": "EC2", "amount": 50.0, "period": {"Start": "2026-04-01", "End": "2026-05-01"}},
            {"service": "S3", "amount": 10.0, "period": {"Start": "2026-04-01", "End": "2026-05-01"}},
            {"service": "EC2", "amount": 60.0, "period": {"Start": "2026-05-01", "End": "2026-06-01"}},
        ]
    }
    s = extract_daily_cost_series(trends)
    assert "2026-04" in s
    assert s["2026-04"] == pytest.approx(60.0)
    assert s["2026-05"] == pytest.approx(60.0)


def test_extract_daily_series_from_spend_90d_groups_only() -> None:
    """Main audit stores CE groups only under spend_90d (no duplicate root ``groups``)."""
    trends = {
        "spend_90d": {
            "groups": [
                {"service": "EC2", "amount": 50.0, "period": {"Start": "2026-04-01", "End": "2026-05-01"}},
                {"service": "S3", "amount": 10.0, "period": {"Start": "2026-04-01", "End": "2026-05-01"}},
            ]
        },
        "month_over_month": {},
    }
    s = extract_daily_cost_series(trends)
    assert s.get("2026-04") == pytest.approx(60.0)


def test_generate_pdf_writes_file(tmp_path) -> None:
    html = render_html(_sample_report())
    out = tmp_path / "audit.pdf"
    path = generate_pdf(html, out)
    assert path.exists()
    assert path.stat().st_size > 800
    head = path.read_bytes()[:5]
    assert head.startswith(b"%PDF")
