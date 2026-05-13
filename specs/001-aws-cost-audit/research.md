# Research Document: AWS Cost Audit Tool

**Feature**: 001-aws-cost-audit
**Date**: 2026-05-13
**Purpose**: Resolve technical unknowns and establish implementation patterns

---

## Table of Contents

1. [AWS Pricing API Integration](#1-aws-pricing-api-integration)
2. [CloudWatch Metrics Best Practices](#2-cloudwatch-metrics-best-practices)
3. [WeasyPrint PDF Styling](#3-weasyprint-pdf-styling)
4. [boto3 Error Handling Patterns](#4-boto3-error-handling-patterns)
5. [Tag Filtering Implementation](#5-tag-filtering-implementation)

---

## 1. AWS Pricing API Integration

### Decision
Use AWS Pricing API in real-time with session-level caching to ensure accurate, current pricing for all savings calculations.

### Rationale
- **Accuracy**: Real-time pricing ensures calculations reflect current AWS rates
- **Completeness**: Covers all regions and instance types without manual maintenance
- **Session caching**: Minimizes API calls (>95% cache hit rate expected)
- **Acceptable latency**: 200-500ms per cold call, <1ms cached

### Implementation Pattern

**Client Setup** (us-east-1 only):
```python
import boto3
from botocore.config import Config

config = Config(
    region_name='us-east-1',  # Pricing API only available here
    retries={'max_attempts': 5, 'mode': 'adaptive'}
)
pricing_client = boto3.client('pricing', config=config)
```

**Region Name Mapping** (critical):
```python
REGION_NAME_MAPPING = {
    'us-east-1': 'US East (N. Virginia)',
    'us-west-2': 'US West (Oregon)',
    'eu-west-1': 'EU (Ireland)',
    # ... full mapping in utils/pricing.py
}
```

**Query Pattern** (EC2 example):
```python
def get_ec2_instance_price(instance_type: str, region: str) -> float:
    location = REGION_NAME_MAPPING.get(region, region)

    filters = [
        {'Type': 'TERM_MATCH', 'Field': 'ServiceCode', 'Value': 'AmazonEC2'},
        {'Type': 'TERM_MATCH', 'Field': 'instanceType', 'Value': instance_type},
        {'Type': 'TERM_MATCH', 'Field': 'location', 'Value': location},
        {'Type': 'TERM_MATCH', 'Field': 'operatingSystem', 'Value': 'Linux'},
        {'Type': 'TERM_MATCH', 'Field': 'tenancy', 'Value': 'Shared'},
    ]

    response = pricing_client.get_products(
        ServiceCode='AmazonEC2',
        Filters=filters,
        MaxResults=1
    )

    # Parse nested JSON structure
    price_item = json.loads(response['PriceList'][0])
    on_demand = price_item['terms']['OnDemand']
    price_dimensions = list(on_demand.values())[0]['priceDimensions']
    return float(list(price_dimensions.values())[0]['pricePerUnit']['USD'])
```

**Session-Level Cache**:
```python
class PricingCache:
    def __init__(self):
        self._cache: Dict[str, float] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[float]:
        with self._lock:
            return self._cache.get(key)

    def set(self, key: str, price: float):
        with self._lock:
            self._cache[key] = price
```

**IAM Permissions Required**:
```json
{
  "Action": ["pricing:GetProducts"],
  "Resource": "*"
}
```

### Alternatives Considered
- **Hardcoded pricing table**: Rejected due to maintenance burden and staleness risk
- **30-day cached pricing**: Rejected for MVP simplicity (session cache sufficient)

### Performance Impact
- Pre-warming cache: 20 common instance types × 5 regions = 100 queries in ~2 seconds
- During scan: >95% cache hits, <1ms per cached lookup
- Total pricing overhead per audit: ~5-10 seconds

---

## 2. CloudWatch Metrics Best Practices

### Decision
Query CloudWatch metrics individually per resource with 14-day lookback, using Average statistic with 86400-second (1-day) period. Skip resources with missing metrics (conservative approach).

### Rationale
- **Accuracy**: 14-day window balances recent behavior vs. anomalies
- **Cost efficiency**: 1-day period minimizes datapoint charges
- **Conservative**: Skipping resources without metrics prevents false positives
- **Performance**: Individual queries with ThreadPoolExecutor (parallel)

### Implementation Pattern

**EC2 CPU Utilization**:
```python
def get_ec2_cpu_utilization(instance_id: str, region: str) -> Optional[float]:
    """
    Get average CPU utilization over last 14 days.
    Returns None if no data available (skip resource).
    """
    cloudwatch = boto3.client('cloudwatch', region_name=region)

    end_time = datetime.utcnow()
    start_time = end_time - timedelta(days=14)

    try:
        response = cloudwatch.get_metric_statistics(
            Namespace='AWS/EC2',
            MetricName='CPUUtilization',
            Dimensions=[{'Name': 'InstanceId', 'Value': instance_id}],
            StartTime=start_time,
            EndTime=end_time,
            Period=86400,  # 1 day
            Statistics=['Average']
        )

        if not response['Datapoints']:
            logger.warning(f"No CloudWatch data for {instance_id}, skipping")
            return None

        # Calculate average across all datapoints
        avg_cpu = sum(dp['Average'] for dp in response['Datapoints']) / len(response['Datapoints'])
        return avg_cpu

    except ClientError as e:
        logger.error(f"CloudWatch query failed for {instance_id}: {e}")
        return None
```

**RDS Database Connections**:
```python
def get_rds_connections(db_instance_id: str, region: str) -> Optional[float]:
    """
    Get max DatabaseConnections over last 14 days.
    Returns None if no data (skip resource).
    """
    cloudwatch = boto3.client('cloudwatch', region_name=region)

    end_time = datetime.utcnow()
    start_time = end_time - timedelta(days=14)

    try:
        response = cloudwatch.get_metric_statistics(
            Namespace='AWS/RDS',
            MetricName='DatabaseConnections',
            Dimensions=[{'Name': 'DBInstanceIdentifier', 'Value': db_instance_id}],
            StartTime=start_time,
            EndTime=end_time,
            Period=86400,
            Statistics=['Maximum']  # Use Maximum to detect any connections
        )

        if not response['Datapoints']:
            logger.warning(f"No CloudWatch data for {db_instance_id}, skipping")
            return None

        max_connections = max(dp['Maximum'] for dp in response['Datapoints'])
        return max_connections

    except ClientError as e:
        logger.error(f"CloudWatch query failed for {db_instance_id}: {e}")
        return None
```

**S3 Bucket Size** (from clarifications):
```python
def get_s3_bucket_size(bucket_name: str, region: str) -> Optional[int]:
    """
    Get bucket size in bytes using CloudWatch BucketSizeBytes metric.
    Returns None if no data available.
    """
    cloudwatch = boto3.client('cloudwatch', region_name=region)

    end_time = datetime.utcnow()
    start_time = end_time - timedelta(days=2)  # Recent datapoint

    try:
        response = cloudwatch.get_metric_statistics(
            Namespace='AWS/S3',
            MetricName='BucketSizeBytes',
            Dimensions=[
                {'Name': 'BucketName', 'Value': bucket_name},
                {'Name': 'StorageType', 'Value': 'StandardStorage'}
            ],
            StartTime=start_time,
            EndTime=end_time,
            Period=86400,
            Statistics=['Average']
        )

        if not response['Datapoints']:
            return None

        # Get most recent datapoint
        latest = sorted(response['Datapoints'], key=lambda x: x['Timestamp'])[-1]
        return int(latest['Average'])

    except ClientError:
        return None
```

**Parallel Querying**:
```python
def batch_get_metrics(resources: List[Dict], metric_func) -> Dict[str, float]:
    """Query metrics for multiple resources in parallel."""
    results = {}

    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_resource = {
            executor.submit(metric_func, r['id'], r['region']): r['id']
            for r in resources
        }

        for future in as_completed(future_to_resource):
            resource_id = future_to_resource[future]
            try:
                value = future.result()
                results[resource_id] = value
            except Exception as e:
                logger.error(f"Metric query failed for {resource_id}: {e}")
                results[resource_id] = None

    return results
```

### IAM Permissions
```json
{
  "Action": [
    "cloudwatch:GetMetricStatistics",
    "cloudwatch:GetMetricData"
  ],
  "Resource": "*"
}
```

### Cost Optimization
- 1 datapoint per day × 14 days = 14 datapoints per resource
- CloudWatch pricing: First 10,000 metrics free, then $0.01 per 1,000 requests
- Expected cost per audit: <$0.10 for typical account

### Alternatives Considered
- **Batch GetMetricData**: More complex, same cost, not worth complexity for MVP
- **Shorter lookback (7 days)**: Rejected—too short to detect patterns
- **Longer lookback (30 days)**: Rejected—costs 2x, diminishing returns

---

## 3. WeasyPrint PDF Styling

### Decision
Use WeasyPrint with CSS3 print media queries for professional PDF generation. Embed matplotlib charts as base64-encoded PNG images inline in HTML.

### Rationale
- **Professional output**: CSS gives full control over styling, page breaks, headers
- **No dependencies**: WeasyPrint handles fonts, layout natively
- **Chart quality**: PNG embedding ensures consistent rendering
- **Cross-platform**: Works on Windows, macOS, Linux

### Implementation Pattern

**HTML Template Structure** (`reports/templates/report.html`):
```html
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>AWS Cost Audit Report - {{ client_name }}</title>
    <style>
        @page {
            size: letter;
            margin: 1in 0.75in;
            @top-center {
                content: "AWS Cost Audit - {{ client_name }}";
                font-size: 10pt;
                color: #666;
            }
            @bottom-right {
                content: "Page " counter(page) " of " counter(pages);
                font-size: 10pt;
                color: #666;
            }
        }

        body {
            font-family: 'Helvetica Neue', Arial, sans-serif;
            font-size: 11pt;
            color: #333;
            line-height: 1.6;
        }

        /* Cover page */
        .cover {
            page-break-after: always;
            text-align: center;
            padding-top: 3in;
        }

        .cover h1 {
            font-size: 36pt;
            color: #0066cc;
            margin-bottom: 0.5in;
        }

        .cover .savings {
            font-size: 48pt;
            color: #00aa44;
            font-weight: bold;
        }

        /* Executive summary */
        .executive-summary {
            page-break-after: always;
        }

        /* Findings table */
        table {
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
            page-break-inside: auto;
        }

        tr {
            page-break-inside: avoid;
            page-break-after: auto;
        }

        th {
            background-color: #0066cc;
            color: white;
            padding: 12px;
            text-align: left;
            font-weight: bold;
        }

        td {
            padding: 10px 12px;
            border-bottom: 1px solid #ddd;
        }

        tr:nth-child(even) {
            background-color: #f9f9f9;
        }

        /* Severity badges */
        .severity {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-weight: bold;
            font-size: 9pt;
        }

        .severity-high {
            background-color: #ff4444;
            color: white;
        }

        .severity-medium {
            background-color: #ff9933;
            color: white;
        }

        .severity-low {
            background-color: #ffcc00;
            color: #333;
        }

        /* Charts */
        .chart {
            text-align: center;
            margin: 30px 0;
        }

        .chart img {
            max-width: 100%;
            height: auto;
        }
    </style>
</head>
<body>
    <!-- Cover page -->
    <div class="cover">
        <h1>AWS Cost Audit Report</h1>
        <h2>{{ client_name }}</h2>
        <p>Report Date: {{ report_date }}</p>
        <div class="savings">{{ "${:,.0f}".format(total_savings) }}</div>
        <p>Estimated Monthly Savings</p>
    </div>

    <!-- Executive Summary -->
    <div class="executive-summary">
        <h1>Executive Summary</h1>
        <p>{{ executive_summary }}</p>

        <div class="chart">
            <h3>90-Day Cost Trend</h3>
            <img src="{{ cost_chart_base64 }}" alt="Cost Trend Chart">
        </div>
    </div>

    <!-- Findings Table -->
    <h1>Findings Detail</h1>
    <table>
        <thead>
            <tr>
                <th>Resource</th>
                <th>Type</th>
                <th>Region</th>
                <th>Issue</th>
                <th>Monthly Savings</th>
                <th>Severity</th>
            </tr>
        </thead>
        <tbody>
            {% for finding in findings %}
            <tr>
                <td>{{ finding.resource_id }}</td>
                <td>{{ finding.resource_type }}</td>
                <td>{{ finding.region }}</td>
                <td>{{ finding.description }}</td>
                <td>${{ "{:,.2f}".format(finding.monthly_savings) }}</td>
                <td>
                    <span class="severity severity-{{ finding.severity.lower() }}">
                        {{ finding.severity }}
                    </span>
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>

    <!-- Recommendations -->
    <div style="page-break-before: always;">
        <h1>Top 5 Recommendations</h1>
        {% for rec in recommendations %}
        <div style="margin-bottom: 30px;">
            <h3>{{ loop.index }}. {{ rec.title }}</h3>
            <p><strong>Impact:</strong> ${{ "{:,.0f}".format(rec.impact) }}/month</p>
            <p><strong>Difficulty:</strong> {{ rec.difficulty }}</p>
            <p>{{ rec.description }}</p>
        </div>
        {% endfor %}
    </div>
</body>
</html>
```

**Chart Generation** (matplotlib):
```python
import matplotlib.pyplot as plt
import base64
from io import BytesIO

def generate_cost_chart(cost_data: Dict[str, float]) -> str:
    """
    Generate cost trend chart and return as base64-encoded PNG.

    Args:
        cost_data: Dict mapping date strings to costs

    Returns:
        Base64-encoded data URL for embedding in HTML
    """
    fig, ax = plt.subplots(figsize=(10, 5))

    dates = list(cost_data.keys())
    costs = list(cost_data.values())

    ax.plot(dates, costs, linewidth=2, color='#0066cc', marker='o')
    ax.set_xlabel('Date', fontsize=12)
    ax.set_ylabel('Daily Cost ($)', fontsize=12)
    ax.set_title('90-Day Cost Trend', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)

    # Rotate x-axis labels
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()

    # Save to base64
    buffer = BytesIO()
    plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
    buffer.seek(0)
    image_base64 = base64.b64encode(buffer.read()).decode()
    plt.close(fig)

    return f"data:image/png;base64,{image_base64}"
```

**PDF Conversion** (`reports/pdf.py`):
```python
from weasyprint import HTML, CSS

def generate_pdf(html_content: str, output_path: str) -> None:
    """
    Convert HTML to PDF using WeasyPrint.

    Args:
        html_content: Rendered Jinja2 HTML string
        output_path: Absolute path to save PDF
    """
    HTML(string=html_content).write_pdf(
        output_path,
        stylesheets=[CSS(string='@page { size: letter; }')]
    )
```

### Dependencies
```txt
weasyprint>=60.0
matplotlib>=3.8.0
Pillow>=10.0.0  # Required by WeasyPrint for image handling
```

### Alternatives Considered
- **ReportLab**: Lower-level, more code, harder to maintain
- **pdfkit/wkhtmltopdf**: External binary dependency, harder to deploy
- **LaTeX**: Overkill for business reports, steeper learning curve

---

## 4. boto3 Error Handling Patterns

### Decision
Use boto3's adaptive retry mode with custom exception handling that logs errors and continues with partial results. Never fail entire audit due to single resource/region failures.

### Rationale
- **Resilience**: Partial results better than no results
- **Client value**: Deliver audit even if some regions/services unavailable
- **Operational reality**: Transient errors common in AWS APIs
- **Logging**: Capture all errors for post-audit review

### Implementation Pattern

**Client Configuration**:
```python
from botocore.config import Config

def create_aws_client(service: str, region: str):
    """Create boto3 client with retry configuration."""
    config = Config(
        region_name=region,
        retries={
            'max_attempts': 5,
            'mode': 'adaptive'  # Automatically handles throttling
        },
        connect_timeout=10,
        read_timeout=30
    )
    return boto3.client(service, config=config)
```

**Exception Handling Pattern**:
```python
from botocore.exceptions import ClientError, BotoCoreError, NoCredentialsError

def safe_scanner_operation(operation_func, *args, **kwargs):
    """
    Wrapper for scanner operations with comprehensive error handling.

    Returns:
        Operation result on success, None on failure
    """
    try:
        return operation_func(*args, **kwargs)

    except NoCredentialsError:
        logger.error("AWS credentials not configured")
        raise  # Critical error, must stop

    except ClientError as e:
        error_code = e.response['Error']['Code']

        if error_code == 'UnauthorizedOperation':
            logger.warning(f"Access denied for {operation_func.__name__}: {e}")
            return None  # Skip this operation

        elif error_code == 'RequestLimitExceeded':
            logger.warning(f"Rate limit exceeded for {operation_func.__name__}")
            return None  # Retries exhausted, skip

        elif error_code == 'InvalidParameterValue':
            logger.error(f"Invalid parameters for {operation_func.__name__}: {e}")
            return None

        else:
            logger.error(f"AWS API error in {operation_func.__name__}: {error_code}")
            return None

    except BotoCoreError as e:
        logger.error(f"Boto core error in {operation_func.__name__}: {e}")
        return None

    except Exception as e:
        logger.exception(f"Unexpected error in {operation_func.__name__}: {e}")
        return None
```

**Scanner Base Class Pattern**:
```python
class BaseScanner:
    """Base class for all AWS resource scanners."""

    def scan(self, region: str) -> List[Finding]:
        """
        Scan region for findings. Never raises exceptions.

        Returns:
            List of findings (empty list on error)
        """
        findings = []

        try:
            resources = self._fetch_resources(region)
            if resources is None:
                logger.warning(f"Skipping {region} due to fetch error")
                return findings

            for resource in resources:
                try:
                    finding = self._analyze_resource(resource)
                    if finding:
                        findings.append(finding)
                except Exception as e:
                    logger.error(f"Error analyzing {resource.get('id')}: {e}")
                    continue  # Skip this resource, continue with others

        except Exception as e:
            logger.exception(f"Critical error scanning {region}: {e}")

        return findings

    def _fetch_resources(self, region: str) -> Optional[List[Dict]]:
        """Fetch resources with error handling."""
        return safe_scanner_operation(self._do_fetch_resources, region)

    def _do_fetch_resources(self, region: str) -> List[Dict]:
        """Actual fetch logic (subclass implements)."""
        raise NotImplementedError
```

**Pagination Pattern**:
```python
def paginate_all_results(client, operation: str, **kwargs) -> List[Dict]:
    """
    Paginate through all results for a boto3 operation.

    Args:
        client: Boto3 client
        operation: Operation name (e.g., 'describe_instances')
        **kwargs: Operation parameters

    Returns:
        List of all results across pages
    """
    results = []

    try:
        paginator = client.get_paginator(operation)
        page_iterator = paginator.paginate(**kwargs)

        for page in page_iterator:
            # Extract results (key varies by service)
            for key in page:
                if isinstance(page[key], list) and key not in ['ResponseMetadata']:
                    results.extend(page[key])

    except ClientError as e:
        logger.error(f"Pagination error for {operation}: {e}")

    return results
```

### IAM Permission Errors
Handle gracefully—skip service, don't fail audit:
```python
if error_code == 'AccessDenied' or error_code == 'UnauthorizedOperation':
    logger.warning(
        f"Insufficient permissions for {service}. "
        "Add permissions to iam_policy.json if needed."
    )
    return []  # Return empty findings, continue audit
```

### Alternatives Considered
- **Fail-fast on errors**: Rejected—wastes scan time, bad UX
- **Exponential backoff without adaptive mode**: Rejected—adaptive mode better
- **No error logging**: Rejected—need visibility into failures

---

## 5. Tag Filtering Implementation

### Decision
Implement tag-based exclusion filtering with exact key=value matching. Apply filters after resource discovery but before enrichment/pricing to minimize wasted API calls.

### Rationale
- **Flexibility**: Operators can configure per-client exclusions
- **Performance**: Filter early to avoid unnecessary CloudWatch/Pricing queries
- **Simplicity**: Exact match easier to reason about than wildcards
- **Client control**: Respects client's resource tagging strategy

### Implementation Pattern

**Tag Filter Parsing**:
```python
from typing import Dict, List

def parse_exclude_tags(exclude_tags_str: str) -> List[Dict[str, str]]:
    """
    Parse comma-separated tag filters.

    Args:
        exclude_tags_str: e.g., "Environment=Production,Critical=true"

    Returns:
        List of tag dicts: [{"Key": "Environment", "Value": "Production"}, ...]
    """
    if not exclude_tags_str:
        return []

    tag_filters = []
    for tag_pair in exclude_tags_str.split(','):
        if '=' not in tag_pair:
            logger.warning(f"Invalid tag format: {tag_pair} (expected Key=Value)")
            continue

        key, value = tag_pair.split('=', 1)
        tag_filters.append({
            'Key': key.strip(),
            'Value': value.strip()
        })

    return tag_filters
```

**Tag Matching Logic**:
```python
def should_exclude_resource(resource_tags: List[Dict[str, str]],
                           exclude_filters: List[Dict[str, str]]) -> bool:
    """
    Check if resource matches any exclusion filter.

    Args:
        resource_tags: Resource tags from AWS API (list of {"Key": ..., "Value": ...})
        exclude_filters: Parsed exclusion filters

    Returns:
        True if resource should be excluded, False otherwise
    """
    if not exclude_filters:
        return False

    if not resource_tags:
        return False  # No tags = not excluded

    # Convert resource tags to dict for easier lookup
    tag_dict = {tag['Key']: tag['Value'] for tag in resource_tags}

    # Check if any filter matches
    for filter_tag in exclude_filters:
        if tag_dict.get(filter_tag['Key']) == filter_tag['Value']:
            logger.debug(
                f"Resource excluded by tag: {filter_tag['Key']}={filter_tag['Value']}"
            )
            return True

    return False
```

**Integration in Scanner**:
```python
class EC2Scanner(BaseScanner):
    def __init__(self, exclude_tags: List[Dict[str, str]]):
        self.exclude_tags = exclude_tags

    def scan(self, region: str) -> List[Finding]:
        findings = []

        # Fetch all instances
        instances = self._fetch_ec2_instances(region)

        for instance in instances:
            # Apply tag filter BEFORE enrichment
            if should_exclude_resource(instance.get('Tags', []), self.exclude_tags):
                logger.info(f"Skipping instance {instance['InstanceId']} (excluded by tags)")
                continue

            # Now enrich with CloudWatch/pricing data
            finding = self._analyze_instance(instance, region)
            if finding:
                findings.append(finding)

        return findings
```

**Configuration**:
```python
# In config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    AWS_PROFILE = os.getenv('AWS_PROFILE', 'default')
    AWS_ROLE_ARN = os.getenv('AWS_ROLE_ARN')
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    CLIENT_NAME = os.getenv('CLIENT_NAME', 'Client')
    EXCLUDE_TAGS = os.getenv('EXCLUDE_TAGS', '')  # Empty = no exclusions

    @property
    def parsed_exclude_tags(self) -> List[Dict[str, str]]:
        return parse_exclude_tags(self.EXCLUDE_TAGS)
```

**CLI Argument** (in main.py):
```python
import argparse

parser = argparse.ArgumentParser()
parser.add_argument(
    '--exclude-tags',
    type=str,
    default=os.getenv('EXCLUDE_TAGS', ''),
    help='Comma-separated tag filters to exclude (e.g., "Environment=Production,Critical=true")'
)
```

### Example Usage
```bash
# Via CLI
python main.py --exclude-tags "Environment=Production,DoNotDelete=true"

# Via .env
EXCLUDE_TAGS=Environment=Production,Critical=true
```

### Alternatives Considered
- **Prefix matching** (Environment=Prod*): Rejected for MVP—more complex, error-prone
- **Include filters instead of exclude**: Rejected—exclude is safer default
- **Case-insensitive matching**: Rejected—AWS tags are case-sensitive
- **Filter after enrichment**: Rejected—wastes CloudWatch/Pricing API calls

---

## Implementation Checklist

All research complete. Ready for Phase 1 (Design & Contracts):

- ✅ AWS Pricing API integration pattern (utils/pricing.py)
- ✅ CloudWatch metrics querying (within scanners/)
- ✅ WeasyPrint PDF styling (reports/templates/report.html, reports/pdf.py)
- ✅ boto3 error handling (scanners/base.py, utils/aws_client.py)
- ✅ Tag filtering (config.py, scanners/base.py)

**Next Steps**:
1. Create data-model.md (Finding, Report, ScanConfig dataclasses)
2. Create contracts/ (CLI interface, config schema, IAM policy)
3. Create quickstart.md (setup instructions)
4. Update CLAUDE.md with plan reference
