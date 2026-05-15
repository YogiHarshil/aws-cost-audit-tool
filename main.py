"""AWS Cost Audit Tool — CLI entrypoint."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Type

from botocore.exceptions import ClientError, ProfileNotFound

from ai.recommender import Recommender
from ai.summarizer import Summarizer
from config import Config, ConfigError
from models.finding import Finding
from models.report import Report, ScanConfig
from reports.generator import render_html
from reports.pdf import generate_pdf
from scanners.base import BaseScanner
from scanners.cost_explorer import CostExplorerScanner
from scanners.ebs import EBSScanner
from scanners.ec2 import EC2Scanner
from scanners.eip import EIPScanner
from scanners.rds import RDSScanner
from scanners.reservations import ReservationScanner
from scanners.s3 import S3Scanner
from scanners.snapshots import SnapshotScanner
from utils.aws_client import create_client, create_session, discover_regions
from utils.pricing import PricingCache

logger = logging.getLogger(__name__)

_EXIT_SUCCESS = 0
_EXIT_CRITICAL = 1
_EXIT_SCANNER_PARTIAL = 2  # one or more Cost Explorer / regional scan steps failed
_EXIT_AI_PARTIAL = 3  # scans completed; AI step failed (see printed notes)

_SCANNER_CLASSES: Sequence[Type[BaseScanner]] = (
    EC2Scanner,
    RDSScanner,
    EBSScanner,
    EIPScanner,
    S3Scanner,
    SnapshotScanner,
)

_SCANNER_LABELS = (
    "EC2 instances",
    "RDS instances",
    "EBS volumes",
    "Elastic IPs",
    "S3 buckets",
    "EBS snapshots",
)

# Severity ranking for deduplication (higher number = higher priority)
_SEVERITY_RANK = {"High": 3, "Medium": 2, "Low": 1}


def deduplicate_findings(findings: List[Finding]) -> List[Finding]:
    """Remove duplicate findings for same resource_id.

    When same resource appears in multiple scanners (e.g., stopped EC2 with large EBS),
    keep highest severity finding and combine savings estimates.
    """
    if not findings:
        return findings

    by_resource: Dict[str, List[Finding]] = defaultdict(list)
    for f in findings:
        by_resource[f.resource_id].append(f)

    deduped: List[Finding] = []
    for resource_id, resource_findings in by_resource.items():
        if len(resource_findings) == 1:
            deduped.append(resource_findings[0])
            continue

        # Multiple findings for same resource - keep highest severity
        resource_findings.sort(
            key=lambda x: _SEVERITY_RANK.get(x.severity, 0), reverse=True
        )
        primary = resource_findings[0]

        # Combine savings from all findings (don't double-count identical savings)
        unique_savings = {primary.monthly_savings}
        for other in resource_findings[1:]:
            if other.monthly_savings not in unique_savings:
                unique_savings.add(other.monthly_savings)

        # Create combined finding if there are additional savings
        combined_savings = sum(unique_savings)
        if combined_savings != primary.monthly_savings:
            # Update details with combined info
            combined_details = dict(primary.details)
            combined_details["combined_from_findings"] = len(resource_findings)
            combined_details["original_savings"] = primary.monthly_savings
            combined_details["total_combined_savings"] = combined_savings

            deduped.append(
                Finding(
                    resource_id=primary.resource_id,
                    resource_type=primary.resource_type,
                    region=primary.region,
                    issue_type=primary.issue_type,
                    description=primary.description,
                    monthly_savings=combined_savings,
                    severity=primary.severity,
                    details=combined_details,
                    ai_explanation=primary.ai_explanation,
                    discovered_at=primary.discovered_at,
                )
            )
        else:
            deduped.append(primary)

    return deduped


def export_findings_json(report: Report, output_path: Path) -> Path:
    """Export findings to JSON for client integration (Jira, Notion, etc.)."""
    export_data = {
        "meta": {
            "account_id": report.account_id,
            "account_alias": report.account_alias,
            "client_name": report.client_name,
            "scan_date": report.scan_date.isoformat(),
            "regions_scanned": report.regions_scanned,
            "total_savings_monthly": report.total_savings,
            "total_savings_annual": report.total_savings * 12,
            "findings_count": report.findings_count,
            "findings_by_severity": report.findings_by_severity,
            "findings_by_type": report.findings_by_type,
        },
        "findings": [],
        "cost_trends": report.cost_trends,
    }

    for f in report.findings:
        finding_dict = {
            "resource_id": f.resource_id,
            "resource_type": f.resource_type,
            "region": f.region,
            "issue_type": f.issue_type,
            "description": f.description,
            "monthly_savings": f.monthly_savings,
            "annual_savings": f.monthly_savings * 12,
            "severity": f.severity,
            "details": f.details,
            "ai_explanation": f.ai_explanation,
            "discovered_at": f.discovered_at.isoformat(),
        }
        export_data["findings"].append(finding_dict)

    with open(output_path, "w", encoding="utf-8") as fp:
        json.dump(export_data, fp, indent=2, default=str)

    return output_path


def build_parser() -> argparse.ArgumentParser:
    """Build and configure the CLI argument parser.

    Returns:
        Configured ArgumentParser with all supported options for the audit tool,
        including AWS profile, region, role ARN, client name, AI toggle, output
        directory, tag exclusion, and verbosity flags.
    """
    p = argparse.ArgumentParser(
        description="Scan AWS accounts for cost waste and emit a PDF audit report.",
    )
    p.add_argument("--profile", help="AWS CLI profile name (default: default or AWS_PROFILE)")
    p.add_argument(
        "--region",
        help="Comma-separated regions to scan (default: all enabled regions)",
    )
    p.add_argument("--role-arn", dest="role_arn", help="Optional IAM role ARN to assume (STS)")
    p.add_argument("--client-name", dest="client_name", help="Name on the report cover")
    p.add_argument("--skip-ai", action="store_true", help="Disable OpenAI summaries and recommendations")
    p.add_argument("--output", "-o", dest="output", help="Output directory for the PDF (default: ./output)")
    p.add_argument(
        "--exclude-tags",
        dest="exclude_tags",
        help='Comma-separated Key=Value pairs to exclude tagged resources (e.g. Environment=Prod)',
    )
    p.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    return p


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments for the audit tool.

    Args:
        argv: List of argument strings to parse. If None, uses sys.argv[1:].

    Returns:
        Namespace containing all parsed arguments with their values.
    """
    return build_parser().parse_args(argv)


