"""System 2 Client: Gemini on Google Cloud Agent Platform (Keyless IAM ADC, Zero Fallbacks)."""

import json
import time
from typing import Optional
from google import genai
from google.genai import types
from app.config import settings
from app.models import System1DecisionResult, System2ReasoningResult, TriageRequest


class GeminiReasoningClient:
    """Invokes Gemini on Google Cloud Agent Platform via keyless IAM ADC."""

    def __init__(self) -> None:
        self.project = settings.google_cloud_project
        self.location = settings.google_cloud_location
        self.model_name = settings.gemini_model
        self._client: Optional[genai.Client] = None

    def _get_client(self) -> genai.Client:
        if not self.project:
            raise RuntimeError("GOOGLE_CLOUD_PROJECT environment variable is required.")
        if self._client is None:
            self._client = genai.Client(
                vertexai=True,
                project=self.project,
                location=self.location,
            )
        return self._client

    async def resolve_complex_query(
        self, request: TriageRequest, s1_result: System1DecisionResult
    ) -> System2ReasoningResult:
        client = self._get_client()
        start_time = time.perf_counter()

        user_prompt = f"""You are an autonomous enterprise incident & policy specialist running on Google Cloud Gemini Enterprise Agent Platform.
A fast System 1 decision model (Gemini Decision 1) evaluated this incoming request and escalated it for deep System 2 reasoning.

Incoming Request: "{request.query}"
Customer Tier: {request.customer_tier}

System 1 Telemetry:
- Preliminary Queue: {s1_result.department.value} (confidence={s1_result.department_confidence})
- Auto-Resolve Probability: {s1_result.auto_resolve_probability}
- Urgency Level: {s1_result.urgency.value} (score={s1_result.urgency_score}/3.0)
- Churn Risk Score: {s1_result.churn_risk_score}/3.0

Analyze the root cause or policy nuances, draft a concise technical/empathetic response, specify the next engineering or operational action, and indicate whether human review is required.

Return strict JSON with keys:
- "reasoning_summary": string
- "generated_response": string
- "suggested_action": string
- "requires_human_escalation": boolean
"""

        response = await client.aio.models.generate_content(
            model=self.model_name,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                response_mime_type="application/json",
            ),
        )
        latency_ms = (time.perf_counter() - start_time) * 1000
        data = json.loads(response.text)

        usage = response.usage_metadata
        input_tokens = int((usage.prompt_token_count if usage else 0) or 0)
        output_tokens = int((usage.candidates_token_count if usage else 0) or 0)
        cost_usd = (input_tokens / 1_000_000 * 0.30) + (output_tokens / 1_000_000 * 2.50)

        return System2ReasoningResult(
            model=self.model_name,
            reasoning_summary=str(data["reasoning_summary"]),
            generated_response=str(data["generated_response"]),
            suggested_action=str(data["suggested_action"]),
            requires_human_escalation=bool(data["requires_human_escalation"]),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=round(latency_ms, 2),
            cost_usd=round(cost_usd, 6),
        )
