-- Q8. Employees still receiving pay after their separation date.
-- A payroll month counts when it starts after separation_date (the last day worked, rule 4) and has EARNING lines.
WITH post_exit AS (
    SELECT f.emp_id, f.payroll_month,
           SUM(CASE WHEN f.component_type = 'EARNING' THEN f.amount ELSE 0 END) AS earnings
    FROM warehouse.fact_payroll_line f
    JOIN warehouse.dim_employee de ON de.employee_sk = f.employee_sk
    WHERE de.separation_date IS NOT NULL
      AND f.payroll_month || '-01' > de.separation_date
    GROUP BY f.emp_id, f.payroll_month
    HAVING earnings > 0
)
SELECT p.emp_id, de.full_name, d.plant, d.dept_id, d.dept_name, de.separation_date,
       COUNT(*)                       AS months_paid_after_separation,
       MIN(p.payroll_month)           AS first_month_paid_after_exit,
       MAX(p.payroll_month)           AS last_month_paid_after_exit,
       ROUND(SUM(p.earnings), 0)      AS earnings_paid_after_exit_pkr
FROM post_exit p
JOIN warehouse.dim_employee de  ON de.emp_id = p.emp_id AND de.is_current = 1
JOIN warehouse.dim_department d ON d.dept_id = de.dept_id
GROUP BY p.emp_id, de.full_name, d.plant, d.dept_id, d.dept_name, de.separation_date
ORDER BY earnings_paid_after_exit_pkr DESC;
