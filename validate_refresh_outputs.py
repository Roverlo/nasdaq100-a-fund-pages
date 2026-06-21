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
PUBLIC_MAIN_COLUMNS = 16
FUND_COUNT = len(generator.FUND_CODES)
TRACKING_SUBPANELS = {
    "tracking-panel-overview",
    "tracking-panel-trend",
    "tracking-panel-years",
    "tracking-panel-allocation",
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
        self.header_columns = 0
        self.body_columns: list[int] = []
        self.panel_ids: set[str] = set()
        self.tracking_tab_ids: set[str] = set()
        self.tracking_panel_ids: set[str] = set()
        self.tab_controls: list[str] = []
        self.portfolio_link_found = False
        self.mobile_card_count = 0
        self.mobile_private_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        element_id = attr.get("id")
        if element_id:
            if element_id.startswith("panel-"):
                self.panel_ids.add(element_id)
            if element_id.startswith("tracking-panel-"):
                self.tracking_panel_ids.add(element_id)
            if element_id.startswith("tracking-tab-"):
                self.tracking_tab_ids.add(element_id)
        classes = set((attr.get("class") or "").split())
        if "data-mobile-card" in attr:
            self.mobile_card_count += 1
        if "mobile-card-private" in classes:
            self.mobile_private_count += 1
        if tag == "button" and "tab-button" in classes:
            control = attr.get("aria-controls")
            if control:
                self.tab_controls.append(control)
        if tag == "a" and attr.get("href") == "portfolio.html" and "tab-link" in classes:
            self.portfolio_link_found = True

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


def fail(message: str) -> None:
    raise AssertionError(message)


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
    missing = required_panels - page.panel_ids
    if missing:
        fail(f"{path.name} missing panels: {sorted(missing)}")
    missing_controls = [control for control in page.tab_controls if control not in page.panel_ids]
    if missing_controls:
        fail(f"{path.name} tab buttons point to missing panels: {missing_controls}")
    if require_portfolio_link and not page.portfolio_link_found:
        fail(f"{path.name} should link to portfolio.html for the holdings page")
    if page.tracking_panel_ids != TRACKING_SUBPANELS:
        fail(f"{path.name} tracking subpanels mismatch: {sorted(page.tracking_panel_ids)}")
    if len(page.tracking_tab_ids) != len(TRACKING_SUBPANELS):
        fail(f"{path.name} tracking subtab count expected {len(TRACKING_SUBPANELS)}, got {len(page.tracking_tab_ids)}")
    if page.mobile_card_count != FUND_COUNT:
        fail(f"{path.name} mobile cards expected {FUND_COUNT}, got {page.mobile_card_count}")
    if require_portfolio_link and page.mobile_private_count:
        fail(f"{path.name} public page should not contain private mobile holding blocks")
    if not require_portfolio_link and page.mobile_private_count != FUND_COUNT:
        fail(f"{path.name} private mobile holding blocks expected {FUND_COUNT}, got {page.mobile_private_count}")
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
    if snapshot.get("holding_plan", {}).get("holding_total") != sum(generator.HOLDING_AMOUNTS.values()):
        fail("snapshot holding total mismatch")
    if snapshot.get("auto_invest_plan", {}).get("active_total") != sum(generator.AUTO_INVEST_AMOUNTS.values()):
        fail("snapshot active auto-invest total mismatch")
    if snapshot.get("auto_invest_plan", {}).get("paused_total") != sum(generator.PAUSED_AUTO_INVEST_AMOUNTS.values()):
        fail("snapshot paused auto-invest total mismatch")
    for fund in funds:
        if not isinstance(fund, dict):
            fail("snapshot fund entry must be an object")
        for key in ("investing_rank", "investing_score", "investing_tier"):
            if fund.get(key) is None:
                fail(f"snapshot fund {fund.get('code')} missing {key}")


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
    if latest.get("holding_total") != snapshot.get("holding_plan", {}).get("holding_total"):
        fail("tracking latest holding_total mismatch")
    if latest.get("active_auto_invest_total") != snapshot.get("auto_invest_plan", {}).get("active_total"):
        fail("tracking latest active_auto_invest_total mismatch")
    if latest.get("paused_auto_invest_total") != snapshot.get("auto_invest_plan", {}).get("paused_total"):
        fail("tracking latest paused_auto_invest_total mismatch")
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
            "holding_amount": snapshot_fund.get("holding_amount"),
            "active_auto_invest_amount": snapshot_fund.get("auto_invest_amount"),
            "paused_auto_invest_amount": snapshot_fund.get("paused_auto_invest_amount"),
        }
        for key, expected in checks.items():
            if tracking_fund.get(key) != expected:
                fail(f"tracking fund {code} {key} expected {expected}, got {tracking_fund.get(key)}")


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
            SELECT holding_total, active_auto_invest_total, paused_auto_invest_total
            FROM portfolio_records
            WHERE record_date = ?
            """,
            (latest_record_date,),
        ).fetchone()
        if row is None:
            fail("SQLite missing latest portfolio record")
        expected_totals = (
            snapshot.get("holding_plan", {}).get("holding_total"),
            snapshot.get("auto_invest_plan", {}).get("active_total"),
            snapshot.get("auto_invest_plan", {}).get("paused_total"),
        )
        actual_totals = (row[0], row[1], row[2])
        if actual_totals != expected_totals:
            fail(f"SQLite portfolio totals expected {expected_totals}, got {actual_totals}")
        view_count = conn.execute("SELECT COUNT(*) FROM v_latest_fund_scores").fetchone()[0]
        if view_count != expected_fund_count:
            fail(f"SQLite v_latest_fund_scores expected {expected_fund_count}, got {view_count}")


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
