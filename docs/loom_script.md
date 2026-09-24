# Loom Recording Script — FDE Data Foundations Assignment (Classes 4–8)

> Read this once, do the dry run in "Before you hit record," then record in one take following
> the verbatim lines. Target **4:30**, hard ceiling **5:00** (assignment requires 3–5 min).
> This script is written to *record from*, not to study — `docs/demo_script.md` is the shorter
> planning outline this was built from; use that one if you just want the beat list.

## What this video must prove (assignment grading, 20% each)

Every segment below is tagged with which grading dimension it's evidence for. Don't skip a tag —
if a segment's tag doesn't get said or shown on screen, that 20% has no evidence in the video.

| Tag | Dimension | Where it lands in this script |
|---|---|---|
| **[SOURCE]** | Source reasoning — sources, owners, grain, gaps | 0:00–0:45 |
| **[RETRIEVAL]** | ≥2 retrieval modes, completeness proof, raw preserved | 0:45–1:15 |
| **[VALIDATE]** | Profiling, business rules, assumptions not silently fixed | 1:15–2:15 |
| **[MODEL]** | Entities/events/states, 3–5 metrics tied to the KPI | 2:15–2:45 |
| **[PIPELINE]** | Ingest→validate→transform→metrics, logging, rerun, failure handling | 1:15–1:45, 2:45–3:15 |
| **[JUDGEMENT]** | The one FDE judgement call, explained | 3:15–4:15 |

---

## Before you hit record — setup checklist

Do this in order. Takes ~5 minutes, saves every re-recording.

1. **Terminal**: WSL2 Ubuntu, repo open at
   `/mnt/a/Forward Deployed Engineering/SF 911 Ambulance Response`, venv activated
   (`source ~/.venvs/sf-ems-pipeline/bin/activate`). Font size big enough to read on a recording
   (14–16pt). Clear scrollback (`clear`) right before recording.
2. **Confirm the warehouse has the full 12-month backfill loaded** (so the pipeline run in
   Beat 3 is fast — under a minute — because extract mostly no-ops on unchanged months):
   ```bash
   python -c "import duckdb; c=duckdb.connect('data/processed/sf_ems.duckdb', read_only=True); print(c.execute('select count(*) from raw_calls').fetchone())"
   ```
   Expect `(364873,)`. If the file doesn't exist, run `python -m pipeline.extract --backfill`
   and `python -m pipeline.load ...` per the README *before* recording — don't do a cold 12-month
   pull on camera.
3. **Browser tabs, in this left-to-right order** (use a clean window, no bookmarks bar clutter,
   no other tabs):
   1. `README.md` rendered on GitHub (push your latest commit first) — **or** VS Code preview if
      recording before pushing
   2. `docs/source_map.md` (scrolled to the Mermaid diagram)
   3. `outputs/2026-06/dashboard.html` — closed/unopened tab, you'll open it fresh after the run
   4. `docs/judgement_call.md`
   5. `GATE2_DATA_READINESS.md`
4. **VS Code** (or your editor) open in a second window/monitor, for the moments that ask you to
   show code rather than docs. Font size bumped up there too.
5. **Close Slack, notifications, email** — anything that can pop a banner mid-recording.
6. **Loom settings**: screen + camera bubble (small, bottom-right), mic check with one spoken
   sentence played back. Record in one continuous take if you can — it reads as more confident
   than a stitched one, and this script is short enough that one clean take is realistic after
   one dry run.
7. **Have this file open on a second monitor or printed** — you are reading/paraphrasing the
   quoted lines, not memorizing them.

---

## The recording

### 0:00–0:45 — The problem and the client story **[SOURCE]**

**Screen:** README.md, top of file (title + problem section).

**Say:**
> "San Francisco's fire department publishes an official number: ambulances reach
> life-threatening emergencies within 10 minutes, 88 point 4 percent of the time. Callers and
> the press say it feels worse than that. My job as the FDE on this was to find out two things:
> can that number actually be trusted, and where is response time really being lost — using
> the city's own public 911 dispatch data, nothing else."

