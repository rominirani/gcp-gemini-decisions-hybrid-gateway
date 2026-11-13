-- ============================================================================
-- Stage 05: Partitioned & Clustered BigQuery Schema for Gemini Decisions API
-- ============================================================================
CREATE TABLE IF NOT EXISTS `decisions_gateway_telemetry.decision_events`
(
  event_timestamp          TIMESTAMP NOT NULL OPTIONS(description="UTC timestamp of the gateway decision"),
  request_id               STRING    NOT NULL OPTIONS(description="UUID for correlation across logs and traces"),
  stage                    STRING    NOT NULL OPTIONS(description="Pipeline stage (stage01..stage05)"),
  route_taken              STRING    NOT NULL OPTIONS(description="FAST_PATH_DECISIONS or SLOW_PATH_AGENT_PLATFORM"),
  question_count           INT64     NOT NULL OPTIONS(description="Number of parallel questions evaluated in 1 pass"),
  modalities               STRING    NOT NULL OPTIONS(description="Comma-separated input modalities (e.g., text, text+image, text+pdf)"),
  decision_input_tokens    INT64     NOT NULL OPTIONS(description="Gemini Decision 1 input tokens ($0.10/MTok)"),
  decision_output_tokens   INT64     NOT NULL OPTIONS(description="Always 0 for Gemini Decisions API"),
  reasoning_input_tokens   INT64     NOT NULL OPTIONS(description="System 2 Agent Platform input tokens (0 on Fast Path)"),
  reasoning_output_tokens  INT64     NOT NULL OPTIONS(description="System 2 Agent Platform output tokens (0 on Fast Path)"),
  decision_latency_ms      FLOAT64   NOT NULL OPTIONS(description="System 1 latency in milliseconds"),
  reasoning_latency_ms     FLOAT64   NOT NULL OPTIONS(description="System 2 latency in milliseconds (0 on Fast Path)"),
  overall_latency_ms       FLOAT64   NOT NULL OPTIONS(description="End-to-end gateway latency in milliseconds"),
  total_cost_usd           FLOAT64   NOT NULL OPTIONS(description="Total request cost in USD"),
  top_choice               STRING             OPTIONS(description="Winning choice or disposition"),
  confidence               FLOAT64            OPTIONS(description="Calibrated confidence of top outcome (0..1)"),
  auto_resolve_prob        FLOAT64            OPTIONS(description="Calibrated yes probability from noul check (0.01..0.99)"),
  ground_truth_match       BOOL               OPTIONS(description="Optional empirical audit label for calibration curve analysis")
)
PARTITION BY DATE(event_timestamp)
CLUSTER BY route_taken, stage, top_choice;