def setup_logging(level_name: str) -> None:
    """Configure root logging from a level name (e.g. INFO, DEBUG)."""
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Keep third-party libraries from flooding DEBUG (matplotlib font scan, PIL chunks, etc.).
    for noisy in ("matplotlib", "matplotlib.font_manager", "PIL", "fontTools", "weasyprint"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # AWS + HTTP clients log full requests (including auth-related headers) at DEBUG — unsafe on --verbose.
    for noisy in (
        "botocore",
        "boto3",
        "urllib3",
        "openai",
        "httpx",
        "httpcore",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _account_id_and_alias(session: Any) -> Tuple[str, str]:
    sts = session.client("sts", region_name="us-east-1")
    ident = sts.get_caller_identity()
    account_id = str(ident.get("Account", "unknown"))
    alias = account_id
    try:
        iam = session.client("iam", region_name="us-east-1")
        resp = iam.list_account_aliases()
        aliases = resp.get("AccountAliases") or []
        if aliases:
            alias = str(aliases[0])
    except ClientError as exc:
        logger.debug("list_account_aliases unavailable: %s", exc)
    return account_id, alias


def _run_scanner_in_region(
    session: Any,
    region: str,
    exclude_tags: List[Dict[str, str]],
    pricing_client: Any,
    cache: PricingCache,
    scanner_cls: Type[BaseScanner],
) -> Tuple[List[Finding], Optional[str]]:
    try:
        inst = scanner_cls(session, region, exclude_tags, pricing_client, cache)
        return inst.scan(), None
    except Exception as exc:
        logger.exception("%s failed in %s", scanner_cls.__name__, region)
        return [], f"{scanner_cls.__name__}:{region}:{exc}"


def run_regional_scanners_parallel(
    session: Any,
    regions: Sequence[str],
    exclude_tags: List[Dict[str, str]],
    pricing_client: Any,
    cache: PricingCache,
    scanner_cls: Type[BaseScanner],
    *,
    max_workers: int = 5,
) -> Tuple[List[Finding], List[str]]:
    """Run one scanner class across all regions (thread pool)."""
    findings: List[Finding] = []
    errors: List[str] = []
    if not regions:
        return findings, errors
    workers = min(max_workers, max(1, len(regions)))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _run_scanner_in_region,
                session,
                r,
                exclude_tags,
                pricing_client,
                cache,
                scanner_cls,
            ): r
            for r in regions
        }
        for fut in as_completed(futures):
            res, err = fut.result()
            findings.extend(res)
            if err:
                errors.append(err)
    return findings, errors


