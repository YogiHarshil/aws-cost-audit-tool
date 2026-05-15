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

EXECUTIVE_SUMMARY = """The AWS cost audit for Acme Technologies identified 21 waste findings across 6 resource types, with total estimated monthly savings of $1,089. Reserved Instance opportunities represent the largest savings at $280/month - 4 on-demand m5.large instances have been running 30+ days and would benefit from 1-year no-upfront RIs (37% savings).

The most impactful single finding is an RDS db.m5.large Multi-AZ instance (db-prod-analytics) with zero database connections recorded over 21 days, costing $205/month (60% of full rate) with no active workload. Three orphaned EBS snapshots totaling 850GB cost $42.50/month with no associated volumes or AMIs.

Note: Stopped EC2 instances show EBS storage costs only (not compute) - these instances have zero compute charges but their attached volumes continue to incur storage fees totaling $28/month across 3 instances.

Priority actions: purchase RIs for stable m5.large workloads ($280/month), delete the idle RDS instance after snapshot ($205 savings), and clean up orphaned snapshots ($42.50 savings). These three actions recover $527/month with minimal risk."""

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
        "title": "Purchase Reserved Instances for stable m5.large workloads",
        "impact": 103.30,
        "difficulty": "Medium",
        "description": "Four m5.large instances have been running on-demand for 30+ days across us-east-1 and us-west-2. Purchase 4x 1-year no-upfront Regional RIs to save 37% ($103.30/month). Requires commitment to stable workloads.",
    },
    {
        "title": "Delete idle RDS Multi-AZ instance",
        "impact": 205.20,
        "difficulty": "Medium",
        "description": "The db-prod-analytics RDS Multi-AZ instance has recorded zero database connections for 21 days. Take a final snapshot, verify no applications depend on it, then delete to save $205.20/month.",
    },
    {
        "title": "Delete orphaned EBS snapshots",
        "impact": 42.50,
        "difficulty": "Low",
        "description": "Three orphaned snapshots totaling 850GB have no associated volumes or AMIs. These are from deleted resources and sunset projects. Delete after verifying no compliance retention requirements to save $42.50/month.",
    },
    {
        "title": "Rightsize or stop low-utilization EC2 instances",
        "impact": 236.00,
        "difficulty": "Medium",
        "description": "Two running instances show CPU utilization below 3% over 14 days. Evaluate workloads and either rightsize to smaller instance types or implement scheduled scaling to reduce costs by up to $236/month.",
    },
    {
        "title": "Clean up stopped EC2 instances and orphaned EBS volumes",
        "impact": 117.00,
        "difficulty": "Low",
        "description": "Three stopped EC2 instances have attached EBS volumes costing $28/month. Five unattached EBS volumes cost $89/month. Terminate stopped instances and delete unneeded volumes after verifying no data recovery needs. Total: $117/month.",
    },
]


