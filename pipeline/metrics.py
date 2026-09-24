"""Compute M1-M5 from fct_call / stg_unit_response and reconcile M1 against the
official scorecard (measure code from config/settings.yaml sources.scorecard).

M1 is computed under every candidate definition in config/kpi_definitions.yaml
- clock start x priority rule x unit scope - because the scorecard publishes
no methodology (docs/source_map.md). "Best" is decided empirically here by
comparing each candidate's monthly values against the real scorecard actual,
never assumed in advance (CLAUDE.md rule 5: never invent numbers).

Every metric is computed over every month in the warehouse (reconciliation
needs the full history). `scope_month` then picks the one month a run is
about; `scope_month_summary` is that month's headline block, which the
dashboard and the per-month KPI pack lead with.
"""

import argparse
import csv
import io
import json
from pathlib import Path
from typing import Optional

import duckdb
import yaml

from pipeline.extract import load_settings
from pipeline.load import get_connection
from pipeline.logging_utils import get_logger

REPO_ROOT = Path(__file__).resolve().parent.parent
KPI_DEFS_PATH = REPO_ROOT / "config" / "kpi_definitions.yaml"
OUTPUTS_DIR = REPO_ROOT / "outputs"

UNIT_SCOPE_COLUMN = {
    "medic_only": "first_medic_on_scene_dttm",
    "ambulance": "first_ambulance_on_scene_dttm",
    "any_unit": "first_any_unit_on_scene_dttm",
}


