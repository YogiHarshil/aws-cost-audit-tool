"""OpenAI-backed top-5 prioritized recommendations."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from openai import OpenAI

from ai.prompts import RECOMMENDATIONS_PROMPT
from ai.summarizer import AI_SUMMARY_UNAVAILABLE
from models.finding import Finding

logger = logging.getLogger(__name__)


def _fallback_recommendations() -> List[Dict[str, Any]]:
    return [
        {
            "title": "Recommendations unavailable",
            "impact": 0.0,
            "difficulty": "Low",
            "description": AI_SUMMARY_UNAVAILABLE,
        }
    ]


class Recommender:
    """Produce top 5 recommendations from findings (JSON mode)."""

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

    def generate_top_5_recommendations(self, findings: List[Finding]) -> List[Dict[str, Any]]:
        if not findings:
            return []

        user = json.dumps({"findings": [asdict(f) for f in findings]}, default=str)
        try:
            create_kw: Dict[str, Any] = {
                "model": self._model,
                "temperature": 0.35,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": RECOMMENDATIONS_PROMPT},
                    {"role": "user", "content": user},
                ],
            }
            if self._extra_body:
                create_kw["extra_body"] = self._extra_body
            resp = self._client.chat.completions.create(**create_kw)
            raw = (resp.choices[0].message.content or "").strip()
            if not raw:
                logger.warning("OpenAI returned empty recommendations payload")
                return _fallback_recommendations()
            data = json.loads(raw)
            recs = data.get("recommendations")
            if not isinstance(recs, list):
                return _fallback_recommendations()
            normalized: List[Dict[str, Any]] = []
            for item in recs[:5]:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title", "")).strip() or "Untitled action"
                desc = str(item.get("description", "")).strip() or AI_SUMMARY_UNAVAILABLE
                diff = str(item.get("difficulty", "Medium"))
                if diff not in ("Low", "Medium", "High"):
                    diff = "Medium"
                try:
                    impact = float(item.get("impact", 0.0))
                except (TypeError, ValueError):
                    impact = 0.0
                normalized.append(
                    {
                        "title": title,
                        "impact": impact,
                        "difficulty": diff,
                        "description": desc,
                    }
                )
            if not normalized:
                return _fallback_recommendations()
            return normalized[:5]
        except Exception as exc:
            logger.warning("OpenAI recommender call failed: %s", exc, exc_info=True)
            return _fallback_recommendations()
