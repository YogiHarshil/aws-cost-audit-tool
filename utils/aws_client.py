"""Boto3 session and client factory with optional AssumeRole and adaptive retries."""

from __future__ import annotations

import logging
from typing import Any, List, Optional

import boto3
from botocore.config import Config as BotoConfig

logger = logging.getLogger(__name__)

_DEFAULT_ROLE_SESSION = "aws-cost-audit-tool"
_DEFAULT_ASSUME_DURATION = 3600


def _boto_core_config() -> BotoConfig:
    """Shared botocore config: adaptive retries for throttling."""
    return BotoConfig(
        retries={"max_attempts": 10, "mode": "adaptive"},
    )


def _session_from_profile(aws_profile: Optional[str]) -> boto3.Session:
    """Build a Session from a named profile, or the default chain if no name is given.

    If ``aws_profile`` is non-empty, **only** that profile is used. There is no
    fallback to other credentials when the profile is missing — this avoids
    accidentally scanning the wrong account when switching clients.

    Args:
        aws_profile: Profile name from ``AWS_PROFILE`` / ``--profile``, or
            None / whitespace to use ``boto3.Session()`` (credential chain only,
            no named profile).

    Returns:
        Configured session.

    Raises:
        botocore.exceptions.ProfileNotFound: If ``aws_profile`` is set but not
            defined in ``~/.aws/credentials`` or ``~/.aws/config``.
    """
    if aws_profile is None or not str(aws_profile).strip():
        return boto3.Session()
    return boto3.Session(profile_name=str(aws_profile).strip())


def create_session(
    aws_profile: Optional[str] = "default",
    aws_role_arn: Optional[str] = None,
) -> boto3.Session:
    """Build a boto3 Session using a profile and/or STS AssumeRole.

    If ``aws_role_arn`` is set, the base profile session calls ``sts:AssumeRole``
    and a new session is returned with temporary credentials.

    Args:
        aws_profile: Named AWS CLI profile for base credentials. Use None or
            ``""`` to use the default credential chain **without** a named
            profile. If set, that profile **must** exist or :exc:`ProfileNotFound`
            is raised (no silent fallback to env/instance credentials).
        aws_role_arn: Optional IAM role ARN to assume.

    Returns:
        Configured ``boto3.Session``.

    Raises:
        botocore.exceptions.ProfileNotFound: If ``aws_profile`` is non-empty and
            missing from AWS shared config.
        ClientError: If AssumeRole fails.
    """
    botocfg = _boto_core_config()

    if aws_role_arn:
        base_session = _session_from_profile(aws_profile)
        sts = base_session.client("sts", config=botocfg)
        logger.debug("Assuming role %s", aws_role_arn)
        response = sts.assume_role(
            RoleArn=aws_role_arn,
            RoleSessionName=_DEFAULT_ROLE_SESSION,
            DurationSeconds=_DEFAULT_ASSUME_DURATION,
        )
        creds = response["Credentials"]
        return boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
        )

    return _session_from_profile(aws_profile)


def create_client(
    session: boto3.Session,
    service_name: str,
    region_name: Optional[str] = None,
) -> Any:
    """Create a low-level service client with consistent retry configuration.

    The Pricing API is only available in ``us-east-1``; ``region_name`` is
    forced for ``service_name == "pricing"``.

    Args:
        session: Active boto3 session.
        service_name: AWS service id (e.g. ``"ec2"``, ``"pricing"``).
        region_name: AWS region for the client. Required except for
            ``"pricing"``, which defaults to ``us-east-1``.

    Returns:
        boto3 service client.

    Raises:
        ValueError: If ``region_name`` is missing for a regional service.
    """
    if service_name == "pricing":
        region_name = "us-east-1"
    if region_name is None:
        raise ValueError(f"region_name is required for service {service_name!r}")
    return session.client(
        service_name,
        region_name=region_name,
        config=_boto_core_config(),
    )


def discover_regions(session: boto3.Session, partition_name: str = "aws") -> List[str]:
    """Return EC2 opt-in aware region codes for the given partition.

    Uses DescribeRegions to query dynamically enabled regions.

    Args:
        session: boto3 session (credentials not consulted for this call).
        partition_name: AWS partition, default ``aws`` (commercial).

    Returns:
        Sorted list of region codes.
    """
    ec2_client = create_client(session, "ec2", region_name="us-east-1")
    try:
        response = ec2_client.describe_regions(AllRegions=False)
        return sorted([r["RegionName"] for r in response["Regions"]])
    except Exception as e:
        logger.warning(f"Failed to describe regions dynamically: {e}")
        regions = session.get_available_regions("ec2", partition_name=partition_name)
        return sorted(regions)
