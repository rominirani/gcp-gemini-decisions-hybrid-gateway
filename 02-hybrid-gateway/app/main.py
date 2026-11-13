"""FastAPI Entry Point for Stage 02: Hybrid AI Gateway on Google Cloud Run."""

import logging
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from app.config import settings
from app.models import GatewayResponse, TriageRequest
from app.router import HybridDecisionsRouter

logger = logging.getLogger("gateway_main")
logging.basicConfig(level=logging.INFO)

# TODO(security): Enforce Cloud Run IAM authentication (--no-allow-unauthenticated)
# or Identity-Aware Proxy (IAP) + Cloud Armor rate-limiting in production deployments.
app = FastAPI(
    title="Stage 02: Google Cloud Hybrid AI Gateway (Gemini Decisions API + Agent Platform)",
    description="System 1 calibrated routing (gemini-decision-1) + System 2 deep reasoning (gemini-3.8-flash).",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

router = HybridDecisionsRouter()
STATIC_DIR = Path(__file__).parent / "static"


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cache-Control"] = "no-store"
    if request.url.path == "/":
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; connect-src 'self'; "
            "img-src 'self' data:; object-src 'none'; frame-ancestors 'none';"
        )
    elif not request.url.path.startswith("/docs") and not request.url.path.startswith("/openapi"):
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none';"
    return response


@app.get("/")
async def root_dashboard():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Hybrid AI Gateway running. Visit /docs for OpenAPI schema."}


@app.get("/health")
async def health_check():
    if not settings.gemini_api_key.strip():
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY is not configured.")
    if not settings.google_cloud_project.strip():
        raise HTTPException(status_code=500, detail="GOOGLE_CLOUD_PROJECT is not configured.")
    return {
        "status": "healthy",
        "system1_model": settings.gemini_decision_model,
        "system2_model": settings.gemini_model,
        "confidence_threshold": settings.confidence_threshold,
    }


@app.post("/api/v1/triage", response_model=GatewayResponse)
async def triage_inquiry(request: TriageRequest):
    try:
        return await router.process_request(request)
    except Exception as exc:
        logger.error("Triage routing failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Gateway triage execution failed.") from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=settings.port, reload=False)
