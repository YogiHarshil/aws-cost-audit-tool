"""RDS instance scanner (zero connections, stopped instances)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from botocore.exceptions import ClientError

from models.finding import Finding
from scanners.base import BaseScanner
from utils.pricing import get_rds_instance_price

logger = logging.getLogger(__name__)

_HOURS_PER_MONTH = 730.0


def _pricing_engine_name(engine: str) -> str:
    """Map DescribeDBInstances Engine to AWS Pricing ``databaseEngine`` value."""
    e = (engine or "").lower()
    mapping = {
        "mysql": "MySQL",
        "postgres": "PostgreSQL",
        "postgresql": "PostgreSQL",
        "aurora-mysql": "Aurora MySQL",
        "aurora-postgresql": "Aurora PostgreSQL",
        "mariadb": "MariaDB",
        "oracle-ee": "Oracle",
        "oracle-se2": "Oracle",
        "oracle-se1": "Oracle",
        "sqlserver-ee": "SQL Server",
        "sqlserver-se": "SQL Server",
        "sqlserver-ex": "SQL Server",
        "sqlserver-web": "SQL Server",
    }
    return mapping.get(e, "MySQL")


class RDSScanner(BaseScanner):
    """Detect idle or stopped RDS DB instances."""

    def scan(self) -> List[Finding]:
        return self._scan_zero_connections() + self._scan_stopped_instances()

    def _db_tags(self, rds: Any, arn: str) -> List[Dict[str, str]]:
        try:
            resp = rds.list_tags_for_resource(ResourceName=arn)
            return resp.get("TagList", [])
        except ClientError:
            return []

    def _hourly_price(self, instance_class: str, engine: str) -> float:
        try:
            return get_rds_instance_price(
                self.pricing_client,
                self.pricing_cache,
                instance_class,
                self.region,
                database_engine=_pricing_engine_name(engine),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("RDS pricing failed for %s: %s", instance_class, exc)
            return 0.0

    def _scan_stopped_instances(self) -> List[Finding]:
        findings: List[Finding] = []
        rds = self.session.client("rds", region_name=self.region)
        try:
            paginator = rds.get_paginator("describe_db_instances")
            for page in paginator.paginate():
                for db in page.get("DBInstances", []):
                    if db.get("DBInstanceStatus") != "stopped":
                        continue
                    arn = db.get("DBInstanceArn", "")
                    tags = self._db_tags(rds, arn) if arn else []
                    if self._tags_excluded(tags):
                        continue
                    iid = db.get("DBInstanceIdentifier", "")
                    cls_name = db.get("DBInstanceClass", "db.t3.micro")
                    engine = db.get("Engine", "mysql")
                    hourly = self._hourly_price(cls_name, engine)
                    monthly = hourly * _HOURS_PER_MONTH
                    findings.append(
                        Finding(
                            resource_id=iid,
                            resource_type="RDS",
                            region=self.region,
                            issue_type="stopped",
                            description="RDS instance is stopped but still billed for storage (compute estimate)",
                            monthly_savings=round(monthly, 2),
                            severity="High" if monthly >= 100 else "Medium",
                            details={
                                "db_instance_class": cls_name,
                                "engine": engine,
                                "allocated_storage": db.get("AllocatedStorage"),
                                "tags": tags,
                            },
                        )
                    )
        except ClientError as exc:
            logger.warning("RDS stopped scan failed in %s: %s", self.region, exc)
        return findings

    def _scan_zero_connections(self) -> List[Finding]:
        findings: List[Finding] = []
        rds = self.session.client("rds", region_name=self.region)
        cw = self.session.client("cloudwatch", region_name=self.region)
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=14)
        try:
            paginator = rds.get_paginator("describe_db_instances")
            for page in paginator.paginate():
                for db in page.get("DBInstances", []):
                    if db.get("DBInstanceStatus") not in ("available", "storage-optimization"):
                        continue
                    arn = db.get("DBInstanceArn", "")
                    tags = self._db_tags(rds, arn) if arn else []
                    if self._tags_excluded(tags):
                        continue
                    iid = db.get("DBInstanceIdentifier", "")
                    max_conn = self._max_db_connections(cw, iid, start, end)
                    if max_conn is None:
                        continue
                    if max_conn > 0:
                        continue
                    cls_name = db.get("DBInstanceClass", "db.t3.micro")
                    engine = db.get("Engine", "mysql")
                    hourly = self._hourly_price(cls_name, engine)
                    monthly = hourly * _HOURS_PER_MONTH
                    findings.append(
                        Finding(
                            resource_id=iid,
                            resource_type="RDS",
                            region=self.region,
                            issue_type="zero_connections",
                            description="No database connections observed in 14d (max metric)",
                            monthly_savings=round(monthly * 0.6, 2),
                            severity="High" if monthly >= 150 else "Medium",
                            details={
                                "db_instance_class": cls_name,
                                "engine": engine,
                                "max_connections_14d": max_conn,
                                "tags": tags,
                            },
                        )
                    )
        except ClientError as exc:
            logger.warning("RDS connections scan failed in %s: %s", self.region, exc)
        return findings

    @staticmethod
    def _max_db_connections(
        cw: Any,
        db_instance_id: str,
        start: datetime,
        end: datetime,
    ) -> Optional[float]:
        try:
            resp = cw.get_metric_statistics(
                Namespace="AWS/RDS",
                MetricName="DatabaseConnections",
                Dimensions=[{"Name": "DBInstanceIdentifier", "Value": db_instance_id}],
                StartTime=start,
                EndTime=end,
                Period=86400,
                Statistics=["Maximum"],
            )
            pts = resp.get("Datapoints") or []
            if not pts:
                return None
            return max(p["Maximum"] for p in pts)
        except ClientError as exc:
            logger.debug("DB connections metric unavailable for %s: %s", db_instance_id, exc)
            return None
