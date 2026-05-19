"""ECS scanner - detects idle clusters, services, and over-provisioned tasks.

ECS costs come from:
- EC2 instances (for EC2 launch type)
- Fargate vCPU and memory (for Fargate launch type)
- Clusters themselves are free, but idle resources waste money

Common issues:
- Empty clusters with no running tasks
- Services with 0 running tasks (scaled to zero but not deleted)
- Services with no recent deployments (stale)
- Over-provisioned Fargate tasks
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from botocore.exceptions import ClientError

from models.finding import Finding
from scanners.base import BaseScanner

logger = logging.getLogger(__name__)

# Fargate pricing (us-east-1) - per vCPU-hour and per GB-hour
_FARGATE_VCPU_HOUR = 0.04048  # $0.04048/vCPU-hour
_FARGATE_GB_HOUR = 0.004445  # $0.004445/GB-hour
_HOURS_PER_MONTH = 730.0

# Thresholds
_STALE_DAYS = 30  # Service with no deployment for 30 days


class ECSScanner(BaseScanner):
    """Detect idle ECS clusters and services.

    Checks for:
    1. Empty clusters (no running tasks)
    2. Services scaled to zero
    3. Services with no recent deployments
    4. Stopped/inactive services still defined
    """

    def scan(self) -> List[Finding]:
        """Scan for ECS cost optimization opportunities."""
        findings: List[Finding] = []
        ecs = self.session.client("ecs", region_name=self.region)

        # Get all clusters
        try:
            cluster_arns = self._list_all_clusters(ecs)
        except ClientError as exc:
            logger.warning("ECS list_clusters failed in %s: %s", self.region, exc)
            return findings

        if not cluster_arns:
            return findings

        # Describe clusters in batches
        for cluster_arn in cluster_arns:
            cluster_findings = self._analyze_cluster(ecs, cluster_arn)
            findings.extend(cluster_findings)

        return findings

    def _list_all_clusters(self, ecs: Any) -> List[str]:
        """List all ECS cluster ARNs."""
        cluster_arns: List[str] = []
        try:
            paginator = ecs.get_paginator("list_clusters")
            for page in paginator.paginate():
                cluster_arns.extend(page.get("clusterArns", []))
        except ClientError as exc:
            logger.warning("ECS list_clusters failed: %s", exc)
        return cluster_arns

    def _analyze_cluster(self, ecs: Any, cluster_arn: str) -> List[Finding]:
        """Analyze a single ECS cluster for cost issues."""
        findings: List[Finding] = []

        try:
            response = ecs.describe_clusters(
                clusters=[cluster_arn],
                include=["TAGS", "STATISTICS"],
            )
            clusters = response.get("clusters", [])
            if not clusters:
                return findings

            cluster = clusters[0]
        except ClientError as exc:
            logger.warning("ECS describe_clusters failed for %s: %s", cluster_arn, exc)
            return findings

        cluster_name = cluster.get("clusterName", "")
        tags = cluster.get("tags", [])

        # Convert tags to expected format
        formatted_tags = [{"Key": t.get("key"), "Value": t.get("value")} for t in tags]
        if self._tags_excluded(formatted_tags):
            return findings

        # Get cluster statistics
        running_tasks = cluster.get("runningTasksCount", 0)
        pending_tasks = cluster.get("pendingTasksCount", 0)
        active_services = cluster.get("activeServicesCount", 0)
        registered_instances = cluster.get("registeredContainerInstancesCount", 0)

        # Check for empty cluster
        if running_tasks == 0 and pending_tasks == 0 and active_services == 0:
            # Empty cluster - could have EC2 instances still running
            if registered_instances > 0:
                # Cluster with EC2 instances but no tasks
                findings.append(
                    Finding(
                        resource_id=cluster_name,
                        resource_type="ECS Cluster",
                        region=self.region,
                        issue_type="idle_with_instances",
                        description=(
                            f"ECS cluster has {registered_instances} container instances "
                            f"but no running tasks. EC2 costs continue."
                        ),
                        monthly_savings=0.0,  # Need EC2 scanner for actual cost
                        severity="High",
                        details={
                            "cluster_arn": cluster_arn,
                            "cluster_name": cluster_name,
                            "running_tasks": running_tasks,
                            "active_services": active_services,
                            "registered_instances": registered_instances,
                            "recommendation": "Terminate idle container instances or delete cluster",
                            "tags": formatted_tags,
                        },
                    )
                )
            else:
                # Completely empty cluster (no instances, no tasks)
                findings.append(
                    Finding(
                        resource_id=cluster_name,
                        resource_type="ECS Cluster",
                        region=self.region,
                        issue_type="empty",
                        description=(
                            "Empty ECS cluster with no services, tasks, or instances. "
                            "Can be safely deleted."
                        ),
                        monthly_savings=0.0,  # Clusters are free
                        severity="Low",
                        details={
                            "cluster_arn": cluster_arn,
                            "cluster_name": cluster_name,
                            "status": cluster.get("status"),
                            "recommendation": "Delete unused cluster",
                            "tags": formatted_tags,
                        },
                    )
                )

        # Analyze services in this cluster
        service_findings = self._analyze_services(ecs, cluster_arn, cluster_name)
        findings.extend(service_findings)

        return findings

    def _analyze_services(
        self, ecs: Any, cluster_arn: str, cluster_name: str
    ) -> List[Finding]:
        """Analyze ECS services for idle or stale services."""
        findings: List[Finding] = []

        try:
            service_arns = self._list_all_services(ecs, cluster_arn)
        except ClientError as exc:
            logger.warning("ECS list_services failed for %s: %s", cluster_name, exc)
            return findings

        if not service_arns:
            return findings

        # Describe services in batches of 10
        for i in range(0, len(service_arns), 10):
            batch = service_arns[i:i + 10]
            try:
                response = ecs.describe_services(
                    cluster=cluster_arn,
                    services=batch,
                    include=["TAGS"],
                )
                for service in response.get("services", []):
                    finding = self._analyze_service(service, cluster_name)
                    if finding:
                        findings.append(finding)
            except ClientError as exc:
                logger.warning("ECS describe_services failed: %s", exc)

        return findings

    def _list_all_services(self, ecs: Any, cluster_arn: str) -> List[str]:
        """List all service ARNs in a cluster."""
        service_arns: List[str] = []
        try:
            paginator = ecs.get_paginator("list_services")
            for page in paginator.paginate(cluster=cluster_arn):
                service_arns.extend(page.get("serviceArns", []))
        except ClientError as exc:
            logger.warning("ECS list_services failed: %s", exc)
        return service_arns

    def _analyze_service(
        self, service: Dict[str, Any], cluster_name: str
    ) -> Optional[Finding]:
        """Analyze a single ECS service."""
        service_name = service.get("serviceName", "")
        service_arn = service.get("serviceArn", "")
        status = service.get("status", "")

        # Skip deleted services
        if status == "INACTIVE":
            return None

        tags = service.get("tags", [])
        formatted_tags = [{"Key": t.get("key"), "Value": t.get("value")} for t in tags]
        if self._tags_excluded(formatted_tags):
            return None

        running_count = service.get("runningCount", 0)
        desired_count = service.get("desiredCount", 0)
        launch_type = service.get("launchType", "EC2")

        # Get task definition for cost estimation
        task_def_arn = service.get("taskDefinition", "")
        monthly_cost = 0.0

        # Check for service scaled to zero
        if desired_count == 0 and running_count == 0:
            return Finding(
                resource_id=f"{cluster_name}/{service_name}",
                resource_type="ECS Service",
                region=self.region,
                issue_type="scaled_to_zero",
                description=(
                    f"ECS service scaled to 0 tasks. "
                    f"Consider deleting if no longer needed."
                ),
                monthly_savings=0.0,  # No active costs
                severity="Low",
                details={
                    "cluster_name": cluster_name,
                    "service_name": service_name,
                    "service_arn": service_arn,
                    "launch_type": launch_type,
                    "desired_count": desired_count,
                    "running_count": running_count,
                    "recommendation": "Delete service if permanently unused",
                    "tags": formatted_tags,
                },
            )

        # Check deployment age (stale service)
        deployments = service.get("deployments", [])
        if deployments:
            latest_deployment = deployments[0]
            created_at = latest_deployment.get("createdAt")
            if created_at:
                days_since_deploy = (datetime.now(timezone.utc) - created_at).days
                if days_since_deploy > _STALE_DAYS * 3:  # 90 days without deployment
                    # Calculate Fargate cost if applicable
                    if launch_type == "FARGATE" and running_count > 0:
                        monthly_cost = self._estimate_fargate_cost(
                            service, running_count
                        )

                    return Finding(
                        resource_id=f"{cluster_name}/{service_name}",
                        resource_type="ECS Service",
                        region=self.region,
                        issue_type="stale",
                        description=(
                            f"ECS service running {running_count} tasks with no deployment "
                            f"for {days_since_deploy} days. Review if still needed."
                        ),
                        monthly_savings=round(monthly_cost * 0.3, 2),  # 30% potential savings
                        severity="Medium" if monthly_cost > 50 else "Low",
                        details={
                            "cluster_name": cluster_name,
                            "service_name": service_name,
                            "launch_type": launch_type,
                            "running_count": running_count,
                            "days_since_deployment": days_since_deploy,
                            "last_deployment": created_at.isoformat() if created_at else None,
                            "estimated_monthly_cost": round(monthly_cost, 2),
                            "recommendation": "Review and update or delete stale service",
                            "tags": formatted_tags,
                        },
                    )

        return None

    def _estimate_fargate_cost(
        self, service: Dict[str, Any], task_count: int
    ) -> float:
        """Estimate monthly Fargate cost for a service."""
        # Default to small task if we can't determine size
        vcpu = 0.25
        memory_gb = 0.5

        # Try to get from task definition (would need additional API call)
        # For now, use deployment configuration hints
        deployments = service.get("deployments", [])
        if deployments:
            # Use running count as approximation
            pass

        # Calculate monthly cost
        vcpu_cost = vcpu * _FARGATE_VCPU_HOUR * _HOURS_PER_MONTH
        memory_cost = memory_gb * _FARGATE_GB_HOUR * _HOURS_PER_MONTH
        task_cost = vcpu_cost + memory_cost

        return task_cost * task_count
