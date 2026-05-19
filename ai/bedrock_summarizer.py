"""AWS Bedrock-backed executive summary and per-finding explanations.

Uses AWS Bedrock for AI summaries. Can use a SEPARATE AWS account for Bedrock
while scanning a different client account.

Authentication Options:
1. BEDROCK_API_KEY: Direct API key from AWS Bedrock console (base64 encoded)
2. BEDROCK_PROFILE: AWS profile with Bedrock access

Cross-Account Setup:
- BEDROCK_PROFILE: Your AWS profile with Bedrock access (YOUR account)
- AWS_PROFILE: Client's AWS profile for scanning (CLIENT account)

This allows you to:
1. Scan client's AWS account for cost waste
2. Use YOUR Bedrock access to generate AI summaries
3. Client doesn't need Bedrock enabled
4. You pay for Bedrock, not the client

Supported models (from cheapest to most capable):
- anthropic.claude-3-haiku-20240307-v1:0: Fast, cheap ($0.00025/$0.00125 per 1K)
- anthropic.claude-instant-v1: Good quality/price ratio
- amazon.titan-text-express-v1: AWS native, cheap
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import asdict
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

from ai.prompts import EXECUTIVE_SUMMARY_PROMPT, FINDING_EXPLANATION_PROMPT
from models.finding import Finding

logger = logging.getLogger(__name__)

AI_SUMMARY_UNAVAILABLE = "AI summary unavailable"

# Default to Claude 3 Haiku - best quality/price ratio
DEFAULT_MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"

# Fallback models if primary not available
FALLBACK_MODELS = [
    "anthropic.claude-instant-v1",
    "amazon.titan-text-express-v1",
    "amazon.titan-text-lite-v1",
]


def create_session_from_api_key(api_key: str, region: str = "us-east-1") -> boto3.Session:
    """Create boto3 session from Bedrock API key.

    Bedrock API keys from AWS console are base64 encoded with a 3-byte binary header:
    [0x00 0x14 0x8a] + "BedrockAPIKey-{key-id}-at-{account-id}:{secret-key}"

    Args:
        api_key: Base64 encoded Bedrock API key from AWS console
        region: AWS region for Bedrock

    Returns:
        boto3.Session configured with the API key credentials
    """
    try:
        # Decode base64 API key
        decoded_bytes = base64.b64decode(api_key)

        # Skip binary header (3 bytes) and decode as UTF-8
        # Header is: 0x00 0x14 0x8a (ABSK prefix in base64)
        # Look for 'Bedrock' marker to find start of actual key
        bedrock_idx = decoded_bytes.find(b"Bedrock")
        if bedrock_idx < 0:
            raise ValueError("Invalid API key - missing Bedrock marker")

        key_data = decoded_bytes[bedrock_idx:].decode("utf-8")

        # Parse format: BedrockAPIKey-{key-id}-at-{account}:{secret}
        if ":" not in key_data:
            raise ValueError("Invalid API key format - missing separator")

        key_part, secret_key = key_data.rsplit(":", 1)

        # For boto3, we use the key part as access key ID
        # This is a Bedrock-specific credential type
        access_key_id = key_part

        logger.info("Creating Bedrock session from API key (key: %s...)", key_part[:30])

        return boto3.Session(
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_key,
            region_name=region,
        )
    except Exception as exc:
        logger.error("Failed to parse Bedrock API key: %s", exc)
        raise ValueError(f"Invalid BEDROCK_API_KEY format: {exc}") from exc


class BedrockSummarizer:
    """Generate executive summaries and per-finding explanations via AWS Bedrock."""

    def __init__(
        self,
        session: Optional[Any] = None,
        model_id: str = DEFAULT_MODEL_ID,
        region: str = "us-east-1",
    ) -> None:
        """Initialize Bedrock summarizer.

        Args:
            session: boto3 session (uses default if not provided)
            model_id: Bedrock model ID to use
            region: AWS region for Bedrock (us-east-1 has most models)
        """
        if session is None:
            session = boto3.Session()

        self._client = session.client("bedrock-runtime", region_name=region)
        self._model_id = model_id
        self._region = region

    def _invoke_model(self, system_prompt: str, user_content: str) -> str:
        """Invoke Bedrock model with system and user prompts."""
        try:
            # Determine model family for correct request format
            if "anthropic" in self._model_id.lower():
                return self._invoke_claude(system_prompt, user_content)
            elif "titan" in self._model_id.lower():
                return self._invoke_titan(system_prompt, user_content)
            else:
                # Default to Claude format
                return self._invoke_claude(system_prompt, user_content)

        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code == "ValidationException":
                logger.warning("Model %s not available, trying fallback", self._model_id)
                return self._try_fallback_models(system_prompt, user_content)
            logger.warning("Bedrock invoke failed: %s", exc)
            return AI_SUMMARY_UNAVAILABLE
        except Exception as exc:
            logger.warning("Bedrock summarizer call failed: %s", exc, exc_info=True)
            return AI_SUMMARY_UNAVAILABLE

    def _invoke_claude(self, system_prompt: str, user_content: str) -> str:
        """Invoke Anthropic Claude model on Bedrock."""
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1024,
            "temperature": 0.3,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": user_content}
            ],
        }

        response = self._client.invoke_model(
            modelId=self._model_id,
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json",
        )

        response_body = json.loads(response["body"].read())
        content = response_body.get("content", [])
        if content and len(content) > 0:
            return content[0].get("text", AI_SUMMARY_UNAVAILABLE)
        return AI_SUMMARY_UNAVAILABLE

    def _invoke_titan(self, system_prompt: str, user_content: str) -> str:
        """Invoke Amazon Titan model on Bedrock."""
        # Titan uses a different format
        combined_prompt = f"{system_prompt}\n\nUser: {user_content}\n\nAssistant:"

        body = {
            "inputText": combined_prompt,
            "textGenerationConfig": {
                "maxTokenCount": 1024,
                "temperature": 0.3,
                "topP": 0.9,
            },
        }

        response = self._client.invoke_model(
            modelId=self._model_id,
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json",
        )

        response_body = json.loads(response["body"].read())
        results = response_body.get("results", [])
        if results and len(results) > 0:
            return results[0].get("outputText", AI_SUMMARY_UNAVAILABLE)
        return AI_SUMMARY_UNAVAILABLE

    def _try_fallback_models(self, system_prompt: str, user_content: str) -> str:
        """Try fallback models if primary model is unavailable."""
        for fallback_id in FALLBACK_MODELS:
            try:
                logger.info("Trying fallback model: %s", fallback_id)
                self._model_id = fallback_id
                if "anthropic" in fallback_id.lower():
                    return self._invoke_claude(system_prompt, user_content)
                else:
                    return self._invoke_titan(system_prompt, user_content)
            except Exception:
                continue
        return AI_SUMMARY_UNAVAILABLE

    def generate_executive_summary(
        self,
        findings: List[Finding],
        cost_trends: Dict[str, Any],
    ) -> str:
        """Generate executive summary for all findings."""
        payload = {
            "findings": [asdict(f) for f in findings],
            "cost_trends": cost_trends or {},
        }
        user_content = json.dumps(payload, default=str)
        return self._invoke_model(EXECUTIVE_SUMMARY_PROMPT, user_content)

    def generate_finding_explanation(self, finding: Finding) -> str:
        """Generate AI explanation for a single finding."""
        user_content = json.dumps(asdict(finding), default=str)
        return self._invoke_model(FINDING_EXPLANATION_PROMPT, user_content)


class BedrockRecommender:
    """Generate top 5 recommendations using AWS Bedrock."""

    RECOMMENDATION_PROMPT = """You are an AWS cost optimization expert. Based on the findings provided, generate exactly 5 prioritized recommendations.

