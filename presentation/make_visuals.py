"""Generate warehouse/erd.png and presentation/slides.pdf (7 slides) from the built warehouse."""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline_config import ROOT, RESULTS_DIR, connect  # noqa: E402

INK, ACCENT, MUTED, RED = "#1f2937", "#2563eb", "#6b7280", "#dc2626"


def erd() -> None:
    tables = {
        "dim_employee (SCD2)": (0.38, 0.62, ["PK employee_sk", "emp_id", "valid_from / valid_to", "is_current",
                                              "FK dept_id", "designation, grade", "basic_salary", "hire / separation"]),
        "dim_department": (0.72, 0.86, ["PK dept_id", "dept_name, previous_name", "plant, plant_code", "cost_center"]),
        "dim_date": (0.04, 0.86, ["PK date_key (YYYYMMDD)", "full_date, year_month", "is_sunday, is_month_end"]),
        "dim_shift": (0.04, 0.40, ["PK shift_code", "start/end_time", "crosses_midnight", "grace_minutes"]),
        "fact_attendance_daily": (0.04, 0.16, ["PK emp_id + date_key", "FK employee_sk, dept_id", "FK date_key, shift_code",
                                               "status, check_in/out", "worked, late, early, ot_hours"]),
        "fact_leave_day": (0.38, 0.16, ["PK request_id + date_key", "FK employee_sk, dept_id, date_key", "leave_type"]),
        "fact_overtime_approved": (0.72, 0.40, ["PK request_id", "FK employee_sk, dept_id, date_key", "approved_hours",
                                                "computed_ot_hours"]),
        "fact_payroll_line": (0.72, 0.16, ["PK line_id", "FK employee_sk, dept_id, date_key", "component, type",
                                           "units, amount"]),
    }
    fig, ax = plt.subplots(figsize=(14, 9))
    ax.set_axis_off()
    centers = {}
    for name, (x, y, cols) in tables.items():
        h = 0.035 * (len(cols) + 1)
        fact = name.startswith("fact")
        ax.add_patch(plt.Rectangle((x, y - h), 0.24, h, fc="#eff6ff" if fact else "#f0fdf4", ec=INK, lw=1.2))
        ax.text(x + 0.01, y - 0.025, name, fontsize=11, weight="bold", color=INK)
        for i, c in enumerate(cols):
            ax.text(x + 0.01, y - 0.06 - 0.032 * i, c, fontsize=9, color=MUTED if not c.startswith(("PK", "FK")) else INK)
        centers[name] = (x + 0.12, y - h / 2)
    links = [("fact_attendance_daily", d) for d in ["dim_employee (SCD2)", "dim_date", "dim_shift", "dim_department"]]
    links += [(f, d) for f in ["fact_leave_day", "fact_overtime_approved", "fact_payroll_line"]
              for d in ["dim_employee (SCD2)", "dim_date", "dim_department"]]
    links += [("dim_employee (SCD2)", "dim_department")]
    for a, b in links:
        (x1, y1), (x2, y2) = centers[a], centers[b]
        ax.plot([x1, x2], [y1, y2], color=ACCENT, lw=0.8, alpha=0.35, zorder=0)
    ax.set_title("Indus Weave HR warehouse - star schema (PK/FK enforced in SQLite)", fontsize=14, color=INK)
    fig.savefig(ROOT / "warehouse" / "erd.png", dpi=130, bbox_inches="tight")
    plt.close(fig)


# The slide theme matches the dashboard so both look like one product in the demo.
BG, PANEL, EDGE, WHITE, SOFT = "#0b1120", "#131c31", "#1e2a44", "#f8fafc", "#94a3b8"
CYAN, VIOLET, ORANGE, ROSE, GREEN, AMBER = "#22d3ee", "#a78bfa", "#f97316", "#f43f5e", "#34d399", "#fbbf24"
W, H = 13.33, 7.5
TOTAL_SLIDES = 7


