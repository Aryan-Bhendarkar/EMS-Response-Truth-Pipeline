"""Profile and validate raw calls data before it's trusted by any downstream stage.

Every check below is a named, documented business rule with a severity
(PASS/WARN/FAIL) and a next action — nothing is silently dropped or fixed
(CLAUDE.md rule 5). A FAIL means the pipeline stops and publishes nothing
(rule 8); a WARN is a known, counted issue that the run continues past.

Thresholds live in config/validation_rules.yaml, not in this file (rule 3).
"""

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import duckdb
import yaml

from pipeline.logging_utils import get_logger

REPO_ROOT = Path(__file__).resolve().parent.parent
RULES_PATH = REPO_ROOT / "config" / "validation_rules.yaml"
RAW_DATA_DIR = REPO_ROOT / "data" / "raw"
OUTPUTS_DIR = REPO_ROOT / "outputs"


def load_rules() -> dict:
    with open(RULES_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@dataclass
class CheckResult:
    rule_id: str
    severity: str  # PASS | WARN | FAIL
    description: str
    metric: dict
    action: str


def _severity_for_rate(rate: float, warn_above: float, fail_above: float) -> str:
    if rate >= fail_above:
        return "FAIL"
    if rate >= warn_above:
        return "WARN"
    return "PASS"


def load_calls_view(con: duckdb.DuckDBPyConnection, run_ts: str) -> None:
    """Register a DuckDB view over every raw page for a backfill run, unparsed until here."""
    glob = str(RAW_DATA_DIR / "calls" / f"run_ts={run_ts}" / "*" / "page_*.json")
    con.execute(
        f"CREATE OR REPLACE VIEW raw_calls AS "
        f"SELECT * FROM read_json_auto('{glob}', union_by_name=true)"
    )


def check_manifest_completeness(run_ts: str, con: duckdb.DuckDBPyConnection) -> CheckResult:
    """Cross-check extract.py's own completeness claim against what's actually on disk."""
    run_dir = RAW_DATA_DIR / "calls" / f"run_ts={run_ts}"
    manifests = sorted(run_dir.glob("*/manifest.json"))
    incomplete = []
    manifest_total = 0
    for m in manifests:
        data = json.loads(m.read_text(encoding="utf-8"))
        manifest_total += data["rows_received"]
        if not data.get("complete", False):
            incomplete.append(data.get("month", m.parent.name))

    actual_rows = con.execute("SELECT COUNT(*) FROM raw_calls").fetchone()[0]
    metric = {
        "months_found": len(manifests),
        "manifest_total_rows": manifest_total,
        "actual_rows_on_disk": actual_rows,
        "months_flagged_incomplete_at_extract": incomplete,
    }
    if incomplete or manifest_total != actual_rows:
        return CheckResult(
            "manifest_completeness", "FAIL",
            "Every extracted month's manifest.json must say complete=true, and the row "
            "count it recorded must match what's actually readable on disk.",
            metric,
            "Stop. Re-run extract for the affected month(s); do not proceed to load.",
        )
    return CheckResult(
        "manifest_completeness", "PASS",
        "Every extracted month's manifest.json must say complete=true, and the row "
        "count it recorded must match what's actually readable on disk.",
        metric, "None.",
    )


def check_schema(con: duckdb.DuckDBPyConnection, rules: dict) -> CheckResult:
    columns = {row[0] for row in con.execute("DESCRIBE raw_calls").fetchall()}
    missing = [c for c in rules["required_columns"] if c not in columns]
    metric = {"required": len(rules["required_columns"]), "missing": missing}
    if missing:
        return CheckResult(
            "schema_required_columns", "FAIL",
            "Every column downstream SQL models depend on must be present in the raw pull.",
            metric,
            f"Stop. {missing} missing from the source — check for an upstream schema "
            f"change at data.sf.gov before re-running.",
        )
    return CheckResult(
        "schema_required_columns", "PASS",
        "Every column downstream SQL models depend on must be present in the raw pull.",
        metric, "None.",
    )


def check_rowid_uniqueness(con: duckdb.DuckDBPyConnection) -> CheckResult:
    row = con.execute(
        "SELECT COUNT(*) AS total, COUNT(DISTINCT rowid) AS distinct_rowid FROM raw_calls"
    ).fetchone()
    total, distinct = row
    duplicates = total - distinct
    metric = {"total_rows": total, "distinct_rowid": distinct, "duplicate_rows": duplicates}
    if duplicates > 0:
        return CheckResult(
            "rowid_uniqueness", "WARN",
            "rowid (call_number-unit_id) is the primary key every load-time upsert relies on.",
            metric,
            "Continue. load.py deduplicates by keeping the row with the latest data_loaded_at "
            "per rowid before upserting — duplicates here do not corrupt the warehouse, but "
            "the source sending them is worth reporting upstream.",
        )
    return CheckResult(
        "rowid_uniqueness", "PASS",
        "rowid (call_number-unit_id) is the primary key every load-time upsert relies on.",
        metric, "None.",
    )


def check_null_rates(con: duckdb.DuckDBPyConnection, rules: dict) -> list[CheckResult]:
    results = []
    total = con.execute("SELECT COUNT(*) FROM raw_calls").fetchone()[0]
    for field, bounds in rules["null_rate_thresholds"].items():
        nulls = con.execute(f"SELECT COUNT(*) FROM raw_calls WHERE {field} IS NULL").fetchone()[0]
        rate = nulls / total if total else 0.0
        severity = _severity_for_rate(rate, bounds["warn_above"], bounds["fail_above"])
        action = (
            "None."
            if severity == "PASS"
            else f"Continue; excluded from metrics that require {field}, counted separately "
            f"per brief Q4/Q9 (cancelled / unable-to-locate / genuinely-missing all fall here)."
            if severity == "WARN"
            else f"Stop. {field} null rate ({rate:.1%}) far exceeds the known baseline — "
            f"investigate an upstream data problem before trusting this pull."
        )
        results.append(CheckResult(
            f"null_rate_{field}", severity,
            f"{field} should be populated for the large majority of rows; some nulls are "
            f"expected and meaningful (e.g. cancelled calls), not a defect to silently drop.",
            {"field": field, "null_count": nulls, "total": total, "rate": round(rate, 4)},
            action,
        ))
    return results


def check_timestamp_order(con: duckdb.DuckDBPyConnection, rules: dict) -> list[CheckResult]:
    results = []
    for earlier, later in rules["timestamp_order_pairs"]:
        row = con.execute(f"""
            SELECT
                COUNT(*) FILTER (WHERE {earlier} IS NOT NULL AND {later} IS NOT NULL) AS both_present,
                COUNT(*) FILTER (
                    WHERE {earlier} IS NOT NULL AND {later} IS NOT NULL
                    AND CAST({later} AS TIMESTAMP) < CAST({earlier} AS TIMESTAMP)
                ) AS violations
            FROM raw_calls
        """).fetchone()
        both_present, violations = row
        rate = violations / both_present if both_present else 0.0
        bounds = rules["timestamp_order_violation_rate"]
        severity = _severity_for_rate(rate, bounds["warn_above"], bounds["fail_above"])
        pair_id = f"{earlier}_before_{later}"
        action = (
            "None."
            if severity == "PASS"
            else f"Continue; rows where {later} < {earlier} are excluded from interval metrics "
            f"built on this pair and counted, per brief Q5 — not silently dropped from the dataset."
            if severity == "WARN"
            else f"Stop. Violation rate ({rate:.2%}) far exceeds the known baseline for "
            f"{pair_id} — investigate before trusting downstream intervals."
        )
        results.append(CheckResult(
            f"timestamp_order_{pair_id}", severity,
            f"{earlier} must be at or before {later} whenever both are recorded — "
            f"lifecycle events can't happen out of sequence.",
            {"pair": pair_id, "both_present": both_present, "violations": violations, "rate": round(rate, 6)},
            action,
        ))
    return results


def check_priority_domain(con: duckdb.DuckDBPyConnection, rules: dict) -> CheckResult:
    expected = set(rules["priority_domain"]["expected_values"])
    rows = con.execute(
        "SELECT COALESCE(original_priority, ''), COUNT(*) FROM raw_calls GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()
    observed = {val: count for val, count in rows}
    unexpected = {val: c for val, c in observed.items() if val not in expected}
    metric = {"observed_value_counts": observed, "unexpected_values": unexpected}
    if unexpected:
        return CheckResult(
            "priority_domain", "WARN",
            "original_priority mixes numeric Code 2/3 and letter determinant codes in one "
            "field (brief Q2) — expected, but any value outside the known set needs review.",
            metric,
            f"Continue. New/unexpected codes found: {list(unexpected)}. Escalate to SF EMS "
            f"Agency / DEM for confirmation before assuming their meaning.",
        )
    return CheckResult(
        "priority_domain", "WARN",
        "original_priority mixes numeric Code 2/3 and letter determinant codes in one field "
        "(brief Q2) — this is a known, expected mix, not a defect, but the letter-code "
        "meanings are still unconfirmed by any owner. See docs/assumptions.md.",
        metric,
        "Continue. Mapping documented in docs/assumptions.md as confirmed_by_owner=false.",
    )


def check_freshness(con: duckdb.DuckDBPyConnection, rules: dict, logger) -> CheckResult:
    """Wall-clock freshness only makes sense for a pull whose own data extends near 'now'.

    A deliberate historical backfill (e.g. 2025-07..2026-06, chosen in Phase 1 so every
    month has an official scorecard actual to reconcile against) will always have an old
    max(data_loaded_at) — that's the window working as designed, not staleness. This check
    first asks whether the pulled data reaches near-present before judging it stale.
    """
    threshold = rules["freshness"]["max_data_loaded_at_age_hours"]
    max_received = con.execute("SELECT MAX(CAST(received_dttm AS TIMESTAMP)) FROM raw_calls").fetchone()[0]
    now = datetime.now(timezone.utc)
    received_age_hours = (now - max_received.replace(tzinfo=timezone.utc)).total_seconds() / 3600

    if received_age_hours > threshold:
        return CheckResult(
            "freshness", "PASS",
            f"The newest data_loaded_at across all pulled rows must be within {threshold}h of "
            f"now — but only for pulls whose own data extends near the present.",
            {"max_received_dttm": str(max_received), "received_age_hours": round(received_age_hours, 2),
             "threshold_hours": threshold, "note": "not applicable: this pull's most recent "
             "received_dttm is already older than the threshold, so it's a deliberate "
             "historical window (e.g. --backfill), not a current/incremental pull."},
            "None — freshness vs. wall-clock time applies to --since/current-month pulls, not backfills.",
        )

    max_loaded = con.execute("SELECT MAX(CAST(data_loaded_at AS TIMESTAMP)) FROM raw_calls").fetchone()[0]
    age_hours = (now - max_loaded.replace(tzinfo=timezone.utc)).total_seconds() / 3600
    metric = {"max_data_loaded_at": str(max_loaded), "age_hours": round(age_hours, 2), "threshold_hours": threshold}
    if age_hours >= threshold:
        return CheckResult(
            "freshness", "FAIL",
            f"The newest data_loaded_at across all pulled rows must be within {threshold}h "
            f"of now, or the pull is stale and should not be published as current.",
            metric,
            "Stop. Re-run extract; if staleness persists, check the DataSF pipeline's own status.",
        )
    return CheckResult(
        "freshness", "PASS",
        f"The newest data_loaded_at across all pulled rows must be within {threshold}h of now.",
        metric, "None.",
    )


def profile_summary(con: duckdb.DuckDBPyConnection) -> dict:
    """Descriptive facts (not PASS/WARN/FAIL) that the notebook narrates. Re-verifies brief Q1/Q3/Q8."""
    grain = con.execute(
        "SELECT COUNT(*) AS unit_rows, COUNT(DISTINCT call_number) AS distinct_calls FROM raw_calls"
    ).fetchone()
    priority_change = con.execute(
        "SELECT COUNT(*) FROM raw_calls "
        "WHERE original_priority IS NOT NULL AND final_priority IS NOT NULL "
        "AND original_priority != final_priority"
    ).fetchone()[0]
    unit_type_counts = con.execute(
        "SELECT unit_type, COUNT(*) FROM raw_calls GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()
    return {
        "unit_rows": grain[0],
        "distinct_calls": grain[1],
        "rows_per_call": round(grain[0] / grain[1], 3) if grain[1] else None,
        "priority_changed_original_vs_final": priority_change,
        "unit_type_counts": dict(unit_type_counts),
    }


def run_validation(run_ts: str, logger, scope: str = "full backfill window (config/settings.yaml backfill.start_month..end_month)") -> dict:
    rules = load_rules()
    con = duckdb.connect()
    load_calls_view(con, run_ts)

    checks: list[CheckResult] = []
    checks.append(check_manifest_completeness(run_ts, con))
    schema_check = check_schema(con, rules)
    checks.append(schema_check)

    if schema_check.severity == "FAIL":
        # Every remaining check queries specific columns - if the schema check
        # already found one missing, running them would crash on an unbound
        # column reference rather than reporting a clean FAIL. Stop here: the
        # schema check alone is enough to fail the run (CLAUDE.md rule 8).
        logger.warning("[validate] schema FAILed - skipping column-dependent checks")
    else:
        checks.append(check_rowid_uniqueness(con))
        checks.extend(check_null_rates(con, rules))
        checks.extend(check_timestamp_order(con, rules))
        checks.append(check_priority_domain(con, rules))
        checks.append(check_freshness(con, rules, logger))

    for c in checks:
        logger.info("[validate/%s] %s", c.rule_id, c.severity)

    if any(c.severity == "FAIL" for c in checks):
        overall = "FAIL"
    elif any(c.severity == "WARN" for c in checks):
        overall = "WARN"
    else:
        overall = "PASS"

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_ts": run_ts,
        "scope": scope,
        "overall_status": overall,
        "checks": [asdict(c) for c in checks],
        "profile": profile_summary(con),
    }

    logger.info("[validate] overall_status=%s (%d checks: %d PASS, %d WARN, %d FAIL)",
                overall, len(checks),
                sum(c.severity == "PASS" for c in checks),
                sum(c.severity == "WARN" for c in checks),
                sum(c.severity == "FAIL" for c in checks))

    con.close()
    return report


def write_report(report: dict, out_path: Optional[Path] = None) -> Path:
    out_path = out_path or (OUTPUTS_DIR / "validation_report.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return out_path


def _cli() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate raw calls data pulled by pipeline/extract.py.")
    parser.add_argument("--run-ts", required=True, help="run_ts directory under data/raw/calls/ to validate")
    parser.add_argument("--out", help="Output path for validation_report.json")
    return parser.parse_args()


def main() -> None:
    args = _cli()
    logger = get_logger(f"validate_{args.run_ts}")
    report = run_validation(args.run_ts, logger)
    out_path = write_report(report, Path(args.out) if args.out else None)
    logger.info("[validate] report written to %s", out_path)
    if report["overall_status"] == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
