"""AWS Pricing API helpers with session-level thread-safe cache."""

from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# Maps EC2 region codes to Pricing API "location" values (us-east-1 only API).
REGION_NAME_MAPPING: Dict[str, str] = {
    "af-south-1": "Africa (Cape Town)",
    "ap-east-1": "Asia Pacific (Hong Kong)",
    "ap-northeast-1": "Asia Pacific (Tokyo)",
    "ap-northeast-2": "Asia Pacific (Seoul)",
    "ap-northeast-3": "Asia Pacific (Osaka)",
    "ap-south-1": "Asia Pacific (Mumbai)",
    "ap-south-2": "Asia Pacific (Hyderabad)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
    "ap-southeast-2": "Asia Pacific (Sydney)",
    "ap-southeast-3": "Asia Pacific (Jakarta)",
    "ap-southeast-4": "Asia Pacific (Melbourne)",
    "ap-southeast-5": "Asia Pacific (Malaysia)",
    "ap-southeast-7": "Asia Pacific (Thailand)",
    "ca-central-1": "Canada (Central)",
    "ca-west-1": "Canada West (Calgary)",
    "eu-central-1": "EU (Frankfurt)",
    "eu-central-2": "EU (Zurich)",
    "eu-north-1": "EU (Stockholm)",
    "eu-south-1": "EU (Milan)",
    "eu-south-2": "EU (Spain)",
    "eu-west-1": "EU (Ireland)",
    "eu-west-2": "EU (London)",
    "eu-west-3": "EU (Paris)",
    "il-central-1": "Israel (Tel Aviv)",
    "me-central-1": "Middle East (UAE)",
    "me-south-1": "Middle East (Bahrain)",
    "mx-central-1": "Mexico (Central)",
    "sa-east-1": "South America (Sao Paulo)",
    "us-east-1": "US East (N. Virginia)",
    "us-east-2": "US East (Ohio)",
    "us-west-1": "US West (N. California)",
    "us-west-2": "US West (Oregon)",
}


def pricing_location_for_region(region: str) -> str:
    """Resolve Pricing API location string for an EC2-style region code."""
    return REGION_NAME_MAPPING.get(region, region)


class PricingCache:
    """Thread-safe in-memory cache for pricing lookups (one audit process)."""

    def __init__(self) -> None:
        self._cache: Dict[str, float] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[float]:
        """Return cached USD amount or None."""
        with self._lock:
            val = self._cache.get(key)
            return val

    def set(self, key: str, price: float) -> None:
        """Store a USD amount for this key."""
        with self._lock:
            self._cache[key] = price


def _first_usd_from_price_list_json(item: Dict[str, Any]) -> float:
    """Extract first On-Demand USD unit price from a GetProducts price document."""
    on_demand = item.get("terms", {}).get("OnDemand", {})
    for _sku_key, sku in on_demand.items():
        for _dim_key, dim in sku.get("priceDimensions", {}).items():
            usd = dim.get("pricePerUnit", {}).get("USD")
            if usd is not None:
                return float(usd)
    raise ValueError("No OnDemand USD price found in price document")


def _get_products_single(
    pricing_client: Any,
    service_code: str,
    filters: List[Dict[str, str]],
) -> Optional[Dict[str, Any]]:
    """Call GetProducts with filters; return first price JSON dict or None."""
    token: Optional[str] = None
    while True:
        kwargs: Dict[str, Any] = {
            "ServiceCode": service_code,
            "Filters": filters,
            "MaxResults": 100,
        }
        if token:
            kwargs["NextToken"] = token
        response = pricing_client.get_products(**kwargs)
        price_list = response.get("PriceList") or []
        for raw in price_list:
            return json.loads(raw)
        token = response.get("NextToken")
        if not token:
            return None


