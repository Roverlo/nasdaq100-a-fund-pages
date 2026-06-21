PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS funds (
  code TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  display_name TEXT,
  is_watchlist INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS refresh_runs (
  snapshot_date TEXT PRIMARY KEY,
  generated_at TEXT,
  fund_count INTEGER NOT NULL,
  base_success_count INTEGER NOT NULL,
  fee_success_count INTEGER NOT NULL,
  tracking_success_count INTEGER NOT NULL,
  source_health_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scoring_models (
  snapshot_date TEXT PRIMARY KEY,
  method TEXT NOT NULL,
  tier_method TEXT NOT NULL,
  weights_json TEXT NOT NULL,
  rules_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fund_daily_snapshots (
  snapshot_date TEXT NOT NULL,
  code TEXT NOT NULL,
  status TEXT,
  holding_horizon TEXT,
  holding_horizon_text TEXT,
  subscription_status TEXT,
  subscription_status_raw TEXT,
  fund_size_billion REAL,
  daily_limit REAL,
  agency_limit_label TEXT,
  direct_limit REAL,
  direct_limit_source TEXT,
  buy_rate REAL,
  management_fee REAL,
  custody_fee REAL,
  sales_fee REAL,
  base_annual_fee_rate REAL,
  operation_fee REAL,
  one_year REAL,
  three_year REAL,
  day_change REAL,
  tracking_index TEXT,
  tracking_error REAL,
  tracking_avg_error REAL,
  tracking_error_date TEXT,
  free_after_days INTEGER,
  redemption_rules_json TEXT NOT NULL,
  source_notes_json TEXT NOT NULL,
  PRIMARY KEY (snapshot_date, code),
  FOREIGN KEY (code) REFERENCES funds(code)
);

CREATE TABLE IF NOT EXISTS score_snapshots (
  snapshot_date TEXT NOT NULL,
  code TEXT NOT NULL,
  investing_tier TEXT NOT NULL,
  investing_score REAL NOT NULL,
  investing_rank INTEGER NOT NULL,
  PRIMARY KEY (snapshot_date, code),
  FOREIGN KEY (code) REFERENCES funds(code)
);

CREATE TABLE IF NOT EXISTS execution_alerts (
  detected_at TEXT NOT NULL,
  snapshot_date TEXT NOT NULL,
  code TEXT NOT NULL,
  alert_type TEXT NOT NULL,
  direction TEXT NOT NULL,
  label TEXT,
  previous_value REAL,
  current_value REAL,
  previous_text TEXT,
  current_text TEXT,
  retained INTEGER NOT NULL DEFAULT 0,
  retention_hours INTEGER,
  PRIMARY KEY (detected_at, code, alert_type),
  FOREIGN KEY (code) REFERENCES funds(code)
);

CREATE TABLE IF NOT EXISTS portfolio_records (
  record_date TEXT PRIMARY KEY,
  recorded_at TEXT,
  holding_total REAL NOT NULL,
  active_auto_invest_total REAL NOT NULL,
  paused_auto_invest_total REAL NOT NULL,
  market_value REAL,
  cost_basis REAL,
  profit REAL,
  return_rate REAL,
  note TEXT
);

CREATE TABLE IF NOT EXISTS portfolio_positions (
  record_date TEXT NOT NULL,
  code TEXT NOT NULL,
  holding_amount REAL NOT NULL DEFAULT 0,
  market_value REAL,
  cost_basis REAL,
  profit REAL,
  return_rate REAL,
  rating TEXT,
  score REAL,
  PRIMARY KEY (record_date, code),
  FOREIGN KEY (record_date) REFERENCES portfolio_records(record_date) ON DELETE CASCADE,
  FOREIGN KEY (code) REFERENCES funds(code)
);

CREATE TABLE IF NOT EXISTS auto_invest_plans (
  record_date TEXT NOT NULL,
  code TEXT NOT NULL,
  status TEXT NOT NULL,
  amount REAL NOT NULL DEFAULT 0,
  active_amount REAL NOT NULL DEFAULT 0,
  paused_amount REAL NOT NULL DEFAULT 0,
  frequency TEXT,
  next_debit_date TEXT,
  next_debit_business_date TEXT,
  PRIMARY KEY (record_date, code),
  FOREIGN KEY (record_date) REFERENCES portfolio_records(record_date) ON DELETE CASCADE,
  FOREIGN KEY (code) REFERENCES funds(code)
);

CREATE TABLE IF NOT EXISTS transactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  trade_date TEXT NOT NULL,
  code TEXT NOT NULL,
  transaction_type TEXT NOT NULL,
  amount REAL,
  shares REAL,
  nav REAL,
  fee REAL,
  source TEXT,
  note TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (code) REFERENCES funds(code)
);

CREATE VIEW IF NOT EXISTS v_latest_snapshot_date AS
SELECT MAX(snapshot_date) AS snapshot_date
FROM fund_daily_snapshots;

CREATE VIEW IF NOT EXISTS v_latest_fund_scores AS
SELECT
  d.snapshot_date,
  f.code,
  f.display_name,
  f.name,
  s.investing_rank,
  s.investing_tier,
  s.investing_score,
  d.one_year,
  d.three_year,
  d.tracking_error,
  d.base_annual_fee_rate,
  d.fund_size_billion,
  d.buy_rate,
  d.free_after_days,
  d.subscription_status,
  d.daily_limit,
  d.direct_limit
FROM fund_daily_snapshots d
JOIN score_snapshots s
  ON s.snapshot_date = d.snapshot_date AND s.code = d.code
JOIN funds f ON f.code = d.code
WHERE d.snapshot_date = (SELECT snapshot_date FROM v_latest_snapshot_date)
ORDER BY s.investing_rank;

CREATE VIEW IF NOT EXISTS v_recent_execution_alerts AS
SELECT
  e.detected_at,
  e.snapshot_date,
  f.code,
  f.display_name,
  f.name,
  e.alert_type,
  e.direction,
  e.label,
  e.previous_text,
  e.current_text,
  e.retained
FROM execution_alerts e
JOIN funds f ON f.code = e.code
ORDER BY e.detected_at DESC, f.code, e.alert_type;

CREATE VIEW IF NOT EXISTS v_latest_portfolio_date AS
SELECT MAX(record_date) AS record_date
FROM portfolio_records;

CREATE VIEW IF NOT EXISTS v_portfolio_latest_positions AS
SELECT
  p.record_date,
  f.code,
  f.display_name,
  f.name,
  p.holding_amount,
  p.market_value,
  p.cost_basis,
  p.profit,
  p.return_rate,
  p.rating,
  p.score,
  a.status AS auto_invest_status,
  a.amount AS auto_invest_amount,
  a.frequency,
  a.next_debit_date,
  a.next_debit_business_date
FROM portfolio_positions p
JOIN funds f ON f.code = p.code
LEFT JOIN auto_invest_plans a
  ON a.record_date = p.record_date AND a.code = p.code
WHERE p.record_date = (SELECT record_date FROM v_latest_portfolio_date)
ORDER BY COALESCE(p.holding_amount, 0) DESC, f.code;

CREATE VIEW IF NOT EXISTS v_monthly_portfolio_summary AS
SELECT
  substr(record_date, 1, 7) AS month,
  COUNT(*) AS snapshot_count,
  MIN(record_date) AS first_record_date,
  MAX(record_date) AS latest_record_date,
  ROUND(AVG(holding_total), 2) AS avg_holding_total,
  ROUND(AVG(active_auto_invest_total), 2) AS avg_active_auto_invest_total,
  ROUND(AVG(paused_auto_invest_total), 2) AS avg_paused_auto_invest_total,
  ROUND(AVG(market_value), 2) AS avg_market_value,
  ROUND(AVG(profit), 2) AS avg_profit,
  ROUND(AVG(return_rate), 4) AS avg_return_rate
FROM portfolio_records
GROUP BY substr(record_date, 1, 7)
ORDER BY month;

CREATE VIEW IF NOT EXISTS v_active_auto_invest_latest AS
SELECT
  a.record_date,
  f.code,
  f.display_name,
  f.name,
  a.amount,
  a.frequency,
  a.next_debit_date,
  a.next_debit_business_date,
  p.holding_amount,
  p.rating,
  p.score
FROM auto_invest_plans a
JOIN funds f ON f.code = a.code
LEFT JOIN portfolio_positions p
  ON p.record_date = a.record_date AND p.code = a.code
WHERE a.record_date = (SELECT record_date FROM v_latest_portfolio_date)
  AND a.status = '定投中'
ORDER BY a.amount DESC, f.code;
