-- Q6. Departments where paid overtime exceeds computed overtime by more than 15%
-- (six-month totals: paid_ot_hours > computed_ot_hours * 1.15).
WITH dept_totals AS (
    SELECT dept_id,
           SUM(computed_ot_hours) AS computed_ot_hours,
           SUM(approved_ot_hours) AS approved_ot_hours,
           SUM(paid_ot_hours)     AS paid_ot_hours,
           SUM(paid_ot_amount)    AS paid_ot_amount
    FROM warehouse.v_employee_month
    WHERE year_month BETWEEN '2026-04' AND '2026-09'
    GROUP BY dept_id
)
SELECT d.plant, d.dept_id, d.dept_name,
       ROUND(t.computed_ot_hours, 2) AS computed_ot_hours,
       ROUND(t.approved_ot_hours, 2) AS approved_ot_hours,
       ROUND(t.paid_ot_hours, 2)     AS paid_ot_hours,
       ROUND(t.paid_ot_hours - t.computed_ot_hours, 2) AS excess_paid_hours,
       ROUND(100.0 * (t.paid_ot_hours - t.computed_ot_hours) / NULLIF(t.computed_ot_hours, 0), 2) AS excess_pct,
       -- Value of the excess hours = the department's average paid rate per OT hour.
       ROUND((t.paid_ot_hours - t.computed_ot_hours) * t.paid_ot_amount / NULLIF(t.paid_ot_hours, 0), 0)
           AS excess_paid_amount_pkr
FROM dept_totals t
JOIN warehouse.dim_department d ON d.dept_id = t.dept_id
WHERE t.paid_ot_hours > t.computed_ot_hours * 1.15
ORDER BY excess_pct DESC;
