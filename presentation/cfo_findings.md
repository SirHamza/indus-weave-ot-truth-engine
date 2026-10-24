# CFO findings: why overtime cost keeps rising

**Context.** OT paid rose from **PKR 2.81M (Apr) to PKR 3.48M (Sep), up 23%**. Over the same months, OT actually worked (computed from biometric punches using rules 14–15) stayed flat at about 6,100–6,500 hours a month. Payroll pays OT hours equal to the approved requests in every one of the 7,233 employee-months, and never checks the punches. So the leak sits between approval and payment, not on the shop floor.

## 1. Stitching was paid 56% more overtime than it worked: about PKR 1.36M
**Number.** Faisalabad Stitching (D20) was paid **7,659 OT hours against 4,906 hours worked** (+2,753 h, **+56%**). Over six months, approved hours grew from 762 (Apr) to 1,779 (Sep), while the hours actually worked stayed between 764 and 920. It is the only department above the 15% threshold.
**Evidence.** `analytics/q05_ot_computed_vs_approved_vs_paid.sql`, `analytics/q06_ot_overpaid_depts.sql`
**Action.** Pay OT from `warehouse.fact_attendance_daily.ot_hours`, capped at the approved hours. Audit the Stitching approvers for Jun–Sep and claw back the unworked hours.

## 2. Six active employees were paid all six months without a single punch: PKR 2.88M
**Number.** E10399, E10491, E10564, E10907, E11064 and E11089 have **no biometric device enrolment and zero attendance** in any month, yet each received full salary every month: **PKR 2,877,075** in earnings. In total, 12 employees and 58 employee-months were paid with zero attendance (the post-exit cases are in finding 3).
**Evidence.** `analytics/q07_paid_zero_attendance.sql`
**Action.** Put these payslips on hold now. HR should physically verify each person (possible ghost employees). Add a payroll pre-run rule: no punches in the month and no approved leave means the payslip is held.

## 3. Five people were paid after they left: PKR 1.95M
**Number.** **5 separated employees kept drawing salary for 21 months in total, PKR 1,948,000.** Example: E10471 (HR, Head Office) left on 2026-04-23 and was paid for May through September (PKR 660,000).
**Evidence.** `analytics/q08_paid_after_separation.sql`
**Action.** Recover the overpayments. Add an exit gate: the payroll run blocks anyone whose `separation_date` is before the pay month (one SQL check, `quality/dq_checks.py` style).

**Total leakage identified: about PKR 6.2M in six months.** Every figure above can be rebuilt from the raw files with `python run_pipeline.py`.
