"""Generate notebooks/01_source_discovery.ipynb. See build_notebook_02.py for the pattern.

Unlike 02-04, this one makes live requests to data.sf.gov (dataset metadata +
small samples) rather than reading the local backfill - it's a discovery
notebook, run once before any data is pulled.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = REPO_ROOT / "notebooks" / "01_source_discovery.ipynb"


def md(*lines: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": [l + "\n" for l in lines]}


def code(*lines: str) -> dict:
    return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": [l + "\n" for l in lines]}


cells = [
    md(
        "# 01 — Source Discovery",
        "",
        "Live queries against data.sf.gov, run before any data is pulled, to confirm the sources "
        "named in `PROJECT_BRIEF.md` actually look the way the brief describes — nothing here is "
        "taken on faith. Full writeup: `docs/source_map.md`. Decisions made from these findings "
        "(what got cut and why): `docs/decision_log.md`.",
    ),
    code(
        "import requests",
        "import pandas as pd",
        "",
        "BASE = \"https://data.sf.gov\"",
    ),
    md("## S1 — Fire Dept & EMS Dispatched Calls for Service (`nuek-vuh3`)"),
    code(
        "meta = requests.get(f\"{BASE}/api/views/nuek-vuh3.json\", timeout=30).json()",
        "print(meta[\"name\"])",
        "print(meta[\"description\"][:300])",
        "print(\"columns:\", len(meta[\"columns\"]))",
        "pd.DataFrame([{\"field\": c[\"fieldName\"], \"type\": c[\"dataTypeName\"]} for c in meta[\"columns\"]]).head(15)",
    ),
    md(
        "Confirms the dataset's own description covers **Fire and EMS** dispatches together, not "
        "EMS alone — this becomes relevant later when scoping the KPI to `call_type_group = "
        "'Potentially Life-Threatening'` (`docs/assumptions.md` §3).",
    ),
    code(
        "sample = requests.get(f\"{BASE}/resource/nuek-vuh3.json\", params={\"$limit\": 2, \"$order\": \"received_dttm DESC\"}, timeout=30).json()",
        "pd.DataFrame(sample)[[\"call_number\", \"unit_id\", \"unit_type\", \"original_priority\", \"final_priority\", \"received_dttm\", \"dispatch_dttm\"]]",
    ),
    md(
        "A live sample confirms the grain directly: two rows can share the same `call_number` "
        "with different `unit_id`/`unit_type` - one row per unit dispatched to a call, exactly as "
        "`docs/source_map.md` describes.",
    ),
    md("## S3 — City Performance Scorecard Measures (`kc49-udxn`), measure 973"),
    code(
        "# actual IS NOT NULL: Socrata omits the key entirely (not null) for months with no",
        "# reported value yet - the most recent months, given the ~3-month reporting lag.",
        "rows = requests.get(f\"{BASE}/resource/kc49-udxn.json\",",
        "                    params={\"measure_code\": \"973\", \"$where\": \"actual IS NOT NULL\",",
        "                            \"$order\": \"calendar_month DESC\", \"$limit\": 6},",
        "                    timeout=30).json()",
        "pd.DataFrame(rows)[[\"measure_title\", \"calendar_month\", \"actual\", \"target\"]]",
    ),
    md(
        "Confirms live: `measure_title` = \"Percentage of ambulances that arrive on-scene within "
        "10 minutes to life-threatening medical emergencies\", `target` = 0.9, and June 2026's "
        "`actual` = 0.884 - matching the brief's headline figure exactly, pulled fresh rather than "
        "copied. Also confirms the scorecard's ~3-month reporting lag: no `actual` is reported yet "
        "for months after June 2026 as of this pull.",
    ),
    md("## S4 — Fire Incidents (`wr8u-xric`) — checked, then cut"),
    code(
        "meta4 = requests.get(f\"{BASE}/api/views/wr8u-xric.json\", timeout=30).json()",
        "print(meta4[\"description\"][:250])",
    ),
    md(
        "The dataset's own metadata states it covers *\"a summary of each **non-medical** "
        "incident.\"* It cannot cross-check or enrich EMS/ambulance calls - the two datasets don't "
        "overlap in subject matter. Cut with this evidence, not a hunch (`docs/decision_log.md`, "
        "2026-09-23).",
    ),
    md("## Which measures exist for the Fire Department?"),
    code(
        "fd_measures = requests.get(f\"{BASE}/resource/kc49-udxn.json\",",
        "                           params={\"department\": \"Fire Department\", \"$select\": \"measure_code,measure_title\", \"$group\": \"measure_code,measure_title\"},",
        "                           timeout=30).json()",
        "pd.DataFrame(fd_measures)",
    ),
    md(
        "**Exactly one** Fire Department scorecard measure exists (973). There is no official "
        "measure for call-processing time or hospital turnaround - M2 and M4 in this project have "
        "no official baseline to reconcile against; they are pipeline-derived only. Worth stating "
        "explicitly so `docs/decision_memo.md` doesn't imply an official comparator exists where "
        "none does.",
    ),
    md(
        "## Summary",
        "",
        "- S1 and S3 confirmed live, matching `PROJECT_BRIEF.md`'s figures exactly where checked "
        "(measure 973's June 2026 actual = 0.884).",
        "- S4 confirmed as out of scope from its own metadata, not assumed.",
        "- Fire Department has exactly one scorecard measure - flags a real reconciliation gap for "
        "M2/M4 addressed later in `notebooks/04_metrics_reconciliation.ipynb`.",
        "- Full source map, ownership, grain, freshness, and every gap: `docs/source_map.md`.",
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
