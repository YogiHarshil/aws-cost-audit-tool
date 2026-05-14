# Tasks: AWS Cost Audit Tool

**Input**: Design documents from `/specs/001-aws-cost-audit/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Test tasks included per constitution requirement (>80% coverage target)

**Organization**: Tasks organized by build phases as specified in CLAUDE.md

## Format: `[ID] [P?] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- Include exact file paths in descriptions

## Path Conventions

Single Python project structure at repository root:
- Source: `scanners/`, `ai/`, `reports/`, `models/`, `utils/`
- Tests: `tests/`
- Config: `.env`, `config.py`, `main.py`

---

## Phase 1: Setup (Project Initialization + Data Models)

**Purpose**: Basic project structure, dependencies, and core data models

**Goal**: Establish Python environment and define Finding/Report dataclasses

- [X] T001 Create .gitignore for Python project (add .env, output/, venv/, __pycache__, *.pyc)
- [X] T002 [P] Create directory structure per plan.md (scanners/, ai/, reports/, models/, utils/, tests/, sample/, output/)
- [X] T003 [P] Create requirements.txt with dependencies (boto3, openai, jinja2, weasyprint, python-dotenv, matplotlib, pytest)
- [X] T004 [P] Create .env.example with template configuration (AWS_PROFILE, AWS_ROLE_ARN, OPENAI_API_KEY, CLIENT_NAME, EXCLUDE_TAGS)
- [X] T005 [P] Create iam_policy.json from contracts/iam-policy.json
- [X] T006 [P] Create README.md based on quickstart.md content
- [X] T007 Create models/__init__.py (empty module initializer)
- [X] T008 [P] Implement Finding dataclass in models/finding.py per data-model.md
- [X] T009 [P] Implement Report dataclass in models/report.py per data-model.md
- [X] T010 [P] Implement ScanConfig dataclass in models/report.py per data-model.md
- [X] T011 [P] Create tests/__init__.py and tests/fixtures/ directory
- [X] T012 Write unit tests for Finding validation in tests/test_models.py (severity, savings >= 0, resource_type)
- [X] T013 Write unit tests for Report validation in tests/test_models.py (regions_scanned not empty, total_savings auto-computed)
- [X] T014 Write unit tests for ScanConfig validation in tests/test_models.py (OpenAI key required if not skip_ai)

**Checkpoint**: Run `pytest tests/test_models.py` - all tests should pass

---

## Phase 2: Foundational (AWS Client + Pricing + Config)

**Purpose**: Core infrastructure for AWS API calls, pricing queries, and configuration loading

**⚠️ CRITICAL**: These components are blocking prerequisites for all scanners

- [X] T015 Create utils/__init__.py (empty module initializer)
- [X] T016 Implement AWS client factory in utils/aws_client.py (create_client with AssumeRole support, region discovery, adaptive retry config)
- [X] T017 Implement region name mapping in utils/pricing.py (REGION_NAME_MAPPING dict per research.md)
- [X] T018 Implement PricingCache class in utils/pricing.py (thread-safe session-level cache)
- [X] T019 Implement get_ec2_instance_price in utils/pricing.py (query Pricing API with filters, parse nested JSON)
- [X] T020 [P] Implement get_rds_instance_price in utils/pricing.py (similar pattern to EC2)
- [X] T021 [P] Implement get_ebs_volume_price in utils/pricing.py (per GB-month pricing)
- [X] T022 [P] Implement batch_get_prices utility in utils/pricing.py (ThreadPoolExecutor for parallel pricing queries)
- [X] T023 Implement config.py (Config class with from_env_and_args classmethod, merge .env and CLI args)
- [X] T024 Implement parse_exclude_tags helper in config.py (parse "Key=Value,Key2=Value2" format)
- [X] T025 [P] Write unit tests for AWS client factory in tests/test_utils.py (mock boto3, verify AssumeRole calls)
- [X] T026 [P] Write unit tests for pricing queries in tests/test_utils.py (mock Pricing API responses, verify cache hits)
- [X] T027 [P] Write unit tests for config loading in tests/test_config.py (test precedence: CLI > env > defaults)

**Checkpoint**: Run `pytest tests/test_utils.py tests/test_config.py` - all tests should pass

---

## Phase 3: AWS Scanners (EC2, RDS, EBS, EIP, S3, Cost Explorer)

**Purpose**: Implement resource scanners for all 6 AWS services