def new_slide(title: str, kicker: str, page: int):
    fig = plt.figure(figsize=(W, H), facecolor=BG)
    fig.patches.append(plt.Rectangle((0, 0.985), 1, 0.015, transform=fig.transFigure, fc=CYAN, ec="none"))
    fig.text(0.05, 0.905, kicker.upper(), fontsize=12, color=CYAN, weight="bold")
    fig.text(0.05, 0.835, title, fontsize=27, color=WHITE, weight="bold")
    fig.text(0.05, 0.03, "OT Truth Engine · Indus Weave Textiles · Apr–Sep 2026", fontsize=10, color=SOFT)
    fig.text(0.95, 0.03, f"{page} / {TOTAL_SLIDES}", fontsize=10, color=SOFT, ha="right")
    return fig


def box(fig, x, y, w, h, edge=EDGE, lw=1.5):
    fig.patches.append(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.015",
                                      transform=fig.transFigure, fc=PANEL, ec=edge, lw=lw))


def card(fig, x, y, w, h, label, value, sub="", color=WHITE, edge=EDGE, value_size=26):
    box(fig, x, y, w, h, edge)
    fig.text(x + 0.018, y + h - 0.05, label.upper(), fontsize=10.5, color=SOFT, weight="bold")
    fig.text(x + 0.018, y + h - 0.05 - 0.075 * value_size / 26, value, fontsize=value_size, color=color,
             weight="bold")
    if sub:
        fig.text(x + 0.018, y + 0.03, sub, fontsize=10.5, color=SOFT)


def dark_axes(ax, grid_axis="y"):
    ax.set_facecolor(BG)
    ax.tick_params(colors=SOFT, labelsize=11)
    for side in ["top", "right"]:
        ax.spines[side].set_visible(False)
    for side in ["left", "bottom"]:
        ax.spines[side].set_color(EDGE)
    ax.grid(axis=grid_axis, color=EDGE, lw=0.8)
    ax.set_axisbelow(True)


def short_month(m: str) -> str:
    return pd.Timestamp(m + "-01").strftime("%b")


def action_note(fig, text):
    fig.text(0.69, 0.15, text, fontsize=11.5, color=WHITE, linespacing=1.5)