def get_ec2_instance_price(
    pricing_client: Any,
    cache: PricingCache,
    instance_type: str,
    region: str,
    *,
    operating_system: str = "Linux",
    tenancy: str = "Shared",
    preinstalled_software: str = "NA",
) -> float:
    """Return Linux shared On-Demand hourly price (USD) for an EC2 instance type."""
    location = pricing_location_for_region(region)
    cache_key = (
        f"ec2|{instance_type}|{location}|{operating_system}|{tenancy}|{preinstalled_software}"
    )
    hit = cache.get(cache_key)
    if hit is not None:
        return hit

    filters = [
        {"Type": "TERM_MATCH", "Field": "ServiceCode", "Value": "AmazonEC2"},
        {"Type": "TERM_MATCH", "Field": "instanceType", "Value": instance_type},
        {"Type": "TERM_MATCH", "Field": "location", "Value": location},
        {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": operating_system},
        {"Type": "TERM_MATCH", "Field": "tenancy", "Value": tenancy},
        {"Type": "TERM_MATCH", "Field": "preInstalledSw", "Value": preinstalled_software},
        {"Type": "TERM_MATCH", "Field": "capacitystatus", "Value": "Used"},
    ]
    item = _get_products_single(pricing_client, "AmazonEC2", filters)
    if item is None:
        logger.warning(
            "No EC2 pricing for instance_type=%s region=%s location=%s",
            instance_type,
            region,
            location,
        )
        cache.set(cache_key, 0.0)
        return 0.0
    price = _first_usd_from_price_list_json(item)
    cache.set(cache_key, price)
    return price


def get_rds_instance_price(
    pricing_client: Any,
    cache: PricingCache,
    instance_type: str,
    region: str,
    *,
    database_engine: str = "MySQL",
    deployment_option: str = "Single-AZ",
    license_model: str = "No License required",
) -> float:
    """Return On-Demand hourly price (USD) for an RDS DB instance class."""
    location = pricing_location_for_region(region)
    cache_key = (
        f"rds|{instance_type}|{location}|{database_engine}|{deployment_option}|{license_model}"
    )
    hit = cache.get(cache_key)
    if hit is not None:
        return hit

    filters = [
        {"Type": "TERM_MATCH", "Field": "ServiceCode", "Value": "AmazonRDS"},
        {"Type": "TERM_MATCH", "Field": "instanceType", "Value": instance_type},
        {"Type": "TERM_MATCH", "Field": "location", "Value": location},
        {"Type": "TERM_MATCH", "Field": "databaseEngine", "Value": database_engine},
        {"Type": "TERM_MATCH", "Field": "deploymentOption", "Value": deployment_option},
        {"Type": "TERM_MATCH", "Field": "licenseModel", "Value": license_model},
    ]
    item = _get_products_single(pricing_client, "AmazonRDS", filters)
    if item is None:
        logger.warning(
            "No RDS pricing for instance_type=%s region=%s location=%s engine=%s",
            instance_type,
            region,
            location,
            database_engine,
        )
        cache.set(cache_key, 0.0)
        return 0.0
    price = _first_usd_from_price_list_json(item)
    cache.set(cache_key, price)
    return price


def get_ebs_volume_price(
    pricing_client: Any,
    cache: PricingCache,
    volume_api_name: str,
    region: str,
) -> float:
    """Return EBS volume price in USD per GB-month for the given volume API name."""
    location = pricing_location_for_region(region)
    cache_key = f"ebs|{volume_api_name}|{location}"
    hit = cache.get(cache_key)
    if hit is not None:
        return hit

    filters = [
        {"Type": "TERM_MATCH", "Field": "ServiceCode", "Value": "AmazonEC2"},
        {"Type": "TERM_MATCH", "Field": "productFamily", "Value": "Storage"},
        {"Type": "TERM_MATCH", "Field": "volumeApiName", "Value": volume_api_name},
        {"Type": "TERM_MATCH", "Field": "location", "Value": location},
    ]
    item = _get_products_single(pricing_client, "AmazonEC2", filters)
    if item is None:
        logger.warning(
            "No EBS pricing for volumeApiName=%s region=%s location=%s",
            volume_api_name,
            region,
            location,
        )
        cache.set(cache_key, 0.0)
        return 0.0
    price = _first_usd_from_price_list_json(item)
    cache.set(cache_key, price)
    return price


def _dispatch_pricing_job(
    job: Tuple[str, ...],
    pricing_client: Any,
    cache: PricingCache,
) -> float:
    """Run a single pricing job tuple."""
    kind = job[0]
    if kind == "ec2":
        _, instance_type, region = job
        return get_ec2_instance_price(pricing_client, cache, instance_type, region)
    if kind == "rds":
        if len(job) == 4:
            _, instance_type, region, engine = job
            return get_rds_instance_price(
                pricing_client, cache, instance_type, region, database_engine=engine
            )
        _, instance_type, region = job
        return get_rds_instance_price(pricing_client, cache, instance_type, region)
    if kind == "ebs":
        _, volume_api_name, region = job
        return get_ebs_volume_price(pricing_client, cache, volume_api_name, region)
    raise ValueError(f"Unknown pricing job kind: {kind!r}")


def batch_get_prices(
    pricing_client: Any,
    cache: PricingCache,
    jobs: Sequence[Tuple[str, ...]],
    *,
    max_workers: int = 10,
) -> List[float]:
    """Run independent pricing lookups in parallel (preserves order).

    Each ``job`` tuple starts with a kind:

    - ``("ec2", instance_type, region)``
    - ``("rds", instance_type, region)`` or ``("rds", instance_type, region, engine)``
    - ``("ebs", volume_api_name, region)`` (e.g. ``gp3``, ``gp2``)

    Args:
        pricing_client: boto3 ``pricing`` client (``us-east-1``).
        cache: Shared :class:`PricingCache` instance.
        jobs: Ordered job specifications.
        max_workers: Thread pool size.

    Returns:
        USD prices in the same order as ``jobs``.
    """
    job_list = list(jobs)
    if not job_list:
        return []

    def _run(j: Tuple[str, ...]) -> float:
        return _dispatch_pricing_job(j, pricing_client, cache)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        return list(pool.map(_run, job_list))
