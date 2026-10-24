# 5-minute CFO demo script

| Time | Screen | Say |
|---|---|---|
| 0:00–0:30 | Terminal: `python run_pipeline.py` output | "12 raw HCM files, rebuilt from scratch in about 80 seconds: raw, staging, star schema, 10 answers, 89 data-quality checks, all passing." |
| 0:30–1:15 | Dashboard → CFO story | "OT paid is up 23%, from PKR 2.81M to 3.48M a month. OT actually worked by the punch clock is flat. Payroll pays the approved hours 1:1 and never looks at the punches." |
| 1:15–2:15 | Overtime gap tab | "One department breaks the 15% line: Faisalabad Stitching was paid 7,659 hours against 4,906 worked. That is +56%, about PKR 1.36M." |
| 2:15–3:15 | Payroll leakage tab | "Six active employees have no device enrolment and zero attendance, yet drew PKR 2.88M. Five people kept getting paid after they left: PKR 1.95M. E10471 alone was paid for 5 months after exit." |
| 3:15–4:00 | 10 questions tab → Q6, show SQL | "Every number comes from one SQL file you can rerun." |
| 4:00–4:30 | Data quality tab | "89 checks prove the numbers reconcile from raw to warehouse." |
| 4:30–5:00 | Back to CFO story → Fix box | "Three fixes: pay OT from punches capped at approved, hold zero-punch payslips, block pay after separation. About PKR 6.2M in six months." |

Backup: if the dashboard fails, open `presentation/slides.pdf` (7 slides, same numbers).
