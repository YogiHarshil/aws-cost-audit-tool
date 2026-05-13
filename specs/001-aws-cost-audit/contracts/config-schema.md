# Configuration Schema

**Feature**: 001-aws-cost-audit
**Component**: Configuration (.env file)
**Date**: 2026-05-13

---

## Overview

The AWS Cost Audit Tool uses a `.env` file for configuration. This file contains AWS credentials, OpenAI API keys, and default settings. The file must be in the project root directory and is loaded using `python-dotenv`.

---

## File Location

```
aws-cost-audit-tool/
├── .env              ← Your configuration (gitignored)
├── .env.example      ← Template with example values
└── main.py
```

**CRITICAL**: `.env` must be in `.gitignore` to prevent credential exposure.

---

## Complete Schema

```bash
# AWS Configuration
AWS_PROFILE=default
AWS_ROLE_ARN=arn:aws:iam::123456789012:role/AuditRole

# OpenAI Configuration
OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Client Configuration
CLIENT_NAME=Acme Corporation

# Scan Configuration
EXCLUDE_TAGS=Environment=Production,Critical=true
OUTPUT_DIR=./output

# Optional: Logging
LOG_LEVEL=INFO
```

---

## Field Definitions

### AWS Configuration

#### `AWS_PROFILE` (optional)
- **Type**: String
- **Default**: `default`
- **Description**: AWS CLI profile name to use for credentials
- **Example**: `AWS_PROFILE=prod-audit`
- **Notes**:
  - Profile must exist in `~/.aws/credentials` or `~/.aws/config`
  - Can be overridden with `--profile` CLI flag
  - Mutually exclusive with `AWS_ROLE_ARN` (if both set, `AWS_ROLE_ARN` takes precedence)

#### `AWS_ROLE_ARN` (optional)
- **Type**: String (AWS IAM Role ARN)
- **Default**: None
- **Description**: IAM role ARN to assume for AWS API calls
- **Example**: `AWS_ROLE_ARN=arn:aws:iam::123456789012:role/CostAuditRole`
- **Format**: `arn:aws:iam::{account-id}:role/{role-name}`
- **Notes**:
  - **Recommended** for production use (more secure than static credentials)
  - Requires permissions to assume the role (via AWS_PROFILE credentials)
  - Role must have read-only permissions (see `iam_policy.json`)

**Authentication Priority**:
1. `AWS_ROLE_ARN` (if set, assume this role)
2. `AWS_PROFILE` (if set, use this profile)
3. Default AWS credential chain (environment variables, instance profile, etc.)

---

### OpenAI Configuration

#### `OPENAI_API_KEY` (conditional required)
- **Type**: String
- **Default**: None
- **Description**: OpenAI API key for GPT-4o-mini summaries
- **Example**: `OPENAI_API_KEY=sk-proj-abc123...`
- **Format**: Starts with `sk-proj-` or `sk-`
- **Required When**: AI summaries enabled (default behavior)
- **Optional When**: `--skip-ai` CLI flag used
- **Validation**: Must be non-empty if not using `--skip-ai`
- **Security**: Never commit this to version control!

**Getting an API Key**:
1. Sign up at https://platform.openai.com/
2. Navigate to API Keys section
3. Create new secret key
4. Copy to `.env` file immediately (not shown again)

**Cost Estimate**:
- GPT-4o-mini pricing: ~$0.10 per audit (typical)
- Depends on number of findings

---

### Client Configuration

#### `CLIENT_NAME` (optional)
- **Type**: String
- **Default**: AWS account alias (or account ID if no alias)
- **Description**: Client name displayed on report cover page
- **Example**: `CLIENT_NAME=Acme Corporation`
- **Notes**:
  - Can be overridden with `--client-name` CLI flag
  - Used in PDF filename: `aws_audit_{account_id}_{date}.pdf`

---

### Scan Configuration

#### `EXCLUDE_TAGS` (optional)
- **Type**: String (comma-separated key=value pairs)
- **Default**: None (no exclusions)
- **Description**: Tag filters to exclude resources from audit
- **Example**: `EXCLUDE_TAGS=Environment=Production,Critical=true,DoNotDelete=true`
- **Format**: `Key1=Value1,Key2=Value2,...`
- **Matching Logic**: Resource excluded if ANY tag matches (OR logic)
- **Notes**:
  - Can be overridden with `--exclude-tags` CLI flag
  - Case-sensitive exact matching
  - Resources without tags are never excluded