def cost_explorer_phase(session: Any) -> Tuple[List[Finding], Dict[str, Any], List[str]]:
    """Account-level Cost Explorer scan and trend payloads for the report."""
    errors: List[str] = []
    try:
        ce = CostExplorerScanner(session)
        findings = ce.scan()
        spend = ce.get_90_day_spend()
        trend = ce.get_month_over_month_trend()
    except Exception as exc:
        logger.exception("Cost Explorer phase failed")
        errors.append(str(exc))
        return [], {"spend_90d": {}, "month_over_month": {}}, errors

    # Service spend lives only under spend_90d (avoids duplicating the same groups list for AI/PDF payloads).
    trends: Dict[str, Any] = {
        "spend_90d": spend if isinstance(spend, dict) else {},
        "month_over_month": trend,
    }
    return findings, trends, errors


def apply_ai_to_report(report: Report, scan_cfg: ScanConfig) -> None:
    """Populate executive summary, recommendations, and per-finding explanations."""
    key = scan_cfg.openai_api_key or ""
    summarizer = Summarizer(
        key,
        model=scan_cfg.openai_model,
        base_url=scan_cfg.openai_base_url,
        extra_body=scan_cfg.openai_extra_body,
        default_headers=scan_cfg.openai_default_headers,
    )
    recommender = Recommender(
        key,
        model=scan_cfg.openai_model,
        base_url=scan_cfg.openai_base_url,
        extra_body=scan_cfg.openai_extra_body,
        default_headers=scan_cfg.openai_default_headers,
    )
    report.executive_summary = summarizer.generate_executive_summary(
        report.findings,
        report.cost_trends,
    )
    report.recommendations = recommender.generate_top_5_recommendations(report.findings)
    for f in report.findings:
        f.ai_explanation = summarizer.generate_finding_explanation(f)


