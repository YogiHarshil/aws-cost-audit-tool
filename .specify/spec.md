# Feature Specification: AWS Cost Audit Tool

**Version:** 1.0.0
**Status:** Draft
**Last Updated:** 2026-05-13

---

## Overview

A Python CLI tool that scans AWS accounts for wasted spend and generates professional PDF audit reports with AI-powered summaries. Built as a productized service tool — operator runs it, client receives polished PDF report worth $800–$1,500 per audit.

---

## Problem Statement

Cloud waste audits are time-consuming and require:
1. Manual inspection across multiple AWS services and regions
2. Cost estimation and savings calculations
3. Professional report generation suitable for C-level executives
4. AI-driven prioritization and explanation of findings

This tool automates the entire process, turning a multi-day manual audit into a 30-minute automated scan.

---

## Goals

**Primary Goals:**
- Scan AWS accounts across all enabled regions in <30 minutes
- Detect 6 categories of waste: EC2, RDS, EBS, EIP, S3, Cost Explorer trends
- Generate professional PDF reports with AI summaries and recommendations
- Require minimal client setup (IAM role ARN only)
- Provide read-only, zero-risk scanning

**Non-Goals (V2 after 10 clients):**
- Web dashboard or SaaS interface
- Automated scheduling (Celery/cron)
- Multi-tenant database (Supabase)
- Payment processing (Stripe)
- REST API (FastAPI)
- Customer portal (Next.js)

---

## User Personas

**Primary User: Service Operator (You)**
- Runs the tool locally via CLI
- Has AWS credentials with read-only access to client accounts
- Has OpenAI API key for AI summaries
- Delivers PDF to client after review

**Secondary User: Client (Indirect)**
- Receives PDF report only (no tool access)
- C-level or engineering leadership
- Needs actionable, easy-to-understand recommendations
- May not be AWS experts

---

## Functional Requirements

### 1. AWS Scanning

#### 1.1 EC2 Scanner
- **Stopped instances >7 days:**
  - Filter: `State=stopped`, `StateTransitionTime` more than 7 days ago
  - Savings: On-demand hourly rate × 730 hours/month
  - Severity: High

- **Low utilization running instances (<5% CPU over 14 days):**
  - Filter: `State=running`
  - CloudWatch: Average `CPUUtilization` over 14 days
  - Threshold: <5% average
  - Savings: On-demand hourly rate × 730 hours/month (rightsizing potential)
  - Severity: Medium

- **Data collected:** Instance ID, type, region, AZ, state, launch time, tags

#### 1.2 RDS Scanner
- **Zero connections for 14+ days:**
  - CloudWatch: `DatabaseConnections` metric
  - Threshold: 0 connections for 14 consecutive days
  - Savings: On-demand hourly rate × 730 hours/month
  - Severity: High

- **Stopped instances:**
  - Filter: `DBInstanceStatus=stopped`
  - Savings: Storage costs only (calculate from AllocatedStorage)
  - Severity: Medium

- **Data collected:** DB instance ID, class, engine, status, region, AZ, allocated storage, tags

#### 1.3 EBS Scanner
- **Unattached volumes:**
  - Filter: `State=available`
  - Savings: Volume size (GB) × regional EBS pricing per GB-month
  - Severity: Medium

- **Data collected:** Volume ID, size, type, state, region, AZ, snapshot ID, creation time, tags

#### 1.4 EIP Scanner
- **Unassociated Elastic IPs:**
  - Filter: `AssociationId` is null
  - Savings: $3.60/month per unassociated EIP (standard AWS pricing)
  - Severity: Low (but quick win)

- **Data collected:** Allocation ID, public IP, region, association status

#### 1.5 S3 Scanner
- **Missing lifecycle policies:**
  - List all buckets
  - Check `GetLifecycleConfiguration` for each
  - Flag buckets with no lifecycle policy
  - Savings: Estimate (no hard number, flag for review)
  - Severity: Low

- **Large buckets without tiering:**
  - Threshold: >100GB total storage
  - Check for Intelligent-Tiering or lifecycle transitions
  - Savings: Estimate based on potential tiering (30% of standard storage costs)
  - Severity: Medium

- **Data collected:** Bucket name, region, size, storage class distribution, lifecycle policy status, creation date

#### 1.6 Cost Explorer Scanner
- **90-day spend by service:**
  - Query Cost Explorer API for last 90 days
  - Group by `SERVICE`
  - Return top 10 services by cost

