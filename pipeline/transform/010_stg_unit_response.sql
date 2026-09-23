-- stg_unit_response: the latest version of each unit-response row, typed and flagged.
--
-- Grain: one row per rowid (call_number-unit_id). Timestamps are cast from the
-- source's text format to TIMESTAMP. Data-quality flags are computed here and
-- carried forward, never used to drop rows (CLAUDE.md rule 5) - fct_call and
-- metrics.py exclude flagged rows from the specific intervals they'd corrupt,
-- while keeping the row for every other purpose.
CREATE OR REPLACE TABLE stg_unit_response AS
SELECT
    rowid,
    call_number,
    unit_id,
    incident_number,
    call_type,
    call_type_group,
    CAST(received_dttm AS TIMESTAMP)   AS received_dttm,
    CAST(entry_dttm AS TIMESTAMP)      AS entry_dttm,
    CAST(dispatch_dttm AS TIMESTAMP)   AS dispatch_dttm,
    CAST(response_dttm AS TIMESTAMP)   AS response_dttm,
    CAST(on_scene_dttm AS TIMESTAMP)   AS on_scene_dttm,
    CAST(transport_dttm AS TIMESTAMP)  AS transport_dttm,
    CAST(hospital_dttm AS TIMESTAMP)   AS hospital_dttm,
    CAST(available_dttm AS TIMESTAMP)  AS available_dttm,
    call_final_disposition,
    NULLIF(original_priority, '')      AS original_priority,
    NULLIF(priority, '')               AS priority,
    NULLIF(final_priority, '')         AS final_priority,
    unit_type,
    CAST(als_unit AS BOOLEAN)          AS als_unit,
    TRY_CAST(unit_sequence_in_call_dispatch AS INTEGER) AS unit_sequence_in_call_dispatch,
    battalion,
    station_area,
    supervisor_district,
    neighborhoods_analysis_boundaries,
    CAST(data_as_of AS TIMESTAMP)      AS data_as_of,
    CAST(data_loaded_at AS TIMESTAMP)  AS data_loaded_at,

    -- Data-quality flags (brief Q5) - counted in validation_report.json, and
    -- used below to exclude only the specific interval each violation breaks.
    (dispatch_dttm IS NOT NULL AND response_dttm IS NOT NULL
        AND CAST(response_dttm AS TIMESTAMP) < CAST(dispatch_dttm AS TIMESTAMP))  AS dq_dispatch_after_response,
    (response_dttm IS NOT NULL AND on_scene_dttm IS NOT NULL
        AND CAST(on_scene_dttm AS TIMESTAMP) < CAST(response_dttm AS TIMESTAMP))  AS dq_response_after_onscene,
    (on_scene_dttm IS NOT NULL AND transport_dttm IS NOT NULL
        AND CAST(transport_dttm AS TIMESTAMP) < CAST(on_scene_dttm AS TIMESTAMP)) AS dq_onscene_after_transport,
    (transport_dttm IS NOT NULL AND hospital_dttm IS NOT NULL
        AND CAST(hospital_dttm AS TIMESTAMP) < CAST(transport_dttm AS TIMESTAMP)) AS dq_transport_after_hospital,
    (hospital_dttm IS NOT NULL AND available_dttm IS NOT NULL
        AND CAST(available_dttm AS TIMESTAMP) < CAST(hospital_dttm AS TIMESTAMP)) AS dq_hospital_after_available
FROM raw_calls;
