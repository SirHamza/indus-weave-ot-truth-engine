-- Q7. Employees paid in a month with zero attendance in that month.
-- Paid = at least one EARNING line in the payroll month.
-- Zero attendance = not a single punch-backed day (no Present or Missing Punch day) in that month.
SELECT m.year_month AS month, m.emp_id, de.full_name, d.plant, d.dept_id, d.dept_name,
       de.hire_date, de.separation_date,
       m.employed_days,
       m.attended_days,
       ROUND(m.earnings_amount, 0) AS earnings_paid_pkr,
       CASE WHEN m.employed_days = 0 THEN 'No employment days in month (after separation)'
            ELSE 'Employed but no punches all month' END AS pattern
FROM warehouse.v_employee_month m
JOIN warehouse.dim_employee de  ON de.employee_sk = m.employee_sk
JOIN warehouse.dim_department d ON d.dept_id = m.dept_id
WHERE m.year_month BETWEEN '2026-04' AND '2026-09'
  AND m.earnings_amount > 0
  AND m.attended_days = 0
ORDER BY m.emp_id, month;