- **Month-over-month trend:**
  - Compare current month (MTD) vs. previous month (full month)
  - Calculate % change
  - Flag if >20% increase

- **Data collected:** Service name, daily costs, monthly totals, trend direction

### 2. AI Integration

#### 2.1 Executive Summary (GPT-4o-mini)
- **Input:** All findings + cost trends
- **Output:** 150–250 word executive summary covering:
  - Total estimated monthly savings
  - Top 3 waste categories
  - Overall account health assessment
  - Urgency level

#### 2.2 Per-Finding Explanations (GPT-4o-mini)
- **Input:** Single finding data (resource type, details, savings)
- **Output:** 2–3 sentence explanation:
  - Why this is wasteful
  - Business impact
  - Suggested action

#### 2.3 Top 5 Recommendations (GPT-4o-mini)
- **Input:** All findings sorted by savings DESC
- **Output:** Prioritized list of 5 actions:
  - Action title
  - Expected impact ($)
  - Implementation difficulty (Low/Medium/High)
  - Order by: savings × ease

#### 2.4 Graceful Degradation
- If OpenAI API key missing or `--skip-ai` flag set:
  - Skip AI summaries
  - Include raw findings only
  - Note in report: "AI summaries disabled"

### 3. Report Generation

#### 3.1 PDF Structure
1. **Cover Page:**
   - Client name (from `--client-name` or AWS account alias)
   - Report date
   - Total estimated monthly savings (large, bold)
   - Scan metadata (regions scanned, resources analyzed)

2. **Executive Summary (Page 2):**
   - AI-generated summary
   - Cost trend chart (last 90 days, line chart)
   - Key metrics: Total resources scanned, findings count, savings breakdown by category

3. **Findings Table (Page 3+):**
   - Sortable by savings DESC
   - Columns: Resource, Type, Region, Issue, Monthly Savings, Severity
   - Severity badges: High (red), Medium (orange), Low (yellow)
   - Per-row AI explanation (in smaller text below resource ID)

4. **Recommendations (Last page):**
   - Top 5 prioritized actions
   - Each with: Title, Impact, Difficulty, Description

#### 3.2 Visual Design
- Professional corporate styling (blues, grays, white)
- Logo placeholder (customizable)
- Page numbers, header with client name
- Charts: Matplotlib or Plotly (embedded as PNG)
- Tables: Alternating row colors, clear borders
- Font: Sans-serif (Arial/Helvetica)

#### 3.3 Export Format
- Output: `output/aws_audit_{account_id}_{date}.pdf`
- File size target: <5MB (compress images if needed)
- PDF metadata: Title, Author, Creation Date

### 4. CLI Interface

#### 4.1 Command Structure
```bash
python main.py [OPTIONS]
```

#### 4.2 Options
- `--profile PROFILE`: AWS CLI profile name (default: `default`)
- `--region REGION`: Scan specific region only (default: all enabled regions)
- `--client-name NAME`: Client name for report cover (default: AWS account alias)
- `--skip-ai`: Disable AI summaries (faster, no OpenAI key needed)
- `--output PATH`: Custom output directory (default: `./output`)
- `--verbose`: Enable debug logging

#### 4.3 Configuration via .env
```
AWS_ROLE_ARN=arn:aws:iam::123456789012:role/AuditRole
AWS_PROFILE=default
OPENAI_API_KEY=sk-...
CLIENT_NAME=Acme Corp
```

#### 4.4 Execution Flow
1. Load config from .env and CLI args (CLI overrides .env)
2. Validate AWS credentials and OpenAI key (if AI enabled)
3. Discover enabled regions
4. Scan services in parallel (ThreadPoolExecutor)
5. Aggregate findings
6. Generate AI summaries (if enabled)
7. Render HTML template
8. Convert HTML to PDF via WeasyPrint
9. Save to `output/` directory
10. Print summary: "Report saved to {path}, Total savings: ${amount}"

#### 4.5 Error Handling
- Missing AWS credentials: Clear error message with setup instructions
- Missing OpenAI key (if not `--skip-ai`): Prompt to set key or use `--skip-ai`
- API rate limits: Exponential backoff, continue with partial results
- Service access denied: Log warning, skip that service, continue scan
- Region unavailable: Log warning, skip region, continue
- PDF generation failure: Save HTML instead, notify user

