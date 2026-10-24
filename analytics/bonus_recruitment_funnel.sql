-- Bonus. Recruitment funnel from applications.csv: conversion and median days at each stage.
-- reached      = applications that ever hit the stage
-- conversion   = reached / reached at the previous funnel stage; overall = reached / applied
-- days_in_stage = days from entering the stage to the application's next stage event (any outcome)
WITH events AS (
    SELECT application_id, stage, stage_date,
           LEAD(stage_date) OVER (PARTITION BY application_id ORDER BY stage_date,
               CASE stage WHEN 'Applied' THEN 1 WHEN 'Screened' THEN 2 WHEN 'Interviewed' THEN 3
                          WHEN 'Offered' THEN 4 ELSE 5 END) AS next_stage_date
    FROM staging.applications
),
funnel AS (
    SELECT 1 AS step, 'Applied' AS stage UNION ALL SELECT 2, 'Screened' UNION ALL
    SELECT 3, 'Interviewed' UNION ALL SELECT 4, 'Offered' UNION ALL SELECT 5, 'Hired'
),
reached AS (
    SELECT f.step, f.stage, COUNT(DISTINCT e.application_id) AS applications
    FROM funnel f LEFT JOIN events e ON e.stage = f.stage
    GROUP BY f.step, f.stage
),
durations AS (
    SELECT e.stage, julianday(e.next_stage_date) - julianday(e.stage_date) AS days,
           ROW_NUMBER() OVER (PARTITION BY e.stage ORDER BY julianday(e.next_stage_date) - julianday(e.stage_date)) AS rn,
           COUNT(*) OVER (PARTITION BY e.stage) AS n
    FROM events e
    WHERE e.next_stage_date IS NOT NULL
),
medians AS (
    -- SQLite has no MEDIAN(): take the average of the middle one or two values.
    SELECT stage, AVG(days) AS median_days, MAX(n) AS transitions
    FROM durations
    WHERE rn IN ((n + 1) / 2, (n + 2) / 2)
    GROUP BY stage
)
SELECT r.step, r.stage, r.applications AS reached,
       ROUND(100.0 * r.applications / LAG(r.applications) OVER (ORDER BY r.step), 2) AS conversion_from_prev_pct,
       ROUND(100.0 * r.applications / FIRST_VALUE(r.applications) OVER (ORDER BY r.step), 2) AS conversion_from_applied_pct,
       m.median_days AS median_days_in_stage,
       m.transitions AS transitions_measured
FROM reached r
LEFT JOIN medians m ON m.stage = r.stage
ORDER BY r.step;
