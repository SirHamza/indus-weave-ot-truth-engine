-- Q1. Month-end headcount by plant and department, for all six months.
-- Rule 4: in headcount if hire_date <= month end AND (no separation_date OR separation_date > month end).
-- Rule 3: department = the SCD2 row valid on the month-end date.
WITH month_ends AS (
    SELECT full_date AS month_end, year_month
    FROM warehouse.dim_date
    WHERE is_month_end = 1 AND full_date BETWEEN '2026-04-01' AND '2026-09-30'
),
active AS (
    SELECT m.year_month, de.emp_id, de.dept_id
    FROM month_ends m
    JOIN warehouse.dim_employee de
      ON m.month_end BETWEEN de.valid_from AND de.valid_to
     AND de.hire_date <= m.month_end
     AND (de.separation_date IS NULL OR de.separation_date > m.month_end)
)
SELECT a.year_month AS month,
       d.plant,
       d.dept_id,
       d.dept_name,
       COUNT(*) AS headcount
FROM active a
JOIN warehouse.dim_department d ON d.dept_id = a.dept_id
GROUP BY a.year_month, d.plant, d.dept_id, d.dept_name
ORDER BY month, d.plant, d.dept_id;