---

## Non-Functional Requirements

### Performance
- Complete scan in <30 minutes for typical AWS account (100–500 resources)
- Parallel scanning across regions (up to 10 concurrent threads)
- CloudWatch queries: 14-day lookback (balance accuracy vs. API cost)

### Security
- Read-only AWS permissions only (no write/delete operations)
- Never commit credentials (.env in .gitignore)
- Prefer IAM role ARN over access keys (STS AssumeRole)
- No data sent to third parties except OpenAI API (findings only, no credentials)

### Reliability
- Handle pagination for all AWS list operations
- Retry on transient errors (rate limits, network issues)
- Continue scan if single region/service fails (partial results)
- Validate data before passing to AI (prevent prompt injection)

### Maintainability
- Python 3.12+ type hints on all functions
- Google-style docstrings
- dataclasses for all models
- Pytest with mocked boto3 (no real AWS calls in tests)
- Code coverage target: >80%

### Usability
- Clear progress indicators during scan (service, region, % complete)
- Helpful error messages with remediation steps
- PDF must be client-ready (no raw JSON or technical jargon)
- Savings estimates clearly labeled as estimates

---

## Technical Architecture

### Tech Stack (Locked)
- **Python 3.12+**: Core language
- **boto3**: AWS SDK
- **Jinja2**: HTML templating
- **WeasyPrint**: HTML to PDF conversion
- **OpenAI API (GPT-4o-mini)**: AI summaries
- **python-dotenv**: Configuration
- **concurrent.futures**: Parallel scanning
- **dataclasses**: Data models
- **pytest + moto/unittest.mock**: Testing

### Project Structure
```
aws-cost-audit-tool/
├── scanners/
│   ├── ec2.py          # EC2 scanner
│   ├── rds.py          # RDS scanner
│   ├── ebs.py          # EBS scanner
│   ├── eip.py          # EIP scanner
│   ├── s3.py           # S3 scanner
│   └── cost_explorer.py # Cost Explorer scanner
├── ai/
│   ├── summarizer.py   # Executive summary generation
│   ├── recommender.py  # Top 5 recommendations
│   └── prompts.py      # Prompt templates
├── reports/
│   ├── templates/
│   │   └── report.html # Jinja2 template
│   ├── generator.py    # HTML generation
│   └── pdf.py          # PDF conversion
├── models/
│   ├── finding.py      # Finding dataclass
│   └── report.py       # Report dataclass
├── utils/
│   ├── aws_client.py   # Boto3 client factory
│   └── pricing.py      # Pricing calculations
├── tests/
│   ├── test_models.py
│   ├── test_scanners.py
│   ├── test_ai.py
│   ├── test_reports.py
│   └── test_e2e.py
├── sample/
│   └── generate_sample.py # Generate demo report
├── output/             # Generated PDFs (gitignored)
├── main.py             # CLI entry point
├── config.py           # Config loader
├── requirements.txt
├── iam_policy.json     # Minimal IAM policy for clients
├── .env.example
├── .gitignore
└── README.md
```

### Data Models

#### Finding
```python
@dataclass
class Finding:
    resource_id: str
    resource_type: str  # "EC2", "RDS", "EBS", "EIP", "S3"
    region: str
    issue_type: str     # "stopped", "low_utilization", etc.
    description: str
    monthly_savings: float
    severity: str       # "High", "Medium", "Low"
    details: dict       # Additional metadata
    ai_explanation: str | None = None
```

#### Report
```python
@dataclass
class Report:
    account_id: str
    account_alias: str
    client_name: str
    scan_date: datetime
    regions_scanned: list[str]
    findings: list[Finding]
    total_savings: float
    cost_trends: dict  # From Cost Explorer
    executive_summary: str | None = None
    recommendations: list[dict] | None = None
```

