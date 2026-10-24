"""Unit tests for the business rules in the pipeline's SQL files.

Each test loads a handful of hand-made rows, runs the real SQL file, and checks the
result against the rule in data_dictionary.md. Dates: 2026-04-05 is a Sunday,
2026-04-06 a Monday.
"""
from __future__ import annotations

import pytest

from conftest import run_sql

SHIFTS = [("DAY", "06:00", "14:00", 0, 10), ("EVE", "14:00", "22:00", 0, 10),
          ("NIGHT", "22:00", "06:00", 1, 10), ("GEN", "09:00", "17:00", 0, 10)]


# ----------------------------------------------------------------- punches (02_punches.sql)
def build_punch_inputs(conn, punches, mapping, roster, corrections=()):
    conn.execute("CREATE TABLE raw.biometric_punches (punch_id, device_id, device_user_id, punch_time, _row_hash)")
    conn.execute("CREATE TABLE staging.device_mapping (device_id, device_user_id, emp_id)")
    conn.execute("CREATE TABLE staging.device_clock_corrections (device_id, drift_from, drift_to, offset_minutes)")
    conn.execute("CREATE TABLE staging.roster_daily (emp_id, work_date, shift_code)")
    conn.executemany("INSERT INTO raw.biometric_punches VALUES (?, ?, ?, ?, ?)", [p + (p[0],) for p in punches])
    conn.executemany("INSERT INTO staging.device_mapping VALUES (?, ?, ?)", mapping)
    conn.executemany("INSERT INTO staging.device_clock_corrections VALUES (?, ?, ?, ?)", corrections)
    conn.executemany("INSERT INTO staging.roster_daily VALUES (?, ?, ?)", roster)
    run_sql(conn, "transform/sql/02_punches.sql")


def kept(conn):
    return {r[0]: r[1:] for r in conn.execute("SELECT punch_id, punch_time, shift_date FROM staging.punches")}


def rejected(conn):
    return dict(conn.execute("SELECT punch_id, reject_reason FROM staging.rejected_punches"))


def test_punch_within_two_minutes_is_a_duplicate(conn):
    build_punch_inputs(conn,
                       punches=[("P1", "DEV-A", "U1", "2026-04-06 06:35:41"),
                                ("P2", "DEV-A", "U1", "2026-04-06 06:36:30"),   # 49 s later
                                ("P3", "DEV-A", "U1", "2026-04-06 15:06:08")],
                       mapping=[("DEV-A", "U1", "E1")], roster=[("E1", "2026-04-06", "DAY")])
    assert set(kept(conn)) == {"P1", "P3"}
    assert rejected(conn) == {"P2": "DUPLICATE_WITHIN_2_MIN"}


def test_punch_from_unmapped_device_user_is_rejected_not_lost(conn):
    build_punch_inputs(conn, punches=[("P1", "DEV-A", "U99", "2026-04-06 06:01:00")],
                       mapping=[("DEV-A", "U1", "E1")], roster=[])
    assert kept(conn) == {}
    assert rejected(conn) == {"P1": "UNMAPPED_DEVICE_USER"}


def test_clock_offset_is_subtracted_only_from_the_drift_date(conn):
    build_punch_inputs(conn,
                       punches=[("P1", "DEV-B", "U2", "2026-06-30 06:02:00"),   # before the drift: unchanged
                                ("P2", "DEV-B", "U2", "2026-07-01 07:02:00")],  # +60 min clock: corrected
                       mapping=[("DEV-B", "U2", "E2")],
                       roster=[("E2", "2026-06-30", "DAY"), ("E2", "2026-07-01", "DAY")],
                       corrections=[("DEV-B", "2026-07-01 00:00:00", None, 60)])
    assert kept(conn)["P1"][0] == "2026-06-30 06:02:00"
    assert kept(conn)["P2"][0] == "2026-07-01 06:02:00"


def test_night_shift_check_out_belongs_to_the_start_date(conn):
    build_punch_inputs(conn,
                       punches=[("P1", "DEV-A", "U3", "2026-04-06 21:58:00"),
                                ("P2", "DEV-A", "U3", "2026-04-07 06:03:00")],
                       mapping=[("DEV-A", "U3", "E3")],
                       roster=[("E3", "2026-04-06", "NIGHT"), ("E3", "2026-04-07", "NIGHT")])
    assert kept(conn)["P1"][1] == "2026-04-06"
    assert kept(conn)["P2"][1] == "2026-04-06"   # 06:03 next morning = check-out of the 6 Apr night shift


def test_morning_punch_is_todays_check_in_when_roster_switches_to_day(conn):
    build_punch_inputs(conn, punches=[("P1", "DEV-A", "U3", "2026-04-13 05:55:00")],
                       mapping=[("DEV-A", "U3", "E3")],
                       roster=[("E3", "2026-04-12", "NIGHT"), ("E3", "2026-04-13", "DAY")])
    assert kept(conn)["P1"][1] == "2026-04-13"


