-- ============================================================================
-- Stage 05: FinOps ROI, Modality Economics & Calibration Queries (BigQuery)
-- ============================================================================

-- 1. Route Performance & FinOps ROI Summary (System 1 Fast Path vs. System 2 Slow Path)
SELECT
  route_taken,
  COUNT(*) AS total_requests,
  ROUND(AVG(decision_latency_ms), 2) AS avg_s1_latency_ms,
  ROUND(AVG(reasoning_latency_ms), 2) AS avg_s2_latency_ms,
  ROUND(AVG(overall_latency_ms), 2) AS avg_total_latency_ms,
  SUM(decision_output_tokens) AS total_s1_output_tokens,
  ROUND(AVG(total_cost_usd) * 1000000, 2) AS avg_cost_per_million_reqs_usd,
  ROUND(AVG(confidence), 4) AS avg_s1_confidence
FROM `decisions_gateway_telemetry.decision_events`
WHERE event_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY route_taken
ORDER BY route_taken;

-- 2. Empirical Calibration Audit (Comparing Predicted Confidence Buckets vs. Ground-Truth Accuracy)
SELECT
  CASE
    WHEN confidence >= 0.95 THEN '0.95 - 1.00'
    WHEN confidence >= 0.85 THEN '0.85 - 0.95'
    WHEN confidence >= 0.70 THEN '0.70 - 0.85'
    ELSE '< 0.70'
  END AS confidence_bucket,
  COUNT(*) AS evaluated_samples,
  ROUND(AVG(confidence), 4) AS mean_predicted_confidence,
  ROUND(AVG(IF(ground_truth_match, 1.0, 0.0)), 4) AS empirical_accuracy,
  ROUND(ABS(AVG(confidence) - AVG(IF(ground_truth_match, 1.0, 0.0))), 4) AS abs_calibration_gap
FROM `decisions_gateway_telemetry.decision_events`
WHERE ground_truth_match IS NOT NULL
  AND event_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY confidence_bucket
ORDER BY confidence_bucket DESC;

-- 3. Parallel Question Amortization & Multimodal Token Breakdown by Stage
SELECT
  stage,
  modalities,
  MAX(question_count) AS questions_per_pass,
  COUNT(*) AS requests,
  ROUND(AVG(decision_input_tokens), 1) AS avg_input_tokens,
  SUM(decision_output_tokens) AS sum_output_tokens,
  ROUND(AVG(decision_latency_ms), 2) AS avg_decision_latency_ms,
  ROUND(AVG(decision_latency_ms / GREATEST(question_count, 1)), 2) AS effective_ms_per_question
FROM `decisions_gateway_telemetry.decision_events`
WHERE event_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY stage, modalities
ORDER BY stage;