**Screen:** scroll to the Sources table in README, then switch to `docs/source_map.md`, point at
the Mermaid diagram and the "gaps" bullet list.

**Say:**
> "Before writing a line of code I mapped the business questions to the actual source systems —
> who owns each one, what grain it's at, and what it can't tell me. The core source is SFFD's
> computer-aided dispatch feed — one row per unit sent to a call. I cross-reference it against
> the city's own published scorecard. And I wrote down the gaps up front: no hospital name in
> this data, no stated methodology for the official number, private ambulance contractors are
> anonymized. One candidate source — the Fire Incidents dataset — turned out on inspection to
> explicitly exclude medical calls, so I cut it. That decision, with the evidence, is in
> `docs/decision_log.md`, not just silently dropped."

---

### 0:45–1:15 — Retrieval, two modes, proof of completeness **[RETRIEVAL]**

**Screen:** VS Code, `pipeline/extract.py` — scroll to `get_count()` and the completeness check
in `_extract_to_raw()`. Then flash `data/raw/calls/run_ts=.../manifest.json` in the file tree.

**Say:**
> "Retrieval is two independently-implemented modes: the Socrata JSON API, paginated with retry
> and backoff, and a second path through the same API's CSV export format — I cross-checked one
> month both ways and got an exact row-count match, 28,737 both ways. Every page is saved to disk
> byte-for-byte before any parsing happens, and before I even start paging, I ask the API for its
> own row count and check what I actually received against it — that's what raises
> `ExtractionIncompleteError` if a pull comes back short. Every run writes a manifest recording
> that proof."

---

### 1:15–2:15 — Run the pipeline live, then validation **[PIPELINE] [VALIDATE]**

**Screen:** terminal, full width.

**Type:**
```bash
python run_pipeline.py --month 2026-06
```

**Say while it runs (~20–40s):**
> "One command does the whole thing: extract, validate against fifteen named business rules,
> load into DuckDB with an idempotent upsert, run the SQL models, compute five candidate KPI
> definitions, reconcile them against the real official scorecard, and write a dashboard."

**Screen:** once it finishes, point at the log lines scrolling past —
`stage=VALIDATE`, `overall_status=WARN`, the check counts.

**Say:**
> "Validation isn't a generic schema check — every rule is business-oriented. For example: is
> every lifecycle timestamp in order, dispatch before response before on-scene? Is the priority
> code inside the known set? Is the data fresh enough to trust as current? Each rule has a
> severity — pass, warn, or fail — and a named next action. A warn means a known, counted issue
> that the run continues past; nothing here is silently fixed. The eight warnings on this run are
> real, expected data issues — a null rate here, a handful of out-of-order timestamps there —
> and every one of them is documented with an owner in `docs/assumptions.md`, not swept under
> the rug."

**Screen:** open `outputs/2026-06/dashboard.html` in the browser (freshly generated).

**Say (10s, just orient):**
> "And here's the dashboard it just built — every number on this page traces back to that run."

*(Don't deep-dive the dashboard yet — you come back to specific numbers in the judgement-call
beat. This is just "the pipeline produced this.")*

---

### 2:15–2:45 — The workflow model and the metrics **[MODEL]**

**Screen:** VS Code, `docs/data_model.md` — the Mermaid table-lineage diagram. Then briefly
`pipeline/transform/030_fct_call.sql`.

**Say:**
> "The underlying data is one row per unit sent to a call, but the KPI is measured per call — so
> the model has to bridge that. Raw rows become a typed staging table, then an event table —
> received, dispatched, en route, on scene, transport, hospital, available — one row per
> lifecycle event. Then a call-grain fact table aggregates that up: first ambulance on scene,
> how many units responded, whether a private contractor was involved. Five metrics come off
> that model, all tied to the one KPI: the headline ten-minute compliance number, call-processing
> time, ambulance travel time, hospital turnaround, and the gap between the published number and
> what a caller actually experiences. Definitions for all five: `docs/kpi_definitions.md`."

---

### 2:45–3:15 — One failure, live **[PIPELINE]**

**Screen:** terminal.

**Type:**
```bash
python run_pipeline.py --month 2026-05 --chaos missing_column
```

