"""Generate notebooks/02_profile_validate.ipynb from source (easier to review/diff than raw JSON).

Run once to (re)write the notebook, then execute it with:
  jupyter nbconvert --to notebook --execute --inplace notebooks/02_profile_validate.ipynb
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = REPO_ROOT / "notebooks" / "02_profile_validate.ipynb"


def md(*lines: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": [l + "\n" for l in lines]}


def code(*lines: str) -> dict:
    return {
        "cell_type": "code", "execution_count": None, "metadata": {},
        "outputs": [], "source": [l + "\n" for l in lines],
    }


cells = [
    md(
        "# 02 — Profile & Validate",
        "",
        "Re-verifies issues Q1-Q10 from `PROJECT_BRIEF.md` §4 against the real 12-month backfill "
        "(`data/raw/calls/run_ts=20260923T163957Z`, 2025-07..2026-06, 364,873 rows) rather than "
        "trusting the brief's own pre-verified figures. Every rule applied here also runs as a "
        "named, thresholded check in `pipeline/validate.py`, written to "
        "`outputs/validation_report.json` on every pipeline run.",
        "",
        "Full detail on anything flagged here as an open question: `docs/assumptions.md` and "
        "`docs/decision_log.md`.",
    ),
    code(
        "import duckdb",
        "import json",
        "import pandas as pd",
        "from pathlib import Path",
        "",
        "REPO_ROOT = Path.cwd().parent if Path.cwd().name == \"notebooks\" else Path.cwd()",
        "RUN_TS = \"20260923T163957Z\"  # the 12-month backfill produced in Phase 2",
        "",
        "con = duckdb.connect()",
        "glob = str(REPO_ROOT / \"data\" / \"raw\" / \"calls\" / f\"run_ts={RUN_TS}\" / \"*\" / \"page_*.json\")",
        "con.execute(f\"CREATE OR REPLACE VIEW raw_calls AS SELECT * FROM read_json_auto('{glob}', union_by_name=true)\")",
        "con.execute(\"SELECT COUNT(*) AS rows FROM raw_calls\").df()",
    ),
    md("## Q1 — Grain: unit-level, not call-level"),
    code(
        "grain = con.execute(\"\"\"",
        "    SELECT COUNT(*) AS unit_rows, COUNT(DISTINCT call_number) AS distinct_calls,",
        "           ROUND(COUNT(*) * 1.0 / COUNT(DISTINCT call_number), 3) AS rows_per_call",
        "    FROM raw_calls",
        "\"\"\").df()",
        "grain",
    ),
    md(
        "**Confirmed.** ~2 unit rows per call, matching the brief's Q1 finding. Any KPI at call "
        "grain (e.g. M1) needs an explicit rule for which unit \"counts\" — handled in Phase 4's "
        "`fct_call` model, not here.",
    ),
    md("## Q2/Q3 — Priority code mix and original-vs-final changes"),
    code(
        "priority_domain = con.execute(\"\"\"",
        "    SELECT COALESCE(original_priority, '(blank)') AS original_priority, COUNT(*) AS n",
        "    FROM raw_calls GROUP BY 1 ORDER BY n DESC",
        "\"\"\").df()",
        "priority_domain",
    ),
    md(
        "Only `2` and `3` are confirmed by the dataset's own column metadata (Code 2 / Code 3). "
        "Every other value (`A,B,C,E,I,T`, and `1`) is unconfirmed — see `docs/assumptions.md` §1 "
        "for the full table and the owner this needs.",
    ),
    code(
        "changed = con.execute(\"\"\"",
        "    SELECT COUNT(*) AS total,",
        "           COUNT(*) FILTER (WHERE original_priority IS NOT NULL AND final_priority IS NOT NULL",
        "                             AND original_priority != final_priority) AS changed,",
        "           ROUND(100.0 * COUNT(*) FILTER (WHERE original_priority IS NOT NULL AND final_priority IS NOT NULL",
        "                             AND original_priority != final_priority) / COUNT(*), 1) AS pct_changed",
        "    FROM raw_calls",
        "\"\"\").df()",
        "changed",
    ),
    md(
        "**~25% of rows have a different final priority than original** — matches the brief's Q3 "
        "finding closely. Confirms priority is reassessed mid-call often enough that a KPI must "
        "pick one field explicitly (`original` vs `final`) and show how the result changes — this "
        "is exactly the definition-sensitivity table Phase 4 builds.",
    ),
    md("## Q4 — Missing `on_scene_dttm`: the real breakdown, not an assumed split"),
    code(
        "null_onscene = con.execute(\"\"\"",
        "    SELECT COALESCE(call_final_disposition, '(null)') AS disposition, COUNT(*) AS n",
        "    FROM raw_calls WHERE on_scene_dttm IS NULL",
        "    GROUP BY 1 ORDER BY n DESC",
        "\"\"\").df()",
        "null_onscene",
    ),
    md(
        "The brief characterized these nulls as splitting into \"cancelled / unable to locate / "
        "genuinely missing.\" The real breakdown shows **Cancelled + Unable to Locate are only "
        "11.9% of the nulls** — the two largest buckets are `Other` and `Fire`, and a notable "
        "chunk (20,354 rows) are dispositioned as an actual transport despite no recorded "
        "`on_scene_dttm`. Not resolved here — flagged in `docs/assumptions.md` §2 for Phase 4 "
        "event modeling rather than silently assumed.",
    ),
    md("## Q5 — Timestamps out of order"),
    code(
        "pairs = [",
        "    (\"dispatch_dttm\", \"response_dttm\"),",
        "    (\"response_dttm\", \"on_scene_dttm\"),",
        "    (\"on_scene_dttm\", \"transport_dttm\"),",
        "    (\"transport_dttm\", \"hospital_dttm\"),",
        "    (\"hospital_dttm\", \"available_dttm\"),",
        "]",
        "rows = []",
        "for earlier, later in pairs:",
        "    r = con.execute(f\"\"\"",
        "        SELECT",
        "            COUNT(*) FILTER (WHERE {earlier} IS NOT NULL AND {later} IS NOT NULL) AS both_present,",
        "            COUNT(*) FILTER (WHERE {earlier} IS NOT NULL AND {later} IS NOT NULL",
        "                             AND CAST({later} AS TIMESTAMP) < CAST({earlier} AS TIMESTAMP)) AS violations",
        "        FROM raw_calls",
        "    \"\"\").fetchone()",
        "    rows.append({\"pair\": f\"{earlier} -> {later}\", \"both_present\": r[0], \"violations\": r[1],",
        "                 \"rate\": round(r[1] / r[0], 6) if r[0] else None})",
        "pd.DataFrame(rows)",
    ),
    md(
        "Violation rates are all well under 1%, consistent with the brief's Q5 finding of rare "
        "but real out-of-order timestamps. `pipeline/validate.py` WARNs on `transport->hospital` "
        "and `hospital->available` (rates ~0.6-0.8%) and would FAIL if any pair exceeded 1% "
        "(`config/validation_rules.yaml`). Violating rows are excluded from interval metrics that "
        "use that pair, not dropped from the dataset.",
    ),
    md("## Q6 — Extreme outliers (p99.9)"),
    code(
        "outliers = con.execute(\"\"\"",
        "    SELECT",
        "        quantile_cont(date_diff('minute', CAST(received_dttm AS TIMESTAMP), CAST(dispatch_dttm AS TIMESTAMP)), 0.999)",
        "            AS p999_received_to_dispatch_min,",
        "        quantile_cont(date_diff('minute', CAST(hospital_dttm AS TIMESTAMP), CAST(available_dttm AS TIMESTAMP)), 0.999)",
        "            AS p999_hospital_to_available_min,",
        "        MAX(date_diff('minute', CAST(received_dttm AS TIMESTAMP), CAST(dispatch_dttm AS TIMESTAMP)))",
        "            AS max_received_to_dispatch_min,",
        "        MAX(date_diff('minute', CAST(hospital_dttm AS TIMESTAMP), CAST(available_dttm AS TIMESTAMP)))",
        "            AS max_hospital_to_available_min",
        "    FROM raw_calls",
        "    WHERE received_dttm IS NOT NULL AND dispatch_dttm IS NOT NULL",
        "\"\"\").df()",
        "outliers",
    ),
    md(
        "Extreme values exist at both ends of the lifecycle, consistent with the brief's Q6 "
        "finding. These are **flagged for review, not dropped** — `config/validation_rules.yaml` "
        "lists both intervals under `outlier_p999_fields`; Phase 4's metrics use median/p90 "
        "(robust to outliers) rather than mean.",
    ),
    md("## Q7 — Freshness and late-arriving updates"),
    md(
        "This 12-month pull is a deliberate historical backfill (chosen in Phase 1 so every "
        "month has an official scorecard actual to reconcile against) — its own most recent "
        "`received_dttm` is already ~3 months old, so a wall-clock \"is this stale\" check isn't "
        "meaningful here by design. `pipeline/validate.py`'s freshness check recognizes this: it "
        "only compares `data_loaded_at` against wall-clock time when the pull's own data reaches "
        "near the present (i.e. `--since`/current-month pulls). A live test against a 3-day "
        "lookback pull (`--since 3`) confirmed the check correctly PASSes there. The late-arriving-"
        "update handling itself (re-pulling a trailing window, upserting by `rowid`) is a Phase 4/5 "
        "load-time concern — `extract_calls_since()` in `pipeline/extract.py` provides the pull; "
        "the upsert lands in `load.py`.",
    ),
    md("## Q8 — Third-party (PRIVATE) units and full `unit_type` mix"),
    code(
        "unit_types = con.execute(\"SELECT unit_type, COUNT(*) AS n FROM raw_calls GROUP BY 1 ORDER BY n DESC\").df()",
        "unit_types",
    ),
    md(
        "`PRIVATE` accounts for 31,970 of 364,873 rows (8.8%) over the full 12 months — confirms "
        "the brief's Q8 finding that private ambulances are a real, non-trivial share of the "
        "system. **New finding beyond the brief:** `unit_type` also includes `ENGINE`, `TRUCK`, "
        "`CHIEF`, `CP`, `RESCUE CAPTAIN`, `BLS`, `SUPPORT`, `RESCUE SQUAD` — i.e. this dataset's "
        "\"first on scene\" isn't necessarily an ambulance at all. See `docs/assumptions.md` §4 — "
        "left open for Phase 4 to resolve empirically against the official scorecard, the same way "
        "the clock-start question is resolved.",
    ),
    md("## Q9 — Missing `call_type_group`"),
    code(
        "call_type_group = con.execute(\"SELECT COALESCE(call_type_group,'(null)') AS g, COUNT(*) AS n FROM raw_calls GROUP BY 1 ORDER BY n DESC\").df()",
        "call_type_group",
    ),
    md(
        "8,345 nulls (2.3%) — close to the brief's Q9 finding. **New finding:** `call_type_group` "
        "also includes `Fire` (14,430 rows) and `Alarm` (91,937 rows) alongside the two EMS-"
        "relevant groups — confirming `nuek-vuh3` covers all SFFD dispatches, not EMS calls only "
        "(`docs/assumptions.md` §3). Phase 4's KPI scoping will filter explicitly to "
        "`Potentially Life-Threatening`, stated as a named rule, not an implicit `WHERE` clause.",
    ),
    md(
        "## Q10 — Official KPI vs. raw reconstruction",
        "",
        "Deferred to Phase 4 (`notebooks/04_metrics_reconciliation.ipynb`) — this requires the "
        "`fct_call` SQL model and the scorecard series, not just raw profiling. Not computed here "
        "to avoid a premature, unvalidated number in this notebook.",
    ),
    md("## Validation report summary"),
    code(
        "report = json.loads((REPO_ROOT / \"outputs\" / \"validation_report.json\").read_text())",
        "print(\"overall_status:\", report[\"overall_status\"])",
        "pd.DataFrame(report[\"checks\"])[[\"rule_id\", \"severity\", \"action\"]]",
    ),
    md(
        "## Summary",
        "",
        "- Structural checks (schema, rowid uniqueness, manifest completeness) all **PASS**.",
        "- Every known data-quality issue from the brief (Q2, Q4, Q5, Q9) reproduces at a similar "
        "  order of magnitude on the real 12-month pull and is now a named, thresholded WARN rule "
        "  in `pipeline/validate.py` rather than a one-off finding.",
        "- Two findings **beyond** the brief: the blank-priority rate is ~19x higher over 12 "
        "  months than the brief's 2-month sample suggested, and `nuek-vuh3`/`unit_type` cover "
        "  more than pure ambulance EMS response (`Fire`/`Alarm` call types, non-ambulance unit "
        "  types). Both are written up in `docs/assumptions.md` as open items for Phase 4, not "
        "  silently resolved here.",
        "- Overall validation status: **WARN** (no structural failures; six known, counted, "
        "  documented issues). Full detail: `outputs/validation_report.json`.",
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
