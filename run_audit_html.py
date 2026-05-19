#!/usr/bin/env python3
"""Run AWS audit and generate HTML report (bypasses WeasyPrint GTK requirement)."""

import os
import sys
import json
from datetime import datetime, timezone
from pathlib import Path

import boto3

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
# Explicitly load .env from project directory
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)
print(f"Loaded .env from: {env_path}")

from utils.aws_client import create_session, create_client
from utils.pricing import PricingCache
from scanners.ec2 import EC2Scanner
from scanners.rds import RDSScanner
from scanners.ebs import EBSScanner
from scanners.eip import EIPScanner
from scanners.s3 import S3Scanner
from scanners.snapshots import SnapshotScanner
from scanners.cost_explorer import CostExplorerScanner
from scanners.nat_gateway import NATGatewayScanner
from scanners.load_balancer import LoadBalancerScanner
from scanners.cloudwatch_logs import CloudWatchLogsScanner
from scanners.ecs import ECSScanner
from models.report import Report
from models.finding import Finding
from ai.summarizer import Summarizer
from ai.recommender import Recommender
from ai.bedrock_summarizer import (
    BedrockSummarizer,
    BedrockRecommender,
    check_bedrock_access,
    create_session_from_api_key,
)
from utils.confidence import calculate_confidence

# Import only generator (not pdf)
from jinja2 import Environment, FileSystemLoader
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import base64
from io import BytesIO


def generate_cost_chart(cost_trends: dict) -> str:
    """Generate cost chart as base64 PNG."""
    fig, ax = plt.subplots(figsize=(8, 4))

    daily = cost_trends.get("daily_costs", {})
    if daily:
        months = list(daily.keys())
        values = list(daily.values())
        ax.bar(months, values, color='#0d5c9e')
        ax.set_ylabel('Cost ($)')
        ax.set_title('Monthly Cost Trend')
    else:
        ax.text(0.5, 0.5, 'No cost data available', ha='center', va='center')

    buf = BytesIO()
    fig.savefig(buf, format='png', dpi=100, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return f"data:image/png;base64,{base64.b64encode(buf.read()).decode()}"


def render_html(report: Report) -> str:
    """Render report to HTML."""
    template_dir = Path(__file__).parent / "reports" / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)))

    # Add filters
    env.filters["money"] = lambda x: f"${x:,.2f}"
    env.filters["money_int"] = lambda x: f"${x:,.0f}"

    template = env.get_template("report.html")

    # Count safe-to-delete findings (confidence >= 90%)
    safe_findings_count = sum(
        1 for f in report.findings
        if getattr(f, 'confidence_score', 0) >= 90
    )

    return template.render(
        client_name=report.client_name,
        account_id=report.account_id,
        account_alias=report.account_alias,
        report_date=report.scan_date.strftime("%B %d, %Y"),
        total_savings=report.total_savings,
        findings_count=report.findings_count,
        findings_by_severity=report.findings_by_severity,
        findings_by_type=report.findings_by_type,
        findings=report.findings,
        executive_summary_display=report.executive_summary or "AI summary not available.",
        recommendations=report.recommendations or [],
        cost_chart_src=generate_cost_chart(report.cost_trends),
        regions_label=", ".join(report.regions_scanned),
        scan_duration_seconds=report.scan_duration_seconds,
        safe_findings_count=safe_findings_count,
    )