Output JSON only, with this exact structure:
{
  "recommendations": [
    {
      "title": "Short action title",
      "impact": 123.45,
      "difficulty": "Low|Medium|High",
      "description": "2-3 sentence description of what to do and why"
    }
  ]
}

Rules:
- Exactly 5 recommendations
- Sort by impact (highest first)
- impact is monthly USD savings (number)
- difficulty reflects implementation effort
- Be specific and actionable
- Only recommend based on actual findings (don't invent)"""

    def __init__(
        self,
        session: Optional[Any] = None,
        model_id: str = DEFAULT_MODEL_ID,
        region: str = "us-east-1",
    ) -> None:
        if session is None:
            session = boto3.Session()

        self._client = session.client("bedrock-runtime", region_name=region)
        self._model_id = model_id

    def generate_top_5_recommendations(
        self, findings: List[Finding]
    ) -> List[Dict[str, Any]]:
        """Generate top 5 recommendations based on findings."""
        if not findings:
            return []

        payload = {"findings": [asdict(f) for f in findings]}
        user_content = json.dumps(payload, default=str)

        try:
            body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1024,
                "temperature": 0.3,
                "system": self.RECOMMENDATION_PROMPT,
                "messages": [
                    {"role": "user", "content": user_content}
                ],
            }

            response = self._client.invoke_model(
                modelId=self._model_id,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )

            response_body = json.loads(response["body"].read())
            content = response_body.get("content", [])
            if not content:
                return self._fallback_recommendations()

            text = content[0].get("text", "")

            # Parse JSON from response
            # Find JSON in the response (may have markdown code blocks)
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]

            data = json.loads(text.strip())
            return data.get("recommendations", [])[:5]

        except Exception as exc:
            logger.warning("Bedrock recommender failed: %s", exc)
            return self._fallback_recommendations()

    def _fallback_recommendations(self) -> List[Dict[str, Any]]:
        """Return empty recommendations if Bedrock fails."""
        return [
            {
                "title": "Review findings manually",
                "impact": 0.0,
                "difficulty": "Low",
                "description": "AI recommendations unavailable. Please review findings above.",
            }
        ]


def check_bedrock_access(session: Optional[Any] = None, region: str = "us-east-1") -> bool:
    """Check if Bedrock is accessible with current credentials."""
    try:
        if session is None:
            session = boto3.Session()
        client = session.client("bedrock", region_name=region)
        # List foundation models to verify access
        client.list_foundation_models(byOutputModality="TEXT")
        return True
    except ClientError as exc:
        logger.warning("Bedrock access check failed: %s", exc)
        return False
    except Exception as exc:
        logger.warning("Bedrock access check error: %s", exc)
        return False
