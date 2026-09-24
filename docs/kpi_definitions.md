# KPI Definitions

> Human-readable definitions of M1-M5. The machine-readable source is
> `config/kpi_definitions.yaml`; the SQL is in `pipeline/metrics.py` and `pipeline/transform/*.sql`.
> If this page and the config ever disagree, the config is what runs, and this page is wrong.
> All figures are 12-month averages from `outputs/metrics.json` (2025-07..2026-06).
>
> **No definition here is confirmed by its owner.** Every `confirmed_by_owner` flag is `false`
> until someone at SF EMS Agency / SFFD / the Controller's Office signs off.

## Conventions that apply to every metric

- **Month** = the month of the call's `received_dttm`.
- **Durations** = `date_diff('second', start, end) / 60.0`, in minutes. Not `date_diff('minute')`,
  which truncates (`docs/decision_log.md`).
- **Percentiles** = exact `quantile_cont`, not `approx_quantile`, so reruns match
  (`docs/decision_log.md`).
- **Priority codes:** `config/priority_map.yaml` → DuckDB table `dim_priority_map`. Only codes `2`
  (Non-Emergency) and `3` (Emergency) are `confirmed_by_owner: true`, from the dataset's own column
  description. `1`, `A`, `B`, `C`, `E`, `I`, `T` and blank are unconfirmed (`docs/assumptions.md` §1).
- **Data-quality flags:** rows with an impossible timestamp order are flagged (`dq_*` on
  `stg_unit_response`), never deleted. Each metric below says which flag it excludes.

---

## M1 — Ambulance 10-minute compliance (the project KPI)

| | |
|---|---|
| **Purpose** | Is SF meeting its target: ambulances on scene of Code 3 emergencies within 10 minutes, 90% of the time? |
| **Formula** | calls where (on-scene time − clock start) ≤ 10 min ÷ eligible calls with a recorded arrival |
| **Grain** | One row per call (`fct_call`) |
| **Clock start** | `fct_call.dispatch_dttm` or `fct_call.received_dttm`, depending on the candidate. Both are the earliest value across all units of the call. |
| **Clock end** | First on-scene time for the candidate's unit scope: `first_medic_on_scene_dttm` (MEDIC), `first_ambulance_on_scene_dttm` (MEDIC+PRIVATE) or `first_any_unit_on_scene_dttm` (any unit) |
| **Filters** | The candidate's priority rule (table below); clock start not null |
| **Exclusions** | (1) Calls with no arrival for the unit scope are left out of the ratio, not counted as misses — counted per month as `excluded_no_arrival` in `metrics.json` and `kpi_monthly.csv` (`docs/assumptions.md` §5). (2) Units flagged `dq_response_after_onscene` are left out of the "first on scene" calculation — counted per call as `fct_call.excluded_dq_rows`. |
| **Target** | 90% within 10 minutes (`target_minutes`, `target_pct` in config) |
| **Official comparator** | City Performance Scorecard measure 973 (`kc49-udxn`). Publishes no methodology. 12-month average 87.3%. |
| **Owner** | Measure published by the Controller's Office (City Performance); definition owned by SF EMS Agency / SFFD. Each candidate's `owner` field in config says whose framing it represents. |
| **confirmed_by_owner** | `false` for all five candidates |
| **Config** | `config/kpi_definitions.yaml` → `m1_candidate_definitions` |

### The five M1 candidates

The scorecard publishes no methodology, so five plausible definitions are computed every month
and compared with the official value. The best fit is picked by the data (lowest mean absolute
gap), not assumed. Full reasoning: `docs/judgement_call.md`.

| Candidate | Clock start | Priority rule | Unit scope | 12-mo avg | Mean abs. gap to official |
|---|---|---|---|---|---|
| **`dispatch_original_medic`** (best fit) | dispatch | `original_priority` ∈ {3, E} | MEDIC | 83.8% | 3.51 pts |
| `dispatch_ctg_any_responder` | dispatch | `call_type_group` = Potentially Life-Threatening | any unit | 83.75% | 3.58 pts |
| `dispatch_final_ambulance` | dispatch | `final_priority` = 3 | MEDIC+PRIVATE | 82.3% | 5.01 pts |
| `received_original_medic` | 911 call received | `original_priority` ∈ {3, E} | MEDIC | 65.7% | 21.61 pts |
| `received_final_ambulance` | 911 call received | `final_priority` = 3 | MEDIC+PRIVATE | 65.3% | 22.08 pts |

Notes:
- `E` is in the `{3, E}` set as a **hypothesis**. Its meaning is unconfirmed (`dim_priority_map`).
- Only `dispatch_ctg_any_responder` filters on `call_type_group`. The four priority-code
  candidates do not exclude `Fire`/`Alarm` calls explicitly; in the best fit's 12-month
  denominator that is 947 of 39,729 calls (2.4%) (`docs/assumptions.md` §3).

---

## M2 — Call-processing time (received → dispatch)

| | |
|---|---|
| **Purpose** | How long from the 911 call being received to the first unit being dispatched? Tests whether dispatch is the bottleneck. |
| **Formula** | p50 and p90 of `dispatch_dttm − received_dttm`, per month |
| **Grain** | One row per call (`fct_call`) |
| **Clock start / end** | `fct_call.received_dttm` → `fct_call.dispatch_dttm` (first dispatch of **any** unit) |
| **Filters** | Both timestamps present |
| **Exclusions** | None beyond missing timestamps. The per-month call count is `n` in `metrics.json`. |
| **Unit scope** | Any unit; **all SFFD calls, including fire and alarm calls** (see open questions) |
| **Result** | p50 2.2 min, p90 4.8 min |
| **Official comparator** | None — the scorecard has no call-processing measure (`docs/source_map.md`) |
| **Owner** | This project's definition; operational owner would be DEM (Division of Emergency Communications) |
| **confirmed_by_owner** | `false` (not in config; project-defined) |
| **Config** | Computed in `pipeline/metrics.py` → `compute_m2_call_processing`; no config parameters |

