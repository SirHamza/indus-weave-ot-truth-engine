"""Stage 6 - automated data-quality checks, run after every load. Results -> warehouse.dq_results.

Every check is a SQL query returning the number of FAILING rows (0 = PASS), except
reconciliation checks which compare a raw count with staging + rejected counts.
Exit code 1 if any check fails, so run_pipeline.py stops loudly instead of demoing bad data.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline_config import connect, log  # noqa: E402

# (table, primary-key columns) for uniqueness + not-null checks
PRIMARY_KEYS = {
    "staging.employees": ["emp_id"],
    "staging.employment_history": ["emp_id", "valid_from"],
    "staging.departments": ["dept_id"],
    "staging.punches": ["punch_id"],
    "staging.leave_requests": ["request_id"],
    "staging.leave_approvals": ["request_id", "step"],
    "staging.leave_days": ["request_id", "leave_date"],
    "staging.overtime_requests": ["request_id"],
    "staging.payroll_lines": ["line_id"],
    "staging.attendance_daily": ["emp_id", "work_date"],
    "warehouse.dim_date": ["date_key"],
    "warehouse.dim_department": ["dept_id"],
    "warehouse.dim_shift": ["shift_code"],
    "warehouse.dim_employee": ["employee_sk"],
    "warehouse.fact_attendance_daily": ["emp_id", "date_key"],
    "warehouse.fact_leave_day": ["request_id", "date_key"],
    "warehouse.fact_overtime_approved": ["request_id"],
    "warehouse.fact_payroll_line": ["line_id"],
}

# (fact table, fk column, dimension table, dimension key)
FOREIGN_KEYS = [
    (fact, col, dim, key)
    for fact in ["fact_attendance_daily", "fact_leave_day", "fact_overtime_approved", "fact_payroll_line"]
    for col, dim, key in [("employee_sk", "dim_employee", "employee_sk"), ("dept_id", "dim_department", "dept_id"),
                          ("date_key", "dim_date", "date_key")]
] + [("fact_attendance_daily", "shift_code", "dim_shift", "shift_code"),
     ("dim_employee", "dept_id", "dim_department", "dept_id")]

# Reconciliation: raw rows = staging rows + rows parked elsewhere (with a reason).
RECONCILIATION = [
    ("employees", "SELECT COUNT(*) FROM raw.employees",
     "SELECT (SELECT COUNT(*) FROM staging.employees) + (SELECT COUNT(*) FROM staging.employee_merge_log)",
     "staging.employees + staging.employee_merge_log"),
    ("employment_history", "SELECT COUNT(*) FROM raw.employment_history",
     "SELECT (SELECT COUNT(*) FROM staging.employment_history) + (SELECT COUNT(*) FROM staging.rejected_employment_history)",
     "staging.employment_history + staging.rejected_employment_history"),
    ("departments", "SELECT COUNT(*) FROM raw.departments", "SELECT COUNT(*) FROM staging.departments", "staging.departments"),
    ("shifts", "SELECT COUNT(*) FROM raw.shifts", "SELECT COUNT(*) FROM staging.shifts", "staging.shifts"),
    ("shift_roster", "SELECT COUNT(*) FROM raw.shift_roster",
     "SELECT COUNT(*) FROM staging.shift_roster WHERE is_imputed = 0", "staging.shift_roster (is_imputed = 0)"),
    ("device_mapping", "SELECT COUNT(*) FROM raw.device_mapping", "SELECT COUNT(*) FROM staging.device_mapping",
     "staging.device_mapping"),
    ("biometric_punches", "SELECT COUNT(*) FROM raw.biometric_punches",
     "SELECT (SELECT COUNT(*) FROM staging.punches) + (SELECT COUNT(*) FROM staging.rejected_punches)",
     "staging.punches + staging.rejected_punches"),
    ("holidays", "SELECT COUNT(*) FROM raw.holidays", "SELECT COUNT(*) FROM staging.holidays", "staging.holidays"),
    ("leave_requests", "SELECT COUNT(*) FROM raw.leave_requests", "SELECT COUNT(*) FROM staging.leave_requests",
     "staging.leave_requests"),
    ("leave_approval_steps", "SELECT SUM(json_array_length(record_json, '$.approvals')) FROM raw.leave_requests",
     "SELECT COUNT(*) FROM staging.leave_approvals", "staging.leave_approvals"),
    ("overtime_requests", "SELECT COUNT(*) FROM raw.overtime_requests", "SELECT COUNT(*) FROM staging.overtime_requests",
     "staging.overtime_requests"),
    ("payroll_lines", "SELECT COUNT(*) FROM raw.payroll_lines", "SELECT COUNT(*) FROM staging.payroll_lines",
     "staging.payroll_lines"),
    ("applications", "SELECT COUNT(*) FROM raw.applications", "SELECT COUNT(*) FROM staging.applications",
     "staging.applications"),
    # staging -> warehouse: no fact row lost in the SCD2 joins
    ("attendance -> fact", "SELECT COUNT(*) FROM staging.attendance_daily",
     "SELECT COUNT(*) FROM warehouse.fact_attendance_daily", "warehouse.fact_attendance_daily"),
    ("leave_days -> fact", "SELECT COUNT(*) FROM staging.leave_days", "SELECT COUNT(*) FROM warehouse.fact_leave_day",
     "warehouse.fact_leave_day"),
    ("approved OT -> fact", "SELECT COUNT(*) FROM staging.overtime_requests WHERE status = 'Approved'",
     "SELECT COUNT(*) FROM warehouse.fact_overtime_approved", "warehouse.fact_overtime_approved"),
    ("payroll -> fact", "SELECT COUNT(*) FROM staging.payroll_lines", "SELECT COUNT(*) FROM warehouse.fact_payroll_line",
     "warehouse.fact_payroll_line"),
    ("employment_history -> dim", "SELECT COUNT(*) FROM staging.employment_history",
     "SELECT COUNT(*) FROM warehouse.dim_employee", "warehouse.dim_employee"),
]

# Columns that may only contain a fixed list of values.
ACCEPTED_VALUES = [
    ("warehouse.fact_attendance_daily", "status",
     ["Present", "Absent", "On Leave", "Holiday", "Weekly Off", "Missing Punch"]),
    ("staging.leave_requests", "leave_type", ["Annual", "Casual", "Sick"]),
    ("warehouse.fact_payroll_line", "component",
     ["BASIC", "HOUSE_RENT", "MEDICAL", "CONVEYANCE", "OVERTIME", "INCOME_TAX", "EOBI", "ABSENCE_DEDUCTION",
      "LOAN_INSTALLMENT"]),
    ("warehouse.fact_payroll_line", "component_type", ["EARNING", "DEDUCTION"]),
    ("staging.overtime_requests", "status", ["Approved", "Rejected", "Pending"]),
    ("staging.leave_approvals", "action", ["Approved", "Rejected"]),
    ("staging.rejected_punches", "reject_reason", ["UNMAPPED_DEVICE_USER", "DUPLICATE_WITHIN_2_MIN"]),
]

# Business-rule checks. Each query counts the rows that break the rule (0 = PASS).
SANITY = [
    ("no negative worked hours", "warehouse.fact_attendance_daily",
     "SELECT COUNT(*) FROM warehouse.fact_attendance_daily WHERE worked_hours < 0"),
    ("no shift longer than 16 hours", "warehouse.fact_attendance_daily",
     "SELECT COUNT(*) FROM warehouse.fact_attendance_daily WHERE worked_hours > 16"),
    ("no negative overtime", "warehouse.fact_attendance_daily",
     "SELECT COUNT(*) FROM warehouse.fact_attendance_daily WHERE ot_hours < 0"),
    ("OT in whole half-hours", "warehouse.fact_attendance_daily",
     "SELECT COUNT(*) FROM warehouse.fact_attendance_daily WHERE ot_hours * 2 <> CAST(ot_hours * 2 AS INTEGER)"),
    ("Present rows have check-in < check-out", "warehouse.fact_attendance_daily",
     "SELECT COUNT(*) FROM warehouse.fact_attendance_daily WHERE status = 'Present' AND NOT (check_in < check_out)"),
    ("no overlapping SCD2 ranges", "warehouse.dim_employee",
     """SELECT COUNT(*) FROM warehouse.dim_employee a JOIN warehouse.dim_employee b
          ON a.emp_id = b.emp_id AND a.employee_sk < b.employee_sk
         AND a.valid_from <= b.valid_to AND b.valid_from <= a.valid_to"""),
    ("no gaps between SCD2 ranges", "warehouse.dim_employee",
     """SELECT COUNT(*) FROM (SELECT valid_to, LEAD(valid_from) OVER (PARTITION BY emp_id ORDER BY valid_from) AS nxt
                              FROM warehouse.dim_employee) WHERE nxt IS NOT NULL AND date(valid_to, '+1 day') <> nxt"""),
    ("exactly one current SCD2 row per employee", "warehouse.dim_employee",
     "SELECT COUNT(*) FROM (SELECT emp_id FROM warehouse.dim_employee GROUP BY emp_id HAVING SUM(is_current) <> 1)"),
    ("first SCD2 row starts on hire_date", "warehouse.dim_employee",
     """SELECT COUNT(*) FROM (SELECT emp_id, MIN(valid_from) f, MIN(hire_date) h FROM warehouse.dim_employee
                              GROUP BY emp_id) WHERE f <> h"""),
    ("no duplicate punches left within 2 min", "staging.punches",
     """SELECT COUNT(*) FROM (SELECT CAST(strftime('%s', punch_time) AS INTEGER)
              - CAST(strftime('%s', LAG(punch_time) OVER (PARTITION BY emp_id ORDER BY punch_time)) AS INTEGER) g
              FROM staging.punches) WHERE g <= 120"""),
    ("no shift date with more than 2 punches", "staging.punches",
     "SELECT COUNT(*) FROM (SELECT 1 FROM staging.punches GROUP BY emp_id, shift_date HAVING COUNT(*) > 2)"),
    ("all employee dates ISO", "staging.employees",
     """SELECT COUNT(*) FROM staging.employees WHERE hire_date NOT GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'
          OR (separation_date IS NOT NULL AND separation_date NOT GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]')"""),
    ("leave days never on Sunday", "warehouse.fact_leave_day",
     "SELECT COUNT(*) FROM warehouse.fact_leave_day f JOIN warehouse.dim_date d USING (date_key) WHERE d.is_sunday = 1"),
    ("one attendance row per employee per employment day", "warehouse.fact_attendance_daily",
     """SELECT ABS((SELECT COUNT(*) FROM warehouse.fact_attendance_daily)
          - (SELECT SUM(julianday(MIN(COALESCE(e.separation_date, p.period_end), p.period_end))
                        - julianday(MAX(e.hire_date, p.period_start)) + 1)
             FROM staging.employees e, staging.pipeline_params p WHERE e.hire_date <= p.period_end
               AND (e.separation_date IS NULL OR e.separation_date >= p.period_start)))"""),
]


