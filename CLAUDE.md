# AWS Cost Audit Tool

> **Version:** 3.0.0 | **Status:** Production Ready | **Phases 1-7:** Complete

## What this project is
Python CLI tool that scans AWS accounts for wasted spend and generates
professional PDF audit reports with AI summaries. Productized service —
built once, run for multiple clients at $800–$1,500 per audit.

## Quick Stats
- **9 AWS Scanners** covering EC2, RDS, EBS, EIP, S3, Snapshots, Cost Explorer, RI, Savings Plans, Compute Optimizer, Trusted Advisor
- **64 Tests** with mocked boto3 (no real AWS calls)
- **38 IAM Actions** (all read-only)
- **~3,500 Lines** of production code

## Tech Stack (locked — do not change)
- Python 3.12 + boto3 (AWS scanning)
- Jinja2 (HTML templating)
- WeasyPrint (HTML to PDF)
- OpenRouter API — GPT-4o-mini (AI summaries)
- python-dotenv (config)
- concurrent.futures (parallel scanning)
- dataclasses (models)
- pytest (tests)

## Project structure
```
scanners/           ← 9 AWS resource scanners
  ec2.py            - Stopped/low-utilization EC2 instances
  rds.py            - Idle RDS databases
  ebs.py            - Unattached EBS volumes
  snapshots.py      - Old/orphaned snapshots (DLM-aware)
  eip.py            - Unassociated Elastic IPs
  s3.py             - S3 buckets without lifecycle
  cost_explorer.py  - Spending trends
  reserved_instances.py - RI coverage gaps
  savings_plans.py  - SP coverage/utilization
  compute_optimizer.py - ML-based EC2 rightsizing
  trusted_advisor.py - TA cost optimization checks

ai/                 ← AI integration
  summarizer.py     - Report summarization
  recommender.py    - Recommendation engine
  prompts.py        - Prompt templates

reports/            ← Report generation
  templates/        - Jinja2 HTML templates
  generator.py      - Report builder
  pdf.py            - WeasyPrint PDF output

models/             ← Data models
  finding.py        - Finding dataclass
  report.py         - Report dataclass

utils/              ← Utilities
  aws_client.py     - boto3 session management
  pricing.py        - AWS pricing lookups

tests/              ← Test suite (64 tests)
sample/             ← Sample report generator
docs/               ← Documentation
  CHANGELOG.md      - Version history + code docs
output/             ← Generated PDFs (gitignored)

main.py             - CLI entry point
config.py           - Configuration loader
requirements.txt    - Python dependencies
iam_policy.json     - 38 read-only IAM actions
```

## Scanners (9 total)
| Scanner | What it finds | AWS APIs |
|---------|---------------|----------|
| EC2 | Stopped instances, low CPU | ec2, cloudwatch |
| RDS | Zero-connection databases | rds, cloudwatch |
| EBS | Unattached volumes | ec2 |
| Snapshots | Old/orphaned (skips DLM/Backup managed) | ec2 |
| EIP | Unassociated IPs | ec2 |
| S3 | No lifecycle policy | s3 |
| Cost Explorer | Spending trends | ce |
| Reserved Instances | Low coverage | ce |
| Savings Plans | Low coverage/utilization | ce |
| Compute Optimizer | Over-provisioned EC2 (ML) | compute-optimizer |
| Trusted Advisor | Cost optimization checks | trustedadvisor |

## Non-negotiables
- Never commit .env or any credentials
- Read-only AWS access only — 38 IAM actions, no write/delete
- All functions have type hints and docstrings
- Tests use mocked boto3 — no real AWS calls in tests
- Never add "Co-Authored-By: Claude" to commits

## Build phases (all complete)
- Phase 1: Project setup + data models
- Phase 2: AWS scanners (ec2, rds, ebs, eip, s3, cost_explorer)
- Phase 3: AI integration (summarizer, recommender)
- Phase 4: Report generation (HTML template + PDF)
- Phase 5: main.py CLI + end-to-end
- Phase 6: Sample report for sales demos
- Phase 7: Advanced scanners (savings_plans, compute_optimizer, trusted_advisor)

## Next phases (see NEXT_PHASE.md)
- Phase 8: Production deployment (Docker, ECS, CI/CD)
- Phase 9: Enterprise features (multi-account, scheduled scans)
- Phase 10: SaaS platform (FastAPI, Supabase, Stripe)
- Phase 11: Advanced analytics (anomaly detection, forecasting)

## Session start
Read this file, run `git log --oneline -5`, confirm in 3 lines, wait for instructions.

## Key files for common tasks
- Add new scanner: `scanners/`, `main.py` (import + call), `iam_policy.json`, `models/finding.py` (if new type)
- Fix PDF styling: `reports/templates/report.html`
- Change AI prompts: `ai/prompts.py`
- Add tests: `tests/test_scanners.py` (mock boto3 clients)