---

## M3 — Ambulance travel time (en route → on scene)

| | |
|---|---|
| **Purpose** | How long ambulances take to reach the scene once moving. Informs deployment and positioning. |
| **Formula** | p50 and p90 of `on_scene_dttm − response_dttm`, per month |
| **Grain** | One row per unit response (`stg_unit_response`) |
| **Clock start / end** | `response_dttm` (en route) → `on_scene_dttm` |
| **Filters** | Both timestamps present; `unit_type` ∈ {MEDIC, PRIVATE} |
| **Exclusions** | Rows flagged `dq_response_after_onscene` — counted by the validation check `timestamp_order_response_dttm_before_on_scene_dttm` in `validation_report.json` |
| **Unit scope** | Ambulances only. All units would give p50 4.4 / p90 15.3, which measures first-responder coverage instead (`docs/decision_log.md`). |
| **Result** | p50 7.4 min, p90 17.5 min |
| **Official comparator** | None |
| **Owner** | This project's definition; operational owner would be SFFD EMS Division |
| **confirmed_by_owner** | `false` (not in config; project-defined) |
| **Config** | `pipeline/metrics.py` → `compute_m3_travel_time`; unit scope is currently in the SQL |

---

## M4 — Hospital turnaround and ambulance-hours lost

| | |
|---|---|
| **Purpose** | How much ambulance capacity is tied up at hospitals beyond the standard |
| **Formula** | p50/p90 of `available_dttm − hospital_dttm`; share over 30 min; ambulance-hours lost = Σ max(interval − 30 min, 0) ÷ 60 |
| **Grain** | One row per unit response with a hospital arrival (`stg_unit_response`) |
| **Clock start / end** | `hospital_dttm` (arrived at ED) → `available_dttm` (back in service) |
| **Filters** | Both timestamps present |
| **Exclusions** | Rows flagged `dq_hospital_after_available` — counted by the validation check `timestamp_order_hospital_dttm_before_available_dttm` |
| **Unit scope** | Every unit with a hospital timestamp (no unit-type filter) |
| **Result** | p50 41.7 min, p90 65.3 min; 83.1% over 30 min; 21,896 ambulance-hours over 12 months (≈ 5.0 twelve-hour shifts per day) |
| **Standard** | SF EMS Agency Policy 4000.1: turnaround ≤ 30 min, 90% of the time. **Effective 2026-10-01, after the analysis window** — used as the forward-looking benchmark. The standard in force during the window was not located. |
| **Not measured** | The 20-min offload standard (APOT-1) needs a hospital-EHR timestamp this dataset doesn't have |
| **Caveat** | The interval includes cleaning and restocking, so it **overstates** the hospital's share |
| **Official comparator** | None published; the policy sets a standard, not a reported value |
| **Owner** | SF EMS Agency (policy); this project (the approximation from CAD timestamps) |
| **confirmed_by_owner** | `false` |
| **Config** | `config/kpi_definitions.yaml` → `m4_hospital_standard` |

---

## M5 — Definition gap (dispatch clock vs. received clock)

| | |
|---|---|
| **Purpose** | Show how much the published-style number (dispatch clock) hides compared with what the caller experiences (received clock) |
| **Formula** | M1(dispatch-clock candidate) − M1(received-clock candidate), in percentage points, per month. Also reports official − dispatch-clock value. |
| **Grain** | Month |
| **Pairs** | **Configured headline pair** (`m5_clock_gap_pair`): `dispatch_final_ambulance` − `received_final_ambulance` → `clock_gap_points`, 17.1 pts on average (monthly range 15.8-18.3). **Best-fit twin** (`m5_best_fit_twin`): `dispatch_original_medic` − `received_original_medic` → `best_fit_twin_gap_points`, 18.1 pts on average (monthly range 17.1-19.6). The twin changes only the clock, for the definition closest to the official number. |
| **Exclusions** | Inherited from M1 |
| **Official comparator** | None for the gap itself |
| **Owner** | This project's definition |
| **confirmed_by_owner** | `false`; which pair to headline is an open question |
| **Config** | `config/kpi_definitions.yaml` → `m5_clock_gap_pair`, `m5_best_fit_twin` |

---

## Open questions for the owner

These would change a KPI or the storyline, so they are not changed without sign-off (CLAUDE.md).

1. **M2 scope.** M2 covers every SFFD call, including fire and alarm calls (over the 12 months,
   34,760 `Alarm` and 6,569 `Fire` calls out of 182,495). Should it be limited to medical, or to
   Potentially Life-Threatening, calls?
2. **Dispatch clock start.** `fct_call.dispatch_dttm` is the first dispatch of **any** unit. For
   MEDIC-only candidates the clock may start when an engine was dispatched, before the ambulance.
   Add a "first ambulance dispatched" candidate?
3. **Which M5 pair to headline.** The headline 17.1 uses the `final_ambulance` pair; the
   like-for-like twin of the best-fit definition gives 18.1. The pair is configurable; the default
   is unchanged.
4. **MEDIC-only vs. any responder** for M1 — the data can't tell them apart (3.51 vs. 3.58 pts).
5. **Letter priority codes and `1`** — meaning unknown (`dim_priority_map`).
