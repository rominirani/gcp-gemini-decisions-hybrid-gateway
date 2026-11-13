#!/usr/bin/env python3
"""Standalone Local Experiment 3: Native Multimodal Triage (Photos + PDF Invoices, Zero OCR).

Demonstrates two multimodal capabilities of gemini-decision-1 in a single script:
  1. Image resolution tuning (resolution="low" vs. resolution="high") on a public
     inspection photo—showing an exact 4x image-token reduction (266 vs. 1,064 tokens).
  2. Native PDF invoice verification (application/pdf) from raw bytes—evaluating
     claim accuracy, disposition, and severity in one pass with zero OCR pipeline.

Requires GEMINI_API_KEY in the environment (or local .env file). No fallbacks.
"""

import base64
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional
from dotenv import load_dotenv
from google import genai

load_dotenv()

DECISION_MODEL = os.getenv("GEMINI_DECISION_MODEL", "gemini-decision-1")
REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_PDF_PATH = (REPO_ROOT / "03-multimodal-triage" / "sample_invoice_8812.pdf").resolve()
PUBLIC_SPILL_IMAGE_URI = "https://storage.googleapis.com/generativeai-downloads/images/spill.jpg"

MULTIMODAL_QUESTIONS: Dict[str, Any] = {
    "evidence_supports_claim": {
        "type": "noul",
        "instructions": "Does the attached visual image or PDF document directly corroborate the user's written claim?",
        "criteria": {
            "true_description": "The image or PDF clearly shows the spill, damage, or duplicate charge described in the claim text.",
            "false_description": "The attachment contradicts the claim text, is unrelated, or lacks visible evidence.",
        },
    },
    "disposition": {
        "type": "choice",
        "instructions": "Select the best operational action based on both the written claim and the attached evidence.",
        "criteria": {
            "automated_credit_or_replacement": "Verified duplicate charge or clear product defect eligible for immediate fulfillment.",
            "dispatch_urgent_facilities": "Major hazard or severe spill requiring professional facilities dispatch.",
            "local_cleanup_or_self_service": "Minor localized issue (such as a small counter spill with a cloth nearby) handled locally.",
            "manual_adjuster_review": "Evidence is ambiguous, contradictory, or high-value requiring human review.",
            "other": "Does not fit any disposition above.",
        },
    },
    "severity": {
        "type": "score",
        "instructions": "Rate the physical or financial severity shown in the evidence.",
        "criteria": [
            "Negligible: Clean surface or valid single-charge invoice.",
            "Minor: Small localized spill or minor cosmetic blemish.",
            "Moderate: Clear duplicate invoice charge or functional item damage.",
            "Severe: Hazardous condition or major multi-item loss.",
        ],
    },
}


def run_multimodal_check(
    client: genai.Client,
    label: str,
    claim_text: str,
    media_block: Dict[str, Any],
    resolution_used: Optional[str] = None,
) -> Dict[str, Any]:
    # Always end text blocks with \n because adjacent blocks concatenate with no separator
    contents = [
        {"type": "text", "text": f"Claim Statement: {claim_text}\nAttached Evidence:\n"},
        media_block,
    ]

    start = time.perf_counter()
    result = client.decisions.create(
        model=DECISION_MODEL,
        input=contents,
        questions=MULTIMODAL_QUESTIONS,
    )
    latency_ms = (time.perf_counter() - start) * 1000

    ans = result.answers
    ev = ans["evidence_supports_claim"]
    disp = ans["disposition"]
    sev = ans["severity"]
    top_sev_idx = max(sev.probabilities, key=sev.probabilities.get)

    tokens_by_modality: Dict[str, int] = {}
    if result.usage and result.usage.input_tokens_by_modality:
        for item in result.usage.input_tokens_by_modality:
            tokens_by_modality[str(item.modality)] = int(item.tokens or 0)

    total_in = int(result.usage.total_input_tokens or 0)
    total_out = int(result.usage.total_output_tokens or 0)

    return {
        "experiment": label,
        "resolution": resolution_used,
        "latency_ms": round(latency_ms, 2),
        "evidence_supports_claim_prob": round(ev.noul, 4),
        "disposition": disp.choice,
        "disposition_confidence": round(disp.confidence, 4),
        "severity_expected_0_to_3": round(sev.score, 4),
        "severity_top_level": sev.legend[top_sev_idx],
        "tokens_by_modality": tokens_by_modality,
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
        "estimated_cost_usd": round((total_in / 1_000_000) * 0.10, 7),
    }


def main() -> None:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is required. Export GEMINI_API_KEY from Google AI Studio "
            "(https://aistudio.google.com/api-keys) before running this script."
        )

    # Enforce strict repository path boundary and PDF magic-byte check
    if not str(SAMPLE_PDF_PATH).startswith(str(REPO_ROOT) + os.sep) or not SAMPLE_PDF_PATH.is_file():
        raise FileNotFoundError(f"Expected sample PDF inside repository at {SAMPLE_PDF_PATH}")
    pdf_bytes = SAMPLE_PDF_PATH.read_bytes()
    if not pdf_bytes.startswith(b"%PDF-"):
        raise ValueError("Sample file failed PDF magic-byte check.")

    client = genai.Client(api_key=api_key, http_options={"api_version": "v1beta"})

    spill_claim = "Breakroom counter check before 9 AM client meeting. Small coffee spill spotted next to wiping cloth."

    # 1a. Inspection photo at resolution="low"
    low_res = run_multimodal_check(
        client=client,
        label="1a_photo_resolution_low",
        claim_text=spill_claim,
        media_block={
            "type": "image",
            "uri": PUBLIC_SPILL_IMAGE_URI,
            "mime_type": "image/jpeg",
            "resolution": "low",
        },
        resolution_used="low",
    )

    # 1b. Same inspection photo at resolution="high"
    high_res = run_multimodal_check(
        client=client,
        label="1b_photo_resolution_high",
        claim_text=spill_claim,
        media_block={
            "type": "image",
            "uri": PUBLIC_SPILL_IMAGE_URI,
            "mime_type": "image/jpeg",
            "resolution": "high",
        },
        resolution_used="high",
    )

    # 2. Native PDF invoice verification (zero OCR)
    pdf_check = run_multimodal_check(
        client=client,
        label="2_pdf_duplicate_invoice_zero_ocr",
        claim_text="I was double-charged $45 twice ($90 total) on invoice INV-8812. Attached is my PDF invoice.",
        media_block={
            "type": "document",
            "data": base64.b64encode(pdf_bytes).decode("ascii"),
            "mime_type": "application/pdf",
        },
        resolution_used=None,
    )

    print(json.dumps([low_res, high_res, pdf_check], indent=2))


if __name__ == "__main__":
    main()
