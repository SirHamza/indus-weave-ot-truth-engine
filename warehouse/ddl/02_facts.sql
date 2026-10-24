-- Stage 4 - warehouse facts. Every fact row carries the SCD2 employee_sk valid on its date.

-- Grain: employee x day of employment (Workforce owns attendance).
CREATE TABLE warehouse.fact_attendance_daily (
    emp_id          TEXT    NOT NULL,
    date_key        INTEGER NOT NULL REFERENCES dim_date (date_key),
    employee_sk     INTEGER NOT NULL REFERENCES dim_employee (employee_sk),
    dept_id         TEXT    NOT NULL REFERENCES dim_department (dept_id),
    shift_code      TEXT    NOT NULL REFERENCES dim_shift (shift_code),
    status          TEXT    NOT NULL CHECK (status IN ('Present', 'Absent', 'On Leave', 'Holiday', 'Weekly Off', 'Missing Punch')),
    is_working_day  INTEGER NOT NULL,
    is_holiday      INTEGER NOT NULL,
    holiday_name    TEXT,
    leave_request_id TEXT,
    roster_imputed  INTEGER NOT NULL,
    punch_count     INTEGER NOT NULL,
    check_in        TEXT,
    check_out       TEXT,
    worked_hours    REAL,
    is_late         INTEGER NOT NULL,
    late_minutes    REAL    NOT NULL,
    is_early_departure INTEGER NOT NULL,
    early_departure_minutes REAL NOT NULL,
    ot_hours        REAL    NOT NULL,
    PRIMARY KEY (emp_id, date_key)   -- shift-length sanity (<= 16 h) is a DQ check, so a bad month is flagged, not crashed
);

-- Grain: approved leave request x leave day (Sundays/plant holidays excluded, rule 17).
CREATE TABLE warehouse.fact_leave_day (
    request_id      TEXT    NOT NULL,
    date_key        INTEGER NOT NULL REFERENCES dim_date (date_key),
    emp_id          TEXT    NOT NULL,
    employee_sk     INTEGER NOT NULL REFERENCES dim_employee (employee_sk),
    dept_id         TEXT    NOT NULL REFERENCES dim_department (dept_id),
    leave_type      TEXT    NOT NULL CHECK (leave_type IN ('Annual', 'Casual', 'Sick')),
    PRIMARY KEY (request_id, date_key)
);

-- Grain: approved overtime request (status = Approved, rule 19). date_key = shift date.
CREATE TABLE warehouse.fact_overtime_approved (
    request_id      TEXT    PRIMARY KEY,
    date_key        INTEGER NOT NULL REFERENCES dim_date (date_key),
    emp_id          TEXT    NOT NULL,
    employee_sk     INTEGER NOT NULL REFERENCES dim_employee (employee_sk),
    dept_id         TEXT    NOT NULL REFERENCES dim_department (dept_id),
    requested_hours REAL    NOT NULL,
    approved_hours  REAL    NOT NULL CHECK (approved_hours >= 0),
    approver_id     TEXT,
    computed_ot_hours REAL,                       -- from fact_attendance_daily for the same shift date
    attendance_status TEXT                        -- status that day (NULL = not employed / no row)
);

-- Grain: payslip line. Payroll consumes attendance; it is attributed (rule 3) to the
-- department on the month's reporting date = month end, or separation date if earlier.
CREATE TABLE warehouse.fact_payroll_line (
    line_id         TEXT    PRIMARY KEY,
    payroll_month   TEXT    NOT NULL,             -- YYYY-MM
    date_key        INTEGER NOT NULL REFERENCES dim_date (date_key),  -- reporting date
    emp_id          TEXT    NOT NULL,
    employee_sk     INTEGER NOT NULL REFERENCES dim_employee (employee_sk),
    dept_id         TEXT    NOT NULL REFERENCES dim_department (dept_id),
    component       TEXT    NOT NULL CHECK (component IN ('BASIC', 'HOUSE_RENT', 'MEDICAL', 'CONVEYANCE', 'OVERTIME',
                                                         'INCOME_TAX', 'EOBI', 'ABSENCE_DEDUCTION', 'LOAN_INSTALLMENT')),
    component_type  TEXT    NOT NULL CHECK (component_type IN ('EARNING', 'DEDUCTION')),
    units           REAL,
    amount          REAL    NOT NULL CHECK (amount >= 0)
);
CREATE INDEX warehouse.ix_fact_payroll_emp_month ON fact_payroll_line (emp_id, payroll_month);
CREATE INDEX warehouse.ix_fact_att_date ON fact_attendance_daily (date_key);
