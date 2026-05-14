"""Base scanner with tag exclusion helpers and safe AWS pagination."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Iterator, List, Optional, Tuple

from models.finding import Finding

logger = logging.getLogger(__name__)


def exclude_tag_pairs_from_config(exclude_tags: Optional[List[Dict[str, str]]]) -> List[Tuple[str, str]]:
    """Normalize exclude tag entries to (key, value) pairs.

    Supports either ``{"Key": "k", "Value": "v"}`` (spec style) or a single-key
    dict ``{"k": "v"}`` (as produced by :func:`config.parse_exclude_tags`).
    """
    pairs: List[Tuple[str, str]] = []
    if not exclude_tags:
        return pairs
    for entry in exclude_tags:
        if "Key" in entry and "Value" in entry:
            pairs.append((str(entry["Key"]), str(entry["Value"])))
        else:
            for k, v in entry.items():
                pairs.append((str(k), str(v)))
    return pairs


def should_exclude_by_tags(
    aws_tags: Optional[List[Dict[str, str]]],
    exclude_pairs: List[Tuple[str, str]],
) -> bool:
    """Return True if this resource must be skipped (OR match on any filter pair).

    Resources with **no** tags are never excluded (per product contract).
    """
    if not exclude_pairs:
        return False
    if not aws_tags:
        return False
    tag_map = {t.get("Key", ""): t.get("Value", "") for t in aws_tags if t.get("Key")}
    for key, val in exclude_pairs:
        if tag_map.get(key) == val:
            logger.debug("Resource excluded by tag %s=%s", key, val)
            return True
    return False


class BaseScanner(ABC):
    """Shared context for regional resource scanners."""

    def __init__(
        self,
        session: Any,
        region: str,
        exclude_tags: Optional[List[Dict[str, str]]],
        pricing_client: Any,
        pricing_cache: Any,
    ) -> None:
        self.session = session
        self.region = region
        self.exclude_pairs = exclude_tag_pairs_from_config(exclude_tags)
        self.pricing_client = pricing_client
        self.pricing_cache = pricing_cache

    def _tags_excluded(self, aws_tags: Optional[List[Dict[str, str]]]) -> bool:
        return should_exclude_by_tags(aws_tags, self.exclude_pairs)

    @staticmethod
    def paginate(operation: Any, **kwargs: Any) -> Iterator[Dict[str, Any]]:
        """Yield pages from a boto3 paginator (swallows iterator setup errors)."""
        paginator = operation.paginate(**kwargs)
        yield from paginator

    @abstractmethod
    def scan(self) -> List[Finding]:
        """Run the scanner in ``self.region`` and return findings."""
