"""End-to-end and CLI tests (AWS, OpenAI, and heavy PDF paths mocked)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import config as config_module
import main


@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config_module, "load_dotenv", lambda *a, **k: None)


def _fake_boto_session() -> MagicMock:
    """Minimal session so all regional scanners and CE return empty results."""

    def empty_paginator() -> MagicMock:
        p = MagicMock()
        p.paginate.return_value = iter([])
        return p

    def client(service_name: str, region_name: str | None = None, **kwargs: object) -> MagicMock:
        c = MagicMock()
        if service_name == "sts":
            c.get_caller_identity.return_value = {"Account": "123456789012", "Arn": "arn:x", "UserId": "u"}
        elif service_name == "iam":
            c.list_account_aliases.return_value = {"AccountAliases": ["demo-alias"]}
        elif service_name == "pricing":
            c.get_products.return_value = {"PriceList": [], "NextToken": None}
        elif service_name == "ec2":
            c.get_paginator.return_value = empty_paginator()
        elif service_name == "rds":
            c.get_paginator.return_value = empty_paginator()
            c.list_tags_for_resource.return_value = {"TagList": []}
        elif service_name == "cloudwatch":
            c.get_metric_statistics.return_value = {"Datapoints": []}
        elif service_name == "s3":
            c.list_buckets.return_value = {"Buckets": []}
        elif service_name == "ce":
            c.get_cost_and_usage.return_value = {"ResultsByTime": []}
        return c

    session = MagicMock()
    session.client.side_effect = client
    return session


def test_parse_args_region_and_flags() -> None:
    args = main.parse_args(
        ["--profile", "p1", "--region", "us-east-1,eu-west-1", "--skip-ai", "--verbose", "--output", "/tmp/out"]
    )
    assert args.profile == "p1"
    assert args.region == "us-east-1,eu-west-1"
    assert args.skip_ai is True
    assert args.verbose is True
    assert args.output == "/tmp/out"


def test_main_config_error_missing_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    code = main.main(["--profile", "x"])
    assert code == 1


def test_main_skip_ai_happy_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(main, "create_session", lambda *a, **k: _fake_boto_session())
    monkeypatch.setattr(main, "discover_regions", lambda session, partition_name="aws": ["us-east-1"])

    written: dict[str, Path] = {}

    def fake_pdf(html: str, path: Path) -> Path:
        p = Path(path)
        p.write_bytes(b"%PDF-1.4 test")
        written["path"] = p
        return p

    monkeypatch.setattr(main, "generate_pdf", fake_pdf)

    code = main.main(["--skip-ai", "--output", str(tmp_path), "--client-name", "E2E Co"])
    assert code == 0
    assert written["path"].exists()
    assert written["path"].name.startswith("aws_audit_123456789012_")


def test_main_ai_partial_exit_on_apply_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy")
    monkeypatch.setattr(main, "create_session", lambda *a, **k: _fake_boto_session())
    monkeypatch.setattr(main, "discover_regions", lambda session, partition_name="aws": ["us-east-1"])

    def boom_ai(report: object, scan_cfg: object) -> None:
        raise RuntimeError("simulated AI failure")

    monkeypatch.setattr(main, "apply_ai_to_report", boom_ai)

    def fake_pdf(html: str, path: Path) -> Path:
        p = Path(path)
        p.write_bytes(b"%PDF-1.4")
        return p

    monkeypatch.setattr(main, "generate_pdf", fake_pdf)

    code = main.main(["--output", str(tmp_path), "--client-name", "AI Fail Co"])
    assert code == 3


def test_main_partial_exit_on_scan_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def boom_scan(self: object) -> list:
        raise RuntimeError("simulated regional failure")

    monkeypatch.setattr(main, "create_session", lambda *a, **k: _fake_boto_session())
    monkeypatch.setattr(main, "discover_regions", lambda session, partition_name="aws": ["us-east-1"])
    monkeypatch.setattr("scanners.ec2.EC2Scanner.scan", boom_scan)

    def fake_pdf(html: str, path: Path) -> Path:
        p = Path(path)
        p.write_bytes(b"%PDF-1.4")
        return p

    monkeypatch.setattr(main, "generate_pdf", fake_pdf)

    code = main.main(["--skip-ai", "--output", str(tmp_path)])
    assert code == 2


def test_main_critical_on_session_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(main, "create_session", MagicMock(side_effect=RuntimeError("no creds")))
    code = main.main(["--skip-ai", "--output", str(tmp_path)])
    assert code == 1


def test_run_audit_invokes_ai_when_key_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy")
    monkeypatch.setattr(main, "create_session", lambda *a, **k: _fake_boto_session())
    monkeypatch.setattr(main, "discover_regions", lambda session, partition_name="aws": ["us-east-1"])

    def fake_apply(report: object, scan_cfg: object) -> None:
        report.executive_summary = "ok"
        report.recommendations = []

    monkeypatch.setattr(main, "apply_ai_to_report", fake_apply)

    def fake_pdf(html: str, path: Path) -> Path:
        p = Path(path)
        p.write_bytes(b"%PDF-1.4")
        return p

    monkeypatch.setattr(main, "generate_pdf", fake_pdf)

    cfg = config_module.Config.from_env_and_args(
        main.parse_args(["--output", str(tmp_path), "--client-name", "AI Co"])
    )
    assert cfg.skip_ai is False
    code = main.run_audit(cfg)
    assert code == 0


def test_config_precedence_cli_output_over_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    out_a.mkdir()
    out_b.mkdir()
    monkeypatch.setenv("OUTPUT_DIR", str(out_a))
    cfg = config_module.Config.from_env_and_args(
        main.parse_args(["--skip-ai", "--output", str(out_b), "--client-name", "x"])
    )
    assert cfg.output_dir == str(out_b)