def main() -> int:
    conn = connect()
    run_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    results: list[tuple] = []

    # Store one check result; 0 failing rows means PASS.
    def record(category, name, table, failing, expected=None, actual=None, details=""):
        results.append((run_at, category, name, table, "PASS" if failing == 0 else "FAIL",
                        int(failing), expected, actual, details))

    # 1) Primary keys: no duplicates and no NULLs.
    for table, cols in PRIMARY_KEYS.items():
        key = ", ".join(cols)
        dup = conn.execute(f"SELECT COUNT(*) FROM (SELECT {key} FROM {table} GROUP BY {key} HAVING COUNT(*) > 1)").fetchone()[0]
        nulls = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE " + " OR ".join(f"{c} IS NULL" for c in cols)).fetchone()[0]
        record("primary_key", f"unique ({key})", table, dup)
        record("primary_key", f"not null ({key})", table, nulls)

    # 2) Foreign keys: every fact row points to an existing dimension row.
    for fact, col, dim, key in FOREIGN_KEYS:
        orphans = conn.execute(f"SELECT COUNT(*) FROM warehouse.{fact} f LEFT JOIN warehouse.{dim} d "
                               f"ON d.{key} = f.{col} WHERE d.{key} IS NULL").fetchone()[0]
        record("referential_integrity", f"{fact}.{col} -> {dim}.{key}", f"warehouse.{fact}", orphans)

    # 3) Reconciliation: row counts match between layers (the difference is the number of failing rows).
    for name, raw_sql, target_sql, target in RECONCILIATION:
        raw_n = conn.execute(raw_sql).fetchone()[0]
        tgt_n = conn.execute(target_sql).fetchone()[0]
        record("reconciliation", f"{name}: source = {target}", target, abs(raw_n - tgt_n), raw_n, tgt_n)

    # 4) Accepted values.
    for table, col, allowed in ACCEPTED_VALUES:
        placeholders = ", ".join("?" * len(allowed))
        bad = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {col} IS NULL OR {col} NOT IN ({placeholders})",
                           allowed).fetchone()[0]
        record("accepted_values", f"{col} in {allowed}", table, bad)

    # 5) Business sanity rules.
    for name, table, sql in SANITY:
        record("business_sanity", name, table, conn.execute(sql).fetchone()[0])

    # Save every result with a timestamp so the history of runs is kept.
    conn.execute("""CREATE TABLE IF NOT EXISTS warehouse.dq_results (
        run_at TEXT, category TEXT, check_name TEXT, table_name TEXT, status TEXT,
        failing_rows INTEGER, expected INTEGER, actual INTEGER, details TEXT)""")
    conn.executemany("INSERT INTO warehouse.dq_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", results)
    conn.commit()
    conn.close()

    # Print a summary per category and every failure.
    failed = [r for r in results if r[4] == "FAIL"]
    by_cat: dict[str, list[int]] = {}
    for r in results:
        by_cat.setdefault(r[1], [0, 0])[0 if r[4] == "PASS" else 1] += 1
    for cat, (ok, bad) in by_cat.items():
        log("dq", f"{cat:<22} pass={ok:<3} fail={bad}")
    for r in failed:
        log("dq", f"FAIL {r[1]} | {r[2]} | {r[3]} | failing={r[5]} expected={r[6]} actual={r[7]}")
    log("dq", f"{len(results) - len(failed)}/{len(results)} checks passed -> warehouse.dq_results")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
