"""Load and validate application configuration from environment and CLI."""

from __future__ import annotations

import json
import logging
import os
import re
from argparse import Namespace
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from models.report import ScanConfig

logger = logging.getLogger(__name__)

_VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
_ROLE_ARN_PATTERN = re.compile(r"^arn:aws:iam::\d{12}:role/.+$")


class ConfigError(ValueError):
    """Raised when configuration is invalid or inconsistent."""


def parse_exclude_tags(raw: Optional[str]) -> List[Dict[str, str]]:
    """Parse comma-separated ``Key=Value`` pairs into tag match dicts.

    Each returned dict has exactly one key (the tag key) mapping to the tag
    value. Scanners treat this as OR logic: a resource is excluded if **any**
    pair matches one of its tags (case-sensitive exact match per contract).

    Args:
        raw: String from ``EXCLUDE_TAGS`` or ``--exclude-tags``, or None.

    Returns:
        List of one-entry dicts, e.g. ``[{"Environment": "Production"}]``.
        Empty or whitespace-only input yields ``[]``.
    """
    if raw is None or not str(raw).strip():
        return []

    result: List[Dict[str, str]] = []
    for segment in str(raw).split(","):
        segment = segment.strip()
        if not segment:
            continue
        if "=" not in segment:
            logger.warning("Skipping invalid exclude tag segment (missing '='): %r", segment)
            continue
        key, value = segment.split("=", 1)
        key, value = key.strip(), value.strip()
        if not key:
            logger.warning("Skipping exclude tag with empty key: %r", segment)
            continue
        result.append({key: value})
    return result


def _cli_first(cli_args: Optional[Namespace], attr: str) -> Optional[str]:
    """Return CLI attribute if set and non-empty string."""
    if cli_args is None:
        return None
    if not hasattr(cli_args, attr):
        return None
    val = getattr(cli_args, attr)
    if val is None:
        return None
    if isinstance(val, str) and not val.strip():
        return None
    if isinstance(val, bool):
        return None  # booleans handled elsewhere
    return val


def _merge_str(
    cli_args: Optional[Namespace],
    cli_attr: str,
    env_name: str,
    default: str,
) -> str:
    """Precedence: CLI string > environment > default."""
    cli_val = _cli_first(cli_args, cli_attr)
    if cli_val is not None:
        return str(cli_val).strip()
    env_val = os.getenv(env_name)
    if env_val is not None and str(env_val).strip():
        return str(env_val).strip()
    return default


def _merge_optional_str(
    cli_args: Optional[Namespace],
    cli_attr: str,
    env_name: str,
) -> Optional[str]:
    """CLI string > environment > None."""
    cli_val = _cli_first(cli_args, cli_attr)
    if cli_val is not None:
        return str(cli_val).strip()
    env_val = os.getenv(env_name)
    if env_val is not None and str(env_val).strip():
        return str(env_val).strip()
    return None


def _parse_json_object_env(name: str) -> Optional[Dict[str, Any]]:
    """Parse ``name`` as a JSON object, or return ``None`` if unset/blank."""
    raw = os.getenv(name)
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        obj = json.loads(s)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{name} must be valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise ConfigError(f"{name} must be a JSON object (got {type(obj).__name__})")
    return obj


def _openrouter_reasoning_extra_body(openai_base_url: Optional[str]) -> Optional[Dict[str, Any]]:
    """If ``OPENROUTER_REASONING`` is truthy and base URL looks like OpenRouter, enable reasoning."""
    flag = (os.getenv("OPENROUTER_REASONING") or "").strip().lower()
    if flag not in ("1", "true", "yes", "on"):
        return None
    base = (openai_base_url or "").lower()
    if "openrouter.ai" not in base:
        logger.debug(
            "OPENROUTER_REASONING is set but OPENAI_BASE_URL does not look like OpenRouter; "
            "not adding reasoning extra_body"
        )
        return None
    return {"reasoning": {"enabled": True}}


def _openai_default_headers_from_env() -> Optional[Dict[str, str]]:
    """Optional OpenRouter leaderboard headers (HTTP-Referer, X-Title)."""
    referer = (
        os.getenv("OPENROUTER_HTTP_REFERER")
        or os.getenv("OPENROUTER_SITE_URL")
        or ""
    ).strip()
    title = (
        os.getenv("OPENROUTER_APP_TITLE")
        or os.getenv("OPENROUTER_X_TITLE")
        or ""
    ).strip()
    headers: Dict[str, str] = {}
    if referer:
        headers["HTTP-Referer"] = referer
    if title:
        headers["X-Title"] = title
    return headers or None


def _parse_regions_arg(value: Optional[str]) -> Optional[List[str]]:
    """Split comma-separated regions into a list, or None if unset."""
    if value is None or not str(value).strip():
        return None
    parts = [p.strip() for p in str(value).split(",") if p.strip()]
    return parts or None


