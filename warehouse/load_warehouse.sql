-- Stage 4 - load the star schema from staging (runs after ddl/01 and ddl/02).

-- dim_date: calendar from 1 Mar to 31 Oct 2026 covers every fact and the opening headcount date.
INSERT INTO warehouse.dim_date
WITH RECURSIVE d(dt) AS (
    SELECT '2026-03-01'
    UNION ALL SELECT date(dt, '+1 day') FROM d WHERE dt < '2026-10-31'
)
SELECT CAST(strftime('%Y%m%d', dt) AS INTEGER), dt,
       CAST(strftime('%Y', dt) AS INTEGER), CAST(strftime('%m', dt) AS INTEGER), strftime('%Y-%m', dt),
       CASE strftime('%m', dt) WHEN '03' THEN 'March' WHEN '04' THEN 'April' WHEN '05' THEN 'May'
            WHEN '06' THEN 'June' WHEN '07' THEN 'July' WHEN '08' THEN 'August'
            WHEN '09' THEN 'September' ELSE 'October' END,
       CAST(strftime('%d', dt) AS INTEGER), CAST(strftime('%w', dt) AS INTEGER),
       CASE strftime('%w', dt) WHEN '0' THEN 'Sunday' WHEN '1' THEN 'Monday' WHEN '2' THEN 'Tuesday'
            WHEN '3' THEN 'Wednesday' WHEN '4' THEN 'Thursday' WHEN '5' THEN 'Friday' ELSE 'Saturday' END,
       CASE WHEN strftime('%w', dt) = '0' THEN 1 ELSE 0 END,
       CASE WHEN date(dt, '+1 day', 'start of month') = date(dt, '+1 day') THEN 1 ELSE 0 END,
       (SELECT holiday_name FROM staging.holidays h WHERE h.holiday_date = dt AND h.scope = 'ALL')
FROM d;

INSERT INTO warehouse.dim_department
SELECT dept_id, dept_name, previous_name, renamed_on, plant, plant_code, cost_center
FROM staging.departments;

INSERT INTO warehouse.dim_shift
SELECT shift_code, name, start_time, end_time, crosses_midnight, grace_minutes, shift_hours
FROM staging.shifts;

INSERT INTO warehouse.dim_employee (emp_id, valid_from, valid_to, is_current, change_reason, dept_id, designation,
    grade, basic_salary, full_name, gender, date_of_birth, plant, employment_type, hire_date, separation_date,
    employee_status, annual_leave_entitlement)
SELECT h.emp_id, h.valid_from, COALESCE(h.valid_to, '9999-12-31'), h.is_current, h.change_reason, h.dept_id,
       h.designation, h.grade, h.basic_salary,
       e.full_name, e.gender, e.date_of_birth, e.plant, e.employment_type, e.hire_date, e.separation_date,
       e.status, e.annual_leave_entitlement
FROM staging.employment_history h
JOIN staging.employees e ON e.emp_id = h.emp_id
ORDER BY h.emp_id, h.valid_from;


INSERT INTO warehouse.fact_attendance_daily
SELECT a.emp_id, CAST(strftime('%Y%m%d', a.work_date) AS INTEGER), de.employee_sk, de.dept_id, a.shift_code,
       a.status, a.is_working_day, a.is_holiday, a.holiday_name, a.leave_request_id, a.roster_imputed,
       a.punch_count, a.check_in, a.check_out, a.worked_hours, a.is_late, a.late_minutes,
       a.is_early_departure, a.early_departure_minutes, a.ot_hours
FROM staging.attendance_daily a
JOIN warehouse.dim_employee de
  ON de.emp_id = a.emp_id AND a.work_date BETWEEN de.valid_from AND de.valid_to;

INSERT INTO warehouse.fact_leave_day
SELECT l.request_id, CAST(strftime('%Y%m%d', l.leave_date) AS INTEGER), l.emp_id, de.employee_sk, de.dept_id, l.leave_type
FROM staging.leave_days l
JOIN warehouse.dim_employee de
  ON de.emp_id = l.emp_id AND l.leave_date BETWEEN de.valid_from AND de.valid_to;

INSERT INTO warehouse.fact_overtime_approved
SELECT o.request_id, CAST(strftime('%Y%m%d', o.ot_date) AS INTEGER), o.emp_id, de.employee_sk, de.dept_id,
       o.requested_hours, o.approved_hours, o.approver_id, a.ot_hours, a.status
FROM staging.overtime_requests o
JOIN warehouse.dim_employee de
  ON de.emp_id = o.emp_id AND o.ot_date BETWEEN de.valid_from AND de.valid_to
LEFT JOIN staging.attendance_daily a ON a.emp_id = o.emp_id AND a.work_date = o.ot_date
WHERE o.status = 'Approved';

-- Rule 3: reporting date = month end, or the separation date when the employee left in/before that month.
INSERT INTO warehouse.fact_payroll_line
WITH lines AS (
    SELECT p.*, e.separation_date,
           date(p.payroll_month || '-01', '+1 month', '-1 day') AS month_end
    FROM staging.payroll_lines p
    JOIN staging.employees e ON e.emp_id = p.emp_id
),
dated AS (
    SELECT lines.*,
           CASE WHEN separation_date IS NOT NULL AND separation_date < month_end THEN separation_date
                ELSE month_end END AS reporting_date
    FROM lines
)
SELECT d.line_id, d.payroll_month, CAST(strftime('%Y%m%d', d.reporting_date) AS INTEGER), d.emp_id,
       de.employee_sk, de.dept_id, d.component, d.component_type, d.units, d.amount
FROM dated d
JOIN warehouse.dim_employee de
  ON de.emp_id = d.emp_id AND d.reporting_date BETWEEN de.valid_from AND de.valid_to;
