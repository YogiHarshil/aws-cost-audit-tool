"""CloudWatch Logs scanner - detects log groups without retention policies.

CloudWatch Logs charges $0.03/GB for ingestion and $0.03/GB-month for storage.
By default, log groups retain logs FOREVER, leading to unbounded storage costs.

Common issues:
- Log groups with "Never Expire" retention (default)
- Large log groups growing unchecked
- Duplicate or debug logs in production
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from botocore.exceptions import ClientError

from models.finding import Finding
from scanners.base import BaseScanner

logger = logging.getLogger(__name__)

# CloudWatch Logs pricing (us-east-1)
_STORAGE_COST_PER_GB_MONTH = 0.03  # $0.03/GB-month
_INGESTION_COST_PER_GB = 0.50  # $0.50/GB ingested

# Thresholds
_MIN_STORAGE_GB = 1  # Only flag log groups > 1GB
_STALE_DAYS = 30  # Log group with no new logs for 30 days


class CloudWatchLogsScanner(BaseScanner):
    """Detect CloudWatch Log groups without retention policies.

    Checks for:
    1. Log groups with no retention policy (infinite storage)
    2. Large log groups (>1GB) growing unchecked
    3. Stale log groups with no recent activity
    """

    def scan(self) -> List[Finding]:
        """Scan for CloudWatch Logs cost optimization opportunities."""
        findings: List[Finding] = []
        logs = self.session.client("logs", region_name=self.region)

        try:
            paginator = logs.get_paginator("describe_log_groups")
            for page in paginator.paginate():
                for log_group in page.get("logGroups", []):
                    finding = self._analyze_log_group(logs, log_group)
                    if finding:
                        findings.append(finding)

        except ClientError as exc:
            logger.warning("CloudWatch Logs describe failed in %s: %s", self.region, exc)

        return findings

    def _analyze_log_group(
        self, logs: Any, log_group: Dict[str, Any]
    ) -> Optional[Finding]:
        """Analyze a single log group for cost issues."""
        log_group_name = log_group.get("logGroupName", "")
        retention_days = log_group.get("retentionInDays")  # None = infinite
        stored_bytes = log_group.get("storedBytes", 0)
        creation_time = log_group.get("creationTime")

        # Convert bytes to GB
        stored_gb = stored_bytes / (1024 ** 3)
        monthly_storage_cost = stored_gb * _STORAGE_COST_PER_GB_MONTH

        # Get tags for exclusion (requires separate API call)
        tags = self._get_log_group_tags(logs, log_group_name)
        if self._tags_excluded(tags):
            return None

        # Check for infinite retention (most common issue)
        if retention_days is None:
            # No retention = logs stored forever
            if stored_gb >= _MIN_STORAGE_GB:
                # Large log group without retention - high priority
                # Estimate savings: if we set 30-day retention, we save ~90% of storage
                estimated_savings = monthly_storage_cost * 0.9

                return Finding(
                    resource_id=log_group_name,
                    resource_type="CloudWatch Logs",
                    region=self.region,
                    issue_type="no_retention_policy",
                    description=(
                        f"Log group ({stored_gb:.1f}GB) has no retention policy. "
                        f"Logs stored indefinitely. Set retention to reduce costs."
                    ),
                    monthly_savings=round(estimated_savings, 2),
                    severity="High" if stored_gb >= 10 else "Medium",
                    details={
                        "log_group_name": log_group_name,
                        "stored_bytes": stored_bytes,
                        "stored_gb": round(stored_gb, 2),
                        "retention_days": "Never Expire",
                        "current_monthly_cost": round(monthly_storage_cost, 2),
                        "recommendation": "Set retention to 30, 60, or 90 days based on compliance needs",
                        "creation_time": self._format_timestamp(creation_time),
                        "tags": tags,
                    },
                )
            elif stored_bytes > 0:
                # Small log group but still no retention
                return Finding(
                    resource_id=log_group_name,
                    resource_type="CloudWatch Logs",
                    region=self.region,
                    issue_type="no_retention_policy",
                    description=(
                        f"Log group has no retention policy. "
                        f"Current size: {stored_gb:.2f}GB. Set retention to prevent unbounded growth."
                    ),
                    monthly_savings=round(monthly_storage_cost * 0.5, 2),
                    severity="Low",
                    details={
                        "log_group_name": log_group_name,
                        "stored_bytes": stored_bytes,
                        "stored_gb": round(stored_gb, 3),
                        "retention_days": "Never Expire",
                        "current_monthly_cost": round(monthly_storage_cost, 2),
                        "recommendation": "Set retention policy to prevent cost growth",
                        "creation_time": self._format_timestamp(creation_time),
                        "tags": tags,
                    },
                )

        # Check for stale log groups (have retention but no recent activity)
        if stored_bytes > 0:
            last_event = self._get_last_event_time(logs, log_group_name)
            if last_event:
                days_since_last_event = (
                    datetime.now(timezone.utc) - last_event
                ).days

                if days_since_last_event > _STALE_DAYS and stored_gb >= 0.1:
                    # Stale log group - might be from deleted service
                    return Finding(
                        resource_id=log_group_name,
                        resource_type="CloudWatch Logs",
                        region=self.region,
                        issue_type="stale",
                        description=(
                            f"Log group ({stored_gb:.1f}GB) has no new logs for {days_since_last_event} days. "
                            f"May be from deleted service."
                        ),
                        monthly_savings=round(monthly_storage_cost, 2),
                        severity="Medium" if stored_gb >= 1 else "Low",
                        details={
                            "log_group_name": log_group_name,
                            "stored_gb": round(stored_gb, 2),
                            "retention_days": retention_days,
                            "days_since_last_event": days_since_last_event,
                            "last_event_time": last_event.isoformat(),
                            "current_monthly_cost": round(monthly_storage_cost, 2),
                            "recommendation": "Delete if no longer needed or reduce retention",
                            "tags": tags,
                        },
                    )

        return None

    def _get_log_group_tags(
        self, logs: Any, log_group_name: str
    ) -> List[Dict[str, str]]:
        """Get tags for a log group."""
        try:
            response = logs.list_tags_log_group(logGroupName=log_group_name)
            # Convert dict to list of {Key, Value} format
            tags_dict = response.get("tags", {})
            return [{"Key": k, "Value": v} for k, v in tags_dict.items()]
        except ClientError as exc:
            logger.debug("list_tags_log_group failed for %s: %s", log_group_name, exc)
            return []

    def _get_last_event_time(
        self, logs: Any, log_group_name: str
    ) -> Optional[datetime]:
        """Get timestamp of last log event in the group."""
        try:
            # Get most recent log stream
            response = logs.describe_log_streams(
                logGroupName=log_group_name,
                orderBy="LastEventTime",
                descending=True,
                limit=1,
            )
            streams = response.get("logStreams", [])
            if not streams:
                return None

            last_event_ts = streams[0].get("lastEventTimestamp")
            if last_event_ts:
                return datetime.fromtimestamp(last_event_ts / 1000, tz=timezone.utc)
            return None

        except ClientError as exc:
            logger.debug("describe_log_streams failed for %s: %s", log_group_name, exc)
            return None

    @staticmethod
    def _format_timestamp(ts_ms: Optional[int]) -> Optional[str]:
        """Format millisecond timestamp to ISO format."""
        if ts_ms is None:
            return None
        try:
            dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            return dt.isoformat()
        except (ValueError, OSError):
            return None
