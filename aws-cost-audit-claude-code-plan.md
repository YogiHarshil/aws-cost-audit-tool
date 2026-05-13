# AWS Cost Audit Tool — Claude Code Implementation Plan

> **PURPOSE:** Feed this document to Claude Code. Execute phase by phase in order. Each phase must fully work before starting the next.
>
> **CRITICAL:** Do NOT skip phases. Do NOT combine phases. Test each phase before proceeding.

---

## Project Overview

**What we are building:** A Python CLI tool that scans a client's AWS account via read-only IAM access, detects cost waste across EC2, RDS, EBS, EIP, S3, and Cost Explorer, generates AI-enhanced findings, and produces a professional PDF audit report.

**Final output:** `python main.py --profile <aws_profile>` runs a full scan and outputs a PDF report.

---

## Tech Stack (Locked — Do Not Change)

- Python 3.12+
- boto3 (AWS SDK)
- Jinja2 (HTML templating)
- WeasyPrint (HTML to PDF)
- OpenAI API (AI summaries — partner integration)
- python-dotenv (env config)
- concurrent.futures (parallel scanning)
- dataclasses (data models)
- pytest (testing)

---

## PHASE 1 — Project Setup and Data Models

**Goal:** Create the project structure, install dependencies, define all data models, and set up AWS client utility.

### Step 1.1 — Initialize project

Create this exact folder structure:

```
aws-cost-audit/
├── scanners/
│   └── __init__.py
├── ai/
│   └── __init__.py
├── reports/
│   ├── templates/
│   └── __init__.py
├── models/
│   └── __init__.py
├── utils/
│   └── __init__.py
├── tests/
│   └── __init__.py
├── output/
├── main.py
├── config.py
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

### Step 1.2 — Create requirements.txt

```
boto3>=1.34.0
jinja2>=3.1.0
weasyprint>=60.0
openai>=1.30.0
python-dotenv>=1.0.0
pytest>=8.0.0
```

### Step 1.3 — Create .env.example

```
# AWS Configuration
# Option A: Use an AWS CLI profile name
AWS_PROFILE=default

# Option B: Use cross-account IAM role ARN (preferred for client audits)
# AWS_ROLE_ARN=arn:aws:iam::123456789012:role/CostAuditRole

# Option C: Use access keys directly (least preferred)
# AWS_ACCESS_KEY_ID=
# AWS_SECRET_ACCESS_KEY=

# Client info for report
CLIENT_NAME=Acme Corp
CLIENT_ACCOUNT_ID=123456789012

# OpenAI (for AI-enhanced summaries)
OPENAI_API_KEY=sk-xxx

# Output
REPORT_OUTPUT_DIR=./output

