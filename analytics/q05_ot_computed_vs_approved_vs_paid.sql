-- Q5. Overtime hours computed from punches vs approved vs paid, by department and month.
-- computed = fact_attendance_daily.ot_hours (rules 14-15), approved = Approved OT requests (rule 19),
-- paid = payroll OVERTIME units (rule 20). Department attribution: warehouse.v_employee_month (rule 3).
WITH dept_month AS (
    SELECT year_month, dept_id,
           SUM(computed_ot_hours) AS computed_ot_hours,
           SUM(approved_ot_hours) AS approved_ot_hours,
           SUM(paid_ot_hours)     AS paid_ot_hours,
           SUM(paid_ot_amount)    AS paid_ot_amount
    FROM warehouse.v_employee_month
    WHERE year_month BETWEEN '2026-04' AND '2026-09'
    GROUP BY year_month, dept_id
)
SELECT m.year_month AS month, d.plant, d.dept_id, d.dept_name,
       ROUND(m.computed_ot_hours, 2) AS computed_ot_hours,
       ROUND(m.approved_ot_hours, 2) AS approved_ot_hours,
       ROUND(m.paid_ot_hours, 2)     AS paid_ot_hours,
       ROUND(m.paid_ot_amount, 0)    AS paid_ot_amount_pkr,
       ROUND(m.paid_ot_hours - m.computed_ot_hours, 2) AS paid_minus_computed_hours,
       ROUND(100.0 * (m.paid_ot_hours - m.computed_ot_hours) / NULLIF(m.computed_ot_hours, 0), 2) AS paid_vs_computed_pct
FROM dept_month m
JOIN warehouse.dim_department d ON d.dept_id = m.dept_id
ORDER BY month, d.dept_id;
