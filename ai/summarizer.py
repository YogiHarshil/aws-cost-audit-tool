"""OpenAI-backed executive summary and per-finding explanations."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from openai import OpenAI

from ai.prompts import EXECUTIVE_SUMMARY_PROMPT, FINDING_EXPLANATION_PROMPT
from models.finding import Finding

logger = logging.getLogger(__name__)

AI_SUMMARY_UNAVAILABLE = "AI summary unavailable"


class Summarizer:
    """Generate executive summaries and per-finding explanations via chat completions."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        base_url: Optional[str] = None,
        extra_body: Optional[Dict[str, Any]] = None,
        default_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        client_kw: Dict[str, Any] = {"api_key": api_key}
        if base_url:
            client_kw["base_url"] = base_url
        if default_headers:
            client_kw["default_headers"] = default_headers
        self._client = OpenAI(**client_kw)
        self._model = model
        self._extra_body = extra_body

    def _chat(self, system_prompt: str, user_content: str) -> str:
        try:
            create_kw: Dict[str, Any] = {
                "model": self._model,
                "temperature": 0.35,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
            }
            if self._extra_body:
                create_kw["extra_body"] = self._extra_body
            resp = self._client.chat.completions.create(**create_kw)
            choice = resp.choices[0].message
            text = (choice.content or "").strip()
            if not text:
                logger.warning("OpenAI returned empty content for summarizer call")
                return AI_SUMMARY_UNAVAILABLE
            return text
        except Exception as exc:
            logger.warning("OpenAI summarizer call failed: %s", exc, exc_info=True)
            return AI_SUMMARY_UNAVAILABLE

    def generate_executive_summary(
        self,
        findings: List[Finding],
        cost_trends: Dict[str, Any],
    ) -> str:
        payload = {
            "findings": [asdict(f) for f in findings],
            "cost_trends": cost_trends or {},
        }
        user = json.dumps(payload, default=str)
        return self._chat(EXECUTIVE_SUMMARY_PROMPT, user)

    def generate_finding_explanation(self, finding: Finding) -> str:
        user = json.dumps(asdict(finding), default=str)
        return self._chat(FINDING_EXPLANATION_PROMPT, user)
