-- Q9. Payroll cost per employee by department, with month-over-month change.
-- Cost = SUM of EARNING lines (rule 21); employees = distinct employees with earnings that month;
-- department per rule 3 (warehouse.v_employee_month). MoM change via LAG().
WITH dept_month AS (
    SELECT year_month, dept_id,
           SUM(earnings_amount)  AS payroll_cost,
           COUNT(DISTINCT emp_id) AS paid_employees
    FROM warehouse.v_employee_month
    WHERE year_month BETWEEN '2026-04' AND '2026-09'
      AND earnings_amount > 0
    GROUP BY year_month, dept_id
),
per_emp AS (
    SELECT dept_month.*,
           payroll_cost / paid_employees AS cost_per_employee
    FROM dept_month
)
SELECT p.year_month AS month, d.plant, d.dept_id, d.dept_name,
       ROUND(p.payroll_cost, 0)     AS payroll_cost_pkr,
       p.paid_employees,
       ROUND(p.cost_per_employee, 2) AS cost_per_employee_pkr,
       ROUND(p.cost_per_employee - LAG(p.cost_per_employee) OVER w, 2) AS mom_change_pkr,
       ROUND(100.0 * (p.cost_per_employee - LAG(p.cost_per_employee) OVER w)
             / LAG(p.cost_per_employee) OVER w, 2)                     AS mom_change_pct
FROM per_emp p
JOIN warehouse.dim_department d ON d.dept_id = p.dept_id
WINDOW w AS (PARTITION BY p.dept_id ORDER BY p.year_month)
ORDER BY d.dept_id, month;
