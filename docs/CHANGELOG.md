# Changelog

All notable changes and improvements to the AWS Cost Audit Tool.

---

## [3.0.0] - 2024-05-15

### New Scanners

#### Savings Plans Scanner (`scanners/savings_plans.py`)

Analyzes AWS Savings Plans coverage and utilization using Cost Explorer API.

**What it does:**
- Checks if EC2/Fargate spend is adequately covered by Savings Plans
- Identifies underutilized Savings Plans (paying for unused commitment)
- Calculates potential savings from purchasing Savings Plans

**Code explanation:**
```python
def scan_savings_plans(session: Any) -> List[Finding]:
    ce = session.client("ce", region_name="us-east-1")  # Cost Explorer is us-east-1 only

    # Get last 30 days of data
    time_period = {
        "Start": start_date.strftime("%Y-%m-%d"),
        "End": end_date.strftime("%Y-%m-%d"),
    }

    # Check coverage: How much on-demand spend could be covered?
    coverage_finding = _check_coverage(ce, time_period)

    # Check utilization: Are existing Savings Plans being used?
    utilization_finding = _check_utilization(ce, time_period)
```

**API calls:**
- `ce.get_savings_plans_coverage()` - Returns on-demand vs covered spend
- `ce.get_savings_plans_utilization()` - Returns commitment vs actual usage

**Thresholds:**
| Metric | Threshold | Finding |
|--------|-----------|---------|
| Coverage | < 50% | Low coverage - recommend purchasing SP |
| Utilization | < 80% | Low utilization - wasted commitment |
| Minimum spend | > $500/month | Only flag significant spend |

---

#### Compute Optimizer Scanner (`scanners/compute_optimizer.py`)

Retrieves ML-based EC2 rightsizing recommendations from AWS Compute Optimizer.

**What it does:**
- Gets recommendations for over-provisioned EC2 instances
- Filters by performance risk (only low-risk recommendations)
- Calculates savings from downsizing

**Code explanation:**
```python
def scan_compute_optimizer(session: Any) -> List[Finding]:
    client = session.client("compute-optimizer", region_name="us-east-1")

    # Step 1: Check if opted in (requires explicit enrollment)
    if not _is_opted_in(client):
        return []  # Gracefully skip

    # Step 2: Get all EC2 recommendations with pagination
    recommendations = _get_all_recommendations(client)

    # Step 3: Filter to over-provisioned with low performance risk
    for rec in recommendations:
        if rec.get("finding") == "Overprovisioned":
            if performance_risk <= 2.0:  # Low risk only
                findings.append(_recommendation_to_finding(rec))
```

**API calls:**
- `compute-optimizer.get_enrollment_status()` - Check if opted in
- `compute-optimizer.get_ec2_instance_recommendations()` - Get ML recommendations

**Requirements:**
- AWS Compute Optimizer must be enabled (opt-in required)
- Instances need 14+ days of CloudWatch metrics
- Gracefully skips if not available

---

#### Trusted Advisor Scanner (`scanners/trusted_advisor.py`)

Retrieves cost optimization recommendations from AWS Trusted Advisor.

**What it does:**
- Gets cost_optimizing pillar recommendations
- Filters to warning/error status only (actionable items)
- Extracts estimated monthly savings

**Code explanation:**
```python
def scan_trusted_advisor(session: Any) -> List[Finding]:
    client = session.client("trustedadvisor", region_name="us-east-1")

    # Get recommendations with pagination
    for status in ["warning", "error"]:
        response = client.list_recommendations(
            pillar="cost_optimizing",
            status=status,
            maxResults=100,
        )
        recommendations.extend(response.get("recommendationSummaries", []))
```

**API calls:**
- `trustedadvisor.list_recommendations()` - Get cost optimization checks

**Requirements:**
- AWS Business or Enterprise Support plan required
- Gracefully handles `SubscriptionRequiredException`
- Returns empty list for accounts without support plan

---

### Bug Fixes

#### DLM Tag Detection (`scanners/snapshots.py`)

**Problem:** Snapshot scanner was flagging AWS Data Lifecycle Manager (DLM) managed snapshots as orphaned.

**Root cause:** Missing DLM-specific tags in the managed tag detection list.

**Fix:** Added AWS DLM tags per official documentation:
```python
_MANAGED_TAG_KEYS = frozenset({
    # AWS Backup managed snapshots
    "aws:backup:source-resource-arn",
    "aws:backup:recovery-point-arn",

    # Data Lifecycle Manager (DLM) managed snapshots
    "dlm:managed",
    "aws:dlm:lifecycle-policy-id",      # Primary DLM tag
    "aws:dlm:lifecycle-schedule-name",  # Schedule name
    "aws:dlm:expirationTime",           # Age-based expiration
})
```

