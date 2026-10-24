-- Stage 4 - warehouse dimensions (star schema). Re-runnable: facts are dropped first (FK order).
DROP TABLE IF EXISTS warehouse.fact_payroll_line;
DROP TABLE IF EXISTS warehouse.fact_overtime_approved;
DROP TABLE IF EXISTS warehouse.fact_leave_day;
DROP TABLE IF EXISTS warehouse.fact_attendance_daily;
DROP TABLE IF EXISTS warehouse.dim_employee;
DROP TABLE IF EXISTS warehouse.dim_department;
DROP TABLE IF EXISTS warehouse.dim_shift;
DROP TABLE IF EXISTS warehouse.dim_date;

CREATE TABLE warehouse.dim_date (
    date_key        INTEGER PRIMARY KEY,          -- YYYYMMDD
    full_date       TEXT    NOT NULL UNIQUE,      -- ISO YYYY-MM-DD
    year            INTEGER NOT NULL,
    month           INTEGER NOT NULL,
    year_month      TEXT    NOT NULL,             -- YYYY-MM (joins payroll_month)
    month_name      TEXT    NOT NULL,
    day_of_month    INTEGER NOT NULL,
    day_of_week     INTEGER NOT NULL,             -- 0 = Sunday ... 6 = Saturday
    day_name        TEXT    NOT NULL,
    is_sunday       INTEGER NOT NULL CHECK (is_sunday IN (0, 1)),
    is_month_end    INTEGER NOT NULL CHECK (is_month_end IN (0, 1)),
    holiday_all_plants TEXT                       -- name when scope = ALL; plant holidays live on the fact
);

CREATE TABLE warehouse.dim_department (
    dept_id         TEXT PRIMARY KEY,
    dept_name       TEXT NOT NULL,                -- current name
    previous_name   TEXT,                         -- name before rename (Procurement, Processing)
    renamed_on      TEXT,
    plant           TEXT NOT NULL,
    plant_code      TEXT NOT NULL,
    cost_center     TEXT NOT NULL
);

CREATE TABLE warehouse.dim_shift (
    shift_code       TEXT PRIMARY KEY,
    shift_name       TEXT    NOT NULL,
    start_time       TEXT    NOT NULL,
    end_time         TEXT    NOT NULL,
    crosses_midnight INTEGER NOT NULL CHECK (crosses_midnight IN (0, 1)),
    grace_minutes    INTEGER NOT NULL,
    shift_hours      REAL    NOT NULL
);

-- SCD Type 2: one row per employment_history record; valid_to = next record start - 1 day.
CREATE TABLE warehouse.dim_employee (
    employee_sk     INTEGER PRIMARY KEY,
    emp_id          TEXT NOT NULL,
    valid_from      TEXT NOT NULL,
    valid_to        TEXT NOT NULL,                -- 9999-12-31 for the current row
    is_current      INTEGER NOT NULL CHECK (is_current IN (0, 1)),
    change_reason   TEXT NOT NULL,
    dept_id         TEXT NOT NULL REFERENCES dim_department (dept_id),
    designation     TEXT NOT NULL,
    grade           TEXT NOT NULL,
    basic_salary    REAL NOT NULL,
    -- Type 1 attributes from the de-duplicated employee master
    full_name       TEXT NOT NULL,
    gender          TEXT,
    date_of_birth   TEXT,
    plant           TEXT NOT NULL,
    employment_type TEXT,
    hire_date       TEXT NOT NULL,
    separation_date TEXT,
    employee_status TEXT,
    annual_leave_entitlement INTEGER NOT NULL,
    UNIQUE (emp_id, valid_from),
    CHECK (valid_from <= valid_to)
);
CREATE INDEX warehouse.ix_dim_employee_emp ON dim_employee (emp_id, valid_from, valid_to);