@dataclass
class Config:
    """Merged CLI + ``.env`` configuration for the audit tool."""

    aws_profile: str
    aws_role_arn: Optional[str]
    regions: Optional[List[str]]
    client_name: str
    openai_api_key: Optional[str]
    openai_base_url: Optional[str]
    openai_model: str
    openai_extra_body: Optional[Dict[str, Any]]
    openai_default_headers: Optional[Dict[str, str]]
    skip_ai: bool
    output_dir: str
    exclude_tags: List[Dict[str, str]]
    log_level: str
    verbose: bool
    max_workers: int  # ThreadPool workers for parallel scanning

    @classmethod
    def from_env_and_args(
        cls,
        cli_args: Optional[Namespace] = None,
        *,
        dotenv_path: Optional[str] = None,
    ) -> Config:
        """Build configuration: load ``.env``, then apply CLI overrides.

        Args:
            cli_args: Parsed ``argparse.Namespace`` from ``main`` (optional).
            dotenv_path: Optional explicit path to a ``.env`` file.

        Returns:
            Validated :class:`Config`.

        Raises:
            ConfigError: On invalid combinations or formats.
        """
        load_dotenv(dotenv_path, override=False)

        skip_ai = bool(cli_args and getattr(cli_args, "skip_ai", False))

        aws_profile = _merge_str(cli_args, "profile", "AWS_PROFILE", "default")
        aws_role_arn = _merge_optional_str(cli_args, "role_arn", "AWS_ROLE_ARN")

        if aws_role_arn and not _ROLE_ARN_PATTERN.match(aws_role_arn):
            raise ConfigError(
                f"Invalid AWS_ROLE_ARN format: {aws_role_arn!r}. "
                "Expected arn:aws:iam::<12-digit-account>:role/<role-name>"
            )

        regions_cli = _cli_first(cli_args, "region")
        regions = _parse_regions_arg(regions_cli) if regions_cli else _parse_regions_arg(
            os.getenv("REGIONS") or os.getenv("AWS_REGIONS")
        )

        client_name = _merge_str(cli_args, "client_name", "CLIENT_NAME", "Client")
        output_dir = _merge_str(cli_args, "output", "OUTPUT_DIR", "./output")

        exclude_raw = _cli_first(cli_args, "exclude_tags")
        if exclude_raw is not None:
            exclude_tags = parse_exclude_tags(exclude_raw)
        else:
            exclude_tags = parse_exclude_tags(os.getenv("EXCLUDE_TAGS"))

        openai_api_key = os.getenv("OPENAI_API_KEY")
        if openai_api_key is not None:
            openai_api_key = openai_api_key.strip() or None

        openai_base_url = os.getenv("OPENAI_BASE_URL")
        if openai_base_url is not None:
            openai_base_url = openai_base_url.strip() or None

        openai_model = (os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip() or "gpt-4o-mini"

        openai_extra_body = _parse_json_object_env("OPENAI_EXTRA_BODY")
        if openai_extra_body is None:
            openai_extra_body = _openrouter_reasoning_extra_body(openai_base_url)
        openai_default_headers = _openai_default_headers_from_env()

        verbose = bool(cli_args and getattr(cli_args, "verbose", False))
        if verbose:
            log_level = "DEBUG"
        else:
            log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
            if log_level not in _VALID_LOG_LEVELS:
                raise ConfigError(
                    f"Invalid LOG_LEVEL: {log_level!r}. "
                    f"Must be one of: {', '.join(sorted(_VALID_LOG_LEVELS))}"
                )

        if not skip_ai and not openai_api_key:
            raise ConfigError(
                "OPENAI_API_KEY required when AI summaries are enabled. "
                "Set the key in .env or pass --skip-ai."
            )

        # MAX_WORKERS for parallel scanning (default 5, safer for large accounts)
        max_workers_raw = os.getenv("MAX_WORKERS", "5")
        try:
            max_workers = max(1, min(20, int(max_workers_raw)))
        except ValueError:
            max_workers = 5

        cfg = cls(
            aws_profile=aws_profile,
            aws_role_arn=aws_role_arn,
            regions=regions,
            client_name=client_name,
            openai_api_key=openai_api_key,
            openai_base_url=openai_base_url,
            openai_model=openai_model,
            openai_extra_body=openai_extra_body,
            openai_default_headers=openai_default_headers,
            skip_ai=skip_ai,
            output_dir=output_dir,
            exclude_tags=exclude_tags,
            log_level=log_level,
            verbose=verbose,
            max_workers=max_workers,
        )
        cfg._ensure_output_dir()
        return cfg

    def _ensure_output_dir(self) -> None:
        """Create output directory if missing (same behavior as :class:`ScanConfig`)."""
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir, exist_ok=True)

    def to_scan_config(self) -> ScanConfig:
        """Convert to :class:`ScanConfig` used by scanners and reports."""
        return ScanConfig(
            aws_profile=self.aws_profile,
            aws_role_arn=self.aws_role_arn,
            regions=self.regions,
            client_name=self.client_name,
            openai_api_key=self.openai_api_key,
            openai_base_url=self.openai_base_url,
            openai_model=self.openai_model,
            openai_extra_body=self.openai_extra_body,
            openai_default_headers=self.openai_default_headers,
            skip_ai=self.skip_ai,
            output_dir=self.output_dir,
            exclude_tags=list(self.exclude_tags),
            verbose=self.verbose,
            max_workers=self.max_workers,
        )
