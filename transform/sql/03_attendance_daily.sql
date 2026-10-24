-- Stage 3 - staging.attendance_daily: one row per employee per day of employment in the period.
-- Rules 7, 10, 12-15 (data_dictionary.md). Period comes from staging.pipeline_params.

DROP TABLE IF EXISTS staging.attendance_daily;
CREATE TABLE staging.attendance_daily AS
-- Step 1: one row per calendar day in the reporting period.
WITH RECURSIVE calendar(work_date) AS (
    SELECT period_start FROM staging.pipeline_params
    UNION ALL
    SELECT date(work_date, '+1 day') FROM calendar, staging.pipeline_params
    WHERE work_date < period_end
),
employee_days AS (
    -- Every day each employee was employed: hire_date up to separation_date (the last day worked).
    SELECT e.emp_id, c.work_date, d.plant, d.plant_code
    FROM staging.employees e
    JOIN staging.departments d ON d.dept_id = e.dept_id
    JOIN calendar c ON c.work_date >= e.hire_date
                   AND (e.separation_date IS NULL OR c.work_date <= e.separation_date)
),
-- Step 2: per employee and shift date, first punch = check-in, last punch = check-out.
punch_day AS (
    SELECT emp_id, shift_date, COUNT(*) AS punch_count,
           MIN(punch_time) AS check_in, MAX(punch_time) AS check_out
    FROM staging.punches
    GROUP BY emp_id, shift_date
),
-- Step 3: approved leave days, holidays, roster and department for each day.
leave_day AS (
    SELECT emp_id, leave_date, MIN(request_id) AS leave_request_id, MIN(leave_type) AS leave_type
    FROM staging.leave_days
    GROUP BY emp_id, leave_date
),
holiday AS (
    SELECT holiday_date, scope, holiday_name FROM staging.holidays
),
-- Step 4: put everything about one employee-day on one row, including the exact shift start/end timestamps.
assembled AS (
    SELECT ed.emp_id, ed.work_date, ed.plant, ed.plant_code,
           h.dept_id,
           r.shift_code, COALESCE(r.is_imputed, 0) AS roster_imputed,
           s.start_time, s.end_time, s.crosses_midnight, s.grace_minutes,
           CASE WHEN strftime('%w', ed.work_date) = '0' THEN 1 ELSE 0 END AS is_sunday,
           COALESCE(hp.holiday_name, ha.holiday_name) AS holiday_name,
           lv.leave_request_id, lv.leave_type,
           COALESCE(p.punch_count, 0) AS punch_count, p.check_in, p.check_out,
           datetime(ed.work_date || ' ' || s.start_time) AS shift_start_ts,
           datetime(ed.work_date || ' ' || s.end_time, CASE WHEN s.crosses_midnight = 1 THEN '+1 day' ELSE '+0 day' END)
               AS shift_end_ts
    FROM employee_days ed
    LEFT JOIN staging.employment_history h
           ON h.emp_id = ed.emp_id AND ed.work_date >= h.valid_from
          AND (h.valid_to IS NULL OR ed.work_date <= h.valid_to)
    LEFT JOIN staging.roster_daily r ON r.emp_id = ed.emp_id AND r.work_date = ed.work_date
    LEFT JOIN staging.shifts s       ON s.shift_code = r.shift_code
    LEFT JOIN holiday ha ON ha.holiday_date = ed.work_date AND ha.scope = 'ALL'
    LEFT JOIN holiday hp ON hp.holiday_date = ed.work_date AND hp.scope = ed.plant_code
    LEFT JOIN leave_day lv ON lv.emp_id = ed.emp_id AND lv.leave_date = ed.work_date
    LEFT JOIN punch_day p  ON p.emp_id = ed.emp_id AND p.shift_date = ed.work_date
),
-- Step 5: decide the day's status and compute the time differences in whole seconds.
with_status AS (
    SELECT a.*,
           CASE WHEN a.is_sunday = 0 AND a.holiday_name IS NULL THEN 1 ELSE 0 END AS is_working_day,
           -- Rule 12 priority order.
           CASE WHEN a.is_sunday = 1 AND a.punch_count = 0           THEN 'Weekly Off'
                WHEN a.holiday_name IS NOT NULL AND a.punch_count = 0 THEN 'Holiday'
                WHEN a.leave_request_id IS NOT NULL                   THEN 'On Leave'
                WHEN a.punch_count >= 2                               THEN 'Present'
                WHEN a.punch_count = 1                                THEN 'Missing Punch'
                ELSE 'Absent' END AS status,
           CAST(strftime('%s', a.check_in) AS INTEGER) - CAST(strftime('%s', a.shift_start_ts) AS INTEGER) AS secs_after_start,
           CAST(strftime('%s', a.shift_end_ts) AS INTEGER) - CAST(strftime('%s', a.check_out) AS INTEGER) AS secs_before_end,
           CAST(strftime('%s', a.check_out) AS INTEGER) - CAST(strftime('%s', a.shift_end_ts) AS INTEGER) AS secs_after_end,
           CAST(strftime('%s', a.check_out) AS INTEGER) - CAST(strftime('%s', a.check_in) AS INTEGER)     AS secs_worked
    FROM assembled a
)
-- Step 6: final columns. Hours/minutes are only filled for Present days.
SELECT emp_id, work_date, dept_id, plant, plant_code, shift_code, roster_imputed,
       is_sunday, CASE WHEN holiday_name IS NOT NULL THEN 1 ELSE 0 END AS is_holiday, holiday_name,
       is_working_day, leave_request_id, leave_type,
       punch_count, check_in, check_out, shift_start_ts, shift_end_ts,
       status,
       CASE WHEN status = 'Present' THEN ROUND(secs_worked / 3600.0, 2) END AS worked_hours,
       -- Rule 13: late / early departure only on Present working days, and only beyond the 10-minute grace.
       CASE WHEN status = 'Present' AND is_working_day = 1 AND secs_after_start > grace_minutes * 60
            THEN 1 ELSE 0 END AS is_late,
       CASE WHEN status = 'Present' AND is_working_day = 1 AND secs_after_start > grace_minutes * 60
            THEN ROUND(secs_after_start / 60.0, 1) ELSE 0 END AS late_minutes,
       CASE WHEN status = 'Present' AND is_working_day = 1 AND secs_before_end > grace_minutes * 60
            THEN 1 ELSE 0 END AS is_early_departure,
       CASE WHEN status = 'Present' AND is_working_day = 1 AND secs_before_end > grace_minutes * 60
            THEN ROUND(secs_before_end / 60.0, 1) ELSE 0 END AS early_departure_minutes,
       -- Rules 14-15: OT = time after shift end on a working day (all worked time on Sunday/holiday),
       -- rounded DOWN to whole half-hours (integer division by 1800 seconds, so no float errors).
       CASE WHEN status <> 'Present' THEN 0
            WHEN is_working_day = 1 THEN (CASE WHEN secs_after_end > 0 THEN secs_after_end / 1800 ELSE 0 END) * 0.5
            ELSE (secs_worked / 1800) * 0.5 END AS ot_hours
FROM with_status;

CREATE UNIQUE INDEX IF NOT EXISTS staging.ux_attendance_emp_date ON attendance_daily (emp_id, work_date);
