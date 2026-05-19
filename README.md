# AWS Cost Audit Tool

Production-ready CLI tool that scans AWS accounts for wasted spend and generates professional PDF audit reports with AI-powered insights.

## Features

- **10 Resource Scanners** - Comprehensive coverage of common cost waste
- **AI-Powered Summaries** - Executive summaries and recommendations
- **Professional PDF Reports** - Client-ready output with charts and tables
- **AWS Bedrock Support** - Use Claude AI via AWS credentials (no API key needed)
- **Read-Only Scanning** - Zero-risk auditing with minimal IAM permissions
- **Multi-Region Support** - Parallel scanning across regions

## Scanners

| Scanner | What It Finds | Monthly Impact |
|---------|---------------|----------------|
| **EC2** | Stopped instances, low CPU utilization | $50-500+ |
| **RDS** | Idle databases (zero connections) | $100-1000+ |
| **EBS** | Unattached volumes | $10-100+ |
| **EIP** | Unassociated Elastic IPs | $3.60 each |
| **S3** | Buckets without lifecycle policies | Varies |
| **Snapshots** | Old/orphaned snapshots (DLM-aware) | $0.05/GB |
| **NAT Gateway** | Idle gateways, high data transfer | $32+/gateway |
| **Load Balancer** | Idle ALB/NLB/CLB with no targets | $16-18/each |
| **CloudWatch Logs** | No retention policy, stale groups | $0.03/GB |
| **ECS** | Empty clusters, idle services | Varies |

**Additional Analysis:**
- Cost Explorer trends and anomalies
- Savings Plans coverage and utilization
- Compute Optimizer recommendations (ML-based)
- Trusted Advisor checks (Business/Enterprise Support)

## Quick Start

### 1. Install

```bash
git clone https://github.com/YogiHarshil/aws-cost-audit-tool.git
cd aws-cost-audit-tool
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env`:
```bash
AWS_PROFILE=your-profile
CLIENT_NAME=Client Name

# AI (choose one):
USE_BEDROCK=true                    # Uses AWS credentials
# OR
OPENAI_API_KEY=sk-proj-...          # OpenAI API key
```

### 3. Run

```bash
python main.py
```

Output: `output/{client}_audit_{date}.pdf`

## IAM Permissions

Attach `iam_policy.json` to your IAM role/user. Contains 40 read-only actions:

```bash
aws iam put-role-policy \
  --role-name CostAuditRole \
  --policy-name AuditPolicy \
  --policy-document file://iam_policy.json
```

**Key permissions:**
- EC2: DescribeInstances, DescribeVolumes, DescribeNatGateways
- RDS: DescribeDBInstances, DescribeDBClusters
- ELB: DescribeLoadBalancers, DescribeTargetGroups
- CloudWatch: GetMetricStatistics, DescribeLogGroups
- ECS: ListClusters, DescribeServices
- Cost Explorer: GetCostAndUsage, GetSavingsPlansCoverage
- Bedrock: ListFoundationModels, InvokeModel (optional, for AI)

## CLI Options

```bash
python main.py --help

Options:
  --region        Regions to scan (default: all enabled)
  --skip-ai       Skip AI summaries
  --exclude-tags  Skip resources with specific tags
  --output        Output directory (default: ./output)
```

Examples:
```bash
# Scan specific regions
python main.py --region us-east-1,us-west-2

# Skip AI (faster, no API needed)
python main.py --skip-ai

# Exclude production resources
python main.py --exclude-tags "Environment=Production"
```

## AI Configuration

### AWS Bedrock (Recommended)

Uses your AWS credentials - no separate API key needed.

1. Enable Bedrock model access in AWS Console:
   - Bedrock > Model Access > Enable Claude 3 Haiku

2. Add Bedrock permissions to IAM policy (included in `iam_policy.json`)

3. Configure `.env`:
   ```bash
   USE_BEDROCK=true
   BEDROCK_MODEL=anthropic.claude-3-haiku-20240307-v1:0
   ```

**Cost:** ~$0.01-0.05 per audit (Claude 3 Haiku pricing)

### OpenAI / OpenRouter

```bash
OPENAI_API_KEY=sk-proj-...
OPENAI_MODEL=gpt-4o-mini
```

## Project Structure

```
aws-cost-audit-tool/
├── main.py              # CLI entry point
├── config.py            # Configuration
├── iam_policy.json      # IAM permissions (40 actions)
├── scanners/            # 10 resource scanners
│   ├── ec2.py
│   ├── rds.py
│   ├── ebs.py
│   ├── eip.py
│   ├── s3.py
│   ├── snapshots.py
│   ├── nat_gateway.py
│   ├── load_balancer.py
│   ├── cloudwatch_logs.py
│   └── ecs.py
├── ai/                  # AI integration
│   ├── summarizer.py
│   ├── recommender.py
│   ├── bedrock_summarizer.py
│   └── prompts.py
├── reports/             # Report generation
│   ├── generator.py
│   ├── pdf.py
│   └── templates/
├── models/              # Data models
├── utils/               # AWS client, pricing
└── tests/               # Test suite
```

## Development

```bash
# Run tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html
```

## Troubleshooting

**WeasyPrint on Windows:**
The PDF generator requires GTK. Use `run_audit_html.py` as alternative:
```bash
python run_audit_html.py
# Opens HTML in browser - print as PDF
```

**Bedrock access denied:**
Enable model access in AWS Console > Bedrock > Model Access

**No findings:**
- Verify AWS credentials: `aws sts get-caller-identity`
- Check region has resources: `aws ec2 describe-instances --region us-east-1`

## License

MIT

## Support

Issues: https://github.com/YogiHarshil/aws-cost-audit-tool/issues