# ----------------------------------------------------------------- attendance (03_attendance_daily.sql)
def build_attendance(conn, punches, roster_shift="DAY", holidays=(), leave_days=(),
                     period=("2026-04-05", "2026-04-08")):
    conn.executescript("""
        CREATE TABLE staging.pipeline_params (period_start, period_end);
        CREATE TABLE staging.employees (emp_id, dept_id, hire_date, separation_date);
        CREATE TABLE staging.departments (dept_id, plant, plant_code);
        CREATE TABLE staging.employment_history (emp_id, valid_from, valid_to, dept_id);
        CREATE TABLE staging.shifts (shift_code, start_time, end_time, crosses_midnight, grace_minutes);
        CREATE TABLE staging.roster_daily (emp_id, work_date, shift_code, is_imputed);
        CREATE TABLE staging.punches (emp_id, shift_date, punch_time);
        CREATE TABLE staging.holidays (holiday_date, scope, holiday_name);
        CREATE TABLE staging.leave_days (emp_id, leave_date, request_id, leave_type);
    """)
    conn.execute("INSERT INTO staging.pipeline_params VALUES (?, ?)", period)
    conn.execute("INSERT INTO staging.employees VALUES ('E1', 'D01', '2020-01-01', NULL)")
    conn.execute("INSERT INTO staging.departments VALUES ('D01', 'Faisalabad Plant', 'FSD')")
    conn.execute("INSERT INTO staging.employment_history VALUES ('E1', '2020-01-01', NULL, 'D01')")
    conn.executemany("INSERT INTO staging.shifts VALUES (?, ?, ?, ?, ?)", SHIFTS)
    days = [r[0] for r in conn.execute(
        "WITH RECURSIVE d(x) AS (SELECT ? UNION ALL SELECT date(x, '+1 day') FROM d WHERE x < ?) SELECT x FROM d",
        period)]
    conn.executemany("INSERT INTO staging.roster_daily VALUES ('E1', ?, ?, 0)", [(d, roster_shift) for d in days])
    conn.executemany("INSERT INTO staging.punches VALUES ('E1', ?, ?)", [(t[:10], t) for t in punches])
    conn.executemany("INSERT INTO staging.holidays VALUES (?, ?, ?)", holidays)
    conn.executemany("INSERT INTO staging.leave_days VALUES ('E1', ?, ?, ?)", leave_days)
    run_sql(conn, "transform/sql/03_attendance_daily.sql")


def day(conn, work_date):
    cur = conn.execute("SELECT * FROM staging.attendance_daily WHERE work_date = ?", (work_date,))
    return dict(zip([c[0] for c in cur.description], cur.fetchone()))


def test_worked_example_late_and_overtime(conn):
    """docs/HOW_IT_WORKS.md section 11: E10580 on 4 Apr, punches 06:35:41 and 15:06:08 on a DAY shift."""
    build_attendance(conn, punches=["2026-04-06 06:35:41", "2026-04-06 15:06:08"])
    d = day(conn, "2026-04-06")
    assert d["status"] == "Present"
    assert (d["is_late"], d["late_minutes"]) == (1, 35.7)
    assert d["is_early_departure"] == 0
    assert d["worked_hours"] == 8.51
    assert d["ot_hours"] == 1.0          # 66 min after 14:00 -> 2 whole half-hours


@pytest.mark.parametrize("check_out, expected_ot", [
    ("2026-04-06 14:29:59", 0.0),        # 29 min 59 s: not a full half-hour
    ("2026-04-06 14:30:00", 0.5),
    ("2026-04-06 14:59:59", 0.5),        # rounded DOWN, never up
    ("2026-04-06 15:00:00", 1.0),
])
def test_overtime_is_rounded_down_to_whole_half_hours(conn, check_out, expected_ot):
    build_attendance(conn, punches=["2026-04-06 05:58:00", check_out])
    assert day(conn, "2026-04-06")["ot_hours"] == expected_ot


def test_check_in_inside_grace_period_is_not_late(conn):
    build_attendance(conn, punches=["2026-04-06 06:10:00", "2026-04-06 14:00:00"])
    d = day(conn, "2026-04-06")
    assert (d["is_late"], d["late_minutes"]) == (0, 0)


def test_status_for_each_kind_of_day(conn):
    build_attendance(conn,
                     punches=["2026-04-06 06:00:00", "2026-04-06 14:00:00",   # Mon: 2 punches
                              "2026-04-07 06:02:00"],                         # Tue: 1 punch
                     holidays=[("2026-04-08", "ALL", "Test Holiday")])
    assert day(conn, "2026-04-05")["status"] == "Weekly Off"     # Sunday, no punches
    assert day(conn, "2026-04-06")["status"] == "Present"
    assert day(conn, "2026-04-07")["status"] == "Missing Punch"
    assert day(conn, "2026-04-08")["status"] == "Holiday"


def test_approved_leave_wins_over_absent(conn):
    build_attendance(conn, punches=[], leave_days=[("2026-04-07", "LR1", "Annual")])
    assert day(conn, "2026-04-06")["status"] == "Absent"         # working day, no punches, no leave
    assert day(conn, "2026-04-07")["status"] == "On Leave"


def test_all_work_on_a_sunday_is_overtime(conn):
    build_attendance(conn, punches=["2026-04-05 06:00:00", "2026-04-05 10:15:00"])
    d = day(conn, "2026-04-05")
    assert d["status"] == "Present" and d["is_working_day"] == 0
    assert d["ot_hours"] == 4.0          # 4 h 15 min worked -> 8 whole half-hours
    assert d["is_late"] == 0             # late is only counted on working days
