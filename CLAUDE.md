# AWS Cost Audit Tool

> **Version:** 3.1.0 | **Status:** Production Ready

## What this project is
Python CLI tool that scans AWS accounts for wasted spend and generates
professional PDF audit reports with AI summaries. Productized service —
built once, run for multiple clients at $800–$1,500 per audit.

## Quick Stats
- **10 Resource Scanners** + Cost Explorer, Savings Plans, Compute Optimizer, Trusted Advisor
- **40 IAM Actions** (all read-only)
- **AWS Bedrock Support** for AI summaries (no external API key needed)

## Tech Stack
- Python 3.12 + boto3 (AWS scanning)
- Jinja2 + WeasyPrint (PDF reports)
- AWS Bedrock / OpenAI (AI summaries)
- pytest (testing)

## Project Structure
```
main.py              ← CLI entry point
config.py            ← Configuration
iam_policy.json      ← 40 read-only IAM actions

scanners/            ← 10 resource scanners
  ec2.py             - Stopped/idle EC2 instances
  rds.py             - Idle RDS databases
  ebs.py             - Unattached EBS volumes
  eip.py             - Unassociated Elastic IPs
  s3.py              - S3 without lifecycle
  snapshots.py       - Old/orphaned snapshots
  nat_gateway.py     - Idle NAT Gateways
  load_balancer.py   - Idle ALB/NLB/CLB
  cloudwatch_logs.py - Logs without retention
  ecs.py             - Empty/idle ECS clusters

ai/                  ← AI integration
  summarizer.py      - OpenAI summarization
  bedrock_summarizer.py - AWS Bedrock AI
  recommender.py     - Recommendations
  prompts.py         - Prompt templates

reports/             ← Report generation
  templates/         - Jinja2 HTML templates
  generator.py       - Report builder
  pdf.py             - WeasyPrint PDF

models/              ← Data models
utils/               ← AWS client, pricing
tests/               ← Test suite
sample/              ← Sample report generator
output/              ← Generated PDFs (gitignored)
```

## Scanners (10 resource + 4 analysis)
| Scanner | What it finds | APIs |
|---------|---------------|------|
| EC2 | Stopped instances, low CPU | ec2, cloudwatch |
| RDS | Zero-connection databases | rds, cloudwatch |
| EBS | Unattached volumes | ec2 |
| Snapshots | Old/orphaned (DLM-aware) | ec2 |
| EIP | Unassociated IPs | ec2 |
| S3 | No lifecycle policy | s3 |
| NAT Gateway | Idle gateways | ec2, cloudwatch |
| Load Balancer | Idle ALB/NLB/CLB | elbv2, elb |
| CloudWatch Logs | No retention policy | logs |
| ECS | Empty clusters, idle services | ecs |
| Cost Explorer | Spending trends | ce |
| Savings Plans | Coverage/utilization | ce |
| Compute Optimizer | ML rightsizing | compute-optimizer |
| Trusted Advisor | Cost checks | trustedadvisor |

## Non-negotiables
- Never commit .env or credentials
- Read-only AWS access only
- All functions have type hints
- Tests use mocked boto3

## Key files for common tasks
- Add scanner: `scanners/`, `main.py`, `iam_policy.json`
- Fix PDF: `reports/templates/report.html`
- AI prompts: `ai/prompts.py`
- Tests: `tests/test_scanners.py`

## Session start
Read this file, run `git status`, confirm ready.
