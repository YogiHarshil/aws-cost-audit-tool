"""Tests for config loading, precedence, and parse_exclude_tags."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

import config as config_module
from config import Config, ConfigError, parse_exclude_tags


@pytest.fixture(autouse=True)
def _disable_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid loading the developer's real .env during tests."""
    monkeypatch.setattr(config_module, "load_dotenv", lambda *a, **k: None)


def _ns(**kwargs: object) -> Namespace:
    """Minimal argparse.Namespace with optional overrides."""
    base = {
        "profile": None,
        "region": None,
        "client_name": None,
        "skip_ai": False,
        "output": None,
        "exclude_tags": None,
        "verbose": False,
        "role_arn": None,
    }
    base.update(kwargs)
    return Namespace(**base)


def test_parse_exclude_tags_empty() -> None:
    assert parse_exclude_tags(None) == []
    assert parse_exclude_tags("") == []
    assert parse_exclude_tags("   ") == []


def test_parse_exclude_tags_single_and_multiple() -> None:
    assert parse_exclude_tags("Environment=Production") == [{"Environment": "Production"}]
    assert parse_exclude_tags("Environment=Production,Critical=true") == [
        {"Environment": "Production"},
        {"Critical": "true"},
    ]


def test_parse_exclude_tags_whitespace_and_skips() -> None:
    assert parse_exclude_tags(" Environment = Prod , Critical=true ") == [
        {"Environment": "Prod"},
        {"Critical": "true"},
    ]
    assert parse_exclude_tags("badsegment,Key=Value") == [{"Key": "Value"}]


def test_cli_profile_overrides_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AWS_PROFILE", "from-env")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setenv("OUTPUT_DIR", str(out))
    cfg = Config.from_env_and_args(_ns(profile="from-cli", skip_ai=True))
    assert cfg.aws_profile == "from-cli"


def test_env_client_name_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CLIENT_NAME", "EnvCo")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    out = tmp_path / "out2"
    out.mkdir()
    monkeypatch.setenv("OUTPUT_DIR", str(out))
    cfg = Config.from_env_and_args(_ns(skip_ai=True))
    assert cfg.client_name == "EnvCo"


def test_cli_client_name_overrides_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CLIENT_NAME", "EnvCo")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    out = tmp_path / "out3"
    out.mkdir()
    monkeypatch.setenv("OUTPUT_DIR", str(out))
    cfg = Config.from_env_and_args(_ns(client_name="CliCo", skip_ai=True))
    assert cfg.client_name == "CliCo"


def test_cli_exclude_tags_override_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EXCLUDE_TAGS", "Env=Prod")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    out = tmp_path / "out4"
    out.mkdir()
    monkeypatch.setenv("OUTPUT_DIR", str(out))
    cfg = Config.from_env_and_args(_ns(exclude_tags="Team=Cost", skip_ai=True))
    assert cfg.exclude_tags == [{"Team": "Cost"}]


def test_exclude_tags_from_env_when_cli_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("EXCLUDE_TAGS", "Env=Staging,Critical=true")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    out = tmp_path / "out5"
    out.mkdir()
    monkeypatch.setenv("OUTPUT_DIR", str(out))
    cfg = Config.from_env_and_args(_ns(skip_ai=True))
    assert cfg.exclude_tags == [{"Env": "Staging"}, {"Critical": "true"}]


def test_regions_from_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    out = tmp_path / "out6"
    out.mkdir()
    monkeypatch.setenv("OUTPUT_DIR", str(out))
    cfg = Config.from_env_and_args(_ns(region="us-east-1, eu-west-1 ", skip_ai=True))
    assert cfg.regions == ["us-east-1", "eu-west-1"]


