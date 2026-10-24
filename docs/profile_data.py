"""Reusable data profiler for the Indus Weave HCM export.

Usage:  python docs/profile_data.py [--raw data/raw] [--out docs/PROFILE.md]

Read-only: never modifies data/raw. Produces a markdown report with generic
profiling (rows / nulls / distinct / value_counts / date formats / duplicate keys)
plus targeted detection of every planted data issue.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PERIOD_START, PERIOD_END = pd.Timestamp("2026-04-01"), pd.Timestamp("2026-09-30")
SHIFT_START_H = {"DAY": 6.0, "EVE": 14.0, "NIGHT": 22.0, "GEN": 9.0}

CSV_FILES = {
    "employees.csv": ["emp_id"],
    "employment_history.csv": ["emp_id", "effective_from"],
    "departments.csv": ["dept_id"],
    "shift_roster.csv": ["emp_id", "week_start"],
    "device_mapping.csv": ["device_id", "device_user_id"],
    "biometric_punches.csv": ["punch_id"],
    "holidays.csv": ["holiday_date", "scope"],
    "overtime_requests.csv": ["request_id"],
    "payroll_lines.csv": ["line_id"],
    "applications.csv": ["application_id", "stage"],
}
CATEGORICAL = {
    "employees.csv": ["plant", "department", "status", "employment_type", "grade", "gender",
                      "annual_leave_entitlement"],
    "employment_history.csv": ["change_reason", "dept_id", "grade"],
    "departments.csv": ["plant"],
    "shift_roster.csv": ["shift_code"],
    "device_mapping.csv": ["device_id"],
    "biometric_punches.csv": ["device_id"],
    "holidays.csv": ["scope"],
    "overtime_requests.csv": ["status", "requested_hours", "approved_hours"],
    "payroll_lines.csv": ["payroll_month", "component", "component_type"],
    "applications.csv": ["stage"],
}
DATE_COLS = {
    "employees.csv": ["date_of_birth", "hire_date", "separation_date", "updated_at"],
    "employment_history.csv": ["effective_from", "effective_to"],
    "departments.csv": ["renamed_on"],
    "shift_roster.csv": ["week_start"],
    "device_mapping.csv": ["enrolled_on"],
    "biometric_punches.csv": ["punch_time"],
    "holidays.csv": ["holiday_date"],
    "overtime_requests.csv": ["ot_date", "requested_at"],
    "applications.csv": ["stage_date"],
}
PATTERNS = [
    (r"^\d{4}-\d{2}-\d{2}$", "YYYY-MM-DD"),
    (r"^\d{2}/\d{2}/\d{4}$", "DD/MM/YYYY"),
    (r"^\d{2}-[A-Za-z]{3}-\d{4}$", "DD-Mon-YYYY"),
    (r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", "YYYY-MM-DD HH:MM:SS"),
    (r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", "YYYY-MM-DD HH:MM"),
    (r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$", "ISO YYYY-MM-DDTHH:MM[:SS]"),
]


# ---------------------------------------------------------------- helpers
def md_table(df: pd.DataFrame, max_rows: int = 60) -> str:
    df = df.head(max_rows)
    cols = [str(c) for c in df.columns]
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in df.itertuples(index=False):
        out.append("| " + " | ".join("" if pd.isna(v) else str(v) for v in row) + " |")
    return "\n".join(out)


def pattern_of(v: str) -> str:
    for rx, name in PATTERNS:
        if re.match(rx, v):
            return name
    return f"OTHER({v[:20]})"


def parse_mixed_date(s: pd.Series) -> pd.Series:
    """YYYY-MM-DD, DD/MM/YYYY, DD-Mon-YYYY -> Timestamp (NaT for blank)."""
    out = pd.to_datetime(s, format="%Y-%m-%d", errors="coerce")
    out = out.fillna(pd.to_datetime(s, format="%d/%m/%Y", errors="coerce"))
    out = out.fillna(pd.to_datetime(s, format="%d-%b-%Y", errors="coerce"))
    return out


def norm_dept(s: pd.Series) -> pd.Series:
    return s.fillna("").str.strip().str.replace(r"\s+", " ", regex=True).str.lower()


def load(raw: Path) -> dict[str, pd.DataFrame]:
    d = {f: pd.read_csv(raw / f, dtype=str, keep_default_na=False) for f in CSV_FILES}
    for df in d.values():
        df.replace("", np.nan, inplace=True)
    return d


# ---------------------------------------------------------------- generic
def generic_section(dfs, leave, shifts) -> list[str]:
    L = ["## 1. Generic profile\n"]
    summary = []
    for f, df in dfs.items():
        key = CSV_FILES[f]
        summary.append({"file": f, "rows": len(df), "cols": df.shape[1],
                        "key": "+".join(key), "dup_key_rows": int(df.duplicated(key).sum())})
    summary.append({"file": "leave_requests.json", "rows": len(leave), "cols": "nested",
                    "key": "request_id",
                    "dup_key_rows": len(leave) - len({r["request_id"] for r in leave})})
    summary.append({"file": "shifts.json", "rows": len(shifts), "cols": "nested",
                    "key": "shift_code", "dup_key_rows": 0})
    L += [md_table(pd.DataFrame(summary)), ""]
    for f, df in dfs.items():
        L.append(f"### {f}\n")
        prof = pd.DataFrame({"column": df.columns,
                             "nulls": df.isna().sum().values,
                             "distinct": df.nunique().values,
                             "example": [df[c].dropna().iloc[0] if df[c].notna().any() else "" for c in df.columns]})
        L += [md_table(prof), ""]
        for c in DATE_COLS.get(f, []):
            vc = df[c].dropna().map(pattern_of).value_counts()
            L.append(f"- date patterns `{c}`: " + ", ".join(f"{k}={v}" for k, v in vc.items())
                     + f"; min={df[c].dropna().min()} max={df[c].dropna().max()}")
        for c in CATEGORICAL.get(f, []):
            vc = df[c].value_counts(dropna=False)
            txt = ", ".join(f"`{k}`={v}" for k, v in vc.head(40).items())
            more = f" ... (+{len(vc) - 40} more)" if len(vc) > 40 else ""
            L.append(f"- value_counts `{c}` ({len(vc)} distinct): {txt}{more}")
        L.append("")
    return L


# ---------------------------------------------------------------- targeted
def issues_section(dfs, leave, shifts) -> tuple[list[str], dict]:
    L = ["## 2. Planted issues - detection and quantification\n"]
    found: dict = {}
    emp, hist, dept = dfs["employees.csv"], dfs["employment_history.csv"], dfs["departments.csv"]

    # 2.1 employee duplicates
    dup_rows = int(emp.duplicated("emp_id").sum())
    dup_ids = int(emp.emp_id.duplicated(keep=False).groupby(emp.emp_id).any().sum())
    e2 = emp.copy()
    e2["upd"] = pd.to_datetime(e2.updated_at)
    ties = int(e2.groupby("emp_id").upd.apply(lambda s: (s == s.max()).sum() > 1).sum())
    found["emp_dup_rows"] = dup_rows
    L += ["### 2.1 Employee duplicates (rule 1)",
          f"- {len(emp)} rows, {emp.emp_id.nunique()} distinct emp_id; **{dup_rows} duplicate rows** "
          f"across **{dup_ids} emp_ids**; ties on max(updated_at): {ties}.", ""]

    # 2.2 department name variants
    dept_n = dept.assign(k=norm_dept(dept.dept_name))
    prev = dept[dept.previous_name.notna()].assign(k=norm_dept(dept.previous_name.dropna()))
    lookup = pd.concat([dept_n[["plant", "k", "dept_id"]].assign(via="dept_name"),
                        prev[["plant", "k", "dept_id"]].assign(via="previous_name")])
    ev = emp.assign(k=norm_dept(emp.department)).merge(lookup, on=["plant", "k"], how="left")
    variants = (ev.groupby(["plant", "department"], dropna=False)
                .agg(rows=("emp_id", "size"), dept_id=("dept_id", "first"), via=("via", "first"))
                .reset_index().sort_values(["dept_id", "department"]))
    found["dept_raw_variants"] = emp.department.nunique()
    found["dept_unmapped_rows"] = int(ev.dept_id.isna().sum())
    found["dept_via_previous_name"] = int((ev.via == "previous_name").sum())
    L += ["### 2.2 Department text variants -> dept_id",
          f"- {emp.department.nunique()} raw department strings; normalisation = trim + collapse spaces + lower, "
          f"joined on (plant, name) to departments.dept_name OR previous_name.",
          f"- unmapped rows after normalisation: **{found['dept_unmapped_rows']}**; rows mapped via previous_name "
          f"(old names Procurement->D04 Supply Chain, Processing->D15 Finishing): **{found['dept_via_previous_name']}**",
          "- renamed: " + "; ".join(f"{r.dept_id} {r.previous_name} -> {r.dept_name} on {r.renamed_on}"
                                    for r in dept[dept.previous_name.notna()].itertuples()),
          "", "<details><summary>variant map</summary>\n", md_table(variants, 200), "\n</details>", ""]

    # employee hire/sep for later
    e_latest = (e2.sort_values("upd").drop_duplicates("emp_id", keep="last").set_index("emp_id"))
    e_latest["hire"] = parse_mixed_date(e_latest.hire_date)
    e_latest["sep"] = parse_mixed_date(e_latest.separation_date)
    # cross-check employee dept vs history dept
    # 2.3 employment_history overlaps / gaps
    h = hist.copy()
    h["f"] = pd.to_datetime(h.effective_from)
    h["t"] = pd.to_datetime(h.effective_to)
    h = h.sort_values(["emp_id", "f"])
    h["next_f"] = h.groupby("emp_id").f.shift(-1)
    h["derived_to"] = h.next_f - pd.Timedelta(days=1)
    has_next = h.next_f.notna()
    overlap = has_next & h.t.notna() & (h.t >= h.next_f)
    gap = has_next & h.t.notna() & (h.t < h.derived_to)
    open_mid = has_next & h.t.isna()
    last_closed = (~has_next) & h.t.notna()
    found["hist_overlap_rows"] = int(overlap.sum())
    found["hist_gap_rows"] = int(gap.sum())
    found["hist_bad_emps"] = int(h[overlap | gap | open_mid].emp_id.nunique())
    L += ["### 2.3 employment_history effective_to unreliable (rule 2)",
          f"- rows={len(h)}, emps={h.emp_id.nunique()}, same (emp, effective_from) dups={int(h.duplicated(['emp_id','f']).sum())}",
          f"- overlaps (effective_to >= next effective_from): **{int(overlap.sum())} rows**; "
          f"gaps (effective_to < next_from-1): **{int(gap.sum())} rows**; "
          f"null effective_to but a later record exists: {int(open_mid.sum())}; "
          f"latest record with non-null effective_to: {int(last_closed.sum())}",
          f"- employees affected (overlap/gap/open-mid): **{found['hist_bad_emps']}**",
          f"- first record change_reason != Hire: {int((h.groupby('emp_id').change_reason.first() != 'Hire').sum())}; "
          f"first effective_from != hire_date: "
          f"{int((h.groupby('emp_id').f.first() != e_latest.hire.reindex(h.groupby('emp_id').f.first().index)).sum())}",
          ""]

    # 2.4 roster missing weeks
    r = dfs["shift_roster.csv"].copy()
    r["ws"] = pd.to_datetime(r.week_start)
    weeks = pd.date_range("2026-03-30", r.ws.max(), freq="7D")
    full = (pd.MultiIndex.from_product([sorted(r.emp_id.unique()), weeks], names=["emp_id", "ws"])
            .to_frame(index=False).merge(r[["emp_id", "ws", "shift_code"]], how="left"))
    full = full.join(e_latest[["hire", "sep"]], on="emp_id")
    # week overlaps employment within the period
    in_emp = ((full.ws + pd.Timedelta(days=6) >= full.hire.clip(lower=PERIOD_START))
              & (full.ws <= full.sep.fillna(PERIOD_END).clip(upper=PERIOD_END)))
    full = full.sort_values(["emp_id", "ws"])
    full["sc_ff"] = full.groupby("emp_id").shift_code.ffill()
    miss = in_emp & full.shift_code.isna()
    found["roster_missing_weeks"] = int(miss.sum())
    found["roster_missing_no_prior"] = int((miss & full.sc_ff.isna()).sum())
    L += ["### 2.4 Roster missing weeks (rule 6)",
          f"- roster weeks {r.week_start.min()}..{r.week_start.max()} ({r.week_start.nunique()} weeks), "
          f"{r.emp_id.nunique()} emps; emp in employees but never rostered: "
          f"{len(set(e_latest.index) - set(r.emp_id))}; rostered emp not in employees: {len(set(r.emp_id) - set(e_latest.index))}",
          f"- missing (emp, week) within employment & period: **{found['roster_missing_weeks']}** "
          f"across {full[miss].emp_id.nunique()} emps; of which no earlier week to forward-fill from: "
          f"{found['roster_missing_no_prior']}",
          f"- shift_code mix: {r.shift_code.value_counts().to_dict()}",
          ""]

    # daily roster (forward filled) for punch analysis
    rd = pd.concat([full[["emp_id", "ws", "sc_ff"]].assign(date=full.ws + pd.Timedelta(days=k)) for k in range(7)])
    S = rd.set_index(["emp_id", "date"])["sc_ff"]

    # 2.5 punches: unmapped
    p = dfs["biometric_punches.csv"].copy()
    p["t"] = pd.to_datetime(p.punch_time)
    dm = dfs["device_mapping.csv"]
    pm = p.merge(dm[["device_id", "device_user_id", "emp_id"]], on=["device_id", "device_user_id"], how="left")
    un = pm[pm.emp_id.isna()]
    found["punch_unmapped"] = len(un)
    L += ["### 2.5 Unmapped punches (rule 8)",
          f"- punches={len(p)}; unmapped (device_id+device_user_id not in device_mapping): **{len(un)}** rows, "
          f"{un.device_user_id.nunique()} distinct device users (ids {un.device_user_id.min()}..{un.device_user_id.max()}); "
          f"by device: {un.device_id.value_counts().to_dict()}",
          f"- device_mapping dup keys: {int(dm.duplicated(['device_id','device_user_id']).sum())}; "
          f"emp mapped to >1 device: {int(dm.emp_id.duplicated().sum())}; mapped emp not in employees: "
          f"{len(set(dm.emp_id) - set(e_latest.index))}", ""]

    # 2.6 device clock offset (computed on raw times, before correction)
    m = pm[pm.emp_id.notna()].sort_values(["emp_id", "t"]).copy()
    m["gap_s"] = m.groupby("emp_id").t.diff().dt.total_seconds()
    m = m[~(m.gap_s <= 120)].copy()     # 2-min dedup first for a clean first-punch
    m["d"] = m.t.dt.normalize()
    m["h"] = m.t.dt.hour + m.t.dt.minute / 60
    m["sc_d"] = S.reindex(pd.MultiIndex.from_arrays([m.emp_id, m.d])).values
    m["sc_p"] = S.reindex(pd.MultiIndex.from_arrays([m.emp_id, m.d - pd.Timedelta(days=1)])).values
    prev = (((m.h < 12) & (m.sc_p == "NIGHT") & ~m.sc_d.isin(["DAY", "GEN"]))
            | ((m.h < 4) & (m.sc_p == "EVE")))
    m["sd"] = m.d - pd.to_timedelta(prev.astype(int), unit="D")
    m["sc"] = np.where(prev, m.sc_p, m.sc_d)
    ci = (m.groupby(["emp_id", "sd"]).agg(t=("t", "min"), n=("t", "size"), sc=("sc", "first"),
                                           dev=("device_id", "first")).reset_index())
    ci = ci[ci.n >= 2]
    ci["delta"] = (ci.t - (ci.sd + pd.to_timedelta(ci.sc.map(SHIFT_START_H), unit="h"))).dt.total_seconds() / 60
    ci["month"] = ci.sd.dt.strftime("%Y-%m")
    per_dev = ci.groupby("dev").delta.agg(["count", "mean", "median"]).round(1).reset_index()
    per_dev_m = ci.pivot_table(index="dev", columns="month", values="delta", aggfunc="median").round(1).reset_index()
    base = ci[ci.dev != "DEV-SITE-01"].delta.median()
    site_after = ci[(ci.dev == "DEV-SITE-01") & (ci.sd >= "2026-07-01")].delta.median()
    site_before = ci[(ci.dev == "DEV-SITE-01") & (ci.sd < "2026-07-01")].delta.median()
    daily = (ci[(ci.dev == "DEV-SITE-01") & ci.sd.between("2026-06-27", "2026-07-03")]
             .groupby("sd").delta.median().round(1).reset_index())
    found["clock_device"] = "DEV-SITE-01"
    found["clock_offset_min"] = round(site_after - site_before, 1)
    L += ["### 2.6 Device clock drift (rule 11)",
          "- method: map punches -> emp, 2-min dedup, assign shift date (sec. 2.7 rule), check-in = first punch, "
          "delta = check-in - rostered shift start (minutes); compare per device and per month/day.",
          md_table(per_dev), "", md_table(per_dev_m), "",
          "- DEV-SITE-01 daily median around the change:", md_table(daily), "",
          f"- **DEV-SITE-01 runs +60 min fast from punch_time >= 2026-07-01 00:00:00** "
          f"(median delta before {site_before:.1f}, after {site_after:.1f}, other devices {base:.1f}; "
          f"step = {site_after - site_before:.1f} min). The 30-Jun night shift check-outs at ~07:00 on 1 Jul "
          f"are already shifted, so the cut-over is midnight. Correction: subtract 60 min.", ""]

    # 2.7 duplicates within 2 minutes (on mapped punches)
    mm = pm[pm.emp_id.notna()].sort_values(["emp_id", "t"]).copy()
    g = mm.groupby("emp_id").t.diff().dt.total_seconds()
    found["punch_dup_2min"] = int((g <= 120).sum())
    L += ["### 2.7 Punches within 2 minutes (rule 9)",
          f"- consecutive mapped punches of same emp with gap <= 120 s: **{int((g <= 120).sum())}** "
          f"(gap range of those: {g[g <= 120].min():.0f}-{g[g <= 120].max():.0f} s; gaps 121-600 s: "
          f"{int(g.between(121, 600).sum())} -> threshold is unambiguous)",
          "- night-shift attribution check: punches before 12:00 where previous day is NIGHT: "
          f"{int(((m.h < 12) & (m.sc_p == 'NIGHT')).sum())}; of those on a Monday whose own shift is DAY/GEN "
          f"(i.e. new week, belongs to today): {int(((m.h < 12) & (m.sc_p == 'NIGHT') & m.sc_d.isin(['DAY','GEN'])).sum())}; "
          f"Sunday punches >= 18:00 by NIGHT-rostered emps: "
          f"{int(((m.t.dt.dayofweek == 6) & (m.h >= 18) & (m.sc_d == 'NIGHT')).sum())}; "
          f"EVE shift check-outs after midnight (00:00-04:00, prev day EVE): {int(((m.h < 4) & (m.sc_p == 'EVE')).sum())}",
          f"- punches by mapped emps outside employment (before hire / after separation): "
          f"{int(((m.sd < e_latest.hire.reindex(m.emp_id).values) | (m.sd > e_latest.sep.reindex(m.emp_id).values)).sum())}",
          ""]

    # per emp-shift-date punch counts
    cnt = m.groupby(["emp_id", "sd"]).size()
    found["missing_punch_days"] = int((cnt == 1).sum())
    L += [f"- emp-shift-days with exactly 1 punch (Missing Punch candidates): **{int((cnt == 1).sum())}**; "
          f">2 punches: {int((cnt > 2).sum())}; shift-days total: {len(cnt)}", ""]

    # 2.8 7th month
    octp = p[p.t >= "2026-10-01"]
    oct_after_noon = p[p.t >= "2026-10-01 12:00"]
    found["oct_punches"] = len(octp)
    L += ["### 2.8 Is there a 7th month?",
          f"- punches dated October: {len(octp)} (max punch_time {p.punch_time.max()}); after 2026-10-01 12:00: "
          f"**{len(oct_after_noon)}** -> only the 30-Sep night-shift check-outs; **no 7th month of punches**. "
          f"Roster has planned weeks to {r.week_start.max()}; payroll months: {sorted(dfs['payroll_lines.csv'].payroll_month.unique())}",
          ""]

    # 2.9 OT approvals on days with no punches
    ot = dfs["overtime_requests.csv"].copy()
    ot["d"] = pd.to_datetime(ot.ot_date)
    keys = set(zip(m.emp_id, m.sd))
    ot["has_punch"] = [(e, d) in keys for e, d in zip(ot.emp_id, ot.d)]
    appr = ot[ot.status == "Approved"]
    found["ot_approved_no_punch"] = int((~appr.has_punch).sum())
    L += ["### 2.9 OT approvals on days with no punches (rule 19)",
          f"- OT requests by status: {ot.status.value_counts().to_dict()}; dup (emp, ot_date): {int(ot.duplicated(['emp_id','ot_date']).sum())}",
          f"- Approved requests whose (emp, ot_date) has zero mapped punches on that shift date: "
          f"**{found['ot_approved_no_punch']}** rows, {appr.loc[~appr.has_punch,'approved_hours'].astype(float).sum():.1f} approved h, "
          f"{appr.loc[~appr.has_punch,'emp_id'].nunique()} emps",
          f"- approved_hours null among Approved: {int(appr.approved_hours.isna().sum())}; non-Approved with approved_hours: "
          f"{int(ot[ot.status != 'Approved'].approved_hours.notna().sum())}; approved_hours > requested: "
          f"{int((appr.approved_hours.astype(float) > appr.requested_hours.astype(float)).sum())}", ""]

    # 2.10 leave approval combos
    rows = []
    for x in leave:
        a = sorted(x["approvals"], key=lambda s: s["step"])
        combo = " > ".join(f"{s['approver_role']}:{s['action']}" for s in a)
        rows.append({"combo": combo, "cancelled": x["cancelled_at"] is not None, "type": x["leave"]["type"],
                     "valid": len(a) == 2 and all(s["action"] == "Approved" for s in a)
                     and {s["approver_role"] for s in a} == {"Manager", "HR"} and x["cancelled_at"] is None,
                     "from": x["leave"]["from"], "to": x["leave"]["to"], "dr": x["leave"]["days_requested"]})
    lv = pd.DataFrame(rows)
    combos = lv.groupby(["combo", "cancelled"]).size().reset_index(name="requests")
    lv["cal"] = (pd.to_datetime(lv["to"]) - pd.to_datetime(lv["from"])).dt.days + 1
    found["leave_valid"] = int(lv.valid.sum())
    L += ["### 2.10 Leave approval combos (rule 16)", md_table(combos), "",
          f"- **valid requests (Manager Approved + HR Approved + not cancelled): {int(lv.valid.sum())}** of {len(lv)}; "
          f"types {lv.type.value_counts().to_dict()}; valid by type {lv[lv.valid].type.value_counts().to_dict()}",
          f"- days_requested != calendar span: {int((lv.dr != lv.cal).sum())}; from > to: "
          f"{int((pd.to_datetime(lv['from']) > pd.to_datetime(lv['to'])).sum())}; "
          f"range {lv['from'].min()}..{lv['to'].max()}", ""]

    # 2.11 payroll components
    pl = dfs["payroll_lines.csv"].copy()
    pl["amt"] = pl.amount.astype(float)
    comp = (pl.groupby(["component", "component_type"])
            .agg(lines=("line_id", "size"), units_filled=("units", lambda s: int(s.notna().sum())),
                 amount_sum=("amt", "sum"), neg_amounts=("amt", lambda s: int((s < 0).sum())))
            .reset_index())
    pkey_dup = int(pl.duplicated(["payroll_month", "emp_id", "component"]).sum())
    seps = e_latest.sep.dropna()
    pl["mstart"] = pd.to_datetime(pl.payroll_month + "-01")
    pl["sep"] = seps.reindex(pl.emp_id).values
    after = pl[(pl.component_type == "EARNING") & pl.sep.notna() & (pl.mstart > pl.sep)]
    found["pay_after_sep_emps"] = int(after.emp_id.nunique())
    L += ["### 2.11 Payroll components (rules 20-21)", md_table(comp), "",
          f"- dup (month, emp, component): {pkey_dup}; payroll emps not in employees: "
          f"{len(set(pl.emp_id) - set(e_latest.index))}",
          f"- earnings in a month starting after separation_date: {len(after)} lines, "
          f"**{after.emp_id.nunique()} emps** (q08 preview)", ""]
    return L, found


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(ROOT / "data" / "raw"))
    ap.add_argument("--out", default=str(ROOT / "docs" / "PROFILE.md"))
    a = ap.parse_args()
    raw = Path(a.raw)
    dfs = load(raw)
    leave = json.loads((raw / "leave_requests.json").read_text(encoding="utf-8"))
    shifts = json.loads((raw / "shifts.json").read_text(encoding="utf-8"))["shifts"]
    L = ["# Data profile - Indus Weave HCM export", "",
         f"Generated by `docs/profile_data.py` from `{raw}`. Read-only.", ""]
    issues, found = issues_section(dfs, leave, shifts)
    L += ["## 0. Headline numbers", ""] + [f"- {k}: **{v}**" for k, v in found.items()] + [""]
    L += issues
    L += generic_section(dfs, leave, shifts)
    L += ["### shifts.json", md_table(pd.DataFrame(shifts)), ""]
    Path(a.out).write_text("\n".join(L), encoding="utf-8")
    print(f"wrote {a.out}")
    for k, v in found.items():
        print(f"{k}={v}")


if __name__ == "__main__":
    main()
