# EMS Response Truth Pipeline

> SF 911 ambulance dispatch data → a validated, repeatable ambulance-response KPI.
> FDE Data Foundations Assignment (Classes 4–8), Track C. **Status: complete (Phases 0–6).**

## Problem

San Francisco's published scorecard says ambulances reach life-threatening emergencies within
10 minutes 88.4% of the time (June 2026; target 90%). Callers, the press and hospitals say
performance feels worse. This project builds a validated, repeatable pipeline from SF's raw
911 dispatch data to that KPI, to answer three questions with evidence instead of assertion:

1. Can the published number be reproduced, and under which definition?
2. What does the caller actually experience?
3. Where in the call lifecycle is time and ambulance capacity actually lost?

**Headline result** (full reasoning: `docs/judgement_call.md`, `outputs/evidence_table.md`):
the published number is reproducible within ~3.5 points using a *dispatch-clock* definition —
but measured from when the 911 call is actually received, compliance is **17-18 points
lower** (15.8-18.3 points every one of the 12 months analyzed). The dominant bottleneck isn't
dispatch or travel time — it's hospital turnaround (median 41.7 min against the 30-min standard
in SF EMS Agency Policy 4000.1, which takes effect 2026-10-01, after the analysis window). That
interval costs an estimated 21,896 ambulance-hours over the 12 months, about 5 twelve-hour
ambulance shifts a day. It's an upper bound, because the interval includes cleaning and restocking.

## Users / stakeholders

| Stakeholder | Cares about | Likely definition of "late" |
|---|---|---|
| SFFD EMS Chief | Meeting the 90%/10-min target; where to add resources | Dispatch clock, SFFD ambulances only |
| SF EMS Agency (regulator) | Compliance across all providers | Includes private ambulances |
| Dispatch / DEM 911 centre | Call-processing time | Received → dispatch, a separate measure |
| Hospitals | Hand-over (turnaround) time | Not measured in their own systems |
| Public / press | Time from phone call to help arriving | 911-call-received clock |

## Project KPI

**M1 — Ambulance 10-minute compliance**: share of eligible life-threatening calls with the
first ambulance on scene within 10 minutes, computed monthly. The definition (clock start,
priority rule, unit scope) is not published by the city — this project resolves it empirically
by testing 5 candidates against 12 real months of the official scorecard. Four supporting
metrics (call-processing time, ambulance travel time, hospital turnaround, and the KPI
definition gap) complete the picture. Full metric definitions: `docs/kpi_definitions.md`
(config: `config/kpi_definitions.yaml`); results: `outputs/evidence_table.md`.

## Sources

| Source | Access | Role |
|---|---|---|
| Fire Dept & EMS Dispatched Calls for Service (`nuek-vuh3`) | SODA API (JSON, paginated) + SODA CSV export | Core lifecycle timestamps |
| City Performance Scorecard Measures (`kc49-udxn`, measure 973) | SODA API | Official published KPI, reconciliation target |

`wr8u-xric` (Fire Incidents) and an Open-Meteo weather source were considered and cut — the
former is explicitly scoped to non-medical incidents (confirmed via its own metadata); the
latter had no concrete testable hypothesis. Both decisions, with evidence: `docs/decision_log.md`.
Full source detail, ownership, grain, freshness and gaps: `docs/source_map.md`. Table lineage
from raw pull to final metric (with a diagram): `docs/data_model.md`.

## Setup and run

```bash
# Inside WSL2 (Ubuntu). Keep the repo wherever you like, including a Windows-mounted
# drive (/mnt/c, /mnt/a, ...) — but create the venv on the native Linux filesystem.
# A venv on /mnt/* is 10-20x slower to install (WSL2's 9p/drvfs protocol is slow for
# the thousands of small file writes pip does).
python3 -m venv ~/.venvs/sf-ems-pipeline
source ~/.venvs/sf-ems-pipeline/bin/activate
pip install -r requirements.txt       # runtime only
pip install -r requirements-dev.txt   # + pytest, pandas, jupyter (tests and notebooks)
cp config/.env.example .env   # fill in SOCRATA_APP_TOKEN (optional; raises the API rate limit)

# Quickstart: one command, extract -> validate -> load -> transform -> metrics
# -> report -> save, for a single month or an incremental lookback window.
# Self-contained - no separate backfill needed first. The dashboard headlines the
# month you ran; a month with no published scorecard actual yet (e.g. 2026-07, or a
# --since window) shows "n/a" for the official comparison instead of failing.
# Note: every run upserts into the one local warehouse (data/processed/sf_ems.duckdb),
# so a later `python -m pipeline.metrics` includes any extra months you've loaded.
python run_pipeline.py --month 2026-06
python run_pipeline.py --since 3

# To reproduce the full 12-month reconciliation story (outputs/evidence_table.md,
# notebooks 02-04): pull and load the whole analysis window once. Takes ~5 min
# without an app token (anonymous Socrata rate limit); faster with one configured.
# Each extract prints a run_id (e.g. "run_id=20260923T163957Z") - copy it into
# the load command that follows.
python -m pipeline.extract --backfill
python -m pipeline.extract --scorecard
python -m pipeline.validate --run-ts <run_id from --backfill>   # writes outputs/validation_report.json
python -m pipeline.load --calls-run-ts <run_id from --backfill> --scorecard-run-ts <run_id from --scorecard>
python -m pipeline.metrics   # writes outputs/metrics.json, outputs/kpi_monthly.csv

# Failure-handling demos (see GATE2_DATA_READINESS.md for what each one proves).
# Chaos runs use a throwaway copy of the warehouse and write to outputs/_chaos/ -
# they can never change real data or a published KPI pack.
python run_pipeline.py --month 2026-05 --chaos missing_column       # FAIL, publishes nothing
python run_pipeline.py --month 2026-04 --chaos duplicate_rowid      # WARN, dedupes on load
python run_pipeline.py --since 3 --chaos stale_data                 # FAIL freshness
python run_pipeline.py --month 2026-03 --chaos truncated_pagination # FAIL manifest_completeness
python run_pipeline.py --month 2026-02 --chaos late_update          # passes; logs the upserted row + unchanged row count

# Tests (hermetic - no network access needed; also run in CI via .github/workflows/tests.yml)
python -m pytest tests/
```