### AWS IAM Policy (Minimal)
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeInstances",
        "ec2:DescribeVolumes",
        "ec2:DescribeAddresses",
        "ec2:DescribeRegions",
        "rds:DescribeDBInstances",
        "s3:ListAllMyBuckets",
        "s3:GetBucketLocation",
        "s3:GetBucketLifecycleConfiguration",
        "s3:GetBucketTagging",
        "cloudwatch:GetMetricStatistics",
        "ce:GetCostAndUsage",
        "sts:GetCallerIdentity"
      ],
      "Resource": "*"
    }
  ]
}
```

---

## Dependencies

### Python Packages
- boto3 (AWS SDK)
- botocore (AWS core utilities)
- jinja2 (templating)
- weasyprint (PDF generation)
- openai (AI summaries)
- python-dotenv (config)
- matplotlib (cost charts)
- pytest (testing)
- moto (AWS mocking for tests)

### External Services
- AWS account with read-only access
- OpenAI API (optional, for AI features)

---

## Implementation Phases

### Phase 1: Project Setup + Data Models ✓
- Initialize Git repo, .gitignore, .env.example
- Create directory structure
- Define dataclasses (Finding, Report)
- Write config.py (load .env + CLI args)
- Write utils/aws_client.py (boto3 client factory)
- Tests: test_models.py

### Phase 2: AWS Scanners ✓
- Implement scanners/ec2.py
- Implement scanners/rds.py
- Implement scanners/ebs.py
- Implement scanners/eip.py
- Implement scanners/s3.py
- Implement scanners/cost_explorer.py
- Implement utils/pricing.py
- Tests: test_scanners.py (mocked boto3)

### Phase 3: AI Integration ✓
- Implement ai/prompts.py (prompt templates)
- Implement ai/summarizer.py (executive summary)
- Implement ai/recommender.py (top 5 recommendations)
- Handle --skip-ai flag gracefully
- Tests: test_ai.py (mocked OpenAI)

### Phase 4: Report Generation ✓
- Create reports/templates/report.html (Jinja2)
- Implement reports/generator.py (render HTML)
- Implement reports/pdf.py (WeasyPrint conversion)
- Add matplotlib chart for cost trends
- Tests: test_reports.py

### Phase 5: CLI + End-to-End ✓
- Implement main.py (CLI entry point)
- Argument parsing
- Parallel scanning orchestration
- Progress indicators
- Error handling
- Tests: test_e2e.py

### Phase 6: Sample Report for Demos ✓
- Implement sample/generate_sample.py
- Generate realistic mock data
- Produce sample PDF for sales

---

## Testing Strategy

### Unit Tests
- Each scanner tested with mocked boto3 responses
- AI module tested with mocked OpenAI responses
- Report generator tested with sample data
- Models tested for validation logic

### Integration Tests
- End-to-end test with mocked AWS + OpenAI
- Config loading from .env and CLI args
- PDF generation from findings

### Manual Testing
- Run against real AWS sandbox account
- Verify PDF output quality
- Test all CLI flags
- Test error scenarios (missing credentials, API limits)

---

## Success Metrics

### Development Success
- All pytest tests pass
- Code coverage >80%
- Completes scan in <30 minutes for typical account
- PDF output is client-ready

### Business Success (Post-Launch)
- Tool used for 10+ client audits
- Zero security incidents
- <5% error rate per scan
- Positive client feedback on PDF quality

---

## Open Questions

None at this time. Spec is complete for MVP.

---

## Future Enhancements (V2+)

After 10 successful client audits, consider:
- Web dashboard for real-time scanning
- Multi-tenant SaaS with Supabase
- Automated scheduling (Celery + Redis)
- Payment processing (Stripe)
- Customer portal (Next.js)
- REST API (FastAPI)
- Additional scanners: Lambda, CloudFront, NAT Gateways, unused AMIs
- Slack/email notifications
- Historical trend tracking (database)

---

## Appendix

### Example Output Summary
```
AWS Cost Audit Report for Acme Corp
Scan Date: 2026-05-13
Regions Scanned: us-east-1, us-west-2, eu-west-1

Total Estimated Monthly Savings: $4,832

Findings:
- 12 EC2 instances (8 stopped >7 days, 4 low utilization)
- 3 RDS instances (zero connections)
- 45 unattached EBS volumes
- 7 unassociated Elastic IPs
- 18 S3 buckets without lifecycle policies

Report saved to: output/aws_audit_123456789012_2026-05-13.pdf
```

### Example AI Summary
```
Your AWS account shows significant waste across compute and storage resources.
The primary cost driver is 8 EC2 instances that have been stopped for over 7
days, costing $2,400/month. Additionally, 45 unattached EBS volumes represent
$1,200/month in unnecessary storage costs. Terminating unused resources and
implementing S3 lifecycle policies could reduce your monthly AWS bill by
approximately $4,832 (estimated 23% savings). Immediate action is recommended
on high-severity findings.
```

---

**End of Specification**
