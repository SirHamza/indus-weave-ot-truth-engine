-- Stage 2 (SQL) - biometric punches: map -> clock-correct -> 2-minute dedup -> shift date.
-- Input : raw.biometric_punches, staging.device_mapping, staging.device_clock_corrections, staging.roster_daily
-- Output: staging.punches (clean, one row per kept punch)
--         staging.rejected_punches (every raw punch that was NOT kept, with a reason)

DROP TABLE IF EXISTS staging.punch_events;
CREATE TABLE staging.punch_events AS
-- Step 1: trim the raw text values.
WITH base AS (
    SELECT b.punch_id,
           TRIM(b.device_id)      AS device_id,
           TRIM(b.device_user_id) AS device_user_id,
           TRIM(b.punch_time)     AS punch_time_raw,
           b._row_hash
    FROM raw.biometric_punches b
),
corrected AS (
    -- Rule 11: subtract the detected clock offset from punches of a drifting device
    -- (the offset is detected in stage2_clean.detect_clock_drift). Unmapped punches keep emp_id = NULL.
    SELECT base.*,
           m.emp_id,
           COALESCE(c.offset_minutes, 0) AS clock_offset_min,
           CASE WHEN c.offset_minutes IS NULL THEN base.punch_time_raw
                ELSE datetime(base.punch_time_raw, printf('%+d minutes', -c.offset_minutes)) END AS punch_time
    FROM base
    LEFT JOIN staging.device_mapping m
           ON m.device_id = base.device_id AND m.device_user_id = base.device_user_id
    LEFT JOIN staging.device_clock_corrections c
           ON c.device_id = base.device_id
          AND base.punch_time_raw >= c.drift_from
          AND (c.drift_to IS NULL OR base.punch_time_raw < c.drift_to)
),
sequenced AS (
    -- Rule 9 (LAG): if the same employee's previous punch is within 120 seconds, this punch is a duplicate.
    SELECT corrected.*,
           LAG(punch_id)   OVER w AS prev_punch_id,
           CAST(strftime('%s', punch_time) AS INTEGER)
             - CAST(strftime('%s', LAG(punch_time) OVER w) AS INTEGER) AS secs_since_prev
    FROM corrected
    WHERE emp_id IS NOT NULL
    WINDOW w AS (PARTITION BY emp_id ORDER BY punch_time, punch_id)
)
-- Step 4: label every punch: NULL reason = keep, otherwise the rejection reason.
SELECT c.punch_id, c.device_id, c.device_user_id, c.emp_id, c.punch_time_raw, c.punch_time,
       c.clock_offset_min, s.prev_punch_id, s.secs_since_prev,
       CASE WHEN c.emp_id IS NULL THEN 'UNMAPPED_DEVICE_USER'
            WHEN s.secs_since_prev <= 120 THEN 'DUPLICATE_WITHIN_2_MIN'
       END AS reject_reason,
       c._row_hash
FROM corrected c
LEFT JOIN sequenced s ON s.punch_id = c.punch_id;

DROP TABLE IF EXISTS staging.rejected_punches;
-- Rejected punches are kept with a readable explanation, so every raw punch is accounted for.
CREATE TABLE staging.rejected_punches AS
SELECT punch_id, device_id, device_user_id, emp_id, punch_time_raw, punch_time, clock_offset_min,
       reject_reason,
       CASE reject_reason
            WHEN 'UNMAPPED_DEVICE_USER' THEN 'No device_mapping row for device_id + device_user_id (contractor/visitor, rule 8)'
            ELSE 'Within ' || secs_since_prev || ' s of punch ' || prev_punch_id || ' (rule 9)'
       END AS reject_detail,
       _row_hash
FROM staging.punch_events
WHERE reject_reason IS NOT NULL;

-- Rule 7 + 10: shift date. A punch belongs to the previous day when
--   * previous day was NIGHT and punch is before 12:00 (night check-out), unless today is a
--     DAY/GEN shift (new roster week: that morning punch is today's check-in), or
--   * previous day was EVE and punch is before 04:00 (evening overtime past midnight).
DROP TABLE IF EXISTS staging.punches;
CREATE TABLE staging.punches AS
WITH kept AS (
    SELECT punch_id, device_id, device_user_id, emp_id, punch_time_raw, punch_time, clock_offset_min,
           date(punch_time) AS cal_date,
           CAST(strftime('%H', punch_time) AS INTEGER) AS hour_of_day
    FROM staging.punch_events
    WHERE reject_reason IS NULL
)
SELECT k.punch_id, k.emp_id, k.device_id, k.device_user_id, k.punch_time_raw, k.punch_time, k.clock_offset_min,
       CASE WHEN (k.hour_of_day < 12 AND prev.shift_code = 'NIGHT' AND COALESCE(cur.shift_code, '') NOT IN ('DAY', 'GEN'))
              OR (k.hour_of_day < 4 AND prev.shift_code = 'EVE')
            THEN date(k.cal_date, '-1 day') ELSE k.cal_date END AS shift_date,
       CASE WHEN (k.hour_of_day < 12 AND prev.shift_code = 'NIGHT' AND COALESCE(cur.shift_code, '') NOT IN ('DAY', 'GEN'))
              OR (k.hour_of_day < 4 AND prev.shift_code = 'EVE')
            THEN prev.shift_code ELSE cur.shift_code END AS shift_code
FROM kept k
LEFT JOIN staging.roster_daily cur  ON cur.emp_id = k.emp_id AND cur.work_date = k.cal_date
LEFT JOIN staging.roster_daily prev ON prev.emp_id = k.emp_id AND prev.work_date = date(k.cal_date, '-1 day');

-- Index for the attendance join; the temporary working table is then dropped.
CREATE INDEX IF NOT EXISTS staging.ix_punches_emp_date ON punches (emp_id, shift_date);
DROP TABLE staging.punch_events;
