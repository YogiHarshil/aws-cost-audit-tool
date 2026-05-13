# AWS Cost Audit Tool

Python CLI tool that scans AWS accounts for wasted spend and generates professional PDF audit reports with AI-powered summaries.

## Features

- **6 Scanner Types**: EC2, RDS, EBS, EIP, S3, Cost Explorer
- **AI-Powered**: GPT-4o-mini summaries and recommendations
- **Professional PDFs**: Client-ready reports with charts and tables
- **Fast Scans**: Complete audits in <30 minutes
- **Read-Only**: Zero-risk AWS scanning with minimal IAM permissions

## Quick Start

### Prerequisites

- Python 3.12+
- AWS account with read-only audit access
- OpenAI API key (optional, for AI summaries)

### Installation

```bash
# Clone repository
git clone https://github.com/YogiHarshil/aws-cost-audit-tool.git
cd aws-cost-audit-tool

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Configuration

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Configure AWS credentials (choose one):
   ```bash
   # Option A: Use AWS CLI profile
   AWS_PROFILE=default

   # Option B: Use IAM role (recommended)
   AWS_ROLE_ARN=arn:aws:iam::123456789012:role/CostAuditRole
   ```

3. Add OpenAI API key (optional):
   ```bash
   OPENAI_API_KEY=sk-proj-your-key-here
   ```

4. Set client name:
   ```bash
   CLIENT_NAME=Acme Corporation
   ```

### Usage

Basic scan:
```bash
python main.py
```

Skip AI summaries (faster, no API key needed):
```bash
python main.py --skip-ai
```

Scan specific regions:
```bash
python main.py --region us-east-1,us-west-2
```

Exclude tagged resources:
```bash
python main.py --exclude-tags "Environment=Production"
```

## IAM Permissions

Attach the minimal read-only policy to your IAM role/user:

```bash
# Use the provided policy
aws iam put-role-policy --role-name CostAuditRole --policy-name AuditPolicy --policy-document file://iam_policy.json
```

See `iam_policy.json` for the complete policy.

## Output

Reports are saved to `output/aws_audit_{account_id}_{date}.pdf`

Example output:
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

## Troubleshooting

### "AWS credentials not configured"
```bash
# Verify AWS credentials
aws sts get-caller-identity
```

### "OPENAI_API_KEY required"
Either add key to `.env` or use `--skip-ai` flag

### WeasyPrint installation issues
- **Windows**: Install GTK3 runtime
- **macOS**: `brew install cairo pango gdk-pixbuf libffi`
- **Linux**: `sudo apt-get install python3-dev libcairo2 libpango-1.0-0`

## Development

Run tests:
```bash
pytest
```

Run with coverage:
```bash
pytest --cov=. --cov-report=html
```

## Security

- Never commit `.env` files
- Use IAM roles instead of access keys
- Rotate OpenAI API keys regularly
- Review `iam_policy.json` for read-only permissions

## License

MIT

## Support

Report issues at: https://github.com/YogiHarshil/aws-cost-audit-tool/issues
