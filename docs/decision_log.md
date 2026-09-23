# Decision Log

Format: date, finding, options considered, choice, why. Every entry is triggered by evidence
shown at the time (query, quote, or document), per CLAUDE.md rule 5.

---

## 2026-09-23 — Cut the Fire Incidents dataset (`wr8u-xric`)

**Finding:** `wr8u-xric`'s own DataSF metadata describes it as *"a summary of each **non-medical**
incident to which the SF Fire Department responded"* (fetched via `data.sf.gov/api/views/wr8u-xric.json`).
Its columns (`suppression_units`, `ignition_cause`, `estimated_property_loss`, `action_taken_primary`)
are fire-suppression fields, not EMS/ambulance fields.

**Options:**
1. Keep it as a cross-check per the brief (§3, S4) — verify a call "really happened" and see its outcome.
2. Cut it.

**Choice:** Cut. `call_final_disposition` in S1 (`nuek-vuh3`) already gives per-unit outcome for
every medical response, and S4 is explicitly scoped to exclude medical incidents — there is no
overlapping subject matter for it to cross-check against. Pulling it would add a retrieval mode
with no evidentiary payoff.

**Why it matters:** The brief listed this as an open Phase-1 decision ("Cut what doesn't earn its
place"); this closes it with primary-source evidence rather than a hunch.

---

## 2026-09-23 — Cut the Open-Meteo weather API (for now)

**Finding:** No change from the brief — it already frames weather as "context signal only
(association, not cause)," and CLAUDE.md rule 10 rules out causal claims for this project.

**Options:**
1. Pull it now, speculatively, in case it's useful later.
2. Cut it until a specific, testable question emerges from profiling (e.g., "does rain raise
   travel-time p90?").

**Choice:** Cut for now. Revisit only if Phase 3/4 profiling surfaces a concrete hypothesis it
would actually test — adding a source with no specific question attached is scope creep, not
retrieval-mode credit.

---

## 2026-09-23 — M4 (hospital capacity loss) redefined against the 30-minute turnaround standard, not the 20-minute offload standard

**Finding:** `PROJECT_BRIEF.md` §4 says "Official policy is 20 min hand-over, 90% of the time"
for the `available_dttm − hospital_dttm` interval computed from S1. Reading the actual policy
(SF EMS Agency Policy 4000.1, *Ambulance Turnaround Time Standard*, effective 10/1/26,
`media.api.sf.gov/documents/EMSA-4000.1-Ambulance-Turnaround-Time-Standard-10-1-2026.pdf`)
shows there are **two separate standards**:
- **Offload time interval ≤ 20 min, 90%** (§4.1) — measured to "APOT-1," defined as the moment a
  patient is moved off the gurney *and* transfer of care is signed off by an ED nurse/doctor in
  the hospital's own EHR. **No field in S1 captures this** — it lives entirely in a hospital
  system this project has no access to.
- **Ambulance turnaround interval ≤ 30 min, 90%** (§4.2) — ED arrival to return-to-service. This
  interval **is** what `hospital_dttm → available_dttm` in S1 approximates.

**Options:**
1. Keep comparing the raw `available_dttm − hospital_dttm` interval to the 20-minute standard, as
   the brief originally framed it.
2. Compare it to the 30-minute turnaround standard instead, and name APOT-1/20-minute as a known
   blind spot the data cannot see.

**Choice:** Option 2. Comparing raw CAD data to a standard it structurally cannot measure would
overstate how bad hospital hand-over looks and misrepresent the policy. The 42-minute median wall
time cited in the brief is still a real finding — it now needs to be read against the 30-minute/90%
turnaround target, not the 20-minute one, and the gap to the *offload* standard should be reported
as unmeasurable with this data source, not silently assumed.

**Owner for closing this gap:** SF EMS Agency (source of the APOT-1 signature data, held in
hospital EHR systems, not DataSF) — noted as an unconfirmed/unavailable data source, per
`docs/source_map.md` §4.

---

## 2026-09-23 — "Which clock starts the official measure" stays an open question, not an assumption

**Finding:** A web search paraphrase claimed the official measure's clock runs "Call Dispatched →
Units On-Scene" ("Roll Time"), but this was not read directly from a primary SF EMS Agency or
Controller's Office document — every primary document actually read (FY25 APR p.17, the scorecard
API record for measure 973) describes the target ("10 minutes, 90% of the time, Code 3") without
stating which timestamp starts the clock.

**Choice:** Do not treat "dispatch" as confirmed. Phase 4 will compute M1 under both a
dispatch-clock and a call-received-clock definition across all backfilled months and see which one
actually reproduces the officially published `actual` values in `kc49-udxn` — that empirical match
is the real evidence, not a search-engine summary. This is exactly the "which clock?" judgement
call the brief anticipated (§4, §8) — it stays open until Phase 4 produces that comparison.
