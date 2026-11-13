"""System 1 Client: Gemini Decisions API (gemini-decision-1) with Zero Fallbacks."""

import json
import time
from typing import Optional
from google import genai
from app.config import settings
from app.models import (
    DepartmentQueue,
    System1DecisionResult,
    TriageRequest,
    UrgencyLevel,
)

ACTION_MAP = {
    DepartmentQueue.ORDER_STATUS: "DISPATCH_ORDER_TRACKING",
    DepartmentQueue.BILLING_REFUND: "INITIATE_BILLING_WORKFLOW",
    DepartmentQueue.SUBSCRIPTION_CANCEL: "RUN_CANCELLATION_WORKFLOW",
    DepartmentQueue.ACCOUNT_ACCESS: "SEND_VERIFIED_MFA_RESET",
    DepartmentQueue.COMPLEX_INCIDENT: "ESCALATE_TO_SYSTEM2_REASONING",
    DepartmentQueue.OTHER: "ESCALATE_TO_HUMAN_REVIEW",
}

URGENCY_LEVELS = [
    UrgencyLevel.LOW,
    UrgencyLevel.MEDIUM,
    UrgencyLevel.HIGH,
    UrgencyLevel.CRITICAL,
]


class GeminiDecisionsClient:
    """Evaluates closed-set triage questions in one forward pass via gemini-decision-1."""

    def __init__(self) -> None:
        self.model = settings.gemini_decision_model
        self._client: Optional[genai.Client] = None

    def _get_client(self) -> genai.Client:
        api_key = settings.gemini_api_key.strip()
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is required for Gemini Decisions API. No fallback is permitted."
            )
        if self._client is None:
            self._client = genai.Client(
                api_key=api_key,
                http_options={"api_version": "v1beta"},
            )
        return self._client

    async def evaluate(self, request: TriageRequest) -> System1DecisionResult:
        client = self._get_client()
        start_time = time.perf_counter()

        structured_context = json.dumps({"customer_tier": request.customer_tier})
        result = await client.aio.decisions.create(
            model=self.model,
            input=[
                {"type": "text", "text": structured_context + "\n"},
                {"type": "text", "text": request.query},
            ],
            questions={
                "department": {
                    "type": "choice",
                    "instructions": "Which operational queue should handle this customer message?",
                    "criteria": {
                        "order_status": "Order tracking, delivery dates, or shipment status.",
                        "billing_refund": "Duplicate charges, invoices, credits, or refund requests.",
                        "subscription_cancel": "Canceling or pausing a recurring subscription.",
                        "account_access": "Password resets, expired 2FA/MFA codes, or login lockouts.",
                        "complex_incident": "Production outages, HTTP 500 errors, architecture, or legal/DPA questions.",
                        "other": "Anything outside these specific categories.",
                    },
                },
                "can_auto_resolve": {
                    "type": "noul",
                    "instructions": "Can this request be fulfilled deterministically by an automated backend lookup or webhook without custom investigation?",
                    "criteria": {
                        "true_description": "Routine single-intent request such as checking tracking, resetting login, or standard cancellation.",
                        "false_description": "Production outage, multi-part legal question, ambiguous dispute, or engineering troubleshooting.",
                    },
                },
                "urgency": {
                    "type": "score",
                    "instructions": "Rate the operational urgency and severity of this message given `customer_tier`.",
                    "criteria": [
                        "Low: Routine informational or tracking question.",
                        "Medium: Standard account, subscription, or billing request.",
                        "High: Time-sensitive customer impact or repeated billing failure.",
                        "Critical: Production-halting outage, data loss risk, or security incident.",
                    ],
                },
                "churn_risk": {
                    "type": "score",
                    "instructions": "How likely is the customer to churn if this issue is not resolved promptly?",
                    "criteria": [
                        "No churn signal",
                        "Mild frustration",
                        "Mentions switching or recurring failure",
                        "Explicitly threatens cancellation or escalation",
                    ],
                },
            },
        )
        latency_ms = (time.perf_counter() - start_time) * 1000

        dept_ans = result.answers["department"]
        auto_ans = result.answers["can_auto_resolve"]
        urg_ans = result.answers["urgency"]
        churn_ans = result.answers["churn_risk"]

        dept_enum = DepartmentQueue(dept_ans.choice)
        top_urg_idx = int(max(urg_ans.probabilities, key=urg_ans.probabilities.get))
        urgency_enum = URGENCY_LEVELS[min(top_urg_idx, len(URGENCY_LEVELS) - 1)]

        in_tokens = int(result.usage.total_input_tokens or 0)
        out_tokens = int(result.usage.total_output_tokens or 0)
        cost_usd = (in_tokens / 1_000_000) * 0.10  # $0.10 per 1M input tokens, $0 output tokens

        return System1DecisionResult(
            model=self.model,
            department=dept_enum,
            department_confidence=round(dept_ans.confidence, 4),
            department_probabilities={k: round(v, 4) for k, v in dept_ans.probabilities.items()},
            can_auto_resolve=bool(auto_ans.noul >= settings.auto_resolve_threshold),
            auto_resolve_probability=round(auto_ans.noul, 4),
            urgency=urgency_enum,
            urgency_score=round(urg_ans.score, 4),
            urgency_confidence=round(urg_ans.confidence, 4),
            churn_risk_score=round(churn_ans.score, 4),
            suggested_action=ACTION_MAP.get(dept_enum, "ESCALATE_TO_HUMAN_REVIEW"),
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            latency_ms=round(latency_ms, 2),
            cost_usd=round(cost_usd, 7),
        )
