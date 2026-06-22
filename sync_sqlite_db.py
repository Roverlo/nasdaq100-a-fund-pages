import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_SNAPSHOT = ROOT / "nasdaq_fund_snapshot.json"
DEFAULT_TRACKING = ROOT / "portfolio_tracking.json"
DEFAULT_DB = ROOT / "data" / "nasdaq_funds.db"
SCHEMA = ROOT / "data" / "schema.sql"


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise SystemExit(f"missing required json: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid json in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"json root must be an object: {path}")
    return payload


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def snapshot_date(snapshot: dict[str, Any], tracking: dict[str, Any]) -> str:
    generated_at = str(snapshot.get("generated_at") or "")
    if len(generated_at) >= 10:
        return generated_at[:10]
    records = tracking_records(tracking)
    if records:
        value = str(records[-1].get("date") or records[-1].get("recorded_at") or "")
        if len(value) >= 10:
            return value[:10]
    raise SystemExit("cannot determine snapshot date from snapshot or tracking json")


def tracking_records(tracking: dict[str, Any]) -> list[dict[str, Any]]:
    records = tracking.get("records")
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, dict)]


def record_date(record: dict[str, Any]) -> str:
    value = str(record.get("date") or record.get("recorded_at") or "")
    return value[:10] if len(value) >= 10 else ""