def load_kpi_definitions() -> dict:
    """Read config/kpi_definitions.yaml (M1 candidates, targets, M4 standard, M5 pairs)."""
    with open(KPI_DEFS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _priority_predicate(definition: dict) -> str:
    field = definition["priority_field"]
    values = ", ".join(f"'{v}'" for v in definition["priority_values"])
    return f"{field} IN ({values})"


def compute_m1_definition_monthly(con: duckdb.DuckDBPyConnection, definition: dict, target_minutes: int) -> list[dict]:
    """One candidate M1 definition, every month present in fct_call.

    Uses date_diff('second', ...) / 60.0 rather than date_diff('minute', ...):
    DuckDB's 'minute' unit diffs the two timestamps' minute-truncated values,
    not true elapsed duration (e.g. 01:40:49 -> 01:53:13 reports 13 minutes,
    not the true 12.4) - up to ~1 minute of bias, enough to flip calls right
    at the 10-minute compliance boundary. Verified via
    notebooks/03_workflow_model.ipynb.
    """
    on_scene_col = UNIT_SCOPE_COLUMN[definition["unit_scope"]]
    clock_col = definition["clock_start_field"]
    predicate = _priority_predicate(definition)

    rows = con.execute(f"""
        SELECT
            strftime(received_dttm, '%Y-%m') AS month,
            COUNT(*) FILTER (WHERE {predicate} AND {clock_col} IS NOT NULL AND {on_scene_col} IS NOT NULL) AS denominator,
            COUNT(*) FILTER (WHERE {predicate} AND {clock_col} IS NOT NULL AND {on_scene_col} IS NOT NULL
                              AND date_diff('second', {clock_col}, {on_scene_col}) / 60.0 <= {target_minutes}) AS numerator,
            COUNT(*) FILTER (WHERE {predicate} AND {clock_col} IS NOT NULL AND {on_scene_col} IS NULL) AS excluded_no_arrival
        FROM fct_call
        WHERE received_dttm IS NOT NULL
        GROUP BY 1 ORDER BY 1
    """).fetchall()

    return [
        {
            "definition_id": definition["id"],
            "month": month,
            "numerator": num,
            "denominator": denom,
            "pct": round(num / denom, 4) if denom else None,
            "excluded_no_arrival": excl,
        }
        for month, denom, num, excl in rows
    ]


def get_official_scorecard(con: duckdb.DuckDBPyConnection, measure_code: str) -> dict:
    """month -> official actual (0-1 scale), from the loaded scorecard_measures table.

    `actual` is text in the source (measure_data_type varies across the whole
    dataset, so DuckDB infers VARCHAR); -9999 is the documented sentinel for
    "no value reported" (dataset metadata, docs/source_map.md). measure_code
    comes from config/settings.yaml (sources.scorecard.measure_code).
    """
    rows = con.execute("""
        SELECT strftime(CAST(calendar_month AS TIMESTAMP), '%Y-%m') AS month,
               CAST(actual AS DOUBLE) AS actual
        FROM scorecard_measures
        WHERE measure_code = ?
          AND actual IS NOT NULL
          AND TRY_CAST(actual AS DOUBLE) IS NOT NULL
          AND TRY_CAST(actual AS DOUBLE) != -9999
    """, [str(measure_code)]).fetchall()
    return {month: actual for month, actual in rows}


def reconcile_m1(m1_rows: list[dict], official: dict) -> dict:
    """For each definition, mean absolute gap to the official value over months where both exist."""
    by_def: dict[str, list[dict]] = {}
    for row in m1_rows:
        by_def.setdefault(row["definition_id"], []).append(row)

    reconciliation = {}
    for def_id, rows in by_def.items():
        gaps = []
        for row in rows:
            official_pct = official.get(row["month"])
            if official_pct is not None and row["pct"] is not None:
                gaps.append(abs(row["pct"] - official_pct))
        reconciliation[def_id] = {
            "months_compared": len(gaps),
            "mean_absolute_gap": round(sum(gaps) / len(gaps), 4) if gaps else None,
        }
    return reconciliation


def compute_m2_call_processing(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Received -> dispatch, p50/p90, monthly. No official comparator exists (docs/source_map.md)."""
    rows = con.execute("""
        SELECT
            strftime(received_dttm, '%Y-%m') AS month,
            quantile_cont(date_diff('second', received_dttm, dispatch_dttm) / 60.0, 0.5) AS p50_minutes,
            quantile_cont(date_diff('second', received_dttm, dispatch_dttm) / 60.0, 0.9) AS p90_minutes,
            COUNT(*) AS n
        FROM fct_call
        WHERE received_dttm IS NOT NULL AND dispatch_dttm IS NOT NULL
        GROUP BY 1 ORDER BY 1
    """).fetchall()
    return [{"month": m, "p50_minutes": round(p50, 1), "p90_minutes": round(p90, 1), "n": n} for m, p50, p90, n in rows]


def compute_m3_travel_time(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """En-route -> on-scene, p50/p90, monthly, at the unit_response grain (brief M3).

    Scoped to MEDIC/PRIVATE (ambulance) units only. Including all unit types
    (fire engines/trucks arrive faster and are far more numerous - see
    docs/assumptions.md §4) pulls the median down to ~4.4 min system-wide,
    which measures first-responder coverage, not ambulance travel time or
    ambulance deployment/positioning - the thing M3 is meant to inform,
    per PROJECT_BRIEF.md §6. Verified: ambulance-only p50=7.4min/p90=17.5min
    vs. all-units p50=4.4min/p90=15.3min - a real, material difference, not
    noise (notebooks/03_workflow_model.ipynb).
    """
    rows = con.execute("""
        SELECT
            strftime(received_dttm, '%Y-%m') AS month,
            quantile_cont(date_diff('second', response_dttm, on_scene_dttm) / 60.0, 0.5) AS p50_minutes,
            quantile_cont(date_diff('second', response_dttm, on_scene_dttm) / 60.0, 0.9) AS p90_minutes,
            COUNT(*) AS n
        FROM stg_unit_response
        WHERE response_dttm IS NOT NULL AND on_scene_dttm IS NOT NULL AND NOT dq_response_after_onscene
          AND unit_type IN ('MEDIC', 'PRIVATE')
        GROUP BY 1 ORDER BY 1
    """).fetchall()
    return [{"month": m, "p50_minutes": round(p50, 1), "p90_minutes": round(p90, 1), "n": n} for m, p50, p90, n in rows]


def compute_m4_hospital(con: duckdb.DuckDBPyConnection, kpi_defs: dict) -> list[dict]:
    """Hospital -> available wall interval, monthly: % over the 30-min turnaround standard,
    and ambulance-hours lost beyond it. The 20-min offload standard is NOT computed here -
    it requires a hospital timestamp this dataset doesn't have (docs/decision_log.md)."""
    standard = kpi_defs["m4_hospital_standard"]["turnaround_minutes"]
    rows = con.execute(f"""
        SELECT
            strftime(received_dttm, '%Y-%m') AS month,
            COUNT(*) AS n_transports,
            COUNT(*) FILTER (WHERE date_diff('second', hospital_dttm, available_dttm) / 60.0 > {standard}) AS n_over_standard,
            quantile_cont(date_diff('second', hospital_dttm, available_dttm) / 60.0, 0.5) AS p50_minutes,
            quantile_cont(date_diff('second', hospital_dttm, available_dttm) / 60.0, 0.9) AS p90_minutes,
            SUM(GREATEST(date_diff('second', hospital_dttm, available_dttm) / 60.0 - {standard}, 0)) / 60.0 AS ambulance_hours_lost
        FROM stg_unit_response
        WHERE hospital_dttm IS NOT NULL AND available_dttm IS NOT NULL AND NOT dq_hospital_after_available
        GROUP BY 1 ORDER BY 1
    """).fetchall()
    return [
        {
            "month": m, "n_transports": n, "n_over_standard": over,
            "pct_over_standard": round(over / n, 4) if n else None,
            "p50_minutes": round(p50, 1), "p90_minutes": round(p90, 1),
            "ambulance_hours_lost": round(hours, 1),
        }
        for m, n, over, p50, p90, hours in rows
    ]


def _gap_points(higher: Optional[float], lower: Optional[float]) -> Optional[float]:
    """(higher - lower) in percentage points, or None if either side is missing."""
    if higher is None or lower is None:
        return None
    return round((higher - lower) * 100, 1)


def compute_m5_definition_gap(m1_rows: list[dict], official: dict, clock_pair: dict, twin_pair: dict) -> list[dict]:
    """Per month: M1(dispatch clock) - M1(received clock) for two definition pairs, plus
    the official value's gap to the headline pair's dispatch-clock definition.

    clock_pair is the headline pair (config m5_clock_gap_pair -> clock_gap_points);
    twin_pair is the like-for-like pair for the best-fitting definition (config
    m5_best_fit_twin -> best_fit_twin_gap_points). Why both: config/kpi_definitions.yaml.
    """
    by_month: dict[str, dict[str, float]] = {}
    for row in m1_rows:
        by_month.setdefault(row["month"], {})[row["definition_id"]] = row["pct"]

    results = []
    for month, defs in sorted(by_month.items()):
        received_pct = defs.get(clock_pair["received_clock"])
        dispatch_pct = defs.get(clock_pair["dispatch_clock"])
        twin_received_pct = defs.get(twin_pair["received_clock"])
        twin_dispatch_pct = defs.get(twin_pair["dispatch_clock"])
        official_pct = official.get(month)
        results.append({
            "month": month,
            "m1_received_clock_pct": received_pct,
            "m1_dispatch_clock_pct": dispatch_pct,
            "clock_gap_points": _gap_points(dispatch_pct, received_pct),
            "official_pct": official_pct,
            "official_vs_dispatch_gap_points": _gap_points(official_pct, dispatch_pct),
            "best_fit_twin_received_clock_pct": twin_received_pct,
            "best_fit_twin_dispatch_clock_pct": twin_dispatch_pct,
            "best_fit_twin_gap_points": _gap_points(twin_dispatch_pct, twin_received_pct),
        })
    return results


def _row_for_month(rows: list[dict], month: str) -> Optional[dict]:
    """The row for `month` in a per-month list, or None if that month has no data."""
    return next((r for r in rows if r["month"] == month), None)


def latest_month(m1_rows: list[dict]) -> Optional[str]:
    """Latest month with any M1 row in the warehouse, or None if the warehouse is empty."""
    return max((r["month"] for r in m1_rows), default=None)


def build_scope_month_summary(metrics: dict, scope_month: str) -> dict:
    """The headline block for one month: every M1 definition vs target and official,
    plus that month's M2/M3/M4/M5 rows.

    Any value can be None (month not in the warehouse, no published official
    actual yet, a definition with an empty denominator) - consumers must render
    None as "n/a", never guess. `in_warehouse` says whether the month has data.
    """
    official_pct = metrics["official_scorecard_by_month"].get(scope_month)
    target_pct = metrics["target_pct"]
    recon = metrics["m1_reconciliation"]

    m1_by_definition = []
    for definition in metrics["m1_definitions"]:
        def_id = definition["id"]
        row = next((r for r in metrics["m1_kpi_monthly"]
                    if r["definition_id"] == def_id and r["month"] == scope_month), None)
        pct = row["pct"] if row else None
        m1_by_definition.append({
            "definition_id": def_id,
            "label": definition.get("label", def_id),
            "pct": pct,
            "numerator": row["numerator"] if row else None,
            "denominator": row["denominator"] if row else None,
            "meets_target": (pct >= target_pct) if pct is not None else None,
            "gap_to_target_points": _gap_points(pct, target_pct),
            "gap_to_official_points": _gap_points(pct, official_pct),
            "mean_absolute_gap_full_history": recon.get(def_id, {}).get("mean_absolute_gap"),
            "is_best_fit": def_id == metrics["m1_best_fitting_definition"],
        })

    return {
        "month": scope_month,
        "in_warehouse": any(r["month"] == scope_month for r in metrics["m1_kpi_monthly"]),
        "target_pct": target_pct,
        "target_minutes": metrics["target_minutes"],
        "official_pct": official_pct,
        "m1_best_fitting_definition": metrics["m1_best_fitting_definition"],
        "m1_by_definition": m1_by_definition,
        "m2_call_processing": _row_for_month(metrics["m2_call_processing_p50_p90"], scope_month),
        "m3_travel_time": _row_for_month(metrics["m3_travel_time_p50_p90"], scope_month),
        "m4_hospital_turnaround": _row_for_month(metrics["m4_hospital_turnaround"], scope_month),
        "m5_definition_gap": _row_for_month(metrics["m5_definition_gap"], scope_month),
    }


def run_metrics(con: duckdb.DuckDBPyConnection, logger, scope_month: Optional[str] = None) -> dict:
    """Compute M1-M5 over every warehouse month, reconcile M1, and add the scope_month block.

    scope_month is the month a run is about (YYYY-MM). If None, the latest month
    in the warehouse is used and `scope_month_basis` says so. A scope_month with
    no warehouse data still gets a summary (all values None, in_warehouse=False).
    """
    kpi_defs = load_kpi_definitions()
    measure_code = load_settings()["sources"]["scorecard"]["measure_code"]
    target_minutes = kpi_defs["target_minutes"]
    official = get_official_scorecard(con, measure_code)
    logger.info("[metrics] official scorecard months available (measure %s): %d", measure_code, len(official))

    m1_rows: list[dict] = []
    for definition in kpi_defs["m1_candidate_definitions"]:
        m1_rows.extend(compute_m1_definition_monthly(con, definition, target_minutes))
    reconciliation = reconcile_m1(m1_rows, official)

    best_def_id = min(
        (d for d, r in reconciliation.items() if r["mean_absolute_gap"] is not None),
        key=lambda d: reconciliation[d]["mean_absolute_gap"],
        default=None,
    )
    logger.info("[metrics] best-fitting M1 definition: %s (mean abs gap %.4f)",
                best_def_id, reconciliation[best_def_id]["mean_absolute_gap"] if best_def_id else float("nan"))

    m2_rows = compute_m2_call_processing(con)
    m3_rows = compute_m3_travel_time(con)
    m4_rows = compute_m4_hospital(con, kpi_defs)
    m5_rows = compute_m5_definition_gap(m1_rows, official, kpi_defs["m5_clock_gap_pair"], kpi_defs["m5_best_fit_twin"])

    scope_month_basis = "requested"
    if scope_month is None:
        scope_month = latest_month(m1_rows)
        scope_month_basis = "latest month in warehouse (none requested)"

    metrics = {
        "scope_month": scope_month,
        "scope_month_basis": scope_month_basis,
        "target_minutes": target_minutes,
        "target_pct": kpi_defs["target_pct"],
        "official_measure_code": measure_code,
        "official_scorecard_by_month": official,
        "m1_definitions": kpi_defs["m1_candidate_definitions"],
        "m1_kpi_monthly": m1_rows,
        "m1_reconciliation": reconciliation,
        "m1_best_fitting_definition": best_def_id,
        "m2_call_processing_p50_p90": m2_rows,
        "m3_travel_time_p50_p90": m3_rows,
        "m4_hospital_turnaround": m4_rows,
        "m4_standard": kpi_defs["m4_hospital_standard"],
        "m5_clock_gap_pair": kpi_defs["m5_clock_gap_pair"],
        "m5_best_fit_twin": kpi_defs["m5_best_fit_twin"],
        "m5_definition_gap": m5_rows,
    }
    metrics["scope_month_summary"] = build_scope_month_summary(metrics, scope_month) if scope_month else None
    if scope_month and not metrics["scope_month_summary"]["in_warehouse"]:
        logger.warning("[metrics] scope_month=%s has no rows in the warehouse - its summary is all n/a", scope_month)
    else:
        logger.info("[metrics] scope_month=%s (%s)", scope_month, scope_month_basis)
    return metrics


def kpi_monthly_csv(m1_rows: list[dict]) -> str:
    """The M1 per-definition, per-month table as CSV text (the one writer every output uses)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["month", "definition_id", "numerator", "denominator", "pct", "excluded_no_arrival"])
    for row in m1_rows:
        writer.writerow([row["month"], row["definition_id"], row["numerator"], row["denominator"],
                         row["pct"] if row["pct"] is not None else "", row["excluded_no_arrival"]])
    return buffer.getvalue()


def write_outputs(metrics: dict, logger) -> None:
    """Write the full-history outputs/metrics.json and outputs/kpi_monthly.csv."""
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUTS_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")
    logger.info("[metrics] wrote %s", OUTPUTS_DIR / "metrics.json")
    (OUTPUTS_DIR / "kpi_monthly.csv").write_text(kpi_monthly_csv(metrics["m1_kpi_monthly"]), encoding="utf-8")
    logger.info("[metrics] wrote %s", OUTPUTS_DIR / "kpi_monthly.csv")


def main() -> None:
    """CLI: compute metrics from the existing warehouse (no network) and write outputs/."""
    parser = argparse.ArgumentParser(description="Compute M1-M5 and reconcile against the official scorecard.")
    parser.add_argument("--scope-month", metavar="YYYY-MM", default=None,
                        help="Month to headline in scope_month_summary (default: latest month in the warehouse)")
    args = parser.parse_args()
    logger = get_logger("metrics")
    con = get_connection()
    metrics = run_metrics(con, logger, scope_month=args.scope_month)
    write_outputs(metrics, logger)
    con.close()


if __name__ == "__main__":
    main()