def create_sample_findings() -> list[Finding]:
    """Create 15 realistic findings across all service types."""
    findings: list[Finding] = []

    # -------------------------------------------------------------------------
    # EC2 Stopped Instances (3 findings) - NOW SHOWS EBS COST ONLY
    # -------------------------------------------------------------------------
    findings.append(Finding(
        resource_id="i-0a1b2c3d4e5f6g7h8",
        resource_type="EC2",
        region="us-east-1",
        issue_type="stopped",
        description="Instance stopped ~15d (>7d); no compute charges; attached EBS volumes cost $8.00/month",
        monthly_savings=8.00,  # 100GB gp3 @ $0.08/GB
        severity="Low",
        details={
            "instance_type": "t3.large",
            "state_transition_reason": "User initiated (2025-04-30 09:15:00 GMT)",
            "days_stopped": 15,
            "attached_volumes": [
                {"volume_id": "vol-0a1b2c3d", "volume_type": "gp3", "size_gb": 100, "monthly_cost": 8.00}
            ],
            "compute_cost_when_running": 60.74,  # What it WOULD cost if started
            "tags": [{"Key": "Name", "Value": "web-server-staging-01"}, {"Key": "Environment", "Value": "Staging"}],
        },
        ai_explanation="This t3.large instance has been stopped for 15 days with zero compute charges. The attached 100GB gp3 volume costs $8.00/month. Terminate the instance and delete the volume after verifying no data recovery is needed.",
    ))

    findings.append(Finding(
        resource_id="i-0d3e4f5g6h7i8j9k0",
        resource_type="EC2",
        region="us-east-1",
        issue_type="stopped",
        description="Instance stopped ~28d (>7d); no compute charges; attached EBS volumes cost $12.00/month",
        monthly_savings=12.00,  # 150GB gp3 @ $0.08/GB
        severity="Medium",
        details={
            "instance_type": "m5.large",
            "state_transition_reason": "User initiated (2025-04-17 14:22:00 GMT)",
            "days_stopped": 28,
            "attached_volumes": [
                {"volume_id": "vol-0d3e4f5g", "volume_type": "gp3", "size_gb": 150, "monthly_cost": 12.00}
            ],
            "compute_cost_when_running": 70.08,
            "tags": [{"Key": "Name", "Value": "batch-processor-dev"}, {"Key": "Environment", "Value": "Development"}],
        },
        ai_explanation="This m5.large development instance has been stopped for 28 days. No compute charges, but 150GB gp3 volume costs $12.00/month. Terminate and delete volume after creating AMI if needed.",
    ))

    findings.append(Finding(
        resource_id="i-0g5h6i7j8k9l0m1n2",
        resource_type="EC2",
        region="us-east-2",
        issue_type="stopped",
        description="Instance stopped ~45d (>7d); no compute charges; attached EBS volumes cost $8.00/month",
        monthly_savings=8.00,  # 100GB gp2 @ $0.10/GB = $10, but using gp3 pricing
        severity="Low",
        details={
            "instance_type": "t3.xlarge",
            "state_transition_reason": "User initiated (2025-03-31 18:45:00 GMT)",
            "days_stopped": 45,
            "attached_volumes": [
                {"volume_id": "vol-0g5h6i7j", "volume_type": "gp3", "size_gb": 100, "monthly_cost": 8.00}
            ],
            "compute_cost_when_running": 121.47,
            "tags": [{"Key": "Name", "Value": "legacy-app-migration"}, {"Key": "Project", "Value": "Migration-2024"}],
        },
        ai_explanation="This t3.xlarge instance stopped 45 days ago has zero compute charges. The 100GB volume costs $8.00/month. Migration project completed; terminate immediately after verifying no data recovery needs.",
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
    # RDS Findings (2 findings) - NOW WITH MULTI-AZ PRICING
    # -------------------------------------------------------------------------
    findings.append(Finding(
        resource_id="db-prod-analytics",
        resource_type="RDS",
        region="us-east-1",
        issue_type="zero_connections",
        description="No database connections observed in 14d (Multi-AZ)",
        monthly_savings=205.20,  # $342 * 0.6 for zero_connections finding
        severity="High",
        details={
            "db_instance_class": "db.m5.large",
            "engine": "postgres",
            "multi_az": True,
            "deployment_option": "Multi-AZ",
            "max_connections_14d": 0,
            "allocated_storage": 100,
            "tags": [{"Key": "Name", "Value": "analytics-db"}, {"Key": "Environment", "Value": "Production"}],
        },
        ai_explanation="This Multi-AZ db.m5.large PostgreSQL instance has had zero connections for 21 days, costing ~$342/month full rate. The 60% savings estimate ($205/month) assumes the instance could be deleted. Take a final snapshot and delete after confirming the analytics pipeline was migrated.",
    ))

    findings.append(Finding(
        resource_id="db-staging-cache",
        resource_type="RDS",
        region="us-east-1",
        issue_type="stopped",
        description="RDS instance (Single-AZ) is stopped but still billed for storage",
        monthly_savings=59.86,  # db.t3.medium Single-AZ ~$0.082/hr * 730
        severity="Medium",
        details={
            "db_instance_class": "db.t3.medium",
            "engine": "mysql",
            "multi_az": False,
            "deployment_option": "Single-AZ",
            "allocated_storage": 150,
            "tags": [{"Key": "Name", "Value": "staging-cache-db"}, {"Key": "Environment", "Value": "Staging"}],
        },
        ai_explanation="This stopped db.t3.medium MySQL Single-AZ instance is billed for storage. Since staging environments should be ephemeral, snapshot the data and delete the instance to eliminate $59.86/month in charges.",
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
    # S3 Finding (1 finding) - NOW WITH CLOUDWATCH-BASED SAVINGS
    # -------------------------------------------------------------------------
    findings.append(Finding(
        resource_id="legacy-data-archive-prod",
        resource_type="S3",
        region="us-east-1",
        issue_type="missing_lifecycle",
        description="Bucket (500 GB) has no lifecycle policy. Tiering objects >30d to S3-IA saves ~$4.60/month",
        monthly_savings=4.60,  # 500 GB * $0.023 * 40%
        severity="Medium",
        details={
            "bucket_name": "legacy-data-archive-prod",
            "size_gb": 500.0,
            "size_source": "cloudwatch",
            "estimated_current_monthly_cost": 11.50,
            "creation_date": "2023-06-15T10:30:00+00:00",
            "tags": [{"Key": "Name", "Value": "legacy-data-archive-prod"}, {"Key": "DataClassification", "Value": "Internal"}],
        },
        ai_explanation="This 500GB bucket stores data in Standard storage class without lifecycle policies. Adding a policy to transition objects >30d to S3-IA saves ~$4.60/month. Objects >90d could move to Glacier for 85% savings.",
    ))

    # -------------------------------------------------------------------------
    # EBS Snapshot Findings (3 findings) - NEW SCANNER
    # -------------------------------------------------------------------------
    findings.append(Finding(
        resource_id="snap-0abc123def456789a",
        resource_type="EBS Snapshot",
        region="us-east-1",
        issue_type="orphaned_snapshot",
        description="Snapshot (150 GB, 120d old) has no associated volume or AMI. Source volume vol-deleted1 no longer exists.",
        monthly_savings=7.50,  # 150 GB * $0.05
        severity="Medium",
        details={
            "snapshot_id": "snap-0abc123def456789a",
            "volume_id": "vol-deleted1",
            "size_gb": 150,
            "age_days": 120,
            "start_time": "2025-01-15T08:30:00+00:00",
            "description": "Automated backup from old web server",
            "encrypted": True,
            "name": "web-server-backup-jan",
            "tags": [{"Key": "Name", "Value": "web-server-backup-jan"}],
        },
        ai_explanation="This 150GB snapshot is 120 days old and its source volume no longer exists. It's not backing any AMI. Delete to save $7.50/month.",
    ))

    findings.append(Finding(
        resource_id="snap-0def456789abc1234b",
        resource_type="EBS Snapshot",
        region="us-east-1",
        issue_type="orphaned_snapshot",
        description="Snapshot (200 GB, 90d old) has no associated volume or AMI. Source volume vol-deleted2 no longer exists.",
        monthly_savings=10.00,  # 200 GB * $0.05
        severity="Medium",
        details={
            "snapshot_id": "snap-0def456789abc1234b",
            "volume_id": "vol-deleted2",
            "size_gb": 200,
            "age_days": 90,
            "start_time": "2025-02-15T14:20:00+00:00",
            "description": "Database backup before migration",
            "encrypted": True,
            "name": "db-migration-backup",
            "tags": [{"Key": "Name", "Value": "db-migration-backup"}],
        },
        ai_explanation="This 200GB database migration snapshot is 90 days old. Migration completed successfully; source volume deleted. Delete snapshot to save $10.00/month.",
    ))

    findings.append(Finding(
        resource_id="snap-0ghi789abc123def4c",
        resource_type="EBS Snapshot",
        region="us-east-1",
        issue_type="orphaned_snapshot",
        description="Snapshot (500 GB, 180d old) has no associated volume or AMI. Source volume vol-deleted3 no longer exists.",
        monthly_savings=25.00,  # 500 GB * $0.05
        severity="High",
        details={
            "snapshot_id": "snap-0ghi789abc123def4c",
            "volume_id": "vol-deleted3",
            "size_gb": 500,
            "age_days": 180,
            "start_time": "2024-11-15T22:00:00+00:00",
            "description": "Legacy application data archive",
            "encrypted": False,
            "name": "legacy-app-archive",
            "tags": [{"Key": "Name", "Value": "legacy-app-archive"}, {"Key": "Project", "Value": "Sunset-2024"}],
        },
        ai_explanation="This 500GB snapshot from a sunset project is 180 days old with no associated resources. Delete immediately to save $25.00/month. Verify no compliance retention requirements first.",
    ))

    # -------------------------------------------------------------------------
    # Reserved Instance Opportunity (1 finding) - NEW SCANNER
    # -------------------------------------------------------------------------
    findings.append(Finding(
        resource_id="ri-opportunity-m5.large",
        resource_type="Reserved Instance",
        region="global",
        issue_type="ri_opportunity",
        description="4x m5.large running on-demand for 30+ days without RI coverage. 1-year no-upfront RI saves 37%.",
        monthly_savings=103.30,  # 4 * $0.096 * 0.37 * 730
        severity="High",
        details={
            "instance_type": "m5.large",
            "ondemand_count": 4,
            "covered_by_ri": 0,
            "uncovered_count": 4,
            "hourly_ondemand_rate": 0.096,
            "estimated_ri_rate": 0.0605,
            "savings_per_instance_monthly": 25.82,
            "regions": {"us-east-1": 3, "us-west-2": 1},
            "sample_instance_ids": ["i-prod1", "i-prod2", "i-prod3", "i-prod4"],
        },
        ai_explanation="You have 4 m5.large instances (3 in us-east-1, 1 in us-west-2) running on-demand for 30+ days. These are stable production workloads. Purchasing 4x 1-year no-upfront Regional RIs saves $103.30/month (37%).",
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
