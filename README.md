# AWS Cost Audit Tool

Python CLI tool that scans AWS accounts for wasted spend and generates professional PDF audit reports with AI-powered summaries.

## Features

- **9 Scanner Types**: EC2, RDS, EBS, EIP, S3, Cost Explorer, Savings Plans, Compute Optimizer, Trusted Advisor
- **AI-Powered**: GPT-4o-mini summaries and recommendations via OpenRouter
- **Professional PDFs**: Client-ready reports with charts, tables, and proper page breaks
- **ML-Based Rightsizing**: AWS Compute Optimizer integration for EC2 recommendations
- **Savings Plans Analysis**: Coverage and utilization checks for commitment optimization
- **Trusted Advisor Integration**: Cost optimization recommendations (Business/Enterprise Support)
- **DLM-Aware Snapshots**: Correctly identifies AWS-managed snapshots (Backup + DLM)
- **Fast Parallel Scans**: Multi-region concurrent scanning
- **Read-Only**: Zero-risk AWS scanning with 38 minimal IAM permissions

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

## Scanners

| Scanner | Description | AWS Service |
|---------|-------------|-------------|
| **EC2** | Stopped instances, low CPU utilization | EC2, CloudWatch |
| **RDS** | Idle databases (zero connections) | RDS, CloudWatch |
| **EBS** | Unattached volumes, old snapshots | EC2 |
| **EIP** | Unassociated Elastic IPs | EC2 |
| **S3** | Buckets without lifecycle policies | S3 |
| **Cost Explorer** | Spending trends, anomalies | Cost Explorer |
| **Savings Plans** | Coverage gaps, underutilization | Cost Explorer |
| **Compute Optimizer** | ML-based EC2 rightsizing | Compute Optimizer |
| **Trusted Advisor** | Cost optimization checks | Trusted Advisor |

**Note**: Compute Optimizer requires opt-in. Trusted Advisor requires Business/Enterprise Support plan. Both gracefully skip if unavailable.

## IAM Permissions

Attach the minimal read-only policy (38 actions) to your IAM role/user:

```bash
# Use the provided policy
aws iam put-role-policy --role-name CostAuditRole --policy-name AuditPolicy --policy-document file://iam_policy.json
```

See `iam_policy.json` for the complete policy.

### Required Permissions Summary

```
EC2:           DescribeInstances, DescribeVolumes, DescribeSnapshots, DescribeAddresses
RDS:           DescribeDBInstances, DescribeDBClusters
CloudWatch:    GetMetricStatistics
S3:            ListAllMyBuckets, GetBucketLifecycleConfiguration, GetBucketLocation
Cost Explorer: GetCostAndUsage, GetSavingsPlansCoverage, GetSavingsPlansUtilization
Compute Opt:   GetEnrollmentStatus, GetEC2InstanceRecommendations
Trusted Adv:   ListRecommendations, GetRecommendation
```

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

## Project Structure

```
aws-cost-audit-tool/
├── main.py                 # CLI entry point
├── config.py               # Configuration loader
├── scanners/               # AWS resource scanners
│   ├── ec2.py              # EC2 instance scanner
│   ├── rds.py              # RDS database scanner
│   ├── ebs.py              # EBS volume scanner
│   ├── snapshots.py        # EBS snapshot scanner (DLM-aware)
│   ├── eip.py              # Elastic IP scanner
│   ├── s3.py               # S3 bucket scanner
│   ├── cost_explorer.py    # Cost trends scanner
│   ├── reserved_instances.py # RI coverage scanner
│   ├── savings_plans.py    # Savings Plans coverage/utilization
│   ├── compute_optimizer.py # ML-based rightsizing
│   └── trusted_advisor.py  # TA cost optimization checks
├── ai/                     # AI integration
│   ├── summarizer.py       # Report summarization
│   ├── recommender.py      # Recommendation engine
│   └── prompts.py          # Prompt templates
├── reports/                # Report generation
│   ├── generator.py        # Report builder
│   ├── pdf.py              # WeasyPrint PDF output
│   └── templates/          # Jinja2 HTML templates
├── models/                 # Data models
│   ├── finding.py          # Finding dataclass
│   └── report.py           # Report dataclass
├── utils/                  # Utilities
│   ├── aws_client.py       # boto3 session management
│   └── pricing.py          # AWS pricing lookups
├── tests/                  # Test suite
├── sample/                 # Sample report generator
├── docs/                   # Documentation
│   └── CHANGELOG.md        # Version history and changes
└── output/                 # Generated PDFs (gitignored)
```

## License

MIT

## Support

Report issues at: https://github.com/YogiHarshil/aws-cost-audit-tool/issues
