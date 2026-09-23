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

**Correction to the brief:** `PROJECT_BRIEF.md` §4 (Q2) states "35 blanks" for `original_priority`
in its June–July 2026 sample (~58k rows, so a ~0.06% blank rate). Our 12-month backfill shows
4,094 blanks out of 364,873 rows — a **1.1% blank rate, about 19x higher**. Worth flagging: either
blank rates vary a lot month to month (plausible, needs a monthly breakdown — Phase 4), or the
two pulls aren't perfectly comparable. Not resolved here; carried into Phase 4 as an open item.

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

## 3. `nuek-vuh3` covers all SFFD dispatches, not only EMS — scope for Phase 4

**Finding:** `call_type_group` includes `Fire` (14,430 rows, 4.0%) and `Alarm` (91,937 rows,
25.2%) alongside `Potentially Life-Threatening` (179,749, 49.3%) and `Non Life-threatening`
(70,412, 19.3%). The dataset's own name — "Fire Department **and** EMS** Dispatched Calls" —
confirms this: it is not EMS-only. **Assumption for Phase 4:** the ambulance-response KPI (M1)
will be scoped to `call_type_group = 'Potentially Life-Threatening'` at minimum; `Fire` and
`Alarm` rows are out of scope for an ambulance-response measure. This will be stated explicitly
in `config/kpi_definitions.yaml`, not silently filtered in SQL with no record of the rule.

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

## 5. Hospital hand-over standard — see `docs/decision_log.md`

Already logged as a decision (2026-09-23): the raw data supports the 30-minute turnaround
standard (`hospital_dttm → available_dttm`), not the 20-minute offload standard, which requires a
hospital-EHR timestamp this dataset doesn't have. Not repeated here in full.
