"""Compute M1-M5 from fct_call / stg_unit_response and reconcile M1 against the
official scorecard (measure 973).

M1 is computed under every candidate definition in config/kpi_definitions.yaml
- clock start x priority rule x unit scope - because the scorecard publishes
no methodology (docs/source_map.md). "Best" is decided empirically here by
comparing each candidate's monthly values against the real scorecard actual,
never assumed in advance (CLAUDE.md rule 5: never invent numbers).
"""

import argparse
import json
from pathlib import Path
from typing import Optional

import duckdb
import yaml

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


def get_official_scorecard(con: duckdb.DuckDBPyConnection) -> dict:
    """month -> official actual (0-1 scale), from the loaded scorecard_measures table.

    `actual` is text in the source (measure_data_type varies across the whole
    dataset, so DuckDB infers VARCHAR); -9999 is the documented sentinel for
    "no value reported" (dataset metadata, docs/source_map.md).
    """
    rows = con.execute("""
        SELECT strftime(CAST(calendar_month AS TIMESTAMP), '%Y-%m') AS month,
               CAST(actual AS DOUBLE) AS actual
        FROM scorecard_measures
        WHERE measure_code = '973'
          AND actual IS NOT NULL
          AND TRY_CAST(actual AS DOUBLE) IS NOT NULL
          AND TRY_CAST(actual AS DOUBLE) != -9999
    """).fetchall()
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
            approx_quantile(date_diff('second', received_dttm, dispatch_dttm) / 60.0, 0.5) AS p50_minutes,
            approx_quantile(date_diff('second', received_dttm, dispatch_dttm) / 60.0, 0.9) AS p90_minutes,
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
    per PROJECT_BRIEF.md §6. Verified: ambulance-only p50=7.4min/p90=17.4min
    vs. all-units p50=4.4min/p90=15.3min - a real, material difference, not
    noise (notebooks/03_workflow_model.ipynb).
    """
    rows = con.execute("""
        SELECT
            strftime(received_dttm, '%Y-%m') AS month,
            approx_quantile(date_diff('second', response_dttm, on_scene_dttm) / 60.0, 0.5) AS p50_minutes,
            approx_quantile(date_diff('second', response_dttm, on_scene_dttm) / 60.0, 0.9) AS p90_minutes,
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
            approx_quantile(date_diff('second', hospital_dttm, available_dttm) / 60.0, 0.5) AS p50_minutes,
            approx_quantile(date_diff('second', hospital_dttm, available_dttm) / 60.0, 0.9) AS p90_minutes,
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


def compute_m5_definition_gap(m1_rows: list[dict], official: dict) -> list[dict]:
    """M1(received-clock) - M1(dispatch-clock), plus the gap of the best dispatch-clock
    definition to the official value, per month."""
    by_month: dict[str, dict[str, float]] = {}
    for row in m1_rows:
        by_month.setdefault(row["month"], {})[row["definition_id"]] = row["pct"]

    results = []
    for month, defs in sorted(by_month.items()):
        received_pct = defs.get("received_final_ambulance")
        dispatch_pct = defs.get("dispatch_final_ambulance")
        official_pct = official.get(month)
        results.append({
            "month": month,
            "m1_received_clock_pct": received_pct,
            "m1_dispatch_clock_pct": dispatch_pct,
            "clock_gap_points": round((dispatch_pct - received_pct) * 100, 1) if received_pct is not None and dispatch_pct is not None else None,
            "official_pct": official_pct,
            "official_vs_dispatch_gap_points": round((official_pct - dispatch_pct) * 100, 1) if official_pct is not None and dispatch_pct is not None else None,
        })
    return results


def run_metrics(con: duckdb.DuckDBPyConnection, logger) -> dict:
    kpi_defs = load_kpi_definitions()
    target_minutes = kpi_defs["target_minutes"]
    official = get_official_scorecard(con)
    logger.info("[metrics] official scorecard months available: %d", len(official))

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
    m5_rows = compute_m5_definition_gap(m1_rows, official)

    return {
        "target_minutes": target_minutes,
        "target_pct": kpi_defs["target_pct"],
        "official_scorecard_by_month": official,
        "m1_definitions": kpi_defs["m1_candidate_definitions"],
        "m1_kpi_monthly": m1_rows,
        "m1_reconciliation": reconciliation,
        "m1_best_fitting_definition": best_def_id,
        "m2_call_processing_p50_p90": m2_rows,
        "m3_travel_time_p50_p90": m3_rows,
        "m4_hospital_turnaround": m4_rows,
        "m4_standard": kpi_defs["m4_hospital_standard"],
        "m5_definition_gap": m5_rows,
    }


def write_outputs(metrics: dict, logger) -> None:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUTS_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")
    logger.info("[metrics] wrote %s", OUTPUTS_DIR / "metrics.json")

    csv_lines = ["month,definition_id,numerator,denominator,pct,excluded_no_arrival"]
    for row in metrics["m1_kpi_monthly"]:
        csv_lines.append(
            f"{row['month']},{row['definition_id']},{row['numerator']},{row['denominator']},"
            f"{row['pct'] if row['pct'] is not None else ''},{row['excluded_no_arrival']}"
        )
    (OUTPUTS_DIR / "kpi_monthly.csv").write_text("\n".join(csv_lines) + "\n", encoding="utf-8")
    logger.info("[metrics] wrote %s", OUTPUTS_DIR / "kpi_monthly.csv")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute M1-M5 and reconcile against the official scorecard.")
    parser.parse_args()
    logger = get_logger("metrics")
    con = get_connection()
    metrics = run_metrics(con, logger)
    write_outputs(metrics, logger)
    con.close()


if __name__ == "__main__":
    main()
