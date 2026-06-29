-- Run examples from PowerShell:
-- python -c "import sqlite3; conn=sqlite3.connect('data/nasdaq_funds.db'); [print(row) for row in conn.execute(\"SELECT * FROM v_latest_fund_scores LIMIT 5\")]"

-- 1. Latest rating table, ordered by the current tier rank.
SELECT
  investing_rank,
  investing_tier,
  display_name,
  code,
  investing_score,
  three_year,
  one_year,
  tracking_error,
  base_annual_fee_rate,
  fund_size_billion
FROM v_latest_fund_scores;

-- 2. Latest auto-invest status in one view.
SELECT
  display_name,
  code,
  status,
  rating,
  score,
  auto_invest_status
FROM v_portfolio_latest_positions
WHERE status <> '候选';

-- 3. Month-level long-term status summary.
SELECT
  month,
  snapshot_count,
  first_record_date,
  latest_record_date,
  avg_active_auto_invest_count,
  avg_paused_auto_invest_count,
  avg_candidate_count
FROM v_monthly_portfolio_summary;

-- 4. Rating and score history for one fund.
SELECT
  s.snapshot_date,
  f.display_name,
  s.investing_rank,
  s.investing_tier,
  s.investing_score
FROM score_snapshots s
JOIN funds f ON f.code = s.code
WHERE s.code = '040046'
ORDER BY s.snapshot_date;

-- 5. Active auto-invest status rows, ordered by score.
SELECT
  display_name,
  code,
  status,
  rating,
  score
FROM v_active_auto_invest_latest;

-- 6. Transaction table is intentionally unused by this public-data tracker.
SELECT COUNT(*) AS transaction_rows FROM transactions;

-- 7. Recent buyability and limit changes.
SELECT
  detected_at,
  display_name,
  code,
  label,
  previous_text,
  current_text
FROM v_recent_execution_alerts
ORDER BY detected_at DESC, code, alert_type;
