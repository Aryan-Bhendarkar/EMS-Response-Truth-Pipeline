# Assumptions

> Per CLAUDE.md rule 5: every exclusion, normalisation or mapping is a named rule, counted, and
> listed here as an assumption with an owner — never silently guessed or fixed in code. All
> figures below are from `outputs/validation_report.json`, generated against the real 12-month
> backfill (`run_ts=20260923T163957Z`, 2025-07..2026-06, 364,873 rows) — not copied from
> `PROJECT_BRIEF.md`.

## 1. `original_priority` code mapping — CONFIRMED PARTIAL, mostly unconfirmed

**Observed values and counts** (12-month backfill):

| Value | Count | % of rows | Status |
|---|---|---|---|
| `3` | 220,137 | 60.3% | **Confirmed**: dataset metadata (`data.sf.gov/api/views/nuek-vuh3.json`) states `original_priority` is "Initial call priority (**Code 2**: Non-Emergency or **Code 3**: Emergency)" — so `3` = Code 3 / Emergency. |
| `2` | 67,033 | 18.4% | **Confirmed** (same source): `2` = Code 2 / Non-Emergency. |
| `A` | 28,445 | 7.8% | Unconfirmed. |
| `E` | 15,557 | 4.3% | Unconfirmed. |
| `1` | 11,787 | 3.2% | Unconfirmed — not even mentioned in the "Code 2 / Code 3" column description, so its meaning is a genuine gap, not just an unmapped letter code. |
| `B` | 9,124 | 2.5% | Unconfirmed. |
| `C` | 7,993 | 2.2% | Unconfirmed. |
| `""` (blank) | 4,094 | 1.1% | Missing at triage. |
| `I` | 654 | 0.18% | Unconfirmed. |
| `T` | 49 | 0.01% | Unconfirmed. |

**Assumption:** the letter codes (`A, B, C, E, I, T`) are a dispatch-triage determinant scale
distinct from the numeric Code 2/3 scale, most likely ordered by severity in some way (common in
CAD systems, e.g. Medical Priority Dispatch System-style determinant codes) — but SF's specific
set (`A,B,C,E,I,T`, no `D`) does not match the standard public MPDS Alpha–Echo scale exactly, so
**no specific severity ordering or meaning is assumed for any letter code**. `confirmed_by_owner:
false` for every letter code and for `1`.

**Owner:** SF EMS Agency / DEM (Division of Emergency Communications) dispatch protocol team —
they define the CAD triage scheme. Not yet contacted (outside this project's scope to reach a real
person); flagged here so a real engagement would know who to ask.

**Where the mapping lives now:** `config/priority_map.yaml`, loaded into DuckDB as
`dim_priority_map`, with `confirmed_by_owner: true` only for codes `2` and `3`.

**Correction to the brief:** `PROJECT_BRIEF.md` §4 (Q2) states "35 blanks" for `original_priority`
in its June–July 2026 sample (~58k rows, so a ~0.06% blank rate). Our 12-month backfill shows
4,094 blanks out of 364,873 rows — a **1.1% blank rate, about 19x higher**. Worth flagging: either
blank rates vary a lot month to month (plausible, needs a monthly breakdown — Phase 4), or the
two pulls aren't perfectly comparable.

**Update 2026-09-24 — partly resolved.** Monthly breakdown (query on `raw_calls` in the
warehouse, `COUNT(*) FILTER (WHERE original_priority IS NULL OR original_priority = '')` grouped
by month of `received_dttm`; the 12 months sum to the same 4,094):

