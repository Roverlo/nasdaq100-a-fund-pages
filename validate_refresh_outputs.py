import json
import re
import sqlite3
from html.parser import HTMLParser
from pathlib import Path

import generate_nasdaq_fund_table as generator


ROOT = Path(__file__).resolve().parent
FULL_HTML = ROOT / "纳指基金支付宝对比表.html"
DOCS_INDEX = ROOT / "docs" / "index.html"
DOCS_PORTFOLIO = ROOT / "docs" / "portfolio.html"
SNAPSHOT = ROOT / "nasdaq_fund_snapshot.json"
TRACKING = ROOT / generator.TRACKING_FILENAME
DATABASE = ROOT / "data" / "nasdaq_funds.db"

FULL_MAIN_COLUMNS = 18
PUBLIC_MAIN_COLUMNS = 18
FUND_COUNT = len(generator.FUND_CODES)
EXPECTED_STATUS_OPTIONS = ["定投中", "暂停定投", "候选"]
EXPECTED_SUBSCRIPTION_OPTIONS = ["允许申购", "暂停申购"]
FULL_SORT_COLUMN_INDEXES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 15, 16, 17]
PUBLIC_SORT_COLUMN_INDEXES = FULL_SORT_COLUMN_INDEXES
EXPECTED_ALERT_DIRECTIONS = {
    "subscription": {"", "opened", "paused"},
    "agency_limit": {"", "up", "down"},
    "direct_limit": {"", "up", "down"},
}
EXPECTED_LIMIT_CONFIDENCES = {
    "trading_page_verified",
    "user_trading_page_verified",
    "fund_company_disclosure",
    "fund_company_status_page",
    "official_disclosure_mirror",
    "third_party_api",
    "third_party_or_screenshot",
    "fallback_unverified",
}
TRACKING_SUBPANELS = {
    "tracking-panel-overview",
    "tracking-panel-years",
    "tracking-panel-funds",
    "tracking-panel-snapshots",
}
FULL_PANELS = {"panel-main", "panel-portfolio", "panel-tracking", "panel-scoring", "panel-sources"}
PUBLIC_PANELS = {"panel-main", "panel-tracking", "panel-scoring", "panel-sources"}


