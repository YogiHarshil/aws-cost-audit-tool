"""Unit tests for AWS scanners (boto3 fully mocked)."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from scanners.base import exclude_tag_pairs_from_config, should_exclude_by_tags
from scanners.cost_explorer import CostExplorerScanner
from scanners.ebs import EBSScanner
from scanners.ec2 import EC2Scanner
from scanners.eip import EIPScanner
from scanners.rds import RDSScanner
from scanners.s3 import S3Scanner


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


def test_ec2_stopped_long_enough() -> None:
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
                            "InstanceType": "t3.micro",
                            "State": {"Name": "stopped"},
                            "Tags": [],
                            "StateTransitionReason": f"User initiated ({old} 12:00:00 GMT)",
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
    assert findings[0].issue_type == "stopped"


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
    _prime_clients(session, "s3")
    s3 = clients["s3"]
    s3.list_buckets.return_value = {"Buckets": [{"Name": "my-bucket"}]}
    s3.get_bucket_location.return_value = {"LocationConstraint": None}
    s3.get_bucket_tagging.side_effect = ClientError(
        {"Error": {"Code": "NoSuchTagSet", "Message": "x"}},
        "GetBucketTagging",
    )
    s3.get_bucket_lifecycle_configuration.side_effect = ClientError(
        {"Error": {"Code": "NoSuchLifecycleConfiguration", "Message": "none"}},
        "GetBucketLifecycleConfiguration",
    )
    scanner = S3Scanner(session, "us-east-1", [], MagicMock(), MagicMock())
    findings = scanner._scan_missing_lifecycle()
    assert len(findings) == 1
    assert findings[0].resource_id == "my-bucket"


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
