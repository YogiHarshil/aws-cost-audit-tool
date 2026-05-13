# Data Model: AWS Cost Audit Tool

**Feature**: 001-aws-cost-audit
**Date**: 2026-05-13
**Purpose**: Define core data structures for audit findings and reports

---

## Overview

The AWS Cost Audit Tool uses Python dataclasses to represent audit findings, reports, and configuration. All models use type hints and include validation logic where appropriate.

---

## Entity: Finding

Represents a single wasteful AWS resource discovered during the audit.

### Dataclass Definition

```python
from dataclasses import dataclass, field
from typing import Dict, Optional
from datetime import datetime

@dataclass
class Finding:
    """Represents a single wasteful AWS resource."""

    resource_id: str  # e.g., "i-1234567890abcdef0", "vol-abc123"
    resource_type: str  # "EC2", "RDS", "EBS", "EIP", "S3"
    region: str  # AWS region code, e.g., "us-east-1"
    issue_type: str  # "stopped", "low_utilization", "unattached", etc.
    description: str  # Human-readable explanation of the issue
    monthly_savings: float  # Estimated monthly savings in USD
    severity: str  # "High", "Medium", or "Low"
    details: Dict  # Additional metadata (instance type, size, tags, etc.)
    ai_explanation: Optional[str] = None  # AI-generated explanation (nullable)
    discovered_at: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self):
        """Validate field values."""
        # Validate severity
        if self.severity not in ["High", "Medium", "Low"]:
            raise ValueError(f"Invalid severity: {self.severity}")

        # Validate monthly_savings
        if self.monthly_savings < 0:
            raise ValueError(f"Negative savings not allowed: {self.monthly_savings}")

        # Validate resource_type
        valid_types = ["EC2", "RDS", "EBS", "EIP", "S3", "Cost Explorer"]
        if self.resource_type not in valid_types:
            raise ValueError(f"Invalid resource_type: {self.resource_type}")
```

### Field Descriptions

| Field | Type | Description | Constraints |
|-------|------|-------------|-------------|
| `resource_id` | str | AWS resource identifier | Required, non-empty |
| `resource_type` | str | Service category | Must be in: EC2, RDS, EBS, EIP, S3, Cost Explorer |
| `region` | str | AWS region code | Required, e.g., "us-east-1" |
| `issue_type` | str | Type of waste detected | e.g., "stopped", "low_utilization", "unattached" |
| `description` | str | Human-readable summary | Required, used in report |
| `monthly_savings` | float | Estimated monthly USD savings | >= 0 |
| `severity` | str | Impact level | Must be: "High", "Medium", or "Low" |
| `details` | Dict | Additional context | Free-form dict, scanner-specific |
| `ai_explanation` | Optional[str] | AI-generated explanation | Nullable (if --skip-ai or API fails) |
| `discovered_at` | datetime | Timestamp of discovery | Auto-set to current UTC time |

### Example Instances

**EC2 Stopped Instance:**
```python
Finding(
    resource_id="i-0123456789abcdef0",
    resource_type="EC2",
    region="us-east-1",
    issue_type="stopped",
    description="Instance stopped for 12 days",
    monthly_savings=43.80,
    severity="High",
    details={
        "instance_type": "t3.medium",
        "stopped_date": "2026-05-01",
        "tags": [{"Key": "Name", "Value": "test-server"}]
    }
)
```

**RDS Zero Connections:**
```python
Finding(
    resource_id="mydb-instance",
    resource_type="RDS",
    region="us-west-2",
    issue_type="zero_connections",
    description="No database connections in 14 days",
    monthly_savings=175.20,
    severity="High",
    details={
        "db_instance_class": "db.m5.large",
        "engine": "PostgreSQL",
        "allocated_storage": 100
    }
)
```

**EBS Unattached Volume:**
```python
Finding(
    resource_id="vol-abc123def456",
    resource_type="EBS",
    region="eu-west-1",
    issue_type="unattached",
    description="Volume unattached (available state)",
    monthly_savings=10.00,
    severity="Medium",
    details={
        "volume_type": "gp3",
        "size": 100,
        "created_date": "2025-12-15"
    }
)
```

---

## Entity: Report

Aggregates all findings from a complete audit run.

### Dataclass Definition

