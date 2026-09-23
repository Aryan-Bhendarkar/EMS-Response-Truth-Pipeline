"""Generate notebooks/04_metrics_reconciliation.ipynb. See build_notebook_02.py for the pattern."""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = REPO_ROOT / "notebooks" / "04_metrics_reconciliation.ipynb"


def md(*lines: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": [l + "\n" for l in lines]}


def code(*lines: str) -> dict:
    return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": [l + "\n" for l in lines]}


cells = [
    md(
        "# 04 — Metrics & Reconciliation",
        "",
        "M1-M5 computed by `pipeline/metrics.py` against the real 12-month backfill, and the "
        "reconciliation exercise that resolves \"which clock?\" empirically. Full writeup: "
        "`docs/judgement_call.md`. Run `python -m pipeline.metrics` before this notebook.",
    ),
    code(
        "import json, pandas as pd",
        "from pathlib import Path",
        "REPO_ROOT = Path.cwd().parent if Path.cwd().name == \"notebooks\" else Path.cwd()",
        "metrics = json.loads((REPO_ROOT / \"outputs\" / \"metrics.json\").read_text())",
        "print(\"target:\", metrics[\"target_pct\"], \"in\", metrics[\"target_minutes\"], \"minutes\")",
    ),
    md("## M1 — reconciliation: which definition best reproduces the official number?"),
    code(
        "recon = pd.DataFrame(metrics[\"m1_reconciliation\"]).T.sort_values(\"mean_absolute_gap\")",
        "recon",
    ),
    md(
        "`dispatch_original_medic` (clock=dispatch, priority=original∈{3,E}, units=MEDIC only) "
        "wins by a wide margin over every received-clock alternative (3.5 points vs. 20+ "
        "points mean absolute gap) — but only narrowly over `dispatch_ctg_any_responder` "
        "(3.6 points), which scopes to *any* first responder, not just ambulances. The clock "
        "choice dominates; the unit-scope choice is close enough that it's not fully resolved "
        "by this data alone. See `docs/judgement_call.md`.",
    ),
    md("## M1 — best-fitting definition vs. official, month by month"),
    code(
        "best_id = metrics[\"m1_best_fitting_definition\"]",
        "df = pd.DataFrame(metrics[\"m1_kpi_monthly\"])",
        "best = df[df.definition_id == best_id][[\"month\", \"pct\"]].set_index(\"month\")",
        "official = pd.Series(metrics[\"official_scorecard_by_month\"], name=\"official\")",
        "comparison = best.join(official).dropna()",
        "comparison[\"gap_points\"] = ((comparison[\"official\"] - comparison[\"pct\"]) * 100).round(1)",
        "comparison",
    ),
    md("## M5 — the caller-experience gap (dispatch clock vs. received clock)"),
    code(
        "pd.DataFrame(metrics[\"m5_definition_gap\"])",
    ),
    md(
        "The gap between the two clock choices is consistently **~15 percentage points**, "
        "every month — this is not a one-off finding from a single cherry-picked month.",
    ),
    md("## M2 — call-processing time (received → dispatch)"),
    code("pd.DataFrame(metrics[\"m2_call_processing_p50_p90\"])"),
    md("## M3 — ambulance travel time (en route → on scene, MEDIC/PRIVATE only)"),
    code("pd.DataFrame(metrics[\"m3_travel_time_p50_p90\"])"),
    md("## M4 — hospital turnaround and ambulance-hours lost"),
    code(
        "m4 = pd.DataFrame(metrics[\"m4_hospital_turnaround\"])",
        "m4",
    ),
    code(
        "total_hours = m4[\"ambulance_hours_lost\"].sum()",
        "avg_pct_over = m4[\"pct_over_standard\"].mean()",
        "print(f\"Total ambulance-hours lost beyond the {metrics['m4_standard']['turnaround_minutes']}-min \"",
        "      f\"turnaround standard, 12 months: {total_hours:,.0f}\")",
        "print(f\"Average share of transports exceeding the standard: {avg_pct_over:.1%}\")",
        "print(f\"That's roughly {total_hours/12/24:.1f} twelve-hour ambulance shifts per day, system-wide.\")",
    ),
    md(
        "**~82% of transports exceed the 30-minute turnaround standard**, and the system loses "
        "roughly 21,900 ambulance-hours over 12 months beyond that standard — equivalent to "
        "several dozen twelve-hour ambulance shifts *per day* that could otherwise be answering "
        "911 calls. This compares against the 30-minute **turnaround** standard "
        "(`hospital_dttm → available_dttm`), not the 20-minute **offload** standard — the "
        "latter requires a hospital-EHR timestamp this dataset doesn't have "
        "(`docs/decision_log.md`, 2026-09-23). The true offload-standard gap is almost "
        "certainly larger, since offload is a strict subset of turnaround time, but it is not "
        "computed here because this dataset cannot measure it - stated as a limitation, not "
        "filled in with a guess.",
    ),
    md(
        "## Summary",
        "",
        "- **M1 (KPI):** best-reproducing definition lands within ~3.5 points of official, "
        "every month, using a dispatch clock — resolving the \"which clock\" judgement call "
        "empirically (`docs/judgement_call.md`).",
        "- **M2:** call-processing (received→dispatch) is fast: p50 ~2.3 min, p90 ~4.9 min. "
        "Not the bottleneck.",
        "- **M3:** ambulance travel time (en route→on scene) is p50 ~7.2 min, p90 ~17 min.",
        "- **M4:** hospital turnaround is the dominant bottleneck — p50 ~41 min against a "
        "30-min standard, ~82% non-compliant, ~21,900 ambulance-hours lost over 12 months.",
        "- **M5:** the caller-experienced KPI (911-call clock) trails the published dispatch-clock "
        "KPI by ~15 points, consistently.",
    ),
]

notebook = {
    "cells": cells,
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
OUT_PATH.write_text(json.dumps(notebook, indent=1), encoding="utf-8")
print(f"wrote {OUT_PATH}")
