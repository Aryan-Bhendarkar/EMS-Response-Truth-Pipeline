# Data Model

> The relational/event model behind `pipeline/transform/*.sql`, separate from `docs/source_map.md`'s
> source-to-fact diagram. Entities, events/states, and interactions/interventions/outcomes are
> described in `notebooks/03_workflow_model.ipynb`; this is the table-lineage view of the same
> model, as it's actually implemented in DuckDB. What each metric means (formula, clock fields,
> filters, exclusions, owner, confirmation status) is in `docs/kpi_definitions.md`.

## Table lineage

```mermaid
flowchart TB
    subgraph Raw["Raw (data/raw/, untouched API pages)"]
        RC[("raw_calls\ngrain: rowid = call_number-unit_id\nupserted by rowid, latest data_loaded_at wins")]
        SC[("scorecard_measures\ngrain: measure_code, month\nfull-replace each load")]
    end

    subgraph Staging["Staging"]
        SUR["stg_unit_response\ngrain: rowid\ntyped timestamps, normalized codes,\ndq_* flags (named, counted, never silently dropped)"]
    end

    subgraph Facts["Facts"]
        FUE["fct_unit_event\ngrain: (rowid, event_type)\nlifecycle unpivoted:\nRECEIVED..AVAILABLE"]
        FC["fct_call\ngrain: call_number\nfirst_medic / first_ambulance / first_any_unit\non-scene candidates, priority, n_units"]
    end

    subgraph Dims["Dimensions"]
        PM[("dim_priority_map\ngrain: original_priority code\nfrom config/priority_map.yaml,\nconfirmed_by_owner per code")]
    end

    subgraph Metrics["Metrics (pipeline/metrics.py, Python-orchestrated)"]
        M1["M1: 5 candidate KPI definitions\n(config/kpi_definitions.yaml)\nx 12 months"]
        RECON["Reconciliation vs. scorecard_measures\n-> docs/judgement_call.md"]
        M2M5["M2-M5: call processing, travel,\nhospital turnaround, definition gap"]
    end

    subgraph Outputs["outputs/"]
        EV["evidence_table.md"]
        DASH["dashboard.html"]
        KPI["kpi_monthly.csv, metrics.json"]
    end

    RC -->|"010_stg_unit_response.sql\nCAST timestamps, flag dq_*"| SUR
    SUR -->|"020_fct_unit_event.sql\nUNION ALL, one row per event"| FUE
    SUR -->|"030_fct_call.sql\nGROUP BY call_number\n(ANY_VALUE safe: 0 exceptions,\nsee notebooks/03)"| FC
    FC --> M1
    PM -.->|"documents what each\npriority code means"| FC
    SC --> RECON
    M1 --> RECON
    SUR --> M2M5
    RECON --> KPI
    M2M5 --> KPI
    KPI --> EV
    KPI --> DASH
```

## Why `fct_call` carries three "on-scene" candidates instead of one

`fct_call` does not pick a single "first ambulance on scene" column. It carries
`first_medic_on_scene_dttm`, `first_ambulance_on_scene_dttm` (MEDIC+PRIVATE), and
`first_any_unit_on_scene_dttm` (any responder) side by side, because which one the official KPI
actually means is an open, empirically-tested question (`docs/assumptions.md` §4,
`docs/judgement_call.md`) - encoding a single choice into the model would have silently picked
an answer the data doesn't yet fully support.

## Why `dq_*` flags live on `stg_unit_response`, not a filter

Rows with an internally inconsistent timestamp (e.g. `on_scene_dttm` earlier than the unit's own
`response_dttm`) are flagged, not deleted, at the staging layer - `fct_call`'s on-scene
aggregations exclude only rows flagged `dq_response_after_onscene` (counted via
`excluded_dq_rows`), and any other query against `stg_unit_response` still sees every row. This
keeps the exclusion local to the specific calculation it protects, per CLAUDE.md rule 5 (never
silently drop rows from the dataset).