def slides() -> None:
    q5 = pd.read_csv(RESULTS_DIR / "q05_ot_computed_vs_approved_vs_paid.csv")
    q6 = pd.read_csv(RESULTS_DIR / "q06_ot_overpaid_depts.csv")
    q7 = pd.read_csv(RESULTS_DIR / "q07_paid_zero_attendance.csv")
    q8 = pd.read_csv(RESULTS_DIR / "q08_paid_after_separation.csv")
    conn = connect()
    dq = pd.read_sql("SELECT status, COUNT(*) n FROM warehouse.dq_results WHERE run_at = "
                     "(SELECT MAX(run_at) FROM warehouse.dq_results) GROUP BY status", conn)
    conn.close()
    passed, total = int(dq.loc[dq.status == "PASS", "n"].sum()), int(dq.n.sum())
    monthly = q5.groupby("month")[["computed_ot_hours", "paid_ot_hours", "paid_ot_amount_pkr"]].sum()
    months = [short_month(m) for m in monthly.index]
    stitch = q5[q5.dept_id == "D20"].set_index("month")
    ghosts = q7[q7.separation_date.isna()]  # active staff, never punched
    s6 = q6.iloc[0]
    pay0, pay1 = monthly.paid_ot_amount_pkr.iloc[0], monthly.paid_ot_amount_pkr.iloc[-1]
    hrs0, hrs1 = monthly.computed_ot_hours.iloc[0], monthly.computed_ot_hours.iloc[-1]
    leak_ot, leak_ghost = s6.excess_paid_amount_pkr, ghosts.earnings_paid_pkr.sum()
    leak_exit = q8.earnings_paid_after_exit_pkr.sum()
    leak_total = leak_ot + leak_ghost + leak_exit
    legend_style = dict(facecolor=PANEL, edgecolor=EDGE, labelcolor=WHITE, fontsize=11)

    with PdfPages(ROOT / "presentation" / "slides.pdf") as pdf:
        # 1. Title
        fig = plt.figure(figsize=(W, H), facecolor=BG)
        hero = fig.add_axes([0, 0.42, 1, 0.58])
        hero.imshow([np.linspace(0, 1, 512)], aspect="auto", extent=[0, 1, 0, 1], interpolation="bicubic",
                    cmap=LinearSegmentedColormap.from_list("hero", ["#0e7490", "#312e81", "#7c2d12"]))
        hero.set_axis_off()
        fig.text(0.06, 0.83, "PEOPLEOPS DATA HACKATHON · CFO BRIEFING", fontsize=13, color="#e0f2fe", weight="bold")
        fig.text(0.06, 0.70, "Why is the overtime bill rising?", fontsize=40, color="white", weight="bold")
        fig.text(0.06, 0.61, "Payroll pays overtime from approved requests, not from biometric punches.",
                 fontsize=18, color="#e0f2fe")
        fig.text(0.06, 0.53, "OT Truth Engine · Indus Weave Textiles · 6 months, Apr–Sep 2026",
                 fontsize=13, color="#bae6fd")
        tiles = [("OT paid, Sep", f"PKR {pay1/1e6:.2f}M", f"+{100*(pay1/pay0-1):.0f}% vs Apr", ROSE),
                 ("OT worked, Sep", f"{hrs1:,.0f} h", f"{100*(hrs1/hrs0-1):+.0f}% vs Apr: flat", CYAN),
                 ("Leakage found", f"PKR {leak_total/1e6:.1f}M", "in 6 months, 3 causes", ORANGE),
                 ("Data quality", f"{passed}/{total}", "automated checks pass", GREEN)]
        for i, (lab, val, sub, col) in enumerate(tiles):
            card(fig, 0.06 + i * 0.23, 0.12, 0.205, 0.22, lab, val, sub, col)
        pdf.savefig(fig, facecolor=BG)
        plt.close(fig)

        # 2. The gap
        fig = new_slide("Paid OT climbs. Worked OT stays flat.", "The problem", 2)
        ax = fig.add_axes([0.07, 0.12, 0.57, 0.63])
        dark_axes(ax)
        ax.bar(months, monthly.paid_ot_hours, color=ORANGE, width=0.6, label="Paid OT hours (= approved)")
        ax.plot(months, monthly.computed_ot_hours, color=CYAN, lw=4, marker="o", ms=9, label="Worked (punches)")
        ax.set_ylabel("OT hours", color=SOFT, fontsize=12)
        ax.set_ylim(0, monthly.paid_ot_hours.max() * 1.22)
        ax.legend(loc="upper left", ncol=2, **legend_style)
        card(fig, 0.69, 0.53, 0.26, 0.22, "OT paid (PKR)", f"+{100*(pay1/pay0-1):.0f}%",
             f"{pay0/1e6:.2f}M in Apr → {pay1/1e6:.2f}M in Sep", ROSE, value_size=34)
        card(fig, 0.69, 0.27, 0.26, 0.22, "OT worked (hours)", f"{100*(hrs1/hrs0-1):+.0f}%",
             f"{hrs0:,.0f} h → {hrs1:,.0f} h by punch clock", CYAN, value_size=34)
        action_note(fig, "Paid hours = approved hours in every\none of 7,233 employee-months.")
        pdf.savefig(fig, facecolor=BG)
        plt.close(fig)

        # 3. Finding 1
        fig = new_slide(f"Stitching was paid {s6.excess_pct:.0f}% more OT than it worked",
                        "Finding 1 · overtime approvals", 3)
        ax = fig.add_axes([0.07, 0.12, 0.57, 0.63])
        dark_axes(ax)
        sm = [short_month(m) for m in stitch.index]
        ax.fill_between(sm, stitch.computed_ot_hours, stitch.paid_ot_hours, color=ROSE, alpha=0.18,
                        label="Paid, never worked")
        ax.plot(sm, stitch.paid_ot_hours, color=ROSE, lw=4, marker="o", ms=9, label="Paid (= approved)")
        ax.plot(sm, stitch.computed_ot_hours, color=CYAN, lw=4, marker="o", ms=9, label="Worked (punches)")
        ax.set_ylabel("OT hours · Faisalabad Stitching (D20)", color=SOFT, fontsize=12)
        ax.legend(loc="upper left", **legend_style)
        card(fig, 0.69, 0.53, 0.26, 0.22, "Overpaid", f"PKR {leak_ot/1e6:.2f}M",
             f"{s6.excess_paid_hours:,.0f} h paid, never worked", ORANGE, edge=ORANGE, value_size=30)
        card(fig, 0.69, 0.27, 0.26, 0.22, "Paid / worked hours", f"{s6.paid_ot_hours:,.0f} / {s6.computed_ot_hours:,.0f}",
             "only dept above the 15% line", WHITE, value_size=26)
        action_note(fig, "Action: pay OT from punches, capped\nat approved. Audit Jun–Sep approvers.")
        pdf.savefig(fig, facecolor=BG)
        plt.close(fig)

        # 4. Finding 2
        fig = new_slide("Six employees were paid every month without one punch", "Finding 2 · ghost payroll", 4)
        per = ghosts.groupby("emp_id").earnings_paid_pkr.sum().sort_values()
        ax = fig.add_axes([0.12, 0.12, 0.52, 0.63])
        dark_axes(ax, "x")
        ax.barh(per.index, per.values / 1e3, color=ROSE, height=0.6)
        for i, v in enumerate(per.values):
            ax.text(v / 1e3 + per.max() / 1e3 * 0.02, i, f"PKR {v/1e3:,.0f}k", va="center", color=WHITE, fontsize=11)
        ax.set_xlabel("Salary paid Apr–Sep (PKR thousand)", color=SOFT, fontsize=12)
        ax.set_xlim(0, per.max() / 1e3 * 1.3)
        card(fig, 0.69, 0.53, 0.26, 0.22, "Paid, zero attendance", f"PKR {leak_ghost/1e6:.2f}M",
             "no device enrolment, 0 punches", ORANGE, edge=ORANGE, value_size=30)
        card(fig, 0.69, 0.27, 0.26, 0.22, "In total (q07)", f"{q7.emp_id.nunique()} people",
             f"{len(q7)} employee-months, no attendance", WHITE, value_size=26)
        action_note(fig, "Action: hold these payslips now.\nHR to verify each person physically.")
        pdf.savefig(fig, facecolor=BG)
        plt.close(fig)

        # 5. Finding 3
        fig = new_slide("Salary kept flowing after people left", "Finding 3 · exit control", 5)
        q8s = q8.sort_values("earnings_paid_after_exit_pkr")
        ax = fig.add_axes([0.12, 0.12, 0.52, 0.63])
        dark_axes(ax, "x")
        ax.barh(q8s.emp_id, q8s.earnings_paid_after_exit_pkr / 1e3, color=VIOLET, height=0.6)
        top_k = q8s.earnings_paid_after_exit_pkr.max() / 1e3
        for i, r in enumerate(q8s.itertuples()):
            ax.text(r.earnings_paid_after_exit_pkr / 1e3 + top_k * 0.02, i,
                    f"PKR {r.earnings_paid_after_exit_pkr/1e3:,.0f}k · {r.months_paid_after_separation} mo after exit",
                    va="center", color=WHITE, fontsize=11)
        ax.set_xlabel("Paid after separation date (PKR thousand)", color=SOFT, fontsize=12)
        ax.set_xlim(0, top_k * 1.75)
        card(fig, 0.69, 0.53, 0.26, 0.22, "Paid after exit", f"PKR {leak_exit/1e6:.2f}M",
             f"{len(q8)} people, {int(q8.months_paid_after_separation.sum())} months", ORANGE, edge=ORANGE,
             value_size=30)
        top = q8.iloc[0]
        card(fig, 0.69, 0.27, 0.26, 0.22, "Largest case", top.emp_id,
             f"left {top.separation_date}, {top.dept_name}", WHITE, value_size=26)
        action_note(fig, "Action: recover the money. Payroll\nblocks any month after separation_date.")
        pdf.savefig(fig, facecolor=BG)
        plt.close(fig)

        # 6. Actions
        fig = new_slide(f"Three payroll rules close a PKR {leak_total/1e6:.1f}M leak", "Recommended actions", 6)
        acts = [("1", "Pay OT from punches", "fact_attendance_daily.ot_hours,\ncapped at approved hours.",
                 leak_ot, ORANGE),
                ("2", "Hold zero-punch payslips", "No punches and no approved\nleave in the month: hold.",
                 leak_ghost, ROSE),
                ("3", "Exit gate in payroll", "Block every pay month after\nseparation_date.",
                 leak_exit, VIOLET)]
        for i, (n, t, d, amt, col) in enumerate(acts):
            x = 0.05 + i * 0.31
            box(fig, x, 0.2, 0.28, 0.52, col, 2)
            fig.text(x + 0.02, 0.62, n, fontsize=34, color=col, weight="bold")
            fig.text(x + 0.02, 0.545, t, fontsize=17, color=WHITE, weight="bold")
            fig.text(x + 0.02, 0.43, d, fontsize=12.5, color=SOFT, va="center", linespacing=1.5)
            fig.text(x + 0.02, 0.28, f"PKR {amt/1e6:.2f}M", fontsize=24, color=col, weight="bold")
            fig.text(x + 0.02, 0.235, "leak closed (Apr–Sep)", fontsize=10.5, color=SOFT)
        fig.text(0.05, 0.11, "Run python run_pipeline.py every month: the DQ results gate the payroll file.",
                 fontsize=13, color=WHITE)
        pdf.savefig(fig, facecolor=BG)
        plt.close(fig)

        # 7. Trust
        fig = new_slide("How we got the numbers right", "Pipeline & data quality", 7)
        steps = [("Raw", "12 files as-is"), ("Staging", "clean + reconcile"), ("Attendance", "rules 12–15"),
                 ("Warehouse", "star schema"), ("10 answers", "SQL → CSV"), ("DQ", f"{passed}/{total} pass")]
        for i, (t, d) in enumerate(steps):
            x = 0.05 + i * 0.152
            col = GREEN if t == "DQ" else CYAN
            box(fig, x, 0.6, 0.13, 0.13, col, 1.8)
            fig.text(x + 0.065, 0.675, t, fontsize=14, color=WHITE, weight="bold", ha="center")
            fig.text(x + 0.065, 0.63, d, fontsize=10.5, color=SOFT, ha="center")
            if i < len(steps) - 1:
                fig.text(x + 0.141, 0.665, "›", fontsize=22, color=col, ha="center", va="center")
        fixes = [("50", "duplicate employees merged"), ("37", "broken history ranges fixed"),
                 ("6,962", "contractor punches rejected"), ("16,175", "duplicate punches (< 2 min)"),
                 ("+60 min", "DEV-SITE-01 clock drift fixed"), ("407", "missing roster weeks filled"),
                 ("4,282", "of 5,372 leave requests valid"), (f"{passed}/{total}", "PK · FK · recon · sanity")]
        for i, (num, txt) in enumerate(fixes):
            x, y = 0.05 + (i % 4) * 0.228, 0.36 - (i // 4) * 0.17
            box(fig, x, y, 0.21, 0.14, EDGE, 1.2)
            fig.text(x + 0.015, y + 0.07, num, fontsize=21, color=GREEN if i == 7 else AMBER, weight="bold")
            fig.text(x + 0.015, y + 0.025, txt, fontsize=10.5, color=SOFT)
        pdf.savefig(fig, facecolor=BG)
        plt.close(fig)


if __name__ == "__main__":
    erd()
    slides()
    print("wrote warehouse/erd.png and presentation/slides.pdf")