def main():
    profile = os.environ.get("AWS_PROFILE", "limit")
    region = "us-east-1"
    client_name = os.environ.get("CLIENT_NAME", "Demo Audit")

    print(f"=== AWS COST AUDIT ===")
    print(f"Profile: {profile}")
    print(f"Region: {region}")
    print(f"Client: {client_name}")
    print()

    # Create session
    print("Creating AWS session...")
    session = create_session(profile, None)
    cache = PricingCache()
    pricing = create_client(session, "pricing")

    # Get account info
    sts = session.client("sts", region_name="us-east-1")
    account_id = sts.get_caller_identity()["Account"]
    print(f"Account: {account_id}")

    findings = []

    # Run scanners
    scanners = [
        ("EC2", EC2Scanner),
        ("RDS", RDSScanner),
        ("EBS", EBSScanner),
        ("EIP", EIPScanner),
        ("S3", S3Scanner),
        ("Snapshots", SnapshotScanner),
        ("NAT Gateway", NATGatewayScanner),
        ("Load Balancer", LoadBalancerScanner),
        ("CloudWatch Logs", CloudWatchLogsScanner),
        ("ECS", ECSScanner),
    ]

    for name, scanner_cls in scanners:
        print(f"Scanning {name}...")
        try:
            scanner = scanner_cls(session, region, [], pricing, cache)
            results = scanner.scan()
            findings.extend(results)
            if results:
                print(f"  Found {len(results)} findings")
        except Exception as e:
            print(f"  Error: {e}")

    # Cost Explorer
    print("Scanning Cost Explorer...")
    try:
        ce = CostExplorerScanner(session)
        ce_findings = ce.scan()
        findings.extend(ce_findings)
        cost_trends = {
            "spend_90d": ce.get_90_day_spend(),
            "month_over_month": ce.get_month_over_month_trend(),
            "daily_costs": {},
        }
        if ce_findings:
            print(f"  Found {len(ce_findings)} findings")
    except Exception as e:
        print(f"  Error: {e}")
        cost_trends = {"spend_90d": {}, "month_over_month": {}, "daily_costs": {}}

    print(f"\nTotal findings: {len(findings)}")

    # Calculate confidence scores for each finding
    print("Calculating confidence scores...")
    scored = 0
    for f in findings:
        score, reasons, label = calculate_confidence(f, session)
        f.confidence_score = score
        f.confidence_reasons = reasons
        f.safe_to_delete = label
        if label != "UNKNOWN":
            scored += 1
    safe_count = sum(1 for f in findings if f.safe_to_delete == "SAFE")
    print(f"  Scored {scored} findings — {safe_count} rated SAFE TO DELETE")

    # Create report
    report = Report(
        account_id=account_id,
        account_alias=profile,
        client_name=client_name,
        scan_date=datetime.now(timezone.utc),
        regions_scanned=[region],
        findings=findings,
        total_savings=0.0,
        cost_trends=cost_trends,
        executive_summary=None,
        recommendations=None,
        scan_duration_seconds=30.0,
        scan_metadata={},
    )

    # AI summaries - try Bedrock API key first, then OpenAI, then Bedrock profile
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    model = os.environ.get("OPENAI_MODEL", "openai/gpt-4o-mini")
    use_bedrock = os.environ.get("USE_BEDROCK", "").lower() in ("true", "1", "yes")
    bedrock_api_key = os.environ.get("BEDROCK_API_KEY", "").strip()
    bedrock_model = os.environ.get("BEDROCK_MODEL", "anthropic.claude-3-haiku-20240307-v1:0")
    bedrock_region = os.environ.get("BEDROCK_REGION", "us-east-1")
    # IMPORTANT: Bedrock can use a DIFFERENT profile than scanning!
    # This lets you use YOUR Bedrock access while scanning CLIENT's account
    bedrock_profile = os.environ.get("BEDROCK_PROFILE", "")

    # Auto-enable Bedrock if API key is provided
    if bedrock_api_key:
        use_bedrock = True

    if api_key and not use_bedrock:
        print("\nGenerating AI summaries (OpenAI/OpenRouter)...")
        try:
            summarizer = Summarizer(api_key, model=model, base_url=base_url)
            recommender = Recommender(api_key, model=model, base_url=base_url)

            print("  Executive summary...")
            report.executive_summary = summarizer.generate_executive_summary(findings, cost_trends)

            print("  Recommendations...")
            report.recommendations = recommender.generate_top_5_recommendations(findings)

            print("  Per-finding explanations...")
            for i, f in enumerate(findings):
                f.ai_explanation = summarizer.generate_finding_explanation(f)
                print(f"    {i+1}/{len(findings)}: {f.resource_id[:30]}...")

        except Exception as e:
            print(f"  AI Error: {e}")
            report.executive_summary = "AI summary unavailable."
            report.recommendations = []
    elif use_bedrock:
        # AWS Bedrock - can use API key, profile, or scanning session
        if bedrock_api_key:
            print(f"\nUsing Bedrock with API key (region: {bedrock_region})")
            try:
                bedrock_session = create_session_from_api_key(bedrock_api_key, bedrock_region)
            except Exception as e:
                print(f"  Error parsing Bedrock API key: {e}")
                bedrock_session = None
        elif bedrock_profile:
            print(f"\nUsing Bedrock with profile: {bedrock_profile} (YOUR account)")
            bedrock_session = boto3.Session(profile_name=bedrock_profile)
        else:
            print("\nUsing Bedrock with scanning session (same account)")
            print("  TIP: Set BEDROCK_API_KEY or BEDROCK_PROFILE for cross-account")
            bedrock_session = session

        if bedrock_session and check_bedrock_access(bedrock_session, bedrock_region):
            print(f"  Bedrock available! Using model: {bedrock_model}")
            try:
                bedrock_summarizer = BedrockSummarizer(
                    session=bedrock_session,
                    model_id=bedrock_model,
                    region=bedrock_region,
                )
                bedrock_recommender = BedrockRecommender(
                    session=bedrock_session,
                    model_id=bedrock_model,
                    region=bedrock_region,
                )

                print("  Executive summary...")
                report.executive_summary = bedrock_summarizer.generate_executive_summary(
                    findings, cost_trends
                )

                print("  Recommendations...")
                report.recommendations = bedrock_recommender.generate_top_5_recommendations(
                    findings
                )

                print("  Per-finding explanations...")
                for i, f in enumerate(findings):
                    f.ai_explanation = bedrock_summarizer.generate_finding_explanation(f)
                    print(f"    {i+1}/{len(findings)}: {f.resource_id[:30]}...")

            except Exception as e:
                print(f"  Bedrock Error: {e}")
                report.executive_summary = "AI summary unavailable."
                report.recommendations = []
        else:
            print("  Bedrock not accessible in this account.")
            if not bedrock_profile:
                print("  TIP: Set BEDROCK_PROFILE=your-profile to use YOUR Bedrock account")
            report.executive_summary = (
                "AI summary not available. Check BEDROCK_PROFILE configuration."
            )
            report.recommendations = []
    else:
        print("\nSkipping AI summaries (no API key or Bedrock configured)")
        report.executive_summary = "AI summary not configured."
        report.recommendations = []

    # Generate HTML
    print("\nGenerating HTML report...")
    html = render_html(report)

    # Save
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    html_path = output_dir / f"{client_name.replace(' ', '_')}_audit_{date_str}.html"
    json_path = output_dir / f"{client_name.replace(' ', '_')}_audit_{date_str}.json"

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    # Save JSON
    json_data = {
        "account_id": report.account_id,
        "client_name": report.client_name,
        "scan_date": report.scan_date.isoformat(),
        "total_savings": report.total_savings,
        "findings_count": report.findings_count,
        "findings": [
            {
                "resource_id": f.resource_id,
                "resource_type": f.resource_type,
                "region": f.region,
                "issue_type": f.issue_type,
                "description": f.description,
                "monthly_savings": f.monthly_savings,
                "severity": f.severity,
                "ai_explanation": f.ai_explanation,
            }
            for f in findings
        ],
        "executive_summary": report.executive_summary,
        "recommendations": report.recommendations,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=2, default=str)

    # Print summary
    print("\n" + "=" * 50)
    print("           AUDIT COMPLETE")
    print("=" * 50)
    print(f"HTML Report: {html_path.resolve()}")
    print(f"JSON Export: {json_path.resolve()}")
    print()
    print("FINDINGS:")
    for f in findings:
        print(f"  [{f.severity}] {f.resource_type}: {f.resource_id}")
        print(f"         ${f.monthly_savings:.2f}/mo - {f.issue_type}")
    print()
    print(f"TOTAL MONTHLY SAVINGS: ${report.total_savings:,.2f}")
    print(f"ANNUAL SAVINGS:        ${report.total_savings * 12:,.2f}")
    print("=" * 50)
    print("\nOpen HTML in browser and press Ctrl+P to print as PDF")


if __name__ == "__main__":
    main()
