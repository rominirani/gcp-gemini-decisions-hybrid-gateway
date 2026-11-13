"""Strict Application Configuration via Pydantic Settings (Zero Fallbacks)."""

import os
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # System 1: Gemini Decisions API (v1beta via GEMINI_API_KEY)
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_decision_model: str = os.getenv("GEMINI_DECISION_MODEL", "gemini-decision-1")

    # System 2: Google Cloud Gemini Enterprise Agent Platform (Keyless IAM ADC)
    google_cloud_project: str = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    google_cloud_location: str = os.getenv("GOOGLE_CLOUD_LOCATION", "global")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

    # Calibrated Routing Policy Thresholds
    confidence_threshold: float = float(os.getenv("CONFIDENCE_THRESHOLD", "0.85"))
    auto_resolve_threshold: float = float(os.getenv("AUTO_RESOLVE_THRESHOLD", "0.80"))

    # Optional BigQuery Telemetry Sink
    enable_bigquery_telemetry: bool = os.getenv("ENABLE_BIGQUERY_TELEMETRY", "false").lower() in (
        "true",
        "1",
        "yes",
    )
    bigquery_dataset: str = os.getenv("BIGQUERY_DATASET", "decisions_gateway_telemetry")
    bigquery_table: str = os.getenv("BIGQUERY_TABLE", "decision_events")

    # Security & Server Settings
    allowed_origins_csv: str = os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:8080,http://localhost:8080")
    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = int(os.getenv("PORT", "8080"))

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def allowed_origins(self) -> List[str]:
        return [o.strip() for o in self.allowed_origins_csv.split(",") if o.strip()]


settings = Settings()
