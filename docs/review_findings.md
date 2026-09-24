# Senior FDE Review — Findings Log (2026-09-24)

> Full-repo review after Phase 6, before submission. Every finding below was verified against
> the code, the real warehouse, or `outputs/metrics.json`. Nothing is inferred. Status column
> is updated as fixes land.
>
> Severity: **P0** = wrong number in a deliverable, or a documented command that crashes ·
> **P1** = correctness or dependability gap · **P2** = rubric/brief gap · **P3** = cleanup.

## A. Correctness bugs (verified)

| # | Sev | Finding | Evidence | Fix |
|---|---|---|---|---|
| A1 | P0 | **README quickstart crashes at REPORT.** `build_dashboard_html` does `official_pct*100` and `best_pct*100` with no None guard. Any month without a published scorecard actual (e.g. `--month 2026-07`, every `--since` run, any fresh clone) raises `TypeError`. | Synthetic call with empty `official_scorecard_by_month` → `TypeError: unsupported operand type(s) for *: 'NoneType' and 'int'` | Render "n/a" for missing values; test it |
| A2 | P0 | **Per-month KPI pack is not month-scoped.** `outputs/2026-06/metrics.json` contains all 12 months; the dashboard headlines "the latest month in the warehouse", not the month that was run. | `outputs/2026-06/metrics.json` → 12 distinct months | Add `scope_month` to metrics; dashboard and pack headline the run's month, full history kept as context |
| A3 | P1 | **Chaos runs write to the production warehouse.** `--chaos late_update` permanently wrote a fake `available_dttm`/`data_loaded_at` (2026-09-23) for rowid `260320014-B01`. Because the fake `data_loaded_at` is newer, reloading the real raw data can never overwrite it. | `SELECT ... WHERE rowid='260320014-B01'` → `available_dttm=2026-09-23T17:51:37` | Chaos runs use a throwaway warehouse copy and `outputs/_chaos/`; repair the row |
| A4 | P1 | **Incremental mode (`--since 3`) FAILs on real data.** Timestamp-order rate thresholds were calibrated on 365k closed rows. A 3-day pull has ~700 transport/hospital pairs, so 9 violations = 1.25% → FAIL. | Re-validated `run_ts=20260923T174948Z` → `timestamp_order_transport_dttm_before_hospital_dttm FAIL` (9/720) | Minimum-sample rule: below N pairs, rate checks cap at WARN (config-driven, logged in decision log) |
| A5 | P1 | `required_columns` omits columns the SQL models need (`transport_dttm`, `hospital_dttm`, `unit_sequence_in_call_dispatch`, `als_unit`, `call_type`, ...). A schema drop on those passes validation and crashes TRANSFORM instead of failing cleanly. | `010_stg_unit_response.sql` vs `config/validation_rules.yaml` | Add every column the SQL reads |
| A6 | P1 | `outlier_p999_fields` is configured but never checked (brief Q6). Dead config. | `grep outlier_p999 pipeline/` → no hits | Implement as a WARN-level, flag-only check |
| A7 | P2 | Log timestamps are labelled `Z` but formatted in local time. They're only correct because WSL runs on UTC. | `logging_utils.py` datefmt `...Z` without `converter=gmtime` | Set `formatter.converter = time.gmtime` |
| A8 | P2 | `check_freshness` crashes when the pull has 0 rows (`MAX()` returns None). `profile_summary` still runs after a schema FAIL and can crash if a profiled column is the missing one. | Code read | Guard both |
| A9 | P2 | CSV extract counts rows by counting newlines, so a quoted field with an embedded newline overcounts. | `extract.py` `response.text.count("\n")` | Count with the `csv` module |

## B. Wrong or inconsistent numbers in deliverables (verified against `outputs/metrics.json`)