**Goal**: Each scanner finds wasteful resources and creates Finding objects

### EC2 Scanner

- [X] T028 Create scanners/__init__.py (empty module initializer)
- [X] T029 Implement BaseScanner class in scanners/base.py (common error handling, tag filtering, pagination)
- [X] T030 Implement EC2Scanner in scanners/ec2.py (inherit from BaseScanner)
- [X] T031 Implement _scan_stopped_instances in scanners/ec2.py (filter stopped >7 days, calculate savings)
- [X] T032 Implement _scan_low_utilization_instances in scanners/ec2.py (CloudWatch CPUUtilization query, <5% threshold, handle missing metrics)
- [X] T033 Write unit tests for EC2Scanner in tests/test_scanners.py (mock boto3 EC2 and CloudWatch responses)

### RDS Scanner

- [X] T034 [P] Implement RDSScanner in scanners/rds.py (inherit from BaseScanner)
- [X] T035 [P] Implement _scan_zero_connections in scanners/rds.py (CloudWatch DatabaseConnections metric, 14-day lookback)
- [X] T036 [P] Implement _scan_stopped_instances in scanners/rds.py (filter stopped RDS instances)
- [X] T037 [P] Write unit tests for RDSScanner in tests/test_scanners.py (mock RDS and CloudWatch)

### EBS Scanner

- [X] T038 [P] Implement EBSScanner in scanners/ebs.py (inherit from BaseScanner)
- [X] T039 [P] Implement _scan_unattached_volumes in scanners/ebs.py (filter State=available, calculate per-GB-month savings)
- [X] T040 [P] Write unit tests for EBSScanner in tests/test_scanners.py (mock EC2 DescribeVolumes)

### EIP Scanner

- [X] T041 [P] Implement EIPScanner in scanners/eip.py (inherit from BaseScanner)
- [X] T042 [P] Implement _scan_unassociated_ips in scanners/eip.py (filter AssociationId=null, $3.60/month savings)
- [X] T043 [P] Write unit tests for EIPScanner in tests/test_scanners.py (mock EC2 DescribeAddresses)

### S3 Scanner

- [X] T044 [P] Implement S3Scanner in scanners/s3.py (inherit from BaseScanner)
- [X] T045 [P] Implement _scan_missing_lifecycle in scanners/s3.py (check GetLifecycleConfiguration)
- [X] T046 [P] Implement _scan_large_buckets_no_tiering in scanners/s3.py (CloudWatch BucketSizeBytes >100GB, check Intelligent-Tiering)
- [X] T047 [P] Write unit tests for S3Scanner in tests/test_scanners.py (mock S3 and CloudWatch)

### Cost Explorer Scanner

- [X] T048 [P] Implement CostExplorerScanner in scanners/cost_explorer.py (NOT inherit from BaseScanner - different pattern)
- [X] T049 [P] Implement get_90_day_spend in scanners/cost_explorer.py (GetCostAndUsage grouped by SERVICE)
- [X] T050 [P] Implement get_month_over_month_trend in scanners/cost_explorer.py (compare current MTD vs previous month, flag >20% increase)
- [X] T051 [P] Write unit tests for CostExplorerScanner in tests/test_scanners.py (mock Cost Explorer API)

**Checkpoint**: Run `pytest tests/test_scanners.py` - all scanner tests should pass

---

## Phase 4: AI Integration (Summarizer + Recommender)

**Purpose**: Generate AI-powered summaries and recommendations using OpenAI GPT-4o-mini

**Goal**: Executive summary, per-finding explanations, top 5 recommendations

- [X] T052 Create ai/__init__.py (empty module initializer)
- [X] T053 Implement prompt templates in ai/prompts.py (EXECUTIVE_SUMMARY_PROMPT, FINDING_EXPLANATION_PROMPT, RECOMMENDATIONS_PROMPT)
- [X] T054 Implement Summarizer class in ai/summarizer.py (generate_executive_summary method)
- [X] T055 Implement error handling in ai/summarizer.py (catch OpenAI API failures, return "AI summary unavailable" on error)
- [X] T056 [P] Implement Recommender class in ai/recommender.py (generate_top_5_recommendations method)
- [X] T057 [P] Implement per-finding explanation in ai/summarizer.py (generate_finding_explanation method for individual findings)
- [X] T058 [P] Write unit tests for AI modules in tests/test_ai.py (mock OpenAI API responses, verify prompt structure)
- [X] T059 [P] Write unit tests for AI error handling in tests/test_ai.py (simulate API failures, verify graceful degradation)

