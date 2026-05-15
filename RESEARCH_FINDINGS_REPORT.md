# RESEARCH FINDINGS REPORT
## AWS Cost Audit Tool — Research-Driven Production Hardening

**Research Date:** 2026-05-15
**Researcher:** Principal AWS DevOps Engineer
**Codebase Version:** 35 Python files, 6,472 lines, 91 tests passing

---

## RESEARCH TOPIC 1: EC2 Pricing API Accuracy

### Current Code Behavior
**File:** `utils/pricing.py:109-149`

The current implementation uses `get_ec2_instance_price()` with these filters:
- ServiceCode: AmazonEC2
- instanceType, location, operatingSystem, tenancy, preInstalledSw
- capacitystatus: "Used"

### Research Findings
Per [boto3 Pricing API documentation](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/pricing/client/get_products.html):
- The API returns multiple products if filters aren't specific enough
- `capacitystatus=Used` is correct (vs "AllocatedCapacityReservation" or "UnusedCapacityReservation")

Per [AWS DescribeServices for EC2](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/using-price-list-query-api.html):
- Valid EC2 filter fields include: instanceType, location, operatingSystem, tenancy, preInstalledSw, capacitystatus, termType, memory, vcpu, physicalProcessor
- The current filter combination (7 fields) is adequate for on-demand Linux pricing

Per [StateTransitionReason boto3 docs](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/instance/state_transition_reason.html):
- Format is "User initiated (YYYY-MM-DD HH:MM:SS GMT)" for user stops
- Other formats: "Client.InternalError", "Server.InsufficientInstanceCapacity"
- Empty string is valid when no transition has occurred

### Gap Assessment: **NO GAP**

The current pricing filters are correct and sufficient for on-demand Linux EC2 pricing. The code correctly uses `capacitystatus=Used` and includes OS/tenancy filters to get the right price.

### Specific Fix Required
None. Current implementation is accurate.

**Source:** [AWS Pricing API GetProducts](https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_GetProducts.html)

---

## RESEARCH TOPIC 2: CloudWatch Metrics Best Practices

### Current Code Behavior
**Files:** `scanners/ec2.py:176-199`, `scanners/rds.py:140-170`, `scanners/s3.py:147-176`

- Uses `GetMetricStatistics` for all CloudWatch queries
- EC2: 14-day window, 86400 Period, Statistics=["Average"] for CPU
- RDS: Uses Statistics=["Maximum"] for DatabaseConnections (correct)
- S3: 3-day window for BucketSizeBytes, 86400 Period

### Research Findings
Per [AWS CloudWatch documentation](https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_GetMetricData.html):
- **GetMetricData is the recommended API** (55%+ of API volume, per 2025 stats)
- GetMetricStatistics is NOT deprecated but GetMetricData is more efficient
- Stopped instances produce NO CloudWatch datapoints (INSUFFICIENT_DATA)
- Missing datapoints are EXPECTED for stopped instances

Per [RDS CloudWatch metrics](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-metrics.html):
- DatabaseConnections: Maximum is correct for detecting "any connections"
- Period of 60 seconds is the native granularity

### Gap Assessment: **MINOR**

Current GetMetricStatistics usage is acceptable. Migration to GetMetricData would improve efficiency at scale but is not blocking.

### Specific Fix Required
No critical fix needed. Consider future migration to GetMetricData for batch efficiency.

