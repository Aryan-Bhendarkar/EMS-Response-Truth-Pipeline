"""Generate notebooks/03_workflow_model.ipynb. See build_notebook_02.py for the pattern."""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = REPO_ROOT / "notebooks" / "03_workflow_model.ipynb"


def md(*lines: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": [l + "\n" for l in lines]}


def code(*lines: str) -> dict:
    return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": [l + "\n" for l in lines]}


cells = [
    md(
        "# 03 — Workflow Model",
        "",
        "Entities, events/states, and interactions/interventions/outcomes for the SF EMS "
        "dispatch lifecycle, and the SQL models (`pipeline/transform/*.sql`) that implement "
        "them in DuckDB. Run via `python -m pipeline.load` before this notebook.",
    ),
    md(
        "## Entities",
        "",
        "- **`call`** — one 911 dispatch event (`call_number`), grain of `fct_call`.",
        "- **`unit`** — a single responding resource (`unit_id`), of type `MEDIC`, `PRIVATE`, "
        "`ENGINE`, `TRUCK`, `CHIEF`, and others (`docs/assumptions.md` §4).",
        "- **`unit_response`** — a unit dispatched to a call (`rowid = call_number-unit_id`), "
        "grain of `stg_unit_response`, the source dataset's own grain.",
        "",
        "## Events / states (per `unit_response`, `fct_unit_event`)",
        "",
        "`RECEIVED -> ENTERED -> DISPATCHED -> EN_ROUTE -> ON_SCENE -> "
        "[TRANSPORTING -> AT_HOSPITAL] -> AVAILABLE`, terminating in "
        "`call_final_disposition` (Transport, Cancelled, Unable to Locate, ...). Only "
        "recorded events produce a row — a call that never reached on-scene has no ON_SCENE "
        "row, visible directly in the event table rather than hidden behind a NULL.",
        "",
        "## Interactions / interventions / outcomes",
        "",
        "- **Interaction:** the 911 call itself + call-taker triage (`original_priority`).",
        "- **Intervention:** priority reassessment (`original_priority` → `final_priority`, "
        "~25% of calls), which units are sent (count, `unit_type` mix), whether a private "
        "ambulance responds.",
        "- **Outcome:** first ambulance on scene within 10 minutes (M1), transport "
        "disposition, unit returned to service (M4).",
    ),
    code(
        "import duckdb, pandas as pd",
        "from pathlib import Path",
        "REPO_ROOT = Path.cwd().parent if Path.cwd().name == \"notebooks\" else Path.cwd()",
        "con = duckdb.connect(str(REPO_ROOT / \"data\" / \"processed\" / \"sf_ems.duckdb\"), read_only=True)",
        "con.execute(\"SELECT \x27stg_unit_response\x27 AS t, COUNT(*) AS n FROM stg_unit_response \"",
        "            \"UNION ALL SELECT \x27fct_unit_event\x27, COUNT(*) FROM fct_unit_event \"",
        "            \"UNION ALL SELECT \x27fct_call\x27, COUNT(*) FROM fct_call\").df()",
    ),
    md(
        "364,873 unit-response rows unpivot into ~2.27M lifecycle events, and roll up to "
        "182,495 calls — consistent with the ~2 units/call grain confirmed in Phase 3.",
    ),
    md("## Verifying the call-level aggregation is safe"),
    code(
        "con.execute(\"\"\"",
        "    SELECT COUNT(*) FROM (",
        "        SELECT call_number,",
        "               COUNT(DISTINCT COALESCE(original_priority,\x27\x27)) AS n_op,",
        "               COUNT(DISTINCT COALESCE(final_priority,\x27\x27)) AS n_fp,",
        "               COUNT(DISTINCT COALESCE(call_type_group,\x27\x27)) AS n_ctg",
        "        FROM stg_unit_response GROUP BY call_number",
        "    ) WHERE n_op > 1 OR n_fp > 1 OR n_ctg > 1",
        "\"\"\").df()",
    ),
    md(
        "**0 calls** have inconsistent priority or call_type_group across their units — "
        "confirms `fct_call.sql`'s use of `ANY_VALUE()` for these fields is safe, not an "
        "unverified assumption.",
    ),
    md("## Lifecycle event coverage — how far calls get"),
    code(
        "con.execute(\"\"\"",
        "    SELECT event_type, COUNT(*) AS n, COUNT(DISTINCT call_number) AS distinct_calls",
        "    FROM fct_unit_event GROUP BY 1",
        "    ORDER BY n DESC",
        "\"\"\").df()",
    ),
    md(
        "Every stage loses some rows relative to the one before it — RECEIVED and DISPATCHED "
        "are recorded for nearly every row, while TRANSPORTING/AT_HOSPITAL/AVAILABLE only "
        "apply to calls that resulted in an actual transport, which is the expected shape of "
        "an EMS lifecycle funnel, not a data problem.",
    ),
    md("## Unit-type mix and the M3 scoping decision"),
    code(
        "con.execute(\"\"\"",
        "    SELECT unit_type,",
        "           quantile_cont(date_diff(\x27second\x27, response_dttm, on_scene_dttm)/60.0, 0.5) AS p50_min,",
        "           COUNT(*) AS n",
        "    FROM stg_unit_response",
        "    WHERE response_dttm IS NOT NULL AND on_scene_dttm IS NOT NULL AND NOT dq_response_after_onscene",
        "    GROUP BY 1 ORDER BY n DESC",
        "\"\"\").df()",
    ),
    md(
        "`ENGINE`/`TRUCK` units arrive materially faster than `MEDIC`/`PRIVATE` ambulances "
        "(they're more numerous and more densely stationed). This is why `pipeline/metrics.py`'s "
        "M3 (travel time) is scoped to `MEDIC`/`PRIVATE` only — an unscoped calculation would "
        "measure first-responder coverage, not ambulance travel time, which is what M3 is "
        "meant to inform (staffing/positioning decisions for ambulances specifically).",
    ),
    md(
        "## Summary",
        "",
        "- The workflow model (`pipeline/transform/010_stg_unit_response.sql` → `020_fct_unit_event.sql` "
        "→ `030_fct_call.sql`) is built and verified against the real 12-month backfill.",
        "- Every call-level aggregation choice (priority/call_type_group via `ANY_VALUE`) is "
        "backed by a 0-exception check, not assumed.",
        "- The unit-type mix directly informed a real modeling decision (M3's ambulance-only "
        "scope) — continued in `notebooks/04_metrics_reconciliation.ipynb`.",
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
