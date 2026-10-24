"""Stage 5 - run analytics/q*.sql against the warehouse and save each result to analytics/results/<name>.csv."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline_config import RESULTS_DIR, connect, log  # noqa: E402

HERE = Path(__file__).resolve().parent


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    conn = connect()
    for sql_file in sorted(HERE.glob("q*.sql")):
        cur = conn.execute(sql_file.read_text(encoding="utf-8"))
        header = [c[0] for c in cur.description]
        rows = cur.fetchall()
        out = RESULTS_DIR / f"{sql_file.stem}.csv"
        with out.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(header)
            writer.writerows(rows)
        log("stage5", f"{sql_file.stem:<40} {len(rows):>5} rows -> {out.relative_to(HERE.parent)}")
    conn.close()


if __name__ == "__main__":
    main()