def run_audit(cfg: Config) -> int:
    """Execute a full audit for merged configuration.

    Exit codes: ``0`` success, ``1`` critical failure, ``2`` scanner partial,
    ``3`` AI-only partial (all scanners succeeded).
    """
    partial_notes: List[str] = []
    t0 = time.perf_counter()

    try:
        session = create_session(cfg.aws_profile, cfg.aws_role_arn)
    except ProfileNotFound as exc:
        logger.error("AWS profile not found: %s", exc)
        print(
            "ERROR: That AWS profile does not exist in ~/.aws/credentials or ~/.aws/config.\n"
            f"  ({exc})\n"
            "  Fix AWS_PROFILE / --profile for this client, or add the profile (e.g. aws configure sso). "
            "The tool does not fall back to other credentials.",
            file=sys.stderr,
        )
        return _EXIT_CRITICAL
    except Exception as exc:
        logger.exception("Failed to create AWS session")
        print(f"ERROR: Could not create AWS session: {exc}", file=sys.stderr)
        return _EXIT_CRITICAL

    try:
        account_id, account_alias = _account_id_and_alias(session)
    except Exception as exc:
        logger.exception("Failed to resolve account identity")
        print(f"ERROR: Could not read account identity: {exc}", file=sys.stderr)
        return _EXIT_CRITICAL

    regions = list(cfg.regions) if cfg.regions else discover_regions(session)
    if not regions:
        print("ERROR: No regions to scan.", file=sys.stderr)
        return _EXIT_CRITICAL

    scan_cfg = cfg.to_scan_config()
    exclude_tags = list(scan_cfg.exclude_tags or [])
    pricing_client = create_client(session, "pricing")
    cache = PricingCache()

    all_findings: List[Finding] = []
    total_steps = 8
    region_count = len(regions)

    print(f"[1/{total_steps}] Scanning Cost Explorer (account-wide)...", flush=True)
    ce_findings, cost_trends, ce_errs = cost_explorer_phase(session)
    all_findings.extend(ce_findings)
    partial_notes.extend(ce_errs)
    if ce_findings:
        print(f"  Found {len(ce_findings)} cost trend findings", flush=True)

    for step_idx, (scanner_cls, label) in enumerate(zip(_SCANNER_CLASSES, _SCANNER_LABELS), start=2):
        print(f"[{step_idx}/{total_steps}] Scanning {label} across {region_count} regions...", flush=True)
        fnd, errs = run_regional_scanners_parallel(
            session,
            regions,
            exclude_tags,
            pricing_client,
            cache,
            scanner_cls,
            max_workers=scan_cfg.max_workers,
        )
        all_findings.extend(fnd)
        partial_notes.extend(errs)
        if fnd:
            # Summarize findings by region
            by_region: Dict[str, int] = defaultdict(int)
            for f in fnd:
                by_region[f.region] += 1
            region_summary = ", ".join(f"{r}:{c}" for r, c in sorted(by_region.items())[:5])
            if len(by_region) > 5:
                region_summary += f" (+{len(by_region) - 5} more regions)"
            print(f"  Found {len(fnd)} findings [{region_summary}]", flush=True)

    # Global RI coverage scan (runs once, checks all regions internally)
    print(f"[{total_steps}/{total_steps}] Scanning Reserved Instance coverage...", flush=True)
    try:
        ri_scanner = ReservationScanner(session, pricing_client, cache)
        ri_findings = ri_scanner.scan()
        all_findings.extend(ri_findings)
        if ri_findings:
            print(f"  Found {len(ri_findings)} RI opportunity findings", flush=True)
    except Exception as exc:
        logger.exception("RI coverage scan failed")
        partial_notes.append(f"reservations:{exc}")

    # Deduplicate findings (same resource from multiple scanners)
    pre_dedup_count = len(all_findings)
    all_findings = deduplicate_findings(all_findings)
    if pre_dedup_count != len(all_findings):
        print(f"  Deduplicated: {pre_dedup_count} -> {len(all_findings)} findings", flush=True)

    scan_elapsed = time.perf_counter() - t0
    scan_date = datetime.now(timezone.utc)

    report = Report(
        account_id=account_id,
        account_alias=account_alias,
        client_name=scan_cfg.client_name,
        scan_date=scan_date,
        regions_scanned=list(regions),
        findings=all_findings,
        total_savings=0.0,
        cost_trends=cost_trends,
        executive_summary=None,
        recommendations=None,
        scan_duration_seconds=scan_elapsed,
        scan_metadata={
            "partial_errors": partial_notes,
            "resources_scanned_estimate": len(all_findings),
        },
    )

    if not scan_cfg.skip_ai and scan_cfg.openai_api_key:
        print("Generating AI summaries...", flush=True)
        try:
            apply_ai_to_report(report, scan_cfg)
        except Exception as exc:
            logger.exception("AI generation failed")
            partial_notes.append(f"ai:{exc}")
            report.scan_metadata["partial_errors"] = partial_notes

    pdf_name = f"aws_audit_{account_id}_{scan_date.strftime('%Y-%m-%d')}.pdf"
    pdf_path = Path(scan_cfg.output_dir) / pdf_name

    # JSON export for client integration (Jira, Notion, etc.)
    json_name = f"{scan_cfg.client_name.replace(' ', '_')}_audit_{scan_date.strftime('%Y-%m-%d')}_findings.json"
    json_path = Path(scan_cfg.output_dir) / json_name

    try:
        html = render_html(report)
        generate_pdf(html, pdf_path)
    except Exception as exc:
        logger.exception("Report generation failed")
        print(f"ERROR: Failed to write PDF: {exc}", file=sys.stderr)
        return _EXIT_CRITICAL

    # Export JSON (non-fatal if fails)
    try:
        export_findings_json(report, json_path)
        print(f"Findings JSON: {json_path.resolve()}", flush=True)
    except Exception as exc:
        logger.warning("JSON export failed: %s", exc)
        partial_notes.append(f"json_export:{exc}")

    elapsed_total = time.perf_counter() - t0
    report.scan_duration_seconds = elapsed_total

    _print_summary(report, pdf_path, elapsed_total)

    if partial_notes:
        scanner_notes = [n for n in partial_notes if not str(n).startswith("ai:")]
        ai_notes = [n for n in partial_notes if str(n).startswith("ai:")]
        if scanner_notes:
            print("\nNote: One or more scan steps reported errors (exit code 2).", flush=True)
            for note in scanner_notes:
                print(f"  - {note}", flush=True)
            if ai_notes:
                print("  AI issues (also recorded):", flush=True)
                for note in ai_notes:
                    print(f"  - {note}", flush=True)
            return _EXIT_SCANNER_PARTIAL
        print("\nNote: AI generation had issues (exit code 3). Scan data is complete.", flush=True)
        for note in ai_notes:
            print(f"  - {note}", flush=True)
        return _EXIT_AI_PARTIAL
    return _EXIT_SUCCESS


