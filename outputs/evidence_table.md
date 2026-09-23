# Evidence Table

> Every number below comes directly from `outputs/metrics.json`, computed by `pipeline/metrics.py`
> against the real 12-month backfill (2025-07..2026-06, 364,873 unit-response rows, 182,495 calls)
> and reconciled against the real official scorecard (measure 973). Nothing here is asserted
> without a query behind it — see `notebooks/04_metrics_reconciliation.ipynb` for the live
> computation.

## M1 — Ambulance 10-minute compliance (the project KPI)

| | Value |
|---|---|
| Best-fitting definition | Clock=dispatch, priority=original∈{3,E}, units=MEDIC only |
| 12-month average (this definition) | **83.8%** |
| 12-month average, official scorecard | 87.3% |
| Mean absolute gap to official (12 months) | 3.5 points |
| Target | 90% within 10 minutes |

The definition above beat every other candidate by resolving the clock-start question
empirically — see `docs/judgement_call.md`. The residual ~3.5-point gap to the official number is
reported honestly, not closed by further tuning; the true methodology likely differs in some
smaller, unconfirmed way (`docs/assumptions.md`).

## M2 — Call-processing time (received → dispatch)

| | p50 | p90 |
|---|---|---|
| 12-month average | 2.2 min | 4.8 min |

No official comparator exists for this metric — the scorecard has no measure for it
(`docs/source_map.md`). Not the bottleneck: call-taking and dispatch are fast.

## M3 — Ambulance travel time (en route → on scene, MEDIC/PRIVATE only)

| | p50 | p90 |
|---|---|---|
| 12-month average | 7.4 min | 17.5 min |

Scoped to ambulance units specifically — an unscoped calculation across all responding unit
types (including fire engines, which arrive faster and are more numerous) understates this by
~3 minutes at the median (`docs/decision_log.md`, `notebooks/03_workflow_model.ipynb`).

## M4 — Hospital turnaround and ambulance-hours lost

| | Value |
|---|---|
| 12-month average p50 | 41.7 min |
| 12-month average p90 | 65.3 min |
| Standard (SF EMS Agency Policy 4000.1) | 30 min, 90% of the time |
| Share of transports exceeding the standard | **83.1%** |
| Total ambulance-hours lost beyond the standard, 12 months | **21,896 hours** (~7.5 twelve-hour shifts/day, system-wide) |

This is measured against the **30-minute turnaround** standard, not the 20-minute **offload**
standard also defined in Policy 4000.1 — the offload standard requires a hospital-EHR signature
timestamp this dataset doesn't have. The true gap to the (stricter) offload standard is almost
certainly larger, but is not estimated here — stated as a limitation, not guessed at.

## M5 — KPI definition gap (what the published number hides)

| | Value |
|---|---|
| Dispatch-clock M1 (what SFFD publishes) | 83.8% (12-mo avg, best-fit definition) |
| Received-clock M1 (what the caller experiences) | 66.8% (12-mo avg) |
| Average gap | **17.1 percentage points**, every month |

---

## Known / Unknown / Assumption / Limitation

**Known**
- The dominant bottleneck is hospital turnaround (median 41.7 min against a 30-min standard),
  not call processing (median 2.2 min) or ambulance travel (median 7.4 min).
- The official KPI can be approximately reproduced (83.8% vs. official 87.3%, ~3.5-point gap)
  using a dispatch-clock, MEDIC-only, original-priority definition — the best fit found by
  testing 5 candidates against 12 real months, not assumed in advance.
- The published number almost certainly starts its clock at dispatch, not at the 911 call being
  received — every dispatch-clock candidate outperforms every received-clock candidate by an
  order of magnitude in reconciliation accuracy (3.5-5.0 points vs. 21.6-22.1 points).

**Unknown**
- The exact official methodology (no methodology field is published for measure 973).
- The meaning of the letter priority codes (`A,B,C,E,I,T`) and numeric code `1` in
  `original_priority` — only `2` and `3` are confirmed by the dataset's own column description.
- Which hospital each transport went to, and which private ambulance contractor responded
  (both anonymized in the source data).
- Whether the official measure counts only `MEDIC` units, or any first responder — the two
  best-fitting candidate definitions (`dispatch_original_medic` and `dispatch_ctg_any_responder`)
  are within 0.1 points of each other in reconciliation accuracy.

**Assumption**
- M1's denominator excludes calls with no recorded on-scene arrival (cancelled, unable-to-locate)
  rather than counting them as automatic misses — a modeling choice, not an EMS Agency-confirmed
  rule (`docs/assumptions.md` §5b).
- Priority and `call_type_group` are treated as call-level attributes (verified consistent across
  every unit of a call, 0 exceptions in 182,495 calls — not an unverified assumption).
- The `hospital_dttm → available_dttm` interval is compared against the 30-minute turnaround
  standard, not the 20-minute offload standard (`docs/decision_log.md`).

**Limitation**
- Association, not causation — this project makes no causal claims about what drives delays.
- The ~3.5-point gap between the best-fitting reconstruction and the official number is
  unexplained by this dataset; closing it would require the actual EMS Agency methodology.
- The most recent ~3 months of dispatch data (relative to any given pull) lag the scorecard's
  own ~3-month publication delay — this project's 12-month window was deliberately chosen to end
  at the latest month with both a closed-out dispatch dataset and a published scorecard actual
  (`docs/decision_log.md`), so every reconciled month has an official number to compare against.
