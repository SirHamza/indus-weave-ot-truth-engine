-- Q10. Employees whose approved Annual leave days in these six months already exceed their
-- full-year entitlement (rule 18). Leave days = fact_leave_day (both approvals, not cancelled,
-- Sundays and plant holidays excluded - rules 16-17).
WITH annual AS (
    SELECT emp_id, COUNT(*) AS approved_annual_leave_days, COUNT(DISTINCT request_id) AS requests
    FROM warehouse.fact_leave_day
    WHERE leave_type = 'Annual'
    GROUP BY emp_id
)
SELECT a.emp_id, de.full_name, d.plant, d.dept_id, d.dept_name,
       de.annual_leave_entitlement,
       a.approved_annual_leave_days,
       a.approved_annual_leave_days - de.annual_leave_entitlement AS days_over_entitlement,
       a.requests
FROM annual a
JOIN warehouse.dim_employee de  ON de.emp_id = a.emp_id AND de.is_current = 1
JOIN warehouse.dim_department d ON d.dept_id = de.dept_id
WHERE a.approved_annual_leave_days > de.annual_leave_entitlement
ORDER BY days_over_entitlement DESC, a.emp_id;
