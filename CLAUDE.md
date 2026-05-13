# AWS Cost Audit Tool

## What this project is
Python CLI tool that scans AWS accounts for wasted spend and generates
professional PDF audit reports with AI summaries. Productized service —
built once, run for multiple clients at $800–$1,500 per audit.

## Tech Stack (locked — do not change)
- Python 3.12 + boto3 (AWS scanning)
- Jinja2 (HTML templating)
- WeasyPrint (HTML to PDF)
- OpenAI API — GPT-4o-mini (AI summaries)
- python-dotenv (config)
- concurrent.futures (parallel scanning)
- dataclasses (models)
- pytest (tests)

## Project structure
scanners/   ← ec2.py, rds.py, ebs.py, eip.py, s3.py, cost_explorer.py
ai/         ← summarizer.py, recommender.py, prompts.py
reports/    ← templates/, generator.py, pdf.py
models/     ← finding.py, report.py
utils/      ← aws_client.py, pricing.py
tests/      ← test_models.py, test_scanners.py, test_ai.py, test_reports.py, test_e2e.py
sample/     ← generate_sample.py
output/     ← generated PDFs (gitignored)
main.py, config.py, requirements.txt, iam_policy.json

## Non-negotiables
- Never commit .env or any credentials
- Read-only AWS access only — no write/delete permissions ever
- All functions have type hints and docstrings
- Tests use mocked boto3 — no real AWS calls in tests
- Never add "Co-Authored-By: Claude" to commits
- Work on dev branch by default

## Build phases (execute in order, test each before next)
Phase 1: Project setup + data models
Phase 2: AWS scanners (ec2, rds, ebs, eip, s3, cost_explorer)
Phase 3: AI integration (summarizer, recommender)
Phase 4: Report generation (HTML template + PDF)
Phase 5: main.py CLI + end-to-end
Phase 6: Sample report for sales demos

## Session start
Read this file, run git log --oneline -5, confirm in 3 lines, wait for instructions.