"""Stage 03: Native Multimodal Claims, Parcel & Facility Triage on Cloud Run.

Evaluates images or PDF documents alongside structured JSON metadata and claim text
in a single forward pass using Gemini Decision 1 (gemini-decision-1) with 0 output tokens.
Includes strict MIME allowlisting, magic-byte inspection, payload caps, and SSRF allowlisting.
"""

import base64
import json
import logging
import os
import time
from typing import Any, Dict, Literal, Optional
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from google import genai

logger = logging.getLogger("multimodal_triage")
logging.basicConfig(level=logging.INFO)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
DECISION_MODEL = os.getenv("GEMINI_DECISION_MODEL", "gemini-decision-1")
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB safety limit
ALLOWED_URI_HOSTS = {"storage.googleapis.com"}
ALLOWED_MIMES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}

_CLIENT: Optional[genai.Client] = None

# TODO(security): Enforce Cloud Run IAM authentication (--no-allow-unauthenticated),
# malware/CDR scanning for external uploads, and API rate-limiting in production.
app = FastAPI(
    title="Stage 03: Multimodal Parcel & Claims Triage (Gemini Decisions API)",
    description="Single-pass image + PDF + text evaluation using gemini-decision-1 with 0 output tokens.",
    version="1.0.0",
)


def _get_client() -> genai.Client:
    global _CLIENT
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY is not configured.")
    if _CLIENT is None:
        _CLIENT = genai.Client(api_key=GEMINI_API_KEY, http_options={"api_version": "v1beta"})
    return _CLIENT


def _verify_magic_bytes(raw: bytes, declared_mime: str) -> None:
    if declared_mime == "image/jpeg" and not raw.startswith(b"\xff\xd8\xff"):
        raise HTTPException(status_code=400, detail="File header does not match image/jpeg.")
    if declared_mime == "image/png" and not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(status_code=400, detail="File header does not match image/png.")
    if declared_mime == "image/webp" and not (raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"):
        raise HTTPException(status_code=400, detail="File header does not match image/webp.")
    if declared_mime == "application/pdf" and not raw.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="File header does not match application/pdf.")


def _validate_https_uri(uri: str) -> None:
    parsed = urlparse(uri)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_URI_HOSTS:
        raise HTTPException(
            status_code=400,
            detail="Only HTTPS URIs from allowlisted storage hosts (storage.googleapis.com) are accepted.",
        )


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


class MultimodalUriRequest(BaseModel):
    claim_text: str = Field(..., min_length=1, max_length=4000)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    media_block_type: Literal["image", "document"] = Field(default="image")
    media_uri: str = Field(..., min_length=10, max_length=1024)
    mime_type: Literal["image/jpeg", "image/png", "image/webp", "application/pdf"] = Field(
        default="image/jpeg"
    )
    resolution: Optional[Literal["low", "medium", "high", "ultra_high"]] = Field(default="low")


class MultimodalDecisionResponse(BaseModel):
    model: str
    claim_text: str
    mime_type: str
    resolution: Optional[str]
    evidence_supports_claim: float
    evidence_confidence: float
    visible_issue_detected: float
    disposition: str
    disposition_confidence: float
    disposition_probabilities: Dict[str, float]
    severity_score: float
    severity_label: str
    severity_confidence: float
    tokens_by_modality: Dict[str, int]
    total_input_tokens: int
    total_output_tokens: int
    estimated_cost_usd: float
    latency_ms: float


MULTIMODAL_QUESTIONS = {
    "evidence_supports_claim": {
        "type": "noul",
        "instructions": "Does the attached image or PDF document corroborate the statement in `claim_text`?",
        "criteria": {
            "true_description": "Visual or document evidence aligns with the reported spill, defect, damage, or invoice charge.",
            "false_description": "Attachment contradicts the claim, shows no issue, or is unrelated.",
        },
    },
    "visible_issue_detected": {
        "type": "noul",
        "instructions": "Does the attachment show an uncleaned spill, physical damage, safety hazard, or duplicate billing line item?",
    },
    "disposition": {
        "type": "choice",
        "instructions": "Which operational action best fits the combined text, metadata, and media evidence?",
        "criteria": {
            "automated_credit_or_replacement": "Clear minor item defect, duplicate line item, or verified low-value claim.",
            "local_cleanup_or_self_service": "Minor localized counter spill or user-resolvable setup issue.",
            "urgent_field_or_ops_dispatch": "Major hazard, active leak, or severe physical facility/equipment failure.",
            "manual_adjuster_review": "Ambiguous evidence, mismatch between text and attachment, or high-value dispute.",
            "ready_no_action": "Scene or document is clean and requires no intervention.",
        },
    },
    "severity": {
        "type": "score",
        "instructions": "Rate the severity of the issue shown across the attachment and report.",
        "criteria": [
            "None: Clean and compliant, no defect or discrepancy.",
            "Low: Minor localized spill, cosmetic wear, or small discrepancy.",
            "Moderate: Clear functional item damage or verified duplicate invoice charge.",
            "Critical: Major safety hazard, broken glass, or severe operational blocker.",
        ],
    },
}


