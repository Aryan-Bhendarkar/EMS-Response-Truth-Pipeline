# Decision Log

Format: date, finding, options considered, choice, why. Every entry is triggered by evidence
shown at the time (query, quote, or document), per CLAUDE.md rule 5.

---

## 2026-09-23 — Cut the Fire Incidents dataset (`wr8u-xric`)

**Finding:** `wr8u-xric`'s own DataSF metadata describes it as *"a summary of each **non-medical**
incident to which the SF Fire Department responded"* (fetched via `data.sf.gov/api/views/wr8u-xric.json`).
Its columns (`suppression_units`, `ignition_cause`, `estimated_property_loss`, `action_taken_primary`)
are fire-suppression fields, not EMS/ambulance fields.

**Options:**
1. Keep it as a cross-check per the brief (§3, S4) — verify a call "really happened" and see its outcome.
2. Cut it.

**Choice:** Cut. `call_final_disposition` in S1 (`nuek-vuh3`) already gives per-unit outcome for
every medical response, and S4 is explicitly scoped to exclude medical incidents — there is no
overlapping subject matter for it to cross-check against. Pulling it would add a retrieval mode
with no evidentiary payoff.

**Why it matters:** The brief listed this as an open Phase-1 decision ("Cut what doesn't earn its
place"); this closes it with primary-source evidence rather than a hunch.

---

## 2026-09-23 — Cut the Open-Meteo weather API (for now)

**Finding:** No change from the brief — it already frames weather as "context signal only
(association, not cause)," and CLAUDE.md rule 10 rules out causal claims for this project.

**Options:**
1. Pull it now, speculatively, in case it's useful later.
2. Cut it until a specific, testable question emerges from profiling (e.g., "does rain raise
   travel-time p90?").

**Choice:** Cut for now. Revisit only if Phase 3/4 profiling surfaces a concrete hypothesis it
would actually test — adding a source with no specific question attached is scope creep, not
retrieval-mode credit.

---

## 2026-09-23 — M4 (hospital capacity loss) redefined against the 30-minute turnaround standard, not the 20-minute offload standard

**Finding:** `PROJECT_BRIEF.md` §4 says "Official policy is 20 min hand-over, 90% of the time"
for the `available_dttm − hospital_dttm` interval computed from S1. Reading the actual policy
(SF EMS Agency Policy 4000.1, *Ambulance Turnaround Time Standard*, effective 10/1/26,
`media.api.sf.gov/documents/EMSA-4000.1-Ambulance-Turnaround-Time-Standard-10-1-2026.pdf`)
shows there are **two separate standards**:
- **Offload time interval ≤ 20 min, 90%** (§4.1) — measured to "APOT-1," defined as the moment a
  patient is moved off the gurney *and* transfer of care is signed off by an ED nurse/doctor in
  the hospital's own EHR. **No field in S1 captures this** — it lives entirely in a hospital
  system this project has no access to.
- **Ambulance turnaround interval ≤ 30 min, 90%** (§4.2) — ED arrival to return-to-service. This
  interval **is** what `hospital_dttm → available_dttm` in S1 approximates.

**Options:**
1. Keep comparing the raw `available_dttm − hospital_dttm` interval to the 20-minute standard, as
   the brief originally framed it.
2. Compare it to the 30-minute turnaround standard instead, and name APOT-1/20-minute as a known
   blind spot the data cannot see.

**Choice:** Option 2. Comparing raw CAD data to a standard it structurally cannot measure would
overstate how bad hospital hand-over looks and misrepresent the policy. The 42-minute median wall
time cited in the brief is still a real finding — it now needs to be read against the 30-minute/90%
turnaround target, not the 20-minute one, and the gap to the *offload* standard should be reported
as unmeasurable with this data source, not silently assumed.

**Owner for closing this gap:** SF EMS Agency (source of the APOT-1 signature data, held in
hospital EHR systems, not DataSF) — noted as an unconfirmed/unavailable data source, per
`docs/source_map.md` §4.

---

## 2026-09-23 — "Which clock starts the official measure" stays an open question, not an assumption

**Finding:** A web search paraphrase claimed the official measure's clock runs "Call Dispatched →
Units On-Scene" ("Roll Time"), but this was not read directly from a primary SF EMS Agency or
Controller's Office document — every primary document actually read (FY25 APR p.17, the scorecard
API record for measure 973) describes the target ("10 minutes, 90% of the time, Code 3") without
stating which timestamp starts the clock.

**Choice:** Do not treat "dispatch" as confirmed. Phase 4 will compute M1 under both a
dispatch-clock and a call-received-clock definition across all backfilled months and see which one
actually reproduces the officially published `actual` values in `kc49-udxn` — that empirical match
is the real evidence, not a search-engine summary. This is exactly the "which clock?" judgement
call the brief anticipated (§4, §8) — it stays open until Phase 4 produces that comparison.

**Update (Phase 4):** tested. Every dispatch-clock candidate fits the official number within
3.5-5.0 points (mean absolute gap); every received-clock candidate is 21.6-22.1 points off. The
call and its limits are in `docs/judgement_call.md`. Still unconfirmed by a primary document.

---

## 2026-09-23 — Backfill window sized and pulled; second retrieval mode added as a real cross-check, not a token file format

**Finding:** Live `count(*)` queries against `nuek-vuh3` gave 364,873 rows for 2025-07..2026-06
(the reconciliation window chosen above) vs. 357,126 rows for 2025-10..2026-09 (a naive
"12 months back from today" window, which would leave the 3 most recent months unreconcilable
against the scorecard's ~3-month lag). Both are close to the brief's ~350k estimate.

**Choice:** Pulled the full 2025-07..2026-06 window via `pipeline/extract.py --backfill`
(month-by-month SODA API, JSON). All 12 months came back complete — the API's own `count(*)`
matched rows received exactly for every month (29,681 .. 33,174 rows/month; total 364,873,
`data/raw/calls/run_ts=20260923T163957Z/*/manifest.json`).

For the second retrieval mode required by the rubric ("≥2 modes across SQL, API, JSON/CSV/files"),
considered pulling the true bulk export (`accessType=DOWNLOAD`, 7.44M rows, full 2000-present
history) as brief §3 (S2) originally suggested, but rejected it: that file is about 20× larger
(7.44M vs. 364,873 rows) than the analysis window needs, contradicts the brief's own "scope to 12 months"
sizing decision (§11), and downloading it would cost real time for zero analytical value — we
don't use pre-2025 data anywhere in this project.

**Instead:** implemented `extract_calls_month_csv()`, pulling the same month through the SODA
API's CSV export format (`.csv` instead of `.json`) rather than the unfiltered bulk file. Ran it
for June 2026 and compared against the JSON pull for the same month: **28,737 rows both ways,
exact match.** This is a genuine second format/parser path (different content-type, different
parsing code) and doubles as a completeness cross-check between two independently-implemented
retrieval paths for the same data — stronger evidence than a format swap alone would give.

**Why it matters:** Satisfies the retrieval-mode requirement with a real validation payoff instead
of a checkbox exercise, and keeps local storage/runtime proportionate to what the project actually
analyzes.

---

## 2026-09-23 — Exact quantiles (`quantile_cont`) instead of `approx_quantile`

**Finding:** Two otherwise-identical runs gave different M2 p90 values (4.7 vs. 4.8 minutes).
DuckDB's `approx_quantile` uses an approximate (t-digest) algorithm, so its result is not
guaranteed to repeat run to run (`GATE2_DATA_READINESS.md` §3).

**Options:**
1. Keep `approx_quantile` and accept small run-to-run drift.
2. Switch to exact `quantile_cont`.

**Choice:** Option 2, in `pipeline/metrics.py` and the notebooks.

**Why:** CLAUDE.md rule 7 (idempotent by default): a rerun of the same period must give the same
numbers. At this project's data volume (~365k rows) exact quantiles are cheap. Re-verified:
`metrics.json` identical across reruns after the change.

---

## 2026-09-23 — Durations computed as `date_diff('second', ...) / 60.0`, not `date_diff('minute', ...)`

**Finding:** DuckDB's `date_diff('minute', a, b)` compares minute-truncated timestamps, not true
elapsed time: 01:40:49 → 01:53:13 reports 13 minutes, not the true 12.4 (`pipeline/metrics.py`,
`compute_m1_definition_monthly` docstring; `notebooks/03_workflow_model.ipynb`). That is up to
~1 minute of bias, enough to flip calls sitting right at the 10-minute compliance boundary.

**Options:**
1. Keep minute-unit diffs (simpler, but biased).
2. Diff in seconds and divide by 60.

**Choice:** Option 2, for every duration in M1-M4.

**Why:** The KPI is a threshold test at exactly 10 minutes, so truncation bias at the boundary
changes the headline number, not just the decimals.

---

## 2026-09-23 — M3 travel time scoped to ambulances (`MEDIC`/`PRIVATE`) only

**Finding:** Pooled over the 12-month window, en-route → on-scene across **all** unit types is
p50 4.4 min / p90 15.3 min. Restricted to `MEDIC`/`PRIVATE` it is p50 7.4 min / p90 17.5 min
(query: `quantile_cont(date_diff('second', response_dttm, on_scene_dttm)/60.0, …)` on
`stg_unit_response`, same filters as `compute_m3_travel_time`; the p90 is 17.48, which the
docstring in `pipeline/metrics.py` truncates to 17.4). Fire engines and trucks arrive faster and
are more numerous, so they pull the all-units figure down.

**Options:**
1. All units (first-responder coverage).
2. Ambulance units only.

**Choice:** Option 2.

**Why:** M3 is meant to inform ambulance deployment and positioning (`PROJECT_BRIEF.md` §6). The
all-units figure measures something else (first-responder coverage) and would understate
ambulance travel time by ~3 minutes at the median.

---

## 2026-09-23 — M1 denominator excludes calls with no recorded arrival

**Finding:** A large share of unit responses have no `on_scene_dttm` (`docs/assumptions.md` §2).
For the best-fitting definition, 51,668 eligible calls over 12 months had no MEDIC arrival
recorded, against a denominator of 39,729 (`outputs/metrics.json` → `m1_kpi_monthly`, sum of
`excluded_no_arrival` and `denominator`).

**Options:**
1. Count no-arrival calls as automatic misses.
2. Exclude them from the ratio, and report the excluded count every month.

**Choice:** Option 2 (`docs/assumptions.md` §5).

**Why:** You can't measure time-to-arrival for a call nothing arrived at. Counting them as misses
would mix two problems (slow response vs. no response) into one number. The exclusion is named
and counted in `kpi_monthly.csv`, not hidden. This is the project's own choice,
`confirmed_by_owner: false`.

---

## 2026-09-23 — Freshness check does not apply to a historical backfill

**Finding:** The 12-month backfill (2025-07..2026-06) will always have an old `data_loaded_at`,
because the window was chosen on purpose to end at the latest month with an official scorecard
value. A plain "newest row within 48h" rule would FAIL every backfill.

**Options:**
1. Drop the freshness check.
2. Keep it, but only judge pulls whose own data reaches near the present.

**Choice:** Option 2 (`pipeline/validate.py`, `check_freshness` docstring). If the pull's newest
`received_dttm` is already older than the threshold, the check PASSes with a "not applicable:
historical window" note in the validation report. `--since` / current-month pulls are still
checked.

**Why:** Staleness means "the source stopped updating", not "we asked for old data on purpose".

---

## 2026-09-24 — Timestamp-order checks cap at WARN on small samples

**Finding:** The timestamp-order violation thresholds (WARN > 0.05%, FAIL ≥ 1%) were calibrated
on ~365k closed rows. A 3-day incremental pull (`--since 3`) has only ~720 transport/hospital
pairs, so 9 violations = 1.25% → FAIL. The run stopped on sampling noise alone
(`run_ts=20260923T174948Z`, `docs/review_findings.md` A4).

**Options:**
1. Separate thresholds for incremental pulls.
2. Count-based thresholds instead of rates.
3. A minimum sample size: below it, a rate check can WARN but not FAIL.

**Choice:** Option 3. `config/validation_rules.yaml` → `min_pairs_for_fail: 5000`. Below 5,000
compared pairs, a FAIL-level rate is capped at WARN and the check's metrics record
`capped_small_sample: true`, so the cap is visible in the validation report.

**Why:** One rule works for both backfills and incremental pulls, needs no second set of
thresholds to tune, and keeps FAIL meaning "the data is broken", not "the sample is small".
Full-month and backfill runs are far above 5,000 pairs, so their behaviour is unchanged.

---

## 2026-09-24 — Chaos runs isolated from the real warehouse

**Finding:** `--chaos late_update` permanently wrote a fake row to the real warehouse: rowid
`260320014-B01` got `available_dttm` / `data_loaded_at` = 2026-09-23. Because the fake
`data_loaded_at` is newer than the real one, reloading the real raw data could never overwrite
it ("latest `data_loaded_at` wins") (`docs/review_findings.md` A3).

**Options:**
1. Keep chaos on the real warehouse and undo each scenario afterwards.
2. Run chaos against a throwaway copy of the warehouse and write outputs to `outputs/_chaos/`.

**Choice:** Option 2. The damaged row was repaired with `scripts/repair_chaos_row.py`.

**Why:** A failure test must never be able to change production numbers. Undo logic (option 1)
can itself fail; isolation cannot leak.

---

## 2026-09-24 — p99.9 outlier check: WARN, flag only

**Finding:** `outlier_p999_fields` was configured in `config/validation_rules.yaml` (brief §4, Q6)
but no code read it (`docs/review_findings.md` A6).

**Options:**
1. Delete the dead config.
2. Implement it as a FAIL, or as an exclusion rule.
3. Implement it as a WARN-level, flag-only check.

**Choice:** Option 3. The check reports values beyond the 99.9th percentile for each configured
interval. It never excludes rows and never stops the run.

**Why:** Metrics use medians and p90, which extreme values barely move. Excluding outliers would
be a silent fix (CLAUDE.md rule 5); flagging them lets a person decide.

---

## 2026-09-24 — Correction: ambulance-hours lost ≈ 5 shifts/day, not 7.5

**Finding:** `outputs/evidence_table.md` and `docs/decision_memo.md` said the 21,896
ambulance-hours lost over 12 months equal "~7.5" / "7-8" twelve-hour shifts per day. The
arithmetic is 21,896 ÷ 365 ÷ 12 ≈ **5.0** shifts per day. The wrong figure echoed the brief's
"about 7 shifts per day", which came from a single month (July 2026) measured against the
20-minute standard, and was not recomputed for this 12-month window and the 30-minute standard.

**Choice:** Corrected to ~5 in both documents. The 21,896-hour figure itself was right.

**Why it matters:** This was an arithmetic error, not a data error, and it overstated the
headline by half. Logged so the correction is visible, not quietly patched.

---

## 2026-09-24 — Freshness is always judged on incremental (`--since`) runs

**Finding:** A new end-to-end test showed that `check_freshness` treated any pull whose newest
`received_dttm` was older than 48h as a "historical window" and PASSed it as not applicable. On a
`--since` run, that is exactly the stalled-source case the check exists to catch.

**Options:** (1) infer historical vs current from the data (old behaviour); (2) pass the run mode
into the check.

**Choice:** Option 2. `run_validation(..., incremental=True)` for `--since` runs, so freshness is
always judged against `data_loaded_at`. Backfills and `--month` runs keep the existing
"not applicable to a historical window" behaviour.

**Why:** the run mode is known for certain; guessing it from the data let the failure it guards
against pass silently.
