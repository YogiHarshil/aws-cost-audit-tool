# AWS Cost Audit Tool — Complete Implementation Guide

**Team:** Harshil (AWS / DevOps) + Partner (AI Engineer)
**Model:** Productized service — build once, sell to multiple clients
**Target:** International clients first (USA, UK, Canada, Australia)

---

## Table of Contents

1. [What You Are Building](#1-what-you-are-building)
2. [How the Business Works](#2-how-the-business-works)
3. [Full Tech Stack](#3-full-tech-stack)
4. [Project Structure](#4-project-structure)
5. [Database Design](#5-database-design)
6. [Implementation Steps](#6-implementation-steps)
7. [Workflow Pipeline](#7-workflow-pipeline)
8. [AI Integration — For Your Partner](#8-ai-integration--for-your-partner)
9. [Security](#9-security)
10. [What You Deliver to Each Client](#10-what-you-deliver-to-each-client)
11. [Pricing](#11-pricing)
12. [How to Find and Close Clients](#12-how-to-find-and-close-clients)
13. [Team Split](#13-team-split)
14. [90-Day Revenue Plan](#14-90-day-revenue-plan)

---

## 1. What You Are Building

A tool that scans a client's AWS account, finds wasted money, and generates a professional PDF report with prioritized action items.

**What it detects:**
- EC2 instances that are stopped or running with near-zero CPU
- RDS instances with zero database connections for 14+ days
- EBS volumes not attached to any instance
- Elastic IPs not associated with any resource
- S3 buckets missing lifecycle policies or accumulating large storage
- CloudWatch alarms that are missing on critical resources
- 90-day cost trend by service from Cost Explorer

**What the client gets:**
A PDF report showing exactly where their money is going, how much they can save, and what to do first — ranked by savings impact.

**Why this sells:**
Every AWS account over $2,000/month has waste. You find more in savings than you charge. That makes this a zero-risk purchase for the client.

---

## 2. How the Business Works

```
You build the tool once
        ↓
Client pays you a fixed fee
        ↓
You get read-only access to their AWS account
        ↓
You run the tool — takes 10-30 minutes
        ↓
AI generates a professional report with findings and recommendations
        ↓
You deliver the PDF report in 5 days
        ↓
Client keeps report. Optional: pay monthly for ongoing monitoring.
        ↓
You move to the next client with the same tool
```

**Your time per client after the tool is built:** 2-4 hours
**Your fee per client:** $800-$1,500
**Effective hourly rate:** $200-$750/hour

---

## 3. Full Tech Stack

### MVP (Weeks 1-3) — Manual Tool

| Layer | Tool | Why |
|---|---|---|
| AWS scanning | Python 3.12 + boto3 | Official AWS SDK, best support, you know it |
| Report templating | Jinja2 | Simple HTML templates, easy to style |
| PDF generation | WeasyPrint | Best CSS-to-PDF quality, free |
| AI summaries | OpenAI GPT-4o-mini or Claude API | Your partner's domain |
| Secrets | .env + python-dotenv | No infrastructure needed for MVP |
| Delivery | Email PDF attachment | Simple, professional |

### V2 Platform (After 10 Clients) — Self-Serve

| Layer | Tool | Why |
|---|---|---|
| Backend API | FastAPI (Python) | Async, auto-docs, you stay in Python |
| Background jobs | Celery + Redis | Scans take 8-20 min, must be async |
| Database | Supabase (PostgreSQL) | You already use it, multi-tenant RLS built-in |
| Frontend dashboard | Next.js 14 + Tailwind | You know it, SSR for report pages |
| Auth | Supabase Auth | Free, email + magic link |
| PDF storage | AWS S3 | Store generated reports, signed URL access |
| Payments | Stripe | Global, handles Indian exports cleanly |
| Hosting | Railway (backend) + Vercel (frontend) | Zero DevOps overhead |
| AI layer | OpenAI API + your partner's logic | See Section 8 |

---

## 4. Project Structure

### MVP Structure

```
aws-cost-audit/
├── scanners/
│   ├── __init__.py
│   ├── ec2.py              ← stopped instances, low CPU utilization
│   ├── rds.py              ← idle instances, zero connections
│   ├── ebs.py              ← unattached volumes
│   ├── eip.py              ← unused elastic IPs
│   ├── s3.py               ← missing lifecycle, large buckets
│   ├── cloudwatch.py       ← missing alarms on critical resources
│   └── cost_explorer.py    ← 90-day spend by service + region
├── ai/
│   ├── __init__.py
│   ├── summarizer.py       ← AI executive summary generation
│   ├── recommender.py      ← AI-enhanced per-finding explanations
│   └── prompts.py          ← all prompt templates in one place
├── reports/
│   ├── templates/
│   │   ├── base.html       ← main report layout
│   │   ├── summary.html    ← executive summary section
│   │   ├── findings.html   ← findings table with savings
│   │   └── recommendations.html
│   ├── generator.py        ← assembles all findings into report data
│   └── pdf.py              ← WeasyPrint HTML-to-PDF conversion
├── models/
│   ├── finding.py          ← Finding dataclass: service, resource_id, savings, severity
│   └── report.py           ← AuditReport dataclass: metadata + findings list
├── utils/
│   ├── aws_client.py       ← boto3 session setup, cross-account role assumption
│   ├── regions.py          ← get all enabled regions for account
│   └── formatting.py       ← currency formatting, date formatting
├── sample/
│   ├── fake_findings.json  ← realistic sample data for sales demos
│   └── sample_report.pdf   ← pre-generated PDF for LinkedIn/Upwork
├── iam_policy.json         ← read-only IAM policy — publish this publicly
├── config.py               ← load env vars, audit configuration
├── main.py                 ← entry point: run all scanners, generate report
├── requirements.txt
└── .env.example            ← template for required environment variables
```

### V2 Platform Structure

```
aws-audit-platform/
├── backend/
│   ├── app/
│   │   ├── api/v1/
│   │   │   ├── audits.py         ← trigger, list, get audit endpoints
│   │   │   ├── findings.py       ← get findings, filter by severity
│   │   │   ├── reports.py        ← download PDF, get signed URL
│   │   │   ├── credentials.py    ← add/manage AWS access per tenant
│   │   │   └── monitoring.py     ← retainer: configure ongoing scans
│   │   ├── core/
│   │   │   ├── config.py         ← env vars, settings
│   │   │   ├── security.py       ← encryption for stored credentials
│   │   │   └── logging.py        ← structured JSON logging
│   │   ├── models/               ← SQLAlchemy models matching DB schema
│   │   ├── services/
│   │   │   ├── audit_service.py  ← orchestrates scan + queues worker
│   │   │   ├── scanner_service.py← calls all scanners per account
│   │   │   ├── report_service.py ← PDF generation + S3 upload
│   │   │   └── ai_service.py     ← AI summary + recommendation calls
│   │   ├── workers/
│   │   │   ├── celery_app.py     ← Celery configuration
│   │   │   └── tasks.py          ← run_audit, generate_pdf, notify tasks
│   │   └── main.py               ← FastAPI app entry point
│   ├── scanners/                 ← same scanner modules as MVP
│   ├── ai/                       ← same AI modules as MVP
│   ├── migrations/               ← Alembic migration files
│   ├── tests/
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── app/
│   │   ├── (auth)/login/
│   │   ├── dashboard/            ← overview: latest audit, total savings
│   │   ├── audits/
│   │   │   └── [id]/             ← findings view, filterable by severity
│   │   ├── credentials/          ← add/manage AWS access
│   │   └── billing/              ← Stripe portal
│   ├── components/
│   │   ├── ui/                   ← shadcn/ui components
│   │   ├── audit/                ← AuditCard, AuditStatus, SavingsChart
│   │   └── findings/             ← FindingsTable, SeverityBadge
│   └── lib/
│       ├── api.ts                ← typed API client
│       └── supabase.ts           ← Supabase client
└── infrastructure/
    └── docker-compose.yml        ← local dev: n8n + Redis + PostgreSQL
```

---

## 5. Database Design

### Core Tables (V2 Platform)

**tenants**

One row per paying client. Root foreign key for all other tables.

| Column | Type | Notes |
|---|---|---|
| id | uuid | Primary key |
| email | text | Login email |
| company_name | text | For report header |
| plan | text | starter / pro / retainer |
| stripe_customer_id | text | Stripe billing link |
| created_at | timestamptz | |

---

**aws_credentials**

How the tool accesses the client's AWS account.

| Column | Type | Notes |
|---|---|---|
| id | uuid | Primary key |
| tenant_id | uuid | Foreign key → tenants |
| credential_type | text | `role_arn` or `access_key` |
| role_arn | text | Preferred — cross-account IAM role |
| access_key_id | text | If access key method used |
| secret_access_key_encrypted | text | AES-256 encrypted before insert |
| regions | text[] | Which regions to scan |
| created_at | timestamptz | |

> **Always prefer role_arn over access keys.** With a role ARN, you never store credentials — you assume the role temporarily via STS. No credentials to leak.

---

**audits**

One row per scan run.

| Column | Type | Notes |
|---|---|---|
| id | uuid | Primary key |
| tenant_id | uuid | Foreign key → tenants |
| status | text | queued / running / completed / failed |
| started_at | timestamptz | |
| completed_at | timestamptz | |
| total_findings | int | Count of waste items found |
| estimated_monthly_savings | decimal | Total savings in USD |
| pdf_s3_url | text | Signed URL to download report |
| ai_summary | text | AI-generated executive summary |
| scan_duration_seconds | int | For performance tracking |

---

**findings**

One row per waste item found. This is the core data.

| Column | Type | Notes |
|---|---|---|
| id | uuid | Primary key |
| audit_id | uuid | Foreign key → audits |
| tenant_id | uuid | For RLS filtering |
| service | text | EC2 / RDS / EBS / EIP / S3 |
| resource_id | text | Instance ID, volume ID, etc. |
| region | text | us-east-1, etc. |
| finding_type | text | idle / oversized / unattached / missing_policy |
| severity | text | high / medium / low |
| estimated_monthly_savings | decimal | USD |
| recommended_action | text | Specific action to take |
| ai_explanation | text | AI-generated plain English explanation |
| raw_data | jsonb | Original boto3 response data |
| created_at | timestamptz | |

---

**monitoring_configs** (Retainer Clients Only)

| Column | Type | Notes |
|---|---|---|
| id | uuid | Primary key |
| tenant_id | uuid | Foreign key → tenants |
| scan_frequency | text | weekly / monthly |
| alert_email | text | Where to send new findings |
| last_scan_at | timestamptz | |
| next_scan_at | timestamptz | |

---

### Key Indexes

```sql
-- Fast finding retrieval per audit, sorted by savings
CREATE INDEX idx_findings_audit_savings
ON findings (audit_id, estimated_monthly_savings DESC);

-- Dashboard query: latest audits per tenant
CREATE INDEX idx_audits_tenant_date
ON audits (tenant_id, created_at DESC);

-- Retainer monitoring cron query
CREATE INDEX idx_monitoring_next_scan
ON monitoring_configs (next_scan_at)
WHERE next_scan_at IS NOT NULL;
```

### Row Level Security (Supabase)

Every table has `tenant_id`. Supabase RLS ensures each client only sees their own data. No application-level filtering needed — the database enforces isolation.

```sql
-- Enable RLS on all tables
ALTER TABLE findings ENABLE ROW LEVEL SECURITY;

-- Policy: users can only read their own tenant's findings
CREATE POLICY "tenant_isolation" ON findings
FOR ALL USING (tenant_id = auth.uid());
```

---

## 6. Implementation Steps

### Phase 1 — Sell Before You Build (Week 1)

Do not write a single line of scanner code this week. Your only job is to create a sales asset.

**Step 1 — Create the sample report**

Build a fake audit result using realistic numbers. A sample client: SaaS startup, $6,000/month AWS bill, found $1,800/month in waste.

Include these fake findings:
- 3 EC2 instances stopped for 30+ days — $240/month waste
- 1 RDS db.m5.large with zero connections for 21 days — $180/month waste
- 8 EBS volumes unattached (leftover from terminated instances) — $64/month waste
- 4 Elastic IPs unused — $15/month waste
- 12 S3 buckets missing lifecycle policies (accumulating old data) — estimated $180/month
- 2 RDS instances missing CloudWatch alarms — risk, not direct cost
- Cost Explorer: EC2 spend up 34% month-over-month with no new deployments

Design the PDF in Google Slides (easier than you think — use a clean template). Export as PDF.

**Step 2 — Write the IAM policy**

Create `iam_policy.json`. This is the read-only policy you give every client. Publish it on GitHub publicly. Transparency is your trust-builder.

Permissions needed:
- `ec2:Describe*`
- `rds:Describe*`
- `rds:ListTagsForResource`
- `s3:ListAllMyBuckets`
- `s3:GetBucketLocation`
- `s3:GetBucketLifecycleConfiguration`
- `cloudwatch:GetMetricStatistics`
- `cloudwatch:DescribeAlarms`
- `ce:GetCostAndUsage`
- `ce:GetCostForecast`
- `sts:GetCallerIdentity`

No write permissions. No delete permissions. Nothing that touches actual resources.

**Step 3 — Post on LinkedIn**

Post the sample report as a PDF attachment on LinkedIn:

> "I ran an AWS cost audit on a $6k/month AWS account. Found $1,800/month in waste in under 30 minutes. Here's exactly what was wasting money — and what to do about it."

This post alone will generate DMs. Repost weekly with different findings.

**Step 4 — Apply to Upwork jobs**

Search: "AWS cost optimization", "cloud cost audit", "AWS billing review". Apply to everything posted in the last 7 days. Attach the sample PDF to every proposal.

---

### Phase 2 — Build the Scanner (Weeks 2-3)

**Step 1 — Project setup**

```
Create virtual environment
Install: boto3, jinja2, weasyprint, python-dotenv, dataclasses
Create .env.example with: AWS_ROLE_ARN, REPORT_OUTPUT_DIR, CLIENT_NAME
```

**Step 2 — Build AWS client utility**

`utils/aws_client.py` — handles two connection modes:

Mode A (cross-account IAM role — preferred):
- Use `boto3.client('sts').assume_role(RoleArn=role_arn, RoleSessionName='audit')`
- Extract temporary credentials from response
- Create boto3 session with temporary credentials
- Session expires after 1 hour — long enough for any audit

Mode B (access key — fallback):
- Create boto3 session directly with access key + secret
- Only use if client cannot create an IAM role (rare)

Also build `utils/regions.py` — fetch all enabled regions for the account using `ec2:DescribeRegions`. This ensures you scan resources in regions the client may have forgotten about.

**Step 3 — Build EC2 scanner**

`scanners/ec2.py`

What to find:
- Instances in `stopped` state for more than 7 days
  - Use `StateTransitionReason` field — contains last stop time
  - Filter: stopped AND has EBS volumes (those volumes still cost money)
- Instances in `running` state with average CPU < 5% over 14 days
  - Pull CloudWatch metric: `CPUUtilization`, stat: `Average`, period: 14 days
  - Threshold: below 5% average = likely idle
- For each finding: calculate estimated monthly cost using instance type pricing table (hardcode a basic lookup for common instance types)

Savings calculation for stopped instances: cost of attached EBS volumes only (the instance itself costs nothing when stopped, but EBS does)

Savings calculation for idle running instances: full instance hourly cost × 720 hours

**Step 4 — Build RDS scanner**

`scanners/rds.py`

What to find:
- Instances with `DatabaseConnections` CloudWatch metric averaging 0 for 14 days
- Instances with `0` connections is the clearest signal of abandonment — dev databases left running after a sprint
- For Multi-AZ instances: the savings of terminating are 2× the instance price

Pricing lookup: RDS instance pricing is complex. Use a simplified lookup for common instance types (db.t3.micro, db.t3.small, db.t3.medium, db.m5.large are 80% of what you'll find).

**Step 5 — Build EBS scanner**

`scanners/ebs.py`

What to find:
- Volumes with state = `available` (not attached to any instance)
- Include: volume size, volume type (gp2/gp3/io1), creation date, last attachment (from volume description)
- Cost: gp2 = $0.10/GB/month, gp3 = $0.08/GB/month, io1 = $0.125/GB/month

This is the easiest scanner to build and often produces the most surprising findings. Clients frequently have hundreds of GB of orphaned volumes from terminated instances.

**Step 6 — Build EIP scanner**

`scanners/eip.py`

What to find:
- Elastic IPs with no `AssociationId` (not associated with any instance or NAT gateway)
- Cost: $0.005/hour per unassociated EIP = $3.60/month each
- Simple to find but creates immediate goodwill — clients feel foolish paying for unused IPs

**Step 7 — Build S3 scanner**

`scanners/s3.py`

What to find:
- Buckets with no lifecycle configuration (`GetBucketLifecycleConfiguration` returns `NoSuchLifecycleConfiguration`)
- Buckets with objects older than 90 days and no transition to Infrequent Access
- Large buckets: use `cloudwatch:GetMetricStatistics` with `BucketSizeBytes` metric to get size without listing all objects

Note: S3 savings estimates are harder to quantify without listing all objects. Frame these as "at risk" findings rather than guaranteed savings. Recommend: "Configure lifecycle policy to move objects older than 30 days to S3-IA. Estimate 40% cost reduction on this bucket."

**Step 8 — Build Cost Explorer integration**

`scanners/cost_explorer.py`

What to pull:
- 90-day cost breakdown by service (EC2, RDS, S3, CloudFront, etc.)
- Month-over-month trend for top 5 services
- Cost by region (often clients have resources running in expensive regions for no reason)
- Current month forecast vs last month actual

This data populates the "Cost Trend" section of the report — the most visually impactful section. A chart showing a cost spike last month catches executive attention immediately.

**Step 9 — Build report generator**

`reports/generator.py`

Assemble all findings into an `AuditReport` dataclass:
- Client metadata (account ID, account alias, scan date, regions scanned)
- Executive summary (total findings, total estimated monthly savings, breakdown by service)
- Findings list sorted by estimated_monthly_savings DESC
- Recommendations list: top 5 actions by savings impact

**Step 10 — Build PDF renderer**

`reports/pdf.py`

Flow:
1. Pass `AuditReport` to Jinja2 template
2. Jinja2 renders HTML string
3. WeasyPrint converts HTML to PDF
4. Save to output directory

Report sections:
1. Cover page: client name, account ID, scan date, total savings headline
2. Executive summary: 3-paragraph overview (AI-generated — see Section 8)
3. Cost trend chart: 90-day spend by service (use a simple CSS bar chart in HTML — no external libraries)
4. Findings table: resource, region, issue, monthly savings, severity badge
5. Recommendations: numbered list, priority order, specific action per finding
6. Methodology: brief explanation of how findings were identified — builds credibility

**Step 11 — Build main entry point**

`main.py`

```
Load config from .env
Create AWS session (role ARN or access key)
Get enabled regions
Run all scanners in parallel (threading — one scanner per region)
Aggregate findings
Call AI layer for summary and explanations
Generate report
Save PDF to output directory
Print: "Report saved to: output/ClientName_audit_2026-05-12.pdf"
```

Run parallel region scanning using `concurrent.futures.ThreadPoolExecutor` with `max_workers=10`. A 10-region scan drops from 15 minutes to 3-4 minutes.

**Step 12 — Test on your own AWS account**

Before selling:
- Run the full tool against your own AWS account or a test account
- Verify every scanner returns plausible results
- Verify the PDF renders correctly
- Fix any formatting issues, add missing instance type pricing
- Generate your real report — this is your second sales asset

---

### Phase 3 — First Paid Client (Week 4)

**Client setup process:**

1. Client creates IAM role in their AWS account using your CloudFormation template (5-minute process — provide the template)
2. Client sends you the role ARN
3. You add role ARN to your `.env`
4. You run `python main.py`
5. You review the PDF — edit any findings that need context
6. You email the PDF with a 3-paragraph cover note
7. Collect final payment

**What to do with feedback:**
Document every finding the client questions. This improves your scanner accuracy and adds edge cases to your test suite.

---

### Phase 4 — Build V2 Platform (Month 2-3)

Only build this after 5+ manual audits. You need real client feedback before investing in a platform.

**Order of platform components to build:**

1. Supabase schema + RLS policies
2. FastAPI backend with audit trigger endpoint
3. Celery worker running scanner in background
4. S3 PDF upload + signed URL generation
5. Stripe checkout integration
6. Next.js dashboard: auth + audit list + findings view
7. PDF download from dashboard
8. Monitoring retainer: scheduled re-scans via Celery beat

---

## 7. Workflow Pipeline

### MVP Workflow (Manual)

```
CLIENT SETUP
─────────────────────────────────────────────────────────
Client creates IAM role → CloudFormation stack (5 min)
Client sends you: Role ARN
You add to .env: AWS_ROLE_ARN=arn:aws:iam::123456789:role/AuditRole

SCAN EXECUTION
─────────────────────────────────────────────────────────
python main.py
    │
    ├── boto3: assume IAM role via STS (temporary credentials)
    │
    ├── Get enabled regions (ec2:DescribeRegions)
    │
    ├── ThreadPoolExecutor (max 10 workers) — parallel region scan
    │   ├── [Region: us-east-1]
    │   │   ├── EC2 scanner → findings[]
    │   │   ├── RDS scanner → findings[]
    │   │   ├── EBS scanner → findings[]
    │   │   └── EIP scanner → findings[]
    │   ├── [Region: us-west-2]
    │   │   └── ... same scanners
    │   └── [Region: eu-west-1]
    │       └── ... same scanners
    │
    ├── S3 scanner (global — runs once, not per region)
    │
    ├── Cost Explorer (global — pulls 90-day account-level data)
    │
    ├── Aggregate all findings → AuditReport object
    │
    ├── AI layer (partner's module)
    │   ├── Generate executive summary (Claude/GPT-4o-mini)
    │   ├── Generate per-finding plain English explanations
    │   └── Generate prioritized action plan
    │
    └── PDF renderer
        ├── Jinja2: AuditReport → HTML
        └── WeasyPrint: HTML → PDF

OUTPUT
─────────────────────────────────────────────────────────
output/ClientName_audit_2026-05-12.pdf
    └── Email to client manually
```

### V2 Platform Workflow (Self-Serve)

```
CLIENT FLOW
─────────────────────────────────────────────────────────
Client signs up → Stripe checkout → account created in Supabase
Client adds AWS role ARN in dashboard
Client clicks "Run Audit"

BACKEND FLOW
─────────────────────────────────────────────────────────
POST /api/v1/audits/trigger
    │
    ├── FastAPI: validate request, create audit row (status=queued)
    ├── Return: {audit_id, status: "queued"} immediately to client
    │
    └── Celery: queue run_audit task

WORKER FLOW (async)
─────────────────────────────────────────────────────────
Celery worker picks up run_audit task
    │
    ├── Update audit status → "running"
    ├── Load encrypted credentials from Supabase
    ├── Decrypt secret (if access key method)
    ├── Assume IAM role via STS
    │
    ├── Run all scanners (parallel, same as MVP)
    │
    ├── Store each finding → Supabase findings table
    │
    ├── Call AI service → executive summary + explanations
    │   └── Store ai_summary in audit row
    │
    ├── Generate PDF → upload to S3 private bucket
    ├── Generate S3 signed URL (1-hour expiry)
    │
    ├── Update audit row: status=completed, pdf_s3_url, estimated_savings
    │
    └── Send email: "Your AWS audit is ready. Download here: [signed URL]"

CLIENT SEES
─────────────────────────────────────────────────────────
Dashboard auto-updates via Supabase Realtime subscription
    └── Audit card flips from "Running" → "Complete"
        └── Client clicks Download → gets signed S3 URL → downloads PDF
```

### CI/CD Pipeline (V2 Platform — GitHub Actions)

```
On push to main branch:
─────────────────────────────────────────────────────────
1. Run tests (pytest)
2. Run type checking (mypy)
3. Run linting (ruff)
4. Build Docker image
5. Push to GitHub Container Registry
6. Run Alembic migrations against Supabase
7. Deploy backend to Railway
8. Vercel auto-deploys frontend (triggered by push to main)

On pull request:
─────────────────────────────────────────────────────────
1. Run tests only
2. No deployment
```

---

## 8. AI Integration — For Your Partner

This section is written specifically for the AI engineer on your team. These are the AI features that add the most value to the product — prioritized by impact and implementation difficulty.

---

### AI Feature 1 — Executive Summary Generator

**Priority: High. Build this first.**

**What it does:**
Takes the structured findings JSON and generates a 3-paragraph executive summary in plain English. This is the first thing the client reads in the report. It needs to be professional, specific, and actionable.

**Input to the model:**
```
- Client company name
- Total findings count
- Total estimated monthly savings
- Top 3 findings by savings (service, resource_id, savings amount)
- 90-day cost trend (up/down X%)
- AWS account total monthly spend
```

**Output from the model:**
A 3-paragraph summary:
- Paragraph 1: What was found at a high level (total waste, key services)
- Paragraph 2: The 2-3 most impactful findings with specific dollar amounts
- Paragraph 3: Priority recommendation — what to fix first and why

**Recommended model:** Claude claude-sonnet-4-20250514 for quality. GPT-4o-mini for cost ($0.002 vs $0.003 per call — negligible at this scale).

**Prompt engineering note:**
Instruct the model to use specific dollar amounts. Forbid vague phrases like "significant savings" or "optimize costs." Every sentence must contain a specific number or a specific resource type. Clients notice vagueness immediately.

**Where it lives:** `ai/summarizer.py`

---

### AI Feature 2 — Per-Finding Plain English Explanation

**Priority: High. Build alongside Feature 1.**

**What it does:**
Each finding in the report gets a 2-sentence AI-generated explanation. The first sentence says what the problem is and why it costs money. The second says exactly what action to take and what the result will be.

**The problem without AI:**
A finding that just says "RDS instance db-prod-legacy is idle (0 connections, 21 days)" is not useful to a non-technical CTO. They need to understand: what is this, why is it costing money, what should I tell my team to do?

**Input to the model:**
```
- Service: RDS
- Resource ID: db-prod-legacy
- Finding type: idle (zero connections)
- Days idle: 21
- Instance class: db.m5.large
- Multi-AZ: true
- Estimated monthly savings: $180
```

**Output from the model:**
> "This RDS database instance has had zero connections for 21 days, suggesting it is a leftover development or testing database that is no longer in use. Terminating this instance after creating a final snapshot will save $180/month immediately, with no impact on production systems."

**Constraint in the prompt:**
- Maximum 2 sentences per finding
- Must include the resource ID by name
- Must include the exact savings figure
- Must recommend a specific action (not "consider reviewing")
- Must state the risk level of the action

**Where it lives:** `ai/recommender.py`

---

### AI Feature 3 — Anomaly Detection in Cost Trends

**Priority: Medium. Build for V2.**

**What it does:**
Analyzes 90 days of Cost Explorer data and identifies unusual cost patterns that rule-based detection misses. Flags anomalies to include in the report.

**Examples of what it detects:**
- EC2 cost spiked 45% in the last 14 days with no new deployments (possible runaway process or forgotten load test)
- Data transfer costs growing 20% month-over-month (possible architectural issue — traffic routing inefficiency)
- S3 request costs unusually high relative to storage (possible application bug making excessive API calls)

**Why this is hard to do with rules:**
Anomaly detection requires understanding context. A 45% EC2 spike is normal if the client just scaled up for a product launch. The AI can be prompted to flag the anomaly while acknowledging it may be intentional — giving the client the data without making a wrong assumption.

**Input to the model:**
The full 90-day cost breakdown by service, with month-over-month percentage changes.

**Output from the model:**
A list of flagged anomalies with: service, percentage change, time period, possible explanation, recommended investigation step.

**Where it lives:** `ai/recommender.py` — add `detect_anomalies()` function

---

### AI Feature 4 — Natural Language Audit Query (V2 Platform)

**Priority: Low. Nice to have. Build only after revenue.**

**What it does:**
Client types a question in the dashboard and gets an AI answer using their audit findings as context.

Examples:
- "Which region is costing us the most and why?"
- "If we fix only the top 3 issues, how much do we save?"
- "Which findings are safe to act on immediately with no risk?"

**Implementation:**
Pass the client's findings JSON as context to the model. Use a system prompt that instructs the model to only answer based on the provided findings data, never to invent numbers, and to always cite which finding it is referencing.

**This is a retrieval-augmented generation (RAG) use case** — straightforward for an AI engineer. The context window is small (one client's findings JSON) so no embedding or vector search needed.

**Where it lives:** New module — `ai/query.py` + a chat UI component in Next.js

---

### AI Implementation Guide — Practical Notes

**API to use:**

Use the Anthropic API (Claude) or OpenAI API. Both work. Claude produces better structured outputs. GPT-4o-mini is cheaper for high-volume use.

For Features 1 and 2: one API call per audit. Cost: $0.003-0.005 per audit. Negligible.

**Prompt storage:**

Keep all prompts in `ai/prompts.py` as constants — not scattered through the codebase. This makes prompt iteration easy. Version control your prompts like code.

**Error handling:**

If the AI API call fails, the audit should still complete and deliver the report without the AI sections. Use try/except around every AI call. Fall back to template-based text: "AI summary unavailable for this audit." Never let an AI failure block a client from getting their report.

**Caching:**

Cache AI responses in the audit row (`ai_summary`, `ai_explanation` per finding). Never regenerate on every PDF download. The AI was called once during the scan — the result is stored.

**Testing prompts:**

Before integrating into the codebase, test every prompt manually using the API playground. Use the fake findings dataset in `sample/fake_findings.json` as test input. Confirm the output is specific, accurate, and sounds professional before shipping.

---

## 9. Security

### Credential Handling — Most Important Decision

**Use cross-account IAM roles, not access keys.**

With access keys, you store the client's secret in your database. If your database is breached, you have a major liability.

With IAM roles:
- Client creates a role in their account that trusts your AWS account
- You call `sts:AssumeRole` to get temporary credentials (valid 1 hour)
- You store only the role ARN — not a secret
- Role assumption is logged in the client's own CloudTrail
- If you stop paying for your AWS account, the role stops working automatically

Provide clients with a CloudFormation template that creates the role in one click. Template creates:
- IAM role named `CostAuditRole`
- Trust policy: allows your AWS account ID to assume the role
- Permission policy: attached from your published `iam_policy.json`

This makes onboarding a 3-minute process and eliminates credential security concerns.

### Data Storage

- Generated PDFs stored in private S3 bucket
- Access only via signed URLs with 1-hour expiry
- Client findings in Supabase — encrypted at rest by default
- If storing access keys (fallback): encrypt `secret_access_key` with AES-256 at application layer before inserting into database
- Never log AWS account IDs or role ARNs in application logs

### What the IAM Policy Allows vs Forbids

| Allowed | Forbidden |
|---|---|
| Describe any EC2 resource | Start / stop / terminate instances |
| Describe any RDS resource | Create / delete databases |
| List S3 buckets | Read / write S3 object contents |
| Read CloudWatch metrics | Create / delete alarms |
| Read Cost Explorer data | Modify billing settings |
| Call sts:GetCallerIdentity | Assume other roles |

Publish this table on your sales page. It directly answers the client's biggest objection: "What if you do something to my AWS account?"

---

## 10. What You Deliver to Each Client

### Standard Deliverable (Every Audit)

1. **PDF audit report** — professional, branded, specific
   - Cover page with total savings headline
   - Executive summary (AI-generated, 3 paragraphs)
   - Cost trend section (90-day spend chart)
   - Findings table (resource, region, issue, savings, severity)
   - Top 5 recommendations in priority order
   - Methodology section

2. **Follow-up email** — sent with the report
   - 3 sentences summarizing the biggest find
   - Offer: "Happy to walk through the report on a 30-minute call"
   - Offer: "Monthly monitoring available at $350/month"

3. **IAM cleanup** — when the audit is complete
   - Remind client to delete your IAM role or rotate the assumed session
   - Shows professionalism — you don't want lingering access

### Setup You Ask the Client for

1. Create IAM role using your CloudFormation template (3 minutes)
2. Send you the role ARN (one line of text)

That is all. The less you ask from the client, the faster you close.

---

## 11. Pricing

### Package Structure

| Package | Price | Scope | Your Time |
|---|---|---|---|
| Basic Audit | $800 | Up to 3 AWS services, 1-3 regions | 2-3 hours |
| Full Audit | $1,200 | All services, all regions, Cost Explorer | 3-4 hours |
| Audit + 90-Day Monitoring | $1,500 + $350/month | Full audit + 3 automated monthly rescans | 4 hours setup |
| Agency Reseller | $500/client | You audit for an agency's multiple clients | 2 hours each |

**Never price below $800.** Clients paying less than this negotiate every finding, demand revisions, and cost you more time than they pay for. At $800+, clients read the report and implement the recommendations.

### The Guarantee

State in every proposal: "If I find less than $200/month in savings, the audit is free."

You will almost never pay this out. Every AWS account over $2,000/month has more than $200 in waste. This guarantee eliminates the client's risk and removes price objections.

### Payment Terms

- Upwork contracts: 50% at start, 50% on delivery
- Direct clients: full payment upfront via Stripe, or 50%/50% via bank transfer
- Never start work without at least 50% deposit

---

## 12. How to Find and Close Clients

### Channel 1 — Upwork (Start Today)

Search terms to target:
- "AWS cost optimization"
- "AWS cost audit"
- "cloud cost reduction"
- "AWS billing review"
- "reduce AWS costs"

Apply to every relevant job posted in the last 7 days. Send minimum 5 proposals per week.

**Proposal formula:**
- Line 1: Specific, relevant experience (not generic)
- Line 2: The guarantee
- Line 3: One question to start a conversation

Example:
> "I run AWS cost audits using automated scanners across EC2, RDS, EBS, S3, and Cost Explorer. Last month I found $1,400/month in waste for a SaaS startup with a $6k AWS bill — primarily idle RDS and 12 unattached EBS volumes.
>
> Fixed price: $1,200. Read-only access only. Delivered in 5 days. If I find less than $200/month in savings, it is free.
>
> What is your approximate current monthly AWS spend?"

**Your AWS SAA certification is your differentiator.** Include it in your Upwork title: "AWS SAA Certified | Cost Optimization & DevOps | Fixed-Price Audits"

### Channel 2 — LinkedIn Content (Week 2 Onwards)

Post once per week. Always include a specific number and a specific finding. Never post generic AWS tips.

**Content that works:**
- "Found $1,800/month in AWS waste on a $6k/month account — here is exactly what was wasting money" (with anonymized findings screenshot)
- "The 5 places every AWS account wastes money — checked 20 accounts this year" (specific list with typical savings per item)
- "CTO asked me to audit their AWS account. Found $240/month in EC2 instances stopped since January. Share this with your team." (short, shareable)

**Connect with:** CTOs, VP Engineering, DevOps leads at funded startups. 20 connection requests per day. No pitch in the first message.

### Channel 3 — Cold Email (Month 2)

Find funded startups via Crunchbase. Filter: raised seed or Series A in last 12 months, tech company, USA/UK/Canada/Australia. These companies have money, are growing fast, and have unreviewed AWS infrastructure.

Email directly to the CTO or VP Engineering:

> Subject: Found $X in AWS waste for [similar company] — worth 20 min?
>
> Hi [Name],
>
> I audit AWS accounts for SaaS startups. For a company at your stage, I typically find $500-2,000/month in waste — idle databases, orphaned volumes, missing lifecycle policies.
>
> Read-only access, delivered in 5 days, $1,200 fixed price. Free if I find less than $200/month in savings.
>
> Worth a quick call?
>
> [Your name]

Send 20 emails per week. Expect 5-10% reply rate. 2-3 calls per week. 1 client per week.

### Closing the Deal — Call Structure

**Discovery call (30 minutes):**
1. "What is your approximate monthly AWS spend?" — qualify immediately
2. "Do you have a team member who manages AWS day-to-day?"
3. "Have you looked at Cost Explorer? What did you find?"
4. "What is your biggest concern about giving someone access to your account?"

Listen for the last answer carefully. Address it directly. Then explain cross-account IAM roles — it resolves 90% of access concerns.

**After the call — same day:**

Send a one-page proposal via email. Not a long document. Three things:
- What you will do (specific scope)
- What they get (specific deliverable)
- What it costs (fixed price + guarantee)

End with: "To get started, I need your IAM role ARN and the first 50% payment via Stripe: [link]"

---

## 13. Team Split

| Responsibility | Harshil | Partner (AI Engineer) |
|---|---|---|
| AWS scanning code (boto3) | ✅ Primary | |
| IAM policy + CloudFormation template | ✅ Primary | |
| Report template design (HTML/CSS) | ✅ | |
| PDF generation (WeasyPrint) | ✅ | |
| AI executive summary (Feature 1) | | ✅ Primary |
| AI per-finding explanations (Feature 2) | | ✅ Primary |
| AI anomaly detection (Feature 3) | | ✅ Primary |
| Prompt engineering + testing | | ✅ Primary |
| FastAPI backend (V2) | ✅ Primary | |
| Celery workers (V2) | ✅ Primary | |
| Next.js dashboard (V2) | ✅ Primary | |
| Supabase schema + RLS | ✅ Primary | |
| Client discovery calls | ✅ Both | ✅ Both |
| Upwork proposals | ✅ Both | ✅ Both |
| LinkedIn content | ✅ Both | ✅ Both |
| Client report delivery and follow-up | ✅ Both | ✅ Both |

**Partner's first task:**
Get the executive summary generator (Feature 1) working against the fake findings dataset in `sample/fake_findings.json`. Output should be a professional 3-paragraph summary that could appear in a real client report. This is a 1-2 day task and should be done during Week 2 while Harshil builds the scanners.

---

## 14. 90-Day Revenue Plan

### Month 1 — Build and First Sale

**Week 1:** Sample report created, LinkedIn post live, first 5 Upwork proposals sent
**Week 2:** EC2 + EBS + EIP scanners built and tested. Partner finishes AI summary generator.
**Week 3:** RDS + S3 + Cost Explorer scanners built. PDF report fully working. Full test run on your own AWS account.
**Week 4:** First paying client. Deliver audit. Collect testimonial.

**Month 1 target:** 1-2 clients
**Month 1 revenue:** $800-$2,400

---

### Month 2 — Scale Outreach

- 5+ Upwork proposals per week
- LinkedIn posts 2x per week
- Cold email campaign starts (20 emails/week)
- Improve report based on client 1 feedback
- Add AI anomaly detection feature

**Month 2 target:** 3-5 clients
**Month 2 revenue:** $2,400-$7,500

---

### Month 3 — Add Retainer Revenue

- First retainer clients enrolled ($350/month each)
- V2 platform development starts if time allows
- Referrals from month 1-2 clients start arriving

**Month 3 target:** 5-8 audits + 2-3 retainer clients
**Month 3 revenue:** $4,000-$12,000 + $700-$1,050 MRR

---

### 6-Month Projection

| Revenue Type | Month 6 |
|---|---|
| One-time audits (8-12 per month) | $6,400-$18,000 |
| Retainer clients (10 × $350/month) | $3,500 |
| **Total** | **$9,900-$21,500/month** |

**Infrastructure cost at this scale:** $150-200/month (Railway + Supabase Pro + Vercel + S3)
**Margin:** 98%+

---

## Quick Reference

| Item | Detail |
|---|---|
| Build time (MVP) | 2-3 weeks |
| Your time per client (after MVP) | 2-4 hours |
| Price per client | $800-$1,500 |
| Client's break-even point | 1-2 months of savings |
| Best platform to start | Upwork |
| Best content platform | LinkedIn |
| Infrastructure cost (MVP) | $0 (run locally) |
| Infrastructure cost (V2) | ~$150/month |
| AWS API cost per audit | ~$0.20 (Cost Explorer) |
| AI API cost per audit | ~$0.01-0.05 |
| Clients needed for $10k/month | 7-12 audits + 5-8 retainers |

---

*Built for Harshil + Partner — AWS Cost Audit Tool*
*May 2026 — International clients first*
