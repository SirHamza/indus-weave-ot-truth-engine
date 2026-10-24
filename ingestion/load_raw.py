"""Stage 1 - load every export into the `raw` schema exactly as delivered.

* Every column is TEXT; nothing is trimmed, parsed or flattened.
* JSON files get one row per top-level array element, stored as the original JSON text.
* Metadata per row: _source_file, _loaded_at, _row_hash.
* Idempotent: _row_hash is the PRIMARY KEY and rows are inserted with INSERT OR IGNORE,
  so a re-run (or an incremental file that repeats old rows) never creates duplicates.
* raw._load_log records file rows vs table rows for every load.

Usage:
    python ingestion/load_raw.py                       # full load of data/raw
    python ingestion/load_raw.py --file new.csv --table biometric_punches   # incremental
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline_config import RAW_DIR, connect, log  # noqa: E402

CSV_FILES = {
    "employees.csv": "employees",
    "employment_history.csv": "employment_history",
    "departments.csv": "departments",
    "shift_roster.csv": "shift_roster",
    "device_mapping.csv": "device_mapping",
    "biometric_punches.csv": "biometric_punches",
    "holidays.csv": "holidays",
    "overtime_requests.csv": "overtime_requests",
    "payroll_lines.csv": "payroll_lines",
    "applications.csv": "applications",
}
# JSON file -> (table, key holding the array; None = file itself is the array)
JSON_FILES = {
    "leave_requests.json": ("leave_requests", None),
    "shifts.json": ("shifts", "shifts"),
}
META_COLS = ["_source_file", "_loaded_at", "_row_hash"]


def row_hash(values: list[str]) -> str:
    # Unit separator se join karte hain taake "a,b"+"c" aur "a"+"b,c" ka hash alag ho.
    return hashlib.sha256("\x1f".join(values).encode("utf-8")).hexdigest()


def ensure_table(conn, table: str, columns: list[str]) -> None:
    cols = ", ".join(f'"{c}" TEXT' for c in columns)
    conn.execute(
        f'CREATE TABLE IF NOT EXISTS raw."{table}" ({cols}, '
        f"_source_file TEXT NOT NULL, _loaded_at TEXT NOT NULL, _row_hash TEXT PRIMARY KEY)"
    )
    existing = [r[1] for r in conn.execute(f'PRAGMA raw.table_info("{table}")')]
    missing = [c for c in columns if c not in existing]
    if missing:
        raise ValueError(f"raw.{table}: file has columns not in table: {missing}")


def read_csv_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        return header, [r for r in reader if r]


def read_json_rows(path: Path, array_key: str | None) -> tuple[list[str], list[list[str]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data[array_key] if array_key else data
    # Raw layer mein JSON ko flatten nahi karte; har element apni asal JSON text ke sath.
    return ["record_json"], [[json.dumps(item, ensure_ascii=False, sort_keys=True)] for item in items]


def load_file(conn, path: Path, table: str, header: list[str], rows: list[list[str]], loaded_at: str) -> dict:
    ensure_table(conn, table, header)
    before = conn.execute(f'SELECT COUNT(*) FROM raw."{table}"').fetchone()[0]
    col_list = ", ".join(f'"{c}"' for c in header + META_COLS)
    placeholders = ", ".join("?" * (len(header) + 3))
    payload = [r + [path.name, loaded_at, row_hash(r)] for r in rows]
    conn.executemany(f'INSERT OR IGNORE INTO raw."{table}" ({col_list}) VALUES ({placeholders})', payload)
    after = conn.execute(f'SELECT COUNT(*) FROM raw."{table}"').fetchone()[0]
    from_file = conn.execute(f'SELECT COUNT(*) FROM raw."{table}" WHERE _source_file = ?', (path.name,)).fetchone()[0]
    entry = {
        "source_file": path.name, "table_name": f"raw.{table}", "file_rows": len(rows),
        "inserted": after - before, "already_loaded": len(rows) - (after - before),
        "table_rows_from_file": from_file, "table_rows_total": after,
        "status": "MATCH" if from_file == len({p[-1] for p in payload}) else "MISMATCH",
        "loaded_at": loaded_at,
    }
    conn.execute(
        "INSERT INTO raw._load_log VALUES (:loaded_at, :source_file, :table_name, :file_rows, :inserted,"
        " :already_loaded, :table_rows_from_file, :table_rows_total, :status)", entry)
    return entry


def main(argv: list[str] | None = None) -> list[dict]:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    ap.add_argument("--file", type=Path, help="incremental: one extra file to append")
    ap.add_argument("--table", help="incremental: target raw table for --file")
    args = ap.parse_args(argv)

    conn = connect()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS raw._load_log (loaded_at TEXT, source_file TEXT, table_name TEXT,"
        " file_rows INTEGER, inserted INTEGER, already_loaded INTEGER, table_rows_from_file INTEGER,"
        " table_rows_total INTEGER, status TEXT)")
    loaded_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    if args.file:
        if not args.table:
            ap.error("--table is required with --file")
        jobs = [(args.file, args.table, None)]
    else:
        jobs = [(args.raw_dir / f, t, None) for f, t in CSV_FILES.items()]
        jobs += [(args.raw_dir / f, t, key) for f, (t, key) in JSON_FILES.items()]

    results = []
    for path, table, json_key in jobs:
        if not path.exists():
            raise FileNotFoundError(f"Missing raw file: {path}. Unzip indus_weave_hcm_data.zip into {args.raw_dir}")
        if path.suffix == ".json":
            header, rows = read_json_rows(path, json_key)
        else:
            header, rows = read_csv_rows(path)
        entry = load_file(conn, path, table, header, rows, loaded_at)
        results.append(entry)
        log("ingest", f"{entry['source_file']:<26} file={entry['file_rows']:>7}  new={entry['inserted']:>7}  "
                      f"table={entry['table_rows_from_file']:>7}  {entry['status']}")
    conn.commit()
    conn.close()
    if any(r["status"] != "MATCH" for r in results):
        raise SystemExit("Row-count mismatch between file and raw table - see raw._load_log")
    return results


if __name__ == "__main__":
    main()
