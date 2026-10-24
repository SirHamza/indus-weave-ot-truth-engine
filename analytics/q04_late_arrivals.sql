-- Q4. The 10 employees with the most late arrivals, and their department.
-- Late = check-in more than 10 min after shift start, on a Present working day (rule 13).
-- Department = current (latest) SCD2 row. RANK() keeps any tie at 10th place visible.
WITH late AS (
    SELECT emp_id,
           SUM(is_late)               AS late_arrivals,
           ROUND(SUM(late_minutes), 1) AS total_late_minutes
    FROM warehouse.fact_attendance_daily
    WHERE date_key BETWEEN 20260401 AND 20260930
    GROUP BY emp_id
),
ranked AS (
    SELECT late.*, RANK() OVER (ORDER BY late_arrivals DESC) AS late_rank
    FROM late
)
SELECT r.late_rank, r.emp_id, de.full_name, d.plant, d.dept_id, d.dept_name,
       r.late_arrivals, r.total_late_minutes
FROM ranked r
JOIN warehouse.dim_employee de  ON de.emp_id = r.emp_id AND de.is_current = 1
JOIN warehouse.dim_department d ON d.dept_id = de.dept_id
WHERE r.late_rank <= 10
ORDER BY r.late_rank, r.emp_id;
