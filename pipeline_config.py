"""Shared configuration and database helper for every pipeline stage.

The warehouse runs on SQLite (allowed by the brief). Three database files are
ATTACHed to one connection as `raw`, `staging` and `warehouse`, so every query
uses schema-qualified names (`staging.attendance_daily`) exactly like PostgreSQL.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

# Folder locations. RAW_DATA_DIR / DB_DIR can be overridden with environment variables
# (used to test an incremental load in a temporary copy).
ROOT = Path(__file__).resolve().parent
RAW_DIR = Path(os.environ.get("RAW_DATA_DIR", ROOT / "data" / "raw"))
DB_DIR = Path(os.environ.get("DB_DIR", ROOT / "db"))
RESULTS_DIR = ROOT / "analytics" / "results"

# Reporting period of the export (data_dictionary.md header).
PERIOD_START = "2026-04-01"
PERIOD_END = os.environ.get("PERIOD_END", "2026-09-30")
OPEN_END_DATE = "9999-12-31"  # valid_to of the current SCD2 row

SCHEMAS = ("raw", "staging", "warehouse")

# Plant name in the HR files -> short code used by holidays.csv `scope`.
PLANT_CODES = {
    "Head Office": "HO",
    "Korangi Plant": "KOR",
    "SITE Plant": "SITE",
    "Faisalabad Plant": "FSD",
}


def connect() -> sqlite3.Connection:
    """Open an in-memory main DB with raw/staging/warehouse attached."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    # An empty in-memory main database; the three real databases are attached to it.
    conn = sqlite3.connect(":memory:")
    for schema in SCHEMAS:
        conn.execute(f"ATTACH DATABASE ? AS {schema}", (str(DB_DIR / f"{schema}.db"),))
    # SQLite only enforces foreign keys when this is switched on for each new connection.
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def run_sql_file(conn: sqlite3.Connection, path: Path) -> None:
    # Run a whole .sql file (many statements) and save the changes.
    conn.executescript(path.read_text(encoding="utf-8"))
    conn.commit()


def log(stage: str, message: str) -> None:
    print(f"[{stage}] {message}", flush=True)
