# PROJECT BRIEF — SF 911 Ambulance Response: From Dispatch Data to a Trustworthy KPI

> FDE Data Foundations Assignment (Classes 4–8) · Track C (own problem)
> Author: Aryan · Brief prepared 23 Sep 2026 · All numbers below were verified against live DataSF data on this date.
> **Purpose of this file:** single source of truth for building the project with Claude Code. Put it in the repo root as `PROJECT_BRIEF.md`.

> **Note (added 2026-09-24):** This brief is the original hypothesis, kept exactly as written. Some of its figures were later superseded by evidence from the pipeline: the 87.4% prototype reconstruction (see `docs/judgement_call.md`), the 20-minute hand-over standard (the measurable standard is the 30-minute turnaround in Policy 4000.1), the ~7 ambulance shifts/day (a single-month July figure; the 12-month figure is ~5), and the 35 blank priority codes (see `docs/assumptions.md` §1). These changes are tracked in `docs/decision_log.md` (and `docs/assumptions.md` for data findings). For current numbers use `outputs/evidence_table.md`.

---

## 1. Problem statement (the client story)

**Client:** San Francisco Fire Department (SFFD) EMS Division + SF EMS Agency (EMSA, the regulator).

**Escalation:** *"City policy says ambulances must reach life-threatening emergencies within 10 minutes at least 90% of the time. Our published scorecard says we're close (88.4% in June 2026). Callers, the press and hospitals say otherwise. Before we buy more ambulances or add more private ambulance contracts, tell us where response time is actually being lost, and whether the number we publish can be trusted."*

**Why this is an FDE problem, not a data-analysis problem:**
- The KPI definition is not written down in the data. Depending on which timestamp starts the clock, which priority field is used and which units count, **the same month ranges from 56% to 87%** (verified, see §4).
- The source records one row per **unit** sent to a call, but the KPI is measured per **call**.
- Rows **keep changing after they first appear**: live calls are missing later timestamps until they close. A pipeline that just appends new rows will double-count calls or keep stale versions.
- Several parties are involved: SFFD ambulances (`MEDIC`), **private ambulance contractors** (`PRIVATE`), hospitals (patient hand-over time) and the regulator (EMSA). Who "owns" a missed target is disputed.

**Business question:** Where in the call lifecycle (call received → call entered → unit dispatched → unit en route → on scene → transport → at hospital → available again) does ambulance response time get lost, and does the published KPI reflect what patients experience?

**Decision the output supports:** whether SFFD should invest in (a) dispatch/call-processing speed, (b) more ambulance units/contracts, or (c) pushing hospitals to hand patients over faster, and which KPI definition should be published.

---

## 2. Stakeholders / users

| Stakeholder | What they care about | Their likely definition of "late" |
|---|---|---|
| SFFD EMS Chief (primary user) | Meeting the 90%/10-min target; where to add resources | Clock starts at **dispatch**, SFFD ambulances only |
| SF EMS Agency (regulator) | Compliance across all providers | Includes **private** ambulances answering 911 calls |
| Dispatch / DEM 911 centre | Call-processing time | Received → dispatch time, a separate KPI |
| Hospitals | Hand-over (wall) time | Not measured in their own systems in this data |
| Public / press | Time from phone call to help arriving | Clock starts when the **911 call is received** |

No single documented owner for the KPI definition → this is the central **FDE judgement call**.

---

## 3. Sources (verified live)

| # | Source | Owner | Access / retrieval mode | Grain | Freshness | Role |
|---|---|---|---|---|---|---|
| S1 | **Fire Dept & EMS Dispatched Calls for Service** (`nuek-vuh3`) | SFFD / DEM computer-aided dispatch (CAD) system | **API**: Socrata SODA `https://data.sf.gov/resource/nuek-vuh3.json`, paginated `$limit/$offset`, SoQL filters | **1 row per unit per call** (`rowid = call_number-unit_id`) | Reloaded daily; `data_as_of`, `data_loaded_at` columns | Core lifecycle timestamps (authoritative) |
| S2 | Same dataset, **bulk CSV export** (`/api/views/nuek-vuh3/rows.csv?accessType=DOWNLOAD`) | same | **File**: historical backfill (7.44M rows, 2000 → today) | same | snapshot | One-time backfill of the chosen history window |
| S3 | **City Performance Scorecard Measures** (`kc49-udxn`), measure `973` | Controller's Office | **API**: SODA | 1 row per measure per month | Monthly, lags about 3 months (latest actual = Jun 2026) | **Official published KPI** → reconciliation target |
| S4 | **Fire Incidents** (`wr8u-xric`) | SFFD incident reporting (written after the call) | **API** | 1 row per incident | Lags about 3–4 weeks | Optional: cross-check that the call happened, and its outcome |
| S5 | Local **DuckDB / SQLite warehouse** built by the pipeline | You | **SQL** (modelling + metrics are written as SQL) | modelled tables | per run | Third retrieval/modelling mode |
| (opt) | Open-Meteo historical weather API | Open-Meteo | API | hourly | daily | Context signal only (association, not cause) |