class PageInspector(HTMLParser):
    VOID_TAGS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.main_table_depth = 0
        self.in_main_table = False
        self.in_thead = False
        self.in_tbody = False
        self.in_tr = False
        self.current_cell_count = 0
        self.current_aux_table: str | None = None
        self.in_aux_thead = False
        self.in_aux_tr = False
        self.current_aux_cell_count = 0
        self.header_columns = 0
        self.body_columns: list[int] = []
        self.panel_ids: set[str] = set()
        self.tracking_tab_ids: set[str] = set()
        self.tracking_panel_ids: set[str] = set()
        self.tab_controls: list[str] = []
        self.portfolio_link_found = False
        self.mobile_card_count = 0
        self.mobile_status_block_count = 0
        self.mobile_status_attr_count = 0
        self.in_status_filter = False
        self.status_filter_depth = 0
        self.status_filter_options: list[str] = []
        self.in_subscription_filter = False
        self.subscription_filter_depth = 0
        self.subscription_filter_options: list[str] = []
        self.holding_table_count = 0
        self.auto_plan_table_count = 0
        self.tracking_history_columns = 0
        self.tracking_fund_columns = 0
        self.tracking_year_columns = 0
        self.main_sort_column_indexes: list[int] = []
        self.mobile_main_sort_column_indexes: list[int] = []
        self.plan_sort_header_count = 0
        self.mobile_plan_sort_button_count = 0
        self.generated_at_meta_count = 0
        self.refresh_check_meta_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        element_id = attr.get("id")
        if tag == "meta" and attr.get("name") == "fund-page-generated-at":
            self.generated_at_meta_count += 1
        if tag == "meta" and attr.get("name") == "fund-page-refresh-check-ms":
            self.refresh_check_meta_count += 1
        if element_id:
            if element_id.startswith("panel-"):
                self.panel_ids.add(element_id)
            if element_id.startswith("tracking-panel-"):
                self.tracking_panel_ids.add(element_id)
            if element_id.startswith("tracking-tab-"):
                self.tracking_tab_ids.add(element_id)
        classes = set((attr.get("class") or "").split())
        if tag == "table" and "holding-table" in classes:
            self.holding_table_count += 1
        if tag == "table" and "auto-plan-table" in classes:
            self.auto_plan_table_count += 1
        if tag == "table" and "tracking-history-table" in classes:
            self.current_aux_table = "tracking-history"
        if tag == "table" and "tracking-fund-table" in classes:
            self.current_aux_table = "tracking-fund"
        if tag == "table" and "tracking-year-table" in classes:
            self.current_aux_table = "tracking-year"
        if self.current_aux_table and tag == "thead":
            self.in_aux_thead = True
        if self.current_aux_table and self.in_aux_thead and tag == "tr":
            self.in_aux_tr = True
            self.current_aux_cell_count = 0
        if self.current_aux_table and self.in_aux_tr and tag in {"th", "td"}:
            self.current_aux_cell_count += 1
        if tag == "th" and "sortable" in classes and "data-column-index" in attr:
            column_index = parse_int(attr.get("data-column-index"))
            if column_index is not None:
                self.main_sort_column_indexes.append(column_index)
        if tag == "button" and "mobile-main-sort-button" in classes and "data-column-index" in attr:
            column_index = parse_int(attr.get("data-column-index"))
            if column_index is not None:
                self.mobile_main_sort_column_indexes.append(column_index)
        if tag == "th" and "sortable" in classes and "data-plan-column-index" in attr:
            self.plan_sort_header_count += 1
        if tag == "button" and "mobile-plan-sort-button" in classes and "data-plan-column-index" in attr:
            self.mobile_plan_sort_button_count += 1
        if "data-mobile-card" in attr:
            self.mobile_card_count += 1
            if "data-status" in attr:
                self.mobile_status_attr_count += 1
        if "mobile-card-status" in classes:
            self.mobile_status_block_count += 1
        if tag == "button" and "tab-button" in classes:
            control = attr.get("aria-controls")
            if control:
                self.tab_controls.append(control)
        if tag == "a" and attr.get("href") == "portfolio.html" and "tab-link" in classes:
            self.portfolio_link_found = True
        if tag == "div" and element_id == "status-filter":
            self.in_status_filter = True
            self.status_filter_depth = 1
            return
        if tag == "div" and element_id == "subscription-filter":
            self.in_subscription_filter = True
            self.subscription_filter_depth = 1
            return
        if self.in_status_filter:
            self.status_filter_depth += 1
            if "select-option" in classes:
                self.status_filter_options.append(attr.get("data-value") or "")
        if self.in_subscription_filter:
            self.subscription_filter_depth += 1
            if "select-option" in classes:
                self.subscription_filter_options.append(attr.get("data-value") or "")

        if tag == "table" and element_id == "main-table":
            self.in_main_table = True
            self.main_table_depth = 1
            return
        if self.in_main_table and tag not in self.VOID_TAGS:
            self.main_table_depth += 1
        if self.in_main_table and tag == "thead":
            self.in_thead = True
        if self.in_main_table and tag == "tbody":
            self.in_tbody = True
        if self.in_main_table and tag == "tr":
            self.in_tr = True
            self.current_cell_count = 0
        if self.in_main_table and self.in_tr and tag in {"th", "td"}:
            self.current_cell_count += 1

    def handle_endtag(self, tag: str) -> None:
        if self.current_aux_table and self.in_aux_tr and tag == "tr":
            if self.current_aux_table == "tracking-history":
                self.tracking_history_columns = self.current_aux_cell_count
            elif self.current_aux_table == "tracking-fund":
                self.tracking_fund_columns = self.current_aux_cell_count
            elif self.current_aux_table == "tracking-year":
                self.tracking_year_columns = self.current_aux_cell_count
            self.in_aux_tr = False
            self.current_aux_cell_count = 0
        if self.current_aux_table and tag == "thead":
            self.in_aux_thead = False
        if self.current_aux_table and tag == "table":
            self.current_aux_table = None
        if self.in_main_table and tag == "tr":
            if self.in_thead:
                self.header_columns = self.current_cell_count
            elif self.in_tbody:
                self.body_columns.append(self.current_cell_count)
            self.in_tr = False
            self.current_cell_count = 0
        if self.in_main_table and tag == "thead":
            self.in_thead = False
        if self.in_main_table and tag == "tbody":
            self.in_tbody = False
        if self.in_main_table:
            self.main_table_depth -= 1
            if self.main_table_depth == 0:
                self.in_main_table = False
        if self.in_status_filter:
            self.status_filter_depth -= 1
            if self.status_filter_depth == 0:
                self.in_status_filter = False
        if self.in_subscription_filter:
            self.subscription_filter_depth -= 1
            if self.subscription_filter_depth == 0:
                self.in_subscription_filter = False


