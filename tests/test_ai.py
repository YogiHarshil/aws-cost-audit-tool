"""Tests for AI summarizer and recommender (OpenAI client mocked)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from ai.prompts import (
    EXECUTIVE_SUMMARY_PROMPT,
    FINDING_EXPLANATION_PROMPT,
    RECOMMENDATIONS_PROMPT,
)
from ai.recommender import Recommender
from ai.summarizer import AI_SUMMARY_UNAVAILABLE, Summarizer
from models.finding import Finding


def _sample_finding(**overrides: object) -> Finding:
    base = {
        "resource_id": "i-abc123",
        "resource_type": "EC2",
        "region": "us-east-1",
        "issue_type": "stopped",
        "description": "Stopped 10 days",
        "monthly_savings": 50.0,
        "severity": "High",
        "details": {"instance_type": "t3.medium"},
    }
    base.update(overrides)
    return Finding(**base)  # type: ignore[arg-type]


def _mock_completion(text: str) -> MagicMock:
    msg = MagicMock()
    msg.content = text
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


@patch("ai.summarizer.OpenAI")
def test_generate_executive_summary_sends_findings_json(mock_openai: MagicMock) -> None:
    mock_client = MagicMock()
    mock_openai.return_value = mock_client
    mock_client.chat.completions.create.return_value = _mock_completion(
        "Total waste is significant across EC2 and RDS."
    )
    findings = [_sample_finding()]
    trends = {"month_over_month_change": 12.5, "top_services": [{"service": "EC2", "cost": 100.0}]}

    s = Summarizer("sk-test")
    out = s.generate_executive_summary(findings, trends)

    assert out == "Total waste is significant across EC2 and RDS."
    mock_client.chat.completions.create.assert_called_once()
    kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "gpt-4o-mini"
    msgs = kwargs["messages"]
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == EXECUTIVE_SUMMARY_PROMPT
    user = msgs[1]["content"]
    assert "i-abc123" in user
    assert "month_over_month_change" in user


@patch("ai.summarizer.OpenAI")
def test_generate_finding_explanation_uses_finding_prompt(mock_openai: MagicMock) -> None:
    mock_client = MagicMock()
    mock_openai.return_value = mock_client
    mock_client.chat.completions.create.return_value = _mock_completion(
        "This instance is idle cost. Consider terminating."
    )
    f = _sample_finding(resource_id="i-xyz")

    s = Summarizer("sk-test")
    out = s.generate_finding_explanation(f)

    assert "idle cost" in out
    msgs = mock_client.chat.completions.create.call_args.kwargs["messages"]
    assert msgs[0]["content"] == FINDING_EXPLANATION_PROMPT
    assert "i-xyz" in msgs[1]["content"]


@patch("ai.summarizer.OpenAI")
def test_summarizer_openai_error_returns_unavailable(mock_openai: MagicMock) -> None:
    mock_client = MagicMock()
    mock_openai.return_value = mock_client
    mock_client.chat.completions.create.side_effect = RuntimeError("rate limited")

    s = Summarizer("sk-test")
    assert s.generate_executive_summary([_sample_finding()], {}) == AI_SUMMARY_UNAVAILABLE
    assert s.generate_finding_explanation(_sample_finding()) == AI_SUMMARY_UNAVAILABLE


@patch("ai.summarizer.OpenAI")
def test_summarizer_empty_content_returns_unavailable(mock_openai: MagicMock) -> None:
    mock_client = MagicMock()
    mock_openai.return_value = mock_client
    resp = MagicMock()
    msg = MagicMock()
    msg.content = None
    choice = MagicMock()
    choice.message = msg
    resp.choices = [choice]
    mock_client.chat.completions.create.return_value = resp

    s = Summarizer("sk-test")
    assert s.generate_finding_explanation(_sample_finding()) == AI_SUMMARY_UNAVAILABLE


@patch("ai.recommender.OpenAI")
def test_recommender_returns_parsed_list(mock_openai: MagicMock) -> None:
    payload = {
        "recommendations": [
            {
                "title": "Stop idle DB",
                "impact": 99.5,
                "difficulty": "Low",
                "description": "Scale down RDS.",
            },
            {
                "title": "Second",
                "impact": 10,
                "difficulty": "Medium",
                "description": "Do thing",
            },
        ]
    }
    mock_client = MagicMock()
    mock_openai.return_value = mock_client
    mock_client.chat.completions.create.return_value = _mock_completion(json.dumps(payload))

    r = Recommender("sk-test")
    recs = r.generate_top_5_recommendations([_sample_finding(), _sample_finding(resource_id="i-2")])

    assert len(recs) == 2
    assert recs[0]["title"] == "Stop idle DB"
    assert recs[0]["impact"] == pytest.approx(99.5)
    assert recs[0]["difficulty"] == "Low"
    kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert kwargs["response_format"] == {"type": "json_object"}
    assert kwargs["messages"][0]["content"] == RECOMMENDATIONS_PROMPT


@patch("ai.recommender.OpenAI")
def test_recommender_api_failure_returns_fallback(mock_openai: MagicMock) -> None:
    mock_client = MagicMock()
    mock_openai.return_value = mock_client
    mock_client.chat.completions.create.side_effect = OSError("network")

    r = Recommender("sk-test")
    recs = r.generate_top_5_recommendations([_sample_finding()])

    assert len(recs) == 1
    assert recs[0]["description"] == AI_SUMMARY_UNAVAILABLE


@patch("ai.recommender.OpenAI")
def test_recommender_invalid_json_returns_fallback(mock_openai: MagicMock) -> None:
    mock_client = MagicMock()
    mock_openai.return_value = mock_client
    mock_client.chat.completions.create.return_value = _mock_completion("not json")

    r = Recommender("sk-test")
    recs = r.generate_top_5_recommendations([_sample_finding()])
    assert recs[0]["title"] == "Recommendations unavailable"


def test_recommender_empty_findings() -> None:
    with patch("ai.recommender.OpenAI"):
        r = Recommender("sk-test")
    assert r.generate_top_5_recommendations([]) == []
