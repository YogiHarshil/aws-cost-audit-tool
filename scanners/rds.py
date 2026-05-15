"""RDS instance scanner (zero connections, stopped instances)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

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


def _is_aurora_engine(engine: str) -> bool:
    """Check if engine is Aurora (different pricing model)."""
    e = (engine or "").lower()
    return "aurora" in e


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

    def _get_proxy_target_instances(self, rds: Any) -> Set[str]:
        """Get set of DB instance identifiers that are targets of RDS Proxies."""
        proxy_targets: Set[str] = set()
        try:
            # List all proxies in this region
            paginator = rds.get_paginator("describe_db_proxies")
            for page in paginator.paginate():
                for proxy in page.get("DBProxies", []):
                    proxy_name = proxy.get("DBProxyName")
                    if not proxy_name:
                        continue
                    # Get targets for this proxy
                    try:
                        targets_resp = rds.describe_db_proxy_targets(DBProxyName=proxy_name)
                        for target in targets_resp.get("Targets", []):
                            target_id = target.get("RdsResourceId") or target.get("TargetArn", "").split(":")[-1]
                            if target_id:
                                proxy_targets.add(target_id)
                    except ClientError as exc:
                        logger.debug("describe_db_proxy_targets failed for %s: %s", proxy_name, exc)
        except ClientError as exc:
            # RDS Proxy may not be available in all regions or account may not use it
            logger.debug("describe_db_proxies unavailable in %s: %s", self.region, exc)
        return proxy_targets

    def _hourly_price(
        self, instance_class: str, engine: str, multi_az: bool = False
    ) -> float:
        deployment_option = "Multi-AZ" if multi_az else "Single-AZ"
        try:
            return get_rds_instance_price(
                self.pricing_client,
                self.pricing_cache,
                instance_class,
                self.region,
                database_engine=_pricing_engine_name(engine),
                deployment_option=deployment_option,
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
                    multi_az = db.get("MultiAZ", False)
                    deployment_option = "Multi-AZ" if multi_az else "Single-AZ"
                    hourly = self._hourly_price(cls_name, engine, multi_az)
                    monthly = hourly * _HOURS_PER_MONTH
                    findings.append(
                        Finding(
                            resource_id=iid,
                            resource_type="RDS",
                            region=self.region,
                            issue_type="stopped",
                            description=f"RDS instance ({deployment_option}) is stopped but still billed for storage",
                            monthly_savings=round(monthly, 2),
                            severity="High" if monthly >= 100 else "Medium",
                            details={
                                "db_instance_class": cls_name,
                                "engine": engine,
                                "multi_az": multi_az,
                                "deployment_option": deployment_option,
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

        # Get instances behind RDS Proxy (zero connections may be normal)
        proxy_targets = self._get_proxy_target_instances(rds)

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
                    engine = db.get("Engine", "mysql")
                    cls_name = db.get("DBInstanceClass", "db.t3.micro")
                    multi_az = db.get("MultiAZ", False)
                    deployment_option = "Multi-AZ" if multi_az else "Single-AZ"

                    # Handle Aurora clusters separately (different pricing model)
                    is_aurora = _is_aurora_engine(engine)

                    max_conn = self._max_db_connections(cw, iid, start, end)
                    if max_conn is None:
                        continue
                    if max_conn > 0:
                        continue

                    # Check if behind RDS Proxy
                    has_proxy = iid in proxy_targets

                    if is_aurora:
                        # Aurora uses different pricing (ACU for serverless, or instance for provisioned)
                        # Don't calculate exact savings, flag for manual review
                        description = (
                            f"Aurora instance ({engine}) has no connections in 14d. "
                            "Verify usage via Performance Insights - pricing differs from standard RDS."
                        )
                        monthly_savings = 0.0  # Can't accurately estimate Aurora savings
                        severity = "Medium" if has_proxy else "High"
                        details: Dict[str, Any] = {
                            "db_instance_class": cls_name,
                            "engine": engine,
                            "is_aurora": True,
                            "multi_az": multi_az,
                            "deployment_option": deployment_option,
                            "max_connections_14d": max_conn,
                            "allocated_storage": db.get("AllocatedStorage"),
                            "has_rds_proxy": has_proxy,
                            "recommended_action": "Verify usage via Performance Insights",
                            "tags": tags,
                        }
                    else:
                        hourly = self._hourly_price(cls_name, engine, multi_az)
                        monthly = hourly * _HOURS_PER_MONTH

                        if has_proxy:
                            # Zero connections may be normal with proxy (connection pooling)
                            description = (
                                f"No direct connections in 14d ({deployment_option}), "
                                f"but has RDS Proxy - verify proxy metrics"
                            )
                            severity = "Low"  # Lower severity when proxy present
                        else:
                            description = f"No database connections observed in 14d ({deployment_option})"
                            severity = "High" if monthly >= 150 else "Medium"

                        monthly_savings = round(monthly * 0.6, 2)
                        details = {
                            "db_instance_class": cls_name,
                            "engine": engine,
                            "is_aurora": False,
                            "multi_az": multi_az,
                            "deployment_option": deployment_option,
                            "max_connections_14d": max_conn,
                            "allocated_storage": db.get("AllocatedStorage"),
                            "has_rds_proxy": has_proxy,
                            "tags": tags,
                        }

                    findings.append(
                        Finding(
                            resource_id=iid,
                            resource_type="RDS",
                            region=self.region,
                            issue_type="zero_connections",
                            description=description,
                            monthly_savings=monthly_savings,
                            severity=severity,
                            details=details,
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