def fail(message: str) -> None:
    raise AssertionError(message)


def parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def load_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        fail(f"missing required file: {path}")
    except json.JSONDecodeError as exc:
        fail(f"invalid json in {path}: {exc}")
    if not isinstance(payload, dict):
        fail(f"json root must be an object: {path}")
    return payload


def inspect_html(path: Path) -> tuple[str, PageInspector]:
    try:
        html = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        fail(f"missing required html: {path}")
    inspector = PageInspector()
    inspector.feed(html)
    return html, inspector


def validate_table(path: Path, expected_columns: int, expected_rows: int) -> None:
    _, page = inspect_html(path)
    if page.header_columns != expected_columns:
        fail(f"{path.name} main-table header columns expected {expected_columns}, got {page.header_columns}")
    if len(page.body_columns) != expected_rows:
        fail(f"{path.name} main-table rows expected {expected_rows}, got {len(page.body_columns)}")
    bad_rows = [index + 1 for index, count in enumerate(page.body_columns) if count != expected_columns]
    if bad_rows:
        fail(f"{path.name} body rows with wrong column count: {bad_rows[:8]}")


def validate_tabs(path: Path, required_panels: set[str], require_portfolio_link: bool = False) -> None:
    html, page = inspect_html(path)
    is_public_index = require_portfolio_link
    if page.generated_at_meta_count != 1:
        fail(f"{path.name} generated-at meta expected 1, got {page.generated_at_meta_count}")
    if page.refresh_check_meta_count != 1:
        fail(f"{path.name} refresh-check interval meta expected 1, got {page.refresh_check_meta_count}")
    if "refresh-check" not in html or "checkPublishedRefresh" not in html:
        fail(f"{path.name} missing published-page refresh polling script")
    missing = required_panels - page.panel_ids
    if missing:
        fail(f"{path.name} missing panels: {sorted(missing)}")
    missing_controls = [control for control in page.tab_controls if control not in page.panel_ids]
    if missing_controls:
        fail(f"{path.name} tab buttons point to missing panels: {missing_controls}")
    if require_portfolio_link and not page.portfolio_link_found:
        fail(f"{path.name} should link to portfolio.html for the status detail page")
    if page.tracking_panel_ids != TRACKING_SUBPANELS:
        fail(f"{path.name} tracking subpanels mismatch: {sorted(page.tracking_panel_ids)}")
    if page.tracking_year_columns != 6:
        fail(f"{path.name} tracking year columns expected 6, got {page.tracking_year_columns}")
    if page.tracking_fund_columns != 4:
        fail(f"{path.name} tracking fund columns expected 4, got {page.tracking_fund_columns}")
    if page.tracking_history_columns != 5:
        fail(f"{path.name} tracking history columns expected 5, got {page.tracking_history_columns}")
    if page.status_filter_options != EXPECTED_STATUS_OPTIONS:
        fail(f"{path.name} status filter options expected 定投中/暂停定投/候选, got {page.status_filter_options}")
    if page.subscription_filter_options != EXPECTED_SUBSCRIPTION_OPTIONS:
        fail(f"{path.name} subscription filter options expected 允许申购/暂停申购, got {page.subscription_filter_options}")
    if len(page.tracking_tab_ids) != len(TRACKING_SUBPANELS):
        fail(f"{path.name} tracking subtab count expected {len(TRACKING_SUBPANELS)}, got {len(page.tracking_tab_ids)}")
    if page.mobile_card_count != FUND_COUNT:
        fail(f"{path.name} mobile cards expected {FUND_COUNT}, got {page.mobile_card_count}")
    expected_sort_indexes = PUBLIC_SORT_COLUMN_INDEXES if is_public_index else FULL_SORT_COLUMN_INDEXES
    if page.main_sort_column_indexes != expected_sort_indexes:
        fail(f"{path.name} main sortable columns expected {expected_sort_indexes}, got {page.main_sort_column_indexes}")
    if page.mobile_main_sort_column_indexes != expected_sort_indexes:
        fail(f"{path.name} mobile main sort buttons expected {expected_sort_indexes}, got {page.mobile_main_sort_column_indexes}")
    if page.mobile_status_block_count != FUND_COUNT:
        fail(f"{path.name} mobile status blocks expected {FUND_COUNT}, got {page.mobile_status_block_count}")
    if page.holding_table_count:
        fail(f"{path.name} should not render the removed personal holding detail table")
    if require_portfolio_link:
        if page.auto_plan_table_count:
            fail(f"{path.name} public page should not contain editable status detail table")
        if page.plan_sort_header_count:
            fail(f"{path.name} public page should not contain editable status detail sort headers")
        if page.mobile_plan_sort_button_count:
            fail(f"{path.name} public page should not contain editable status detail mobile sort buttons")
    elif page.auto_plan_table_count != 1:
        fail(f"{path.name} auto-plan table expected 1, got {page.auto_plan_table_count}")
    elif page.plan_sort_header_count != 2:
        fail(f"{path.name} auto-plan sortable headers expected 2, got {page.plan_sort_header_count}")
    elif page.mobile_plan_sort_button_count != 2:
        fail(f"{path.name} mobile auto-plan sort buttons expected 2, got {page.mobile_plan_sort_button_count}")
    forbidden_patterns = [
        r"C:\\ALL_in_H\\",
        r"tracking-file",
        r"Staticrypt",
        r"staticrypt",
        r"password",
    ]
    for pattern in forbidden_patterns:
        if re.search(pattern, html, flags=re.I):
            fail(f"{path.name} contains forbidden public marker: {pattern}")


