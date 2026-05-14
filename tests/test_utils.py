"""Tests for AWS client factory and pricing helpers."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ProfileNotFound

from utils.aws_client import create_client, create_session, discover_regions
from utils.pricing import (
    PricingCache,
    batch_get_prices,
    get_ec2_instance_price,
    get_ebs_volume_price,
    get_rds_instance_price,
    pricing_location_for_region,
)


def _sample_price_json(usd: str = "0.0416") -> str:
    doc = {
        "terms": {
            "OnDemand": {
                "sku1": {
                    "priceDimensions": {
                        "dim1": {"pricePerUnit": {"USD": usd}},
                    }
                }
            }
        }
    }
    return json.dumps(doc)


def test_pricing_location_mapping() -> None:
    assert pricing_location_for_region("us-east-1") == "US East (N. Virginia)"
    assert pricing_location_for_region("unknown-region-xyz") == "unknown-region-xyz"


def test_pricing_cache_threadsafe() -> None:
    cache = PricingCache()
    assert cache.get("k") is None
    cache.set("k", 1.5)
    assert cache.get("k") == 1.5


def test_get_ec2_instance_price_uses_cache() -> None:
    client = MagicMock()
    client.get_products.return_value = {"PriceList": [_sample_price_json("0.01")], "NextToken": None}

    cache = PricingCache()
    p1 = get_ec2_instance_price(client, cache, "t3.micro", "us-east-1")
    p2 = get_ec2_instance_price(client, cache, "t3.micro", "us-east-1")
    assert p1 == pytest.approx(0.01)
    assert p2 == pytest.approx(0.01)
    client.get_products.assert_called_once()


def test_get_ec2_returns_zero_when_empty() -> None:
    client = MagicMock()
    client.get_products.return_value = {"PriceList": [], "NextToken": None}
    cache = PricingCache()
    assert get_ec2_instance_price(client, cache, "fake.type", "us-east-1") == 0.0
    assert cache.get("ec2|fake.type|US East (N. Virginia)|Linux|Shared|NA") == 0.0


def test_get_rds_and_ebs_parse() -> None:
    client = MagicMock()

    def se(**kwargs: object) -> dict:
        filters = kwargs.get("Filters") or []
        fdict = {f["Field"]: f["Value"] for f in filters}
        if fdict.get("ServiceCode") == "AmazonRDS":
            return {"PriceList": [_sample_price_json("0.05")], "NextToken": None}
        if fdict.get("volumeApiName") == "gp3":
            return {"PriceList": [_sample_price_json("0.08")], "NextToken": None}
        return {"PriceList": [], "NextToken": None}

    client.get_products.side_effect = se
    cache = PricingCache()
    assert get_rds_instance_price(client, cache, "db.t3.micro", "us-east-1") == pytest.approx(0.05)
    assert get_ebs_volume_price(client, cache, "gp3", "us-west-2") == pytest.approx(0.08)


def test_batch_get_prices_order_preserved() -> None:
    client = MagicMock()

    def side_effect(**kwargs: object) -> dict:
        filters = kwargs.get("Filters") or []
        fdict = {f["Field"]: f["Value"] for f in filters}
        if fdict.get("ServiceCode") == "AmazonRDS":
            return {"PriceList": [_sample_price_json("0.03")], "NextToken": None}
        if fdict.get("volumeApiName") == "gp2":
            return {"PriceList": [_sample_price_json("0.12")], "NextToken": None}
        if fdict.get("instanceType") == "t3.small":
            return {"PriceList": [_sample_price_json("0.02")], "NextToken": None}
        return {"PriceList": [], "NextToken": None}

    client.get_products.side_effect = side_effect
    cache = PricingCache()
    jobs = [
        ("ec2", "t3.small", "us-east-1"),
        ("rds", "db.t3.micro", "us-east-1"),
        ("ebs", "gp2", "eu-west-1"),
    ]
    prices = batch_get_prices(client, cache, jobs, max_workers=3)
    assert prices[0] == pytest.approx(0.02)
    assert prices[1] == pytest.approx(0.03)
    assert prices[2] == pytest.approx(0.12)


@patch("utils.aws_client.boto3.Session")
def test_create_session_raises_when_default_profile_missing(mock_session_cls: MagicMock) -> None:
    """Missing named profile must not fall back to another credential source."""
    mock_session_cls.side_effect = ProfileNotFound(profile="default")
    with pytest.raises(ProfileNotFound):
        create_session(aws_profile="default", aws_role_arn=None)
    mock_session_cls.assert_called_once_with(profile_name="default")


@patch("utils.aws_client.boto3.Session")
def test_create_session_raises_when_named_profile_missing(mock_session_cls: MagicMock) -> None:
    mock_session_cls.side_effect = ProfileNotFound(profile="my-audit-profile")
    with pytest.raises(ProfileNotFound):
        create_session(aws_profile="my-audit-profile", aws_role_arn=None)
    mock_session_cls.assert_called_once_with(profile_name="my-audit-profile")


@patch("utils.aws_client.boto3.Session")
def test_create_session_without_role(mock_session_cls: MagicMock) -> None:
    fake = MagicMock()
    mock_session_cls.return_value = fake
    sess = create_session(aws_profile="myprof", aws_role_arn=None)
    assert sess is fake
    mock_session_cls.assert_called_once_with(profile_name="myprof")


@patch("utils.aws_client.boto3.Session")
def test_create_session_with_assume_role(mock_session_cls: MagicMock) -> None:
    base_session = MagicMock()
    sts = MagicMock()
    base_session.client.return_value = sts
    sts.assume_role.return_value = {
        "Credentials": {
            "AccessKeyId": "ASIA",
            "SecretAccessKey": "secret",
            "SessionToken": "token",
        }
    }
    assumed_session = MagicMock()
    mock_session_cls.side_effect = [base_session, assumed_session]

    sess = create_session(aws_profile="default", aws_role_arn="arn:aws:iam::123456789012:role/R")
    assert sess is assumed_session
    sts.assume_role.assert_called_once()
    mock_session_cls.assert_any_call(profile_name="default")
    mock_session_cls.assert_any_call(
        aws_access_key_id="ASIA",
        aws_secret_access_key="secret",
        aws_session_token="token",
    )


@patch("utils.aws_client.boto3.Session")
def test_discover_regions(mock_session_cls: MagicMock) -> None:
    s = MagicMock()
    s.get_available_regions.return_value = ["b-region", "a-region"]
    mock_session_cls.return_value = s
    regions = discover_regions(s)
    assert regions == ["a-region", "b-region"]
    s.get_available_regions.assert_called_once_with("ec2", partition_name="aws")


def test_create_client_pricing_forces_us_east_1() -> None:
    session = MagicMock()
    create_client(session, "pricing")
    session.client.assert_called_once()
    _, kwargs = session.client.call_args
    assert kwargs["region_name"] == "us-east-1"


def test_create_client_requires_region_for_ec2() -> None:
    session = MagicMock()
    with pytest.raises(ValueError, match="region_name"):
        create_client(session, "ec2", region_name=None)
