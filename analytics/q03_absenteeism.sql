-- Q3. Absenteeism rate by plant and month, excluding approved leave.
-- Denominator = scheduled working days (not Sunday, not a plant holiday) that are NOT approved leave.
-- Numerator   = those days with status Absent. Missing Punch is not absence (the employee punched in).
WITH working_days AS (
    SELECT dd.year_month, d.plant, f.status
    FROM warehouse.fact_attendance_daily f
    JOIN warehouse.dim_date dd      ON dd.date_key = f.date_key
    JOIN warehouse.dim_department d ON d.dept_id = f.dept_id
    WHERE f.is_working_day = 1
      AND f.status <> 'On Leave'
)
SELECT year_month AS month,
       plant,
       COUNT(*)                                            AS scheduled_days_excl_leave,
       SUM(CASE WHEN status = 'Absent' THEN 1 ELSE 0 END)  AS absent_days,
       ROUND(100.0 * SUM(CASE WHEN status = 'Absent' THEN 1 ELSE 0 END) / COUNT(*), 2) AS absenteeism_rate_pct
FROM working_days
GROUP BY year_month, plant
ORDER BY month, plant;