# Scan configuration
# Comma-separated list of regions to scan. Leave empty to scan all enabled regions.
SCAN_REGIONS=
# Number of days to look back for idle detection
IDLE_THRESHOLD_DAYS=14
# CPU utilization percentage below which an instance is considered idle
CPU_IDLE_THRESHOLD=5.0
```

### Step 1.4 — Create .gitignore

```
__pycache__/
*.pyc
.env
output/*.pdf
output/*.json
.venv/
venv/
*.egg-info/
dist/
build/
.pytest_cache/
```

### Step 1.5 — Create config.py

Load all configuration from environment variables. Use python-dotenv to read from .env file.

Define a Config dataclass with ALL fields from .env.example. Include validation:
- If AWS_ROLE_ARN is set, use cross-account role assumption
- If AWS_PROFILE is set, use named profile
- If neither, fall back to default credentials chain
- IDLE_THRESHOLD_DAYS defaults to 14
- CPU_IDLE_THRESHOLD defaults to 5.0
- REPORT_OUTPUT_DIR defaults to ./output
- SCAN_REGIONS: if empty string or not set, scan all enabled regions

Include a `load_config()` function that returns a Config instance. Raise clear errors if CLIENT_NAME is missing.

### Step 1.6 — Create models/finding.py

Define a `Finding` dataclass:

```python
@dataclass
class Finding:
    service: str           # "EC2", "RDS", "EBS", "EIP", "S3"
    resource_id: str       # AWS resource ID (i-xxx, vol-xxx, etc.)
    resource_name: str     # Name tag value or empty string
    region: str            # us-east-1, etc.
    finding_type: str      # "idle", "stopped", "unattached", "oversized", "missing_policy"
    severity: str          # "high", "medium", "low"
    estimated_monthly_savings: float  # USD
    recommended_action: str  # Human-readable action
    details: dict          # Extra data: instance_type, days_idle, cpu_avg, etc.
    ai_explanation: str = ""  # Populated later by AI module
```

Include a `to_dict()` method that returns all fields as a dictionary (for JSON serialization and Jinja2 templates).

### Step 1.7 — Create models/report.py

Define an `AuditReport` dataclass:

```python
@dataclass
class AuditReport:
    client_name: str
    account_id: str
    scan_date: str            # ISO format date
    regions_scanned: list[str]
    scan_duration_seconds: int
    total_monthly_spend: float  # From Cost Explorer
    findings: list[Finding]
    cost_by_service: dict       # {"EC2": 1234.56, "RDS": 567.89, ...}
    cost_trend: list[dict]      # [{"month": "2026-03", "total": 5678.90}, ...]
    ai_executive_summary: str = ""
```

Include these computed properties:
- `total_findings` → len(self.findings)
- `total_estimated_savings` → sum of all finding savings
- `high_severity_count` → count of high severity findings
- `medium_severity_count` → count of medium severity findings
- `low_severity_count` → count of low severity findings
- `findings_by_service` → dict grouping findings by service name
- `top_findings` → top 5 findings sorted by estimated_monthly_savings DESC

Include a `to_dict()` method for Jinja2 template rendering.

### Step 1.8 — Create utils/aws_client.py

Create a function `create_aws_session(config: Config) -> boto3.Session`:

Logic:
1. If config.aws_role_arn is set and not empty:
   - Create a default boto3 session
   - Call sts_client.assume_role(RoleArn=config.aws_role_arn, RoleSessionName='cost-audit', DurationSeconds=3600)
   - Extract temporary credentials from response
   - Return a new boto3.Session with those temporary credentials
2. If config.aws_profile is set:
   - Return boto3.Session(profile_name=config.aws_profile)
3. Else:
   - Return boto3.Session() (default credential chain)

Create a function `get_enabled_regions(session: boto3.Session) -> list[str]`:
- If config.scan_regions is set, return that list
- Otherwise call ec2_client.describe_regions(AllRegions=False) to get all enabled regions
- Return list of region names

Create a function `get_account_id(session: boto3.Session) -> str`:
- Call sts_client.get_caller_identity()
- Return the Account field

### Step 1.9 — Create utils/pricing.py

Create a dictionary of common AWS resource costs for estimation:

```python
EC2_HOURLY_COST = {
    "t3.nano": 0.0052, "t3.micro": 0.0104, "t3.small": 0.0208,
    "t3.medium": 0.0416, "t3.large": 0.0832, "t3.xlarge": 0.1664,
    "t3.2xlarge": 0.3328, "t2.nano": 0.0058, "t2.micro": 0.0116,
    "t2.small": 0.023, "t2.medium": 0.0464, "t2.large": 0.0928,
    "m5.large": 0.096, "m5.xlarge": 0.192, "m5.2xlarge": 0.384,
    "m5.4xlarge": 0.768, "m6i.large": 0.096, "m6i.xlarge": 0.192,
    "c5.large": 0.085, "c5.xlarge": 0.17, "r5.large": 0.126,
    "r5.xlarge": 0.252,
}

RDS_HOURLY_COST = {
    "db.t3.micro": 0.017, "db.t3.small": 0.034, "db.t3.medium": 0.068,
    "db.t3.large": 0.136, "db.m5.large": 0.171, "db.m5.xlarge": 0.342,
    "db.m5.2xlarge": 0.684, "db.r5.large": 0.24, "db.r5.xlarge": 0.48,
    "db.m6i.large": 0.171, "db.m6i.xlarge": 0.342,
}

EBS_MONTHLY_PER_GB = {
    "gp2": 0.10, "gp3": 0.08, "io1": 0.125, "io2": 0.125,
    "st1": 0.045, "sc1": 0.015, "standard": 0.05,
}

EIP_MONTHLY_COST = 3.60  # $0.005/hour when unattached
```

Create helper functions:
- `get_ec2_monthly_cost(instance_type: str) -> float`: look up hourly cost, multiply by 730 (hours/month). Return 0.0 if instance type not in dict.
- `get_rds_monthly_cost(instance_class: str, multi_az: bool) -> float`: hourly × 730. If multi_az, multiply by 2.
- `get_ebs_monthly_cost(volume_type: str, size_gb: int) -> float`: per-GB rate × size.

### Step 1.10 — Write test for Phase 1

Create `tests/test_models.py`:
- Test Finding creation with all fields
- Test Finding.to_dict() returns correct keys
- Test AuditReport computed properties (total_findings, total_estimated_savings, top_findings sorting)
- Test pricing helpers with known instance types

Create `tests/test_config.py`:
- Test config loads with mock .env values
- Test config defaults work when optional fields missing

Run all tests. All must pass before proceeding.

**PHASE 1 VERIFICATION:** Run `pytest tests/` — all tests must pass. Run `python -c "from config import load_config"` — must not crash (can fail on missing .env, that's fine).

---

## PHASE 2 — AWS Scanners

**Goal:** Build all 6 scanners. Each scanner is a standalone module that takes a boto3 session + region + config and returns a list of Finding objects.

### Step 2.1 — Create scanners/ec2.py

Function `scan_ec2(session: boto3.Session, region: str, config: Config) -> list[Finding]`:

**Scan 1 — Stopped instances:**
- Call `ec2.describe_instances(Filters=[{'Name': 'instance-state-name', 'Values': ['stopped']}])`
- For each stopped instance, check `StateTransitionReason` to get approximate stop date
- If stopped for more than config.idle_threshold_days: create Finding with:
  - finding_type = "stopped"
  - severity = "high" if stopped > 30 days, "medium" if > 7 days
  - estimated_monthly_savings = sum of attached EBS volume costs (stopped instances still pay for EBS)
  - recommended_action = "Terminate this instance after verifying it is no longer needed. Create an AMI first if you may need it later."
  - details: include instance_type, launch_time, days_stopped, attached_volume_ids and their sizes

**Scan 2 — Idle running instances:**
- Call `ec2.describe_instances(Filters=[{'Name': 'instance-state-name', 'Values': ['running']}])`
- For each running instance, get CloudWatch CPUUtilization average over config.idle_threshold_days:
  - `cloudwatch.get_metric_statistics(Namespace='AWS/EC2', MetricName='CPUUtilization', Dimensions=[{'Name': 'InstanceId', 'Value': instance_id}], StartTime=now-threshold_days, EndTime=now, Period=86400, Statistics=['Average'])`
  - Calculate overall average from all datapoints
  - If average < config.cpu_idle_threshold: create Finding with:
    - finding_type = "idle"
    - severity = "medium"
    - estimated_monthly_savings = EC2 instance monthly cost from pricing lookup
    - recommended_action = "This instance has averaged {avg}% CPU over {days} days. Consider stopping, rightsizing, or terminating."
    - details: include instance_type, avg_cpu, days_monitored, name_tag

**Error handling:** Wrap each describe call in try/except. Log errors but continue scanning. An error in one instance should not abort the whole scanner. If CloudWatch has no datapoints for an instance (new instance), skip it.

**Name tag extraction:** For each instance, extract the Name tag from Tags list. If no Name tag exists, use empty string.

### Step 2.2 — Create scanners/rds.py

Function `scan_rds(session: boto3.Session, region: str, config: Config) -> list[Finding]`:

- Call `rds.describe_db_instances()`
- For each DB instance, get CloudWatch DatabaseConnections average over config.idle_threshold_days:
  - `cloudwatch.get_metric_statistics(Namespace='AWS/RDS', MetricName='DatabaseConnections', Dimensions=[{'Name': 'DBInstanceIdentifier', 'Value': db_id}], StartTime=now-threshold_days, EndTime=now, Period=86400, Statistics=['Average'])`
  - If average connections == 0 across ALL datapoints (truly zero):
    - finding_type = "idle"
    - severity = "high"
    - estimated_monthly_savings = RDS instance monthly cost (multiply by 2 if MultiAZ)
    - recommended_action = "This RDS instance has had zero connections for {days} days. Create a final snapshot and consider deleting."
    - details: include db_instance_class, engine, multi_az, storage_gb, days_idle

- Also check for instances with `DBInstanceStatus` == 'stopped':
  - RDS stopped instances still incur storage costs
  - finding_type = "stopped"
  - severity = "medium"
  - estimated_monthly_savings = storage cost only (storage_gb * $0.115/GB for gp2)

### Step 2.3 — Create scanners/ebs.py

Function `scan_ebs(session: boto3.Session, region: str, config: Config) -> list[Finding]`:

- Call `ec2.describe_volumes(Filters=[{'Name': 'status', 'Values': ['available']}])`
- 'available' means the volume is NOT attached to any instance — this is pure waste
- For each unattached volume:
  - finding_type = "unattached"
  - severity = "high" if size > 100 GB, "medium" otherwise
  - estimated_monthly_savings = EBS monthly cost from pricing lookup (volume_type × size_gb)
  - recommended_action = "This EBS volume is not attached to any instance. Snapshot it if needed and delete."
  - details: include volume_type, size_gb, create_time, iops (for io1/io2), snapshot_id (if created from snapshot)

### Step 2.4 — Create scanners/eip.py

Function `scan_eip(session: boto3.Session, region: str, config: Config) -> list[Finding]`:

- Call `ec2.describe_addresses()`
- Filter for addresses where 'AssociationId' is NOT present (or is None/empty) AND 'InstanceId' is NOT present
- For each unassociated EIP:
  - finding_type = "unattached"
  - severity = "low"
  - estimated_monthly_savings = 3.60 (constant — $0.005/hour)
  - recommended_action = "This Elastic IP is not associated with any resource. Release it to stop charges."
  - details: include public_ip, allocation_id, domain

### Step 2.5 — Create scanners/s3.py

Function `scan_s3(session: boto3.Session, region: str, config: Config) -> list[Finding]`:

**Important:** S3 is a global service. This scanner should only run ONCE (not per region). Check if region == 'us-east-1' (or the first region in the scan list) before running. Otherwise return empty list.

- Call `s3.list_buckets()`
- For each bucket:

  **Check 1 — Missing lifecycle configuration:**
  - Try `s3.get_bucket_lifecycle_configuration(Bucket=bucket_name)`
  - If raises `ClientError` with code 'NoSuchLifecycleConfiguration':
    - finding_type = "missing_policy"
    - severity = "low"
    - estimated_monthly_savings = 0.0 (cannot estimate without knowing storage size)
    - recommended_action = "This bucket has no lifecycle policy. Old objects accumulate indefinitely. Add a policy to transition objects to S3-IA after 30 days."
    - details: include bucket_name, creation_date

  **Check 2 — Bucket size estimation:**
  - Use CloudWatch metric `BucketSizeBytes` (namespace: AWS/S3, metric: BucketSizeBytes, dimensions: BucketName + StorageType=StandardStorage)
  - If bucket is larger than 100 GB and has no lifecycle policy:
    - Upgrade severity to "medium"
    - estimated_monthly_savings = rough estimate: bucket_size_gb × $0.023 × 0.4 (40% savings from lifecycle tiering)

**Error handling:** Some buckets may be in different regions or have access restrictions. Wrap each bucket check in try/except and skip buckets that throw AccessDenied.

### Step 2.6 — Create scanners/cost_explorer.py

Function `scan_cost_explorer(session: boto3.Session, config: Config) -> tuple[dict, list[dict], float]`:

**This scanner returns 3 things (not findings — raw cost data):**
1. cost_by_service: dict mapping service name to monthly cost
2. cost_trend: list of monthly totals for the past 3 months
3. total_monthly_spend: current month's total

**Query 1 — Cost by service (current month):**
```python
ce.get_cost_and_usage(
    TimePeriod={'Start': first_day_of_month, 'End': today},
    Granularity='MONTHLY',
    Metrics=['UnblendedCost'],
    GroupBy=[{'Type': 'DIMENSION', 'Key': 'SERVICE'}]
)
```
Parse response: for each group in ResultsByTime[0].Groups, extract service name and cost amount. Build dict.

**Query 2 — Monthly trend (last 3 months):**
```python
ce.get_cost_and_usage(
    TimePeriod={'Start': three_months_ago_first_day, 'End': today},
    Granularity='MONTHLY',
    Metrics=['UnblendedCost']
)
```
Parse response: for each month in ResultsByTime, extract start date and total cost. Build list of dicts.

**Query 3 — Total current month spend:**
Sum from Query 1 results or use the total from Query 2 for the current month.

**Date handling:** Use datetime.date.today() for end date. First day of current month = today.replace(day=1). Three months ago = subtract 3 months carefully (handle year rollover). Format all dates as 'YYYY-MM-DD' strings.

**Cost Explorer note:** The Cost Explorer API returns cost values as strings, not floats. Cast them: `float(group['Metrics']['UnblendedCost']['Amount'])`. Round to 2 decimal places.

### Step 2.7 — Create scanners/__init__.py with orchestrator

Create a function `run_all_scanners(session, config) -> tuple[list[Finding], dict, list[dict], float]`:

Logic:
1. Get list of regions to scan (from config or by calling get_enabled_regions)
2. Run Cost Explorer scan first (global, not per-region) — get cost_by_service, cost_trend, total_spend
3. Use `concurrent.futures.ThreadPoolExecutor(max_workers=10)` to run these scanners in parallel across all regions:
   - ec2.scan_ec2 per region
   - rds.scan_rds per region
   - ebs.scan_ebs per region
   - eip.scan_eip per region
4. Run S3 scanner once (passing first region only)
5. Collect all findings into a single list
6. Sort findings by estimated_monthly_savings DESC
7. Return (all_findings, cost_by_service, cost_trend, total_spend)

Include robust error handling per region per scanner. If a scanner fails in one region, log the error and continue with other regions. Never let a single region failure abort the entire audit.

Print progress: `print(f"Scanning {region}...")` before each region. `print(f"Found {len(findings)} findings in {region}")` after each region.

### Step 2.8 — Write tests for Phase 2

Create `tests/test_scanners.py`:

You cannot run real AWS API calls in tests without credentials. Instead:
- Test that each scanner function exists and has the correct signature
- Test that the pricing utility returns correct values
- Test date calculations for Cost Explorer (3 months ago, first of month)
- Test that the orchestrator correctly merges findings from multiple mock lists

**PHASE 2 VERIFICATION:** Run `pytest tests/` — all tests pass. If you have AWS credentials configured, run `python -c "from scanners import run_all_scanners; from utils.aws_client import create_aws_session; from config import load_config; c = load_config(); s = create_aws_session(c); print('Session created')"` to verify AWS connection works.

---

## PHASE 3 — AI Integration

**Goal:** Build the AI module that generates executive summaries and per-finding explanations using OpenAI API.

### Step 3.1 — Create ai/prompts.py

Store ALL prompt templates as string constants. No prompt text should exist anywhere else in the codebase.

**EXECUTIVE_SUMMARY_PROMPT:**

```
You are a senior AWS cloud infrastructure consultant writing an executive summary for a cost audit report.

CLIENT: {client_name}
AWS ACCOUNT: {account_id}
TOTAL MONTHLY SPEND: ${total_monthly_spend}
TOTAL FINDINGS: {total_findings}
TOTAL ESTIMATED MONTHLY SAVINGS: ${total_estimated_savings}
COST TREND (last 3 months): {cost_trend_text}

TOP 5 FINDINGS:
{top_findings_text}

Write a 3-paragraph executive summary:
- Paragraph 1: What was found at a high level — total waste, which services have the most waste, overall health of the account.
- Paragraph 2: The 2-3 most impactful findings with specific dollar amounts and resource IDs. Be concrete.
- Paragraph 3: Priority recommendation — what should be fixed first, expected savings timeline, and risk level of the recommended actions.

RULES:
- Every sentence must contain a specific number or specific resource type. No vague language.
- Do NOT use phrases like "significant savings" or "optimize costs" — state exact dollar amounts.
- Keep it under 250 words total.
- Write in professional third person ("The audit found..." not "We found...").
- If total savings is under $100/month, note that the account is already well-optimized.
```

**FINDING_EXPLANATION_PROMPT:**

```
You are a senior AWS cloud consultant explaining a cost audit finding to a non-technical CTO.

FINDING:
- Service: {service}
- Resource ID: {resource_id}
- Resource Name: {resource_name}
- Region: {region}
- Issue: {finding_type}
- Estimated Monthly Savings: ${estimated_monthly_savings}
- Details: {details_text}

Write exactly 2 sentences:
- Sentence 1: What this resource is, why it is costing money unnecessarily.
- Sentence 2: The specific action to take and what the result will be.

RULES:
- Include the resource ID by name in your explanation.
- Include the exact savings figure.
- State the risk level of the recommended action (safe to do immediately vs needs verification).
- Maximum 60 words total.
```

### Step 3.2 — Create ai/summarizer.py

Function `generate_executive_summary(report: AuditReport, api_key: str) -> str`:

- Build the prompt using EXECUTIVE_SUMMARY_PROMPT template
- Format top_findings_text: for each of report.top_findings, include service, resource_id, savings, finding_type
- Format cost_trend_text: for each month, show month name and total
- Call OpenAI API:
  ```python
  client = openai.OpenAI(api_key=api_key)
  response = client.chat.completions.create(
      model="gpt-4o-mini",
      messages=[{"role": "user", "content": prompt}],
      max_tokens=500,
      temperature=0.3
  )
  return response.choices[0].message.content.strip()
  ```
- If API call fails (any exception): return a fallback summary:
  "This AWS cost audit identified {n} findings with an estimated total monthly savings of ${x}. The top area of waste is {service} accounting for ${y}/month in potential savings. Review the detailed findings below for specific resource-level recommendations."

### Step 3.3 — Create ai/recommender.py

Function `generate_finding_explanations(findings: list[Finding], api_key: str) -> list[Finding]`:

- For each finding in the list:
  - Build prompt using FINDING_EXPLANATION_PROMPT
  - Call OpenAI API (same model and params as summarizer)
  - Set finding.ai_explanation = response text
  - If API call fails: set finding.ai_explanation = finding.recommended_action (use the rule-based recommendation as fallback)
  - Add a small delay between calls to avoid rate limits: `time.sleep(0.2)`
- Return the updated findings list

**Optimization:** If there are more than 20 findings, only generate AI explanations for the top 10 by savings. For the rest, use the rule-based recommended_action as the explanation.

### Step 3.4 — Create ai/__init__.py with orchestrator

Function `enhance_report_with_ai(report: AuditReport, api_key: str) -> AuditReport`:

1. If api_key is empty or None: print("Skipping AI enhancement — no API key provided") and return report unchanged
2. Call generate_executive_summary → set report.ai_executive_summary
3. Call generate_finding_explanations → update report.findings
4. Return enhanced report

### Step 3.5 — Write tests for Phase 3

Create `tests/test_ai.py`:
- Test that prompts render correctly with sample data (no empty placeholders)
- Test that fallback summary is generated when API key is empty
- Test that findings with no AI key retain their original recommended_action as explanation

**PHASE 3 VERIFICATION:** Run `pytest tests/` — all tests pass. If you have an OpenAI API key, test manually: `python -c "from ai.summarizer import generate_executive_summary; ..."` with fake report data.

---

## PHASE 4 — PDF Report Generation

**Goal:** Build the HTML report template and WeasyPrint PDF renderer.

### Step 4.1 — Create reports/templates/styles.css

Create a clean, professional CSS stylesheet for the report. Include:
- Page setup: A4 size, margins
- Font: system sans-serif stack
- Color scheme: dark navy headers (#1E3A5F), accent blue (#2E86DE), green for savings (#1A7F4B), red for high severity (#DC3545), amber for medium (#FFC107)
- Table styling: alternating row colors, borders, padding
- Cover page styling
- Section headers
- Severity badges (colored pills)
- Chart container for cost trend (simple CSS bar chart)
- Page break controls between sections
- Print-friendly styles

### Step 4.2 — Create reports/templates/report.html

Create a Jinja2 HTML template. The template receives the AuditReport.to_dict() as context.

**Page 1 — Cover page:**
- Title: "AWS Cost Audit Report"
- Client name: {{ client_name }}
- Account ID: {{ account_id }}
- Date: {{ scan_date }}
- Headline metric: "Estimated Monthly Savings: ${{ total_estimated_savings }}"
- Secondary metrics: total findings count, regions scanned count

**Page 2 — Executive Summary:**
- If ai_executive_summary is not empty: render it
- If empty: show a brief template-based summary using total_findings and total_estimated_savings

**Page 3 — Cost Overview:**
- Cost trend table: month | total spend | change from previous month (%)
- Cost by service table: service name | monthly cost — sorted by cost DESC, show top 10 services
- Simple CSS bar chart showing top 5 services by cost (horizontal bars using div width percentages)

**Page 4+ — Findings:**
- Section header: "Findings ({{ total_findings }} total — Estimated Savings: ${{ total_estimated_savings }}/month)"
- Summary counts: {{ high_severity_count }} High | {{ medium_severity_count }} Medium | {{ low_severity_count }} Low
- For each finding (sorted by savings DESC):
  - Severity badge (colored pill)
  - Service | Resource ID | Region
  - Finding type description
  - Estimated Monthly Savings: $X.XX
  - AI explanation (or recommended_action if no AI)
  - Horizontal rule between findings

**Last Page — Methodology:**
- Brief paragraph explaining what was scanned and how
- List of services checked
- Note: "Cost data reflects charges through yesterday. Recent changes may not be reflected."
- Note: "All savings estimates should be verified before implementing changes."
- Scanner version and scan duration

### Step 4.3 — Create reports/pdf.py

Function `generate_pdf(report: AuditReport, output_dir: str) -> str`:

1. Load the Jinja2 template from reports/templates/report.html
2. Load CSS from reports/templates/styles.css
3. Render the template with report.to_dict() as context
4. Use WeasyPrint to convert the rendered HTML to PDF:
   ```python
   from weasyprint import HTML, CSS
   html = HTML(string=rendered_html)
   css = CSS(string=css_content)
   filename = f"{report.client_name.replace(' ', '_')}_audit_{report.scan_date}.pdf"
   filepath = os.path.join(output_dir, filename)
   html.write_pdf(filepath, stylesheets=[css])
   return filepath
   ```
5. Return the full file path of the generated PDF

### Step 4.4 — Create reports/generator.py

Function `build_report(config, findings, cost_by_service, cost_trend, total_spend, scan_duration, regions) -> AuditReport`:

Simply assembles all collected data into an AuditReport object. This is a pure data assembly function — no scanning or API calls.

### Step 4.5 — Test PDF generation

Create `tests/test_reports.py`:
- Create a fake AuditReport with 5 sample findings
- Call generate_pdf and verify:
  - The returned filepath exists
  - The file is a valid PDF (file size > 0, starts with %PDF magic bytes)
  - The filename contains the client name and date

**PHASE 4 VERIFICATION:** Run `pytest tests/` — all tests pass. Manually run the PDF test and open the generated PDF to verify it renders correctly.

---

## PHASE 5 — Main Entry Point and End-to-End Flow

**Goal:** Wire everything together into a working CLI tool.

### Step 5.1 — Create main.py

```python
import sys
import time
import argparse
from config import load_config
from utils.aws_client import create_aws_session, get_enabled_regions, get_account_id
from scanners import run_all_scanners
from ai import enhance_report_with_ai
from reports.generator import build_report
from reports.pdf import generate_pdf
```

Function `main()`:

1. Parse command-line arguments:
   - `--profile` (optional): AWS profile name override
   - `--regions` (optional): comma-separated region list override
   - `--skip-ai` (optional flag): skip AI enhancement
   - `--output` (optional): output directory override

2. Load config. Apply CLI overrides if provided.

3. Print banner:
   ```
   ╔══════════════════════════════════════╗
   ║     AWS Cost Audit Tool v1.0        ║
   ╚══════════════════════════════════════╝
   ```

4. Print: `"Client: {client_name} | Account: {account_id}"`

5. Create AWS session. Print: "AWS session created successfully."

6. Get account ID. Get regions to scan. Print: "Scanning {n} regions: {region_list}"

7. Start timer: `start = time.time()`

8. Run all scanners. Print progress along the way.

9. Calculate scan duration.

10. Print summary:
    ```
    Scan complete in {duration}s
    Found {n} findings
    Estimated monthly savings: ${total}
    ```

11. Build AuditReport object.

12. If not skip_ai and config has OpenAI key:
    - Print: "Enhancing report with AI..."
    - Call enhance_report_with_ai

13. Print: "Generating PDF report..."

14. Generate PDF. Print: "Report saved to: {filepath}"

15. Print findings summary table to console:
    ```
    SERVICE    | RESOURCE         | SAVINGS  | SEVERITY
    ─────────────────────────────────────────────────────
    EC2        | i-0abc123def     | $180.00  | HIGH
    RDS        | db-prod-legacy   | $136.80  | HIGH
    EBS        | vol-0abc123      | $8.00    | MEDIUM
    ```

16. Exit with code 0.

Add `if __name__ == "__main__": main()` at the bottom.

### Step 5.2 — Create sample data for testing without AWS

Create `tests/test_e2e.py`:
- Mock boto3 session and all scanner returns
- Run the full pipeline with mock data
- Verify a PDF is generated in the output directory
- Verify the report contains the expected number of findings

### Step 5.3 — Create the IAM policy file

Create `iam_policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CostAuditReadOnly",
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeInstances",
        "ec2:DescribeVolumes",
        "ec2:DescribeAddresses",
        "ec2:DescribeRegions",
        "rds:DescribeDBInstances",
        "rds:ListTagsForResource",
        "s3:ListAllMyBuckets",
        "s3:GetBucketLocation",
        "s3:GetBucketLifecycleConfiguration",
        "cloudwatch:GetMetricStatistics",
        "cloudwatch:DescribeAlarms",
        "ce:GetCostAndUsage",
        "ce:GetCostForecast",
        "sts:GetCallerIdentity"
      ],
      "Resource": "*"
    }
  ]
}
```

### Step 5.4 — Create README.md

Write a clear README with:
- What the tool does (3 sentences max)
- Prerequisites: Python 3.12+, AWS credentials
- Installation: `pip install -r requirements.txt`
- Setup: copy .env.example to .env and fill in values
- Usage: `python main.py` (and all CLI options)
- IAM setup: how to create the read-only role using iam_policy.json
- Output: where the PDF is saved

### Step 5.5 — Final end-to-end test

If AWS credentials are available:
1. Copy .env.example to .env
2. Fill in a real AWS profile name and client name
3. Run: `python main.py --skip-ai`
4. Verify PDF is generated
5. Open PDF and review output

If no AWS credentials:
1. Run: `pytest tests/` — all tests must pass
2. Run: `python main.py --help` — must show help text without crashing

**PHASE 5 VERIFICATION:** `python main.py --help` works. `pytest tests/` all pass. If AWS credentials exist, a real scan produces a real PDF.

---

## PHASE 6 — Sample Report and Sales Assets

**Goal:** Generate a realistic sample report with fake data for sales demos.

### Step 6.1 — Create sample/generate_sample.py

Create a script that:
1. Builds a fake AuditReport with realistic findings (15 findings across all service types)
2. Includes realistic cost_by_service data (EC2: $3,200, RDS: $1,800, S3: $450, etc.)
3. Includes a 3-month cost trend showing a 15% increase
4. Sets ai_executive_summary to a pre-written professional summary
5. Sets ai_explanation on each finding to a pre-written explanation
6. Calls generate_pdf to create a polished sample PDF

Sample findings to include:
- 3 stopped EC2 instances (various sizes, 15-45 days stopped)
- 2 idle running EC2 instances (CPU < 3%)
- 1 idle RDS db.m5.large with 0 connections for 21 days
- 1 stopped RDS instance (storage costs)
- 5 unattached EBS volumes (20 GB to 500 GB)
- 2 unused Elastic IPs
- 1 large S3 bucket (500 GB) with no lifecycle policy

Total monthly savings should be between $1,200 and $2,000 (realistic and impressive).

### Step 6.2 — Run sample generator

Run: `python sample/generate_sample.py`

Verify the output PDF looks professional. This is the PDF you will attach to Upwork proposals and LinkedIn posts.

**PHASE 6 VERIFICATION:** A polished sample PDF exists in the output directory. It looks professional enough to send to a prospect.

---

## Post-Build Checklist

After all 6 phases are complete, verify:

- [ ] `python main.py --help` shows all options
- [ ] `pytest tests/` — all tests pass with 0 failures
- [ ] `python main.py --skip-ai` with real AWS credentials produces a PDF
- [ ] `python main.py` with real AWS credentials + OpenAI key produces an AI-enhanced PDF
- [ ] `python sample/generate_sample.py` produces a sample PDF
- [ ] iam_policy.json is valid JSON
- [ ] README.md is complete and accurate
- [ ] .gitignore includes all sensitive files
- [ ] No hardcoded credentials anywhere in the codebase

---

## File Manifest (What Should Exist When Done)

```
aws-cost-audit/
├── scanners/
│   ├── __init__.py          ← orchestrator (run_all_scanners)
│   ├── ec2.py               ← EC2 stopped + idle scanner
│   ├── rds.py               ← RDS idle + stopped scanner
│   ├── ebs.py               ← EBS unattached volume scanner
│   ├── eip.py               ← EIP unused scanner
│   ├── s3.py                ← S3 lifecycle + size scanner
│   └── cost_explorer.py     ← Cost by service + trend
├── ai/
│   ├── __init__.py          ← enhance_report_with_ai orchestrator
│   ├── prompts.py           ← all prompt templates
│   ├── summarizer.py        ← executive summary generator
│   └── recommender.py       ← per-finding explanation generator
├── reports/
│   ├── __init__.py
│   ├── templates/
│   │   ├── report.html      ← Jinja2 report template
│   │   └── styles.css       ← report styling
│   ├── generator.py         ← build_report assembler
│   └── pdf.py               ← WeasyPrint PDF converter
├── models/
│   ├── __init__.py
│   ├── finding.py           ← Finding dataclass
│   └── report.py            ← AuditReport dataclass
├── utils/
│   ├── __init__.py
│   ├── aws_client.py        ← session creation, region discovery
│   └── pricing.py           ← instance cost lookups
├── tests/
│   ├── __init__.py
│   ├── test_models.py
│   ├── test_config.py
│   ├── test_scanners.py
│   ├── test_ai.py
│   ├── test_reports.py
│   └── test_e2e.py
├── sample/
│   └── generate_sample.py   ← fake report generator for demos
├── output/                  ← generated PDFs land here
├── main.py                  ← CLI entry point
├── config.py                ← env config loader
├── requirements.txt
├── iam_policy.json          ← read-only IAM policy for clients
├── .env.example
├── .gitignore
└── README.md
```

Total files: 30
Estimated lines of code: 1,500-2,000
Estimated build time for Claude Code: 2-3 hours across all phases

---

*AWS Cost Audit Tool — Claude Code Implementation Plan v1.0*
*Feed to Claude Code. Execute phase by phase. Test before proceeding.*
