# Implementation Plan: AWS Cost Audit Tool

**Branch**: `001-aws-cost-audit` | **Date**: 2026-05-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-aws-cost-audit/spec.md`

## Summary

Build a Python CLI tool that scans AWS accounts for wasted spend across EC2, RDS, EBS, EIP, S3, and Cost Explorer. The tool generates professional PDF audit reports with AI-powered summaries and recommendations. The tool must complete scans in under 30 minutes, use read-only AWS permissions, and produce client-ready PDFs worth $800–$1,500 per audit.

**Technical Approach**: Single-process Python CLI using boto3 for AWS scanning, concurrent.futures.ThreadPoolExecutor for parallel region scanning, OpenAI GPT-4o-mini for AI summaries, Jinja2 for HTML templating, and WeasyPrint for PDF generation. All pricing data fetched from AWS Pricing API with session-level caching.

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**:
- boto3 + botocore (AWS SDK)
- openai (GPT-4o-mini for AI summaries)
- jinja2 (HTML templating)
- weasyprint (HTML to PDF conversion)
- python-dotenv (configuration)
- matplotlib (cost trend charts)

**Storage**: Local filesystem only
- `.env` file for configuration (gitignored)
- `output/` directory for generated PDFs (gitignored)
- No database required (stateless tool)

**Testing**: pytest + unittest.mock
- All AWS calls mocked (no real AWS API calls in tests)
- OpenAI calls mocked
- Target: >80% code coverage

**Target Platform**: Cross-platform CLI (Windows, macOS, Linux)
- Python 3.12+ required
- AWS credentials via environment variables or IAM role

**Project Type**: CLI tool (single-purpose service tool)

**Performance Goals**:
- Complete scan in <30 minutes for typical AWS account (100–500 resources)
- Parallel scanning across up to 10 regions concurrently
- PDF generation <2 minutes

**Constraints**:
- Read-only AWS access only (no write/delete operations)
- Must work with minimal client setup (IAM role ARN only)
- PDF must be client-ready (professional quality, no technical jargon)
- No credentials ever committed to repository
- CloudWatch queries limited to 14-day lookback (cost vs. accuracy)

**Scale/Scope**:
- MVP: 6 resource types (EC2, RDS, EBS, EIP, S3, Cost Explorer)
- Target: 10+ client audits before V2
- Typical scan: 100–500 resources across 3–5 regions

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### From CLAUDE.md Non-Negotiables

✅ **SECURITY: Read-only AWS only**
- IAM policy documented in `iam_policy.json`
- No write/delete permissions in any scanner
- `.env` in `.gitignore` always
- Credentials never committed

✅ **RELIABILITY: Partial results on failure**
- All scanners handle pagination
- Continue on single region/service failure
- Retry logic with exponential backoff
- Conservative CloudWatch handling (skip vs. false positive)

✅ **ACCURACY: Savings clearly labeled as estimates**
- All pricing from AWS Pricing API (real-time)
- Calculation logic documented in code comments
- Savings marked as "estimated" in reports
- CloudWatch metrics: 14-day lookback

✅ **CODE QUALITY: Python 3.12, type hints, docstrings**
- Type hints on all functions
- Google-style docstrings
- dataclasses for all models
- No bare `except` clauses

✅ **TESTABILITY: Mocked boto3, no real AWS calls**
- pytest with unittest.mock
- All scanners tested with mocked responses
- OpenAI calls mocked
- >80% coverage target

✅ **BUSINESS CONTEXT: <30 min scans, professional PDF**
- ThreadPoolExecutor for parallel scanning
- WeasyPrint for PDF generation
- Minimal client friction (IAM role only)

**Constitution Status**: ✅ All gates passed

## Project Structure

### Documentation (this feature)

```text
specs/001-aws-cost-audit/
├── plan.md              # This file
├── research.md          # Phase 0 output (dependency patterns, pricing API, error handling)
├── data-model.md        # Phase 1 output (Finding, Report dataclasses)
├── quickstart.md        # Phase 1 output (setup, first scan, sample report)
└── contracts/           # Phase 1 output (CLI interface, .env schema, IAM policy)
    ├── cli-interface.md
    ├── config-schema.md
    └── iam-policy.json