async def _run_multimodal_decisions(
    claim_text: str,
    metadata: Dict[str, Any],
    media_block: Dict[str, Any],
    mime_type: str,
    resolution: Optional[str],
) -> MultimodalDecisionResponse:
    client = _get_client()
    context_str = json.dumps({"metadata": metadata, "claim_text": claim_text})

    start = time.perf_counter()
    try:
        result = await client.aio.decisions.create(
            model=DECISION_MODEL,
            input=[
                {"type": "text", "text": context_str + "\n"},
                media_block,
            ],
            questions=MULTIMODAL_QUESTIONS,
        )
    except Exception as exc:
        logger.error("Multimodal decision call failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Multimodal decision evaluation failed.") from exc

    latency_ms = (time.perf_counter() - start) * 1000
    ans = result.answers
    ev = ans["evidence_supports_claim"]
    vis = ans["visible_issue_detected"]
    disp = ans["disposition"]
    sev = ans["severity"]
    top_sev_idx = max(sev.probabilities, key=sev.probabilities.get)

    mod_tokens: Dict[str, int] = {}
    if result.usage and result.usage.input_tokens_by_modality:
        for item in result.usage.input_tokens_by_modality:
            mod_tokens[str(item.modality)] = int(item.tokens or 0)

    total_in = int(result.usage.total_input_tokens or 0)
    total_out = int(result.usage.total_output_tokens or 0)

    return MultimodalDecisionResponse(
        model=DECISION_MODEL,
        claim_text=claim_text,
        mime_type=mime_type,
        resolution=resolution,
        evidence_supports_claim=round(ev.noul, 4),
        evidence_confidence=round(ev.confidence, 4),
        visible_issue_detected=round(vis.noul, 4),
        disposition=disp.choice,
        disposition_confidence=round(disp.confidence, 4),
        disposition_probabilities={k: round(v, 4) for k, v in disp.probabilities.items()},
        severity_score=round(sev.score, 4),
        severity_label=sev.legend[top_sev_idx],
        severity_confidence=round(sev.confidence, 4),
        tokens_by_modality=mod_tokens,
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        estimated_cost_usd=round((total_in / 1_000_000) * 0.10, 7),
        latency_ms=round(latency_ms, 2),
    )


@app.get("/health")
async def health_check():
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY is not configured.")
    return {"status": "healthy", "model": DECISION_MODEL, "stage": "03-multimodal-triage"}


@app.post("/triage/uri", response_model=MultimodalDecisionResponse)
async def triage_by_uri(req: MultimodalUriRequest):
    _validate_https_uri(req.media_uri)
    if req.media_block_type == "document" and req.mime_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Document blocks require application/pdf.")

    media_block: Dict[str, Any] = {
        "type": req.media_block_type,
        "uri": req.media_uri,
        "mime_type": req.mime_type,
    }
    if req.media_block_type == "image" and req.resolution:
        media_block["resolution"] = req.resolution

    return await _run_multimodal_decisions(
        claim_text=req.claim_text,
        metadata=req.metadata,
        media_block=media_block,
        mime_type=req.mime_type,
        resolution=req.resolution if req.media_block_type == "image" else None,
    )


@app.post("/triage/upload", response_model=MultimodalDecisionResponse)
async def triage_by_upload(
    claim_text: str = Form(..., min_length=1, max_length=4000),
    customer_tier: Literal["STANDARD", "PREMIUM", "ENTERPRISE"] = Form("STANDARD"),
    resolution: Literal["low", "medium", "high", "ultra_high"] = Form("low"),
    file: UploadFile = File(...),
):
    declared_mime = (file.content_type or "").strip().lower()
    if declared_mime not in ALLOWED_MIMES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported MIME type. Allowed: {sorted(ALLOWED_MIMES)}",
        )

    raw_bytes = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(raw_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Uploaded file exceeds 5 MB limit.")

    _verify_magic_bytes(raw_bytes, declared_mime)

    is_pdf = declared_mime == "application/pdf"
    block_type = "document" if is_pdf else "image"
    media_block: Dict[str, Any] = {
        "type": block_type,
        "data": base64.b64encode(raw_bytes).decode("ascii"),
        "mime_type": declared_mime,
    }
    if not is_pdf:
        media_block["resolution"] = resolution

    return await _run_multimodal_decisions(
        claim_text=claim_text,
        metadata={"customer_tier": customer_tier},
        media_block=media_block,
        mime_type=declared_mime,
        resolution=None if is_pdf else resolution,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=int(os.getenv("PORT", "8080")), reload=False)