Retrieval modes covered: **API (S1, S3) + File (S2) + SQL (S5)** → exceeds the "at least two" requirement.

**Important gaps (write these down, don't hide them):**
- **The hospital's name is not in S1.** Hand-over (wall) time can be measured per unit but **cannot be attributed to a specific hospital**.
- There is no direct "patient contact" timestamp. `on_scene_dttm` means the unit arrived at the address, not that it reached the patient.
- Private ambulance companies are anonymised as `unit_type = PRIVATE`, so you can't see which contractor.
- The scorecard publishes **no methodology** (field is null), so the official definition must be reverse-engineered and confirmed with the owner.

---

## 4. Verified data facts (June–July 2026 pull: 58,256 unit rows, 29,711 calls)

### Data quality issues (all real, none planted)
| # | Issue | Evidence | FDE handling |
|---|---|---|---|
| Q1 | **Grain**: unit-level, not call-level | 58,256 rows vs 29,711 distinct calls (~2 units per call) | Model `call` and `unit_response` separately; KPI at call grain = first ambulance on scene |
| Q2 | **Priority codes mix two systems** | `original_priority` ∈ {1,2,3} **and** {A,B,C,E,I,T} + 35 blanks; `final_priority` only {2,3} | Mapping needs owner confirmation → validation = WARN, assumption recorded |
| Q3 | **Priority changes during the call** | ~25% of units: original ≠ final (e.g., A→3: 2,748; 3→2: 1,300) | KPI must pick one field; show how the result changes (definition table) |
| Q4 | **Missing on-scene time** | `on_scene_dttm` null 21.3%; `response_dttm` null 2.4% | Separate cancelled / "Unable to Locate" / genuinely missing; never silently drop |
| Q5 | **Timestamps out of order** | dispatch>response: 4 · on_scene>transport: 1 · transport>hospital: 81 · hospital>available: 67 (negative wall time down to −90 min) | Rule-based FAIL flag per row; exclude from interval metrics, count reported |
| Q6 | **Extreme outliers** | received→dispatch max 436 min; wall time max 776 min | Keep, flag > p99.9 for review; median/p90 over mean |
| Q7 | **Records change after first load** | Latest calls lack on_scene/transport/available; `data_loaded_at` changes | Upsert by `rowid`; re-pull a lookback window (e.g., 3 days) each run |
| Q8 | **Third-party units** | `PRIVATE` = 2,772 rows in July alone | Ownership question: does the KPI include them? Show both |
| Q9 | Missing call category | `call_type_group` null for 1,159 rows | WARN; excluded from priority-group splits, counted |
| Q10 | **Official KPI vs raw data don't match** | Scorecard Jun 2026 = **88.4%**; best raw reconstruction = 87.4% | Core reconciliation exercise (below) |

### Headline finding: the KPI definition decides the answer (June 2026, verified)
| Clock start | Priority rule | Units | % on scene ≤ 10 min |
|---|---|---|---|
| **Dispatch** | original ∈ {3,E} | MEDIC only | **87.4%** ← closest to official 88.4% |
| Dispatch | final = 3 | MEDIC + PRIVATE | 85.3% |
| Call entered | original ∈ {3,E} | MEDIC only | 83.1% |
| **911 call received** | final = 3 | MEDIC + PRIVATE | **66.4%** ← what the caller experiences |
| 911 call received | "Potentially Life-Threatening" group | MEDIC + PRIVATE | 56.2% |

→ **The published number most likely starts the clock at dispatch. From the caller's point of view, performance is about 20 points worse.** That is the demo's judgement call.

### Where the time goes (ambulance units, June–July 2026)
| Step | Median | p90 |
|---|---|---|
| Queue: received → dispatched | 2.4 min | 5.9 min |
| Travel: en route → on scene | 7.1 min | 16.9 min |
| **Hospital hand-over / wall: at hospital → available** | **42.2 min** | **65.2 min** |

9% of hospital hand-overs take over 60 minutes. Each of those is an ambulance that can't take the next call. Official policy is 20 min hand-over, 90% of the time. (The wall interval also includes cleaning/restocking the ambulance, so state this assumption.)

---

## 5. Workflow + data model (Class 7)

**Entities:** `call`, `unit`, `unit_response` (unit × call), `station_area/battalion`, `neighborhood`, `month` (KPI period).

**Events/states (per unit_response):** `RECEIVED → ENTERED → DISPATCHED → EN_ROUTE → ON_SCENE → [TRANSPORTING → AT_HOSPITAL] → AVAILABLE`, plus terminal outcomes from `call_final_disposition` (Code 2/3 Transport, Cancelled, Unable to Locate, Medical Examiner…).

**Interactions / interventions / outcomes (maps to the course template):**
- *Interaction:* 911 call received + call-taker triage (original priority)
- *Intervention:* priority up/downgrade (original → final), number/type of units sent, private ambulance used, ALS unit added
- *Outcome:* first ambulance on scene ≤ 10 min (KPI), transport disposition, unit back in service

**Tables (SQL, in DuckDB):**
| Table | Primary key | Grain | Key columns |
|---|---|---|---|
| `raw_calls` | `rowid` + `load_ts` | raw API row, append-only | all source fields, untouched |
| `stg_unit_response` | `rowid` | latest version of each unit row | typed timestamps, normalised codes, dq_flags |
| `fct_unit_event` | `rowid, event_type` | one row per lifecycle event | `event_ts`, `actor=unit_id` |
| `fct_call` | `call_number` | one row per call | first_ambulance_on_scene, priorities, n_units, private_used, kpi flags per definition |
| `dim_priority_map` | `code` | code lookup | assumed meaning + `confirmed_by_owner` = false |
| `kpi_monthly` | `month, definition` | one row per month per KPI definition | numerator, denominator, pct, official_value, gap |

Diagrams to include: **source map** (sources → facts → owners) and **ER/lifecycle diagram** (Mermaid in `docs/`).

---

## 6. Metrics (3–5, all tied to the project KPI)

| # | Metric | Formula | Grain | Type | Why it matters |
|---|---|---|---|---|---|
| M1 | **Ambulance 10-min compliance** (project KPI) | calls with first ambulance on scene ≤ 10 min / eligible life-threatening calls | call, monthly | Outcome | The city's published target (90%) |
| M2 | **Call-processing time p90** | received → dispatch | call | Driver (dispatch-controllable) | Time lost before any unit moves; invisible in the published KPI |
| M3 | **Travel time p90** | en route → on scene | unit_response | Driver (coverage/deployment) | Tells you whether more units or better positioning would help |
| M4 | **Hospital hand-over time > 20 min rate** | units with wall > 20 min / transports | unit_response | Driver (hospitals) | Ambulances stuck at hospitals shrink available capacity |
| M5 | **KPI definition gap** | M1 (clock from received) − M1 (clock from dispatch); plus raw vs official | month | Trust/governance | Shows how much the published number flatters reality |

---

## 7. Pipeline design (Class 8)

```
python run_pipeline.py --month 2026-07            # or --since 3d for incremental
  EXTRACT   S1 via SODA (paginate, retry 429/5xx with backoff, app token from .env),
            S3 scorecard; save every raw page → data/raw/<source>/run_ts=.../page_NNN.json
            completeness check: API count(*) for the same filter == rows received
  VALIDATE  schema/required columns · rowid uniqueness · timestamp order · priority code
            domain · null rates vs thresholds · freshness (max data_loaded_at age) →
            PASS/WARN/FAIL per check → validation_report.json; any FAIL = stop, publish nothing
  TRANSFORM load to DuckDB (upsert by rowid) → SQL models (stg → fct → kpi)
  METRICS   kpi_monthly for all definitions + official comparison → metrics.json + evidence table
  SAVE      atomic write, partitioned by logical month (idempotent rerun)
  LOG       logs/pipeline_<run>.log with stage, source, rows, attempt, decision
```
Failure demos (`--chaos`): drop `on_scene_dttm` column (schema break → FAIL), inject duplicate rowid (uniqueness WARN + dedupe), simulate stale load (freshness FAIL), cut pagination short (completeness FAIL), and **late-arriving update** (rerun for the same month shows no double count).
Tests: `pytest` for validation rules and definition logic. Optional: GitHub Actions nightly run.

---

## 8. Rubric verification: what the final repo will show

| Rubric (20% each) | Required evidence | Our concrete output | Confidence |
|---|---|---|---|
| **Source reasoning** | question → info → source; ownership, grain, gaps | `docs/source_map.md` + diagram; §3 table; gaps (no hospital name, no methodology, anonymised private units) | High |
| **Retrieval** | ≥2 modes, completeness proof, raw preserved | SODA API (paginated + retries) + bulk CSV + SQL; per-run check that API count(*) matches rows received; raw pages saved | High |
| **Validation** | profiling, business rules, assumptions not silently fixed | `notebooks/02_profile_validate.ipynb` + `validation_report.json` with Q1–Q10 as PASS/WARN/FAIL; `dim_priority_map.confirmed_by_owner=false` | High |
| **Workflow + metrics** | entities, events/states, interactions/interventions/outcomes, 3–5 metrics | lifecycle event table, `fct_call`, M1–M5, definition-sensitivity table, reconciliation to official 88.4% | High |
| **Pipeline dependability** | ingest→validate→transform→metrics, logging, rerun, failures | one command, idempotent upsert, chaos flags, logs, pytest, Gate-2 readiness file | High |
| README | problem, users, KPI, sources, setup/run, decision | `README.md` | High |
| Evidence table + K/U/A/L | 3–5 metrics + Known/Unknown/Assumption/Limitation | `outputs/evidence_table.md` (+ optional static HTML dashboard) | High |
| Demo (3–5 min) | one judgement call | **"Which clock?": published 88.4% vs caller experience ~66%, and why I publish both with a named owner** | High |

### Known / Unknown / Assumption / Limitation (starter)
- **Known:** most time is lost at hospital hand-over (median 42 min) and in travel p90 (17 min), not call processing (median 2.4 min); the published KPI can be approximately reproduced (87.4% vs 88.4%) using a dispatch clock start.
- **Unknown:** the exact official methodology; the meaning of letter priority codes (A/B/C/E/I/T); which hospital each transport went to; which private contractor.
- **Assumption:** the KPI counts the first ambulance (MEDIC/PRIVATE) per call; `available_dttm − hospital_dttm` ≈ hand-over + cleanup time; letter codes E/A ≈ emergency (to be confirmed).
- **Limitation:** association, not causation; the ~1-point gap to the official figure is unexplained; the latest few days are incomplete until records close.

---

## 9. Suggested repo structure

```
sf-ems-response-pipeline/
├── README.md  PROJECT_BRIEF.md  GATE2_DATA_READINESS.md
├── docs/ source_map.md  data_model.md (Mermaid)  kpi_definitions.md  judgement_call.md
├── config/ .env.example  settings.yaml (thresholds, windows, definitions)
├── pipeline/ extract.py  validate.py  load.py  transform/ (*.sql)  metrics.py  save.py  logging_utils.py
├── notebooks/ 01_source_discovery  02_profile_validate  03_workflow_model  04_metrics_reconciliation
├── tests/ test_validate.py  test_definitions.py
├── data/ raw/ (gitignored except 1 sample month)  processed/
├── outputs/ evidence_table.md  metrics.json  validation_report.json
└── run_pipeline.py
```

---

## 10. Final alternatives check (why this project wins)

| Candidate | Verdict |
|---|---|
| **SF 911 ambulance response (chosen)** | Hourly-updated API, 9 lifecycle timestamps, unit-vs-call grain, mixed priority codes, private contractors, **and an official published KPI to reconcile against**. Rare to find all of these together. |
| NYC EMS Incident Dispatch (`76xm-jjuj`) | Good domain, but incident-level with pre-computed response seconds, updated only a few times a year → weak retrieval/pipeline story |
| NYC 311 Service Requests (`erm2-nwe9`) | Daily, huge, messy, a strong runner-up; but "resolution" is loosely defined and there's no official SLA to reconcile → weaker KPI story |
| NYC TLC trips (Track B) | Clean-ish, no interventions, no ownership conflict |
| BTS airline on-time | Good delay-cause model, monthly only; much of the work is time zones |
| Olist e-commerce (Kaggle) | Static, overused, no pipeline story |
| FlashEats (Track A) | Class code already covers ~80% → low differentiation |

## 11. Risks & mitigations
- **API throttling without an app token** → register a free Socrata app token and keep it in `.env`.
- **Data size** → scope to 12 months (~350k unit rows), pulled month by month; DuckDB handles it easily.
- **Domain terms** → `docs/kpi_definitions.md` lists every assumption; no guessing hidden in code.
- **Time** → build order: extract + raw → validation → model/SQL → metrics → pipeline hardening → docs/demo.

## 12. Final deliverables & expected outcomes (definition of done)

**Product name:** *EMS Response Truth Pipeline*. One command turns raw SF dispatch data into a validated monthly KPI pack that shows the official number next to what the data actually supports.

### What gets built
| # | Deliverable | Concrete form | Done when |
|---|---|---|---|
| D1 | Public GitHub repo | structure from §9 | a fresh clone + `pip install` + `python run_pipeline.py --month 2026-07` works on another machine |
| D2 | Pipeline | `run_pipeline.py` + `pipeline/` + SQL models in DuckDB | end-to-end run < 5 min for 1 month; rerun gives identical output; 5 failure demos behave as designed |
| D3 | Monthly KPI pack | `outputs/<month>/metrics.json`, `evidence_table.md`, `validation_report.json`, `kpi_monthly.csv` | M1–M5 computed for 12 months, with the official scorecard figure alongside |
| D4 | One-page dashboard | static `outputs/<month>/dashboard.html` generated by the pipeline | shows KPI under each definition vs 90% target and official value; time lost per step (queue / travel / hospital); hand-over trend; validation gate status |
| D5 | Docs | `source_map.md`, `data_model.md` (Mermaid), `kpi_definitions.md`, `judgement_call.md`, `GATE2_DATA_READINESS.md`, K/U/A/L | every assumption named, each unconfirmed rule has a named owner |
| D6 | Notebooks | 01 discovery · 02 profile/validate · 03 workflow model · 04 reconciliation | readable story, each ending in a decision |
| D7 | Tests | `pytest` for validation rules + KPI definitions | green locally (optional GitHub Actions) |
| D7b | 1-page decision memo | `docs/decision_memo.md` | findings → recommendation → decisions the owner must make → what the dispatch system should start recording |
| D8 | Demo video | 3–5 min screen recording | walks the repo → runs the pipeline → shows one failure → explains the "which clock?" call |

### Expected findings (based on the June–July 2026 prototype; final values come from the pipeline)
1. **Official KPI reproducible:** ~87% vs published 88.4%, using a dispatch clock start and city ambulances only; the remaining gap is documented, not hidden.
2. **What the caller experiences is ~20 pts worse:** ~66% within 10 min when the clock starts at the 911 call.
3. **The bottleneck is hospital hand-over, not dispatch:** median ~42 min at the hospital vs ~2.4 min to dispatch. This points investment at hospital hand-over rules, not faster dispatch software.
3b. **Capacity lost at hospitals:** July 2026 had about **2,700 ambulance-hours** beyond the 20-min hand-over standard. That's about **7 twelve-hour ambulance shifts per day**. It's an upper bound, because the interval includes cleaning and restocking.
4. **About 1 in 5 unit responses has no on-scene time**, split into cancelled / unable to locate / truly missing.
5. **Recommendations to the client:**
   - Publish two KPIs: the official one and a caller-clock one.
   - Assign an owner for the priority-code mapping.
   - Start recording the hospital's name and the actual patient hand-over timestamp.
   - Don't build any predictive/AI model until the definitions are fixed.

### Out of scope (deliberately)
No ML model, no real-time app, no Airflow/Spark, no causal claims.

## 13. Resume line
*Built an idempotent, validated pipeline over 1M+ San Francisco 911 dispatch records (Socrata API + bulk files → DuckDB/SQL). Reverse-engineered the city's published ambulance-response KPI (88.4%) and showed caller-experienced compliance is ~66%. Found that hospital hand-over time (median 42 min) outweighs dispatch delay in lost ambulance capacity.*