def db_value(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    if value == "":
        return None
    return value


def existing_row(conn: sqlite3.Connection, table: str, where: str, params: tuple[Any, ...]) -> sqlite3.Row | None:
    query = f"SELECT * FROM {table} WHERE {where}"
    return conn.execute(query, params).fetchone()


def upsert_if_changed(
    conn: sqlite3.Connection,
    table: str,
    key_columns: list[str],
    values: dict[str, Any],
    volatile_columns: set[str] | None = None,
) -> None:
    key_values = tuple(values[column] for column in key_columns)
    where = " AND ".join(f"{column} = ?" for column in key_columns)
    current = existing_row(conn, table, where, key_values)
    normalized = {key: db_value(value) for key, value in values.items()}
    if current is None:
        columns = list(normalized)
        placeholders = ", ".join("?" for _ in columns)
        conn.execute(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
            [normalized[column] for column in columns],
        )
        return
    volatile_columns = volatile_columns or set()
    changed = any(current[column] != normalized[column] for column in normalized if column not in volatile_columns)
    if not changed:
        return
    update_columns = [column for column in normalized if column not in key_columns]
    if not update_columns:
        return
    assignments = ", ".join(f"{column} = ?" for column in update_columns)
    conn.execute(
        f"UPDATE {table} SET {assignments} WHERE {where}",
        [normalized[column] for column in update_columns] + list(key_values),
    )


def apply_schema(conn: sqlite3.Connection) -> None:
    if not SCHEMA.exists():
        raise SystemExit(f"missing schema file: {SCHEMA}")
    for view in (
        "v_recent_execution_alerts",
        "v_active_auto_invest_latest",
        "v_monthly_portfolio_summary",
        "v_portfolio_latest_positions",
        "v_latest_portfolio_date",
        "v_latest_fund_scores",
        "v_latest_snapshot_date",
    ):
        conn.execute(f"DROP VIEW IF EXISTS {view}")
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    ensure_column(conn, "auto_invest_plans", "next_debit_business_date", "TEXT")
    ensure_column(conn, "fund_daily_snapshots", "agency_limit_source", "TEXT")
    ensure_column(conn, "fund_daily_snapshots", "agency_limit_confidence", "TEXT")
    ensure_column(conn, "fund_daily_snapshots", "direct_limit_confidence", "TEXT")
    upsert_if_changed(
        conn,
        "schema_migrations",
        ["version"],
        {"version": 1, "name": "initial fund snapshot and portfolio schema"},
    )
    upsert_if_changed(
        conn,
        "schema_migrations",
        ["version"],
        {"version": 2, "name": "execution alerts for subscription and limit changes"},
    )


def ensure_column(conn: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def display_name(name: str) -> str:
    for suffix in (
        "纳斯达克100指数发起式(QDII)A",
        "纳斯达克100ETF发起联接(QDII)A",
        "纳斯达克100指数(QDII)A",
        "纳斯达克100ETF联接(QDII)A",
        "纳斯达克100指数(QDII)",
    ):
        if suffix in name:
            return name.split(suffix, 1)[0].strip()
    return name[:8]


def tracking_name_map(tracking: dict[str, Any]) -> dict[str, str]:
    records = tracking_records(tracking)
    if not records:
        return {}
    funds = records[-1].get("funds")
    if not isinstance(funds, dict):
        return {}
    names: dict[str, str] = {}
    for code, item in funds.items():
        if isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"].strip():
            names[str(code)] = item["name"].strip()
    return names


def sync_snapshot(conn: sqlite3.Connection, snapshot: dict[str, Any], tracking: dict[str, Any]) -> str:
    date_key = snapshot_date(snapshot, tracking)
    funds = snapshot.get("funds")
    if not isinstance(funds, list) or not funds:
        raise SystemExit("snapshot funds must be a non-empty list")
    short_names = tracking_name_map(tracking)
    source_health = snapshot.get("source_health")
    if not isinstance(source_health, dict):
        raise SystemExit("snapshot missing source_health")
    checks = source_health.get("checks")
    if not isinstance(checks, dict):
        raise SystemExit("snapshot missing source_health.checks")

    upsert_if_changed(
        conn,
        "refresh_runs",
        ["snapshot_date"],
        {
            "snapshot_date": date_key,
            "generated_at": snapshot.get("generated_at"),
            "fund_count": source_health.get("fund_count") or len(funds),
            "base_success_count": checks.get("base_data", {}).get("success_count"),
            "fee_success_count": checks.get("fee_data", {}).get("success_count"),
            "tracking_success_count": checks.get("tracking_error", {}).get("success_count"),
            "source_health_json": stable_json(source_health),
        },
        volatile_columns={"generated_at"},
    )

    scoring_model = snapshot.get("scoring_model")
    if not isinstance(scoring_model, dict):
        raise SystemExit("snapshot missing scoring_model")
    upsert_if_changed(
        conn,
        "scoring_models",
        ["snapshot_date"],
        {
            "snapshot_date": date_key,
            "method": scoring_model.get("method") or "",
            "tier_method": scoring_model.get("tier_method") or "",
            "weights_json": stable_json(scoring_model.get("weights") or {}),
            "rules_json": stable_json(scoring_model.get("rules") or []),
        },
    )

    for fund in funds:
        if not isinstance(fund, dict):
            raise SystemExit("snapshot fund entry must be an object")
        code = str(fund.get("code") or "")
        name = str(fund.get("name") or "")
        if not code or not name:
            raise SystemExit(f"snapshot fund missing code or name: {fund}")
        upsert_if_changed(
            conn,
            "funds",
            ["code"],
            {"code": code, "name": name, "display_name": short_names.get(code) or display_name(name), "is_watchlist": 1},
        )
        upsert_if_changed(
            conn,
            "fund_daily_snapshots",
            ["snapshot_date", "code"],
            {
                "snapshot_date": date_key,
                "code": code,
                "status": fund.get("status"),
                "holding_horizon": fund.get("holding_horizon"),
                "holding_horizon_text": fund.get("holding_horizon_text"),
                "subscription_status": fund.get("subscription_status"),
                "subscription_status_raw": fund.get("subscription_status_raw"),
                "fund_size_billion": fund.get("fund_size_billion"),
                "daily_limit": fund.get("daily_limit"),
                "agency_limit_label": fund.get("agency_limit_label"),
                "agency_limit_source": fund.get("agency_limit_source"),
                "agency_limit_confidence": fund.get("agency_limit_confidence"),
                "direct_limit": fund.get("direct_limit"),
                "direct_limit_source": fund.get("direct_limit_source"),
                "direct_limit_confidence": fund.get("direct_limit_confidence"),
                "buy_rate": fund.get("buy_rate"),
                "management_fee": fund.get("management_fee"),
                "custody_fee": fund.get("custody_fee"),
                "sales_fee": fund.get("sales_fee"),
                "base_annual_fee_rate": fund.get("base_annual_fee_rate"),
                "operation_fee": fund.get("operation_fee"),
                "one_year": fund.get("one_year"),
                "three_year": fund.get("three_year"),
                "day_change": fund.get("day_change"),
                "tracking_index": fund.get("tracking_index"),
                "tracking_error": fund.get("tracking_error"),
                "tracking_avg_error": fund.get("tracking_avg_error"),
                "tracking_error_date": fund.get("tracking_error_date"),
                "free_after_days": fund.get("free_after_days"),
                "redemption_rules_json": stable_json(fund.get("redemption_rules") or []),
                "source_notes_json": stable_json(fund.get("source_notes") or []),
            },
        )
        upsert_if_changed(
            conn,
            "score_snapshots",
            ["snapshot_date", "code"],
            {
                "snapshot_date": date_key,
                "code": code,
                "investing_tier": fund.get("investing_tier"),
                "investing_score": fund.get("investing_score"),
                "investing_rank": fund.get("investing_rank"),
            },
        )
    sync_execution_alerts(conn, snapshot, date_key)
    return date_key


def sync_execution_alerts(conn: sqlite3.Connection, snapshot: dict[str, Any], date_key: str) -> None:
    alerts = snapshot.get("execution_alerts")
    if not isinstance(alerts, dict):
        return
    for code, alert in alerts.items():
        if not isinstance(alert, dict):
            continue
        detected_at = str(alert.get("detected_at") or snapshot.get("generated_at") or "")
        if not detected_at:
            continue
        detected_date = detected_at[:10] if len(detected_at) >= 10 else date_key
        retention_hours = alert.get("retention_hours")
        for alert_type in ("subscription", "agency_limit", "direct_limit"):
            item = alert.get(alert_type)
            if not isinstance(item, dict) or not item.get("direction"):
                continue
            upsert_if_changed(
                conn,
                "execution_alerts",
                ["detected_at", "code", "alert_type"],
                {
                    "detected_at": detected_at,
                    "snapshot_date": detected_date,
                    "code": str(code),
                    "alert_type": alert_type,
                    "direction": item.get("direction"),
                    "label": item.get("label") or "",
                    "previous_value": item.get("previous"),
                    "current_value": item.get("current"),
                    "previous_text": item.get("previous_text") or item.get("previous") or "",
                    "current_text": item.get("current_text") or item.get("current") or "",
                    "retained": 0,
                    "retention_hours": retention_hours,
                },
            )


def sync_tracking(conn: sqlite3.Connection, tracking: dict[str, Any], snapshot: dict[str, Any]) -> str:
    records = tracking_records(tracking)
    if not records:
        raise SystemExit("tracking records must be a non-empty list")
    fund_codes = {str(fund.get("code")) for fund in snapshot.get("funds", []) if isinstance(fund, dict)}
    plan = snapshot.get("auto_invest_plan") if isinstance(snapshot.get("auto_invest_plan"), dict) else {}
    frequency = plan.get("frequency")
    next_debit_date = plan.get("next_debit_date")
    next_debit_business_date = plan.get("next_debit_business_date")
    latest_date = ""
    for record in records:
        date_key = record_date(record)
        if not date_key:
            raise SystemExit(f"tracking record missing date: {record}")
        latest_date = date_key
        record_frequency = record.get("auto_invest_frequency") or frequency
        record_next_debit_date = record.get("next_debit_date") or next_debit_date
        record_next_debit_business_date = record.get("next_debit_business_date") or next_debit_business_date
        upsert_if_changed(
            conn,
            "portfolio_records",
            ["record_date"],
            {
                "record_date": date_key,
                "recorded_at": record.get("recorded_at"),
                "holding_total": record.get("holding_total") or 0,
                "active_auto_invest_total": record.get("active_auto_invest_total") or 0,
                "paused_auto_invest_total": record.get("paused_auto_invest_total") or 0,
                "market_value": record.get("market_value"),
                "cost_basis": record.get("cost_basis"),
                "profit": record.get("profit"),
                "return_rate": record.get("return_rate"),
                "note": record.get("note"),
            },
            volatile_columns={"recorded_at"},
        )
        funds = record.get("funds")
        if not isinstance(funds, dict):
            raise SystemExit(f"tracking record {date_key} missing funds")
        for code, item in funds.items():
            if code not in fund_codes:
                continue
            if not isinstance(item, dict):
                continue
            active_amount = item.get("active_auto_invest_amount") or 0
            paused_amount = item.get("paused_auto_invest_amount") or 0
            status = "定投中" if active_amount else ("暂停定投" if paused_amount else "未定投")
            amount = active_amount if active_amount else paused_amount
            upsert_if_changed(
                conn,
                "portfolio_positions",
                ["record_date", "code"],
                {
                    "record_date": date_key,
                    "code": code,
                    "holding_amount": item.get("holding_amount") or 0,
                    "market_value": item.get("market_value"),
                    "cost_basis": item.get("cost_basis"),
                    "profit": item.get("profit"),
                    "return_rate": item.get("return_rate"),
                    "rating": item.get("rating"),
                    "score": item.get("score"),
                },
            )
            upsert_if_changed(
                conn,
                "auto_invest_plans",
                ["record_date", "code"],
                {
                    "record_date": date_key,
                    "code": code,
                    "status": status,
                    "amount": amount,
                    "active_amount": active_amount,
                    "paused_amount": paused_amount,
                    "frequency": record_frequency,
                    "next_debit_date": record_next_debit_date,
                    "next_debit_business_date": record_next_debit_business_date,
                },
            )
    return latest_date


def validate_database(conn: sqlite3.Connection, snapshot: dict[str, Any], latest_snapshot_date: str, latest_record_date: str) -> None:
    expected_count = len(snapshot.get("funds") or [])
    checks = {
        "funds": conn.execute("SELECT COUNT(*) FROM funds").fetchone()[0],
        "fund_daily_snapshots": conn.execute(
            "SELECT COUNT(*) FROM fund_daily_snapshots WHERE snapshot_date = ?", (latest_snapshot_date,)
        ).fetchone()[0],
        "score_snapshots": conn.execute(
            "SELECT COUNT(*) FROM score_snapshots WHERE snapshot_date = ?", (latest_snapshot_date,)
        ).fetchone()[0],
        "portfolio_positions": conn.execute(
            "SELECT COUNT(*) FROM portfolio_positions WHERE record_date = ?", (latest_record_date,)
        ).fetchone()[0],
        "auto_invest_plans": conn.execute(
            "SELECT COUNT(*) FROM auto_invest_plans WHERE record_date = ?", (latest_record_date,)
        ).fetchone()[0],
    }
    for table, count in checks.items():
        if count != expected_count:
            raise SystemExit(f"database {table} expected {expected_count}, got {count}")
    portfolio = conn.execute(
        """
        SELECT holding_total, active_auto_invest_total, paused_auto_invest_total
        FROM portfolio_records
        WHERE record_date = ?
        """,
        (latest_record_date,),
    ).fetchone()
    if portfolio is None:
        raise SystemExit("database missing latest portfolio record")
    holding_plan = snapshot.get("holding_plan") if isinstance(snapshot.get("holding_plan"), dict) else {}
    auto_plan = snapshot.get("auto_invest_plan") if isinstance(snapshot.get("auto_invest_plan"), dict) else {}
    expected_totals = (
        holding_plan.get("holding_total"),
        auto_plan.get("active_total"),
        auto_plan.get("paused_total"),
    )
    actual_totals = (portfolio[0], portfolio[1], portfolio[2])
    if actual_totals != expected_totals:
        raise SystemExit(f"database portfolio totals expected {expected_totals}, got {actual_totals}")


def sync_database(snapshot_path: Path, tracking_path: Path, db_path: Path) -> None:
    snapshot = load_json(snapshot_path)
    tracking = load_json(tracking_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        apply_schema(conn)
        latest_snapshot_date = sync_snapshot(conn, snapshot, tracking)
        latest_record_date = sync_tracking(conn, tracking, snapshot)
        validate_database(conn, snapshot, latest_snapshot_date, latest_record_date)
        conn.commit()
    print(f"synced SQLite database: {db_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync generated fund JSON files into SQLite.")
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--tracking", type=Path, default=DEFAULT_TRACKING)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    sync_database(args.snapshot, args.tracking, args.db)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
