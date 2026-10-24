"""Bonus - run bonus_recruitment_funnel.sql and save analytics/results/bonus_recruitment_funnel.csv."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline_config import RESULTS_DIR, connect, log  # noqa: E402

SQL = Path(__file__).resolve().parent / "bonus_recruitment_funnel.sql"


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    conn = connect()
    cur = conn.execute(SQL.read_text(encoding="utf-8"))
    header, rows = [c[0] for c in cur.description], cur.fetchall()
    with (RESULTS_DIR / "bonus_recruitment_funnel.csv").open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows([header, *rows])
    for r in rows:
        log("funnel", " | ".join(str(v) for v in r))
    conn.close()


if __name__ == "__main__":
    main()
