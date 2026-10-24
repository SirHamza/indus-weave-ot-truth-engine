-- Stage 4 - analytics view: one row per employee x payroll month, attributed to the department
-- on the month's reporting date (rule 3: month end, or separation date if they left in/before that month).
-- Used by q05-q09 so the attribution logic exists in exactly one place.
DROP VIEW IF EXISTS warehouse.v_employee_month;
CREATE VIEW warehouse.v_employee_month AS
WITH attendance AS (
    SELECT dd.year_month, f.emp_id,
           SUM(f.ot_hours)                                                    AS computed_ot_hours,
           SUM(CASE WHEN f.status IN ('Present', 'Missing Punch') THEN 1 ELSE 0 END) AS attended_days,
           SUM(CASE WHEN f.status = 'Present' THEN 1 ELSE 0 END)              AS present_days,
           COUNT(*)                                                           AS employed_days
    FROM fact_attendance_daily f
    JOIN dim_date dd ON dd.date_key = f.date_key
    GROUP BY dd.year_month, f.emp_id
),
approved AS (
    SELECT dd.year_month, o.emp_id, SUM(o.approved_hours) AS approved_ot_hours
    FROM fact_overtime_approved o
    JOIN dim_date dd ON dd.date_key = o.date_key
    GROUP BY dd.year_month, o.emp_id
),
payroll AS (
    -- Long -> wide pivot (rules 20-21): OVERTIME units = hours paid; cost = SUM of EARNING lines.
    SELECT payroll_month AS year_month, emp_id,
           SUM(CASE WHEN component = 'OVERTIME' THEN units  ELSE 0 END)    AS paid_ot_hours,
           SUM(CASE WHEN component = 'OVERTIME' THEN amount ELSE 0 END)    AS paid_ot_amount,
           SUM(CASE WHEN component_type = 'EARNING' THEN amount ELSE 0 END) AS earnings_amount,
           SUM(CASE WHEN component_type = 'DEDUCTION' THEN amount ELSE 0 END) AS deductions_amount
    FROM fact_payroll_line
    GROUP BY payroll_month, emp_id
),
keys AS (
    SELECT year_month, emp_id FROM attendance
    UNION SELECT year_month, emp_id FROM approved
    UNION SELECT year_month, emp_id FROM payroll
),
reporting AS (
    SELECT k.year_month, k.emp_id, e.separation_date, e.hire_date,
           date(k.year_month || '-01', '+1 month', '-1 day') AS month_end
    FROM keys k
    JOIN (SELECT DISTINCT emp_id, separation_date, hire_date FROM dim_employee) e ON e.emp_id = k.emp_id
)
SELECT r.year_month, r.emp_id, de.employee_sk, de.dept_id, r.hire_date, r.separation_date,
       CASE WHEN r.separation_date IS NOT NULL AND r.separation_date < r.month_end
            THEN r.separation_date ELSE r.month_end END              AS reporting_date,
       COALESCE(a.computed_ot_hours, 0)  AS computed_ot_hours,
       COALESCE(ap.approved_ot_hours, 0) AS approved_ot_hours,
       COALESCE(p.paid_ot_hours, 0)      AS paid_ot_hours,
       COALESCE(p.paid_ot_amount, 0)     AS paid_ot_amount,
       COALESCE(p.earnings_amount, 0)    AS earnings_amount,
       COALESCE(p.deductions_amount, 0)  AS deductions_amount,
       CASE WHEN p.emp_id IS NOT NULL THEN 1 ELSE 0 END AS on_payroll,
       COALESCE(a.attended_days, 0)      AS attended_days,
       COALESCE(a.present_days, 0)       AS present_days,
       COALESCE(a.employed_days, 0)      AS employed_days
FROM reporting r
JOIN dim_employee de
  ON de.emp_id = r.emp_id
 AND (CASE WHEN r.separation_date IS NOT NULL AND r.separation_date < r.month_end
           THEN r.separation_date ELSE r.month_end END) BETWEEN de.valid_from AND de.valid_to
LEFT JOIN attendance a ON a.year_month = r.year_month AND a.emp_id = r.emp_id
LEFT JOIN approved  ap ON ap.year_month = r.year_month AND ap.emp_id = r.emp_id
LEFT JOIN payroll    p ON p.year_month = r.year_month AND p.emp_id = r.emp_id;
