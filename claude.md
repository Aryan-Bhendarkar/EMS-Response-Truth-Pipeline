# CLAUDE.md — SF EMS Response Pipeline

Claude Code reads this file automatically at the start of every session. These rules apply to all work in this repo.

## Project in one line
Build a trustworthy, repeatable path from San Francisco's public 911 dispatch data to an ambulance-response KPI that decision-makers can act on. It's an FDE course assignment (Classes 4–8). **`PROJECT_BRIEF.md` is the source of truth** for scope, sources, metrics and deliverables. Read it before any major step.

## Environment
- Developer machine: Windows + WSL2 (Ubuntu). Run everything inside WSL. Use Linux paths, `python3`, `venv`.
- Python 3.11+, pandas, requests, duckdb, pyyaml, pytest. Add a dependency only when it clearly earns its place, and pin it in `requirements.txt`.
- Secrets (Socrata app token) go only in `.env` (gitignored). Commit `config/.env.example`.

## Engineering principles
1. **Simple and self-explanatory beats clever.** Small functions with names that explain themselves. A newcomer should follow any module in 5 minutes.
2. **One responsibility per module:** `extract` · `validate` · `load` · `transform (SQL)` · `metrics` · `report` · `save`.
3. **Config is not code.** Thresholds, date windows, KPI definitions and URLs live in `config/`, never hard-coded.
4. **SQL for modelling, Python for orchestration.** Business logic (grain, joins, KPI rules) lives in readable `.sql` files run by DuckDB.
5. **Never silently fix data.** Every exclusion, normalisation or mapping is (a) a named rule, (b) counted, (c) written to the validation report, (d) listed in `docs/` as an assumption with an owner.
6. **Preserve raw inputs.** API pages are saved untouched before any parsing.
7. **Idempotent by default.** Rerunning a logical period replaces its output. Load with upserts keyed on `rowid`.
8. **Fail loudly and safely.** A FAIL-level check stops the run and publishes nothing. Error messages name the stage, source, check and next action.
9. **Comments explain *why*, not *what*.** A docstring on every public function. Type hints on function signatures.
10. **No ML, no Airflow/Spark, no web app.** Out of scope on purpose.

## Research freedom and when to change the plan
- The brief is a starting hypothesis, not a script. You may explore the data, read official docs (DataSF dataset pages, SF EMS Agency policies, SF scorecards) and change the plan when evidence says so.
- **When a finding contradicts the brief** (a number, a field meaning, a better KPI rule, a better source), do this:
  1. Show the evidence (query + result).
  2. Log it in `docs/decision_log.md` (date, finding, options, choice, why).
  3. Update the affected docs and code.
  4. Ask me before any change that alters **scope, the project KPI, or the main storyline**.
- Prefer primary sources (dataset metadata, official policy PDFs) over blogs. Cite URLs in the docs.
- Never invent numbers. Every number in the docs must come from pipeline output or a query shown in a notebook.

## Working style
- Work in phases (see the kickoff prompt). At the end of each phase, stop and give me a short checkpoint: what was built, key findings, open questions, next step.
- Keep `README.md` runnable and accurate at all times.
- Make small, meaningful commits with conventional messages (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`).
- Before saying something is done: run it, test it, and show the output.