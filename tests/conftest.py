"""Shared test helpers.

The tests never need the real data files: each test builds a tiny in-memory database
with only the rows it needs, then runs the SAME SQL files and Python functions the
pipeline uses. So they run anywhere in a second, including GitHub Actions.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
# Make the pipeline modules importable: pipeline_config, stage2_clean, load_raw.
for folder in (ROOT, ROOT / "transform", ROOT / "ingestion"):
    sys.path.insert(0, str(folder))


@pytest.fixture
def conn() -> sqlite3.Connection:
    """An empty database with in-memory `raw` and `staging` schemas, like pipeline_config.connect()."""
    c = sqlite3.connect(":memory:")
    c.execute("ATTACH DATABASE ':memory:' AS raw")
    c.execute("ATTACH DATABASE ':memory:' AS staging")
    yield c
    c.close()


def run_sql(conn: sqlite3.Connection, relative_path: str) -> None:
    """Run one of the pipeline's own SQL files."""
    conn.executescript((ROOT / relative_path).read_text(encoding="utf-8"))
