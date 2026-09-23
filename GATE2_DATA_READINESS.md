# Gate 2 — Data Readiness

> Filled in at the end of Phase 5 (Class 8), once extract → validate → load → transform → metrics → report → save
> has run end-to-end and the chaos scenarios have been exercised. This is a stub until then.

## Status: NOT YET READY (pipeline not built)

| Check | Status | Evidence |
|---|---|---|
| Sources identified with owner, grain, gaps | Pending | `docs/source_map.md` |
| Retrieval proven complete (≥2 modes, raw preserved) | Pending | `pipeline/extract.py`, `data/raw/` |
| Validation rules defined with severity + owner | Pending | `pipeline/validate.py`, `outputs/<month>/validation_report.json` |
| Idempotent rerun (same input → same output) | Pending | run twice, diff outputs |
| Failure handling proven (`--chaos`) | Pending | `missing_column`, `duplicate_rowid`, `stale_data`, `truncated_pagination`, `late_update` |
| Tests green | Pending | `pytest` |

Will be updated with concrete run evidence in Phase 5.
