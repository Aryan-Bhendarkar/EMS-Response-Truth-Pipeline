# Gate 2 — Data Readiness

> Filled in at the end of Phase 5 (Class 8), with concrete evidence from real runs against the
> live 12-month backfill (2025-07..2026-06, 364,873 rows) — no number below is asserted without
> a command that produced it.

## Status: READY

| Check | Status | Evidence |
|---|---|---|
| Sources identified with owner, grain, gaps | ✅ Done | `docs/source_map.md` — S1/S3 detailed, S4/weather cut with evidence |
| Retrieval proven complete (≥2 modes, raw preserved) | ✅ Done | See §1 below |
| Validation rules defined with severity + owner | ✅ Done | See §2 below |
| Idempotent rerun (same input → same output) | ✅ Done | See §3 below |
| Failure handling proven (`--chaos`) | ✅ Done | See §4 below |
| Tests green | ✅ Done | See §5 below |

---

## 1. Retrieval — complete, two modes, raw preserved

- **JSON API** (`pipeline/extract.py --backfill`): 12/12 months complete. API `count(*)` matched
  rows received exactly for every month (29,681–33,174 rows/month; total **364,873**, matching
  the pre-run size estimate). Manifests: `data/raw/calls/run_ts=20260923T163957Z/*/manifest.json`.
- **CSV export** (`pipeline/extract.py --csv-month`): cross-checked June 2026 — **28,737 rows via
  JSON, 28,737 via CSV**, exact match, two independently-implemented retrieval paths.
- Every raw page saved untouched under `data/raw/<source>/run_ts=<timestamp>/`, never overwritten.

## 2. Validation — 13 named rules, real result

Run: `python -m pipeline.validate --run-ts 20260923T163957Z` → `outputs/validation_report.json`.

**Result: `overall_status = WARN`** — 7 PASS, 6 WARN, 0 FAIL, across schema, rowid uniqueness,
manifest-completeness cross-check, 3 null-rate checks, 5 timestamp-order checks, priority-domain,
and freshness. Every WARN has a named rule, a counted metric, and a next action (thresholds:
`config/validation_rules.yaml`; unconfirmed mappings and their owners: `docs/assumptions.md`).

A real bug was found and fixed here: a genuinely missing column (simulated by `--chaos
missing_column`) crashed several downstream checks with a raw `BinderException` instead of
failing cleanly, because they blindly queried columns without checking the schema check's result
first. Fixed: `run_validation()` now short-circuits column-dependent checks when the schema check
itself FAILs (`pipeline/validate.py`).

## 3. Idempotent rerun — proven, with the one legitimate exception documented

`python run_pipeline.py --month 2026-06` run twice in succession:

- `outputs/2026-06/metrics.json`: **byte-identical** between runs.
- `outputs/2026-06/validation_report.json`: identical except `generated_at`, `run_ts`, and
  `received_age_hours` (a wall-clock-relative freshness metric) — all three are *supposed* to
  differ between runs, since they measure "when did this run happen," not "what did it compute."
  Every substantive field (check severities, row counts, metrics) is exactly reproducible.

A real non-determinism was found and fixed along the way: DuckDB's `approx_quantile` produced
slightly different p90 values (4.7 vs 4.8 minutes) across two otherwise-identical runs — an
artifact of its approximate (t-digest) algorithm. Since this project's data volumes are small
enough that exact computation is cheap, every `approx_quantile` call in `pipeline/metrics.py` and
the notebooks was switched to `quantile_cont` (exact). Re-verified: `metrics.json` identical
after the fix. This also incidentally corrected M3's travel-time figures to match the brief's
original prototype numbers much more closely (see `docs/decision_log.md`).

## 4. Failure handling — all 5 `--chaos` scenarios verified

| Scenario | Command | Result |
|---|---|---|
| `missing_column` | `--month 2026-05 --chaos missing_column` | **FAIL** `schema_required_columns`. Exit code 1. No `outputs/2026-05/` directory created — nothing published. |
| `duplicate_rowid` | `--month 2026-04 --chaos duplicate_rowid` | **WARN** `rowid_uniqueness` (not FAIL, per spec). Pipeline continued; `load.py`'s upsert-by-rowid absorbed the duplicate (`364873 -> 364873 rows, net +0`) — deduped, not appended. |
| `stale_data` | `--since 3 --chaos stale_data` | **FAIL** `freshness`. Exit code 1. Only meaningful on a `--since`/current pull — a `--month` backfill of a historical month is already outside the freshness window by design (see `pipeline/validate.py`'s `check_freshness` docstring). |
| `truncated_pagination` | `--month 2026-03 --chaos truncated_pagination` | **FAIL** `manifest_completeness` — on-disk row count no longer matched what `extract.py` originally claimed. Exit code 1. |
| `late_update` | `--month 2026-02 --chaos late_update` | Passed validation normally (nothing broken). Re-running `load.py` afterward: warehouse row count unchanged (`364873 -> 364873`, net +0), but the amended row's `available_dttm`/`data_loaded_at` reflected the new value — confirmed directly by querying the warehouse for that `rowid`. Proves upsert, not duplicate-append. |

Two real bugs were caught and fixed via this testing, not just simulated:
1. `check_timestamp_order`/`check_null_rates` crashing on a missing column (§2).
2. `duplicate_rowid` chaos incidentally tripping `manifest_completeness` too, because the
   injected duplicate wasn't reflected in `manifest.json`'s row count — fixed by having the
   injector update the manifest, isolating each scenario to the check it's meant to demonstrate.

## 5. Tests — 24/24 passing

`python -m pytest tests/` → **24 passed in ~1.2s**. Hermetic: synthetic in-memory DuckDB
fixtures, no network access or real data pull required.

- `tests/test_validate.py` (14 tests): severity threshold boundaries, schema check,
  rowid-uniqueness WARN-not-FAIL behavior, timestamp-order violation detection, priority-domain
  unexpected-value detection, null-rate PASS/FAIL boundaries.
- `tests/test_definitions.py` (10 tests): `config/kpi_definitions.yaml` structural integrity
  (every definition has required fields, no definition is pre-marked confirmed, IDs unique), and
  `compute_m1_definition_monthly`'s core rules — target-minute boundary, the no-arrival-excluded-
  from-denominator rule (`docs/assumptions.md` §5b), priority filtering, unit-scope column
  selection.

## Known limitation of this gate

All runs above used the anonymous Socrata rate limit (no `SOCRATA_APP_TOKEN` configured) — this
worked reliably but slowly (~20-25s/month). The retry/backoff path in `pipeline/extract.py` exists
and is exercised by real 429 responses under this rate limit, but was not independently unit-
tested against a mocked failure sequence. Acceptable for this project's scale; would be worth a
dedicated test before scaling to a much larger backfill window.
