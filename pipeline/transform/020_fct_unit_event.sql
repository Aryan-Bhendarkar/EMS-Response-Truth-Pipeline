-- fct_unit_event: the unit-response lifecycle unpivoted into one row per event.
--
-- Grain: (rowid, event_type). Mirrors PROJECT_BRIEF.md §5's lifecycle:
-- RECEIVED -> ENTERED -> DISPATCHED -> EN_ROUTE -> ON_SCENE -> [TRANSPORTING ->
-- AT_HOSPITAL] -> AVAILABLE. Only recorded events produce a row - a call that
-- never reached "on scene" simply has no ON_SCENE event, which is visible
-- and queryable rather than hidden behind a NULL column.
CREATE OR REPLACE TABLE fct_unit_event AS
SELECT rowid, call_number, unit_id AS actor, 'RECEIVED'     AS event_type, received_dttm  AS event_ts FROM stg_unit_response WHERE received_dttm  IS NOT NULL
UNION ALL
SELECT rowid, call_number, unit_id, 'ENTERED',     entry_dttm     FROM stg_unit_response WHERE entry_dttm     IS NOT NULL
UNION ALL
SELECT rowid, call_number, unit_id, 'DISPATCHED',  dispatch_dttm  FROM stg_unit_response WHERE dispatch_dttm  IS NOT NULL
UNION ALL
SELECT rowid, call_number, unit_id, 'EN_ROUTE',     response_dttm  FROM stg_unit_response WHERE response_dttm  IS NOT NULL
UNION ALL
SELECT rowid, call_number, unit_id, 'ON_SCENE',     on_scene_dttm  FROM stg_unit_response WHERE on_scene_dttm  IS NOT NULL
UNION ALL
SELECT rowid, call_number, unit_id, 'TRANSPORTING', transport_dttm FROM stg_unit_response WHERE transport_dttm IS NOT NULL
UNION ALL
SELECT rowid, call_number, unit_id, 'AT_HOSPITAL',  hospital_dttm  FROM stg_unit_response WHERE hospital_dttm  IS NOT NULL
UNION ALL
SELECT rowid, call_number, unit_id, 'AVAILABLE',    available_dttm FROM stg_unit_response WHERE available_dttm IS NOT NULL;
