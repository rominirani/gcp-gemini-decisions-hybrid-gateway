"""Domain Models and Strict Pydantic Contracts for the Hybrid Decisions Gateway."""

from enum import Enum
from typing import Any, Dict, Literal, Optional
from pydantic import BaseModel, Field


class DepartmentQueue(str, Enum):
    ORDER_STATUS = "order_status"
    BILLING_REFUND = "billing_refund"
    SUBSCRIPTION_CANCEL = "subscription_cancel"
    ACCOUNT_ACCESS = "account_access"
    COMPLEX_INCIDENT = "complex_incident"
    OTHER = "other"


class UrgencyLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RouteTarget(str, Enum):
    FAST_PATH_DECISIONS = "FAST_PATH_DECISIONS"
    SLOW_PATH_AGENT_PLATFORM = "SLOW_PATH_AGENT_PLATFORM"


class TriageRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        max_length=8000,
        description="Unstructured customer message or operational event payload.",
    )
    customer_tier: Literal["STANDARD", "PREMIUM", "ENTERPRISE"] = Field(
        default="STANDARD",
        description="Customer SLA tier.",
    )


class System1DecisionResult(BaseModel):
    model: str
    department: DepartmentQueue
    department_confidence: float = Field(..., ge=0.0, le=1.0)
    department_probabilities: Dict[str, float]
    can_auto_resolve: bool
    auto_resolve_probability: float = Field(..., ge=0.0, le=1.0)
    urgency: UrgencyLevel
    urgency_score: float
    urgency_confidence: float = Field(..., ge=0.0, le=1.0)
    churn_risk_score: float
    suggested_action: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    cost_usd: float


class System2ReasoningResult(BaseModel):
    model: str
    reasoning_summary: str
    generated_response: str
    suggested_action: str
    requires_human_escalation: bool
    input_tokens: int
    output_tokens: int
    latency_ms: float
    cost_usd: float


class GatewayResponse(BaseModel):
    request_query: str
    customer_tier: str
    route_taken: RouteTarget
    overall_latency_ms: float
    overall_cost_usd: float
    system1_decision: System1DecisionResult
    system2_reasoning: Optional[System2ReasoningResult] = None
    final_action: str
    resolution_payload: Dict[str, Any]
    routing_reason: str