A FAIL at the validate stage stops the run before anything is loaded or published — nothing in
`outputs/<scope>/` is written until the data has passed every structural check
(`CLAUDE.md` rule 8). Every stage's module (`pipeline/extract.py`, `validate.py`, `load.py`,
`metrics.py`) can also be run standalone; each has a module docstring explaining its contract.

## Outputs

- `outputs/evidence_table.md` — 3-5 headline metrics plus a Known/Unknown/Assumption/Limitation section
- `outputs/metrics.json`, `outputs/kpi_monthly.csv` — full 12-month reconciliation, all 5 KPI definitions
- `outputs/validation_report.json` — 15 named validation checks (7 PASS / 8 WARN / 0 FAIL), run against the real backfill
- `outputs/<month>/` — per-run outputs from `run_pipeline.py` (`dashboard.html`, `metrics.json`, `validation_report.json`, `kpi_monthly.csv`)
- `outputs/_chaos/<scope>/` — chaos-run outputs (gitignored, never published)
- `docs/decision_memo.md` — 1-page recommendation to the client
- `docs/judgement_call.md` — the "which clock?" judgement call, with the reconciliation evidence
- `docs/demo_script.md` — 3-5 minute demo walkthrough (outline); `docs/loom_script.md` — verbatim recording script

## What decision this supports

Whether SFFD should invest in (a) dispatch/call-processing speed, (b) more ambulance
units/contracts, or (c) faster hospital hand-over — and which KPI definition the city should
publish. Full recommendation: `docs/decision_memo.md`.

## Repo structure

```
├── README.md  PROJECT_BRIEF.md  GATE2_DATA_READINESS.md
├── docs/
│   ├── source_map.md          Phase 1: sources, owners, gaps, Mermaid diagram
│   ├── data_model.md          table lineage (raw -> stg -> fct -> metrics), Mermaid diagram
│   ├── decision_log.md        every evidence-based pivot away from the brief's hypotheses
│   ├── assumptions.md         every unconfirmed mapping/exclusion, with an owner
│   ├── kpi_definitions.md     M1-M5 definitions, owners, confirmation status, open questions
│   ├── review_findings.md     pre-submission review: every gap found and how it was fixed
│   ├── judgement_call.md      the "which clock?" call, with reconciliation evidence
│   ├── decision_memo.md       1-page client recommendation
│   └── demo_script.md         3-5 min demo walkthrough
├── config/
│   ├── .env.example  settings.yaml  validation_rules.yaml  kpi_definitions.yaml  priority_map.yaml
├── pipeline/
│   ├── extract.py  validate.py  load.py  metrics.py  report.py  save.py  chaos.py  logging_utils.py
│   └── transform/  010_stg_unit_response.sql  020_fct_unit_event.sql  030_fct_call.sql
├── notebooks/     01_source_discovery · 02_profile_validate ·
│                  03_workflow_model · 04_metrics_reconciliation
├── tests/         unit tests per stage + hermetic end-to-end test (99 tests, ~7s, no network)
├── data/          raw/ (gitignored and reproducible, except a committed 1-day sample and one
│                  scorecard pull used by the end-to-end test) · processed/ (gitignored DuckDB warehouse)
├── outputs/       evidence_table.md  metrics.json  validation_report.json  kpi_monthly.csv  <month>/
├── scripts/       one-off helpers (sample data pull, notebook generation, chaos-row repair)
├── .github/       CI: pytest on every push
└── run_pipeline.py
```