| Month | Blanks | Rows | Blank rate |
|---|---|---|---|
| 2025-07 | 603 | 29,681 | 2.03% |
| 2025-08 | 363 | 30,842 | 1.18% |
| 2025-09 | 558 | 30,518 | 1.83% |
| 2025-10 | 463 | 31,845 | 1.45% |
| 2025-11 | 353 | 29,540 | 1.19% |
| 2025-12 | 121 | 33,174 | 0.36% |
| 2026-01 | 366 | 31,957 | 1.15% |
| 2026-02 | 339 | 28,648 | 1.18% |
| 2026-03 | 332 | 31,198 | 1.06% |
| 2026-04 | 263 | 28,642 | 0.92% |
| 2026-05 | 220 | 30,091 | 0.73% |
| 2026-06 | 113 | 28,737 | 0.39% |

So the blank rate does vary a lot by month (0.36%-2.03%), which explains most of the difference.
It does not fully explain the brief's figure: June 2026 alone has 113 blanks (0.39%), still well
above the brief's ~0.06%. The brief's sample can't be re-run exactly, so the rest of the
difference stays **open**. Impact on the KPI is small: a blank is never in any M1 candidate's
priority set (`{3,E}` or `3`), so blank-priority calls are simply outside those definitions.

## 2. `on_scene_dttm` nulls (21.7% of rows) — real breakdown, not a guess

Brief §4 (Q4) says these nulls should be split into "cancelled / unable to locate / genuinely
missing." Queried directly against the real backfill instead of assuming that split:

| `call_final_disposition` (rows with null `on_scene_dttm`) | Count |
|---|---|
| Other | 24,362 |
| Fire | 24,217 |
| Code 2 Transport | 18,312 |
| Cancelled | 6,153 |
| Unable to Locate | 3,290 |
| Code 3 Transport | 2,042 |
| Medical Examiner | 876 |
| Duplicate | 35 |
| Multi-casualty Incident | 12 |

**Finding, not assumption:** "Cancelled" and "Unable to Locate" — the two categories the brief
named — only account for 9,443 of the 79,299 nulls (11.9%). The two largest buckets are "Other"
and "Fire," and a surprising 20,354 rows are dispositioned as an actual **transport** (Code 2 or
Code 3) despite having no recorded `on_scene_dttm` — logically a unit can't transport a patient
without having been on scene, so this is either a secondary/backup unit attached to the call
record without personally arriving, or a genuine data-entry gap. **Not resolved here** — flagged
for Phase 4 modeling (`fct_unit_event`) rather than silently assumed either way.

Cross-checked against `call_type_group`: the null rate is broadly similar across every group
(22.0% for Potentially Life-Threatening, 24.5% Alarm, 17.6% Non Life-threatening, 25.9% Fire) —
this is not an artifact of non-medical dispatches being mixed into the null bucket; it's a broad
pattern across call types.

## 3. `nuek-vuh3` covers all SFFD dispatches, not only EMS — how each metric is scoped

**Finding:** `call_type_group` includes `Fire` (14,430 rows, 4.0%) and `Alarm` (91,937 rows,
25.2%) alongside `Potentially Life-Threatening` (179,749, 49.3%) and `Non Life-threatening`
(70,412, 19.3%). The dataset's own name — "Fire Department **and** EMS** Dispatched Calls" —
confirms this: it is not EMS-only.

**Phase 1 plan (superseded):** scope M1 to `call_type_group = 'Potentially Life-Threatening'`.

**What was actually built (Phase 4):** the scope rule is stated per candidate in
`config/kpi_definitions.yaml`, but only **one** of the five M1 candidates
(`dispatch_ctg_any_responder`) filters on `call_type_group`. The other four filter on a
**priority code** instead (`original_priority ∈ {3,E}` or `final_priority = 3`), because the
official measure is described as covering "Code 3" incidents (`docs/source_map.md`). Those four
do **not** exclude `Fire`/`Alarm` calls explicitly. Measured on the warehouse (`fct_call`
grouped by `call_type_group`, same filters as `pipeline/metrics.py`): in the best-fitting
definition's 12-month denominator (39,729 calls), 593 are `Alarm` and 354 are `Fire` — 947 calls,
2.4%. Small, but not zero; whether the official measure includes them is part of the open
methodology question (`docs/kpi_definitions.md`).