def validate_snapshot(snapshot: dict) -> None:
    funds = snapshot.get("funds")
    if not isinstance(funds, list):
        fail("snapshot funds must be a list")
    if len(funds) != FUND_COUNT:
        fail(f"snapshot fund count expected {FUND_COUNT}, got {len(funds)}")
    codes = [fund.get("code") for fund in funds if isinstance(fund, dict)]
    if set(codes) != set(generator.FUND_CODES):
        fail("snapshot fund codes do not match generator.FUND_CODES")
    weights = snapshot.get("scoring_model", {}).get("weights")
    expected_weights = {rule["key"]: rule["weight"] for rule in generator.SCORING_RULES}
    if weights != expected_weights:
        fail("snapshot scoring weights do not match generator.SCORING_RULES")
    source_health = snapshot.get("source_health")
    if not isinstance(source_health, dict):
        fail("snapshot missing source_health")
    checks = source_health.get("checks")
    if not isinstance(checks, dict):
        fail("snapshot source_health.checks must be an object")
    for key in ("base_data", "fee_data", "tracking_error"):
        check = checks.get(key)
        if not isinstance(check, dict):
            fail(f"snapshot source_health missing {key}")
        success_count = check.get("success_count")
        required = check.get("required_success_count")
        if success_count != required or success_count != FUND_COUNT:
            fail(
                f"source health {key} expected {FUND_COUNT}/{FUND_COUNT}, "
                f"got {success_count}/{required}; failed={check.get('failed_codes')}"
            )
    auto_plan = snapshot.get("auto_invest_plan", {})
    if auto_plan.get("status_policy") != generator.AUTO_INVEST_STATUS_POLICY:
        fail("snapshot auto-invest status policy mismatch")
    if auto_plan.get("active_count") != len(generator.AUTO_INVESTING_CODES):
        fail("snapshot active auto-invest count mismatch")
    if auto_plan.get("paused_count") != len(generator.PAUSED_AUTO_INVESTING_CODES):
        fail("snapshot paused auto-invest count mismatch")
    expected_candidate_count = len([code for code in generator.FUND_CODES if generator.fund_status(code) == "候选"])
    if auto_plan.get("candidate_count") != expected_candidate_count:
        fail("snapshot candidate count mismatch")
    if auto_plan.get("active_codes") != sorted(generator.AUTO_INVESTING_CODES):
        fail("snapshot active auto-invest codes mismatch")
    if auto_plan.get("paused_codes") != sorted(generator.PAUSED_AUTO_INVESTING_CODES):
        fail("snapshot paused auto-invest codes mismatch")
    if auto_plan.get("status_summary") != generator.AUTO_INVEST_STATUS_SUMMARY:
        fail("snapshot auto-invest status summary mismatch")
    if "holding_plan" in snapshot:
        fail("snapshot should not contain personal holding_plan")
    monitor = snapshot.get("execution_monitor")
    if not isinstance(monitor, dict):
        fail("snapshot missing execution_monitor")
    if monitor.get("refresh_times_beijing") != list(generator.AUTO_REFRESH_TIMES_BEIJING):
        fail("snapshot execution monitor refresh times mismatch")
    if monitor.get("alert_retention_hours") != generator.EXECUTION_ALERT_RETENTION_HOURS:
        fail("snapshot execution monitor retention mismatch")
    if monitor.get("agency_limit_overrides") != generator.AGENCY_LIMIT_OVERRIDES:
        fail("snapshot agency limit overrides mismatch")
    alerts = snapshot.get("execution_alerts")
    if not isinstance(alerts, dict):
        fail("snapshot execution_alerts must be an object")
    if set(alerts) - set(codes):
        fail("snapshot execution_alerts contains unknown fund code")
    for fund in funds:
        if not isinstance(fund, dict):
            fail("snapshot fund entry must be an object")
        code = fund.get("code")
        if fund.get("status") not in set(EXPECTED_STATUS_OPTIONS):
            fail(f"snapshot fund {code} has invalid status {fund.get('status')}")
        forbidden_personal_keys = {
            "holding_amount",
            "auto_invest_amount",
            "paused_auto_invest_amount",
            "projected_auto_invest_addition",
            "projected_holding_amount",
        }
        leaked = forbidden_personal_keys & set(fund)
        if leaked:
            fail(f"snapshot fund {code} leaks personal amount keys: {sorted(leaked)}")
        if fund.get("subscription_status") not in set(EXPECTED_SUBSCRIPTION_OPTIONS):
            fail(f"snapshot fund {code} has invalid subscription_status {fund.get('subscription_status')}")
        agency_confidence = fund.get("agency_limit_confidence")
        direct_confidence = fund.get("direct_limit_confidence")
        if agency_confidence not in EXPECTED_LIMIT_CONFIDENCES:
            fail(f"snapshot fund {code} has invalid agency_limit_confidence {agency_confidence}")
        if direct_confidence not in EXPECTED_LIMIT_CONFIDENCES:
            fail(f"snapshot fund {code} has invalid direct_limit_confidence {direct_confidence}")
        if not fund.get("agency_limit_source"):
            fail(f"snapshot fund {code} missing agency_limit_source")
        if not fund.get("direct_limit_source"):
            fail(f"snapshot fund {code} missing direct_limit_source")
        if "脚本内置回退值" in str(fund.get("direct_limit_source")):
            fail(f"snapshot fund {code} still uses script fallback direct limit")
        if direct_confidence == "fallback_unverified" and fund.get("direct_limit") is not None:
            fail(f"snapshot fund {code} has numeric direct_limit with fallback_unverified confidence")
        agency_override = generator.AGENCY_LIMIT_OVERRIDES.get(str(code))
        if agency_override:
            expected_limit = generator.number_or_none(agency_override.get("limit"))
            if fund.get("daily_limit") != expected_limit:
                fail(f"snapshot fund {code} agency limit override expected {expected_limit}, got {fund.get('daily_limit')}")
            notes = fund.get("source_notes")
            if not isinstance(notes, list) or not any("代销限额校准" in str(note) for note in notes):
                fail(f"snapshot fund {code} agency limit override missing source note")
        for key in ("investing_rank", "investing_score", "investing_tier"):
            if fund.get(key) is None:
                fail(f"snapshot fund {code} missing {key}")
        fund_alert = fund.get("execution_alert")
        if fund_alert is None:
            fail(f"snapshot fund {code} missing execution_alert")
        if not isinstance(fund_alert, dict):
            fail(f"snapshot fund {code} execution_alert must be an object")
        if fund_alert != alerts.get(code, {}):
            fail(f"snapshot fund {code} execution_alert does not match top-level execution_alerts")
        if fund_alert:
            summary = fund_alert.get("summary")
            if not isinstance(summary, list):
                fail(f"snapshot fund {code} execution alert summary must be a list")
            for key, allowed in EXPECTED_ALERT_DIRECTIONS.items():
                item = fund_alert.get(key)
                if not isinstance(item, dict):
                    fail(f"snapshot fund {code} execution alert missing {key}")
                direction = item.get("direction", "")
                if direction not in allowed:
                    fail(f"snapshot fund {code} execution alert {key} has invalid direction {direction}")


