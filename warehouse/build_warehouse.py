"""Stage 4 - create the star schema (ddl/) and load it from staging (load_warehouse.sql)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline_config import connect, log, run_sql_file  # noqa: E402

HERE = Path(__file__).resolve().parent
TABLES = ["dim_date", "dim_department", "dim_shift", "dim_employee",
          "fact_attendance_daily", "fact_leave_day", "fact_overtime_approved", "fact_payroll_line"]


def main() -> None:
    conn = connect()
    for ddl in sorted((HERE / "ddl").glob("*.sql")):
        run_sql_file(conn, ddl)
    run_sql_file(conn, HERE / "load_warehouse.sql")
    for t in TABLES:
        log("stage4", f"warehouse.{t:<24} {conn.execute(f'SELECT COUNT(*) FROM warehouse.{t}').fetchone()[0]:>7} rows")
    violations = conn.execute("PRAGMA warehouse.foreign_key_check").fetchall()
    log("stage4", f"foreign_key_check violations: {len(violations)}")
    conn.close()
    if violations:
        raise SystemExit(f"FK violations in warehouse: {violations[:5]}")


if __name__ == "__main__":
    main()
