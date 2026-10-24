"""Stage 3 - build staging.attendance_daily (logic lives in transform/sql/03_attendance_daily.sql)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline_config import PERIOD_END, PERIOD_START, connect, log, run_sql_file  # noqa: E402

SQL = Path(__file__).resolve().parent / "sql" / "03_attendance_daily.sql"


def main() -> None:
    conn = connect()
    conn.executescript("DROP TABLE IF EXISTS staging.pipeline_params;"
                       "CREATE TABLE staging.pipeline_params (period_start TEXT NOT NULL, period_end TEXT NOT NULL);")
    conn.execute("INSERT INTO staging.pipeline_params VALUES (?, ?)", (PERIOD_START, PERIOD_END))
    conn.commit()
    run_sql_file(conn, SQL)
    for status, n in conn.execute("SELECT status, COUNT(*) FROM staging.attendance_daily GROUP BY 1 ORDER BY 2 DESC"):
        log("stage3", f"attendance_daily {status:<14} {n:>7}")
    conn.close()


if __name__ == "__main__":
    main()
