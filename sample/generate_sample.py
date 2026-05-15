#!/usr/bin/env python3
"""Generate a sample PDF audit report with realistic fake data for sales demos.

This script creates a professional-looking audit report for the fictional
client "Acme Technologies" with 15 findings across EC2, RDS, EBS, EIP, and S3.
The data is realistic enough for client presentations and sales demos.

Usage:
    python sample/generate_sample.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is in path for imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from models.finding import Finding
from models.report import Report
from reports.generator import render_html
from reports.pdf import generate_pdf

# ------------------------------------------------------------------------------
# Sample Data Constants
# ------------------------------------------------------------------------------

CLIENT_NAME = "Acme Technologies"
ACCOUNT_ID = "891234567890"
ACCOUNT_ALIAS = "acme-prod"
SCAN_DATE = datetime(2025, 5, 15, 14, 30, 0, tzinfo=timezone.utc)
REGIONS_SCANNED = ["us-east-1", "us-east-2", "us-west-2", "ap-south-1"]

EXECUTIVE_SUMMARY = """The AWS cost audit for Acme Technologies identified 15 waste findings across 4 services, with total estimated monthly savings of $1,634. EC2 represents the largest savings opportunity at $892/month, driven by 3 stopped instances accumulating EBS charges and 2 idle servers running below 3% CPU utilization for over 14 days.

The most impactful single finding is an RDS db.m5.large Multi-AZ instance (db-prod-analytics) with zero database connections recorded over 21 days, costing $342/month with no active workload. Five orphaned EBS volumes totalling 870GB across us-east-1 represent an additional $89/month in pure waste with zero business value.

