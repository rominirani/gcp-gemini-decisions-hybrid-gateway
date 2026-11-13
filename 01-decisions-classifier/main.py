"""Stage 01: Standalone Gemini Decisions API Microservice on Google Cloud Run.

Evaluates closed-set routing, yes/no auto-resolvability, and severity rubric questions
in a single forward pass using Gemini Decision 1 (gemini-decision-1) with 0 output tokens.
Strictly requires GEMINI_API_KEY (mounted from Cloud Secret Manager). Zero fallbacks.
"""

import logging
import os
import time
from typing import Dict, Optional
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field
from google import genai

logger = logging.getLogger("decisions_classifier")
logging.basicConfig(level=logging.INFO)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
DECISION_MODEL = os.getenv("GEMINI_DECISION_MODEL", "gemini-decision-1")
_DECISIONS_CLIENT: Optional[genai.Client] = None

# TODO(security): Enforce Cloud Run IAM authentication (--no-allow-unauthenticated)
# or Cloud Armor / API Gateway rate-limiting and JWT auth in production deployments.
app = FastAPI(
    title="Stage 01: Gemini Decisions API Classifier on Cloud Run",
    description="Fast, calibrated closed-set decisions (noul, choice, score) powered by gemini-decision-1.",
    version="1.0.0",
)

ACTION_MAP = {
    "order_status": "DISPATCH_ORDER_TRACKING",
    "billing_refund": "INITIATE_BILLING_WORKFLOW",
    "subscription_cancel": "INITIATE_CANCELLATION_FLOW",
    "account_access": "SEND_MFA_RECOVERY_LINK",
    "complex_incident": "ESCALATE_TO_SYSTEM2_REASONING",
    "other": "ESCALATE_TO_HUMAN_REVIEW",
}

URGENCY_LABELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


def _get_decisions_client() -> genai.Client:
    global _DECISIONS_CLIENT
    if not GEMINI_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="Service misconfigured: GEMINI_API_KEY secret is not mounted.",
        )
    if _DECISIONS_CLIENT is None:
        _DECISIONS_CLIENT = genai.Client(
            api_key=GEMINI_API_KEY,
            http_options={"api_version": "v1beta"},
        )
    return _DECISIONS_CLIENT


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cache-Control"] = "no-store"
    if not request.url.path.startswith("/docs") and not request.url.path.startswith("/openapi"):
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none';"
    return response


class ClassificationRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        max_length=8000,
        description="Unstructured customer message or operational event text.",
    )


class ClassificationResponse(BaseModel):
    query: str
    model: str
    department: str
    department_confidence: float
    department_probabilities: Dict[str, float]
    can_auto_resolve: bool
    auto_resolve_probability: float
    urgency_level: str
    urgency_score: float
    urgency_confidence: float
    suggested_action: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    latency_ms: float
    platform: str = "Google Cloud Run"


@app.get("/health")
async def health_check():
    """Liveness probe (uses /health because /healthz is reserved by Google Front End)."""
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY is not configured.")
    return {
        "status": "healthy",
        "model": DECISION_MODEL,
        "platform": "Google Cloud Run",
    }


@app.post("/classify", response_model=ClassificationResponse)
async def classify_inquiry(req: ClassificationRequest):
    """Evaluate department choice, auto-resolve yes/no, and urgency score in one pass."""
    client = _get_decisions_client()
    start_time = time.perf_counter()

    try:
        result = await client.aio.decisions.create(
            model=DECISION_MODEL,
            input=req.query,
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
                    "instructions": "Rate the operational urgency and severity of this message.",
                    "criteria": [
                        "Low: Routine informational or tracking question.",
                        "Medium: Standard account, subscription, or billing request.",
                        "High: Time-sensitive customer impact or repeated billing failure.",
                        "Critical: Production-halting outage, data loss risk, or security incident.",
                    ],
                },
            },
        )
    except Exception as exc:
        logger.error("Gemini Decisions API call failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Upstream decision evaluation failed.") from exc

    latency_ms = (time.perf_counter() - start_time) * 1000

    dept = result.answers["department"]
    auto = result.answers["can_auto_resolve"]
    urg = result.answers["urgency"]
    top_urg_idx = int(max(urg.probabilities, key=urg.probabilities.get))
    in_tokens = int(result.usage.total_input_tokens or 0)
    out_tokens = int(result.usage.total_output_tokens or 0)

    return ClassificationResponse(
        query=req.query,
        model=DECISION_MODEL,
        department=dept.choice,
        department_confidence=round(dept.confidence, 4),
        department_probabilities={k: round(v, 4) for k, v in dept.probabilities.items()},
        can_auto_resolve=bool(auto.noul >= 0.80 and dept.confidence >= 0.85),
        auto_resolve_probability=round(auto.noul, 4),
        urgency_level=URGENCY_LABELS[min(top_urg_idx, len(URGENCY_LABELS) - 1)],
        urgency_score=round(urg.score, 4),
        urgency_confidence=round(urg.confidence, 4),
        suggested_action=ACTION_MAP.get(dept.choice, "ESCALATE_TO_HUMAN_REVIEW"),
        input_tokens=in_tokens,
        output_tokens=out_tokens,
        estimated_cost_usd=round((in_tokens / 1_000_000) * 0.10, 7),
        latency_ms=round(latency_ms, 2),
    )


if __name__ == "__main__":
    import uvicorn
    # Bind strictly to 127.0.0.1 for local testing
    uvicorn.run("main:app", host="127.0.0.1", port=int(os.getenv("PORT", "8080")), reload=False)