**Source:** [AWS DLM Documentation](https://docs.aws.amazon.com/ebs/latest/userguide/dlm-elements.html)

---

#### PDF Table Breaks (`reports/templates/report.html`)

**Problem:** PDF tables were splitting rows across page boundaries, making reports hard to read.

**Fix:** Added CSS rules to prevent page breaks inside table rows:
```css
table.findings thead {
    display: table-header-group;  /* Repeat header on each page */
}

table.findings tr {
    break-inside: avoid;          /* Modern browsers */
    page-break-inside: avoid;     /* Legacy support */
}

.rec-block {
    break-inside: avoid;
    page-break-inside: avoid;
}
```

---

### IAM Policy Updates

Added 6 new read-only permissions for new scanners:

```json
{
    "Effect": "Allow",
    "Action": [
        "ce:GetSavingsPlansCoverage",
        "ce:GetSavingsPlansUtilization",
        "compute-optimizer:GetEnrollmentStatus",
        "compute-optimizer:GetEC2InstanceRecommendations",
        "trustedadvisor:ListRecommendations",
        "trustedadvisor:GetRecommendation"
    ],
    "Resource": "*"
}
```

**Total IAM actions:** 38 (all read-only, verified no Create/Delete/Put/Update)

---

### Model Updates

Added new resource types to Finding model (`models/finding.py`):

```python
valid_types = [
    "EC2", "RDS", "EBS", "EIP", "S3", "Cost Explorer",
    "EBS Snapshot", "Reserved Instance",
    "SavingsPlans",      # New: Savings Plans scanner
    "TrustedAdvisor",    # New: Trusted Advisor scanner
]
```

---

### Test Coverage

Added 9 new tests for new scanners:

| Test | Description |
|------|-------------|
| `test_snapshot_scanner_skips_dlm_lifecycle_policy_id` | DLM tag detection |
| `test_savings_plans_low_coverage_generates_finding` | Coverage gap detection |
| `test_savings_plans_empty_data_returns_empty` | Empty data handling |
| `test_savings_plans_access_denied_returns_empty` | Permission error handling |
| `test_compute_optimizer_not_opted_in_returns_empty` | Opt-in check |
| `test_compute_optimizer_over_provisioned_generates_finding` | Rightsizing recommendation |
| `test_compute_optimizer_access_denied_returns_empty` | Permission error handling |
| `test_trusted_advisor_subscription_required_returns_empty` | Support plan check |
| `test_trusted_advisor_warning_generates_finding` | Warning recommendation |

**Total tests:** 64 core tests passing

---

## [2.0.0] - Previous Release

- EC2, RDS, EBS, EIP, S3, Cost Explorer scanners
- AI-powered summaries via OpenRouter
- Professional PDF report generation
- Multi-region parallel scanning

---

## Architecture Overview

### Scanner Pattern

All scanners follow the same pattern:

```python
def scan_<resource>(session: Any, regions: List[str] = None) -> List[Finding]:
    """
    1. Create boto3 client
    2. Handle permission errors gracefully
    3. Paginate through all resources
    4. Filter for wasteful resources
    5. Return List[Finding]
    """
```

### Finding Model

```python
@dataclass
class Finding:
    resource_id: str        # e.g., "i-1234567890abcdef0"
    resource_type: str      # "EC2", "RDS", "EBS", etc.
    region: str             # "us-east-1"
    issue_type: str         # "stopped", "low_utilization", etc.
    description: str        # Human-readable explanation
    monthly_savings: float  # Estimated savings in USD
    severity: str           # "High", "Medium", "Low"
    details: Dict           # Additional metadata
```

### Error Handling

All scanners handle these AWS errors gracefully:
- `AccessDeniedException` - Skip scanner, log info
- `SubscriptionRequiredException` - Skip Trusted Advisor
- `OptInRequiredException` - Skip Compute Optimizer
- `DataUnavailableException` - Skip Cost Explorer metrics

---

## API Reference

### Cost Explorer (us-east-1 only)

```python
# Savings Plans Coverage
ce.get_savings_plans_coverage(
    TimePeriod={"Start": "2024-01-01", "End": "2024-01-31"},
    Granularity="MONTHLY"
)

# Savings Plans Utilization
ce.get_savings_plans_utilization(
    TimePeriod={"Start": "2024-01-01", "End": "2024-01-31"},
    Granularity="MONTHLY"
)
```

### Compute Optimizer (us-east-1 only)

```python
# Check enrollment
compute_optimizer.get_enrollment_status()

# Get recommendations
compute_optimizer.get_ec2_instance_recommendations(
    maxResults=100,
    nextToken="..."  # Pagination
)
```

### Trusted Advisor (us-east-1 only)

```python
# List cost optimization recommendations
trustedadvisor.list_recommendations(
    pillar="cost_optimizing",
    status="warning",  # or "error"
    maxResults=100
)
```