**Example Use Cases**:
```bash
# Exclude production resources
EXCLUDE_TAGS=Environment=Production

# Exclude critical and protected resources
EXCLUDE_TAGS=Critical=true,DoNotDelete=true

# Exclude specific project
EXCLUDE_TAGS=Project=Legacy,Owner=SecurityTeam
```

#### `OUTPUT_DIR` (optional)
- **Type**: String (directory path)
- **Default**: `./output`
- **Description**: Directory where PDF reports are saved
- **Example**: `OUTPUT_DIR=/var/reports/aws-audits`
- **Notes**:
  - Can be overridden with `--output` CLI flag
  - Directory created automatically if doesn't exist
  - Must have write permissions

#### `LOG_LEVEL` (optional)
- **Type**: String
- **Default**: `INFO`
- **Description**: Logging level for console output
- **Values**: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`
- **Example**: `LOG_LEVEL=DEBUG`
- **Notes**:
  - `DEBUG`: Verbose output for troubleshooting
  - `INFO`: Normal operation (recommended)
  - `WARNING`: Only warnings and errors
  - Can use `--verbose` CLI flag as shortcut for `DEBUG`

---

## Validation Rules

### Required Fields
- **None** - All fields have defaults or conditional requirements
- **Conditional**: `OPENAI_API_KEY` required if not using `--skip-ai`

### Format Validation
- `AWS_ROLE_ARN`: Must match pattern `arn:aws:iam::{account}:role/{name}`
- `OPENAI_API_KEY`: Must start with `sk-proj-` or `sk-`
- `EXCLUDE_TAGS`: Must be comma-separated `Key=Value` pairs
- `OUTPUT_DIR`: Must be valid filesystem path
- `LOG_LEVEL`: Must be in [DEBUG, INFO, WARNING, ERROR, CRITICAL]

### Validation Logic (in `config.py`)

```python
import os
from dotenv import load_dotenv

load_dotenv()

class ConfigError(Exception):
    """Configuration validation error."""
    pass

def validate_config(skip_ai: bool = False):
    """Validate required configuration."""

    # Validate OpenAI key if AI enabled
    if not skip_ai and not os.getenv('OPENAI_API_KEY'):
        raise ConfigError(
            "OPENAI_API_KEY required when AI summaries enabled. "
            "Set key in .env or use --skip-ai flag."
        )

    # Validate AWS credentials
    if not os.getenv('AWS_PROFILE') and not os.getenv('AWS_ROLE_ARN'):
        # Check default credential chain
        try:
            import boto3
            boto3.client('sts').get_caller_identity()
        except Exception:
            raise ConfigError(
                "AWS credentials not configured. "
                "Set AWS_PROFILE or AWS_ROLE_ARN in .env"
            )

    # Validate AWS_ROLE_ARN format if provided
    role_arn = os.getenv('AWS_ROLE_ARN')
    if role_arn and not role_arn.startswith('arn:aws:iam::'):
        raise ConfigError(
            f"Invalid AWS_ROLE_ARN format: {role_arn}. "
            "Expected: arn:aws:iam::{account-id}:role/{role-name}"
        )
```

---

## Example `.env` Files

### Minimal Configuration

```bash
# Minimal setup - uses default AWS credentials and skips AI
AWS_PROFILE=default
```
Run with: `python main.py --skip-ai`

### Recommended Configuration

```bash
# AWS Authentication
AWS_ROLE_ARN=arn:aws:iam::123456789012:role/CostAuditRole

# OpenAI API Key
OPENAI_API_KEY=sk-proj-abc123def456...

# Client Information
CLIENT_NAME=Acme Corporation

# Exclude production resources
EXCLUDE_TAGS=Environment=Production
```

### Full Configuration (All Options)

```bash
# AWS Configuration
AWS_PROFILE=audit-profile
AWS_ROLE_ARN=arn:aws:iam::123456789012:role/AuditRole

# OpenAI Configuration
OPENAI_API_KEY=sk-proj-abc123def456...

# Client Configuration
CLIENT_NAME=Acme Corporation

# Scan Configuration
EXCLUDE_TAGS=Environment=Production,Critical=true
OUTPUT_DIR=./client-reports

