"""Chaos injection: mutate a just-extracted raw pull to simulate five failure
modes, so run_pipeline.py --chaos <scenario> proves the pipeline fails loudly
and safely (CLAUDE.md rule 8) instead of quietly publishing bad data.

Each function mutates the first raw page written by this run and returns a
one-line description of what it changed, logged by run_pipeline.py.

Isolation: a chaos run never touches the production warehouse or the real
KPI packs. run_pipeline.py copies data/processed/sf_ems.duckdb to a throwaway
data/processed/chaos_<run_id>.duckdb (deleted when the run ends, pass or fail)
and writes outputs to outputs/_chaos/<scope>/ (gitignored). Before this, a
late_update run permanently wrote a fake available_dttm into the real
warehouse (docs/review_findings.md A3).

How to see the late_update demo: run
    python run_pipeline.py --month 2026-02 --chaos late_update
and read the "[pipeline/chaos:late_update] verify" log line. It is written
from the throwaway warehouse right after the upsert and shows the amended
rowid's available_dttm/data_loaded_at (the new, amended value - upsert, not
append) and the raw_calls row count before vs after (unchanged for a month
already in the warehouse - no duplicate row).
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from pipeline.extract import RAW_DATA_DIR


def _first_page_path(run_ts: str, scope_dir: str) -> Path:
    """First raw calls page written by this run for this scope."""
    d = RAW_DATA_DIR / "calls" / f"run_ts={run_ts}" / scope_dir
    pages = sorted(d.glob("page_*.json"))
    if not pages:
        raise FileNotFoundError(f"no raw pages found under {d}")
    return pages[0]


def first_row_rowid(run_ts: str, scope_dir: str) -> Optional[str]:
    """rowid of the first row on the first raw page - the row late_update amends."""
    rows = json.loads(_first_page_path(run_ts, scope_dir).read_text(encoding="utf-8"))
    return rows[0].get("rowid") if rows else None


def inject_missing_column(run_ts: str, scope_dir: str) -> str:
    """Drop on_scene_dttm from every row - expect validate.py FAIL: schema_required_columns."""
    path = _first_page_path(run_ts, scope_dir)
    rows = json.loads(path.read_text(encoding="utf-8"))
    for row in rows:
        row.pop("on_scene_dttm", None)
    path.write_text(json.dumps(rows), encoding="utf-8")
    return f"removed on_scene_dttm from {len(rows)} rows in {path.name} -> expect FAIL: schema_required_columns"


def inject_duplicate_rowid(run_ts: str, scope_dir: str) -> str:
    """Duplicate the first row - expect validate.py WARN: rowid_uniqueness, then load.py dedupes via upsert.

    Also bumps manifest.json's rows_received by 1, so this scenario isolates
    the uniqueness check specifically (simulating the API itself legitimately
    sending a duplicate rowid) rather than also tripping manifest_completeness
    (a manifest/disk mismatch is the separate truncated_pagination scenario).
    """
    path = _first_page_path(run_ts, scope_dir)
    rows = json.loads(path.read_text(encoding="utf-8"))
    if rows:
        rows.append(dict(rows[0]))
    path.write_text(json.dumps(rows), encoding="utf-8")

    manifest_path = path.parent / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["rows_received"] += 1
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    rowid = rows[0].get("rowid") if rows else "?"
    return f"duplicated rowid={rowid} in {path.name} (manifest updated to match) -> expect WARN: rowid_uniqueness, then upsert dedupes on load"


def inject_stale_data(run_ts: str, scope_dir: str) -> str:
    """Rewrite data_loaded_at to 100h ago on every row - expect FAIL: freshness (only meaningful
    on a --since pull, since a --month backfill of a historical month is already 'stale' by design)."""
    path = _first_page_path(run_ts, scope_dir)
    rows = json.loads(path.read_text(encoding="utf-8"))
    stale_ts = (datetime.now(timezone.utc) - timedelta(hours=100)).strftime("%Y-%m-%dT%H:%M:%S.000")
    for row in rows:
        row["data_loaded_at"] = stale_ts
    path.write_text(json.dumps(rows), encoding="utf-8")
    return f"set data_loaded_at={stale_ts} on {len(rows)} rows in {path.name} -> expect FAIL: freshness (use --since for this scenario)"


def inject_truncated_pagination(run_ts: str, scope_dir: str) -> str:
    """Drop half the rows without updating manifest.json - expect FAIL: manifest_completeness
    (disk row count no longer matches what extract.py claimed it received)."""
    path = _first_page_path(run_ts, scope_dir)
    rows = json.loads(path.read_text(encoding="utf-8"))
    kept = rows[: len(rows) // 2]
    path.write_text(json.dumps(kept), encoding="utf-8")
    return f"truncated {path.name} from {len(rows)} to {len(kept)} rows, manifest.json left unchanged -> expect FAIL: manifest_completeness"


def inject_late_update(run_ts: str, scope_dir: str) -> str:
    """Amend the first row's available_dttm and bump data_loaded_at to now, simulating a
    late-arriving correction. Passes validation (nothing is broken) - run_pipeline.py then
    logs, from the throwaway chaos warehouse, that the total row count is unchanged (no
    duplicate) and the amended row's new value is reflected (upsert, not append)."""
    path = _first_page_path(run_ts, scope_dir)
    rows = json.loads(path.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000")
    if rows:
        rows[0]["available_dttm"] = now
        rows[0]["data_loaded_at"] = now
    path.write_text(json.dumps(rows), encoding="utf-8")
    rowid = rows[0].get("rowid") if rows else "?"
    return f"amended rowid={rowid} with a new available_dttm={now} -> see the '[pipeline/chaos:late_update] verify' log line after LOAD"


SCENARIOS = {
    "missing_column": inject_missing_column,
    "duplicate_rowid": inject_duplicate_rowid,
    "stale_data": inject_stale_data,
    "truncated_pagination": inject_truncated_pagination,
    "late_update": inject_late_update,
}
