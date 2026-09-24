# Decision Memo: SF Ambulance Response — What the Data Shows

**To:** SFFD EMS Division Chief, SF EMS Agency
**From:** EMS Response Truth Pipeline project
**Re:** Reproducing the published ambulance-response KPI, and where response time is actually lost
**Data:** 12 months of dispatch records (2025-07 through 2026-06, 364,873 unit responses,
182,495 calls), reconciled against the official scorecard (measure 973)

## Findings

1. **The published 88.4% (June 2026) is reproducible, within ~3.5 points, using a dispatch
   clock.** Testing five plausible definitions against 12 months of real scorecard data, the
   one starting the 10-minute timer at *dispatch* (not the 911 call being received), scoped to
   SFFD's own ambulances, reproduces the official number far better than any alternative —
   about a 6× better fit than any definition starting the clock at the 911 call (3.5-point
   average gap vs. 21.6-22.1 points). See `docs/judgement_call.md`.

2. **What callers experience is materially worse than what's published.** Measured from the
   911 call being received — what a caller and the press actually experience — compliance
   averages 17 percentage points below the same definition measured from dispatch (monthly range
   15.8-18.3; 18.1 points for the like-for-like twin of the best-fitting definition), every
   single month for 12 months straight. This is not a one-off finding.

3. **Hospital turnaround, not dispatch or travel, is where ambulance capacity is actually
   lost.** Median call-processing time is 2.2 minutes; median ambulance travel time is 7.4
   minutes. Median hospital turnaround (arrival at ED to returning to service) is **41.7
   minutes** — against a 30-minute policy standard 90% of the time (SF EMS Agency Policy 4000.1,
   effective 2026-10-01 — after this analysis window, so it is used as the forward-looking
   benchmark; the standard in force during the window was not located). 83% of transports miss
   that standard. Over 12 months, that's an estimated **21,896 ambulance-hours** lost beyond the
   standard — about 5 twelve-hour ambulance shifts (21,896 ÷ 365 ÷ 12 ≈ 5.0), every day,
   system-wide. The interval also includes cleaning and restocking the ambulance after
   hand-over, so this overstates the hospital's own share of the loss.

4. **The 20-minute offload standard (Policy 4000.1) cannot currently be measured at all.** It
   requires a hospital-EHR timestamp (patient physically off the gurney, care transferred) that
   doesn't exist in the CAD dispatch data. Measured against the 30-minute turnaround standard,
   the figure above is an upper bound on the hospital's share (it includes cleaning/restocking).
   Against the stricter 20-minute offload standard, the true shortfall is likely larger — but it
   cannot be measured with this data, so it is not estimated.

## Recommendation

**Publish two KPIs, not one.** Keep the dispatch-clock number as the internal operational
measure — it's what the dispatch and field teams actually control. Publish the received-clock
number alongside it as the public-facing figure, with the gap explicitly labeled as
call-processing and queueing time. Hiding this gap behind a single number invites exactly the
credibility problem the city is already facing in the press.

**Prioritize hospital turnaround over dispatch speed.** The data doesn't support investing
further in call-processing or dispatch software — that stage is already fast. It strongly
supports investing in hospital hand-over: even partial progress toward the 30-minute standard
would return meaningfully more ambulance-hours to the street than any plausible dispatch-side
improvement.

## Decisions the owner must make

1. **Confirm or correct the "which clock" finding.** This project inferred a dispatch-clock
   start empirically, because the scorecard publishes no stated methodology. Someone who
   actually owns measure 973's definition should confirm this — or correct it.
2. **Assign an owner for the priority-code mapping.** `original_priority` mixes a confirmed
   numeric scale (`2`=non-emergency, `3`=emergency) with six unconfirmed letter codes and an
   unexplained `1` value, covering ~21% of all calls. Nobody currently owns documenting what
   these mean.
3. **Decide whether "first responder" should count toward the ambulance KPI.** Fire
   engines/trucks routinely arrive before a dedicated ambulance and can carry ALS-certified
   crew. A definition counting any first responder fits the official number almost as well as
   MEDIC-only (3.6 vs. 3.5-point gap) — this project cannot fully resolve which the city
   actually means.

## What the dispatch system should start recording

- **The hospital's name/identifier per transport** — currently anonymized, making it impossible
  to identify which hospitals drive the turnaround problem.
- **The actual patient-offload timestamp (APOT-1)** — the only way to measure against the
  20-minute standard the city has itself already adopted.
- **Which private ambulance contractor responded** — currently just `unit_type = PRIVATE`, with
  no way to hold any specific contractor accountable.

Full evidence: `outputs/evidence_table.md`. Full reasoning: `docs/judgement_call.md`,
`docs/decision_log.md`, `docs/assumptions.md`.
