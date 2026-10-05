-- SQLite audit queries used to validate the report datasets.
-- The companion build_report.py loads predictions.jsonl, threshold_policy.jsonl,
-- descriptive_accuracy_frontier.jsonl, and manifest composition into the named
-- in-memory tables before running the corresponding SELECT.

-- fixed_metrics
WITH audit AS (
  SELECT label, score
  FROM predictions
  WHERE split = 'audit'
)
SELECT
  COUNT(*) AS sample_count,
  SUM(label = 1 AND score >= 0.27235443798317116) AS true_positive,
  SUM(label = 0 AND score < 0.27235443798317116) AS true_negative,
  SUM(label = 0 AND score >= 0.27235443798317116) AS false_positive,
  SUM(label = 1 AND score < 0.27235443798317116) AS false_negative,
  1.0 * SUM(label = 1 AND score >= 0.27235443798317116) / SUM(label = 1) AS recall,
  1.0 * SUM(label = 0 AND score >= 0.27235443798317116) / SUM(label = 0) AS false_positive_rate,
  1.0 * SUM((label = 1 AND score >= 0.27235443798317116) OR (label = 0 AND score < 0.27235443798317116)) / COUNT(*) AS accuracy
FROM audit;

-- category_metrics
WITH category_rows AS (
  SELECT category, label, score
  FROM predictions
  WHERE split = 'audit'
    AND category IN ('system_prompt', 'rag', 'cot', 'skill')
    AND (
      label = 1
      OR (label = 0 AND negative_subtype = 'topic_matched_hard_negative')
    )
)
SELECT
  category,
  COUNT(*) AS sample_count,
  SUM(label = 1 AND score < 0.27235443798317116) AS false_negative,
  SUM(label = 0 AND score >= 0.27235443798317116) AS false_positive,
  1.0 * SUM(label = 1 AND score >= 0.27235443798317116) / SUM(label = 1) AS recall,
  1.0 * SUM(label = 0 AND score >= 0.27235443798317116) / SUM(label = 0) AS false_positive_rate,
  1.0 * SUM((label = 1 AND score >= 0.27235443798317116) OR (label = 0 AND score < 0.27235443798317116)) / COUNT(*) AS accuracy
FROM category_rows
GROUP BY category
ORDER BY recall ASC;

-- fpr_policy
SELECT
  target_fpr_cap,
  selected_threshold,
  calibration_fpr,
  heldout_actual_fpr,
  heldout_recall,
  heldout_accuracy,
  heldout_precision
FROM threshold_policy
ORDER BY target_fpr_cap ASC;

-- oracle_frontier
SELECT
  target_fpr_cap,
  selected_threshold,
  observed_fpr,
  recall,
  accuracy,
  deployment_eligible
FROM oracle_frontier
ORDER BY target_fpr_cap ASC;

-- composition
SELECT
  split,
  SUM(CASE WHEN label = 1 THEN count ELSE 0 END) AS attack_count,
  SUM(CASE WHEN label = 0 THEN count ELSE 0 END) AS safe_count,
  SUM(count) AS total_count
FROM dataset_composition
GROUP BY split
ORDER BY total_count DESC;

-- errors
SELECT
  CASE WHEN label = 1 THEN '漏报' ELSE '误伤' END AS error_type,
  category,
  language,
  score,
  CASE WHEN label = 1 THEN 1.0 - score ELSE score END AS error_confidence,
  query
FROM classification_errors
ORDER BY error_confidence DESC
LIMIT 30;