**Checkpoint**: Run `pytest tests/test_ai.py` - all AI tests should pass

---

## Phase 5: Report Generation (HTML Template + PDF)

**Purpose**: Generate professional PDF audit reports from findings

**Goal**: Jinja2 HTML template rendered to PDF with WeasyPrint

- [X] T060 Create reports/__init__.py (empty module initializer)
- [X] T061 Create reports/templates/ directory
- [X] T062 Implement HTML report template in reports/templates/report.html (cover page, executive summary, findings table, recommendations per research.md)
- [X] T063 Implement CSS styling in report.html (professional corporate styling: blues/grays, @page rules, alternating row colors, severity badges)
- [X] T064 Implement generate_cost_chart in reports/generator.py (matplotlib line chart, save as base64-encoded PNG)
- [X] T065 Implement render_html in reports/generator.py (Jinja2 rendering with findings, cost chart, AI summaries)
- [X] T066 Implement generate_pdf in reports/pdf.py (WeasyPrint HTML to PDF conversion)
- [X] T067 [P] Write unit tests for report generator in tests/test_reports.py (test HTML rendering with sample data)
- [X] T068 [P] Write unit tests for PDF generation in tests/test_reports.py (verify PDF output file exists and is valid)

**Checkpoint**: Run `pytest tests/test_reports.py` - all report tests should pass

---

## Phase 6: CLI + End-to-End Integration

**Purpose**: Command-line interface and orchestration of all components

**Goal**: Complete audit workflow from CLI invocation to PDF output

- [X] T069 Implement CLI argument parsing in main.py (argparse with --profile, --region, --client-name, --skip-ai, --output, --exclude-tags, --verbose)
- [X] T070 Implement logging setup in main.py (configure logging based on --verbose flag and LOG_LEVEL env var)
- [X] T071 Implement main orchestration flow in main.py (load config, validate credentials, discover regions, run scanners in parallel)
- [X] T072 Implement parallel scanner execution in main.py (ThreadPoolExecutor with up to 10 workers, aggregate findings)
- [X] T073 Implement AI summary generation in main.py (call summarizer and recommender if not --skip-ai)
- [X] T074 Implement report generation and PDF output in main.py (call report generator, save to output/ directory)
- [X] T075 Implement progress indicators in main.py (print scan progress: "[1/6] Scanning EC2 instances...")
- [X] T076 Implement error handling and exit codes in main.py (exit 0 on success, 1 on critical error, 2 on partial results)
- [X] T077 Implement summary output in main.py (print report path, total savings, breakdown by severity, scan duration)
- [X] T078 Write end-to-end tests in tests/test_e2e.py (mock all AWS and OpenAI calls, verify complete workflow)
- [X] T079 Write CLI argument tests in tests/test_e2e.py (test argument parsing, config precedence, exit codes)

**Checkpoint**: Run `pytest tests/test_e2e.py` - end-to-end tests should pass

---

## Phase 7: Sample Report Generator

**Purpose**: Generate demo report with mock data for sales/testing

**Goal**: Standalone script to create sample PDF without AWS credentials

- [ ] T080 Create sample/ directory
- [ ] T081 Implement mock data generation in sample/generate_sample.py (create realistic Finding and Report objects)
- [ ] T082 Implement sample report generation in sample/generate_sample.py (call report generator with mock data, output to output/sample_report_demo_YYYY-MM-DD.pdf)
- [ ] T083 Test sample report generation (run `python sample/generate_sample.py`, verify PDF created)

**Checkpoint**: Run `python sample/generate_sample.py` - demo PDF should be created successfully

---

## Phase 8: Polish & Documentation

**Purpose**: Final touches, documentation, and integration testing

**Goal**: Production-ready tool with complete documentation

- [ ] T084 Create comprehensive README.md (installation, quickstart, usage examples, troubleshooting based on quickstart.md)
- [ ] T085 [P] Create CONTRIBUTING.md (contribution guidelines, code style, test requirements)
- [ ] T086 [P] Add docstrings to all public functions (Google-style docstrings per constitution)
- [ ] T087 [P] Add type hints to remaining functions (ensure all functions have complete type hints)
- [ ] T088 Run pytest with coverage (pytest --cov=. --cov-report=html, verify >80% coverage)
- [ ] T089 Run full integration test against sandbox AWS account (optional, requires real AWS credentials)
- [ ] T090 Create CHANGELOG.md (document v1.0.0 initial release)

