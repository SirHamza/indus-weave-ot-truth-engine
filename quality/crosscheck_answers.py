"""Independent cross-check of the 10 answers (Stage 5).

The answers in analytics/results/*.csv come from SQL on the warehouse. This script
recomputes every answer a second, independent way: with pandas, straight from the
staging tables, without using any warehouse table, view or SQL file. Then it compares
the two results value by value.

If both methods agree, a bug would have to exist twice, in two different languages,
in the same way. That gives much stronger confidence in the numbers judged against the
answer key.

Exit code 1 if any answer differs, so run_pipeline.py stops.

Usage:  python quality/crosscheck_answers.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline_config import RESULTS_DIR, connect, log  # noqa: E402

MONTHS = [f"2026-{m:02d}" for m in range(4, 10)]  # Apr..Sep 2026
TOLERANCE = 0.011  # answers are rounded to 2 decimals in SQL


# ----------------------------------------------------------------- staging data
def load_staging() -> dict[str, pd.DataFrame]:
    """Read only staging tables: the cross-check never touches the warehouse."""
    conn = connect()
    tables = {
        "employees": "SELECT emp_id, hire_date, separation_date, annual_leave_entitlement FROM staging.employees",
        "history": "SELECT emp_id, valid_from, valid_to, dept_id FROM staging.employment_history",
        "departments": "SELECT dept_id, plant FROM staging.departments",
        "attendance": "SELECT emp_id, work_date, plant, status, is_working_day, is_late, ot_hours "
                      "FROM staging.attendance_daily",
        "overtime": "SELECT emp_id, ot_date, approved_hours FROM staging.overtime_requests WHERE status = 'Approved'",
        "payroll": "SELECT emp_id, payroll_month, component, component_type, units, amount FROM staging.payroll_lines",
        "leave_days": "SELECT emp_id, request_id, leave_type FROM staging.leave_days",
    }
    data = {name: pd.read_sql(sql, conn) for name, sql in tables.items()}
    conn.close()
    # The current history row has no end date: treat it as open-ended.
    data["history"]["valid_to"] = data["history"]["valid_to"].fillna("9999-12-31")
    return data


def month_end(month: str) -> str:
    return (pd.Timestamp(month + "-01") + pd.offsets.MonthEnd(0)).strftime("%Y-%m-%d")


def dept_on(history: pd.DataFrame, rows: pd.DataFrame, date_col: str) -> pd.DataFrame:
    """Add dept_id = the department each employee was in on rows[date_col] (SCD2 lookup)."""
    merged = rows.merge(history, on="emp_id")
    valid = (merged.valid_from <= merged[date_col]) & (merged[date_col] <= merged.valid_to)
    return merged[valid].drop(columns=["valid_from", "valid_to"])


def active_on(employees: pd.DataFrame, date: str) -> pd.Series:
    """Rule 4: employed on `date` = hired on/before it and not separated on/before it."""
    return (employees.hire_date <= date) & (employees.separation_date.isna() | (employees.separation_date > date))


def employee_months(d: dict) -> pd.DataFrame:
    """Cached: q05, q06, q07 and q09 all need the same employee-month table."""
    if "_employee_months" not in d:
        d["_employee_months"] = _build_employee_months(d)
    return d["_employee_months"].copy()


def _build_employee_months(d: dict) -> pd.DataFrame:
    """One row per employee and month with computed / approved / paid OT, earnings and attendance.

    Department = the one on the reporting date (rule 3): month end, or the separation
    date if the employee left before the month end.
    """
    att = d["attendance"].assign(month=d["attendance"].work_date.str[:7])
    att = att.assign(attended=att.status.isin(["Present", "Missing Punch"]).astype(int))
    att_m = att.groupby(["emp_id", "month"]).agg(
        computed=("ot_hours", "sum"), attended=("attended", "sum"), employed=("status", "size")).reset_index()
    ot = d["overtime"].assign(month=d["overtime"].ot_date.str[:7])
    ot_m = ot.groupby(["emp_id", "month"]).approved_hours.sum().rename("approved").reset_index()
    pay = d["payroll"].rename(columns={"payroll_month": "month"})
    is_ot, is_earning = pay.component == "OVERTIME", pay.component_type == "EARNING"
    pay = pay.assign(paid=pay.units.where(is_ot, 0), paid_amount=pay.amount.where(is_ot, 0),
                     earnings=pay.amount.where(is_earning, 0))
    pay_m = pay.groupby(["emp_id", "month"])[["paid", "paid_amount", "earnings"]].sum().reset_index()

    em = att_m.merge(ot_m, on=["emp_id", "month"], how="outer").merge(pay_m, on=["emp_id", "month"], how="outer")
    em = em.fillna({"computed": 0, "attended": 0, "employed": 0, "approved": 0, "paid": 0,
                    "paid_amount": 0, "earnings": 0})
    em = em.merge(d["employees"][["emp_id", "separation_date"]], on="emp_id")
    em["month_end"] = em.month.map(month_end)
    leaves_early = em.separation_date.notna() & (em.separation_date < em.month_end)
    em["reporting_date"] = np.where(leaves_early, em.separation_date, em.month_end)
    return dept_on(d["history"], em, "reporting_date")


# ----------------------------------------------------------------- the 10 answers
def q01(d):
    rows = []
    for m in MONTHS:
        me = month_end(m)
        active = d["employees"][active_on(d["employees"], me)][["emp_id"]].assign(as_of=me)
        counts = dept_on(d["history"], active, "as_of").groupby("dept_id").size()
        rows += [{"month": m, "dept_id": k, "headcount": v} for k, v in counts.items()]
    return pd.DataFrame(rows), ["month", "dept_id"], ["headcount"]


def q02(d):
    def headcount(date):
        active = d["employees"][active_on(d["employees"], date)][["emp_id"]].assign(as_of=date)
        return dept_on(d["history"], active, "as_of").groupby("dept_id").size()

    seps = d["employees"].dropna(subset=["separation_date"])
    seps = dept_on(d["history"], seps[["emp_id", "separation_date"]], "separation_date")
    rows = []
    for m in MONTHS:
        prev_end = (pd.Timestamp(m + "-01") - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        opening, closing = headcount(prev_end), headcount(month_end(m))
        left = seps[seps.separation_date.str[:7] == m].groupby("dept_id").size()
        for dept in d["departments"].dept_id:
            o, c, s = opening.get(dept, 0), closing.get(dept, 0), left.get(dept, 0)
            avg = (o + c) / 2
            rows.append({"month": m, "dept_id": dept, "opening_headcount": o, "closing_headcount": c,
                         "separations": s, "attrition_rate_pct": round(100 * s / avg, 2) if avg else np.nan})
    return pd.DataFrame(rows), ["month", "dept_id"], ["opening_headcount", "closing_headcount", "separations",
                                                      "attrition_rate_pct"]


def q03(d):
    a = d["attendance"]
    a = a[(a.is_working_day == 1) & (a.status != "On Leave")].assign(month=lambda x: x.work_date.str[:7])
    g = a.groupby(["month", "plant"]).agg(scheduled_days_excl_leave=("status", "size"),
                                          absent_days=("status", lambda s: (s == "Absent").sum())).reset_index()
    g["absenteeism_rate_pct"] = (100 * g.absent_days / g.scheduled_days_excl_leave).round(2)
    return g, ["month", "plant"], ["scheduled_days_excl_leave", "absent_days", "absenteeism_rate_pct"]


def q04(d):
    a = d["attendance"]
    a = a[a.work_date.between("2026-04-01", "2026-09-30")]
    late = a.groupby("emp_id").is_late.sum().rename("late_arrivals").reset_index()
    late["late_rank"] = late.late_arrivals.rank(method="min", ascending=False).astype(int)
    return late[late.late_rank <= 10], ["emp_id"], ["late_rank", "late_arrivals"]


def q05(d):
    em = employee_months(d)
    em = em[em.month.isin(MONTHS)]
    g = em.groupby(["month", "dept_id"])[["computed", "approved", "paid", "paid_amount"]].sum().reset_index()
    g = g.rename(columns={"computed": "computed_ot_hours", "approved": "approved_ot_hours",
                          "paid": "paid_ot_hours", "paid_amount": "paid_ot_amount_pkr"})
    g["paid_ot_amount_pkr"] = g.paid_ot_amount_pkr.round(0)
    return g, ["month", "dept_id"], ["computed_ot_hours", "approved_ot_hours", "paid_ot_hours", "paid_ot_amount_pkr"]


def q06(d):
    em = employee_months(d)
    t = em[em.month.isin(MONTHS)].groupby("dept_id")[["computed", "paid"]].sum().reset_index()
    t = t[t.paid > t.computed * 1.15]
    t["excess_paid_hours"] = (t.paid - t.computed).round(2)
    t["excess_pct"] = (100 * (t.paid - t.computed) / t.computed).round(2)
    return t, ["dept_id"], ["excess_paid_hours", "excess_pct"]


def q07(d):
    em = employee_months(d)
    em = em[em.month.isin(MONTHS) & (em.earnings > 0) & (em.attended == 0)]
    em = em.assign(earnings_paid_pkr=em.earnings.round(0))
    return em, ["month", "emp_id"], ["earnings_paid_pkr"]


def q08(d):
    pay = d["payroll"].merge(d["employees"][["emp_id", "separation_date"]], on="emp_id")
    pay = pay[pay.separation_date.notna() & ((pay.payroll_month + "-01") > pay.separation_date)]
    per_month = pay[pay.component_type == "EARNING"].groupby(["emp_id", "payroll_month"]).amount.sum()
    per_month = per_month[per_month > 0].reset_index()
    g = per_month.groupby("emp_id").agg(months_paid_after_separation=("payroll_month", "size"),
                                        earnings_paid_after_exit_pkr=("amount", "sum")).reset_index()
    g["earnings_paid_after_exit_pkr"] = g.earnings_paid_after_exit_pkr.round(0)
    return g, ["emp_id"], ["months_paid_after_separation", "earnings_paid_after_exit_pkr"]


def q09(d):
    em = employee_months(d)
    em = em[em.month.isin(MONTHS) & (em.earnings > 0)]
    g = em.groupby(["dept_id", "month"]).agg(payroll_cost_pkr=("earnings", "sum"),
                                             paid_employees=("emp_id", "nunique")).reset_index()
    g["cost_per_employee_pkr"] = g.payroll_cost_pkr / g.paid_employees
    g["mom_change_pct"] = (100 * g.groupby("dept_id").cost_per_employee_pkr.pct_change()).round(2)
    g["cost_per_employee_pkr"] = g.cost_per_employee_pkr.round(2)
    g["payroll_cost_pkr"] = g.payroll_cost_pkr.round(0)
    return g, ["month", "dept_id"], ["payroll_cost_pkr", "paid_employees", "cost_per_employee_pkr", "mom_change_pct"]


def q10(d):
    annual = d["leave_days"][d["leave_days"].leave_type == "Annual"].groupby("emp_id").agg(
        approved_annual_leave_days=("request_id", "size")).reset_index()
    t = annual.merge(d["employees"][["emp_id", "annual_leave_entitlement"]], on="emp_id")
    t = t[t.approved_annual_leave_days > t.annual_leave_entitlement]
    t["days_over_entitlement"] = t.approved_annual_leave_days - t.annual_leave_entitlement
    return t, ["emp_id"], ["approved_annual_leave_days", "days_over_entitlement"]


CHECKS = {
    "q01_headcount": q01, "q02_attrition": q02, "q03_absenteeism": q03, "q04_late_arrivals": q04,
    "q05_ot_computed_vs_approved_vs_paid": q05, "q06_ot_overpaid_depts": q06,
    "q07_paid_zero_attendance": q07, "q08_paid_after_separation": q08,
    "q09_payroll_cost_mom": q09, "q10_leave_overuse": q10,
}


# ----------------------------------------------------------------- comparison
def compare(name: str, mine: pd.DataFrame, keys: list[str], values: list[str]) -> list[str]:
    """Return a list of differences between the pandas result and the SQL CSV (empty = identical)."""
    sql = pd.read_csv(RESULTS_DIR / f"{name}.csv")
    mine = mine[keys + values].copy()
    problems = []
    sql_keys, my_keys = set(map(tuple, sql[keys].astype(str).values)), set(map(tuple, mine[keys].astype(str).values))
    if sql_keys != my_keys:
        problems.append(f"rows differ: only in SQL {sorted(sql_keys - my_keys)[:3]}, "
                        f"only in pandas {sorted(my_keys - sql_keys)[:3]}")
        return problems
    both = sql[keys + values].astype({k: str for k in keys}).merge(
        mine.astype({k: str for k in keys}), on=keys, suffixes=("_sql", "_pandas"))
    for v in values:
        a, b = both[f"{v}_sql"].astype(float), both[f"{v}_pandas"].astype(float)
        # PKR amounts are rounded to whole rupees, everything else to 2 decimals.
        tolerance = 1.0 if v.endswith("_pkr") else TOLERANCE
        bad = ~(((a - b).abs() <= tolerance) | (a.isna() & b.isna()))
        if bad.any():
            row = both[bad].iloc[0]
            problems.append(f"{v}: {int(bad.sum())} values differ, e.g. {dict(row[keys])} "
                            f"SQL={row[f'{v}_sql']} pandas={row[f'{v}_pandas']}")
    return problems


def main() -> int:
    data = load_staging()
    failed = 0
    for name, fn in CHECKS.items():
        mine, keys, values = fn(data)
        problems = compare(name, mine, keys, values)
        status = "MATCH" if not problems else "DIFF"
        log("crosscheck", f"{name:<38} {len(mine):>4} rows  {status}")
        for p in problems:
            log("crosscheck", f"    {p}")
        failed += bool(problems)
    log("crosscheck", f"{len(CHECKS) - failed}/{len(CHECKS)} answers confirmed by an independent pandas recomputation")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
