"""EC2 instance scanner (stopped >7d, low CPU utilization)."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from botocore.exceptions import ClientError

from models.finding import Finding
from scanners.base import BaseScanner
from utils.pricing import get_ebs_volume_price, get_ec2_instance_price

logger = logging.getLogger(__name__)

_STOP_DATE_RE = re.compile(r"\((\d{4}-\d{2}-\d{2})")
_HOURS_PER_MONTH = 730.0
_CPU_LOW_PCT = 5.0
_STOPPED_MIN_DAYS = 7
_MIN_INSTANCE_AGE_DAYS = 14  # Skip CPU check for new instances


def _days_since_embedded_date(
    reason: Optional[str], launch_time: Optional[datetime] = None
) -> Tuple[Optional[float], bool]:
    """Parse YYYY-MM-DD from StateTransitionReason or fallback to LaunchTime.

    Returns:
        (days_since, date_available): days_since is None if neither source available.
        date_available indicates whether the exact stop date was parsed.
    """
    if reason:
        m = _STOP_DATE_RE.search(reason)
        if m:
            try:
                day = datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                return (now - day).total_seconds() / 86400.0, True
            except ValueError:
                pass

    # Fallback: use LaunchTime as an approximation (minimum time stopped)
    if launch_time:
        now = datetime.now(timezone.utc)
        return (now - launch_time).total_seconds() / 86400.0, False

    return None, False


def _is_spot_instance(inst: Dict[str, Any]) -> bool:
    """Check if instance is a Spot instance (no savings from termination)."""
    return inst.get("InstanceLifecycle") == "spot" or bool(inst.get("SpotInstanceRequestId"))


def _is_asg_managed(inst: Dict[str, Any]) -> bool:
    """Check if instance is managed by Auto Scaling Group."""
    tags = inst.get("Tags") or []
    for tag in tags:
        if tag.get("Key") == "aws:autoscaling:groupName":
            return True
    return False


def _get_asg_name(inst: Dict[str, Any]) -> Optional[str]:
    """Get ASG name if instance is managed by one."""
    tags = inst.get("Tags") or []
    for tag in tags:
        if tag.get("Key") == "aws:autoscaling:groupName":
            return tag.get("Value")
    return None


class EC2Scanner(BaseScanner):
    """Detect costly EC2 usage patterns."""

    def scan(self) -> List[Finding]:
        return self._scan_stopped_instances() + self._scan_low_utilization_instances()

    def _scan_stopped_instances(self) -> List[Finding]:
        findings: List[Finding] = []
        ec2 = self.session.client("ec2", region_name=self.region)
        try:
            paginator = ec2.get_paginator("describe_instances")
            for page in paginator.paginate(
                Filters=[{"Name": "instance-state-name", "Values": ["stopped"]}]
            ):
                for reservation in page.get("Reservations", []):
                    for inst in reservation.get("Instances", []):
                        tags = inst.get("Tags")
                        if self._tags_excluded(tags):
                            continue

                        # Skip Spot instances (AWS manages lifecycle)
                        if _is_spot_instance(inst):
                            logger.debug("Skipping Spot instance %s", inst.get("InstanceId"))
                            continue

                        reason = inst.get("StateTransitionReason", "")
                        launch_time = inst.get("LaunchTime")
                        days, date_available = _days_since_embedded_date(reason, launch_time)

                        if days is None or days < _STOPPED_MIN_DAYS:
                            continue

                        iid = inst.get("InstanceId", "")
                        itype = inst.get("InstanceType", "t3.micro")

                        # Calculate actual EBS storage cost (not compute cost)
                        attached_volumes = self._get_attached_volume_costs(ec2, inst)
                        ebs_monthly = sum(v["monthly_cost"] for v in attached_volumes)

                        # Compute cost is informational only (what it WOULD cost if started)
                        hourly = self._hourly_price(itype)
                        compute_monthly = hourly * _HOURS_PER_MONTH

                        # Savings = EBS cost only (stopped instances have zero compute cost)
                        sev = "High" if ebs_monthly >= 50 else "Medium" if ebs_monthly >= 10 else "Low"

                        # Check if ASG managed - change recommendation
                        is_asg = _is_asg_managed(inst)
                        asg_name = _get_asg_name(inst) if is_asg else None

                        date_note = "" if date_available else " (stopped date approximated from launch time)"
                        description = (
                            f"Instance stopped ~{int(days)}d (>{_STOPPED_MIN_DAYS}d); "
                            f"no compute charges; attached EBS volumes cost ${ebs_monthly:.2f}/month{date_note}"
                        )

                        details: Dict[str, Any] = {
                            "instance_type": itype,
                            "state_transition_reason": reason,
                            "days_stopped": round(days, 1),
                            "stop_date_available": date_available,
                            "attached_volumes": attached_volumes,
                            "compute_cost_when_running": round(compute_monthly, 2),
                            "tags": tags or [],
                        }

                        if is_asg:
                            details["asg_managed"] = True
                            details["asg_name"] = asg_name
                            description += " [ASG managed - review scaling policies]"

                        findings.append(
                            Finding(
                                resource_id=iid,
                                resource_type="EC2",
                                region=self.region,
                                issue_type="stopped",
                                description=description,
                                monthly_savings=round(ebs_monthly, 2),
                                severity=sev,
                                details=details,
                            )
                        )
        except ClientError as exc:
            logger.warning("EC2 stopped scan failed in %s: %s", self.region, exc)
        return findings

    def _get_attached_volume_costs(
        self, ec2: Any, instance: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Get EBS volume details and costs for all attached volumes."""
        volumes: List[Dict[str, Any]] = []
        block_mappings = instance.get("BlockDeviceMappings", [])
        if not block_mappings:
            return volumes

        volume_ids = [
            m["Ebs"]["VolumeId"]
            for m in block_mappings
            if m.get("Ebs", {}).get("VolumeId")
        ]
        if not volume_ids:
            return volumes

        try:
            resp = ec2.describe_volumes(VolumeIds=volume_ids)
            for vol in resp.get("Volumes", []):
                vol_id = vol.get("VolumeId", "")
                vol_type = vol.get("VolumeType", "gp3")
                size_gb = int(vol.get("Size", 0))
                try:
                    gb_month_price = get_ebs_volume_price(
                        self.pricing_client,
                        self.pricing_cache,
                        vol_type,
                        self.region,
                    )
                except Exception as exc:
                    logger.warning("EBS pricing failed for %s: %s", vol_id, exc)
                    gb_month_price = 0.0
                monthly_cost = size_gb * gb_month_price
                volumes.append({
                    "volume_id": vol_id,
                    "volume_type": vol_type,
                    "size_gb": size_gb,
                    "monthly_cost": round(monthly_cost, 2),
                })
        except ClientError as exc:
            logger.warning("describe_volumes failed: %s", exc)
        return volumes

    def _hourly_price(self, instance_type: str) -> float:
        try:
            return get_ec2_instance_price(
                self.pricing_client,
                self.pricing_cache,
                instance_type,
                self.region,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("EC2 pricing failed for %s: %s", instance_type, exc)
            return 0.0

    def _scan_low_utilization_instances(self) -> List[Finding]:
        findings: List[Finding] = []
        ec2 = self.session.client("ec2", region_name=self.region)
        cw = self.session.client("cloudwatch", region_name=self.region)
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=14)
        min_launch_threshold = end - timedelta(days=_MIN_INSTANCE_AGE_DAYS)

        try:
            paginator = ec2.get_paginator("describe_instances")
            for page in paginator.paginate(
                Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
            ):
                for reservation in page.get("Reservations", []):
                    for inst in reservation.get("Instances", []):
                        tags = inst.get("Tags")
                        if self._tags_excluded(tags):
                            continue

                        iid = inst.get("InstanceId", "")

                        # Skip Spot instances (AWS manages lifecycle, pricing different)
                        if _is_spot_instance(inst):
                            logger.debug("Skipping Spot instance %s for utilization", iid)
                            continue

                        # Skip instances <14 days old (insufficient CloudWatch data)
                        launch_time = inst.get("LaunchTime")
                        if launch_time and launch_time > min_launch_threshold:
                            logger.debug(
                                "Skipping instance %s: launched %s (<%d days old)",
                                iid, launch_time, _MIN_INSTANCE_AGE_DAYS
                            )
                            continue

                        itype = inst.get("InstanceType", "t3.micro")
                        avg_cpu = self._avg_cpu_utilization(cw, iid, start, end)
                        if avg_cpu is None:
                            continue
                        if avg_cpu >= _CPU_LOW_PCT:
                            continue

                        hourly = self._hourly_price(itype)
                        monthly = hourly * _HOURS_PER_MONTH
                        sev = "Medium" if monthly >= 50 else "Low"

                        # Check if ASG managed - different recommendation
                        is_asg = _is_asg_managed(inst)
                        asg_name = _get_asg_name(inst) if is_asg else None

                        if is_asg:
                            description = (
                                f"Average CPU {avg_cpu:.1f}% over 14d (<{_CPU_LOW_PCT}%); "
                                f"ASG managed ({asg_name}) - review scaling policies instead of direct termination"
                            )
                            recommended_action = "Review ASG scaling policies"
                        else:
                            description = (
                                f"Average CPU {avg_cpu:.1f}% over 14d (<{_CPU_LOW_PCT}%); "
                                "consider rightsizing or stopping non-prod"
                            )
                            recommended_action = "Rightsize or terminate"

                        details: Dict[str, Any] = {
                            "instance_type": itype,
                            "avg_cpu_14d": round(avg_cpu, 2),
                            "recommended_action": recommended_action,
                            "tags": tags or [],
                        }

                        if is_asg:
                            details["asg_managed"] = True
                            details["asg_name"] = asg_name

                        findings.append(
                            Finding(
                                resource_id=iid,
                                resource_type="EC2",
                                region=self.region,
                                issue_type="low_utilization",
                                description=description,
                                monthly_savings=round(monthly * 0.5, 2),
                                severity=sev,
                                details=details,
                            )
                        )
        except ClientError as exc:
            logger.warning("EC2 utilization scan failed in %s: %s", self.region, exc)
        return findings

    @staticmethod
    def _avg_cpu_utilization(
        cw: Any,
        instance_id: str,
        start: datetime,
        end: datetime,
    ) -> Optional[float]:
        try:
            resp = cw.get_metric_statistics(
                Namespace="AWS/EC2",
                MetricName="CPUUtilization",
                Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
                StartTime=start,
                EndTime=end,
                Period=86400,
                Statistics=["Average"],
            )
            pts = resp.get("Datapoints") or []
            if not pts:
                return None
            return sum(p["Average"] for p in pts) / len(pts)
        except ClientError as exc:
            logger.debug("CPU metric unavailable for %s: %s", instance_id, exc)
            return None