def _print_summary(report: Report, pdf_path: Path, elapsed: float) -> None:
    by_sev = report.findings_by_severity
    annual_savings = report.total_savings * 12
    # Assume audit fee of $1,200 for ROI calculation
    audit_fee = 1200.0
    roi_pct = ((annual_savings - audit_fee) / audit_fee * 100) if audit_fee > 0 else 0
    payback_days = (audit_fee / (report.total_savings / 30)) if report.total_savings > 0 else float("inf")

    print("\n" + "=" * 50, flush=True)
    print("           AUDIT COMPLETE", flush=True)
    print("=" * 50, flush=True)
    print(f"Report PDF: {pdf_path.resolve()}", flush=True)
    print("", flush=True)
    print("EXECUTIVE METRICS:", flush=True)
    print(f"  Monthly savings:    ${report.total_savings:,.2f}", flush=True)
    print(f"  Annualized savings: ${annual_savings:,.2f}", flush=True)
    if report.total_savings > 0:
        print(f"  ROI (vs $1,200 fee): {roi_pct:,.0f}%", flush=True)
        print(f"  Payback period:     {payback_days:.0f} days", flush=True)
    print("", flush=True)
    print(
        f"Findings: {report.findings_count} "
        f"(High: {by_sev['High']}, Medium: {by_sev['Medium']}, Low: {by_sev['Low']})",
        flush=True,
    )
    print(f"Duration: {elapsed:.1f}s", flush=True)
    print("=" * 50, flush=True)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    try:
        cfg = Config.from_env_and_args(args)
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return _EXIT_CRITICAL

    setup_logging(cfg.log_level)
    return run_audit(cfg)


if __name__ == "__main__":
    raise SystemExit(main())