```python
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime

@dataclass
class Report:
    """Complete audit report for an AWS account."""

    account_id: str  # AWS account ID
    account_alias: str  # AWS account alias (or account_id if no alias)
    client_name: str  # Client name for report cover
    scan_date: datetime  # When the scan was performed
    regions_scanned: List[str]  # List of regions included in scan
    findings: List[Finding]  # All findings, sorted by savings DESC
    total_savings: float  # Sum of all finding savings
    cost_trends: Dict  # Cost Explorer data (service spend, trends)
    executive_summary: Optional[str] = None  # AI-generated summary
    recommendations: Optional[List[Dict]] = None  # Top 5 AI recommendations
    scan_duration_seconds: float = 0.0  # Total scan time
    scan_metadata: Dict = field(default_factory=dict)  # Additional context

    def __post_init__(self):
        """Validate and compute derived fields."""
        # Validate regions_scanned not empty
        if not self.regions_scanned:
            raise ValueError("regions_scanned cannot be empty")

        # Compute total_savings from findings if not set
        if self.total_savings == 0 and self.findings:
            self.total_savings = sum(f.monthly_savings for f in self.findings)

        # Sort findings by savings DESC
        self.findings.sort(key=lambda f: f.monthly_savings, reverse=True)

    @property
    def findings_count(self) -> int:
        """Total number of findings."""
        return len(self.findings)

    @property
    def findings_by_severity(self) -> Dict[str, int]:
        """Count findings by severity level."""
        counts = {"High": 0, "Medium": 0, "Low": 0}
        for finding in self.findings:
            counts[finding.severity] += 1
        return counts

    @property
    def findings_by_type(self) -> Dict[str, int]:
        """Count findings by resource type."""
        counts = {}
        for finding in self.findings:
            counts[finding.resource_type] = counts.get(finding.resource_type, 0) + 1
        return counts

    def get_findings_by_region(self, region: str) -> List[Finding]:
        """Get all findings for a specific region."""
        return [f for f in self.findings if f.region == region]
```

### Field Descriptions

| Field | Type | Description | Constraints |
|-------|------|-------------|-------------|
| `account_id` | str | AWS account ID | Required, 12-digit string |
| `account_alias` | str | Account alias or ID | Fallback to account_id if no alias |
| `client_name` | str | Client name for report | Used on cover page |
| `scan_date` | datetime | Scan timestamp | UTC datetime |
| `regions_scanned` | List[str] | Regions included | Must not be empty |
| `findings` | List[Finding] | All findings | Sorted by savings DESC |
| `total_savings` | float | Sum of all savings | Auto-computed if 0 |
| `cost_trends` | Dict | Cost Explorer data | Service spend, MoM trends |
| `executive_summary` | Optional[str] | AI summary | Nullable |
| `recommendations` | Optional[List[Dict]] | Top 5 recs | Nullable |
| `scan_duration_seconds` | float | Total scan time | Measured from start to end |
| `scan_metadata` | Dict | Additional context | Scanner versions, errors, etc. |

### Example Instance

```python
Report(
    account_id="123456789012",
    account_alias="acme-prod",
    client_name="Acme Corp",
    scan_date=datetime(2026, 5, 13, 10, 30, 0),
    regions_scanned=["us-east-1", "us-west-2", "eu-west-1"],
    findings=[finding1, finding2, finding3],  # List of Finding objects
    total_savings=4832.50,
    cost_trends={
        "daily_costs": {"2026-05-01": 1250.00, "2026-05-02": 1300.00, ...},
        "top_services": [
            {"service": "EC2", "cost": 2500.00},
            {"service": "RDS", "cost": 1800.00}
        ],
        "month_over_month_change": 12.5  # % increase
    },
    executive_summary="Your AWS account shows significant waste...",
    recommendations=[
        {
            "title": "Terminate 8 stopped EC2 instances",
            "impact": 2400.00,
            "difficulty": "Low",
            "description": "..."
        }
    ],
    scan_duration_seconds=1245.67,
    scan_metadata={
        "tool_version": "1.0.0",
        "errors_encountered": 2,
        "resources_scanned": 347
    }
)
```

---

## Entity: ScanConfig

Configuration for a single audit scan run.

### Dataclass Definition

```python
from dataclasses import dataclass
from typing import List, Dict, Optional

@dataclass
class ScanConfig:
    """Configuration for audit scan."""

    aws_profile: str = "default"
    aws_role_arn: Optional[str] = None
    regions: Optional[List[str]] = None  # None = all enabled regions
    client_name: str = "Client"
    openai_api_key: Optional[str] = None
    skip_ai: bool = False
    output_dir: str = "./output"
    exclude_tags: List[Dict[str, str]] = None  # Tag filters
    verbose: bool = False

    def __post_init__(self):
        """Validate configuration."""
        # Initialize exclude_tags if None
        if self.exclude_tags is None:
            self.exclude_tags = []

        # Validate OpenAI key if AI enabled
        if not self.skip_ai and not self.openai_api_key:
            raise ValueError(
                "OPENAI_API_KEY required when AI summaries enabled. "
                "Set key or use --skip-ai flag."
            )

        # Validate output directory exists or can be created
        import os
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir, exist_ok=True)

    @classmethod
    def from_env_and_args(cls, args):
        """Create config from environment variables and CLI args."""
        import os
        from utils.tag_filter import parse_exclude_tags

        return cls(
            aws_profile=args.profile or os.getenv('AWS_PROFILE', 'default'),
            aws_role_arn=os.getenv('AWS_ROLE_ARN'),
            regions=args.region.split(',') if args.region else None,
            client_name=args.client_name or os.getenv('CLIENT_NAME', 'Client'),
            openai_api_key=os.getenv('OPENAI_API_KEY'),
            skip_ai=args.skip_ai,
            output_dir=args.output or os.getenv('OUTPUT_DIR', './output'),
            exclude_tags=parse_exclude_tags(
                args.exclude_tags or os.getenv('EXCLUDE_TAGS', '')
            ),
            verbose=args.verbose
        )
```