# Logging
LOG_LEVEL=INFO
```

---

## Security Best Practices

### ✅ DO

1. **Add `.env` to `.gitignore`**
   ```gitignore
   # .gitignore
   .env
   *.env
   .env.*
   ```

2. **Use IAM roles instead of access keys**
   ```bash
   AWS_ROLE_ARN=arn:aws:iam::123456789012:role/AuditRole
   ```

3. **Rotate OpenAI API keys regularly**
   - Regenerate keys every 90 days
   - Revoke old keys after rotation

4. **Set minimal IAM permissions**
   - Use provided `iam_policy.json`
   - Only grant read-only access
   - No write/delete permissions

5. **Store `.env` securely**
   - Restrict file permissions: `chmod 600 .env`
   - Don't share via email/Slack
   - Use secrets manager for production

### ❌ DON'T

1. **Never commit `.env` to Git**
   - Check with: `git status` before committing
   - Use `.env.example` for templates only

2. **Don't use AWS access keys directly in `.env`**
   ```bash
   # ❌ BAD - Don't do this
   AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
   AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
   ```
   Use `AWS_ROLE_ARN` or `AWS_PROFILE` instead.

3. **Don't share API keys in logs**
   - Tool never logs `OPENAI_API_KEY` or credentials
   - Mask sensitive values in error messages

---

## Loading Configuration

### In Code (`config.py`)

```python
import os
from dotenv import load_dotenv
from dataclasses import dataclass
from typing import Optional, List, Dict

# Load .env file
load_dotenv()

@dataclass
class Config:
    """Application configuration."""

    aws_profile: str
    aws_role_arn: Optional[str]
    openai_api_key: Optional[str]
    client_name: str
    exclude_tags: List[Dict[str, str]]
    output_dir: str
    log_level: str

    @classmethod
    def from_env(cls, cli_args=None):
        """Load configuration from environment and CLI args."""
        from utils.tag_filter import parse_exclude_tags

        return cls(
            aws_profile=cls._get_value(cli_args, 'profile', 'AWS_PROFILE', 'default'),
            aws_role_arn=os.getenv('AWS_ROLE_ARN'),
            openai_api_key=os.getenv('OPENAI_API_KEY'),
            client_name=cls._get_value(cli_args, 'client_name', 'CLIENT_NAME', 'Client'),
            exclude_tags=parse_exclude_tags(
                cls._get_value(cli_args, 'exclude_tags', 'EXCLUDE_TAGS', '')
            ),
            output_dir=cls._get_value(cli_args, 'output', 'OUTPUT_DIR', './output'),
            log_level=os.getenv('LOG_LEVEL', 'INFO')
        )

    @staticmethod
    def _get_value(cli_args, arg_name, env_name, default):
        """Get value with precedence: CLI > env > default."""
        if cli_args and hasattr(cli_args, arg_name):
            value = getattr(cli_args, arg_name)
            if value is not None:
                return value
        return os.getenv(env_name, default)
```

---

## Testing Configuration

### Verify `.env` Loading

```bash
$ python -c "from dotenv import load_dotenv; import os; load_dotenv(); print(os.getenv('AWS_PROFILE'))"
default
```

### Validate AWS Credentials

```bash
$ aws sts get-caller-identity --profile YOUR_PROFILE
{
    "UserId": "AIDAI...",
    "Account": "123456789012",
    "Arn": "arn:aws:iam::123456789012:user/audit-user"
}
```

### Test OpenAI API Key

```bash
$ python -c "from openai import OpenAI; client = OpenAI(); print('API key valid')"
API key valid
```

---

## Troubleshooting

### Error: "AWS credentials not configured"

**Solution**:
1. Check `.env` file exists: `ls -la .env`
2. Verify credentials: `cat .env | grep AWS_`
3. Test AWS access: `aws sts get-caller-identity --profile YOUR_PROFILE`

### Error: "OPENAI_API_KEY required"

**Solution**:
1. Check `.env` has key: `cat .env | grep OPENAI_API_KEY`
2. Or use `--skip-ai` flag: `python main.py --skip-ai`

### Error: "Invalid AWS_ROLE_ARN format"

**Solution**:
Check ARN format:
```bash
# ✅ Correct format
AWS_ROLE_ARN=arn:aws:iam::123456789012:role/AuditRole

# ❌ Wrong format
AWS_ROLE_ARN=AuditRole
```

---

## Next Steps

1. Copy `.env.example` to `.env`: `cp .env.example .env`
2. Fill in your credentials in `.env`
3. Verify `.env` is in `.gitignore`
4. Test configuration: `python main.py --help`
