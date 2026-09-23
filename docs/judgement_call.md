# Judgement Call: Which Clock?

> The one FDE judgement call this project's demo centers on (per the assignment brief).
> All numbers below come from `outputs/metrics.json`, computed by `pipeline/metrics.py`
> against the real 12-month backfill (2025-07..2026-06, 364,873 rows) and reconciled
> against the real official scorecard (measure 973, `kc49-udxn`) — not asserted.

## The question

The city's published ambulance-response KPI (measure 973, "percentage of ambulances that
arrive on-scene within 10 minutes to life-threatening medical emergencies") publishes no
methodology field (`docs/source_map.md`). The raw dispatch data supports at least five
plausible definitions, varying on three independent choices:

1. **Clock start** — when does the 10-minute timer begin: the 911 call being **received**,
   or the unit being **dispatched**?
2. **Priority rule** — `original_priority` (triage at call-taking) or `final_priority`
   (after reassessment)?
3. **Unit scope** — ambulances only (`MEDIC`), ambulances including private contractors
   (`MEDIC`+`PRIVATE`), or any first responder including fire engines/trucks?

These aren't cosmetic choices. They produce materially different answers to "is SF hitting
its target."

## What the data shows

Five candidate definitions were computed for all 12 months and compared against the real
scorecard actual for each month (mean absolute gap, `outputs/metrics.json` →
`m1_reconciliation`):

| Definition | Clock | Priority | Units | Mean abs. gap to official |
|---|---|---|---|---|
| **`dispatch_original_medic`** | **dispatch** | original ∈ {3,E} | MEDIC only | **3.51 points** ← best fit |
| `dispatch_ctg_any_responder` | dispatch | call_type_group = Potentially Life-Threatening | any unit | 3.58 points |
| `dispatch_final_ambulance` | dispatch | final = 3 | MEDIC+PRIVATE | 5.01 points |
| `received_original_medic` | 911 call received | original ∈ {3,E} | MEDIC only | 21.6 points |
| `received_final_ambulance` | 911 call received | final = 3 | MEDIC+PRIVATE | 22.1 points |

**The clock start dominates everything else.** Every dispatch-clock definition lands within
5 points of the official number; every received-clock definition is off by 20+ points. The
choice of priority field or unit scope barely matters next to the choice of clock.

June 2026 detail (the month the brief's original hypothesis was built around):
`dispatch_original_medic` = 85.6% vs. official 88.4% (2.8-point gap) — a reasonable
reproduction, not an exact one.

## The call

**The official measure almost certainly starts its clock at dispatch, not at the 911 call
being received.** This is not proven by a primary document (no SF EMS Agency or
Controller's Office text we read states this explicitly — see `docs/source_map.md`'s "still
open" section) — it is proven **empirically**, by testing every plausible definition against
12 months of real official data and finding one clock choice wins by an order of magnitude
over the alternative, consistently, every month.

**What this means for the client:** the number SFFD publishes (88.4% in June 2026) reflects
*dispatch-to-scene* performance. It does not include the time between a caller dialing 911
and a unit being dispatched — call-taking, triage, and queueing (M2: median 2.3 min, p90
4.9 min). From the caller's actual experience — phone ringing to help arriving — compliance
is **~15 points worse** than the published figure, every single month (`outputs/metrics.json`
→ `m5_definition_gap`, `clock_gap_points`), not a one-off finding from a single month.

## Why this is the judgement call, not just a finding

Nobody at SFFD or the EMS Agency confirmed this. It's inferred from data, with the inference
made as rigorous as the timeline allowed: five hypotheses, tested against 12 real months, not
one month cherry-picked to fit a story. The residual 3.5-point gap on even the best-fitting
definition is reported honestly, not hidden — the true methodology likely differs in some
smaller way this dataset can't fully resolve (e.g., a specific edge-case handling rule, or a
slightly different unit-inclusion rule at the margins).

**Recommendation to the client (see `docs/decision_memo.md`):** publish both numbers. The
dispatch-clock figure is what the operational team controls and should keep as the internal
performance measure. The received-clock figure is what the public and press actually
experience and should be published alongside it, with the ~15-point gap explained as
call-processing + queueing time — currently invisible in the number SF publishes today.