**Say:**
> "This injects a real failure mode — I drop a required column from the raw pull before
> validation ever sees it, simulating an upstream schema change."

**Screen:** point at `FAIL at stage=VALIDATE`, then `STOPPED. Nothing loaded or published.`

**Type:**
```bash
ls outputs/2026-05/
```

**Say (pointing at the empty/missing result):**
> "No directory. No half-written dashboard, no silently-wrong number published. It fails loudly
> and stops before anything downstream can trust bad data — that's `docs/GATE2_DATA_READINESS.md`
> rule, and it's proven here, not just claimed. Five failure scenarios like this one are verified
> in that file, and the pipeline runs the same way — extract, validate, load, metrics — whether
> it's a full backfill or a 3-day incremental catch-up, with ninety-nine automated tests behind
> it and a CI run on every push."

---

### 3:15–4:15 — The judgement call **[JUDGEMENT]**

**Screen:** `docs/judgement_call.md`, scrolled to the reconciliation table.

**Say:**
> "Here's the one judgement call I want to walk through, because it's the center of this whole
> project. The scorecard publishes no methodology for its number — no stated clock start, no
> stated priority rule, no stated unit scope. So instead of guessing, I computed five candidate
> definitions and tested every one of them against twelve real months of the actual published
> data."

**Screen:** point at the table rows — `dispatch_original_medic` at 3.51 points, the two
`received_*` rows at 21.6 and 22.1 points.

**Say:**
> "The result is lopsided. Every definition that starts its ten-minute clock at *dispatch* lands
> within about five points of the official number. Every definition that starts the clock at the
> *911 call being received* — which is what a caller actually experiences — is off by twenty-one
> to twenty-two points. Not from one lucky month. Every single month, for a year. That's about a
> six-times difference in how well the two clock choices fit reality, and it's the strongest
> single piece of evidence in this whole project."

**Screen:** switch to the dashboard tab, point at the "which clock" bar chart and the stat tiles.

**Say:**
> "So the call I'm making is: the number SFFD publishes almost certainly measures
> dispatch-to-scene time. It's real, and my best reconstruction gets within about three and a
> half points of it. But it hides seventeen to eighteen points of call-processing and queueing
> time that happens *before* dispatch — time the caller experiences but the published number
> doesn't count. My recommendation to the client is to publish both numbers side by side, with
> a named owner for confirming which one the scorecard actually means — not to silently pick a
> favorite. Full reasoning and every number behind it: `docs/judgement_call.md` and
> `docs/decision_memo.md`."

---

### 4:15–4:30 — Close

**Screen:** README.md, repo file tree, or the dashboard — whatever reads as a clean final frame.

**Say:**
> "Everything here reproduces from a fresh clone with one setup step and one command. The full
> evidence table, every assumption with an owner, the decision log, and ninety-nine passing
> tests are all in the repo. Thanks for watching."

---

## If something goes wrong on camera

- **A command hangs or errors:** don't edit around it live — say "let me re-run that" and re-run
  it once. If it fails twice, stop recording, fix it, restart from the top of that beat (Loom
  lets you trim, or just re-record the segment and stitch).
- **The pipeline run in Beat 3 takes longer than expected:** keep talking through what's
  happening (you have narration written for exactly this), don't sit in silence.
- **You go over 5:00 in the dry run:** cut from the close first, then tighten the [MODEL] beat
  (2:15–2:45) — it's the one section with no live screen action forcing its length.
- **You're under 3:00:** don't pad — that's a sign you're skipping the "say" lines, not that you
  need filler. Go back and read them in full instead of paraphrasing down to bullet points.

## After recording

1. Get the shareable Loom link (set to "anyone with the link" if the client/grader doesn't have
   a Loom account).
2. Add the link to `README.md` (a line near the top, e.g. under the problem statement) **and**
   confirm it's listed in whatever the actual assignment submission form asks for — the brief
   requires the demo alongside the GitHub URL, not instead of it.
3. Do a full watch-through once before submitting — confirm audio is present for the whole video
   and the screen recording didn't drop a segment.
