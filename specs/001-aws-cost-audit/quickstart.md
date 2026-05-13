# Quickstart Guide: AWS Cost Audit Tool

**Feature**: 001-aws-cost-audit
**Date**: 2026-05-13
**Purpose**: Get up and running in under 10 minutes

---

## Prerequisites

- **Python 3.12+** installed
- **AWS account** with read-only audit access
- **OpenAI API key** (optional, for AI summaries)
- **10-30 minutes** for first audit scan

---

## Step 1: Clone Repository

```bash
git clone https://github.com/YogiHarshil/aws-cost-audit-tool.git
cd aws-cost-audit-tool
```

---

## Step 2: Set Up Python Environment

### Create Virtual Environment

```bash
python -m venv venv
```

### Activate Virtual Environment

**Windows**:
```cmd
venv\Scripts\activate
```

**macOS/Linux**:
```bash
source venv/bin/activate
```

### Install Dependencies

```bash
pip install -r requirements.txt
```

**Expected output**:
```
Collecting boto3>=1.42.0
Collecting openai
Collecting jinja2
Collecting weasyprint>=60.0
...
Successfully installed boto3-1.42.0 openai-1.x.x ...
```

---

## Step 3: Configure AWS Credentials

### Option A: Use IAM Role (Recommended)

1. Create an IAM role in your AWS account with the policy from `iam_policy.json`
2. Grant your AWS user/role permission to assume this audit role
3. Add role ARN to `.env`:

```bash
cp .env.example .env
nano .env  # or use your favorite editor
```

```bash
# .env
AWS_ROLE_ARN=arn:aws:iam::123456789012:role/CostAuditRole
```

### Option B: Use AWS CLI Profile

```bash
# .env
AWS_PROFILE=default
```

Make sure profile is configured:
```bash
aws configure --profile default
# or
aws sts get-caller-identity --profile default
```

---

## Step 4: Configure OpenAI API Key (Optional)

### Get API Key