**Source:** [Use API to retrieve data points](https://repost.aws/knowledge-center/cloudwatch-getmetricdata-api)

---

## RESEARCH TOPIC 3: Cost Explorer API Edge Cases

### Current Code Behavior
**File:** `scanners/cost_explorer.py:89-106`

- Uses `get_anomalies()` with DateInterval and MaxResults=10
- Uses `get_cost_and_usage()` with MONTHLY granularity and BlendedCost
- No LINKED_ACCOUNT filter for multi-account isolation

### Research Findings
Per [Cost Explorer GetCostAndUsage docs](https://docs.aws.amazon.com/cli/latest/reference/ce/get-cost-and-usage.html):
- LINKED_ACCOUNT dimension filter isolates specific accounts in Organizations
- Management account sees ALL member accounts by default
- BlendedCost includes credits but **daily granularity excludes refunds**

Per [GetAnomalies API](https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_GetAnomalies.html):
- Requires Cost Anomaly Detection to be configured first
- Returns anomalies up to 90 days old
- May return empty if no anomaly monitor exists (NOT an error)

### Gap Assessment: **IMPORTANT**

Current code handles missing anomaly detection gracefully. However, for multi-account Organizations, the tool may aggregate costs across accounts unexpectedly.

### Specific Fix Required
1. Document that Cost Anomaly Detection must be configured for anomaly findings
2. Consider adding optional LINKED_ACCOUNT filter for Organizations

**Source:** [Cost Explorer Filtering](https://docs.aws.amazon.com/cost-management/latest/userguide/ce-filtering.html)

---

## RESEARCH TOPIC 4: EBS Snapshot Costs and Orphan Detection

### Current Code Behavior
**File:** `scanners/snapshots.py:17-51`

- Uses `$0.05/GB/month` hardcoded pricing
- Checks for `aws:backup:source-resource-arn`, `dlm:managed`, `aws:backup:recovery-point-arn` tags
- Skips cross-region copies via description parsing

### Research Findings
Per [AWS EBS Snapshot Pricing](https://aws.amazon.com/ebs/pricing/):
- Standard snapshot: $0.05/GB/month (us-east-1) — **matches current code**
- Archive tier: $0.0125/GB/month + retrieval costs
- Cross-region copy: Data transfer charges apply ($0.01-0.02/GB varies by route)

Per [AWS DLM Documentation - Amazon Data Lifecycle Manager tags](https://docs.aws.amazon.com/ebs/latest/userguide/dlm-elements.html):

**EXACT system tags DLM applies to ALL snapshots it creates:**
- `aws:dlm:lifecycle-policy-id` — policy ID that created snapshot
- `aws:dlm:lifecycle-schedule-name` — schedule name
- `aws:dlm:expirationTime` — for age-based schedules (when to delete)
- `dlm:managed` — marks as DLM-managed
- `aws:dlm:archived` — for archived snapshots
- `aws:dlm:pre-script` — for snapshots with pre scripts
- `aws:dlm:post-script` — for snapshots with post scripts

**Current code at `snapshots.py:20-24` only checks:**
```python
_MANAGED_TAG_KEYS = frozenset({
    "aws:backup:source-resource-arn",
    "dlm:managed",  # ← Has this
    "aws:backup:recovery-point-arn",
})
# MISSING: aws:dlm:lifecycle-policy-id (the PRIMARY tag)
```

Per [AWS Backup managed resources](https://docs.aws.amazon.com/aws-backup/latest/devguide/tags-on-backups.html):
- AWS Backup copies source resource tags to recovery points
- The `aws:backup:source-resource-arn` tag is correctly detected

### Gap Assessment: **IMPORTANT**

DLM detection is incomplete. The code checks `dlm:managed` but MISSES `aws:dlm:lifecycle-policy-id` which is the PRIMARY tag DLM applies to every snapshot.

### Specific Fix Required
Add `aws:dlm:lifecycle-policy-id` to `_MANAGED_TAG_KEYS` in `scanners/snapshots.py:20-24`.

**Source:** [How Amazon Data Lifecycle Manager works](https://docs.aws.amazon.com/ebs/latest/userguide/dlm-elements.html) - Section "Amazon Data Lifecycle Manager tags"

---

## RESEARCH TOPIC 5: S3 Cost Analysis Accuracy

### Current Code Behavior
**File:** `scanners/s3.py:147-176`

- Uses CloudWatch `BucketSizeBytes` metric with 3-day window
- Period=86400 (1 day), Statistics=["Average"]
- Hardcoded `$0.023/GB/month` for S3 Standard

### Research Findings
Per [S3 CloudWatch metrics](https://docs.aws.amazon.com/AmazonS3/latest/userguide/cloudwatch-monitoring.html):
- BucketSizeBytes updates **once per day at midnight UTC**
- 3-day window is appropriate to handle delays
- Data may be up to 24-48 hours stale

Per [S3 Storage Lens vs CloudWatch](https://repost.aws/knowledge-center/s3-console-metric-discrepancy):
- Storage Lens is also daily, not real-time
- CloudWatch uses base-10 conversion (/1000), Storage Lens uses base-2 (/1024)
- For cost audit purposes, CloudWatch is sufficient

Per [S3 Intelligent Tiering costs](https://www.impossiblecloud.com/en-us/magazine/aws-s3-standard-vs-intelligent-tiering-cost):
- Monitoring fee: $0.0025 per 1,000 objects
- Transition fee: $0.01 per 1,000 objects
- Objects <128KB stay in Frequent tier (no savings)
- Recommend IT only for buckets with large average object size

### Gap Assessment: **MINOR**

Current implementation is accurate. CloudWatch delay is documented and acceptable.

### Specific Fix Required
Consider documenting that S3 metrics may be up to 48 hours stale. No code change needed.

**Source:** [Monitoring metrics with CloudWatch](https://docs.aws.amazon.com/AmazonS3/latest/userguide/cloudwatch-monitoring.html)

---

## RESEARCH TOPIC 6: Reserved Instances and Savings Plans Detection

### Current Code Behavior
**File:** `scanners/reservations.py:60-84`

- Uses `describe_reserved_instances()` with `state=active` filter
- Aggregates RI count by instance_type across all regions
- Does NOT check Savings Plans coverage

### Research Findings
Per [Regional vs Zonal RIs](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/reserved-instances-scope.html):
- Zonal RIs: Specific AZ, no size flexibility
- Regional RIs: Any AZ in region, size flexibility within family
- Current code aggregates both correctly

Per [Savings Plans APIs](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ce/client/get_savings_plans_coverage.html):
- `GetSavingsPlansCoverage` — shows what percentage is covered by SPs
- `GetSavingsPlansUtilization` — shows SP usage efficiency
- Savings Plans are often MORE impactful than RIs for modern workloads

### Gap Assessment: **CRITICAL**

**Savings Plans are not checked at all.** Many AWS accounts use Savings Plans instead of RIs. This is a significant gap for accurate coverage recommendations.

### Specific Fix Required
Add Savings Plans coverage check using `ce.get_savings_plans_coverage()` API. Integrate with RI scanner or create separate scanner.

**Source:** [GetSavingsPlansCoverage](https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_GetSavingsPlansCoverage.html)

---

## RESEARCH TOPIC 7: Competitive Analysis (Compute Optimizer, Trusted Advisor)

### Current Code Behavior
No integration with AWS Compute Optimizer or Trusted Advisor.

### Research Findings

**AWS Compute Optimizer** ([docs](https://aws.amazon.com/compute-optimizer/)):
- Provides ML-based rightsizing recommendations for EC2, Lambda, EBS, ECS
- API: `compute-optimizer.get_ec2_instance_recommendations()`
- Requires opt-in and 14+ days of CloudWatch data
- More accurate than simple CPU threshold detection
- IAM: `compute-optimizer:GetEC2InstanceRecommendations`

**AWS Trusted Advisor** ([docs](https://docs.aws.amazon.com/awssupport/latest/user/cost-optimization-checks.html)):
- Cost optimization checks: idle EC2, RIs, EBS volumes, etc.
- **Requires Business/Enterprise Support plan**
- API transitioning from Support API to new Trusted Advisor API
- Old API: `support.describe_trusted_advisor_checks()` (deprecated 2024)
- New API: `trustedadvisor.list_recommendations()`

### Gap Assessment: **IMPORTANT**

Compute Optimizer provides higher-quality rightsizing recommendations than CPU threshold analysis. Trusted Advisor provides checks we may be duplicating.

### Specific Fix Required
1. Add optional `scanners/compute_optimizer.py` for rightsizing recommendations
2. Add optional `scanners/trusted_advisor.py` with graceful skip if no Business Support
3. Add IAM permissions: `compute-optimizer:Get*`, `trustedadvisor:List*`

**Source:** [Compute Optimizer boto3](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/compute-optimizer.html)

---

## RESEARCH TOPIC 8: WeasyPrint PDF Quality

### Current Code Behavior
**File:** `reports/pdf.py`, `reports/templates/report.html`

- Uses WeasyPrint with HTML string input
- CSS has `@page { size: Letter; margin: 0.65in 0.6in; }`
- No explicit page-break control for table rows
- System fonts (Helvetica, Arial, sans-serif)

### Research Findings
Per [WeasyPrint tips and tricks](https://www.naveenmk.me/blog/weasyprint/):
- Use `break-inside: avoid;` on table rows to prevent splitting
- Use `thead { display: table-header-group; }` for header repetition
- WeasyPrint embeds and subsets fonts automatically

Per [WeasyPrint font handling](https://github.com/Kozea/WeasyPrint/issues/1318):
- WeasyPrint embeds fonts by default (subset for file size)
- Custom fonts need accessible paths or @font-face URLs
- System fonts work for offline rendering if available on host

### Gap Assessment: **MINOR**

Current PDF generation works. Table rows may split across pages which looks unprofessional.

### Specific Fix Required
Add CSS: `tr { break-inside: avoid; }` and `thead { display: table-header-group; }` for better table rendering.

**Source:** [WeasyPrint page breaks](https://www.naveenmk.me/blog/weasyprint/)

---

# PRIORITIZED FIX LIST (Ordered by Client Impact)

| Priority | Fix | Why Critical | Verified Source |
|----------|-----|--------------|-----------------|
| 1 | **Add Savings Plans coverage check** | Missing coverage for dominant AWS commitment model. Code at `reservations.py` only checks RIs, never calls Savings Plans API. | [GetSavingsPlansCoverage API](https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_GetSavingsPlansCoverage.html) |
| 2 | **Expand DLM managed tag detection** | Code at `snapshots.py:20-24` checks `dlm:managed` but misses `aws:dlm:lifecycle-policy-id` — the PRIMARY tag per AWS docs. | [DLM elements docs](https://docs.aws.amazon.com/ebs/latest/userguide/dlm-elements.html) |
| 3 | **Add Compute Optimizer integration (optional)** | ML-based rightsizing is more accurate than CPU threshold; requires 14d of CloudWatch data | [Compute Optimizer API](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/compute-optimizer.html) |
| 4 | **Add Trusted Advisor integration (optional)** | Leverage AWS native cost checks; requires Business/Enterprise Support plan | [Trusted Advisor API](https://docs.aws.amazon.com/awssupport/latest/user/get-started-with-aws-trusted-advisor-api.html) |
| 5 | **Fix PDF table row breaks** | Professional report appearance; table rows may split across pages | [WeasyPrint CSS best practices](https://www.naveenmk.me/blog/weasyprint/) |
| 6 | **Document Cost Anomaly Detection prereq** | `get_anomalies()` returns empty if no monitor configured (not an error) | [GetAnomalies docs](https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_GetAnomalies.html) |

**REMOVED from original list:**
- ~~Add marketoption filter to EC2 pricing~~ — Could not verify this filter exists in AWS Pricing API. Current filters are adequate.

---

# MISSING FEATURES FOUND IN RESEARCH

| Feature | What Competitors Do | Difficulty | Recommendation |
|---------|---------------------|------------|----------------|
| **Savings Plans coverage** | CloudHealth, Spot.io check SP utilization | Medium | **Implement** |
| **Compute Optimizer integration** | CloudHealth uses native AWS recommendations | Medium | **Implement** |
| **Trusted Advisor integration** | Native AWS checks, avoids duplication | Easy | **Implement (optional)** |
| **Lambda cost optimization** | Spot.io, Compute Optimizer check Lambda | Medium | Roadmap v2 |
| **Kubernetes/ECS costs** | CloudHealth, Spot.io | Hard | Roadmap v2 |
| **Real-time spot pricing** | Spot.io specializes here | Hard | Out of scope |
| **Multi-cloud support** | CloudHealth supports Azure/GCP | Hard | Out of scope |
| **FinOps showback/chargeback** | CloudHealth enterprise feature | Hard | Out of scope |
| **Terraform/IaC cost preview** | Infracost specializes here | Hard | Out of scope |

---

# SUMMARY

## Verified Critical Gaps
1. **No Savings Plans coverage check** — Code at `reservations.py` only calls `describe_reserved_instances()`, never uses `GetSavingsPlansCoverage`. Many AWS accounts now use Savings Plans over RIs.

## Verified Important Gaps
2. **Incomplete DLM tag detection** — Code at `snapshots.py:20-24` checks `dlm:managed` but misses `aws:dlm:lifecycle-policy-id` which AWS docs confirm is applied to ALL DLM-created snapshots.
3. **No Compute Optimizer integration** — Optional but provides ML-based rightsizing vs simple CPU threshold.
4. **No Trusted Advisor integration** — Optional, requires Business Support plan.

## Verified Minor Gaps
5. PDF table rows may split across pages (no `break-inside: avoid`)
6. Cost Anomaly Detection requires pre-configuration (should be documented)

## NOT Gaps (Corrected)
- ~~EC2 pricing filters~~ — Current filters are correct per AWS docs
- ~~CloudWatch GetMetricStatistics~~ — Not deprecated, still valid

---

## NEXT STEPS (Phase 3 — Implementation)

**Waiting for approval before implementing:**

1. Add `scanners/savings_plans.py` with `GetSavingsPlansCoverage` API
2. Add `aws:dlm:lifecycle-policy-id` to `_MANAGED_TAG_KEYS` in `snapshots.py:20-24`
3. Add `scanners/compute_optimizer.py` with `get_ec2_instance_recommendations()` (optional)
4. Add `scanners/trusted_advisor.py` with graceful skip for non-Business accounts (optional)
5. Add CSS `break-inside: avoid` for table rows in `report.html`
6. Update `iam_policy.json` with new permissions: `ce:GetSavingsPlansCoverage`
7. Add tests for each change
8. Run full validation suite

**Estimated scope:** 200-400 lines of new code
