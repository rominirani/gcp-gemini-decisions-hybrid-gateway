"""Confidence-Calibrated Router: Dispatches between Gemini Decisions API and Agent Platform."""

from datetime import datetime, timezone
import logging
import time
import uuid
from app.config import settings
from app.decisions_client import GeminiDecisionsClient
from app.models import (
    DepartmentQueue,
    GatewayResponse,
    RouteTarget,
    TriageRequest,
)
from app.reasoning_client import GeminiReasoningClient

logger = logging.getLogger("hybrid_router")


class HybridDecisionsRouter:
    """Routes traffic using calibrated probabilities from Gemini Decision 1."""

    def __init__(self) -> None:
        self.decisions_client = GeminiDecisionsClient()
        self.reasoning_client = GeminiReasoningClient()
        self.confidence_threshold = settings.confidence_threshold
        self.auto_resolve_threshold = settings.auto_resolve_threshold

    async def process_request(self, request: TriageRequest) -> GatewayResponse:
        overall_start = time.perf_counter()

        # Step 1: System 1 single-pass evaluation via Gemini Decisions API (0 output tokens)
        s1_result = await self.decisions_client.evaluate(request)

        is_high_confidence = s1_result.department_confidence >= self.confidence_threshold
        is_deterministic_queue = s1_result.department not in (
            DepartmentQueue.COMPLEX_INCIDENT,
            DepartmentQueue.OTHER,
        )

        if is_high_confidence and s1_result.can_auto_resolve and is_deterministic_queue:
            overall_latency_ms = (time.perf_counter() - overall_start) * 1000
            final_action = f"AUTO_EXECUTE_{s1_result.suggested_action}"

            routing_reason = (
                f"Fast-path selected: Gemini Decision 1 queue confidence "
                f"({s1_result.department_confidence:.3f} >= {self.confidence_threshold:.2f}) "
                f"and auto-resolve probability ({s1_result.auto_resolve_probability:.3f} >= "
                f"{self.auto_resolve_threshold:.2f}) satisfied with 0 output tokens."
            )

            response = GatewayResponse(
                request_query=request.query,
                customer_tier=request.customer_tier,
                route_taken=RouteTarget.FAST_PATH_DECISIONS,
                overall_latency_ms=round(overall_latency_ms, 2),
                overall_cost_usd=s1_result.cost_usd,
                system1_decision=s1_result,
                system2_reasoning=None,
                final_action=final_action,
                resolution_payload={
                    "status": "AUTO_RESOLVED_BY_SYSTEM_1",
                    "dispatched_action": final_action,
                    "queue": s1_result.department.value,
                    "urgency": s1_result.urgency.value,
                    "churn_risk_score": s1_result.churn_risk_score,
                },
                routing_reason=routing_reason,
            )
        else:
            routing_reason = (
                f"Slow-path selected: queue='{s1_result.department.value}' "
                f"(conf={s1_result.department_confidence:.3f}), "
                f"P(auto_resolve)={s1_result.auto_resolve_probability:.3f}. "
                f"Escalated to Gemini Enterprise Agent Platform ({settings.gemini_model})."
            )
            s2_result = await self.reasoning_client.resolve_complex_query(request, s1_result)
            overall_latency_ms = (time.perf_counter() - overall_start) * 1000
            total_cost = s1_result.cost_usd + s2_result.cost_usd

            response = GatewayResponse(
                request_query=request.query,
                customer_tier=request.customer_tier,
                route_taken=RouteTarget.SLOW_PATH_AGENT_PLATFORM,
                overall_latency_ms=round(overall_latency_ms, 2),
                overall_cost_usd=round(total_cost, 6),
                system1_decision=s1_result,
                system2_reasoning=s2_result,
                final_action=s2_result.suggested_action,
                resolution_payload={
                    "status": "ESCALATED_TO_SYSTEM_2",
                    "reasoning_summary": s2_result.reasoning_summary,
                    "drafted_response": s2_result.generated_response,
                    "requires_human_escalation": s2_result.requires_human_escalation,
                },
                routing_reason=routing_reason,
            )

        await self._emit_bigquery_telemetry(response)
        return response

    async def _emit_bigquery_telemetry(self, response: GatewayResponse) -> None:
        if not settings.enable_bigquery_telemetry or not settings.google_cloud_project:
            return
        try:
            from google.cloud import bigquery

            bq_client = bigquery.Client(project=settings.google_cloud_project)
            table_id = (
                f"{settings.google_cloud_project}."
                f"{settings.bigquery_dataset}.{settings.bigquery_table}"
            )
            s1 = response.system1_decision
            s2 = response.system2_reasoning
            row = {
                "event_timestamp": datetime.now(timezone.utc).isoformat(),
                "request_id": str(uuid.uuid4()),
                "stage": "stage02_hybrid_gateway",
                "route_taken": response.route_taken.value,
                "question_count": 4,
                "modalities": "text",
                "decision_input_tokens": s1.input_tokens,
                "decision_output_tokens": s1.output_tokens,
                "reasoning_input_tokens": s2.input_tokens if s2 else 0,
                "reasoning_output_tokens": s2.output_tokens if s2 else 0,
                "decision_latency_ms": s1.latency_ms,
                "reasoning_latency_ms": s2.latency_ms if s2 else 0.0,
                "overall_latency_ms": response.overall_latency_ms,
                "total_cost_usd": response.overall_cost_usd,
                "top_choice": s1.department.value,
                "confidence": s1.department_confidence,
                "auto_resolve_prob": s1.auto_resolve_probability,
                "ground_truth_match": None,
            }
            bq_client.insert_rows_json(table_id, [row])
        except Exception as exc:
            logger.warning("Non-blocking telemetry emission skipped: %s", type(exc).__name__)