1. Sign up at https://platform.openai.com/
2. Navigate to **API Keys**
3. Create new secret key
4. Copy key immediately (it won't be shown again)

### Add to `.env`

```bash
# .env
OPENAI_API_KEY=sk-proj-abc123...
```

### Skip AI (Alternative)

If you don't have an OpenAI key, you can skip AI summaries:

```bash
python main.py --skip-ai
```

---

## Step 5: Set Client Name

```bash
# .env
CLIENT_NAME=Acme Corporation
```

Or use CLI flag:
```bash
python main.py --client-name "Acme Corporation"
```

---

## Step 6: Run Your First Audit

### Basic Scan

```bash
python main.py
```

**Expected output**:
```
AWS Cost Audit Tool v1.0.0
================================

[1/6] Scanning EC2 instances...
  ✓ us-east-1: 12 instances scanned, 5 findings
  ✓ us-west-2: 8 instances scanned, 2 findings

[2/6] Scanning RDS instances...
  ✓ us-east-1: 4 instances scanned, 1 finding

[3/6] Scanning EBS volumes...
  ✓ us-east-1: 45 volumes scanned, 12 findings

[4/6] Scanning Elastic IPs...
  ✓ us-east-1: 10 IPs scanned, 3 findings

[5/6] Scanning S3 buckets...
  ✓ Global: 22 buckets scanned, 8 findings

[6/6] Querying Cost Explorer...
  ✓ 90-day cost trend retrieved

Generating AI summaries... ✓
Rendering PDF report... ✓

================================
Audit Complete!

Report: output/aws_audit_123456789012_2026-05-13.pdf
Total Findings: 34
Estimated Monthly Savings: $4,832.50

Scan Duration: 18m 32s
================================
```

### View Report

```bash
# Windows
start output/aws_audit_123456789012_2026-05-13.pdf

# macOS
open output/aws_audit_123456789012_2026-05-13.pdf

# Linux
xdg-open output/aws_audit_123456789012_2026-05-13.pdf
```

---

## Step 7: Customize Your Scan (Optional)

### Scan Specific Regions Only

```bash
python main.py --region us-east-1,us-west-2
```

### Exclude Production Resources

```bash
python main.py --exclude-tags "Environment=Production"
```

### Skip AI Summaries (Faster)

```bash
python main.py --skip-ai
```

### Verbose Logging

```bash
python main.py --verbose
```

### Custom Output Directory

```bash
python main.py --output ./client-reports
```

### Combined Options

```bash
python main.py \
  --region us-east-1,eu-west-1 \
  --client-name "Acme Corp" \
  --exclude-tags "Environment=Production" \
  --output ./reports \
  --verbose
```

---

## Common Issues & Solutions

### Issue: "AWS credentials not configured"

**Solution**:
```bash
# Check if AWS CLI is configured
aws sts get-caller-identity

# If not, configure it
aws configure
```

Then verify `.env` has either:
- `AWS_PROFILE=your-profile` OR
- `AWS_ROLE_ARN=arn:aws:iam::123456789012:role/YourRole`

### Issue: "OPENAI_API_KEY required"

**Solution**:
Either add key to `.env`:
```bash
OPENAI_API_KEY=sk-proj-...
```

Or skip AI:
```bash
python main.py --skip-ai
```

### Issue: "Access Denied" errors during scan

**Solution**:
1. Check IAM policy in `iam_policy.json`
2. Ensure your role/user has all required permissions
3. Verify policy is attached to the role/user you're using

### Issue: "No module named 'boto3'"

**Solution**:
```bash
# Make sure virtual environment is activated
source venv/bin/activate  # macOS/Linux
venv\Scripts\activate     # Windows

# Reinstall dependencies
pip install -r requirements.txt
```

### Issue: WeasyPrint installation errors

**Windows**:
```cmd
# Install GTK3 runtime (required by WeasyPrint)
# Download from: https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases
```

**macOS**:
```bash
brew install cairo pango gdk-pixbuf libffi
```

**Linux (Ubuntu/Debian)**:
```bash
sudo apt-get install python3-dev python3-pip python3-setuptools python3-wheel python3-cffi libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 libffi-dev shared-mime-info
```

---

## Generate Sample Report (Demo)

Generate a sample report with mock data for demo purposes:

```bash
python sample/generate_sample.py
```

This creates:
```
output/sample_report_demo_2026-05-13.pdf
```

Use this for:
- Testing PDF generation without AWS scan
- Sales demos
- Template customization

---

## Configuration Examples

### Minimal Setup (No AI)

```bash
# .env
AWS_PROFILE=default
```

Run:
```bash
python main.py --skip-ai
```

### Production Setup (IAM Role + AI)

```bash
# .env
AWS_ROLE_ARN=arn:aws:iam::123456789012:role/CostAuditRole
OPENAI_API_KEY=sk-proj-abc123...
CLIENT_NAME=Acme Corporation
EXCLUDE_TAGS=Environment=Production
OUTPUT_DIR=./client-reports
```

Run:
```bash
python main.py
```

### Multi-Client Setup

```bash
# client1.env
AWS_ROLE_ARN=arn:aws:iam::111111111111:role/AuditRole
CLIENT_NAME=Client One
OUTPUT_DIR=./reports/client1

# client2.env
AWS_ROLE_ARN=arn:aws:iam::222222222222:role/AuditRole
CLIENT_NAME=Client Two
OUTPUT_DIR=./reports/client2
```

Run:
```bash
# Client 1
cp client1.env .env
python main.py

# Client 2
cp client2.env .env
python main.py
```

---

## Next Steps

### Customize Report Template

Edit `reports/templates/report.html` to:
- Add your company logo
- Change color scheme
- Modify layout

### Automate with Cron/Scheduler

```bash
# crontab -e
# Run audit every Monday at 9 AM
0 9 * * 1 cd /path/to/aws-cost-audit-tool && /path/to/venv/bin/python main.py
```

### CI/CD Integration

```yaml
# .github/workflows/audit.yml
name: Weekly AWS Audit

on:
  schedule:
    - cron: '0 9 * * 1'  # Every Monday 9 AM

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt
      - run: python main.py
        env:
          AWS_ROLE_ARN: ${{ secrets.AWS_ROLE_ARN }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
      - uses: actions/upload-artifact@v2
        with:
          name: audit-report
          path: output/*.pdf
```

### Docker Deployment

```bash
# Build image
docker build -t aws-cost-audit-tool .

# Run audit
docker run --rm \
  -v ~/.aws:/root/.aws:ro \
  -v ./output:/app/output \
  -e CLIENT_NAME="Acme Corp" \
  aws-cost-audit-tool:latest
```

---

## Performance Tips

### Faster Scans

1. **Scan specific regions only**:
   ```bash
   python main.py --region us-east-1,us-west-2
   ```

2. **Skip AI summaries**:
   ```bash
   python main.py --skip-ai
   ```

3. **Run during off-peak hours** (fewer AWS API rate limits)

### Better Accuracy

1. **Scan all regions** (default behavior)
2. **Enable AI summaries** for better recommendations
3. **Exclude known resources** with `--exclude-tags`

---

## Getting Help

### Check Logs

```bash
python main.py --verbose 2>&1 | tee audit.log
```

### Test Individual Components

```bash
# Test AWS connection
python -c "import boto3; print(boto3.client('sts').get_caller_identity())"

# Test OpenAI API
python -c "from openai import OpenAI; client = OpenAI(); print('API key valid')"

# Test config loading
python -c "from config import Config; print(Config.from_env())"
```

### Report Issues

https://github.com/YogiHarshil/aws-cost-audit-tool/issues

---

## Security Checklist

Before first run:

- [ ] `.env` file created with credentials
- [ ] `.env` is in `.gitignore`
- [ ] IAM policy uses read-only permissions only
- [ ] File permissions set: `chmod 600 .env`
- [ ] OpenAI API key is project-specific (not org-level)
- [ ] AWS role has MFA requirement (optional but recommended)

---

## Success!

You're now ready to audit AWS accounts for cost optimization opportunities. Your first report should be in the `output/` directory.

**Typical savings**: $500 - $5,000/month per account
**Audit frequency**: Monthly recommended
**Time to ROI**: First report pays for itself

Happy auditing! 🚀
