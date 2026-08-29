-- playback_events: one row per playback session.
-- Session-grain keeps the KPI math clean: rebuffer_rate = avg(rebuffered).
CREATE TABLE IF NOT EXISTS playback_events
(
    event_time    DateTime,                    -- session start time
    session_id    UUID,
    user_id       UInt64,
    country       LowCardinality(String),
    region        LowCardinality(String),
    device        LowCardinality(String),
    os            LowCardinality(String),
    app_version   LowCardinality(String),
    cdn_pop       LowCardinality(String),
    isp           LowCardinality(String),
    title         LowCardinality(String),
    watch_seconds UInt32,
    rebuffered    UInt8,                        -- 1 if the session experienced a rebuffer
    rebuffer_ms   UInt32,                       -- total rebuffer duration (ms)
    errored       UInt8,                        -- 1 if playback errored
    error_code    LowCardinality(String)        -- '' if none
)
ENGINE = MergeTree
ORDER BY (event_time, region, cdn_pop);