| # | Sev | Where | Stated | Actual | Fix |
|---|---|---|---|---|---|
| B1 | P0 | `evidence_table.md`, `decision_memo.md` | 21,896 ambulance-hours ≈ "~7.5" / "7-8" twelve-hour shifts per day | 21,896 / 365 / 12 = **5.0 shifts/day** (the brief's "7/day" came from one July month) | Correct to ~5 |
| B2 | P0 | `evidence_table.md` M5 | Dispatch 83.8% vs received 66.8%, gap 17.1 | M5's 17.1 is `dispatch_final_ambulance` (82.3%) − `received_final_ambulance` (65.3%). 66.8% matches no definition. The table mixes two definition pairs. | Show one consistent pair; add the like-for-like best-fit pair (83.8 − 65.7 = **18.1**) as a second row |
| B3 | P1 | `judgement_call.md` | M2 median 2.3 / p90 4.9 | **2.2 / 4.8** | Correct |
| B4 | P1 | `decision_memo.md` | "3.5-point gap vs. 17-22 points" for received-clock definitions | Received-clock gaps are **21.6–22.1**. The 17 is the clock gap, a different quantity. | Correct |
| B5 | P2 | evidence, judgement call, memo | Dispatch clock wins "by an order of magnitude" | 3.5 vs 21.6 ≈ **6×** | Soften the wording |
| B6 | P2 | `decision_memo.md` finding 4 | Calls the 30-min figure a "lower bound" | The interval includes cleaning/restocking (brief §4), so it's an upper bound on the hospital's share. It's a lower bound only against the stricter offload standard. | Reword precisely |
| B7 | P2 | all M4 docs | Policy 4000.1 cited as "the standard" | The policy is **effective 2026-10-01**, after the whole analysis window. It's the forward standard, not the one in force at the time. | State this as a limitation |

## C. Brief / rubric gaps

| # | Sev | Gap | Fix |
|---|---|---|---|
| C1 | P2 | `docs/kpi_definitions.md` is listed in brief §9/D5 but doesn't exist | Human-readable M1–M5 definitions, each with owner and status |
| C2 | P2 | `dim_priority_map` (brief §5, cited as rubric evidence in §8) isn't built. The priority mapping lives only in prose. | `config/priority_map.yaml` → `dim_priority_map` table with `confirmed_by_owner=false` |
| C3 | P2 | Dashboard (D4) should show *each* definition vs the 90% target and the official value. It currently shows only the best fit plus gap averages. | Add a per-definition table for the scoped month |
| C4 | P2 | Test gaps: no tests for load/upsert idempotency, the late update, freshness, manifest completeness, extract helpers and retry, reconcile/M5, report rendering, or an end-to-end run. The committed `sample_day` raw data isn't used by anything. | Add unit tests plus a hermetic end-to-end test over `sample_day` + the committed scorecard page |
| C5 | P3 | No CI (brief lists it as optional) | GitHub Actions: pytest on push |
| C6 | P2 | `decision_log.md` misses later pivots that are only described in GATE2 or code: approx→exact quantiles, the `date_diff('minute')` bias, M3 ambulance-only scope, M1 no-arrival denominator rule, freshness not applying to backfills | Add the entries |
| C7 | P2 | Stale "open going into Phase 2/3/4" sections in `source_map.md` §4 and `assumptions.md` §1/§3. Resolved items aren't marked resolved. Section numbering runs 1,2,3,4,5b,5. | Mark resolutions, renumber |

## D. Code quality / unnecessary

| # | Sev | Finding | Fix |
|---|---|---|---|
| D1 | P3 | `extract.py`: three near-identical extract functions (~150 duplicated lines); dead `last_day` code in `month_bounds` | One shared `_extract_to_raw()` helper |
| D2 | P3 | KPI CSV writer duplicated in `metrics.py` and `save.py` | One `kpi_monthly_csv()` |
| D3 | P2 | Hard-coded values in `metrics.py`: measure code `'973'` and the M5 definition IDs (CLAUDE.md rule 3) | Move to config |
| D4 | P3 | `run_pipeline.py`: unused `is_historical`, redundant `scope_dir`, `run()` has no docstring or Optional hints | Clean up |
| D5 | P3 | `requirements.txt` isn't pinned (CLAUDE.md says pin). Jupyter is mixed into runtime deps. | Pin; split into `requirements-dev.txt` |
| D6 | P3 | `.env.example` lists `SOCRATA_USERNAME`/`PASSWORD` it says are unused | Remove |
| D7 | P3 | `PROJECT_BRIEF.md` still carries prototype numbers (87.4%, 20-min standard, 7 shifts/day) that were later superseded, and nothing signposts that | Add a header note pointing to the decision log (brief body left intact) |
| D8 | P3 | Local clutter (not in git): 14 chaos/test raw runs (~1 GB in `data/raw`) and 20+ logs | Left alone on purpose: gitignored, and the raw runs are the audit trail for the chaos evidence. Safe to delete by hand (`data/raw/calls/run_ts=*` except the backfill `20260923T163957Z` and `sample_day`). |

## E. Open questions for the owner — NOT changed (CLAUDE.md: KPI/storyline changes need sign-off)

1. **M2 scope:** call processing is computed over *all* SFFD calls, including fire alarms. Scope it to medical / Potentially Life-Threatening calls?
2. **Dispatch clock:** `fct_call.dispatch_dttm` is the first dispatch of *any* unit, so MEDIC-only definitions start the clock when an engine may have been dispatched first. Add a "first ambulance dispatched" candidate?
3. **M5 pair:** the headline 17.1-pt gap uses the `final_ambulance` pair. The like-for-like best-fit pair is 18.1. The pair is now configurable, but the default is unchanged.

## F. Found during the fix pass (by the new tests)

| # | Sev | Finding | Fix |
|---|---|---|---|
| A10 | P1 | `--since` freshness decided "historical" from the data's own age, so a source stalled for >48h passed as "not applicable" and would be published as current | `check_freshness(..., incremental=True)` for `--since` runs always judges freshness |
| A11 | P1 | LOAD crashed (`BinderException`) when a later pull lacked an optional column. Socrata omits a field that is null on every row. | `upsert_calls` selects `NULL` for absent non-required columns |

## Resolution (2026-09-24)

All findings in sections A–D and F are **fixed**. Section E is left open for the owner's decision.
D8 (local clutter) was intentionally left alone. Verification:

- `python -m pytest tests/` → **99 passed** (was 24), including a hermetic end-to-end test over the
  committed sample. CI: `.github/workflows/tests.yml`.
- Live `python run_pipeline.py --month 2026-06` → WARN (15 checks: 7 PASS / 8 WARN / 0 FAIL).
  The upsert gave 364,873 → 364,873 rows and the best fit is unchanged (`dispatch_original_medic`,
  3.51 pts).
- Live `python run_pipeline.py --since 3 --chaos late_update` → the incremental path now passes
  (it used to FAIL on sampling noise). 2,037 new rows went into a throwaway warehouse only, which
  was deleted afterwards. The production warehouse is still 364,873 rows with max `received_dttm`
  2026-06-30.
- Warehouse row `260320014-B01` has been restored to its real `available_dttm` (2026-02-01T00:14:34).
- `outputs/metrics.json` was regenerated. The committed copy still held pre-Phase-5
  `approx_quantile` values, so M2–M4 percentiles move by up to ±0.1 min. M1, M5 and all counts
  are unchanged.