Priority actions: terminate or snapshot stopped EC2 instances within 48 hours ($420 savings), delete the idle RDS instance after taking a final snapshot ($342 savings), and release both unassociated Elastic IPs immediately ($7.20 savings). These three actions alone recover $769/month with zero risk to production workloads."""

COST_TRENDS = {
    "spend_90d": {
        "groups": [
            {"service": "Amazon Elastic Compute Cloud - Compute", "amount": 4200.00, "period": {"Start": "2025-05-01", "End": "2025-05-15"}},
            {"service": "Amazon Relational Database Service", "amount": 1800.00, "period": {"Start": "2025-05-01", "End": "2025-05-15"}},
            {"service": "Amazon Simple Storage Service", "amount": 980.00, "period": {"Start": "2025-05-01", "End": "2025-05-15"}},
            {"service": "Amazon CloudFront", "amount": 620.00, "period": {"Start": "2025-05-01", "End": "2025-05-15"}},
            {"service": "AWS Lambda", "amount": 430.00, "period": {"Start": "2025-05-01", "End": "2025-05-15"}},
            {"service": "Other", "amount": 420.00, "period": {"Start": "2025-05-01", "End": "2025-05-15"}},
        ]
    },
    "month_over_month": {
        "current_mtd": 8450.00,
        "prior_window": 7250.00,
        "increase_pct": 16.6,
        "days_compared": 15,
    },
    "daily_costs": {
        "2025-03": 6180.00,
        "2025-04": 7250.00,
        "2025-05": 8450.00,
    },
}

RECOMMENDATIONS = [
    {
        "title": "Terminate or snapshot stopped EC2 instances",
        "impact": 420.00,
        "difficulty": "Low",
        "description": "Three EC2 instances (i-0a1b2c3d, i-0d3e4f5g, i-0g5h6i7j) have been stopped for 15-45 days but continue incurring EBS storage charges. Create AMI snapshots for disaster recovery, then terminate the instances to eliminate $420/month in waste.",
    },
    {
        "title": "Delete idle RDS Multi-AZ instance",
        "impact": 342.00,
        "difficulty": "Medium",
        "description": "The db-prod-analytics RDS instance has recorded zero database connections for 21 days. Take a final snapshot, verify no applications depend on it, then delete the instance to save $342/month.",
    },
    {
        "title": "Rightsize or stop low-utilization EC2 instances",
        "impact": 472.00,
        "difficulty": "Medium",
        "description": "Two running instances (i-0k9l8m7n, i-0p6q5r4s) show CPU utilization below 3% over 14 days. Evaluate workloads and either rightsize to smaller instance types or stop during off-hours to reduce costs by up to $472/month.",
    },
    {
        "title": "Delete orphaned EBS volumes",
        "impact": 89.00,
        "difficulty": "Low",
        "description": "Five unattached EBS volumes totaling 870GB have no associated instances. Snapshot any needed data, then delete these volumes to recover $89/month immediately.",
    },
    {
        "title": "Release unassociated Elastic IPs and add S3 lifecycle policies",
        "impact": 12.20,
        "difficulty": "Low",
        "description": "Two Elastic IPs are allocated but not associated with any resource ($7.20/month). The legacy-data-archive-prod S3 bucket lacks lifecycle policies for $5/month potential savings. Release the EIPs and configure Intelligent-Tiering.",
    },
]


def create_sample_findings() -> list[Finding]:
    """Create 15 realistic findings across all service types."""
    findings: list[Finding] = []

    # -------------------------------------------------------------------------
    # EC2 Stopped Instances (3 findings)
    # -------------------------------------------------------------------------
    findings.append(Finding(
        resource_id="i-0a1b2c3d4e5f6g7h8",
        resource_type="EC2",
        region="us-east-1",
        issue_type="stopped",
        description="Instance stopped ~15d (>7d); still incurring EBS/root costs; compute savings estimate from on-demand rate",
        monthly_savings=95.00,
        severity="High",
        details={
            "instance_type": "t3.large",
            "state_transition_reason": "User initiated (2025-04-30 09:15:00 GMT)",
            "estimated_stopped_days": 15,
            "tags": [{"Key": "Name", "Value": "web-server-staging-01"}, {"Key": "Environment", "Value": "Staging"}],
        },
        ai_explanation="This t3.large instance has been stopped for 15 days but continues to incur $95/month in EBS storage charges. Create an AMI snapshot for backup purposes, then terminate the instance to eliminate ongoing costs.",
    ))

    findings.append(Finding(
        resource_id="i-0d3e4f5g6h7i8j9k0",
        resource_type="EC2",
        region="us-east-1",
        issue_type="stopped",
        description="Instance stopped ~28d (>7d); still incurring EBS/root costs; compute savings estimate from on-demand rate",
        monthly_savings=175.00,
        severity="High",
        details={
            "instance_type": "m5.large",
            "state_transition_reason": "User initiated (2025-04-17 14:22:00 GMT)",
            "estimated_stopped_days": 28,
            "tags": [{"Key": "Name", "Value": "batch-processor-dev"}, {"Key": "Environment", "Value": "Development"}],
        },
        ai_explanation="This m5.large development instance has been stopped for 28 days with $175/month in EBS costs. Since it's a dev resource with no recent activity, terminate it after creating a snapshot to preserve the configuration.",
    ))

    findings.append(Finding(
        resource_id="i-0g5h6i7j8k9l0m1n2",
        resource_type="EC2",
        region="us-east-2",
        issue_type="stopped",
        description="Instance stopped ~45d (>7d); still incurring EBS/root costs; compute savings estimate from on-demand rate",
        monthly_savings=150.00,
        severity="High",
        details={
            "instance_type": "t3.xlarge",
            "state_transition_reason": "User initiated (2025-03-31 18:45:00 GMT)",
            "estimated_stopped_days": 45,
            "tags": [{"Key": "Name", "Value": "legacy-app-migration"}, {"Key": "Project", "Value": "Migration-2024"}],
        },
        ai_explanation="This t3.xlarge instance stopped 45 days ago during a migration project is costing $150/month in storage. The migration project completed in Q1; terminate this instance immediately after verifying no data recovery needs.",
    ))

    # -------------------------------------------------------------------------
    # EC2 Low Utilization (2 findings)
    # -------------------------------------------------------------------------
    findings.append(Finding(
        resource_id="i-0k9l8m7n6o5p4q3r2",
        resource_type="EC2",
        region="us-east-1",
        issue_type="low_utilization",
        description="Average CPU 2.1% over 14d (<5%); consider rightsizing or stopping non-prod",
        monthly_savings=236.00,
        severity="Medium",
        details={
            "instance_type": "t3.xlarge",
            "avg_cpu_14d": 2.1,
            "tags": [{"Key": "Name", "Value": "analytics-worker-02"}, {"Key": "Environment", "Value": "Production"}],
        },
        ai_explanation="This t3.xlarge instance averages only 2.1% CPU over 14 days, wasting $236/month of its capacity. Rightsize to t3.medium (saving ~60%) or implement auto-scaling to match actual workload demands.",
    ))

    findings.append(Finding(
        resource_id="i-0p6q5r4s3t2u1v0w9",
        resource_type="EC2",
        region="us-west-2",
        issue_type="low_utilization",
        description="Average CPU 1.8% over 14d (<5%); consider rightsizing or stopping non-prod",
        monthly_savings=236.00,
        severity="Medium",
        details={
            "instance_type": "m5.2xlarge",
            "avg_cpu_14d": 1.8,
            "tags": [{"Key": "Name", "Value": "report-generator-prod"}, {"Key": "Environment", "Value": "Production"}],
        },
        ai_explanation="This m5.2xlarge instance shows only 1.8% average CPU utilization, indicating severe over-provisioning at $236/month waste. Downgrade to m5.large or implement scheduled scaling for batch report generation windows.",
    ))

    # -------------------------------------------------------------------------
    # RDS Findings (2 findings)
    # -------------------------------------------------------------------------
    findings.append(Finding(
        resource_id="db-prod-analytics",
        resource_type="RDS",
        region="us-east-1",
        issue_type="zero_connections",
        description="No database connections observed in 14d (max metric)",
        monthly_savings=342.00,
        severity="High",
        details={
            "db_instance_class": "db.m5.large",
            "engine": "postgres",
            "max_connections_14d": 0,
            "multi_az": True,
            "allocated_storage": 100,
            "tags": [{"Key": "Name", "Value": "analytics-db"}, {"Key": "Environment", "Value": "Production"}],
        },
        ai_explanation="This Multi-AZ db.m5.large PostgreSQL instance has had zero connections for 21 days, costing $342/month with no workload. Take a final snapshot and delete the instance after confirming the analytics pipeline was migrated.",
    ))

    findings.append(Finding(
        resource_id="db-staging-cache",
        resource_type="RDS",
        region="us-east-1",
        issue_type="stopped",
        description="RDS instance is stopped but still billed for storage (compute estimate)",
        monthly_savings=178.00,
        severity="Medium",
        details={
            "db_instance_class": "db.t3.medium",
            "engine": "mysql",
            "allocated_storage": 150,
            "tags": [{"Key": "Name", "Value": "staging-cache-db"}, {"Key": "Environment", "Value": "Staging"}],
        },
        ai_explanation="This stopped db.t3.medium MySQL instance incurs $178/month in storage costs for 150GB. Since staging environments should be ephemeral, snapshot the data and delete the instance to eliminate ongoing charges.",
    ))

    # -------------------------------------------------------------------------
    # EBS Unattached Volumes (5 findings)
    # -------------------------------------------------------------------------
    ebs_volumes = [
        ("vol-0a1b2c3d4e5f6a1b2", 20, "gp2", 2.00, "Low", "backup-temp-vol"),
        ("vol-0c3d4e5f6g7h8i9j0", 50, "gp3", 4.00, "Low", "dev-data-vol"),
        ("vol-0e5f6g7h8i9j0k1l2", 100, "gp2", 10.00, "Medium", "old-app-storage"),
        ("vol-0g7h8i9j0k1l2m3n4", 200, "gp3", 16.00, "Medium", "migration-snapshot"),
        ("vol-0i9j0k1l2m3n4o5p6", 500, "io1", 57.00, "High", "database-backup-legacy"),
    ]

    for vol_id, size, vol_type, savings, severity, name in ebs_volumes:
        findings.append(Finding(
            resource_id=vol_id,
            resource_type="EBS",
            region="us-east-1",
            issue_type="unattached",
            description=f"Unattached {vol_type} volume ({size} GiB) in available state",
            monthly_savings=savings,
            severity=severity,
            details={
                "volume_type": vol_type,
                "size_gib": size,
                "encrypted": True,
                "tags": [{"Key": "Name", "Value": name}],
            },
            ai_explanation=f"This {size}GB {vol_type} volume is unattached and costing ${savings:.2f}/month with no benefit. Verify no data recovery is needed, then delete the volume to eliminate waste immediately.",
        ))

    # -------------------------------------------------------------------------
    # EIP Unassociated (2 findings)
    # -------------------------------------------------------------------------
    findings.append(Finding(
        resource_id="eipalloc-0a1b2c3d4e5f6g7h8",
        resource_type="EIP",
        region="us-east-1",
        issue_type="unassociated",
        description="Elastic IP allocated but not associated",
        monthly_savings=3.60,
        severity="Medium",
        details={
            "public_ip": "3.92.145.201",
            "domain": "vpc",
            "tags": [{"Key": "Name", "Value": "3-ip-prod-old"}],
        },
        ai_explanation="This Elastic IP (3.92.145.201) is allocated but not attached to any resource, wasting $3.60/month. Release it immediately unless it's reserved for a specific upcoming deployment.",
    ))

    findings.append(Finding(
        resource_id="eipalloc-0i9j0k1l2m3n4o5p6",
        resource_type="EIP",
        region="us-east-1",
        issue_type="unassociated",
        description="Elastic IP allocated but not associated",
        monthly_savings=3.60,
        severity="Medium",
        details={
            "public_ip": "54.210.88.112",
            "domain": "vpc",
            "tags": [{"Key": "Name", "Value": "54-ip-staging-forgotten"}],
        },
        ai_explanation="This Elastic IP (54.210.88.112) labeled 'staging-forgotten' confirms it's orphaned infrastructure costing $3.60/month. Release it immediately as staging resources should use dynamic IPs.",
    ))

    # -------------------------------------------------------------------------
    # S3 Finding (1 finding)
    # -------------------------------------------------------------------------
    findings.append(Finding(
        resource_id="legacy-data-archive-prod",
        resource_type="S3",
        region="us-east-1",
        issue_type="large_bucket_no_tiering",
        description="Large bucket (~2.1 TiB avg Standard storage in 14d) without Intelligent-Tiering configuration",
        monthly_savings=125.80,
        severity="High",
        details={
            "approx_size_gib": 2150.0,
            "tags": [{"Key": "Name", "Value": "legacy-data-archive-prod"}, {"Key": "DataClassification", "Value": "Internal"}],
        },
        ai_explanation="This 2.1TB bucket stores archive data in Standard storage class without lifecycle policies, wasting ~$125.80/month. Enable S3 Intelligent-Tiering or configure lifecycle rules to transition objects to Glacier after 90 days.",
    ))

    return findings


def create_sample_report() -> Report:
    """Build the complete sample audit report."""
    findings = create_sample_findings()

    return Report(
        account_id=ACCOUNT_ID,
        account_alias=ACCOUNT_ALIAS,
        client_name=CLIENT_NAME,
        scan_date=SCAN_DATE,
        regions_scanned=REGIONS_SCANNED,
        findings=findings,
        total_savings=0.0,  # Will be computed from findings
        cost_trends=COST_TRENDS,
        executive_summary=EXECUTIVE_SUMMARY,
        recommendations=RECOMMENDATIONS,
        scan_duration_seconds=47.3,
        scan_metadata={
            "tool_version": "1.0.0",
            "sample_report": True,
        },
    )


def main() -> int:
    """Generate the sample PDF report.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    output_dir = PROJECT_ROOT / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / "SAMPLE_Acme_Technologies_2025-05.pdf"

    print("Building sample audit report...")
    report = create_sample_report()

    print(f"  Client: {report.client_name}")
    print(f"  Findings: {report.findings_count}")
    print(f"  Total savings: ${report.total_savings:,.2f}/month")
    print(f"  Severity breakdown: {report.findings_by_severity}")

    print("Rendering HTML template...")
    html = render_html(report)

    print("Generating PDF...")
    path = generate_pdf(html, output_file)

    print(f"\nSample report generated: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