```

### Source Code (repository root)

```text
aws-cost-audit-tool/
├── scanners/
│   ├── __init__.py
│   ├── base.py          # Base scanner class with common logic
│   ├── ec2.py           # EC2 scanner (stopped, low utilization)
│   ├── rds.py           # RDS scanner (zero connections, stopped)
│   ├── ebs.py           # EBS scanner (unattached volumes)
│   ├── eip.py           # EIP scanner (unassociated IPs)
│   ├── s3.py            # S3 scanner (lifecycle, tiering)
│   └── cost_explorer.py # Cost Explorer scanner (trends, spend)
│
├── ai/
│   ├── __init__.py
│   ├── prompts.py       # Prompt templates for GPT-4o-mini
│   ├── summarizer.py    # Executive summary generation
│   └── recommender.py   # Top 5 recommendations generation
│
├── reports/
│   ├── __init__.py
│   ├── templates/
│   │   └── report.html  # Jinja2 template (cover, summary, findings, recommendations)
│   ├── generator.py     # HTML generation from findings
│   └── pdf.py           # WeasyPrint PDF conversion
│
├── models/
│   ├── __init__.py
│   ├── finding.py       # Finding dataclass
│   └── report.py        # Report dataclass
│
├── utils/
│   ├── __init__.py
│   ├── aws_client.py    # Boto3 client factory (handles AssumeRole, regions)
│   └── pricing.py       # AWS Pricing API queries with session cache
│
├── tests/
│   ├── __init__.py
│   ├── test_models.py         # Finding, Report validation tests
│   ├── test_scanners.py       # All scanner tests (mocked boto3)
│   ├── test_ai.py             # AI module tests (mocked OpenAI)
│   ├── test_reports.py        # Report generation tests
│   ├── test_e2e.py            # End-to-end CLI tests
│   └── fixtures/              # Mock AWS responses, sample data
│
├── sample/
│   └── generate_sample.py     # Generate demo report for sales
│
├── output/                    # Generated PDFs (gitignored)
│
├── main.py                    # CLI entry point
├── config.py                  # Config loader (.env + CLI args)
├── requirements.txt           # Python dependencies
├── iam_policy.json            # Minimal IAM policy for clients
├── .env.example               # Example configuration file
├── .gitignore
├── README.md
└── CLAUDE.md                  # Project guidance (this file updated in Phase 1)
```

**Structure Decision**: Single project structure selected. This is a standalone CLI tool with no frontend/backend separation needed. All scanners, AI, and reporting logic live in the same Python package for simplicity and ease of deployment as a single executable.

## Complexity Tracking

> No constitutional violations. All requirements align with non-negotiables.

---

## Phase 0: Research & Unknowns

### Research Tasks

#### 1. AWS Pricing API Integration Pattern
**Question**: How to efficiently query AWS Pricing API for EC2, RDS, EBS pricing across regions without adding significant latency?

**Research Focus**:
- AWS Pricing API query patterns (filters, pagination)
- Caching strategies (session-level, per-resource-type)
- Rate limits and best practices
- Common pitfalls (product code variations, region name mapping)

**Output**: `research.md` section on pricing API with example queries and cache implementation approach

#### 2. CloudWatch Metrics Best Practices
**Question**: Best practices for querying CloudWatch metrics (CPUUtilization, DatabaseConnections, BucketSizeBytes) efficiently across multiple resources and regions?

**Research Focus**:
- Batch vs. individual metric queries
- Optimal period/statistic for 14-day lookback
- Handling missing data points (conservative approach confirmed in clarifications)
- Cost optimization (minimize GetMetricStatistics calls)

**Output**: `research.md` section on CloudWatch querying patterns

#### 3. WeasyPrint PDF Styling Best Practices
**Question**: How to achieve professional corporate PDF styling with WeasyPrint (charts, tables, page headers, alternating row colors)?

**Research Focus**:
- CSS best practices for print media
- Chart embedding (matplotlib PNG vs. inline SVG)
- Page break control for multi-page findings tables
- Corporate styling patterns (blues, grays, professional look)

**Output**: `research.md` section on PDF generation with CSS examples

#### 4. boto3 Error Handling Patterns
**Question**: Best practices for handling boto3 exceptions (rate limits, access denied, region unavailable) to ensure partial results on failure?

**Research Focus**:
- Common boto3 exception types (ClientError, BotoCoreError)
- Exponential backoff with jitter (built-in retries vs. custom)
- Pagination patterns (handle_pagination helper)
- Logging vs. raising (when to fail vs. skip)

**Output**: `research.md` section on error handling with code patterns

#### 5. Tag Filtering Implementation
**Question**: How to efficiently implement tag-based exclusion filters across all scanners?

**Research Focus**:
- Tag matching logic (exact match vs. prefix)
- Performance implications (filter before or after enrichment)
- Handling resources without tags
- Common tag naming patterns to support

**Output**: `research.md` section on tag filtering with helper function design

---

## Phase 1: Design & Contracts

### 1. Data Model (`data-model.md`)

**Entities**:
- `Finding`: Represents a single wasteful resource
- `Report`: Aggregates all findings for an audit
- `ScanConfig`: Configuration for a single scan run

**Validation Rules**:
- `Finding.monthly_savings` must be >= 0
- `Finding.severity` must be in ["High", "Medium", "Low"]
- `Report.regions_scanned` must not be empty
- `ScanConfig.exclude_tags` parsed as key=value pairs

**State Transitions**: N/A (stateless tool)

### 2. Interface Contracts (`/contracts/`)

#### CLI Interface (`cli-interface.md`)
- Command structure: `python main.py [OPTIONS]`
- Options: `--profile`, `--region`, `--client-name`, `--skip-ai`, `--output`, `--exclude-tags`, `--verbose`
- Exit codes: 0 (success), 1 (error), 2 (partial results)
- Output format: Summary to stdout, errors to stderr

#### Configuration Schema (`config-schema.md`)
- `.env` file structure
- Required vs. optional fields
- Validation rules (e.g., OPENAI_API_KEY required if not --skip-ai)
- Example configuration

#### IAM Policy (`iam-policy.json`)
- Minimal read-only permissions
- Service-by-service breakdown
- Resource ARN patterns (use "*" for read-only list operations)

### 3. Quickstart Guide (`quickstart.md`)

**Setup**:
1. Clone repository
2. Create virtual environment: `python -m venv venv`
3. Install dependencies: `pip install -r requirements.txt`
4. Copy `.env.example` to `.env`
5. Configure AWS credentials and OpenAI API key

**First Scan**:
1. Run: `python main.py --client-name "Test Client"`
2. Wait for completion (<30 minutes)
3. Find report in `output/aws_audit_{account_id}_{date}.pdf`

**Sample Report**:
1. Run: `python sample/generate_sample.py`
2. Generates demo report with mock data for sales demos

### 4. Agent Context Update

Update `CLAUDE.md` to add Spec Kit reference:

```markdown
<!-- SPECKIT START -->
## Active Feature

Current feature: AWS Cost Audit Tool (001-aws-cost-audit)
Implementation plan: specs/001-aws-cost-audit/plan.md
<!-- SPECKIT END -->
```

---

## Phase 2: Not Included

Phase 2 (task generation) is handled by the `/speckit-tasks` command, not `/speckit-plan`.

---

## Next Steps

After this plan is complete:
1. Review `research.md` for technical decisions
2. Review `data-model.md` for entity design
3. Review `contracts/` for interface definitions
4. Run `/speckit-tasks` to generate implementation tasks
5. Begin Phase 1 implementation (project setup + data models)

---

## Constitution Re-Check (Post-Design)

*To be completed after Phase 1 design artifacts are generated.*

All design decisions must maintain:
- ✅ Read-only AWS access
- ✅ No credentials committed
- ✅ Type hints and docstrings
- ✅ Mocked tests
- ✅ <30 minute scans
- ✅ Professional PDF output
