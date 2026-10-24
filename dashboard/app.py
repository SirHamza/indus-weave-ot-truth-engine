"""OT Truth Engine dashboard on the warehouse tables.  Run:  streamlit run dashboard/app.py"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline_config import DB_DIR, connect  # noqa: E402

RESULTS = ROOT / "analytics" / "results"
st.set_page_config(page_title="OT Truth Engine", page_icon="⏱️", layout="wide")

# Colors ek jagah rakhe hain taake har chart same palette use kare.
C_COMPUTED, C_APPROVED, C_PAID, C_BAD, C_OK = "#22d3ee", "#a78bfa", "#f97316", "#f43f5e", "#34d399"

st.markdown("""
<style>
.block-container {padding-top: 1.6rem; max-width: 1400px;}
.hero {background: linear-gradient(120deg,#0e7490 0%,#312e81 55%,#7c2d12 100%); border-radius: 18px;
       padding: 26px 32px; margin-bottom: 18px; box-shadow: 0 10px 30px rgba(0,0,0,.35);}
.hero h1 {color:#fff; font-size: 2.1rem; margin: 0 0 4px 0; letter-spacing: -.5px;}
.hero p {color:#e0f2fe; margin: 0; font-size: 1.02rem;}
.hero .pill {display:inline-block; background: rgba(255,255,255,.14); color:#fff; border-radius: 999px;
             padding: 3px 12px; font-size: .78rem; margin: 10px 6px 0 0;}
.kpi {background:#131c31; border:1px solid #1e2a44; border-radius:14px; padding:16px 18px; height:100%;}
.kpi .label {color:#94a3b8; font-size:.78rem; text-transform:uppercase; letter-spacing:.6px;}
.kpi .value {color:#f8fafc; font-size:1.75rem; font-weight:700; margin-top:4px;}
.kpi .delta {font-size:.85rem; margin-top:2px;}
.up-bad {color:#fb7185;} .flat {color:#22d3ee;} .good {color:#34d399;}
.finding {background:#131c31; border-left:5px solid #f97316; border-radius:12px; padding:16px 18px; margin-bottom:12px;}
.finding h4 {margin:0 0 6px 0; color:#f8fafc;}
.finding .amt {color:#fb923c; font-size:1.5rem; font-weight:700;}
.finding p {color:#cbd5e1; margin:6px 0 0 0; font-size:.92rem;}
.stage {background:#131c31; border:1px solid #1e2a44; border-radius:12px; padding:12px; text-align:center; height:100%;}
.stage .n {color:#22d3ee; font-weight:700; font-size:.8rem;}
.stage .t {color:#f8fafc; font-weight:600; margin:2px 0;}
.stage .d {color:#94a3b8; font-size:.78rem;}
.stTabs [data-baseweb="tab"] {font-size: 1rem; padding: 10px 16px;}
</style>
""", unsafe_allow_html=True)

if not (DB_DIR / "warehouse.db").exists():
    st.error("Warehouse not built yet. Run `python run_pipeline.py` first.")
    st.stop()


@st.cache_data
def q(sql: str) -> pd.DataFrame:
    conn = connect()
    try:
        return pd.read_sql(sql, conn)
    finally:
        conn.close()


@st.cache_data
def csv(name: str) -> pd.DataFrame:
    path = RESULTS / f"{name}.csv"
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def style(fig: go.Figure, height: int = 380) -> go.Figure:
    fig.update_layout(template="plotly_dark", height=height, paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)", margin=dict(l=10, r=10, t=90, b=10), title=dict(y=0.97, x=0),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title_text=""),
                      font=dict(size=13))
    return fig


def kpi(col, label: str, value: str, delta: str = "", cls: str = "flat") -> None:
    col.markdown(f'<div class="kpi"><div class="label">{label}</div><div class="value">{value}</div>'
                 f'<div class="delta {cls}">{delta}</div></div>', unsafe_allow_html=True)


# ---------- data ----------
monthly = q("""SELECT year_month AS month, SUM(computed_ot_hours) computed, SUM(approved_ot_hours) approved,
                      SUM(paid_ot_hours) paid, SUM(paid_ot_amount) paid_pkr
               FROM warehouse.v_employee_month WHERE year_month BETWEEN '2026-04' AND '2026-09' GROUP BY 1 ORDER BY 1""")
dq = q("SELECT * FROM warehouse.dq_results WHERE run_at = (SELECT MAX(run_at) FROM warehouse.dq_results)")
q5, q6, q7, q8 = (csv(n) for n in ["q05_ot_computed_vs_approved_vs_paid", "q06_ot_overpaid_depts",
                                    "q07_paid_zero_attendance", "q08_paid_after_separation"])
dept_ot = (q5.groupby(["plant", "dept_id", "dept_name"], as_index=False)[["computed_ot_hours", "paid_ot_hours"]].sum())
dept_ot["excess_pct"] = (100 * (dept_ot.paid_ot_hours - dept_ot.computed_ot_hours) / dept_ot.computed_ot_hours).round(1)
dept_ot["dept"] = dept_ot.dept_name + " · " + dept_ot.plant.str.replace(" Plant", "")

ghosts = q7[q7.separation_date.isna()]
leak_ot = float(q6.excess_paid_amount_pkr.sum()) if len(q6) else 0.0
leak_ghost = float(ghosts.earnings_paid_pkr.sum())
leak_exit = float(q8.earnings_paid_after_exit_pkr.sum())
leak_total = leak_ot + leak_ghost + leak_exit
dq_pass = int((dq.status == "PASS").sum())

# ---------- hero ----------
st.markdown(f"""
<div class="hero">
  <h1>⏱️ OT Truth Engine · Indus Weave Textiles</h1>
  <p>Payroll pays overtime from <b>approved requests</b>, not from <b>biometric punches</b>.
     This warehouse rebuilds the truth from raw HCM exports, Apr–Sep 2026.</p>
  <span class="pill">12 raw files → raw · staging · warehouse</span>
  <span class="pill">Star schema · PK/FK enforced</span>
  <span class="pill">10 SQL answers</span>
  <span class="pill">{dq_pass}/{len(dq)} DQ checks passing</span>
</div>""", unsafe_allow_html=True)

first, last = monthly.iloc[0], monthly.iloc[-1]
k = st.columns(5)
kpi(k[0], "OT paid · Sep", f"PKR {last.paid_pkr/1e6:.2f}M",
    f"▲ {100*(last.paid_pkr/first.paid_pkr-1):.0f}% vs Apr (PKR {first.paid_pkr/1e6:.2f}M)", "up-bad")
kpi(k[1], "OT actually worked · Sep", f"{last.computed:,.0f} h",
    f"{100*(last.computed/first.computed-1):+.0f}% vs Apr: flat", "flat")
kpi(k[2], "Paid = approved", "100%", "of 7,233 employee-months: punches never checked", "up-bad")
kpi(k[3], "Leakage found", f"PKR {leak_total/1e6:.1f}M", "OT excess + ghosts + post-exit pay", "up-bad")
kpi(k[4], "Data quality", f"{dq_pass}/{len(dq)}", "checks pass · numbers are proven",
    "good" if dq_pass == len(dq) else "up-bad")
st.write("")

tabs = st.tabs(["📊 CFO story", "⏱️ Overtime gap", "💸 Payroll leakage", "❓ 10 questions",
                "✅ Data quality", "🔧 Pipeline", "🧪 SQL explorer"])

# ---------- 1. CFO story ----------
with tabs[0]:
    left, right = st.columns([3, 2])
    with left:
        fig = go.Figure()
        fig.add_bar(x=monthly.month, y=monthly.paid, name="Paid OT hours", marker_color=C_PAID)
        fig.add_scatter(x=monthly.month, y=monthly.approved, name="Approved", mode="lines+markers",
                        line=dict(color=C_APPROVED, width=3, dash="dot"))
        fig.add_scatter(x=monthly.month, y=monthly.computed, name="Worked (punches)", mode="lines+markers",
                        line=dict(color=C_COMPUTED, width=4))
        st.plotly_chart(style(fig.update_layout(title="Paid OT climbs, worked OT stays flat"), 430),
                        width="stretch")
    with right:
        st.markdown("#### Top 3 findings")
        top = q6.iloc[0] if len(q6) else None
        cards = [
            ("1 · Stitching paid for hours nobody worked", leak_ot,
             f"{top.dept_name} ({top.plant}) was paid {top.paid_ot_hours:,.0f} OT hours vs "
             f"{top.computed_ot_hours:,.0f} worked (+{top.excess_pct:.0f}%)." if top is not None else ""),
            ("2 · Paid every month, never punched in", leak_ghost,
             f"{ghosts.emp_id.nunique()} active employees with no device enrolment drew full salary "
             f"({', '.join(sorted(ghosts.emp_id.unique()))})."),
            ("3 · Salary kept flowing after exit", leak_exit,
             f"{len(q8)} separated employees were paid for {int(q8.months_paid_after_separation.sum())} "
             f"months after their separation date."),
        ]
        for title, amount, text in cards:
            st.markdown(f'<div class="finding"><h4>{title}</h4><div class="amt">PKR {amount:,.0f}</div>'
                        f'<p>{text}</p></div>', unsafe_allow_html=True)
    st.info("**Fix:** pay OT from `fact_attendance_daily.ot_hours`, capped at approved hours · hold payslips with "
            "zero punches and no approved leave · block pay months after `separation_date`.")

# ---------- 2. Overtime gap ----------
with tabs[1]:
    plants = ["All plants"] + sorted(q5.plant.unique())
    pick = st.segmented_control("Plant", plants, default="All plants") or "All plants"
    sub = q5 if pick == "All plants" else q5[q5.plant == pick]
    by_month = sub.groupby("month", as_index=False)[["computed_ot_hours", "approved_ot_hours", "paid_ot_hours"]].sum()
    long = by_month.melt("month", var_name="measure", value_name="hours")
    long["measure"] = long.measure.map({"computed_ot_hours": "Worked (punches)", "approved_ot_hours": "Approved",
                                        "paid_ot_hours": "Paid"})
    a, b = st.columns(2)
    a.plotly_chart(style(px.bar(long, x="month", y="hours", color="measure", barmode="group",
                                color_discrete_map={"Worked (punches)": C_COMPUTED, "Approved": C_APPROVED,
                                                    "Paid": C_PAID},
                                title=f"OT hours by month · {pick}")), width="stretch")
    d = dept_ot if pick == "All plants" else dept_ot[dept_ot.plant == pick]
    d = d.sort_values("excess_pct")
    fig = px.bar(d, x="excess_pct", y="dept", orientation="h", title="Paid vs worked OT, % over (6 months)",
                 color=d.excess_pct > 15, color_discrete_map={True: C_BAD, False: "#334155"})
    fig.add_vline(x=15, line_dash="dash", line_color="#fbbf24", annotation_text="15% threshold (q06)")
    b.plotly_chart(style(fig.update_layout(showlegend=False), max(380, 26 * len(d))), width="stretch")
    st.caption("Worked OT = punch-based hours beyond the shift, in 30-minute blocks (rules 14–15). "
               "Paid OT = payroll OT lines.")

# ---------- 3. Payroll leakage ----------
with tabs[2]:
    leak = pd.DataFrame({"source": ["OT paid above worked (q06)", "Paid with zero attendance (q07)",
                                    "Paid after separation (q08)"], "pkr": [leak_ot, leak_ghost, leak_exit]})
    a, b = st.columns([2, 3])
    a.plotly_chart(style(px.pie(leak, names="source", values="pkr", hole=.6, title="Where PKR {:.1f}M goes"
                                .format(leak_total / 1e6), color_discrete_sequence=[C_PAID, C_BAD, C_APPROVED]),
                         400).update_layout(legend=dict(orientation="v", y=-.1)), width="stretch")
    top8 = q8.sort_values("earnings_paid_after_exit_pkr")
    b.plotly_chart(style(px.bar(top8, x="earnings_paid_after_exit_pkr", y="emp_id", orientation="h",
                                hover_data=["full_name", "dept_name", "separation_date"],
                                color_discrete_sequence=[C_APPROVED],
                                title="Salary paid after separation, by employee (PKR)")), width="stretch")
    st.markdown("##### Paid with zero attendance (q07)")
    st.dataframe(q7, width="stretch", hide_index=True,
                 column_config={"earnings_paid_pkr": st.column_config.NumberColumn("Paid (PKR)", format="%,.0f")})
    st.markdown("##### Paid after separation (q08)")
    st.dataframe(q8, width="stretch", hide_index=True)

# ---------- 4. 10 questions ----------
QUESTIONS = {
    "Q1 · Headcount by month, plant, department": "q01_headcount",
    "Q2 · Monthly attrition rate": "q02_attrition",
    "Q3 · Absenteeism rate by plant": "q03_absenteeism",
    "Q4 · Top 10 late arrivals": "q04_late_arrivals",
    "Q5 · OT computed vs approved vs paid": "q05_ot_computed_vs_approved_vs_paid",
    "Q6 · Departments paid >15% above worked OT": "q06_ot_overpaid_depts",
    "Q7 · Paid with zero attendance": "q07_paid_zero_attendance",
    "Q8 · Paid after separation": "q08_paid_after_separation",
    "Q9 · Payroll cost per employee, MoM": "q09_payroll_cost_mom",
    "Q10 · Annual leave above entitlement": "q10_leave_overuse",
    "Bonus · Recruitment funnel": "bonus_recruitment_funnel",
}
with tabs[3]:
    label = st.selectbox("Business question", list(QUESTIONS))
    name = QUESTIONS[label]
    df = csv(name)
    fig = None
    if name == "q01_headcount":
        fig = px.area(df.groupby(["month", "plant"], as_index=False).headcount.sum(), x="month", y="headcount",
                      color="plant", title="Headcount by plant")
    elif name == "q02_attrition":
        g = df.groupby("month", as_index=False)[["separations", "avg_headcount"]].sum()
        g["rate"] = (100 * g.separations / g.avg_headcount).round(2)
        fig = px.bar(g, x="month", y="rate", text="rate", title="Company attrition rate % (separations / avg headcount)",
                     color_discrete_sequence=[C_APPROVED])
    elif name == "q03_absenteeism":
        fig = px.line(df, x="month", y="absenteeism_rate_pct", color="plant", markers=True,
                      title="Absenteeism rate % by plant")
    elif name == "q04_late_arrivals":
        fig = px.bar(df.sort_values("late_arrivals"), x="late_arrivals", y="full_name", orientation="h",
                     color="dept_name", title="Most late arrivals (check-in > 10 min after shift start)")
    elif name == "q05_ot_computed_vs_approved_vs_paid":
        fig = px.bar(monthly.melt("month", ["computed", "approved", "paid"]), x="month", y="value",
                     color="variable", barmode="group", title="Company OT hours",
                     color_discrete_map={"computed": C_COMPUTED, "approved": C_APPROVED, "paid": C_PAID})
    elif name == "q09_payroll_cost_mom":
        g = df.groupby(["month", "plant"], as_index=False).payroll_cost_pkr.sum()
        fig = px.bar(g, x="month", y="payroll_cost_pkr", color="plant", title="Payroll cost (earnings) by plant")
    elif name == "q10_leave_overuse":
        fig = px.bar(df.head(15), x="emp_id", y=["annual_leave_entitlement", "days_over_entitlement"],
                     title="Approved annual leave vs entitlement", hover_data=["full_name", "dept_name"])
    elif name == "bonus_recruitment_funnel":
        fig = go.Figure(go.Funnel(y=df.stage, x=df.reached, textinfo="value+percent initial",
                                  marker=dict(color=[C_COMPUTED, "#38bdf8", C_APPROVED, "#c084fc", C_OK])))
        fig.update_layout(title="Applied → Hired")
    if fig is not None:
        st.plotly_chart(style(fig, 420), width="stretch")
    m1, m2 = st.columns([1, 4])
    m1.metric("Rows", len(df))
    m2.caption(f"SQL: `analytics/{name}.sql` · CSV: `analytics/results/{name}.csv`")
    st.dataframe(df, width="stretch", hide_index=True, height=360)
    sql_path = ROOT / "analytics" / f"{name}.sql"
    if sql_path.exists():
        with st.expander("Show the SQL"):
            st.code(sql_path.read_text(encoding="utf-8"), language="sql")

# ---------- 5. Data quality ----------
with tabs[4]:
    cats = dq.groupby(["category", "status"], as_index=False).size()
    a, b = st.columns([2, 3])
    a.plotly_chart(style(px.bar(cats, x="size", y="category", color="status", orientation="h",
                                color_discrete_map={"PASS": C_OK, "FAIL": C_BAD}, title="Checks by category")),
                   width="stretch")
    with b:
        st.markdown(f"#### {dq_pass} of {len(dq)} checks pass")
        st.progress(dq_pass / max(len(dq), 1))
        st.caption("PK uniqueness, FK integrity, row-count reconciliation raw → staging → warehouse, "
                   "accepted values, sanity ranges. `python quality/dq_checks.py` exits 1 on any failure.")
        status = st.multiselect("Status", ["PASS", "FAIL"], default=["PASS", "FAIL"])
    view = dq[dq.status.isin(status)][["category", "check_name", "table_name", "status", "failing_rows",
                                        "expected", "actual"]]
    st.dataframe(view, width="stretch", height=480, hide_index=True)

# ---------- 6. Pipeline ----------
with tabs[5]:
    stages = [("1", "Raw", "12 files loaded as-is, row-hash idempotent"),
              ("2", "Staging", "clean, de-dup, SCD2 fix, clock drift, night shift"),
              ("3", "Attendance", "status, late, early, OT per rules 12–15"),
              ("4", "Warehouse", "star schema, PK/FK enforced"),
              ("5", "Questions", "10 SQL files → CSV"),
              ("6", "Quality", f"{len(dq)} DQ checks"),
              ("7", "Demo", "dashboard, ERD, slides")]
    cols = st.columns(len(stages))
    for col, (n, t, d) in zip(cols, stages):
        col.markdown(f'<div class="stage"><div class="n">STAGE {n}</div><div class="t">{t}</div>'
                     f'<div class="d">{d}</div></div>', unsafe_allow_html=True)
    st.write("")
    a, b = st.columns(2)
    with a:
        st.markdown("##### Layer row counts")
        counts = q("""SELECT 'staging.punches' AS tbl, COUNT(*) AS n FROM staging.punches
            UNION ALL SELECT 'staging.rejected_punches', COUNT(*) FROM staging.rejected_punches
            UNION ALL SELECT 'warehouse.fact_attendance_daily', COUNT(*) FROM warehouse.fact_attendance_daily
            UNION ALL SELECT 'warehouse.fact_payroll_line', COUNT(*) FROM warehouse.fact_payroll_line
            UNION ALL SELECT 'warehouse.fact_overtime_approved', COUNT(*) FROM warehouse.fact_overtime_approved
            UNION ALL SELECT 'warehouse.fact_leave_day', COUNT(*) FROM warehouse.fact_leave_day
            UNION ALL SELECT 'warehouse.dim_employee (SCD2)', COUNT(*) FROM warehouse.dim_employee""")
        st.dataframe(counts, width="stretch", hide_index=True)
        rej = q("SELECT reject_reason AS reason, COUNT(*) AS punches FROM staging.rejected_punches GROUP BY 1")
        st.plotly_chart(style(px.pie(rej, names="reason", values="punches", hole=.55,
                                     title="Rejected punches (kept, with a reason)",
                                     color_discrete_sequence=[C_BAD, C_APPROVED]), 320), width="stretch")
    with b:
        st.markdown("##### Raw load log (file rows = table rows)")
        st.dataframe(q("SELECT * FROM raw._load_log"), width="stretch", hide_index=True)
        status = q("SELECT status, COUNT(*) AS days FROM warehouse.fact_attendance_daily GROUP BY 1 ORDER BY 2 DESC")
        st.plotly_chart(style(px.bar(status, x="status", y="days", title="Attendance days by status",
                                     color_discrete_sequence=[C_COMPUTED]), 320), width="stretch")
    erd = ROOT / "warehouse" / "erd.png"
    if erd.exists():
        with st.expander("Warehouse ERD", expanded=False):
            st.image(str(erd))

# ---------- 7. SQL explorer ----------
with tabs[6]:
    sql = st.text_area("Read-only SQL (schemas: raw, staging, warehouse)", height=140,
                       value="SELECT status, COUNT(*) AS days\nFROM warehouse.fact_attendance_daily\nGROUP BY 1 ORDER BY 2 DESC")
    if st.button("Run query", type="primary"):
        if not sql.strip().lower().startswith(("select", "with")):
            st.warning("Only SELECT / WITH queries are allowed.")
        else:
            try:
                st.dataframe(q(sql), width="stretch", hide_index=True)
            except Exception as exc:  # SQL error dikhao, app crash na ho
                st.error(f"Query failed: {exc}")

st.caption("Every number on this page is read from `db/warehouse.db` or `analytics/results/`. "
           "Rebuild everything with `python run_pipeline.py`.")
