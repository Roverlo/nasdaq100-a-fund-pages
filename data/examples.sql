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

-- 2. Latest holdings and auto-invest plan in one view.
SELECT
  display_name,
  code,
  holding_amount,
  rating,
  score,
  auto_invest_status,
  auto_invest_amount,
  frequency,
  next_debit_date,
  next_debit_business_date
FROM v_portfolio_latest_positions
WHERE holding_amount > 0 OR auto_invest_amount > 0;

-- 3. Month-level long-term portfolio summary.
SELECT
  month,
  snapshot_count,
  first_record_date,
  latest_record_date,
  avg_holding_total,
  avg_active_auto_invest_total,
  avg_market_value,
  avg_profit,
  avg_return_rate
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

-- 5. Active auto-invest plans, ordered by amount.
SELECT
  display_name,
  code,
  amount,
  frequency,
  next_debit_business_date,
  holding_amount,
  rating,
  score
FROM v_active_auto_invest_latest;

-- 6. Transaction table is for confirmed trades only; scheduled auto-invest plans do not change holding_total by themselves.
-- INSERT INTO transactions (trade_date, code, transaction_type, amount, shares, nav, fee, source, note)
-- VALUES ('2026-06-21', '040046', 'buy', 10, NULL, NULL, 0, '支付宝', '日定投');