def validate_tracking(snapshot: dict, tracking: dict) -> None:
    records = tracking.get("records")
    if not isinstance(records, list) or not records:
        fail("tracking records must be a non-empty list")
    today = generator.now_beijing().strftime("%Y-%m-%d")
    dates = [str(record.get("date") or record.get("recorded_at") or "")[:10] for record in records if isinstance(record, dict)]
    if len(dates) != len(set(dates)):
        fail("tracking records contain duplicate date entries")
    latest = records[-1]
    if not isinstance(latest, dict):
        fail("latest tracking record must be an object")
    latest_date = str(latest.get("date") or latest.get("recorded_at") or "")[:10]
    if latest_date != today:
        fail(f"latest tracking date expected {today}, got {latest_date}")
    auto_plan = snapshot.get("auto_invest_plan", {})
    if latest.get("active_auto_invest_count") != auto_plan.get("active_count"):
        fail("tracking latest active_auto_invest_count mismatch")
    if latest.get("paused_auto_invest_count") != auto_plan.get("paused_count"):
        fail("tracking latest paused_auto_invest_count mismatch")
    if latest.get("candidate_count") != auto_plan.get("candidate_count"):
        fail("tracking latest candidate_count mismatch")
    if latest.get("status_policy") != auto_plan.get("status_policy"):
        fail("tracking latest status_policy mismatch")
    for forbidden in (
        "holding_total",
        "active_auto_invest_total",
        "paused_auto_invest_total",
        "projected_auto_invest_periods",
        "projected_auto_invest_addition_total",
        "projected_holding_total",
        "market_value",
        "cost_basis",
        "profit",
        "return_rate",
    ):
        if forbidden in latest:
            fail(f"tracking latest should not contain {forbidden}")
    funds = latest.get("funds")
    if not isinstance(funds, dict):
        fail("latest tracking funds must be an object")
    snapshot_by_code = {fund["code"]: fund for fund in snapshot["funds"]}
    if set(funds) != set(snapshot_by_code):
        fail("tracking latest fund set does not match snapshot")
    for code, snapshot_fund in snapshot_by_code.items():
        tracking_fund = funds.get(code)
        if not isinstance(tracking_fund, dict):
            fail(f"tracking fund {code} must be an object")
        checks = {
            "rating": snapshot_fund.get("investing_tier"),
            "score": snapshot_fund.get("investing_score"),
            "status": snapshot_fund.get("status"),
        }
        for key, expected in checks.items():
            if tracking_fund.get(key) != expected:
                fail(f"tracking fund {code} {key} expected {expected}, got {tracking_fund.get(key)}")
        leaked = {
            "holding_amount",
            "active_auto_invest_amount",
            "paused_auto_invest_amount",
            "projected_auto_invest_addition",
            "projected_holding_amount",
            "market_value",
            "cost_basis",
            "profit",
            "return_rate",
        } & set(tracking_fund)
        if leaked:
            fail(f"tracking fund {code} leaks personal amount keys: {sorted(leaked)}")