### Field Descriptions

| Field | Type | Description | Default |
|-------|------|-------------|---------|
| `aws_profile` | str | AWS CLI profile name | "default" |
| `aws_role_arn` | Optional[str] | IAM role ARN to assume | None |
| `regions` | Optional[List[str]] | Specific regions to scan | None (all) |
| `client_name` | str | Client name for report | "Client" |
| `openai_api_key` | Optional[str] | OpenAI API key | None |
| `skip_ai` | bool | Disable AI summaries | False |
| `output_dir` | str | Output directory path | "./output" |
| `exclude_tags` | List[Dict[str, str]] | Tag exclusion filters | [] |
| `verbose` | bool | Enable debug logging | False |

---

## Relationships

```
Report
  ├── findings: List[Finding]
  │     Each Finding represents one wasteful resource
  │
  ├── cost_trends: Dict
  │     From Cost Explorer scanner
  │
  ├── executive_summary: Optional[str]
  │     From AI summarizer (if not --skip-ai)
  │
  └── recommendations: Optional[List[Dict]]
        From AI recommender (if not --skip-ai)

ScanConfig
  └── Used by main.py to initialize scanners
      Passed to each scanner for tag filtering
```

---

## Validation Rules Summary

### Finding
- ✅ `severity` in ["High", "Medium", "Low"]
- ✅ `monthly_savings` >= 0
- ✅ `resource_type` in valid service types
- ✅ `discovered_at` auto-set to UTC now

### Report
- ✅ `regions_scanned` not empty
- ✅ `total_savings` auto-computed from findings
- ✅ `findings` auto-sorted by savings DESC

### ScanConfig
- ✅ `openai_api_key` required if not `skip_ai`
- ✅ `output_dir` created if doesn't exist
- ✅ `exclude_tags` initialized to empty list if None

---

## Usage Examples

### Creating Findings in Scanners

```python
# In scanners/ec2.py
def analyze_stopped_instance(instance: Dict, region: str, price: float) -> Finding:
    """Create Finding for stopped EC2 instance."""
    return Finding(
        resource_id=instance['InstanceId'],
        resource_type="EC2",
        region=region,
        issue_type="stopped",
        description=f"Instance stopped for {days_stopped} days",
        monthly_savings=price * 730,  # hourly rate × 730 hours/month
        severity="High",
        details={
            "instance_type": instance['InstanceType'],
            "stopped_date": instance['StateTransitionReason'],
            "tags": instance.get('Tags', [])
        }
    )
```

### Building a Report

```python
# In main.py
def run_audit(config: ScanConfig) -> Report:
    """Execute complete audit and return report."""

    # Run all scanners
    all_findings = []
    all_findings.extend(ec2_scanner.scan_all_regions(config))
    all_findings.extend(rds_scanner.scan_all_regions(config))
    # ... other scanners

    # Get cost trends
    cost_trends = cost_explorer_scanner.get_trends()

    # Generate AI content (if enabled)
    executive_summary = None
    recommendations = None
    if not config.skip_ai:
        executive_summary = summarizer.generate(all_findings, cost_trends)
        recommendations = recommender.generate_top_5(all_findings)

    # Build report
    report = Report(
        account_id=get_account_id(),
        account_alias=get_account_alias(),
        client_name=config.client_name,
        scan_date=datetime.utcnow(),
        regions_scanned=get_scanned_regions(),
        findings=all_findings,
        total_savings=0,  # Auto-computed in __post_init__
        cost_trends=cost_trends,
        executive_summary=executive_summary,
        recommendations=recommendations
    )

    return report
```

---

## State Transitions

**N/A** - This is a stateless tool. No state machines or lifecycle management needed. All entities are immutable once created (dataclasses with frozen=False for flexibility, but not modified after creation).

---

## Serialization

### To JSON (for debugging/logging)

```python
import json
from dataclasses import asdict
from datetime import datetime

def serialize_finding(finding: Finding) -> str:
    """Convert Finding to JSON string."""
    def json_serial(obj):
        """Handle datetime serialization."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Type {type(obj)} not serializable")

    return json.dumps(asdict(finding), default=json_serial, indent=2)
```

### To PDF (via Jinja2)

Findings and Report are passed directly to Jinja2 templates as Python objects. Template accesses fields using dot notation:

```jinja2
{% for finding in findings %}
  <tr>
    <td>{{ finding.resource_id }}</td>
    <td>{{ finding.resource_type }}</td>
    <td>${{ "{:,.2f}".format(finding.monthly_savings) }}</td>
  </tr>
{% endfor %}
```

---

## Next Steps

1. Implement these dataclasses in `models/finding.py` and `models/report.py`
2. Write unit tests in `tests/test_models.py` to verify validation logic
3. Use these models consistently across all scanners and report generation