def test_regions_from_env_var(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("REGIONS", "ap-south-1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    out = tmp_path / "out7"
    out.mkdir()
    monkeypatch.setenv("OUTPUT_DIR", str(out))
    cfg = Config.from_env_and_args(_ns(skip_ai=True))
    assert cfg.regions == ["ap-south-1"]


def test_openai_required_when_ai_enabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    out = tmp_path / "out8"
    out.mkdir()
    monkeypatch.setenv("OUTPUT_DIR", str(out))
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        Config.from_env_and_args(_ns(skip_ai=False))


def test_skip_ai_allows_missing_openai(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    out = tmp_path / "out9"
    out.mkdir()
    monkeypatch.setenv("OUTPUT_DIR", str(out))
    cfg = Config.from_env_and_args(_ns(skip_ai=True))
    assert cfg.openai_api_key is None
    assert cfg.skip_ai is True


def test_invalid_log_level(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOG_LEVEL", "SILLY")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    out = tmp_path / "out10"
    out.mkdir()
    monkeypatch.setenv("OUTPUT_DIR", str(out))
    with pytest.raises(ConfigError, match="Invalid LOG_LEVEL"):
        Config.from_env_and_args(_ns(skip_ai=True))


def test_verbose_forces_debug_log_level(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    out = tmp_path / "out11"
    out.mkdir()
    monkeypatch.setenv("OUTPUT_DIR", str(out))
    cfg = Config.from_env_and_args(_ns(skip_ai=True, verbose=True))
    assert cfg.log_level == "DEBUG"


def test_invalid_role_arn(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AWS_ROLE_ARN", "not-an-arn")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    out = tmp_path / "out12"
    out.mkdir()
    monkeypatch.setenv("OUTPUT_DIR", str(out))
    with pytest.raises(ConfigError, match="Invalid AWS_ROLE_ARN"):
        Config.from_env_and_args(_ns(skip_ai=True))


def test_valid_role_arn(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(
        "AWS_ROLE_ARN",
        "arn:aws:iam::123456789012:role/CostAudit/path",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    out = tmp_path / "out13"
    out.mkdir()
    monkeypatch.setenv("OUTPUT_DIR", str(out))
    cfg = Config.from_env_and_args(_ns(skip_ai=True))
    assert cfg.aws_role_arn.endswith("CostAudit/path")


def test_to_scan_config_round_trip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    out = tmp_path / "out14"
    out.mkdir()
    monkeypatch.setenv("OUTPUT_DIR", str(out))
    cfg = Config.from_env_and_args(_ns(skip_ai=True, profile="audit"))
    sc = cfg.to_scan_config()
    assert sc.aws_profile == "audit"
    assert sc.skip_ai is True
    assert sc.exclude_tags == []
    assert sc.openai_base_url is None
    assert sc.openai_model == "gpt-4o-mini"
    assert sc.openai_extra_body is None
    assert sc.openai_default_headers is None


def test_openrouter_reasoning_extra_body(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-or-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("OPENROUTER_REASONING", "true")
    out = tmp_path / "or2"
    out.mkdir()
    monkeypatch.setenv("OUTPUT_DIR", str(out))
    cfg = Config.from_env_and_args(_ns())
    assert cfg.openai_extra_body == {"reasoning": {"enabled": True}}
    sc = cfg.to_scan_config()
    assert sc.openai_extra_body == {"reasoning": {"enabled": True}}


def test_openai_extra_body_env_overrides_reasoning(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-or-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("OPENROUTER_REASONING", "true")
    monkeypatch.setenv("OPENAI_EXTRA_BODY", '{"reasoning": {"enabled": false}}')
    out = tmp_path / "or3"
    out.mkdir()
    monkeypatch.setenv("OUTPUT_DIR", str(out))
    cfg = Config.from_env_and_args(_ns())
    assert cfg.openai_extra_body == {"reasoning": {"enabled": False}}


def test_openrouter_default_headers_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENROUTER_HTTP_REFERER", "https://example.com/app")
    monkeypatch.setenv("OPENROUTER_APP_TITLE", "Cost Audit")
    out = tmp_path / "hdr"
    out.mkdir()
    monkeypatch.setenv("OUTPUT_DIR", str(out))
    cfg = Config.from_env_and_args(_ns(skip_ai=True))
    assert cfg.openai_default_headers == {
        "HTTP-Referer": "https://example.com/app",
        "X-Title": "Cost Audit",
    }


def test_invalid_openai_extra_body_not_object(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_EXTRA_BODY", "[1,2]")
    out = tmp_path / "bad2"
    out.mkdir()
    monkeypatch.setenv("OUTPUT_DIR", str(out))
    with pytest.raises(ConfigError, match="JSON object"):
        Config.from_env_and_args(_ns(skip_ai=True))


def test_invalid_openai_extra_body_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_EXTRA_BODY", "not-json")
    out = tmp_path / "bad"
    out.mkdir()
    monkeypatch.setenv("OUTPUT_DIR", str(out))
    with pytest.raises(ConfigError, match="OPENAI_EXTRA_BODY"):
        Config.from_env_and_args(_ns(skip_ai=True))


def test_openrouter_reasoning_ignored_without_openrouter_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENROUTER_REASONING", "true")
    out = tmp_path / "norouter"
    out.mkdir()
    monkeypatch.setenv("OUTPUT_DIR", str(out))
    cfg = Config.from_env_and_args(_ns(skip_ai=True))
    assert cfg.openai_extra_body is None
    monkeypatch.setenv("OPENAI_API_KEY", "sk-or-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("OPENAI_MODEL", "openai/gpt-4o-mini")
    out = tmp_path / "or"
    out.mkdir()
    monkeypatch.setenv("OUTPUT_DIR", str(out))
    cfg = Config.from_env_and_args(_ns())
    assert cfg.openai_base_url == "https://openrouter.ai/api/v1"
    assert cfg.openai_model == "openai/gpt-4o-mini"
    sc = cfg.to_scan_config()
    assert sc.openai_base_url == "https://openrouter.ai/api/v1"
    assert sc.openai_model == "openai/gpt-4o-mini"
