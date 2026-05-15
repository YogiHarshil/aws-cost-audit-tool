"""Unit tests for AWS scanners (boto3 fully mocked)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from scanners.base import exclude_tag_pairs_from_config, should_exclude_by_tags
from scanners.cost_explorer import CostExplorerScanner
from scanners.ebs import EBSScanner
from scanners.ec2 import EC2Scanner
from scanners.eip import EIPScanner
from scanners.rds import RDSScanner
from scanners.reservations import ReservationScanner
from scanners.s3 import S3Scanner
from scanners.snapshots import SnapshotScanner


def _session_with_clients() -> tuple[MagicMock, dict]:
    clients: dict = {}
    session = MagicMock()

    def _client(name: str, **kwargs: object) -> MagicMock:
        if name not in clients:
            clients[name] = MagicMock()
        return clients[name]

    session.client.side_effect = _client
    return session, clients


def _prime_clients(session: MagicMock, *services: str, region: str = "us-east-1") -> None:
    """Populate the client registry (same keys scanners use via ``session.client``)."""
    for svc in services:
        session.client(svc, region_name=region)


def test_should_exclude_by_tags() -> None:
    tags = [{"Key": "Environment", "Value": "Production"}]
    assert should_exclude_by_tags(tags, [("Environment", "Production")]) is True
    assert should_exclude_by_tags(tags, [("Environment", "Dev")]) is False
    assert should_exclude_by_tags([], [("Environment", "Production")]) is False


def test_exclude_tag_pairs_from_config_mixed() -> None:
    pairs = exclude_tag_pairs_from_config(
        [{"Key": "A", "Value": "1"}, {"B": "2"}]
    )
    assert ("A", "1") in pairs
    assert ("B", "2") in pairs


def test_ebs_scan_unattached() -> None:
    session, clients = _session_with_clients()
    _prime_clients(session, "ec2")
    ec2 = clients["ec2"]
    paginator = MagicMock()
    ec2.get_paginator.return_value = paginator
    paginator.paginate.return_value = [
        {
            "Volumes": [
                {
                    "VolumeId": "vol-1",
                    "Size": 10,
                    "VolumeType": "gp3",
                    "Encrypted": True,
                    "Tags": [{"Key": "Name", "Value": "disk"}],
                }
            ]
        }
    ]
    with patch("scanners.ebs.get_ebs_volume_price", return_value=0.08):
        scanner = EBSScanner(session, "us-east-1", [], MagicMock(), MagicMock())
        findings = scanner.scan()
    assert len(findings) == 1
    assert findings[0].resource_id == "vol-1"
    assert findings[0].issue_type == "unattached"
    assert findings[0].monthly_savings == pytest.approx(0.8, rel=1e-3)


def test_ebs_respects_exclude_tags() -> None:
    session, clients = _session_with_clients()
    _prime_clients(session, "ec2")
    ec2 = clients["ec2"]
    paginator = MagicMock()
    ec2.get_paginator.return_value = paginator
    paginator.paginate.return_value = [
        {
            "Volumes": [
                {
                    "VolumeId": "vol-x",
                    "Size": 1,
                    "VolumeType": "gp2",
                    "Tags": [{"Key": "Environment", "Value": "Production"}],
                }
            ]
        }
    ]
    with patch("scanners.ebs.get_ebs_volume_price", return_value=0.1):
        scanner = EBSScanner(
            session,
            "us-east-1",
            [{"Environment": "Production"}],
            MagicMock(),
            MagicMock(),
        )
        assert scanner.scan() == []


def test_eip_unassociated() -> None:
    session, clients = _session_with_clients()
    _prime_clients(session, "ec2", region="eu-west-1")
    ec2 = clients["ec2"]
    ec2.describe_addresses.return_value = {
        "Addresses": [
            {"AllocationId": "eipalloc-1", "PublicIp": "1.2.3.4", "Domain": "vpc"},
            {
                "AllocationId": "eipalloc-2",
                "PublicIp": "5.6.7.8",
                "AssociationId": "eipassoc-99",
            },
        ]
    }
    scanner = EIPScanner(session, "eu-west-1", [], MagicMock(), MagicMock())
    findings = scanner.scan()
    assert len(findings) == 1
    assert findings[0].resource_id == "eipalloc-1"
    assert findings[0].monthly_savings == pytest.approx(3.60)


def test_ec2_stopped_calculates_ebs_cost_not_compute() -> None:
    """Verify stopped EC2 savings = EBS storage cost only, NOT compute rate."""
    session, clients = _session_with_clients()
    _prime_clients(session, "ec2")
    ec2 = clients["ec2"]
    paginator = MagicMock()
    ec2.get_paginator.return_value = paginator
    old = (date.today() - timedelta(days=20)).strftime("%Y-%m-%d")
    paginator.paginate.return_value = [
        {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": "i-stopped1",
                            "InstanceType": "t3.large",  # Would cost ~$60/month compute
                            "State": {"Name": "stopped"},
                            "Tags": [],
                            "StateTransitionReason": f"User initiated ({old} 12:00:00 GMT)",
                            "BlockDeviceMappings": [
                                {"Ebs": {"VolumeId": "vol-123"}}
                            ],
                        }
                    ]
                }
            ]
        }
    ]
    # Mock describe_volumes to return 50GB gp3 volume
    ec2.describe_volumes.return_value = {
        "Volumes": [
            {"VolumeId": "vol-123", "VolumeType": "gp3", "Size": 50}
        ]
    }
    # Mock pricing: compute $0.0832/hr, EBS $0.08/GB/month
    with patch("scanners.ec2.get_ec2_instance_price", return_value=0.0832):
        with patch("scanners.ec2.get_ebs_volume_price", return_value=0.08):
            scanner = EC2Scanner(session, "us-east-1", [], MagicMock(), MagicMock())
            findings = scanner._scan_stopped_instances()

    assert len(findings) == 1
    assert findings[0].issue_type == "stopped"
    # Savings should be EBS cost: 50 GB * $0.08 = $4.00, NOT compute ~$60.74
    assert findings[0].monthly_savings == pytest.approx(4.0, rel=1e-2)
    # Verify details include attached volumes
    assert "attached_volumes" in findings[0].details
    assert len(findings[0].details["attached_volumes"]) == 1
    assert findings[0].details["attached_volumes"][0]["volume_id"] == "vol-123"
    # Compute cost should be informational only
    assert "compute_cost_when_running" in findings[0].details
    assert findings[0].details["compute_cost_when_running"] > 50  # ~$60.74


def test_ec2_stopped_skipped_without_date() -> None:
    session, clients = _session_with_clients()
    _prime_clients(session, "ec2")
    ec2 = clients["ec2"]
    paginator = MagicMock()
    ec2.get_paginator.return_value = paginator
    paginator.paginate.return_value = [
        {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": "i-nodate",
                            "InstanceType": "t3.micro",
                            "State": {"Name": "stopped"},
                            "Tags": [],
                            "StateTransitionReason": "Client.UserInitiatedShutdown",
                        }
                    ]
                }
            ]
        }
    ]
    scanner = EC2Scanner(session, "us-east-1", [], MagicMock(), MagicMock())
    assert scanner._scan_stopped_instances() == []


def test_ec2_low_utilization() -> None:
    session, clients = _session_with_clients()
    _prime_clients(session, "ec2", "cloudwatch", region="us-west-2")
    ec2 = clients["ec2"]
    paginator = MagicMock()
    ec2.get_paginator.return_value = paginator
    paginator.paginate.return_value = [
        {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": "i-run1",
                            "InstanceType": "t3.small",
                            "State": {"Name": "running"},
                            "Tags": [],
                        }
                    ]
                }
            ]
        }
    ]
    cw = clients["cloudwatch"]
    cw.get_metric_statistics.return_value = {
        "Datapoints": [{"Average": 2.0}, {"Average": 1.0}],
    }
    with patch("scanners.ec2.get_ec2_instance_price", return_value=0.02):
        scanner = EC2Scanner(session, "us-west-2", [], MagicMock(), MagicMock())
        findings = scanner._scan_low_utilization_instances()
    assert len(findings) == 1
    assert findings[0].issue_type == "low_utilization"


def test_rds_stopped() -> None:
    session, clients = _session_with_clients()
    _prime_clients(session, "rds")
    rds = clients["rds"]
    paginator = MagicMock()
    rds.get_paginator.return_value = paginator
    paginator.paginate.return_value = [
        {
            "DBInstances": [
                {
                    "DBInstanceIdentifier": "db-stopped",
                    "DBInstanceArn": "arn:aws:rds:us-east-1:1:db:db-stopped",
                    "DBInstanceStatus": "stopped",
                    "DBInstanceClass": "db.t3.micro",
                    "Engine": "mysql",
                    "AllocatedStorage": 20,
                }
            ]
        }
    ]
    rds.list_tags_for_resource.return_value = {"TagList": []}
    with patch("scanners.rds.get_rds_instance_price", return_value=0.05):
        scanner = RDSScanner(session, "us-east-1", [], MagicMock(), MagicMock())
        findings = scanner._scan_stopped_instances()
    assert len(findings) == 1
    assert findings[0].issue_type == "stopped"


def test_rds_zero_connections() -> None:
    session, clients = _session_with_clients()
    _prime_clients(session, "rds", "cloudwatch", region="eu-west-1")
    rds = clients["rds"]
    paginator = MagicMock()
    rds.get_paginator.return_value = paginator
    paginator.paginate.return_value = [
        {
            "DBInstances": [
                {
                    "DBInstanceIdentifier": "db-idle",
                    "DBInstanceArn": "arn:aws:rds:eu-west-1:1:db:db-idle",
                    "DBInstanceStatus": "available",
                    "DBInstanceClass": "db.m5.large",
                    "Engine": "postgres",
                    "AllocatedStorage": 100,
                }
            ]
        }
    ]
    rds.list_tags_for_resource.return_value = {"TagList": []}
    cw = clients["cloudwatch"]
    cw.get_metric_statistics.return_value = {
        "Datapoints": [{"Maximum": 0.0}, {"Maximum": 0.0}],
    }
    with patch("scanners.rds.get_rds_instance_price", return_value=0.20):
        scanner = RDSScanner(session, "eu-west-1", [], MagicMock(), MagicMock())
        findings = scanner._scan_zero_connections()
    assert len(findings) == 1
    assert findings[0].issue_type == "zero_connections"


def test_s3_missing_lifecycle() -> None:
    session, clients = _session_with_clients()
    _prime_clients(session, "s3", "cloudwatch")
    s3 = clients["s3"]
    cw = clients["cloudwatch"]
    s3.list_buckets.return_value = {"Buckets": [{"Name": "my-bucket", "CreationDate": datetime.now(timezone.utc)}]}
    s3.get_bucket_location.return_value = {"LocationConstraint": None}
    s3.get_bucket_tagging.side_effect = ClientError(
        {"Error": {"Code": "NoSuchTagSet", "Message": "x"}},
        "GetBucketTagging",
    )
    s3.get_bucket_lifecycle_configuration.side_effect = ClientError(
        {"Error": {"Code": "NoSuchLifecycleConfiguration", "Message": "none"}},
        "GetBucketLifecycleConfiguration",
    )
    # Mock CloudWatch to return no datapoints (small/unknown bucket)
    cw.get_metric_statistics.return_value = {"Datapoints": []}
    scanner = S3Scanner(session, "us-east-1", [], MagicMock(), MagicMock())
    findings = scanner._scan_missing_lifecycle()
    assert len(findings) == 1
    assert findings[0].resource_id == "my-bucket"
    assert findings[0].monthly_savings == 0.0  # No size available = 0 savings


def test_s3_large_bucket_no_tiering() -> None:
    session, clients = _session_with_clients()
    _prime_clients(session, "s3", "cloudwatch", region="eu-west-1")
    s3 = clients["s3"]
    cw = clients["cloudwatch"]
    s3.list_buckets.return_value = {"Buckets": [{"Name": "big-bucket"}]}
    s3.get_bucket_location.return_value = {"LocationConstraint": "eu-west-1"}
    s3.get_bucket_tagging.side_effect = ClientError(
        {"Error": {"Code": "NoSuchTagSet", "Message": "x"}},
        "GetBucketTagging",
    )
    s3.list_bucket_intelligent_tiering_configurations.return_value = {
        "IntelligentTieringConfigurationList": []
    }
    large = 120 * 1024 * 1024 * 1024
    cw.get_metric_statistics.return_value = {
        "Datapoints": [{"Average": large}, {"Average": large}],
    }
    scanner = S3Scanner(session, "eu-west-1", [], MagicMock(), MagicMock())
    findings = scanner._scan_large_buckets_no_tiering()
    assert len(findings) == 1
    assert findings[0].issue_type == "large_bucket_no_tiering"


def test_cost_explorer_scan_finding_on_spike() -> None:
    session = MagicMock()
    ce = MagicMock()
    session.client.return_value = ce

    def ce_side_effect(*args: object, **kwargs: object) -> MagicMock:
        return ce

    session.client.side_effect = ce_side_effect

    scanner = CostExplorerScanner(session)
    with patch.object(
        CostExplorerScanner,
        "get_month_over_month_trend",
        return_value={"increase_pct": 35.0},
    ):
        findings = scanner.scan()
    assert len(findings) == 1
    assert findings[0].resource_type == "Cost Explorer"


def test_cost_explorer_no_finding_when_flat() -> None:
    session = MagicMock()
    ce = MagicMock()
    session.client.return_value = ce
    session.client.side_effect = lambda *a, **k: ce
    scanner = CostExplorerScanner(session)
    with patch.object(
        CostExplorerScanner,
        "get_month_over_month_trend",
        return_value={"increase_pct": 5.0},
    ):
        assert scanner.scan() == []


# =============================================================================
# NEW TESTS: EC2 Stopped EBS Cost (not compute)
# =============================================================================


def test_ec2_stopped_no_volumes_zero_savings() -> None:
    """Stopped instance with no attached volumes should show $0 savings."""
    session, clients = _session_with_clients()
    _prime_clients(session, "ec2")
    ec2 = clients["ec2"]
    paginator = MagicMock()
    ec2.get_paginator.return_value = paginator
    old = (date.today() - timedelta(days=20)).strftime("%Y-%m-%d")
    paginator.paginate.return_value = [
        {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": "i-novol",
                            "InstanceType": "t3.micro",
                            "State": {"Name": "stopped"},
                            "Tags": [],
                            "StateTransitionReason": f"User initiated ({old} 12:00:00 GMT)",
                            "BlockDeviceMappings": [],  # No volumes
                        }
                    ]
                }
            ]
        }
    ]
    with patch("scanners.ec2.get_ec2_instance_price", return_value=0.01):
        scanner = EC2Scanner(session, "us-east-1", [], MagicMock(), MagicMock())
        findings = scanner._scan_stopped_instances()

    assert len(findings) == 1
    assert findings[0].monthly_savings == 0.0
    assert findings[0].details["attached_volumes"] == []


# =============================================================================
# NEW TESTS: RDS Multi-AZ Pricing
# =============================================================================


def test_rds_multi_az_pricing() -> None:
    """Verify Multi-AZ RDS uses correct deployment_option for pricing."""
    session, clients = _session_with_clients()
    _prime_clients(session, "rds")
    rds = clients["rds"]
    paginator = MagicMock()
    rds.get_paginator.return_value = paginator
    paginator.paginate.return_value = [
        {
            "DBInstances": [
                {
                    "DBInstanceIdentifier": "db-multiaz",
                    "DBInstanceArn": "arn:aws:rds:us-east-1:1:db:db-multiaz",
                    "DBInstanceStatus": "stopped",
                    "DBInstanceClass": "db.m5.large",
                    "Engine": "postgres",
                    "MultiAZ": True,  # Multi-AZ enabled
                    "AllocatedStorage": 100,
                }
            ]
        }
    ]
    rds.list_tags_for_resource.return_value = {"TagList": []}

    # Mock pricing to verify Multi-AZ is passed
    pricing_calls = []

    def mock_pricing(*args, **kwargs):
        pricing_calls.append(kwargs)
        return 0.35  # Multi-AZ rate

    with patch("scanners.rds.get_rds_instance_price", side_effect=mock_pricing):
        scanner = RDSScanner(session, "us-east-1", [], MagicMock(), MagicMock())
        findings = scanner._scan_stopped_instances()

    assert len(findings) == 1
    # Verify pricing was called with Multi-AZ deployment option
    assert len(pricing_calls) == 1
    assert pricing_calls[0].get("deployment_option") == "Multi-AZ"
    # Verify details include multi_az info
    assert findings[0].details["multi_az"] is True
    assert findings[0].details["deployment_option"] == "Multi-AZ"


def test_rds_single_az_pricing() -> None:
    """Verify Single-AZ RDS uses correct deployment_option."""
    session, clients = _session_with_clients()
    _prime_clients(session, "rds")
    rds = clients["rds"]
    paginator = MagicMock()
    rds.get_paginator.return_value = paginator
    paginator.paginate.return_value = [
        {
            "DBInstances": [
                {
                    "DBInstanceIdentifier": "db-singleaz",
                    "DBInstanceArn": "arn:aws:rds:us-east-1:1:db:db-singleaz",
                    "DBInstanceStatus": "stopped",
                    "DBInstanceClass": "db.t3.micro",
                    "Engine": "mysql",
                    "MultiAZ": False,
                    "AllocatedStorage": 20,
                }
            ]
        }
    ]
    rds.list_tags_for_resource.return_value = {"TagList": []}

    pricing_calls = []

    def mock_pricing(*args, **kwargs):
        pricing_calls.append(kwargs)
        return 0.05

    with patch("scanners.rds.get_rds_instance_price", side_effect=mock_pricing):
        scanner = RDSScanner(session, "us-east-1", [], MagicMock(), MagicMock())
        scanner._scan_stopped_instances()

    assert pricing_calls[0].get("deployment_option") == "Single-AZ"


# =============================================================================
# NEW TESTS: S3 Lifecycle with CloudWatch Size
# =============================================================================


def test_s3_missing_lifecycle_large_bucket_uses_cloudwatch() -> None:
    """Large bucket without lifecycle should show savings based on actual size."""
    session, clients = _session_with_clients()
    _prime_clients(session, "s3", "cloudwatch")
    s3 = clients["s3"]
    cw = clients["cloudwatch"]

    s3.list_buckets.return_value = {"Buckets": [{"Name": "large-bucket", "CreationDate": datetime.now(timezone.utc)}]}
    s3.get_bucket_location.return_value = {"LocationConstraint": None}
    s3.get_bucket_tagging.side_effect = ClientError(
        {"Error": {"Code": "NoSuchTagSet", "Message": "x"}},
        "GetBucketTagging",
    )
    s3.get_bucket_lifecycle_configuration.side_effect = ClientError(
        {"Error": {"Code": "NoSuchLifecycleConfiguration", "Message": "none"}},
        "GetBucketLifecycleConfiguration",
    )

    # 500 GB bucket (over 100 GB threshold)
    large_bytes = 500 * 1024 * 1024 * 1024
    cw.get_metric_statistics.return_value = {
        "Datapoints": [{"Average": large_bytes, "Timestamp": datetime.now(timezone.utc)}]
    }

    scanner = S3Scanner(session, "us-east-1", [], MagicMock(), MagicMock())
    findings = scanner._scan_missing_lifecycle()

    assert len(findings) == 1
    # Savings = 500 GB * $0.023 * 40% = $4.60
    assert findings[0].monthly_savings == pytest.approx(4.60, rel=0.1)
    assert findings[0].severity == "Medium"
    assert findings[0].details["size_gb"] == pytest.approx(500, rel=0.1)
    assert findings[0].details["size_source"] == "cloudwatch"


def test_s3_missing_lifecycle_small_bucket_zero_savings() -> None:
    """Small bucket without lifecycle should show $0 savings (hygiene only)."""
    session, clients = _session_with_clients()
    _prime_clients(session, "s3", "cloudwatch")
    s3 = clients["s3"]
    cw = clients["cloudwatch"]

    s3.list_buckets.return_value = {"Buckets": [{"Name": "small-bucket", "CreationDate": datetime.now(timezone.utc)}]}
    s3.get_bucket_location.return_value = {"LocationConstraint": None}
    s3.get_bucket_tagging.side_effect = ClientError(
        {"Error": {"Code": "NoSuchTagSet", "Message": "x"}},
        "GetBucketTagging",
    )
    s3.get_bucket_lifecycle_configuration.side_effect = ClientError(
        {"Error": {"Code": "NoSuchLifecycleConfiguration", "Message": "none"}},
        "GetBucketLifecycleConfiguration",
    )

    # 10 GB bucket (under 100 GB threshold)
    small_bytes = 10 * 1024 * 1024 * 1024
    cw.get_metric_statistics.return_value = {
        "Datapoints": [{"Average": small_bytes, "Timestamp": datetime.now(timezone.utc)}]
    }

    scanner = S3Scanner(session, "us-east-1", [], MagicMock(), MagicMock())
    findings = scanner._scan_missing_lifecycle()

    assert len(findings) == 1
    assert findings[0].monthly_savings == 0.0
    assert findings[0].severity == "Low"


# =============================================================================
# NEW TESTS: EBS Snapshot Scanner
# =============================================================================


def test_snapshot_scanner_orphaned() -> None:
    """Orphaned snapshot (no volume, no AMI) should be flagged."""
    session, clients = _session_with_clients()
    _prime_clients(session, "ec2")
    ec2 = clients["ec2"]

    # No existing volumes
    vol_paginator = MagicMock()
    vol_paginator.paginate.return_value = [{"Volumes": []}]

    # No AMIs
    ami_paginator = MagicMock()
    ami_paginator.paginate.return_value = [{"Images": []}]

    # One orphaned snapshot
    snap_paginator = MagicMock()
    snap_paginator.paginate.return_value = [
        {
            "Snapshots": [
                {
                    "SnapshotId": "snap-orphan1",
                    "VolumeId": "vol-deleted",
                    "VolumeSize": 100,
                    "StartTime": datetime.now(timezone.utc) - timedelta(days=60),
                    "Description": "Old backup",
                    "Encrypted": True,
                    "Tags": [{"Key": "Name", "Value": "old-backup"}],
                }
            ]
        }
    ]

    def paginator_factory(name):
        if name == "describe_volumes":
            return vol_paginator
        elif name == "describe_images":
            return ami_paginator
        elif name == "describe_snapshots":
            return snap_paginator
        return MagicMock()

    ec2.get_paginator.side_effect = paginator_factory

    scanner = SnapshotScanner(session, "us-east-1", [], MagicMock(), MagicMock())
    findings = scanner.scan()

    assert len(findings) == 1
    assert findings[0].resource_id == "snap-orphan1"
    assert findings[0].issue_type == "orphaned_snapshot"
    # Savings = 100 GB * $0.05 = $5.00
    assert findings[0].monthly_savings == pytest.approx(5.0)
    assert findings[0].details["size_gb"] == 100
    assert findings[0].details["age_days"] >= 60


def test_snapshot_scanner_excludes_ami_backed() -> None:
    """Snapshot backing an AMI should NOT be flagged."""
    session, clients = _session_with_clients()
    _prime_clients(session, "ec2")
    ec2 = clients["ec2"]

    vol_paginator = MagicMock()
    vol_paginator.paginate.return_value = [{"Volumes": []}]

    # AMI uses this snapshot
    ami_paginator = MagicMock()
    ami_paginator.paginate.return_value = [
        {
            "Images": [
                {
                    "ImageId": "ami-123",
                    "BlockDeviceMappings": [
                        {"Ebs": {"SnapshotId": "snap-ami-backed"}}
                    ],
                }
            ]
        }
    ]

    snap_paginator = MagicMock()
    snap_paginator.paginate.return_value = [
        {
            "Snapshots": [
                {
                    "SnapshotId": "snap-ami-backed",
                    "VolumeId": "vol-deleted",
                    "VolumeSize": 50,
                    "StartTime": datetime.now(timezone.utc) - timedelta(days=90),
                }
            ]
        }
    ]

    def paginator_factory(name):
        if name == "describe_volumes":
            return vol_paginator
        elif name == "describe_images":
            return ami_paginator
        elif name == "describe_snapshots":
            return snap_paginator
        return MagicMock()

    ec2.get_paginator.side_effect = paginator_factory

    scanner = SnapshotScanner(session, "us-east-1", [], MagicMock(), MagicMock())
    findings = scanner.scan()

    assert len(findings) == 0  # Should not flag AMI-backed snapshots


def test_snapshot_scanner_excludes_volume_exists() -> None:
    """Snapshot with existing source volume should NOT be flagged."""
    session, clients = _session_with_clients()
    _prime_clients(session, "ec2")
    ec2 = clients["ec2"]

    # Source volume still exists
    vol_paginator = MagicMock()
    vol_paginator.paginate.return_value = [
        {"Volumes": [{"VolumeId": "vol-exists"}]}
    ]

    ami_paginator = MagicMock()
    ami_paginator.paginate.return_value = [{"Images": []}]

    snap_paginator = MagicMock()
    snap_paginator.paginate.return_value = [
        {
            "Snapshots": [
                {
                    "SnapshotId": "snap-has-vol",
                    "VolumeId": "vol-exists",  # This volume still exists
                    "VolumeSize": 50,
                    "StartTime": datetime.now(timezone.utc) - timedelta(days=90),
                }
            ]
        }
    ]

    def paginator_factory(name):
        if name == "describe_volumes":
            return vol_paginator
        elif name == "describe_images":
            return ami_paginator
        elif name == "describe_snapshots":
            return snap_paginator
        return MagicMock()

    ec2.get_paginator.side_effect = paginator_factory

    scanner = SnapshotScanner(session, "us-east-1", [], MagicMock(), MagicMock())
    findings = scanner.scan()

    assert len(findings) == 0


# =============================================================================
# NEW TESTS: Reserved Instance Coverage Scanner
# =============================================================================


def test_ri_scanner_finds_uncovered_instances() -> None:
    """On-demand instances without RI coverage should be flagged."""
    session = MagicMock()
    ec2 = MagicMock()

    # Make session.client always return the same ec2 mock
    session.client.return_value = ec2

    # No active RIs
    ec2.describe_reserved_instances.return_value = {"ReservedInstances": []}

    # 3 running m5.large instances (30+ days)
    paginator = MagicMock()
    paginator.paginate.return_value = [
        {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": f"i-{i}",
                            "InstanceType": "m5.large",
                            "LaunchTime": datetime.now(timezone.utc) - timedelta(days=45),
                        }
                        for i in range(3)
                    ]
                }
            ]
        }
    ]
    ec2.get_paginator.return_value = paginator

    pricing_cache = MagicMock()

    # Mock discover_regions to return just one region
    with patch("scanners.reservations.discover_regions", return_value=["us-east-1"]):
        with patch(
            "scanners.reservations.get_ec2_instance_price", return_value=0.096
        ):
            scanner = ReservationScanner(session, MagicMock(), pricing_cache)
            findings = scanner.scan()

    assert len(findings) == 1
    assert findings[0].issue_type == "ri_opportunity"
    assert findings[0].details["uncovered_count"] == 3
    # Savings = 3 * 0.096 * 0.37 * 730 = ~$77.80/month
    assert findings[0].monthly_savings > 70


def test_ri_scanner_excludes_covered_instances() -> None:
    """Instances covered by RIs should NOT be flagged."""
    session = MagicMock()
    ec2 = MagicMock()
    session.client.return_value = ec2

    # 2 active RIs for m5.large
    ec2.describe_reserved_instances.return_value = {
        "ReservedInstances": [
            {"InstanceType": "m5.large", "InstanceCount": 2, "State": "active"}
        ]
    }

    # 2 running m5.large (covered by RIs)
    paginator = MagicMock()
    paginator.paginate.return_value = [
        {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": f"i-{i}",
                            "InstanceType": "m5.large",
                            "LaunchTime": datetime.now(timezone.utc) - timedelta(days=45),
                        }
                        for i in range(2)
                    ]
                }
            ]
        }
    ]
    ec2.get_paginator.return_value = paginator

    pricing_cache = MagicMock()

    with patch("scanners.reservations.discover_regions", return_value=["us-east-1"]):
        with patch(
            "scanners.reservations.get_ec2_instance_price", return_value=0.096
        ):
            scanner = ReservationScanner(session, MagicMock(), pricing_cache)
            findings = scanner.scan()

    # All instances covered, no findings
    assert len(findings) == 0


def test_ri_scanner_skips_spot_instances() -> None:
    """Spot instances should NOT be flagged for RI coverage."""
    session = MagicMock()
    ec2 = MagicMock()
    session.client.return_value = ec2

    ec2.describe_reserved_instances.return_value = {"ReservedInstances": []}

    # 3 spot instances (have SpotInstanceRequestId)
    paginator = MagicMock()
    paginator.paginate.return_value = [
        {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": f"i-spot{i}",
                            "InstanceType": "m5.large",
                            "LaunchTime": datetime.now(timezone.utc) - timedelta(days=45),
                            "SpotInstanceRequestId": f"sir-{i}",  # Spot instance
                        }
                        for i in range(3)
                    ]
                }
            ]
        }
    ]
    ec2.get_paginator.return_value = paginator

    pricing_cache = MagicMock()

    with patch("scanners.reservations.discover_regions", return_value=["us-east-1"]):
        scanner = ReservationScanner(session, MagicMock(), pricing_cache)
        findings = scanner.scan()

    # Spot instances excluded, no findings
    assert len(findings) == 0


def test_ec2_stopped_skips_spot_instances() -> None:
    """Stopped Spot instances should NOT be flagged (AWS manages lifecycle)."""
    session = MagicMock()
    ec2 = MagicMock()
    session.client.return_value = ec2

    paginator = MagicMock()
    paginator.paginate.return_value = [
        {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": "i-spot123",
                            "InstanceType": "t3.large",
                            "InstanceLifecycle": "spot",  # Spot instance
                            "StateTransitionReason": "User initiated (2024-01-01 00:00:00 GMT)",
                        }
                    ]
                }
            ]
        }
    ]
    ec2.get_paginator.return_value = paginator

    scanner = EC2Scanner(session, "us-east-1", [], MagicMock(), MagicMock())
    findings = scanner._scan_stopped_instances()

    # Spot instances should be skipped
    assert len(findings) == 0


def test_ec2_low_util_skips_new_instances() -> None:
    """Instances <14 days old should NOT be flagged for low utilization."""
    session = MagicMock()
    ec2 = MagicMock()
    cw = MagicMock()
    session.client.side_effect = lambda svc, **kw: ec2 if svc == "ec2" else cw

    # Instance launched 5 days ago (too new)
    paginator = MagicMock()
    paginator.paginate.return_value = [
        {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": "i-new123",
                            "InstanceType": "t3.large",
                            "LaunchTime": datetime.now(timezone.utc) - timedelta(days=5),
                        }
                    ]
                }
            ]
        }
    ]
    ec2.get_paginator.return_value = paginator

    scanner = EC2Scanner(session, "us-east-1", [], MagicMock(), MagicMock())
    findings = scanner._scan_low_utilization_instances()

    # New instances should be skipped
    assert len(findings) == 0


def test_ec2_stopped_detects_asg_managed() -> None:
    """ASG-managed stopped instances should include ASG info in details."""
    session = MagicMock()
    ec2 = MagicMock()
    session.client.return_value = ec2

    paginator = MagicMock()
    paginator.paginate.return_value = [
        {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": "i-asg123",
                            "InstanceType": "t3.large",
                            "StateTransitionReason": "User initiated (2024-01-01 00:00:00 GMT)",
                            "Tags": [
                                {"Key": "Name", "Value": "web-server"},
                                {"Key": "aws:autoscaling:groupName", "Value": "prod-asg"},
                            ],
                            "BlockDeviceMappings": [{"Ebs": {"VolumeId": "vol-123"}}],
                        }
                    ]
                }
            ]
        }
    ]
    ec2.get_paginator.return_value = paginator
    ec2.describe_volumes.return_value = {
        "Volumes": [{"VolumeId": "vol-123", "VolumeType": "gp3", "Size": 100}]
    }

    with patch("scanners.ec2.get_ebs_volume_price", return_value=0.08):
        scanner = EC2Scanner(session, "us-east-1", [], MagicMock(), MagicMock())
        findings = scanner._scan_stopped_instances()

    assert len(findings) == 1
    f = findings[0]
    assert f.details.get("asg_managed") is True
    assert f.details.get("asg_name") == "prod-asg"
    assert "ASG managed" in f.description


def test_snapshot_scanner_skips_aws_backup_managed() -> None:
    """Snapshots with AWS Backup tags should NOT be flagged."""
    session = MagicMock()
    ec2 = MagicMock()
    session.client.return_value = ec2

    # Return existing volumes
    vol_paginator = MagicMock()
    vol_paginator.paginate.return_value = [{"Volumes": []}]

    # Return no AMIs
    img_paginator = MagicMock()
    img_paginator.paginate.return_value = [{"Images": []}]

    # AWS Backup managed snapshot
    snap_paginator = MagicMock()
    snap_paginator.paginate.return_value = [
        {
            "Snapshots": [
                {
                    "SnapshotId": "snap-backup123",
                    "VolumeId": "vol-deleted",
                    "VolumeSize": 100,
                    "StartTime": datetime.now(timezone.utc) - timedelta(days=60),
                    "Tags": [
                        {"Key": "aws:backup:source-resource-arn", "Value": "arn:aws:ec2:us-east-1:123456789012:volume/vol-abc"}
                    ],
                }
            ]
        }
    ]

    def paginator_factory(op):
        if op == "describe_volumes":
            return vol_paginator
        elif op == "describe_images":
            return img_paginator
        elif op == "describe_snapshots":
            return snap_paginator
        raise ValueError(f"Unknown operation: {op}")

    ec2.get_paginator.side_effect = paginator_factory

    scanner = SnapshotScanner(session, "us-east-1", [], MagicMock(), MagicMock())
    findings = scanner.scan()

    # AWS Backup managed snapshots should be skipped
    assert len(findings) == 0


def test_snapshot_scanner_skips_dlm_managed() -> None:
    """Snapshots with DLM tags should NOT be flagged."""
    session = MagicMock()
    ec2 = MagicMock()
    session.client.return_value = ec2

    vol_paginator = MagicMock()
    vol_paginator.paginate.return_value = [{"Volumes": []}]

    img_paginator = MagicMock()
    img_paginator.paginate.return_value = [{"Images": []}]

    # DLM managed snapshot
    snap_paginator = MagicMock()
    snap_paginator.paginate.return_value = [
        {
            "Snapshots": [
                {
                    "SnapshotId": "snap-dlm123",
                    "VolumeId": "vol-deleted",
                    "VolumeSize": 100,
                    "StartTime": datetime.now(timezone.utc) - timedelta(days=60),
                    "Tags": [
                        {"Key": "dlm:managed", "Value": "true"}
                    ],
                }
            ]
        }
    ]

    def paginator_factory(op):
        if op == "describe_volumes":
            return vol_paginator
        elif op == "describe_images":
            return img_paginator
        elif op == "describe_snapshots":
            return snap_paginator
        raise ValueError(f"Unknown operation: {op}")

    ec2.get_paginator.side_effect = paginator_factory

    scanner = SnapshotScanner(session, "us-east-1", [], MagicMock(), MagicMock())
    findings = scanner.scan()

    # DLM managed snapshots should be skipped
    assert len(findings) == 0
