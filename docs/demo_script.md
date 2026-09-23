# Demo Script (3-5 minutes)

> Walks the repo → runs the pipeline → shows one failure → explains the "which clock?"
> judgement call. Timings are approximate.

## 0:00-0:30 — The problem

> "SF's official scorecard says ambulances reach life-threatening calls within 10 minutes
> 88.4% of the time. The press and callers say it feels worse. My job was to find out whether
> that number can be trusted, and where response time is actually being lost — using SF's own
> public dispatch data."

Open `README.md` — point to the KPI section and the sources table.

## 0:30-1:15 — The repo, quickly

Open `docs/source_map.md` — show the Mermaid diagram and the "gaps" section (no hospital
name, no methodology published, anonymized private contractors).

> "Before writing any code, I mapped business questions to sources, owners, and gaps. One
> source I considered — the Fire Incidents dataset — turned out to explicitly exclude medical
> calls, so I cut it. That's logged, not silently dropped." (`docs/decision_log.md`)

## 1:15-2:30 — Run the pipeline, live

```bash
python run_pipeline.py --month 2026-06
```

Let it run (~30-60s). While it runs:

> "One command: extract from the SODA API with pagination and retry, validate against 13 named
> business rules, load into DuckDB with an idempotent upsert, run the SQL models, compute five
> candidate KPI definitions, reconcile against the real official scorecard, and write a
> dashboard — all in one shot."

When it finishes, open `outputs/2026-06/dashboard.html` in a browser. Point to:
- The KPI-vs-official comparison table (which definition wins, and by how much)
- The time-lost-per-step bars (call processing vs. travel vs. hospital turnaround)
- The gate status at the bottom (PASS/WARN/FAIL per rule)

## 2:30-3:15 — Show one failure

```bash
python run_pipeline.py --month 2026-05 --chaos missing_column
```

> "This simulates a schema change upstream — I drop a required column from the raw pull before
> validation sees it."

Point to the log output: `FAIL at stage=VALIDATE`, then `STOPPED. Nothing loaded or published.`

```bash
ls outputs/2026-05/   # doesn't exist
```

> "No half-written output, no silently-wrong dashboard. It fails loudly and stops before
> anything downstream trusts bad data." Optionally show a second scenario:

```bash
python run_pipeline.py --month 2026-04 --chaos duplicate_rowid
```

> "This one WARNs instead of failing — a duplicate row isn't a structural break, it's something
> the load step's upsert-by-rowid handles on its own. Same command, two different outcomes,
> because the two problems genuinely are different severities." (Full chaos evidence:
> `GATE2_DATA_READINESS.md`.)

## 3:15-4:30 — The judgement call

Open `docs/judgement_call.md`.

> "Here's the one call I want to walk through. The scorecard publishes no methodology for its
> 88.4% figure — no stated clock start, no stated priority rule, no stated unit scope. So I
> tested five plausible definitions against all 12 months of the real published data."

Show the reconciliation table.

> "The clock start dominates everything else. Every definition starting the timer at
> *dispatch* lands within 5 points of the official number. Every definition starting at the
> *911 call being received* — what the caller actually experiences — is off by 17 to 22
> points. Not from one lucky month; every single month, for a year.
>
> That's the finding: the number SF publishes measures dispatch-to-scene time. It hides
> roughly 17 points of call-processing and queueing time that happens *before* dispatch. My
> recommendation is to publish both numbers, not just one."

## 4:30-5:00 — Close

> "The full evidence — every number, every assumption, every exclusion — is in
> `outputs/evidence_table.md` and `docs/assumptions.md`, with named owners for what's still
> unconfirmed. The pipeline reruns idempotently, its validation rules are unit-tested, and
> every one of the five failure scenarios in `GATE2_DATA_READINESS.md` is verified against the
> real thing, not simulated in a slide."

## If asked "what would you do with more time?"

- Get the actual measure-973 methodology confirmed by its real owner, closing the residual
  ~3.5-point reconciliation gap.
- Push for the hospital name and APOT-1 offload timestamp to be added to the CAD system — the
  single highest-value data gap this project found (`docs/decision_memo.md`).
- Add a scheduled (e.g. nightly) incremental run via `--since Nd` in CI, so the "current month"
  dashboard stays fresh without a manual re-run.
