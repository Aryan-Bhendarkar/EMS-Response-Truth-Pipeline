-- fct_call: one row per call, with every ingredient the KPI definitions in
-- config/kpi_definitions.yaml need - never a single hard-coded "first
-- ambulance" rule. metrics.py picks which columns to combine per definition.
--
-- Excludes rows flagged dq_response_after_onscene from the on-scene MIN
-- aggregations below (an on_scene timestamp earlier than the unit's own
-- en-route timestamp is internally inconsistent and would corrupt "first on
-- scene"). This is a named, counted exclusion (excluded_dq_rows), not a
-- silent drop - see docs/assumptions.md.
--
-- Priority and call_type_group are identical across every unit of a call in
-- 100% of the 182,495 calls checked (notebooks/03_workflow_model.ipynb) - so
-- ANY_VALUE is safe here, not an assumption.
CREATE OR REPLACE TABLE fct_call AS
SELECT
    call_number,
    MIN(received_dttm)  AS received_dttm,
    MIN(entry_dttm)     AS entry_dttm,
    MIN(dispatch_dttm)  AS dispatch_dttm,
    ANY_VALUE(original_priority) AS original_priority,
    ANY_VALUE(priority)          AS priority,
    ANY_VALUE(final_priority)    AS final_priority,
    ANY_VALUE(call_type_group)   AS call_type_group,
    ANY_VALUE(call_final_disposition) FILTER (WHERE unit_sequence_in_call_dispatch = 1)
        AS primary_unit_disposition,

    COUNT(*) AS n_units,
    COUNT(*) FILTER (WHERE unit_type = 'MEDIC')   AS n_medic_units,
    COUNT(*) FILTER (WHERE unit_type = 'PRIVATE') AS n_private_units,
    BOOL_OR(unit_type = 'MEDIC')   AS medic_used,
    BOOL_OR(unit_type = 'PRIVATE') AS private_used,

    -- "First on scene" under three unit-scope definitions (brief's open
    -- question, docs/assumptions.md §4 - resolved empirically in Phase 4,
    -- not assumed):
    MIN(on_scene_dttm) FILTER (WHERE unit_type = 'MEDIC' AND NOT dq_response_after_onscene)
        AS first_medic_on_scene_dttm,
    MIN(on_scene_dttm) FILTER (WHERE unit_type IN ('MEDIC', 'PRIVATE') AND NOT dq_response_after_onscene)
        AS first_ambulance_on_scene_dttm,
    MIN(on_scene_dttm) FILTER (WHERE NOT dq_response_after_onscene)
        AS first_any_unit_on_scene_dttm,

    COUNT(*) FILTER (WHERE dq_response_after_onscene) AS excluded_dq_rows

FROM stg_unit_response
GROUP BY call_number;