**Checkpoint**: All tests pass, coverage >80%, documentation complete

---

## Dependencies

### Phase Dependencies (Sequential)
1. **Phase 1** (Setup) → **Phase 2** (Foundational) → All other phases can proceed
2. **Phases 3, 4, 5** can be worked on in parallel after Phase 2 completes
3. **Phase 6** (CLI) depends on Phases 3, 4, 5 being complete
4. **Phase 7** (Sample) depends on Phase 5 (Reports) being complete
5. **Phase 8** (Polish) should be done last

### Task Dependencies Within Phases
- **Phase 1**: T008-T010 (data models) can run in parallel; T012-T014 (tests) depend on models
- **Phase 2**: T019-T022 (pricing functions) can run in parallel after T017-T018 (cache and mapping)
- **Phase 3**: All scanner implementations (T030-T051) can run in parallel after T029 (BaseScanner)
- **Phase 4**: T054-T057 (AI implementation) can run in parallel
- **Phase 5**: T062-T063 (template) must complete before T064-T066 (generation)
- **Phase 6**: T069-T077 must be sequential (orchestration flow)
- **Phase 8**: T086-T087 (docstrings/type hints) can run in parallel

---

## Parallel Execution Opportunities

### High Parallelism (Can Work Simultaneously)
- **Phase 1**: T002-T006 (file creation)
- **Phase 2**: T019-T022 (pricing functions), T025-T027 (tests)
- **Phase 3**: T030-T051 (all 6 scanners)
- **Phase 4**: T054-T057 (AI components), T058-T059 (AI tests)
- **Phase 5**: T067-T068 (report tests)
- **Phase 8**: T085-T087 (documentation)

### Medium Parallelism (Some Dependencies)
- **Phase 1**: T008-T010 (data models) after T007
- **Phase 2**: T016 must complete before T015 can use it
- **Phase 6**: T073-T077 depend on T069-T072

### Sequential (Must Complete in Order)
- **Phase 1**: T001 → T002 → models → tests
- **Phase 2**: config.py depends on having models defined
- **Phase 6**: main.py orchestration tasks (T069-T077)

---

## MVP Scope Recommendation

**Minimum Viable Product**: Phases 1-6 (Exclude Phase 7 sample report)

**Essential for First Client Audit**:
- ✅ Phase 1: Data models
- ✅ Phase 2: AWS client + pricing
- ✅ Phase 3: All 6 scanners
- ✅ Phase 4: AI integration
- ✅ Phase 5: PDF reports
- ✅ Phase 6: CLI interface

**Can Defer to V1.1**:
- ⏸️ Phase 7: Sample report generator (nice-to-have for demos)
- ⏸️ Phase 8: Some polish items (can iterate)

**Time Estimate**: Phases 1-6 = MVP ready for first client audit

---

## Implementation Strategy

1. **Week 1**: Phases 1-2 (Foundation)
   - Complete project setup
   - Implement data models and core utilities
   - Ensure all foundational tests pass

2. **Week 2**: Phase 3 (Scanners)
   - Implement all 6 AWS scanners
   - Test each scanner independently
   - Verify pricing calculations

3. **Week 3**: Phases 4-5 (AI + Reports)
   - Integrate OpenAI API
   - Build PDF report generation
   - Test end-to-end report output

4. **Week 4**: Phase 6 (CLI + Integration)
   - Build CLI interface
   - Integrate all components
   - End-to-end testing

5. **Polish**: Phase 7-8 (Optional)
   - Generate sample reports
   - Complete documentation
   - Achieve >80% test coverage

---

## Success Criteria

- [ ] All pytest tests pass (>80% code coverage)
- [ ] CLI runs successfully: `python main.py --help`
- [ ] Complete audit scan runs in <30 minutes
- [ ] PDF output is professional and client-ready
- [ ] No credentials committed to repository
- [ ] All functions have type hints and docstrings
- [ ] Constitution non-negotiables verified (security, reliability, accuracy, code quality, testability)

---

## Next Steps

1. Review this task breakdown for completeness
2. Begin Phase 1: Create virtual environment, install dependencies
3. Implement data models with tests (T001-T014)
4. Proceed phase-by-phase, running tests after each phase
5. Use `/speckit-implement` to begin execution

**Ready to implement!** 🚀
