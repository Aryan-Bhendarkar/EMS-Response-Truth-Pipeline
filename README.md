# EMS Response Truth Pipeline

> SF 911 ambulance dispatch data → a validated, repeatable ambulance-response KPI.
> FDE Data Foundations Assignment (Classes 4–8), Track C. Status: **Phase 5 — dependable pipeline.**

## Problem

*(filled in as the project develops — see `PROJECT_BRIEF.md` for the full brief in the meantime)*

SF Fire Department's published scorecard says ambulances reach life-threatening calls within
10 minutes 88.4% of the time (June 2026, target 90%). Callers, the press and hospitals say
otherwise. This project builds a pipeline from the raw 911 dispatch data to a KPI that can be
reproduced, questioned and trusted — and shows where in the call lifecycle response time and
ambulance capacity are actually lost.

## Users / stakeholders

- SFFD EMS Chief — resource allocation
- SF EMS Agency (regulator) — compliance across providers
- Dispatch / DEM 911 centre — call-processing performance
- Hospitals — hand-over time
- Public / press — caller-experienced response time

See `PROJECT_BRIEF.md` §2 for detail on how each stakeholder's definition of "late" differs.

## Project KPI

M1 — **Ambulance 10-minute compliance**: share of eligible life-threatening calls with the first
ambulance on scene within 10 minutes, computed monthly. The KPI's definition (clock start,
priority rule, which units count) is itself an open question this project resolves — see
`docs/judgement_call.md` (added in Phase 4/6).

## Sources

| Source | Access | Role |
|---|---|---|
| Fire Dept & EMS Dispatched Calls for Service (`nuek-vuh3`) | SODA API (JSON, month-by-month) + SODA CSV export | Core lifecycle timestamps |
| City Performance Scorecard Measures (`kc49-udxn`, measure 973) | SODA API | Official published KPI, reconciliation target |

`wr8u-xric` (Fire Incidents) and an optional weather API were considered and cut — both are
explicitly scoped to non-medical data or association-only signals with no concrete question to
answer yet. See `docs/decision_log.md`.

Full detail, ownership, grain and gaps: `docs/source_map.md` (Phase 1).

## Setup and run

```bash
# Inside WSL2 (Ubuntu). Clone/keep the repo wherever you like, including a
# Windows-mounted drive (/mnt/c, /mnt/a, ...) — but create the venv itself on
# the native Linux filesystem. Installing into a venv on a /mnt/* path is
# 10-20x slower (WSL2's 9p/drvfs protocol is slow for the thousands of small
# file writes pip does), so we point it at ~/.venvs instead.
python3 -m venv ~/.venvs/sf-ems-pipeline
source ~/.venvs/sf-ems-pipeline/bin/activate
pip install -r requirements.txt
cp config/.env.example .env   # fill in SOCRATA_APP_TOKEN (optional but recommended)

# One command: extract -> validate -> load -> transform -> metrics -> report -> save
python run_pipeline.py --month 2026-07
python run_pipeline.py --since 3              # incremental: trailing 3-day lookback

# One-time backfill of the 12-month analysis window (config/settings.yaml)
python -m pipeline.extract --backfill

# Failure-handling demos
python run_pipeline.py --month 2026-05 --chaos missing_column       # FAIL, publishes nothing
python run_pipeline.py --month 2026-04 --chaos duplicate_rowid      # WARN, dedupes on load
python run_pipeline.py --since 3 --chaos stale_data                 # FAIL freshness
python run_pipeline.py --month 2026-03 --chaos truncated_pagination # FAIL manifest_completeness
python run_pipeline.py --month 2026-02 --chaos late_update          # passes; re-run load.py to see the upsert

# Tests
python -m pytest tests/
```

A FAIL at the validate stage stops the run before anything is loaded or published — nothing in
`outputs/<scope>/` is written until the data has passed every structural check. Every stage's
individual module (`pipeline/extract.py`, `validate.py`, `load.py`, `metrics.py`) can also be run
standalone; see each module's docstring or `GATE2_DATA_READINESS.md` for real run evidence.

## Outputs

- `outputs/<month>/metrics.json`, `evidence_table.md`, `validation_report.json`, `kpi_monthly.csv`
- `outputs/<month>/dashboard.html` — static one-page dashboard
- `docs/decision_memo.md` — 1-page recommendation to the client

## What decision this supports

Whether SFFD should invest in (a) dispatch/call-processing speed, (b) more ambulance
units/contracts, or (c) faster hospital hand-over — and which KPI definition the city should
publish. See `docs/decision_memo.md` (added in Phase 6).

## Repo structure

See `PROJECT_BRIEF.md` §9.
