# AWS Cost Audit Tool - Production Roadmap

> **Version:** 4.0 Planning
> **Status:** Phase 7 Complete - Ready for Production Deployment
> **Last Updated:** May 2025

---

## Table of Contents

1. [Implementation Summary](#1-implementation-summary)
2. [Phase 8: Production Deployment](#2-phase-8-production-deployment)
3. [Phase 9: Enterprise Features](#3-phase-9-enterprise-features)
4. [Phase 10: SaaS Platform](#4-phase-10-saas-platform)
5. [Phase 11: Advanced Analytics](#5-phase-11-advanced-analytics)
6. [Architecture Decisions](#6-architecture-decisions)
7. [Security Hardening](#7-security-hardening)
8. [Monitoring & Observability](#8-monitoring--observability)

---

## 1. Implementation Summary

### Completed Phases (1-7)

| Phase | Scope | Status |
|-------|-------|--------|
| Phase 1 | Project setup, data models, config | Complete |
| Phase 2 | Core scanners (EC2, RDS, EBS, EIP, S3, Cost Explorer) | Complete |
| Phase 3 | AI integration (OpenRouter GPT-4o-mini) | Complete |
| Phase 4 | PDF report generation (WeasyPrint) | Complete |
| Phase 5 | CLI entry point, end-to-end flow | Complete |
| Phase 6 | Sample report generator for demos | Complete |
| Phase 7 | Advanced scanners (Savings Plans, Compute Optimizer, Trusted Advisor) | Complete |

### Current Capabilities

```
9 AWS Scanners
├── EC2         - Stopped instances, low CPU utilization
├── RDS         - Zero-connection databases, stopped instances
├── EBS         - Unattached volumes
├── Snapshots   - Old/orphaned (DLM-aware, AWS Backup-aware)
├── EIP         - Unassociated Elastic IPs
├── S3          - Buckets without lifecycle policies
├── Cost Explorer - Spending trends, service breakdown
├── Reserved Instances - Coverage gap analysis
├── Savings Plans - Coverage and utilization analysis
├── Compute Optimizer - ML-based EC2 rightsizing (opt-in)
└── Trusted Advisor - Cost optimization checks (Business/Enterprise)
```

### Technical Stack (Locked)

| Component | Technology | Purpose |
|-----------|------------|---------|
| Language | Python 3.12 | Core application |
| AWS SDK | boto3 | All AWS API calls |
| AI | OpenRouter (GPT-4o-mini) | Report summarization |
| Templates | Jinja2 | HTML report generation |
| PDF | WeasyPrint | Professional PDF output |
| Config | python-dotenv | Environment management |
| Parallelism | concurrent.futures | Multi-region scanning |
| Data Models | dataclasses | Type-safe structures |
| Testing | pytest | 64 tests, mocked boto3 |

### Code Metrics

| Metric | Value |
|--------|-------|
| Source Files | 32 |
| Test Files | 8 |
| Lines of Code | ~3,500 |
| Test Coverage | 64 tests passing |
| IAM Permissions | 38 read-only actions |

---

## 2. Phase 8: Production Deployment

**Goal:** Deploy production-grade infrastructure for client scanning.

### 8.1 Containerization

```dockerfile
# Dockerfile (already exists - enhance)
FROM python:3.12-slim

# WeasyPrint dependencies
RUN apt-get update && apt-get install -y \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Non-root user for security
RUN useradd -m auditor && chown -R auditor:auditor /app
USER auditor

ENTRYPOINT ["python", "main.py"]
```

**Tasks:**
- [ ] Multi-stage build for smaller image (~200MB target)
- [ ] Health check endpoint for container orchestration
- [ ] Resource limits (CPU: 1 core, Memory: 2GB)
- [ ] Secrets injection via environment variables

### 8.2 AWS Infrastructure (Terraform)

```hcl
# infrastructure/main.tf

# ECS Fargate for serverless container execution
resource "aws_ecs_cluster" "audit_cluster" {
  name = "cost-audit-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

# Task definition for audit jobs
resource "aws_ecs_task_definition" "audit_task" {
  family                   = "cost-audit"
  requires_compatibilities = ["FARGATE"]
  network_mode            = "awsvpc"
  cpu                     = 1024    # 1 vCPU
  memory                  = 2048    # 2 GB
  execution_role_arn      = aws_iam_role.ecs_execution.arn
  task_role_arn           = aws_iam_role.audit_task.arn
}

# S3 for report storage
resource "aws_s3_bucket" "reports" {
  bucket = "cost-audit-reports-${var.environment}"

  versioning {
    enabled = true
  }

  lifecycle_rule {
    enabled = true
    expiration {
      days = 90  # Reports expire after 90 days
    }
  }
}

# Secrets Manager for API keys
resource "aws_secretsmanager_secret" "openrouter" {
  name = "cost-audit/openrouter-api-key"
}
```

### 8.3 CI/CD Pipeline (GitHub Actions)

```yaml
# .github/workflows/deploy.yml
name: Deploy

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt
      - run: pytest tests/ -v --tb=short

  build:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE }}
          aws-region: us-east-1
      - name: Build and push to ECR
        run: |
          aws ecr get-login-password | docker login --username AWS --password-stdin $ECR_REGISTRY
          docker build -t cost-audit:${{ github.sha }} .
          docker push $ECR_REGISTRY/cost-audit:${{ github.sha }}

  deploy:
    needs: build
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - name: Update ECS service
        run: |
          aws ecs update-service \
            --cluster cost-audit-cluster \
            --service audit-service \
            --force-new-deployment
```

### 8.4 CloudFormation Template for Clients

```yaml
# client-iam-role.yaml
# One-click role creation for client onboarding

AWSTemplateFormatVersion: '2010-09-09'
Description: 'Read-only IAM role for AWS Cost Audit Tool'

Parameters:
  TrustedAccountId:
    Type: String
    Description: 'AWS Account ID of the audit provider'
    Default: '123456789012'  # Your account ID
  ExternalId:
    Type: String
    Description: 'Unique identifier for cross-account access'

Resources:
  CostAuditRole:
    Type: 'AWS::IAM::Role'
    Properties:
      RoleName: 'CostAuditReadOnlyRole'
      MaxSessionDuration: 3600  # 1 hour
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal:
              AWS: !Sub 'arn:aws:iam::${TrustedAccountId}:root'
            Action: 'sts:AssumeRole'
            Condition:
              StringEquals:
                'sts:ExternalId': !Ref ExternalId
      ManagedPolicyArns:
        - 'arn:aws:iam::aws:policy/ReadOnlyAccess'
      Policies:
        - PolicyName: 'CostExplorerAccess'
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Effect: Allow
                Action:
                  - 'ce:*'
                  - 'compute-optimizer:Get*'
                  - 'trustedadvisor:List*'
                  - 'trustedadvisor:Get*'
                Resource: '*'

Outputs:
  RoleArn:
    Description: 'Role ARN to provide to the audit service'
    Value: !GetAtt CostAuditRole.Arn
```

---

## 3. Phase 9: Enterprise Features

**Goal:** Add features required by larger organizations.

### 9.1 Multi-Account Scanning (AWS Organizations)

```python
# scanners/organizations.py

def scan_organization(session: boto3.Session) -> List[Dict]:
    """
    Discover all accounts in AWS Organization and scan each.

    Flow:
    1. Get organization root from management account
    2. List all member accounts
    3. Assume role in each account
    4. Run full scan per account
    5. Aggregate findings with account-level grouping
    """
    org = session.client('organizations')

    # Get all active accounts
    accounts = []
    paginator = org.get_paginator('list_accounts')
    for page in paginator.paginate():
        for account in page['Accounts']:
            if account['Status'] == 'ACTIVE':
                accounts.append({
                    'id': account['Id'],
                    'name': account['Name'],
                    'email': account['Email']
                })

    return accounts


def scan_account_with_role_assumption(
    management_session: boto3.Session,
    account_id: str,
    role_name: str = 'OrganizationAccountAccessRole'
) -> List[Finding]:
    """
    Assume role in target account and run full scan.
    """
    sts = management_session.client('sts')

    credentials = sts.assume_role(
        RoleArn=f'arn:aws:iam::{account_id}:role/{role_name}',
        RoleSessionName='CostAuditOrgScan',
        DurationSeconds=3600
    )['Credentials']

    # Create session with assumed credentials
    account_session = boto3.Session(
        aws_access_key_id=credentials['AccessKeyId'],
        aws_secret_access_key=credentials['SecretAccessKey'],
        aws_session_token=credentials['SessionToken']
    )

    # Run all scanners
    from scanners import run_all_scanners
    return run_all_scanners(account_session, config)
```

**New IAM Permissions:**
```json
{
  "Effect": "Allow",
  "Action": [
    "organizations:ListAccounts",
    "organizations:DescribeOrganization",
    "organizations:ListRoots",
    "organizations:ListAccountsForParent"
  ],
  "Resource": "*"
}
```

### 9.2 Scheduled Scanning (AWS EventBridge)

```python
# lambda/scheduled_scan.py

import json
import boto3
from datetime import datetime

def handler(event, context):
    """
    Lambda handler for scheduled cost audits.

    Triggered by EventBridge rule (weekly/monthly).
    Runs full scan and stores report in S3.
    """
    # Get configuration from event or environment
    config = {
        'client_name': event.get('client_name'),
        'account_id': event.get('account_id'),
        'role_arn': event.get('role_arn'),
    }

    # Run audit
    from main import run_audit
    report_path = run_audit(config)

    # Upload to S3
    s3 = boto3.client('s3')
    s3.upload_file(
        report_path,
        'cost-audit-reports',
        f"{config['client_name']}/{datetime.now().strftime('%Y-%m')}/report.pdf"
    )

    # Send notification
    sns = boto3.client('sns')
    sns.publish(
        TopicArn='arn:aws:sns:us-east-1:123456789012:audit-complete',
        Message=json.dumps({
            'client': config['client_name'],
            'report_url': f"s3://cost-audit-reports/{config['client_name']}/...",
            'findings_count': report.total_findings,
            'estimated_savings': report.total_estimated_savings
        })
    )

    return {'statusCode': 200, 'body': 'Audit complete'}
```

**EventBridge Rule:**
```json
{
  "Name": "weekly-cost-audit",
  "ScheduleExpression": "cron(0 6 ? * MON *)",
  "Targets": [
    {
      "Id": "audit-lambda",
      "Arn": "arn:aws:lambda:us-east-1:123456789012:function:scheduled-scan",
      "Input": "{\"client_name\": \"Acme Corp\", \"role_arn\": \"...\"}"
    }
  ]
}
```

### 9.3 Compliance Tagging Scanner

```python
# scanners/tagging.py

REQUIRED_TAGS = ['Environment', 'Owner', 'CostCenter', 'Project']

def scan_tagging_compliance(session: boto3.Session, region: str) -> List[Finding]:
    """
    Find resources missing required tags.

    Untagged resources cannot be attributed to cost centers,
    making cost allocation and showback/chargeback impossible.
    """
    findings = []

    # Use Resource Groups Tagging API for cross-service tagging
    client = session.client('resourcegroupstaggingapi', region_name=region)

    paginator = client.get_paginator('get_resources')

    for page in paginator.paginate():
        for resource in page['ResourceTagMappingList']:
            tags = {t['Key']: t['Value'] for t in resource.get('Tags', [])}
            missing = [t for t in REQUIRED_TAGS if t not in tags]

            if missing:
                findings.append(Finding(
                    service='Tagging',
                    resource_id=resource['ResourceARN'],
                    resource_name=tags.get('Name', ''),
                    region=region,
                    finding_type='missing_tags',
                    severity='low',
                    estimated_monthly_savings=0.0,  # Compliance, not direct cost
                    recommended_action=f"Add missing tags: {', '.join(missing)}",
                    details={'missing_tags': missing, 'existing_tags': list(tags.keys())}
                ))

    return findings
```

### 9.4 FinOps Dashboard Metrics Export

```python
# exporters/prometheus.py

from prometheus_client import Gauge, CollectorRegistry, push_to_gateway

def export_metrics_to_prometheus(report: AuditReport, pushgateway_url: str):
    """
    Export audit metrics to Prometheus for FinOps dashboards.

    Enables:
    - Grafana dashboards for cost trends
    - Alerting on waste thresholds
    - Historical tracking over time
    """
    registry = CollectorRegistry()

    # Total estimated savings gauge
    savings_gauge = Gauge(
        'aws_cost_audit_estimated_savings_usd',
        'Total estimated monthly savings in USD',
        ['account_id', 'client_name'],
        registry=registry
    )
    savings_gauge.labels(
        account_id=report.account_id,
        client_name=report.client_name
    ).set(report.total_estimated_savings)

    # Findings by severity
    findings_gauge = Gauge(
        'aws_cost_audit_findings_count',
        'Number of findings by severity',
        ['account_id', 'severity'],
        registry=registry
    )
    for severity, count in [
        ('high', report.high_severity_count),
        ('medium', report.medium_severity_count),
        ('low', report.low_severity_count)
    ]:
        findings_gauge.labels(
            account_id=report.account_id,
            severity=severity
        ).set(count)

    # Push to gateway
    push_to_gateway(pushgateway_url, job='cost_audit', registry=registry)
```

---

## 4. Phase 10: SaaS Platform

**Goal:** Self-serve platform for clients to run their own audits.

### 10.1 Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SaaS Platform Architecture                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐         │
│  │   Next.js    │───▶│   FastAPI    │───▶│    Celery    │         │
│  │  Dashboard   │    │   Backend    │    │   Workers    │         │
│  └──────────────┘    └──────────────┘    └──────────────┘         │
│         │                   │                   │                  │
│         │                   │                   │                  │
│         ▼                   ▼                   ▼                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐         │
│  │   Vercel     │    │   Railway    │    │     ECS      │         │
│  │  (Frontend)  │    │  (Backend)   │    │  (Workers)   │         │
│  └──────────────┘    └──────────────┘    └──────────────┘         │
│                             │                   │                  │
│                             ▼                   ▼                  │
│                      ┌──────────────┐    ┌──────────────┐         │
│                      │   Supabase   │    │     S3       │         │
│                      │  PostgreSQL  │    │   Reports    │         │
│                      └──────────────┘    └──────────────┘         │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 10.2 Database Schema (Supabase)

```sql
-- Tenants (clients)
CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    company_name TEXT NOT NULL,
    plan TEXT DEFAULT 'starter' CHECK (plan IN ('starter', 'pro', 'enterprise')),
    stripe_customer_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- AWS Credentials (encrypted)
CREATE TABLE aws_credentials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
    credential_type TEXT CHECK (credential_type IN ('role_arn', 'access_key')),
    role_arn TEXT,
    external_id TEXT,
    access_key_id_encrypted TEXT,
    secret_key_encrypted TEXT,
    regions TEXT[] DEFAULT ARRAY['us-east-1'],
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (tenant_id)  -- One credential per tenant
);

-- Audits
CREATE TABLE audits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
    status TEXT DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    total_findings INTEGER DEFAULT 0,
    estimated_monthly_savings DECIMAL(10,2) DEFAULT 0,
    report_s3_key TEXT,
    ai_summary TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Findings
CREATE TABLE findings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    audit_id UUID REFERENCES audits(id) ON DELETE CASCADE,
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
    service TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    resource_name TEXT,
    region TEXT NOT NULL,
    finding_type TEXT NOT NULL,
    severity TEXT CHECK (severity IN ('high', 'medium', 'low')),
    estimated_monthly_savings DECIMAL(10,2),
    recommended_action TEXT,
    ai_explanation TEXT,
    details JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Row Level Security
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE aws_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE audits ENABLE ROW LEVEL SECURITY;
ALTER TABLE findings ENABLE ROW LEVEL SECURITY;

-- Tenant isolation policies
CREATE POLICY tenant_isolation ON tenants
    FOR ALL USING (id = auth.uid());

CREATE POLICY credential_isolation ON aws_credentials
    FOR ALL USING (tenant_id = auth.uid());

CREATE POLICY audit_isolation ON audits
    FOR ALL USING (tenant_id = auth.uid());

CREATE POLICY finding_isolation ON findings
    FOR ALL USING (tenant_id = auth.uid());

-- Indexes for performance
CREATE INDEX idx_audits_tenant_date ON audits(tenant_id, created_at DESC);
CREATE INDEX idx_findings_audit ON findings(audit_id);
CREATE INDEX idx_findings_savings ON findings(audit_id, estimated_monthly_savings DESC);
```

### 10.3 API Endpoints (FastAPI)

```python
# api/v1/audits.py

from fastapi import APIRouter, Depends, BackgroundTasks
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/audits", tags=["audits"])


class AuditTriggerResponse(BaseModel):
    audit_id: str
    status: str
    message: str


@router.post("/trigger", response_model=AuditTriggerResponse)
async def trigger_audit(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Database = Depends(get_db)
):
    """
    Trigger a new cost audit for the authenticated user.

    1. Create audit record (status=queued)
    2. Queue background task
    3. Return immediately with audit_id
    """
    # Create audit record
    audit = await db.audits.create(
        tenant_id=current_user.id,
        status='queued'
    )

    # Queue background task
    background_tasks.add_task(
        run_audit_task,
        audit_id=audit.id,
        tenant_id=current_user.id
    )

    return AuditTriggerResponse(
        audit_id=str(audit.id),
        status='queued',
        message='Audit queued successfully. Check status at /audits/{audit_id}'
    )


@router.get("/{audit_id}")
async def get_audit(
    audit_id: str,
    current_user: User = Depends(get_current_user),
    db: Database = Depends(get_db)
):
    """Get audit status and results."""
    audit = await db.audits.get(audit_id, tenant_id=current_user.id)

    if audit.status == 'completed':
        # Generate signed URL for PDF download
        pdf_url = generate_presigned_url(audit.report_s3_key)
        return {**audit.dict(), 'pdf_url': pdf_url}

    return audit


@router.get("/{audit_id}/findings")
async def get_findings(
    audit_id: str,
    severity: Optional[str] = None,
    service: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Database = Depends(get_db)
):
    """Get findings for an audit with optional filters."""
    findings = await db.findings.list(
        audit_id=audit_id,
        tenant_id=current_user.id,
        severity=severity,
        service=service
    )
    return findings
```

### 10.4 Stripe Integration

```python
# payments/stripe_service.py

import stripe
from config import Config

stripe.api_key = Config.STRIPE_SECRET_KEY

PRICE_IDS = {
    'starter': 'price_1234starter',      # $99/month
    'pro': 'price_1234pro',              # $299/month
    'enterprise': 'price_1234enterprise'  # $799/month
}


async def create_checkout_session(tenant_id: str, plan: str) -> str:
    """Create Stripe checkout session for subscription."""
    session = stripe.checkout.Session.create(
        customer_email=tenant.email,
        payment_method_types=['card'],
        line_items=[{
            'price': PRICE_IDS[plan],
            'quantity': 1
        }],
        mode='subscription',
        success_url=f'{Config.FRONTEND_URL}/dashboard?session_id={{CHECKOUT_SESSION_ID}}',
        cancel_url=f'{Config.FRONTEND_URL}/pricing',
        metadata={'tenant_id': tenant_id}
    )
    return session.url


async def handle_webhook(payload: bytes, signature: str):
    """Handle Stripe webhook events."""
    event = stripe.Webhook.construct_event(
        payload, signature, Config.STRIPE_WEBHOOK_SECRET
    )

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        tenant_id = session['metadata']['tenant_id']

        # Update tenant with Stripe customer ID and plan
        await db.tenants.update(
            id=tenant_id,
            stripe_customer_id=session['customer'],
            plan=get_plan_from_price(session['line_items'][0]['price']['id'])
        )

    elif event['type'] == 'customer.subscription.deleted':
        # Downgrade to free plan
        customer_id = event['data']['object']['customer']
        await db.tenants.update_by_stripe_id(
            stripe_customer_id=customer_id,
            plan='free'
        )
```

---

## 5. Phase 11: Advanced Analytics

**Goal:** ML-powered insights and predictive analytics.

### 11.1 Cost Anomaly Detection

```python
# ai/anomaly_detection.py

import numpy as np
from scipy import stats
from typing import List, Dict, Tuple


def detect_cost_anomalies(
    cost_history: List[Dict],
    sensitivity: float = 2.0
) -> List[Dict]:
    """
    Detect unusual cost patterns using statistical methods.

    Args:
        cost_history: List of {date, service, amount} dicts
        sensitivity: Z-score threshold (default 2.0 = 95% confidence)

    Returns:
        List of anomaly findings with explanations
    """
    anomalies = []

    # Group by service
    services = {}
    for entry in cost_history:
        service = entry['service']
        if service not in services:
            services[service] = []
        services[service].append(entry['amount'])

    for service, costs in services.items():
        if len(costs) < 7:  # Need at least 7 days of data
            continue

        # Calculate z-scores
        mean = np.mean(costs)
        std = np.std(costs)

        if std == 0:
            continue

        recent_cost = costs[-1]
        z_score = (recent_cost - mean) / std

        if abs(z_score) > sensitivity:
            direction = 'spike' if z_score > 0 else 'drop'
            pct_change = ((recent_cost - mean) / mean) * 100

            anomalies.append({
                'service': service,
                'anomaly_type': direction,
                'current_cost': recent_cost,
                'expected_cost': mean,
                'z_score': z_score,
                'percent_change': pct_change,
                'confidence': 1 - stats.norm.sf(abs(z_score)) * 2,
                'explanation': f"{service} cost {'increased' if direction == 'spike' else 'decreased'} "
                              f"by {abs(pct_change):.1f}% vs 30-day average"
            })

    return sorted(anomalies, key=lambda x: abs(x['z_score']), reverse=True)
```

### 11.2 Cost Forecasting

```python
# ai/forecasting.py

from datetime import datetime, timedelta
import numpy as np


def forecast_monthly_cost(
    cost_history: List[Dict],
    forecast_months: int = 3
) -> Dict:
    """
    Forecast future costs using linear regression.

    Returns:
        {
            'forecasts': [{'month': '2025-06', 'predicted': 5432.10}, ...],
            'trend': 'increasing' | 'decreasing' | 'stable',
            'monthly_change_pct': 5.2,
            'confidence': 0.85
        }
    """
    # Extract monthly totals
    months = sorted(set(entry['month'] for entry in cost_history))
    monthly_totals = []

    for month in months:
        total = sum(e['amount'] for e in cost_history if e['month'] == month)
        monthly_totals.append(total)

    # Linear regression
    x = np.arange(len(monthly_totals))
    y = np.array(monthly_totals)

    coeffs = np.polyfit(x, y, 1)
    slope, intercept = coeffs

    # Calculate R-squared for confidence
    y_pred = np.polyval(coeffs, x)
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

    # Generate forecasts
    forecasts = []
    last_month = datetime.strptime(months[-1], '%Y-%m')

    for i in range(1, forecast_months + 1):
        future_month = last_month + timedelta(days=32 * i)
        future_month = future_month.replace(day=1)
        predicted = intercept + slope * (len(monthly_totals) + i - 1)

        forecasts.append({
            'month': future_month.strftime('%Y-%m'),
            'predicted': max(0, round(predicted, 2))  # No negative costs
        })

    # Determine trend
    monthly_change = (slope / np.mean(y)) * 100 if np.mean(y) > 0 else 0

    if monthly_change > 5:
        trend = 'increasing'
    elif monthly_change < -5:
        trend = 'decreasing'
    else:
        trend = 'stable'

    return {
        'forecasts': forecasts,
        'trend': trend,
        'monthly_change_pct': round(monthly_change, 1),
        'confidence': round(max(0, r_squared), 2)
    }
```

### 11.3 Rightsizing Recommendations (Beyond Compute Optimizer)

```python
# ai/rightsizing.py

# Instance family upgrade paths
UPGRADE_PATHS = {
    # Current generation upgrades
    't3': 't3a',      # AMD-based, 10% cheaper
    'm5': 'm5a',      # AMD-based, 10% cheaper
    'c5': 'c5a',      # AMD-based, 10% cheaper
    'r5': 'r5a',      # AMD-based, 10% cheaper

    # Graviton upgrades (ARM, 20% cheaper, 40% better perf/$)
    't3': 't4g',
    'm5': 'm6g',
    'c5': 'c6g',
    'r5': 'r6g',

    # Previous gen upgrades
    't2': 't3',
    'm4': 'm5',
    'c4': 'c5',
    'r4': 'r5',
}


def analyze_rightsizing_opportunities(
    instances: List[Dict],
    metrics: Dict[str, Dict]
) -> List[Finding]:
    """
    Analyze EC2 instances for rightsizing beyond Compute Optimizer.

    Considers:
    - Instance family upgrades (AMD, Graviton)
    - Size downgrades based on utilization
    - Memory-optimized vs compute-optimized selection
    """
    findings = []

    for instance in instances:
        instance_id = instance['InstanceId']
        instance_type = instance['InstanceType']
        family = instance_type.split('.')[0]
        size = instance_type.split('.')[1]

        cpu_avg = metrics.get(instance_id, {}).get('cpu_avg', 100)
        mem_avg = metrics.get(instance_id, {}).get('memory_avg', 100)

        # Check for family upgrade opportunity
        if family in UPGRADE_PATHS:
            new_family = UPGRADE_PATHS[family]
            current_price = get_instance_price(instance_type)
            new_price = get_instance_price(f"{new_family}.{size}")

            if new_price and new_price < current_price:
                savings = (current_price - new_price) * 730  # Monthly

                findings.append(Finding(
                    service='EC2',
                    resource_id=instance_id,
                    resource_name=get_name_tag(instance),
                    region=instance['Placement']['AvailabilityZone'][:-1],
                    finding_type='upgrade_opportunity',
                    severity='low',
                    estimated_monthly_savings=savings,
                    recommended_action=f"Upgrade from {instance_type} to {new_family}.{size} "
                                       f"for {((current_price - new_price) / current_price * 100):.0f}% savings",
                    details={
                        'current_type': instance_type,
                        'recommended_type': f"{new_family}.{size}",
                        'upgrade_reason': 'newer_generation'
                    }
                ))

        # Check for size downgrade based on utilization
        if cpu_avg < 30 and mem_avg < 50:
            smaller_size = get_smaller_size(size)
            if smaller_size:
                current_price = get_instance_price(instance_type)
                new_price = get_instance_price(f"{family}.{smaller_size}")
                savings = (current_price - new_price) * 730

                findings.append(Finding(
                    service='EC2',
                    resource_id=instance_id,
                    resource_name=get_name_tag(instance),
                    region=instance['Placement']['AvailabilityZone'][:-1],
                    finding_type='oversized',
                    severity='medium',
                    estimated_monthly_savings=savings,
                    recommended_action=f"Downsize from {instance_type} to {family}.{smaller_size} "
                                       f"(CPU: {cpu_avg:.0f}%, Memory: {mem_avg:.0f}%)",
                    details={
                        'current_type': instance_type,
                        'recommended_type': f"{family}.{smaller_size}",
                        'avg_cpu': cpu_avg,
                        'avg_memory': mem_avg
                    }
                ))

    return findings
```

---

## 6. Architecture Decisions

### ADR-001: Cross-Account Access via IAM Roles

**Decision:** Use cross-account IAM role assumption instead of access keys.

**Context:** Clients need to grant access to their AWS accounts for scanning.

**Options Considered:**
1. Access keys - simple but high security risk (credentials stored)
2. IAM roles - no credentials stored, time-limited access
3. AWS SSO - enterprise only, complex setup

**Decision:** IAM roles with external ID for all client access.

**Rationale:**
- No long-term credentials stored
- Time-limited access (1 hour max)
- Full audit trail in client's CloudTrail
- Industry best practice for cross-account access
- External ID prevents confused deputy attacks

---

### ADR-002: AI Provider Selection

**Decision:** Use OpenRouter with GPT-4o-mini as primary, with fallback to template-based summaries.

**Context:** Need AI-generated summaries that are professional and cost-effective.

**Options Considered:**
1. OpenAI direct - best quality, $0.150/$0.600 per 1M tokens (4o)
2. Anthropic Claude - excellent quality, similar pricing
3. OpenRouter - model flexibility, competitive pricing
4. Self-hosted LLM - no API costs, but high infra overhead

**Decision:** OpenRouter for model flexibility; GPT-4o-mini for cost efficiency ($0.15/$0.60 per 1M tokens).

**Rationale:**
- GPT-4o-mini is 90% as good as GPT-4o at 10% of the cost
- OpenRouter allows switching models without code changes
- Cost per audit: ~$0.01-0.05 (negligible at any scale)
- Fallback to template-based summary if API fails

---

### ADR-003: PDF Generation

**Decision:** Use WeasyPrint for HTML-to-PDF conversion.

**Options Considered:**
1. WeasyPrint - CSS-based, good quality, Python native
2. Puppeteer/Playwright - Chrome-based, perfect rendering, Node.js
3. wkhtmltopdf - deprecated, security issues
4. ReportLab - Python native, programmatic only (no HTML)

**Decision:** WeasyPrint for Python-native solution with CSS support.

**Rationale:**
- Native Python, no external process
- Good CSS support for professional layouts
- Active development and maintenance
- Reasonable PDF quality for business reports

---

## 7. Security Hardening

### 7.1 Secrets Management

```python
# utils/secrets.py

from functools import lru_cache
import boto3
from botocore.exceptions import ClientError


@lru_cache(maxsize=10)
def get_secret(secret_name: str, region: str = 'us-east-1') -> str:
    """
    Retrieve secret from AWS Secrets Manager.

    Caches results for efficiency (secrets rarely change).
    """
    client = boto3.client('secretsmanager', region_name=region)

    try:
        response = client.get_secret_value(SecretId=secret_name)
        return response['SecretString']
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceNotFoundException':
            raise ValueError(f"Secret {secret_name} not found")
        raise


# Usage in config.py
class Config:
    OPENROUTER_API_KEY = get_secret('cost-audit/openrouter-api-key')
```

### 7.2 Input Validation

```python
# utils/validation.py

import re
from typing import Optional


def validate_role_arn(arn: str) -> bool:
    """Validate AWS IAM role ARN format."""
    pattern = r'^arn:aws:iam::\d{12}:role/[\w+=,.@-]+$'
    return bool(re.match(pattern, arn))


def validate_account_id(account_id: str) -> bool:
    """Validate AWS account ID format."""
    return bool(re.match(r'^\d{12}$', account_id))


def validate_region(region: str) -> bool:
    """Validate AWS region format."""
    valid_regions = [
        'us-east-1', 'us-east-2', 'us-west-1', 'us-west-2',
        'eu-west-1', 'eu-west-2', 'eu-west-3', 'eu-central-1',
        'ap-northeast-1', 'ap-northeast-2', 'ap-southeast-1', 'ap-southeast-2',
        'ap-south-1', 'sa-east-1', 'ca-central-1'
    ]
    return region in valid_regions


def sanitize_client_name(name: str) -> str:
    """Sanitize client name for use in filenames."""
    # Remove any characters that aren't alphanumeric, space, hyphen, or underscore
    sanitized = re.sub(r'[^\w\s-]', '', name)
    # Replace spaces with underscores
    sanitized = sanitized.replace(' ', '_')
    # Limit length
    return sanitized[:50]
```

### 7.3 Rate Limiting

```python
# utils/rate_limiter.py

import time
from collections import defaultdict
from threading import Lock


class RateLimiter:
    """
    Thread-safe rate limiter for AWS API calls.

    Prevents hitting AWS API rate limits during large scans.
    """

    def __init__(self):
        self.calls = defaultdict(list)
        self.lock = Lock()

        # AWS API limits (requests per second)
        self.limits = {
            'ec2': 100,
            'rds': 25,
            'cloudwatch': 400,
            's3': 100,
            'ce': 5,  # Cost Explorer is very limited
            'compute-optimizer': 10,
            'trustedadvisor': 10,
        }

    def acquire(self, service: str):
        """Acquire permission to make an API call."""
        limit = self.limits.get(service, 50)

        with self.lock:
            now = time.time()
            # Remove calls older than 1 second
            self.calls[service] = [t for t in self.calls[service] if now - t < 1]

            if len(self.calls[service]) >= limit:
                # Wait until we can make another call
                sleep_time = 1 - (now - self.calls[service][0])
                if sleep_time > 0:
                    time.sleep(sleep_time)

            self.calls[service].append(time.time())


# Global rate limiter instance
rate_limiter = RateLimiter()
```

---

## 8. Monitoring & Observability

### 8.1 Structured Logging

```python
# utils/logging.py

import json
import logging
import sys
from datetime import datetime


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def format(self, record):
        log_entry = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }

        # Add extra fields
        if hasattr(record, 'audit_id'):
            log_entry['audit_id'] = record.audit_id
        if hasattr(record, 'account_id'):
            log_entry['account_id'] = record.account_id
        if hasattr(record, 'region'):
            log_entry['region'] = record.region
        if hasattr(record, 'scanner'):
            log_entry['scanner'] = record.scanner
        if hasattr(record, 'duration_ms'):
            log_entry['duration_ms'] = record.duration_ms

        # Add exception info if present
        if record.exc_info:
            log_entry['exception'] = self.formatException(record.exc_info)

        return json.dumps(log_entry)


def setup_logging(level: str = 'INFO'):
    """Configure structured JSON logging."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level))
    root_logger.addHandler(handler)

    # Suppress noisy boto3 logs
    logging.getLogger('boto3').setLevel(logging.WARNING)
    logging.getLogger('botocore').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
```

### 8.2 CloudWatch Metrics

```python
# utils/cloudwatch_metrics.py

import boto3
from datetime import datetime


class AuditMetrics:
    """Publish custom metrics to CloudWatch."""

    def __init__(self, namespace: str = 'CostAuditTool'):
        self.client = boto3.client('cloudwatch', region_name='us-east-1')
        self.namespace = namespace

    def record_audit_duration(self, duration_seconds: float, client_name: str):
        """Record how long an audit took."""
        self.client.put_metric_data(
            Namespace=self.namespace,
            MetricData=[{
                'MetricName': 'AuditDuration',
                'Value': duration_seconds,
                'Unit': 'Seconds',
                'Dimensions': [
                    {'Name': 'Client', 'Value': client_name}
                ]
            }]
        )

    def record_findings_count(self, count: int, severity: str, client_name: str):
        """Record number of findings by severity."""
        self.client.put_metric_data(
            Namespace=self.namespace,
            MetricData=[{
                'MetricName': 'FindingsCount',
                'Value': count,
                'Unit': 'Count',
                'Dimensions': [
                    {'Name': 'Client', 'Value': client_name},
                    {'Name': 'Severity', 'Value': severity}
                ]
            }]
        )

    def record_estimated_savings(self, amount: float, client_name: str):
        """Record total estimated monthly savings."""
        self.client.put_metric_data(
            Namespace=self.namespace,
            MetricData=[{
                'MetricName': 'EstimatedMonthlySavings',
                'Value': amount,
                'Unit': 'None',  # USD
                'Dimensions': [
                    {'Name': 'Client', 'Value': client_name}
                ]
            }]
        )

    def record_scanner_error(self, scanner: str, region: str):
        """Record scanner errors for alerting."""
        self.client.put_metric_data(
            Namespace=self.namespace,
            MetricData=[{
                'MetricName': 'ScannerErrors',
                'Value': 1,
                'Unit': 'Count',
                'Dimensions': [
                    {'Name': 'Scanner', 'Value': scanner},
                    {'Name': 'Region', 'Value': region}
                ]
            }]
        )
```

### 8.3 Health Checks

```python
# api/health.py

from fastapi import APIRouter, Response
from datetime import datetime
import boto3

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """Basic health check for load balancer."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@router.get("/health/deep")
async def deep_health_check():
    """
    Deep health check verifying all dependencies.

    Checks:
    - AWS STS (can get caller identity)
    - Database connectivity
    - S3 bucket access
    - OpenRouter API
    """
    checks = {}

    # AWS STS
    try:
        sts = boto3.client('sts')
        sts.get_caller_identity()
        checks['aws'] = 'healthy'
    except Exception as e:
        checks['aws'] = f'unhealthy: {str(e)}'

    # Database
    try:
        # Supabase ping
        from db import supabase
        supabase.table('tenants').select('id').limit(1).execute()
        checks['database'] = 'healthy'
    except Exception as e:
        checks['database'] = f'unhealthy: {str(e)}'

    # S3
    try:
        s3 = boto3.client('s3')
        s3.head_bucket(Bucket='cost-audit-reports')
        checks['s3'] = 'healthy'
    except Exception as e:
        checks['s3'] = f'unhealthy: {str(e)}'

    # Determine overall status
    all_healthy = all(v == 'healthy' for v in checks.values())
    status_code = 200 if all_healthy else 503

    return Response(
        content=json.dumps({
            'status': 'healthy' if all_healthy else 'degraded',
            'checks': checks,
            'timestamp': datetime.utcnow().isoformat()
        }),
        status_code=status_code,
        media_type='application/json'
    )
```

---

## Quick Reference

### Next Actions (Priority Order)

1. **Phase 8.1** - Containerization (1-2 days)
   - Optimize Dockerfile
   - Set up ECR repository
   - Configure ECS Fargate

2. **Phase 8.3** - CI/CD Pipeline (1 day)
   - GitHub Actions workflow
   - Automated testing
   - Deployment to ECS

3. **Phase 8.4** - Client CloudFormation (1 day)
   - One-click role creation
   - External ID for security
   - Documentation

4. **Phase 9.2** - Scheduled Scanning (2-3 days)
   - Lambda function
   - EventBridge rules
   - SNS notifications

### Cost Estimates

| Component | Monthly Cost |
|-----------|--------------|
| ECS Fargate (on-demand) | ~$50 |
| S3 (report storage) | ~$5 |
| CloudWatch Logs | ~$10 |
| Secrets Manager | ~$1 |
| **Total (MVP)** | **~$66/month** |

### Success Metrics

| Metric | Target |
|--------|--------|
| Audit completion rate | >99% |
| Audit duration | <10 minutes |
| Customer satisfaction | >4.5/5 |
| Monthly recurring audits | 50+ |
| Platform uptime | 99.9% |

---

*AWS Cost Audit Tool - Production Roadmap v4.0*
*Built for scale, security, and reliability*