def validate_database(snapshot: dict, tracking: dict) -> None:
    if not DATABASE.exists():
        fail(f"missing SQLite database: {DATABASE}")
    latest_tracking = tracking.get("records", [])[-1]
    latest_record_date = str(latest_tracking.get("date") or latest_tracking.get("recorded_at") or "")[:10]
    latest_snapshot_date = str(snapshot.get("generated_at") or "")[:10] or latest_record_date
    expected_fund_count = len(snapshot.get("funds", []))
    expected_tables = {
        "funds",
        "refresh_runs",
        "scoring_models",
        "fund_daily_snapshots",
        "score_snapshots",
        "portfolio_records",
        "portfolio_positions",
        "auto_invest_plans",
        "execution_alerts",
        "transactions",
    }
    with sqlite3.connect(DATABASE) as conn:
        existing_tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        missing = expected_tables - existing_tables
        if missing:
            fail(f"SQLite database missing tables: {sorted(missing)}")
        existing_views = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'view'"
            )
        }
        if "v_recent_execution_alerts" not in existing_views:
            fail("SQLite database missing v_recent_execution_alerts view")
        fund_count = conn.execute("SELECT COUNT(*) FROM funds").fetchone()[0]
        if fund_count != expected_fund_count:
            fail(f"SQLite funds expected {expected_fund_count}, got {fund_count}")
        for table, date_column, date_value in (
            ("fund_daily_snapshots", "snapshot_date", latest_snapshot_date),
            ("score_snapshots", "snapshot_date", latest_snapshot_date),
            ("portfolio_positions", "record_date", latest_record_date),
            ("auto_invest_plans", "record_date", latest_record_date),
        ):
            count = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {date_column} = ?",
                (date_value,),
            ).fetchone()[0]
            if count != expected_fund_count:
                fail(f"SQLite {table} expected {expected_fund_count} rows for {date_value}, got {count}")
        row = conn.execute(
            """
            SELECT active_auto_invest_count, paused_auto_invest_count, candidate_count, status_policy
            FROM portfolio_records
            WHERE record_date = ?
            """,
            (latest_record_date,),
        ).fetchone()
        if row is None:
            fail("SQLite missing latest portfolio record")
        expected_totals = (
            snapshot.get("auto_invest_plan", {}).get("active_count"),
            snapshot.get("auto_invest_plan", {}).get("paused_count"),
            snapshot.get("auto_invest_plan", {}).get("candidate_count"),
            snapshot.get("auto_invest_plan", {}).get("status_policy"),
        )
        actual_totals = (row[0], row[1], row[2], row[3])
        if actual_totals != expected_totals:
            fail(f"SQLite portfolio status totals expected {expected_totals}, got {actual_totals}")
        grouped_status_rows = dict(
            conn.execute(
                "SELECT status, COUNT(*) FROM auto_invest_plans WHERE record_date = ? GROUP BY status",
                (latest_record_date,),
            ).fetchall()
        )
        status_rows = {status: int(grouped_status_rows.get(status, 0)) for status in EXPECTED_STATUS_OPTIONS}
        expected_status_rows = {
            "定投中": snapshot.get("auto_invest_plan", {}).get("active_count"),
            "暂停定投": snapshot.get("auto_invest_plan", {}).get("paused_count"),
            "候选": snapshot.get("auto_invest_plan", {}).get("candidate_count"),
        }
        if status_rows != expected_status_rows:
            fail(f"SQLite auto-invest status counts expected {expected_status_rows}, got {status_rows}")
        view_count = conn.execute("SELECT COUNT(*) FROM v_latest_fund_scores").fetchone()[0]
        if view_count != expected_fund_count:
            fail(f"SQLite v_latest_fund_scores expected {expected_fund_count}, got {view_count}")
        expected_alert_rows = 0
        expected_alert_keys = []
        for code, alert in snapshot.get("execution_alerts", {}).items():
            if not isinstance(alert, dict):
                continue
            detected_at = str(alert.get("detected_at") or snapshot.get("generated_at") or "")
            for key in ("subscription", "agency_limit", "direct_limit"):
                item = alert.get(key)
                if isinstance(item, dict) and item.get("direction"):
                    expected_alert_rows += 1
                    expected_alert_keys.append((detected_at, str(code), key))
        actual_alert_rows = conn.execute("SELECT COUNT(*) FROM execution_alerts").fetchone()[0]
        if actual_alert_rows < expected_alert_rows:
            fail(f"SQLite execution_alerts expected at least {expected_alert_rows}, got {actual_alert_rows}")
        for detected_at, code, alert_type in expected_alert_keys:
            row = conn.execute(
                """
                SELECT 1
                FROM execution_alerts
                WHERE detected_at = ? AND code = ? AND alert_type = ?
                """,
                (detected_at, code, alert_type),
            ).fetchone()
            if row is None:
                fail(f"SQLite execution_alerts missing current alert {detected_at} {code} {alert_type}")
        view_alert_rows = conn.execute("SELECT COUNT(*) FROM v_recent_execution_alerts").fetchone()[0]
        if view_alert_rows < expected_alert_rows:
            fail(f"SQLite v_recent_execution_alerts expected at least {expected_alert_rows}, got {view_alert_rows}")


def main() -> int:
    validate_table(FULL_HTML, FULL_MAIN_COLUMNS, FUND_COUNT)
    validate_table(DOCS_PORTFOLIO, FULL_MAIN_COLUMNS, FUND_COUNT)
    validate_table(DOCS_INDEX, PUBLIC_MAIN_COLUMNS, FUND_COUNT)
    validate_tabs(FULL_HTML, FULL_PANELS)
    validate_tabs(DOCS_PORTFOLIO, FULL_PANELS)
    validate_tabs(DOCS_INDEX, PUBLIC_PANELS, require_portfolio_link=True)
    snapshot = load_json(SNAPSHOT)
    tracking = load_json(TRACKING)
    validate_snapshot(snapshot)
    validate_tracking(snapshot, tracking)
    validate_database(snapshot, tracking)
    print("refresh output validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
