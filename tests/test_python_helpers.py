"""Unit tests for the Python cleaning helpers and the idempotent raw load."""
from __future__ import annotations

import pandas as pd
import pytest

import load_raw
import stage2_clean


def test_parse_mixed_date_accepts_all_three_formats():
    raw = pd.Series(["2026-04-01", "01/04/2026", "01-Apr-2026", " 15/09/2026 "])
    assert stage2_clean.parse_mixed_date(raw).tolist() == ["2026-04-01", "2026-04-01", "2026-04-01", "2026-09-15"]


def test_parse_mixed_date_keeps_missing_values_missing():
    out = stage2_clean.parse_mixed_date(pd.Series(["2026-04-01", None]))
    assert out.iloc[0] == "2026-04-01" and pd.isna(out.iloc[1])


def test_parse_mixed_date_fails_loudly_on_unknown_format():
    with pytest.raises(ValueError, match="Unparseable"):
        stage2_clean.parse_mixed_date(pd.Series(["April 1st 2026"]))


def test_clean_text_trims_and_collapses_spaces():
    assert stage2_clean.clean_text(pd.Series(["  Weaving   Dept "])).tolist() == ["Weaving Dept"]


def test_row_hash_is_stable_and_separator_safe():
    assert load_raw.row_hash(["E1", "2026-04-01"]) == load_raw.row_hash(["E1", "2026-04-01"])
    # Moving a comma between fields must give a different hash.
    assert load_raw.row_hash(["a,b", "c"]) != load_raw.row_hash(["a", "b,c"])


def test_raw_load_is_idempotent(conn, tmp_path):
    """Loading the same file twice must not create duplicate rows (brief, Stage 1)."""
    conn.execute("CREATE TABLE raw._load_log (loaded_at TEXT, source_file TEXT, table_name TEXT, file_rows INTEGER,"
                 " inserted INTEGER, already_loaded INTEGER, table_rows_from_file INTEGER,"
                 " table_rows_total INTEGER, status TEXT)")
    path = tmp_path / "holidays.csv"
    path.write_text("holiday_date,holiday_name,scope\n2026-05-01,Labour Day,ALL\n2026-08-14,Independence Day,ALL\n",
                    encoding="utf-8")
    header, rows = load_raw.read_csv_rows(path)

    first = load_raw.load_file(conn, path, "holidays", header, rows, "2026-10-01 00:00:00")
    second = load_raw.load_file(conn, path, "holidays", header, rows, "2026-10-02 00:00:00")

    assert (first["inserted"], first["status"]) == (2, "MATCH")
    assert (second["inserted"], second["already_loaded"], second["table_rows_total"]) == (0, 2, 2)
    # Every column is kept as text, exactly as delivered.
    assert conn.execute("SELECT typeof(holiday_date) FROM raw.holidays LIMIT 1").fetchone()[0] == "text"
