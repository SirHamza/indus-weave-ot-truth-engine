-- Q2. Monthly attrition rate by department = separations in month / average headcount.
-- Average headcount = (opening headcount on the previous month end + closing headcount on month end) / 2.
-- A separation belongs to the department on the separation date (= last day worked, rules 3-4).
WITH months AS (
    SELECT year_month,
           MIN(full_date)                 AS month_start,
           MAX(full_date)                 AS month_end,
           date(MIN(full_date), '-1 day') AS prev_month_end
    FROM warehouse.dim_date
    WHERE full_date BETWEEN '2026-04-01' AND '2026-09-30'
    GROUP BY year_month
),
snapshots AS (
    SELECT year_month, 'opening' AS kind, prev_month_end AS as_of FROM months
    UNION ALL
    SELECT year_month, 'closing', month_end FROM months
),
headcount_at AS (
    SELECT s.year_month, s.kind, de.dept_id, COUNT(*) AS headcount
    FROM snapshots s
    JOIN warehouse.dim_employee de
      ON s.as_of BETWEEN de.valid_from AND de.valid_to
     AND de.hire_date <= s.as_of
     AND (de.separation_date IS NULL OR de.separation_date > s.as_of)
    GROUP BY s.year_month, s.kind, de.dept_id
),
separations AS (
    SELECT m.year_month, de.dept_id, COUNT(*) AS separations
    FROM months m
    JOIN warehouse.dim_employee de
      ON de.separation_date BETWEEN m.month_start AND m.month_end
     AND de.separation_date BETWEEN de.valid_from AND de.valid_to
    GROUP BY m.year_month, de.dept_id
),
combined AS (
    SELECT m.year_month, d.plant, d.dept_id, d.dept_name,
           COALESCE(o.headcount, 0)   AS opening_headcount,
           COALESCE(c.headcount, 0)   AS closing_headcount,
           COALESCE(s.separations, 0) AS separations
    FROM months m
    CROSS JOIN warehouse.dim_department d
    LEFT JOIN headcount_at o ON o.year_month = m.year_month AND o.dept_id = d.dept_id AND o.kind = 'opening'
    LEFT JOIN headcount_at c ON c.year_month = m.year_month AND c.dept_id = d.dept_id AND c.kind = 'closing'
    LEFT JOIN separations  s ON s.year_month = m.year_month AND s.dept_id = d.dept_id
)
SELECT year_month AS month, plant, dept_id, dept_name,
       opening_headcount, closing_headcount,
       (opening_headcount + closing_headcount) / 2.0 AS avg_headcount,
       separations,
       ROUND(100.0 * separations / NULLIF((opening_headcount + closing_headcount) / 2.0, 0), 2) AS attrition_rate_pct
FROM combined
ORDER BY month, dept_id;
