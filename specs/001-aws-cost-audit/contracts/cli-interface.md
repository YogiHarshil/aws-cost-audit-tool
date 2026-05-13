# CLI Interface Contract

**Feature**: 001-aws-cost-audit
**Component**: Command-Line Interface
**Date**: 2026-05-13

---

## Overview

The AWS Cost Audit Tool is invoked as a Python CLI tool. It accepts configuration via command-line arguments and environment variables (.env file), executes the audit scan, and outputs a PDF report.

---

## Command Structure

```bash
python main.py [OPTIONS]
```

---

## Command-Line Options

### Required Options
None. All options have sensible defaults or fallback to environment variables.

### Optional Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--profile PROFILE` | string | `default` | AWS CLI profile name |
| `--region REGION` | string | all enabled | Comma-separated regions to scan (e.g., `us-east-1,us-west-2`) |
| `--client-name NAME` | string | AWS account alias | Client name for report cover page |
| `--skip-ai` | flag | disabled | Disable AI summaries (faster, no OpenAI key needed) |
| `--output PATH` | string | `./output` | Directory for generated PDF reports |
| `--exclude-tags TAGS` | string | none | Comma-separated tag filters (e.g., `Environment=Production,Critical=true`) |
| `--verbose` | flag | disabled | Enable debug logging to console |

### Configuration Precedence

Command-line arguments override environment variables (.env file):

```
CLI args > .env file > defaults
```

---

## Usage Examples

### Basic Scan (Default Configuration)

```bash
python main.py
```

Uses:
- AWS profile: `default`
- Regions: All enabled regions
- Client name: AWS account alias
- Output: `./output/`
- AI summaries: Enabled (requires `OPENAI_API_KEY` in .env)

### Scan Specific Regions

```bash
python main.py --region us-east-1,us-west-2
```

Scans only US East (N. Virginia) and US West (Oregon) regions.

### Skip AI Summaries

```bash
python main.py --skip-ai
```

Generates report without AI summaries (no OpenAI API key required). Useful for:
- Testing/debugging
- Environments without OpenAI access
- Faster scans

### Custom Client Name

```bash
python main.py --client-name "Acme Corporation"
```

Sets client name on report cover page.

### Exclude Tagged Resources

```bash
python main.py --exclude-tags "Environment=Production,DoNotDelete=true"
```

Skips resources with tags matching:
- `Environment=Production` OR
- `DoNotDelete=true`

(Any match triggers exclusion)

### Custom Output Directory

```bash
python main.py --output /path/to/reports
```

Saves PDF to `/path/to/reports/aws_audit_{account_id}_{date}.pdf`

### Verbose Logging

```bash
python main.py --verbose
```

Enables DEBUG-level logging to console for troubleshooting.

### Combined Options

```bash
python main.py \
  --profile prod-audit \
  --region us-east-1,eu-west-1 \
  --client-name "Acme Corp" \
  --exclude-tags "Environment=Production" \
  --output ./client-reports \
  --verbose
```

---

## Exit Codes

| Code | Meaning | Description |
|------|---------|-------------|
| `0` | Success | Audit completed successfully, PDF generated |
| `1` | Error | Critical error (missing credentials, invalid config, etc.) |
| `2` | Partial Success | Audit completed with warnings (some regions/services failed) |

### Exit Code Examples

**Success**:
```bash
$ python main.py
...
Report saved to: output/aws_audit_123456789012_2026-05-13.pdf
Total estimated monthly savings: $4,832.50
$ echo $?
0
```

**Critical Error**:
```bash
$ python main.py
ERROR: AWS credentials not configured. Set AWS_PROFILE or AWS_ROLE_ARN in .env
$ echo $?
1
```

**Partial Success** (with warnings):
```bash
$ python main.py
WARNING: Failed to scan region ap-south-1 (AccessDenied)
WARNING: Failed to fetch EBS pricing for 3 volumes
Report saved to: output/aws_audit_123456789012_2026-05-13.pdf
Total estimated monthly savings: $4,100.00 (partial results)
$ echo $?
2
```

---

## Output Format

### Console Output (stdout)

**Progress Indicators**:
```
AWS Cost Audit Tool v1.0.0
================================

[1/6] Scanning EC2 instances...
  ✓ us-east-1: 12 instances scanned, 5 findings
  ✓ us-west-2: 8 instances scanned, 2 findings
  ✓ eu-west-1: 15 instances scanned, 3 findings

[2/6] Scanning RDS instances...
  ✓ us-east-1: 4 instances scanned, 1 finding
  ✓ us-west-2: 2 instances scanned, 0 findings

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

Breakdown by Severity:
  High:   15 findings ($3,200.00)
  Medium: 12 findings ($1,400.00)
  Low:     7 findings ($232.50)

Scan Duration: 18m 32s
================================
```

