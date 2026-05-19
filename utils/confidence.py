"""Confidence scoring for safe-to-delete findings.

Calculates a 0-100 confidence score for each Finding and assigns a
safe_to_delete label: SAFE (80-100), CAUTION (60-79), RISKY (0-59).

CloudTrail lookup is best-effort — any AccessDenied or quota error
causes the rule to be silently skipped so the scan is never blocked.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from botocore.exceptions import ClientError

from models.finding import Finding

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEV_PATTERNS = {"test", "dev", "temp", "staging", "demo", "poc", "old", "backup"}
_PROD_PATTERNS = {"prod", "production", "live", "critical", "main"}


def _get_name_tag(tags: Any) -> str:
    """Return the Name tag value (lower-cased) or '' if absent."""
    if not tags:
        return ""
    for t in tags:
        if isinstance(t, dict) and t.get("Key") == "Name":
            return str(t.get("Value", "")).lower()
    return ""


def _matches_any(name: str, patterns: set) -> Optional[str]:
    """Return the first matched pattern substring, or None."""
    for p in patterns:
        if p in name:
            return p
    return None


def _clamp(score: int) -> int:
    return max(0, min(100, score))


def _score_to_label(score: int) -> str:
    if score >= 80:
        return "SAFE"
    if score >= 60:
        return "CAUTION"
    return "RISKY"


# ---------------------------------------------------------------------------
# CloudTrail helper (optional — graceful on any error)
# ---------------------------------------------------------------------------

def _had_start_instance_event(
    session: Any,
    region: str,
    instance_id: str,
    days: int = 30,
) -> Optional[bool]:
    """Return True if StartInstances was called for the instance in the last `days` days.

    Returns None if CloudTrail data is unavailable (AccessDenied, quota, etc.).
    CloudTrail lookup_events API docs:
    https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/cloudtrail/client/lookup_events.html
    """
    try:
        ct = session.client("cloudtrail", region_name=region)
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        resp = ct.lookup_events(
            LookupAttributes=[{"AttributeKey": "EventName", "AttributeValue": "StartInstances"}],
            StartTime=start,
            EndTime=end,
            MaxResults=50,
        )
        for event in resp.get("Events", []):
            resources = event.get("Resources", [])
            for r in resources:
                if r.get("ResourceName") == instance_id:
                    return True
        # Handle pagination — but a single page of 50 is sufficient for this signal
        return False
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("AccessDeniedException", "AccessDenied"):
            logger.debug("CloudTrail LookupEvents denied for %s — skipping", instance_id)
        else:
            logger.debug("CloudTrail LookupEvents error for %s: %s", instance_id, exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.debug("CloudTrail lookup unexpected error for %s: %s", instance_id, exc)
        return None


# ---------------------------------------------------------------------------
# Per-resource-type scoring functions
# ---------------------------------------------------------------------------

def _score_ec2_stopped(finding: Finding, session: Any) -> Tuple[int, List[str]]:
    """Score a stopped EC2 instance finding."""
    score = 50
    reasons: List[str] = []
    details = finding.details or {}
    tags = details.get("tags") or []
    name = _get_name_tag(tags)

    days_stopped: float = details.get("days_stopped") or 0.0

    # Age bonuses
    if days_stopped > 60:
        score += 10
        reasons.append(f"Stopped {int(days_stopped)} days ago (>60d)")
    elif days_stopped > 30:
        score += 20
        reasons.append(f"Stopped {int(days_stopped)} days ago (>30d)")
    elif days_stopped < 14:
        score -= 10
        reasons.append(f"Stopped only {int(days_stopped)} days ago (<14d — recent)")

    # Name tag — dev/test patterns
    dev_match = _matches_any(name, _DEV_PATTERNS)
    if dev_match:
        score += 15
        reasons.append(f"Dev/test naming pattern ('{dev_match}' in name)")

    # Name tag — production patterns
    prod_match = _matches_any(name, _PROD_PATTERNS)
    if prod_match:
        score -= 20
        reasons.append(f"Production naming pattern ('{prod_match}' in name) — caution")

    # Elastic IP association (EIP stored in details by scanner if present)
    has_eip = details.get("has_elastic_ip", False)
    if has_eip:
        score -= 15
        reasons.append("Has active Elastic IP associated — may be referenced externally")

    # CloudTrail: was this instance started recently?
    ct_result = _had_start_instance_event(
        session, finding.region, finding.resource_id, days=30
    )
    if ct_result is True:
        score -= 15
        reasons.append("StartInstances event found in CloudTrail (last 30 days) — recently used")
    elif ct_result is False:
        score += 15
        reasons.append("No StartInstances event in CloudTrail (last 30 days)")
    # ct_result is None → CloudTrail unavailable, skip quietly

    return _clamp(score), reasons


def _score_ec2_idle(finding: Finding, session: Any) -> Tuple[int, List[str]]:
    """Score a running but idle EC2 instance (low CPU)."""
    score = 30  # Running = higher risk baseline
    reasons: List[str] = []
    details = finding.details or {}
    tags = details.get("tags") or []
    name = _get_name_tag(tags)

    avg_cpu: float = details.get("avg_cpu_14d") or 0.0

    if avg_cpu < 2.0:
        score += 20
        reasons.append(f"Avg CPU {avg_cpu:.1f}% over 14 days (<2% — extremely idle)")
    elif avg_cpu < 5.0:
        score += 10
        reasons.append(f"Avg CPU {avg_cpu:.1f}% over 14 days (<5% — low utilization)")

    # Name-based signals
    dev_match = _matches_any(name, {"test", "dev", "temp", "staging"})
    if dev_match:
        score += 15
        reasons.append(f"Dev/test naming pattern ('{dev_match}' in name)")

    prod_match = _matches_any(name, _PROD_PATTERNS)
    if prod_match:
        score -= 30
        reasons.append(f"Production naming pattern ('{prod_match}' in name) — high risk")

    # Public IP with traffic (stored by scanner if applicable)
    has_public_ip = details.get("public_ip_address") or details.get("has_public_ip", False)
    incoming_traffic = details.get("incoming_network_bytes_14d", -1)
    if has_public_ip and incoming_traffic > 0:
        score -= 20
        reasons.append("Has public IP with incoming network traffic — may be receiving requests")

    # ASG-managed instances are riskier to remove
    if details.get("asg_managed"):
        score -= 15
        asg_name = details.get("asg_name", "unknown ASG")
        reasons.append(f"Part of Auto Scaling Group ({asg_name}) — review ASG policies instead")

    return _clamp(score), reasons


def _score_rds_idle(finding: Finding, session: Any) -> Tuple[int, List[str]]:
    """Score an RDS instance with zero connections."""
    score = 40
    reasons: List[str] = []
    details = finding.details or {}
    tags = details.get("tags") or []
    name = _get_name_tag(tags)

    # Connection data quality — how many days of zero connections?
    # The scanner checks 14 days; we also check description for "21" days
    desc = (finding.description or "").lower()
    max_conn = details.get("max_connections_14d", -1)

    if max_conn == 0:
        # Scanner confirmed zero — look at description for longer window hint
        if "21" in desc or "21d" in desc:
            score += 25
            reasons.append("Zero database connections for 21+ days")
        else:
            score += 15
            reasons.append("Zero database connections for 14 days")

    # Name-based signals
    dev_match = _matches_any(name, {"dev", "test", "staging", "temp"})
    if dev_match:
        score += 10
        reasons.append(f"Dev/test naming pattern ('{dev_match}' in name)")

    prod_match = _matches_any(name, _PROD_PATTERNS)
    if prod_match:
        score -= 20
        reasons.append(f"Production naming pattern ('{prod_match}' in name) — caution")

    # Multi-AZ = strong production signal
    if details.get("multi_az"):
        score -= 25
        reasons.append("Multi-AZ deployment — production configuration, verify before deleting")

    # Read replicas (stored in details if scanner detected them)
    if details.get("has_read_replicas"):
        score -= 15
        reasons.append("Has read replicas — indicates active production use pattern")

    return _clamp(score), reasons


def _score_ebs_unattached(finding: Finding, session: Any) -> Tuple[int, List[str]]:
    """Score an unattached EBS volume.

    Uses describe_volumes to check creation/attachment timestamps.
    API docs: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/describe_volumes.html
    """
    score = 70  # Unattached is a strong waste signal
    reasons: List[str] = []
    details = finding.details or {}
    tags = details.get("tags") or []
    name = _get_name_tag(tags)

    # Try to get detachment age via describe_volumes
    days_unattached: Optional[float] = None
    try:
        ec2 = session.client("ec2", region_name=finding.region)
        resp = ec2.describe_volumes(VolumeIds=[finding.resource_id])
        vols = resp.get("Volumes", [])
        if vols:
            vol = vols[0]
            # CreateTime is always present
            create_time = vol.get("CreateTime")
            if create_time:
                now = datetime.now(timezone.utc)
                days_unattached = (now - create_time).total_seconds() / 86400.0
    except ClientError as exc:
        logger.debug("describe_volumes for confidence check failed (%s): %s", finding.resource_id, exc)
    except Exception as exc:  # noqa: BLE001
        logger.debug("describe_volumes unexpected error (%s): %s", finding.resource_id, exc)

    if days_unattached is not None:
        if days_unattached > 30:
            score += 15
            reasons.append(f"Volume unattached (available) for {int(days_unattached)}+ days")
        elif days_unattached < 7:
            score -= 20
            reasons.append(f"Volume detached only {int(days_unattached)} days ago — may be intentional")

    # Name-based signals
    temp_match = _matches_any(name, {"temp", "old", "test", "backup"})
    if temp_match:
        score += 10
        reasons.append(f"Temporary/disposable naming pattern ('{temp_match}' in name)")

    prod_match = _matches_any(name, {"prod", "data", "db"})
    if prod_match:
        score -= 15
        reasons.append(f"Production/data naming pattern ('{prod_match}' in name) — check before deleting")

    # Snapshot existence check — if no snapshot, easier to delete (but riskier if wrong)
    # Conversely, no snapshot means data is unprotected → score slightly up (more waste signal)
    try:
        ec2 = session.client("ec2", region_name=finding.region)
        resp = ec2.describe_snapshots(
            Filters=[{"Name": "volume-id", "Values": [finding.resource_id]}],
            OwnerIds=["self"],
        )
        snaps = resp.get("Snapshots", [])
        if not snaps:
            score += 10
            reasons.append("No snapshot exists for this volume — nothing to restore from")
        else:
            reasons.append(f"Volume has {len(snaps)} snapshot(s) — data recoverable if needed")
    except ClientError as exc:
        logger.debug("describe_snapshots for confidence check failed (%s): %s", finding.resource_id, exc)
    except Exception as exc:  # noqa: BLE001
        logger.debug("describe_snapshots unexpected error (%s): %s", finding.resource_id, exc)

    return _clamp(score), reasons


def _score_eip(finding: Finding, session: Any) -> Tuple[int, List[str]]:
    """EIPs are clear waste — fixed score of 90."""
    return 90, ["Unassociated Elastic IP — $3.60/month with zero utility"]


def _score_ebs_snapshot(finding: Finding, session: Any) -> Tuple[int, List[str]]:
    """Score an orphaned EBS snapshot."""
    score = 60
    reasons: List[str] = []
    details = finding.details or {}
    age_days: int = details.get("age_days") or 0
    desc = (details.get("description") or "").lower()
    encrypted: bool = details.get("encrypted", False)
    source_volume_gone: bool = (
        details.get("volume_id", "") not in ("", "vol-ffffffff")
        and not details.get("volume_exists", True)
    )

    # Age bonuses
    if age_days > 180:
        score += 20
        reasons.append(f"Snapshot is {age_days} days old (>180d — very stale)")
    elif age_days > 90:
        score += 15
        reasons.append(f"Snapshot is {age_days} days old (>90d — stale)")

    # Source volume no longer exists (already confirmed by the scanner)
    if source_volume_gone or details.get("volume_id"):
        score += 10
        reasons.append(f"Source volume ({details.get('volume_id', 'unknown')}) no longer exists")

    # Production keywords in description
    prod_match = _matches_any(desc, {"prod", "production", "critical"})
    if prod_match:
        score -= 20
        reasons.append(f"Description mentions '{prod_match}' — verify compliance retention requirements")

    # Encrypted snapshots may need process (key management, compliance)
    if encrypted:
        score -= 15
        reasons.append("Encrypted snapshot — may contain sensitive data; verify retention policy")
    else:
        reasons.append("Unencrypted snapshot — low retention risk")

    return _clamp(score), reasons


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def calculate_confidence(
    finding: Finding,
    session: Any,
) -> Tuple[int, List[str], str]:
    """Calculate confidence score, reasons, and label for a finding.

    Args:
        finding: The Finding to score.
        session: An active boto3 Session for optional API enrichment.

    Returns:
        (confidence_score, confidence_reasons, safe_to_delete_label)
    """
    resource_type = finding.resource_type
    issue_type = finding.issue_type

    try:
        if resource_type == "EC2" and issue_type == "stopped":
            score, reasons = _score_ec2_stopped(finding, session)
        elif resource_type == "EC2" and issue_type == "low_utilization":
            score, reasons = _score_ec2_idle(finding, session)
        elif resource_type == "RDS" and issue_type in ("zero_connections", "stopped"):
            score, reasons = _score_rds_idle(finding, session)
        elif resource_type == "EBS" and issue_type == "unattached":
            score, reasons = _score_ebs_unattached(finding, session)
        elif resource_type == "EIP" and issue_type == "unassociated":
            score, reasons = _score_eip(finding, session)
        elif resource_type == "EBS Snapshot" and issue_type == "orphaned_snapshot":
            score, reasons = _score_ebs_snapshot(finding, session)
        else:
            # Unknown resource type — return neutral/unknown
            return 0, [], "UNKNOWN"

        label = _score_to_label(score)
        return score, reasons, label

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Confidence scoring failed for %s (%s): %s",
            finding.resource_id, finding.resource_type, exc
        )
        return 0, [], "UNKNOWN"
