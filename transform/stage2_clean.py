"""Stage 2 - clean and standardise raw tables into the `staging` schema.

Python handles what is awkward in SQL (three date formats, nested JSON, roster
forward-fill, clock-drift detection). Punch mapping, clock correction and the
2-minute de-duplication run in SQL (transform/sql/02_punches.sql) right after.

Every raw row ends up in exactly one place: a staging table or a log/rejected table
(see quality/dq_checks.py reconciliation checks).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline_config import PERIOD_END, PERIOD_START, PLANT_CODES, connect, log, run_sql_file  # noqa: E402

SQL_DIR = Path(__file__).resolve().parent / "sql"
# Order of history records that start on the same date (a hire comes before a transfer, etc.).
REASON_ORDER = {"Hire": 0, "Transfer": 1, "Promotion": 2, "Salary Revision": 3}


# ----------------------------------------------------------------- helpers
def read_raw(conn, table: str) -> pd.DataFrame:
    df = pd.read_sql(f'SELECT * FROM raw."{table}"', conn)
    # Raw stores missing values as empty strings; staging uses real NULLs.
    return df.replace("", np.nan)


def clean_text(s: pd.Series) -> pd.Series:
    # Trim and collapse repeated spaces: '  Weaving   Dept ' -> 'Weaving Dept'.
    return s.str.strip().str.replace(r"\s+", " ", regex=True)


def parse_mixed_date(s: pd.Series) -> pd.Series:
    """YYYY-MM-DD | DD/MM/YYYY | DD-Mon-YYYY -> ISO text. Unknown formats raise."""
    s = s.str.strip()
    # Try each known format in turn; a value is filled by the first format that parses it.
    out = pd.to_datetime(s, format="%Y-%m-%d", errors="coerce")
    out = out.fillna(pd.to_datetime(s, format="%d/%m/%Y", errors="coerce"))
    out = out.fillna(pd.to_datetime(s, format="%d-%b-%Y", errors="coerce"))
    bad = s.notna() & out.isna()
    # Anything that matched no format is an unknown format: stop instead of guessing.
    if bad.any():
        raise ValueError(f"Unparseable dates: {s[bad].unique()[:5]}")
    return out.dt.strftime("%Y-%m-%d")


def sql_type(dtype) -> str:
    if pd.api.types.is_integer_dtype(dtype) or pd.api.types.is_bool_dtype(dtype):
        return "INTEGER"
    if pd.api.types.is_float_dtype(dtype):
        return "REAL"
    return "TEXT"


def write(conn, df: pd.DataFrame, table: str, schema: str = "staging") -> None:
    """Replace schema.table with df. (pandas.to_sql ignores `schema` on sqlite3, so we write it ourselves.)"""
    cols = ", ".join(f'"{c}" {sql_type(t)}' for c, t in df.dtypes.items())
    conn.execute(f'DROP TABLE IF EXISTS {schema}."{table}"')
    conn.execute(f'CREATE TABLE {schema}."{table}" ({cols})')
    clean = df.astype(object).where(df.notna(), None)
    rows = [tuple(v.item() if hasattr(v, "item") else v for v in r) for r in clean.itertuples(index=False)]
    conn.executemany(f'INSERT INTO {schema}."{table}" VALUES ({", ".join("?" * len(df.columns))})', rows)
    conn.commit()
    log("stage2", f"{schema}.{table:<26} {len(df):>7} rows")


# ----------------------------------------------------------------- tables
# Departments: trimmed text, ISO dates, plus the plant code.
def build_departments(conn) -> pd.DataFrame:
    d = read_raw(conn, "departments")
    out = pd.DataFrame({
        "dept_id": clean_text(d.dept_id),
        "dept_name": clean_text(d.dept_name),
        "plant": clean_text(d.plant),
        "cost_center": clean_text(d.cost_center),
        "previous_name": clean_text(d.previous_name),
        "renamed_on": parse_mixed_date(d.renamed_on),
        "_row_hash": d._row_hash,
    })
    out["plant_code"] = out.plant.map(PLANT_CODES)
    write(conn, out, "departments")
    return out


# Employees: clean text and dates, map department text to dept_id, remove duplicates (rule 1).
def build_employees(conn, depts: pd.DataFrame) -> None:
    e = read_raw(conn, "employees")
    for c in ["emp_id", "full_name", "gender", "email", "phone", "plant", "department",
              "designation", "grade", "employment_type", "status"]:
        e[c] = clean_text(e[c])
    e["email"] = e.email.str.lower()
    e["grade"] = e.grade.str.upper()
    for c in ["date_of_birth", "hire_date", "separation_date"]:
        e[c] = parse_mixed_date(e[c])
    e["updated_at"] = pd.to_datetime(e.updated_at.str.strip()).dt.strftime("%Y-%m-%d %H:%M:%S")
    e["annual_leave_entitlement"] = e.annual_leave_entitlement.astype(int)

    # Map the free-text department to a dept_id: normalise case/spaces, then match on
    # (plant, current name) OR (plant, previous name before a rename).
    key = depts.assign(k=depts.dept_name.str.lower())[["plant", "k", "dept_id"]]
    old = depts.dropna(subset=["previous_name"]).assign(k=lambda x: x.previous_name.str.lower())[["plant", "k", "dept_id"]]
    lookup = pd.concat([key.assign(via="current_name"), old.assign(via="previous_name")])
    e["k"] = e.department.str.lower()
    e = e.merge(lookup, on=["plant", "k"], how="left").drop(columns="k")
    if e.dept_id.isna().any():
        raise ValueError(f"Unmapped department text: {e[e.dept_id.isna()].department.unique()}")
    e = e.rename(columns={"department": "department_raw", "via": "dept_matched_via"})
    e = e.merge(depts[["dept_id", "dept_name"]], on="dept_id")

    # Rule 1: same emp_id -> keep latest updated_at, log the dropped rows and what differed.
    e = e.sort_values(["emp_id", "updated_at"], ascending=[True, False])
    if e.duplicated(["emp_id", "updated_at"]).any():
        raise ValueError("Tie on (emp_id, updated_at) - rule 1 cannot pick a winner")
    keep = e.drop_duplicates("emp_id", keep="first")
    dropped = e[e.duplicated("emp_id", keep="first")]
    compare = ["full_name", "gender", "date_of_birth", "email", "phone", "plant", "dept_id", "designation",
               "grade", "employment_type", "hire_date", "separation_date", "status", "annual_leave_entitlement"]
    kept_idx = keep.set_index("emp_id")
    merge_log = []
    # For every dropped duplicate, record which fields differed from the kept row (audit trail).
    for _, row in dropped.iterrows():
        winner = kept_idx.loc[row.emp_id]
        diffs = [f"{c}: '{row[c]}' -> '{winner[c]}'" for c in compare
                 if not (pd.isna(row[c]) and pd.isna(winner[c])) and row[c] != winner[c]]
        merge_log.append({
            "emp_id": row.emp_id,
            "kept_row_hash": winner._row_hash, "kept_updated_at": winner.updated_at,
            "dropped_row_hash": row._row_hash, "dropped_updated_at": row.updated_at,
            "reason": "Duplicate emp_id; kept latest updated_at (rule 1)",
            "differences": "; ".join(diffs) if diffs else "identical except updated_at/formatting",
        })
    write(conn, keep.reset_index(drop=True), "employees")
    write(conn, pd.DataFrame(merge_log), "employee_merge_log")


# Employment history -> clean SCD2 ranges (valid_from / valid_to) with no overlaps or gaps.
def build_employment_history(conn) -> None:
    h = read_raw(conn, "employment_history")
    for c in ["emp_id", "dept_id", "designation", "grade", "change_reason"]:
        h[c] = clean_text(h[c])
    h["effective_from"] = parse_mixed_date(h.effective_from)
    h["effective_to_raw"] = parse_mixed_date(h.effective_to)
    h["basic_salary"] = pd.to_numeric(h.basic_salary)
    h["reason_order"] = h.change_reason.map(REASON_ORDER).fillna(9)
    h = h.sort_values(["emp_id", "effective_from", "reason_order"]).reset_index(drop=True)

    # Two records starting on the same day: the earlier one would cover zero days (rule 2),
    # so it is moved to rejected_employment_history with a reason.
    same_day = h.duplicated(["emp_id", "effective_from"], keep="last")
    rejected = h[same_day].assign(reject_reason="Superseded by a later record starting the same day (rule 2: zero-length range)")
    h = h[~same_day].copy()

    # Rule 2: valid_to = next record's start - 1 day; latest record is open-ended (NULL).
    nxt = h.groupby("emp_id").effective_from.shift(-1)
    h["valid_from"] = h.effective_from
    h["valid_to"] = (pd.to_datetime(nxt) - pd.Timedelta(days=1)).dt.strftime("%Y-%m-%d")
    h["is_current"] = nxt.isna().astype(int)
    exp_to = h.valid_to
    changed = ~((h.effective_to_raw == exp_to) | (h.effective_to_raw.isna() & exp_to.isna()))
    # Explain, per row, how the exported end date was corrected (NULL = it was already right).
    h["effective_to_fix"] = np.where(
        ~changed, None,
        np.where(h.effective_to_raw.isna(), "export had no end date but a later record exists",
                 np.where(exp_to.isna(), "export end date removed: latest record is open-ended",
                          np.where(h.effective_to_raw > exp_to, "overlap with next record fixed",
                                   "gap before next record fixed"))))
    cols = ["emp_id", "valid_from", "valid_to", "is_current", "dept_id", "designation", "grade", "basic_salary",
            "change_reason", "effective_from", "effective_to_raw", "effective_to_fix", "_row_hash"]
    write(conn, h[cols], "employment_history")
    write(conn, rejected[["emp_id", "effective_from", "effective_to_raw", "dept_id", "change_reason",
                          "basic_salary", "reject_reason", "_row_hash"]], "rejected_employment_history")


# Shifts (JSON): unpack each record and compute the shift length in hours.
def build_shifts(conn) -> None:
    s = read_raw(conn, "shifts")
    recs = pd.DataFrame([json.loads(x) for x in s.record_json])
    recs["_row_hash"] = s._row_hash.values
    recs["crosses_midnight"] = recs.crosses_midnight.astype(int)
    start = pd.to_timedelta(recs.start_time + ":00")
    # A NIGHT shift ends the next day, so add one day to its end time.
    end = pd.to_timedelta(recs.end_time + ":00") + pd.to_timedelta(recs.crosses_midnight, unit="D")
    recs["shift_hours"] = (end - start).dt.total_seconds() / 3600
    write(conn, recs[["shift_code", "name", "start_time", "end_time", "crosses_midnight", "grace_minutes",
                      "shift_hours", "applies_to", "_row_hash"]], "shifts")


# Weekly roster -> complete weekly roster -> one row per employee per day (roster_daily).
def build_roster(conn) -> None:
    r = read_raw(conn, "shift_roster")
    r["emp_id"] = clean_text(r.emp_id)
    r["shift_code"] = clean_text(r.shift_code).str.upper()
    r["week_start"] = parse_mixed_date(r.week_start)
    if (pd.to_datetime(r.week_start).dt.day_of_week != 0).any():
        raise ValueError("roster week_start that is not a Monday")
    emps = pd.read_sql("SELECT emp_id, hire_date, separation_date FROM staging.employees", conn)

    # Rule 6: build a grid of every week from each employee's first rostered week to the last week.
    # A week missing from the export copies the previous week's shift (forward-fill), flagged is_imputed = 1.
    weeks = pd.date_range(r.week_start.min(), r.week_start.max(), freq="7D").strftime("%Y-%m-%d")
    first = r.groupby("emp_id").week_start.min()
    grid = pd.MultiIndex.from_product([emps.emp_id, weeks], names=["emp_id", "week_start"]).to_frame(index=False)
    grid = grid.merge(first.rename("first_week"), on="emp_id", how="left")
    grid = grid[grid.week_start >= grid.first_week].drop(columns="first_week")
    full = grid.merge(r[["emp_id", "week_start", "shift_code", "_row_hash"]], on=["emp_id", "week_start"], how="left")
    full["is_imputed"] = full.shift_code.isna().astype(int)
    full["shift_code"] = full.groupby("emp_id").shift_code.ffill()
    write(conn, full, "shift_roster")

    # Daily roster (period +/- 1 day) so punches and attendance can join on a date.
    days = pd.date_range(pd.Timestamp(PERIOD_START) - pd.Timedelta(days=1), pd.Timestamp(PERIOD_END) + pd.Timedelta(days=1))
    daily = pd.DataFrame({"work_date": days})
    daily["week_start"] = (daily.work_date - pd.to_timedelta(daily.work_date.dt.day_of_week, unit="D")).dt.strftime("%Y-%m-%d")
    daily["work_date"] = daily.work_date.dt.strftime("%Y-%m-%d")
    rd = full[["emp_id", "week_start", "shift_code", "is_imputed"]].merge(daily, on="week_start")
    write(conn, rd[["emp_id", "work_date", "week_start", "shift_code", "is_imputed"]], "roster_daily")


# Tables that only need trimming, case fixes and date/number parsing.
def build_simple(conn) -> None:
    dm = read_raw(conn, "device_mapping")
    dm = dm.assign(device_id=clean_text(dm.device_id), device_user_id=clean_text(dm.device_user_id),
                   emp_id=clean_text(dm.emp_id), enrolled_on=parse_mixed_date(dm.enrolled_on))
    write(conn, dm[["device_id", "device_user_id", "emp_id", "enrolled_on", "_row_hash"]], "device_mapping")

    ho = read_raw(conn, "holidays")
    ho = ho.assign(holiday_date=parse_mixed_date(ho.holiday_date), holiday_name=clean_text(ho.holiday_name),
                   scope=clean_text(ho.scope).str.upper())
    write(conn, ho[["holiday_date", "holiday_name", "scope", "_row_hash"]], "holidays")

    ot = read_raw(conn, "overtime_requests")
    ot = ot.assign(request_id=clean_text(ot.request_id), emp_id=clean_text(ot.emp_id),
                   ot_date=parse_mixed_date(ot.ot_date), status=clean_text(ot.status).str.title(),
                   requested_hours=pd.to_numeric(ot.requested_hours), approved_hours=pd.to_numeric(ot.approved_hours),
                   requested_at=pd.to_datetime(ot.requested_at).dt.strftime("%Y-%m-%d %H:%M:%S"))
    write(conn, ot[["request_id", "emp_id", "ot_date", "requested_hours", "approved_hours", "status",
                    "approver_id", "requested_at", "_row_hash"]], "overtime_requests")

    p = read_raw(conn, "payroll_lines")
    p = p.assign(line_id=clean_text(p.line_id), payroll_month=clean_text(p.payroll_month), emp_id=clean_text(p.emp_id),
                 component=clean_text(p.component).str.upper(), component_type=clean_text(p.component_type).str.upper(),
                 units=pd.to_numeric(p.units), amount=pd.to_numeric(p.amount))
    write(conn, p[["line_id", "payroll_month", "emp_id", "component", "component_type", "units", "amount",
                   "_row_hash"]], "payroll_lines")

    a = read_raw(conn, "applications")
    a = a.assign(stage=clean_text(a.stage), stage_date=parse_mixed_date(a.stage_date))
    write(conn, a[["application_id", "candidate_id", "job_req_id", "dept_id", "stage", "stage_date", "_row_hash"]],
          "applications")


# Leave requests (nested JSON) -> one row per request, one row per approval step, one row per leave day.
def build_leave(conn) -> None:
    raw = read_raw(conn, "leave_requests")
    reqs, steps = [], []
    for rh, txt in zip(raw._row_hash, raw.record_json):
        x = json.loads(txt)
        acts = {a["approver_role"]: a["action"] for a in x["approvals"]}
        for a in x["approvals"]:
            steps.append({"request_id": x["request_id"], "step": a["step"], "approver_role": a["approver_role"],
                          "approver_id": a["approver_id"], "action": a["action"], "acted_at": a["acted_at"],
                          "_row_hash": rh})
        mgr, hr, cancelled = acts.get("Manager"), acts.get("HR"), x.get("cancelled_at")
        # Rule 16: a leave counts only if Manager AND HR both approved and it was never cancelled.
        if cancelled:
            reason = "Cancelled"
        elif mgr != "Approved":
            reason = f"Manager {mgr or 'missing'}"
        elif hr != "Approved":
            reason = f"HR {hr or 'pending'}"
        else:
            reason = None
        reqs.append({"request_id": x["request_id"], "emp_id": x["employee"]["emp_id"], "plant": x["employee"]["plant"],
                     "leave_type": x["leave"]["type"].strip().title(), "from_date": x["leave"]["from"],
                     "to_date": x["leave"]["to"], "days_requested": x["leave"]["days_requested"],
                     "submitted_at": x["submitted_at"], "cancelled_at": cancelled,
                     "manager_action": mgr, "hr_action": hr, "is_valid": int(reason is None),
                     "invalid_reason": reason, "_row_hash": rh})
    req = pd.DataFrame(reqs)
    for c in ["from_date", "to_date"]:
        req[c] = parse_mixed_date(req[c])
    for c in ["submitted_at", "cancelled_at"]:
        req[c] = pd.to_datetime(req[c]).dt.strftime("%Y-%m-%d %H:%M:%S")
    st = pd.DataFrame(steps)
    st["acted_at"] = pd.to_datetime(st.acted_at).dt.strftime("%Y-%m-%d %H:%M:%S")
    write(conn, req, "leave_requests")
    write(conn, st, "leave_approvals")

    # Rule 17: every calendar day of a valid request is a leave day, except Sundays and that plant's holidays
    # (so days_requested from the export is ignored).
    hol = pd.read_sql("SELECT holiday_date, scope FROM staging.holidays", conn)
    v = req[req.is_valid == 1]
    days = v.assign(leave_date=[pd.date_range(f, t).strftime("%Y-%m-%d").tolist()
                                for f, t in zip(v.from_date, v.to_date)]).explode("leave_date")
    days["plant_code"] = days.plant.map(PLANT_CODES)
    is_sunday = pd.to_datetime(days.leave_date).dt.day_of_week == 6
    hol_keys = set(zip(hol.holiday_date, hol.scope))
    is_holiday = [(d, "ALL") in hol_keys or (d, p) in hol_keys for d, p in zip(days.leave_date, days.plant_code)]
    days = days[~is_sunday & ~np.array(is_holiday)]
    write(conn, days[["request_id", "emp_id", "leave_date", "leave_type", "plant"]], "leave_days")


def detect_clock_drift(conn) -> None:
    """Rule 11: compare each device's daily median check-in vs shift start with the fleet.

    A device is drifting from day D if, on every day from D onwards, its median
    check-in offset differs from the other devices' median by more than 30 minutes.
    The correction is that difference rounded to the nearest 15 minutes.
    """
    p = pd.read_sql("""
        SELECT m.emp_id, b.device_id, b.punch_time
        FROM raw.biometric_punches b
        JOIN staging.device_mapping m ON m.device_id = TRIM(b.device_id) AND m.device_user_id = TRIM(b.device_user_id)
    """, conn)
    p["t"] = pd.to_datetime(p.punch_time)
    p["work_date"] = p.t.dt.strftime("%Y-%m-%d")
    rd = pd.read_sql("SELECT emp_id, work_date, shift_code FROM staging.roster_daily", conn)
    sh = pd.read_sql("SELECT shift_code, start_time FROM staging.shifts WHERE crosses_midnight = 0", conn)
    # Use only shifts that do not cross midnight (DAY/EVE/GEN): their check-in falls on the same calendar day.
    p = p.merge(rd, on=["emp_id", "work_date"]).merge(sh, on="shift_code")
    # First punch of each employee-day, and how many minutes after the shift start it was.
    first = p.groupby(["emp_id", "work_date"]).agg(t=("t", "min"), device_id=("device_id", "first"),
                                                     start_time=("start_time", "first")).reset_index()
    first["delta_min"] = (first.t - pd.to_datetime(first.work_date + " " + first.start_time)).dt.total_seconds() / 60
    first = first[first.delta_min.abs() < 240]  # ignore Sunday/OT oddities far from shift start
    daily = first.groupby(["device_id", "work_date"]).delta_min.agg(["median", "size"]).reset_index()
    daily = daily[daily["size"] >= 20]

    findings = []
    # Compare each device's daily median with the median of ALL OTHER devices on the same day.
    for dev in sorted(daily.device_id.unique()):
        mine = daily[daily.device_id == dev].set_index("work_date")["median"]
        fleet = first[first.device_id != dev].groupby("work_date").delta_min.median().reindex(mine.index)
        diff = (mine - fleet).sort_index()
        off = diff.abs() > 30
        if not off.any():
            continue
        # Find the first day from which EVERY later day is off (a drift that started and never stopped).
        # Reversed cumulative-min turns 'off' into 'off from here to the end'.
        tail_ok = off[::-1].cummin()[::-1]
        if not tail_ok.any():
            continue
        start_day = tail_ok[tail_ok].index.min()
        # The correction = typical difference since the drift started, rounded to 15 minutes (here +60).
        offset = int(round(diff[diff.index >= start_day].median() / 15) * 15)
        findings.append({
            "device_id": dev, "drift_from": f"{start_day} 00:00:00", "drift_to": None,
            "offset_minutes": offset,
            "baseline_median_before": round(float(diff[diff.index < start_day].median()), 1),
            "median_diff_after": round(float(diff[diff.index >= start_day].median()), 1),
            "days_affected": int((diff.index >= start_day).sum()),
            "method": "daily median(first punch - rostered shift start) vs other devices, DAY/EVE/GEN shifts",
        })
    out = pd.DataFrame(findings, columns=["device_id", "drift_from", "drift_to", "offset_minutes",
                                          "baseline_median_before", "median_diff_after", "days_affected", "method"])
    write(conn, out, "device_clock_corrections")
    for f in findings:
        log("stage2", f"clock drift: {f['device_id']} {f['offset_minutes']:+d} min from {f['drift_from']} "
                      f"(median diff {f['median_diff_after']} vs {f['baseline_median_before']} before)")


def main() -> None:
    conn = connect()
    depts = build_departments(conn)
    build_employees(conn, depts)
    build_employment_history(conn)
    build_shifts(conn)
    build_simple(conn)
    build_roster(conn)
    build_leave(conn)
    detect_clock_drift(conn)
    conn.commit()
    # Punch mapping, clock correction, de-duplication and night-shift dating run in SQL.
    run_sql_file(conn, SQL_DIR / "02_punches.sql")
    for t in ["punches", "rejected_punches"]:
        log("stage2", f"staging.{t:<24} {conn.execute(f'SELECT COUNT(*) FROM staging.{t}').fetchone()[0]:>7} rows")
    conn.close()


if __name__ == "__main__":
    main()