**Error Messages** (stderr):
```
ERROR: Failed to authenticate with AWS using profile 'prod-audit'
ERROR: OpenAI API key not found. Set OPENAI_API_KEY in .env or use --skip-ai
WARNING: Access denied for RDS DescribeDBInstances in eu-central-1
WARNING: No CloudWatch data for instance i-abc123, skipping low-utilization check
```

---

## Help Output

```bash
$ python main.py --help
```

```
usage: main.py [-h] [--profile PROFILE] [--region REGION]
               [--client-name NAME] [--skip-ai] [--output PATH]
               [--exclude-tags TAGS] [--verbose]

AWS Cost Audit Tool - Scan AWS accounts for wasted spend and generate PDF reports.

optional arguments:
  -h, --help            show this help message and exit
  --profile PROFILE     AWS CLI profile name (default: "default")
  --region REGION       Comma-separated regions to scan (default: all enabled regions)
  --client-name NAME    Client name for report cover (default: AWS account alias)
  --skip-ai             Disable AI summaries (faster, no OpenAI key needed)
  --output PATH         Output directory for PDF reports (default: ./output)
  --exclude-tags TAGS   Comma-separated tag filters to exclude resources
                        (e.g., "Environment=Production,Critical=true")
  --verbose             Enable debug logging

Examples:
  python main.py
  python main.py --region us-east-1,us-west-2 --skip-ai
  python main.py --client-name "Acme Corp" --exclude-tags "Environment=Production"

For more information, see: https://github.com/YogiHarshil/aws-cost-audit-tool
```

---

## Environment Variables

When CLI options are not provided, the tool falls back to environment variables from `.env`:

| Variable | CLI Equivalent | Description |
|----------|----------------|-------------|
| `AWS_PROFILE` | `--profile` | AWS CLI profile name |
| `AWS_ROLE_ARN` | N/A | IAM role ARN to assume (alternative to profile) |
| `OPENAI_API_KEY` | N/A | OpenAI API key for AI summaries |
| `CLIENT_NAME` | `--client-name` | Client name for report |
| `EXCLUDE_TAGS` | `--exclude-tags` | Comma-separated tag filters |
| `OUTPUT_DIR` | `--output` | Output directory path |

**Priority**: CLI args override .env variables.

---

## Integration with CI/CD

### Automated Audits (Example)

```bash
#!/bin/bash
# audit-client.sh

# Load client-specific config
export AWS_PROFILE="client-audit-role"
export CLIENT_NAME="$1"
export EXCLUDE_TAGS="Environment=Production"

# Run audit
python main.py \
  --output "./reports/$CLIENT_NAME" \
  --verbose

# Check exit code
if [ $? -eq 0 ]; then
  echo "Audit successful!"
  # Upload to S3, send email, etc.
else
  echo "Audit failed!"
  exit 1
fi
```

### Docker Usage

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

ENTRYPOINT ["python", "main.py"]
```

```bash
docker run --rm \
  -v ~/.aws:/root/.aws:ro \
  -v ./output:/app/output \
  -e CLIENT_NAME="Acme Corp" \
  aws-cost-audit-tool:latest \
  --skip-ai
```

---

## Error Handling

### Missing Credentials

```
ERROR: AWS credentials not configured
→ Set AWS_PROFILE in .env or use --profile flag
→ Alternatively, set AWS_ROLE_ARN to assume an IAM role
→ See README.md for setup instructions

Exit code: 1
```

### Missing OpenAI Key (when AI enabled)

```
ERROR: OPENAI_API_KEY required for AI summaries
→ Set OPENAI_API_KEY in .env file
→ Or use --skip-ai flag to disable AI features

Exit code: 1
```

### Invalid Region

```
ERROR: Invalid region: us-east-99
→ Valid regions: us-east-1, us-west-2, eu-west-1, ...

Exit code: 1
```

### Output Directory Error

```
ERROR: Cannot create output directory: /invalid/path
→ Check directory permissions
→ Or specify different path with --output flag

Exit code: 1
```

---

## Performance Expectations

| Account Size | Regions | Duration | Output Size |
|--------------|---------|----------|-------------|
| Small (50-100 resources) | 2-3 | 5-10 min | 500 KB - 1 MB |
| Medium (100-500 resources) | 3-5 | 15-25 min | 1-3 MB |
| Large (500-1000 resources) | 5+ | 25-30 min | 3-5 MB |

**Target**: <30 minutes for typical medium-sized accounts

---

## Compatibility

- **Python**: 3.12+
- **Operating Systems**: Windows, macOS, Linux
- **AWS CLI**: Not required (uses boto3 directly)
- **Permissions**: Read-only IAM permissions (see `iam_policy.json`)

---

## Version Information

```bash
$ python main.py --version
AWS Cost Audit Tool v1.0.0
Python 3.12.0
boto3 1.42.0
```

---

## Next Steps

After reviewing this contract:
1. Implement argument parsing in `main.py` using `argparse`
2. Create `config.py` to merge CLI args and .env variables
3. Implement progress indicators and console output formatting
4. Write integration tests in `tests/test_e2e.py` to verify CLI behavior