M2 is **not** scoped by call type at all: it covers every SFFD call with a received and dispatch
time (182,495 calls, of which 34,760 `Alarm` and 6,569 `Fire`). Whether to scope M2 to medical
calls is an open question for the owner (`docs/kpi_definitions.md`).

## 4. `unit_type` includes non-ambulance responders — open question for Phase 4

**Finding:** `unit_type` values in the real backfill: `ENGINE` (113,189), `MEDIC` (100,258),
`TRUCK` (38,311), `PRIVATE` (31,970), `CHIEF` (28,244), `CP` (22,147), `RESCUE CAPTAIN` (11,224),
`BLS` (9,766), `SUPPORT` (4,995), `RESCUE SQUAD` (4,584), `INVESTIGATION` (177), `AIRPORT` (8).

The brief's KPI logic (§5, `fct_call.first_ambulance_on_scene`) assumes "first ambulance" means
first `MEDIC`/`PRIVATE` unit. But SF EMS Agency's own FY25 Annual Performance Report (quoted in
`docs/source_map.md`) says *"first responders arrive at the scene and provide basic and/or
advanced life support"* — suggesting `ENGINE`/`TRUCK` companies (which often arrive before a
dedicated ambulance and can carry BLS/ALS-certified crew, per the `als_unit` flag) may be the
units the official 10-minute clock actually measures, not just `MEDIC`/`PRIVATE`. **Not decided
here.** Phase 4's reconciliation exercise will test both definitions (ambulance-only vs.
any-first-responder) against the official scorecard, the same way it tests the clock-start
question — see `docs/decision_log.md` (2026-09-23, "which clock" entry).

**Update after Phase 4 — tested, still open.** Both were tested. MEDIC-only
(`dispatch_original_medic`, mean absolute gap 3.51 points) and any-first-responder
(`dispatch_ctg_any_responder`, 3.58 points) fit the official number almost equally well, so the
data cannot settle it (`docs/judgement_call.md`). Listed as a decision for the owner in
`docs/decision_memo.md`.

## 5. M1 denominator excludes calls with no recorded on-scene arrival

**Rule:** `pipeline/metrics.py`'s M1 denominator is *eligible calls where the relevant unit
scope actually has an on-scene timestamp* — calls that were cancelled, went "Unable to
Locate," or otherwise never got a recorded arrival are **excluded from the ratio**, not
counted as automatic misses. Each month's `excluded_no_arrival` count is written to
`outputs/metrics.json` / `outputs/kpi_monthly.csv` alongside the ratio — visible, not hidden.

**Why:** you cannot measure "time to arrival" for a call nothing ever arrived at. Counting
these as automatic failures would conflate two different problems (slow response vs. no
response) into one number, and would make every candidate M1 definition's reconstructed
value implausibly low relative to the published ~85-88% figures, since ~20% of unit-responses
have no `on_scene_dttm` (`docs/assumptions.md` §2).

**Owner:** this is this project's own modeling choice (not an EMS Agency-confirmed rule) —
flagged as an assumption a real engagement would confirm with the measure's actual owner.

## 6. Hospital hand-over standard — see `docs/decision_log.md`

Already logged as a decision (2026-09-23): the raw data supports the 30-minute turnaround
standard (`hospital_dttm → available_dttm`), not the 20-minute offload standard, which requires a
hospital-EHR timestamp this dataset doesn't have. Not repeated here in full.

Two further assumptions on M4, both stated in `outputs/evidence_table.md`:
- The `hospital_dttm → available_dttm` interval includes cleaning and restocking the ambulance,
  so it **overstates** the hospital's own share of the 30-minute turnaround.
- Policy 4000.1 is effective **2026-10-01**, after the analysis window (2025-07..2026-06). It is
  used as the forward-looking benchmark; the standard in force during the window was not located.

**Owner:** SF EMS Agency (author of Policy 4000.1).
