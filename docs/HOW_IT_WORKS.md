# How the code works

This guide walks through the whole pipeline: what each file does, the key code, and one real example traced from a raw punch to a CFO number. Read it alongside the code; every file also has comments explaining each step.

**Contents**
1. [The big picture](#1-the-big-picture)
2. [How to run it](#2-how-to-run-it)
3. [One database, three layers](#3-one-database-three-layers-pipeline_configpy)
4. [Stage 1: raw load](#4-stage-1-raw-load-ingestionload_rawpy)
5. [Stage 2: clean and reconcile](#5-stage-2-clean-and-reconcile)
6. [Stage 3: daily attendance](#6-stage-3-daily-attendance-transformsql03_attendance_dailysql)
7. [Stage 4: star-schema warehouse](#7-stage-4-star-schema-warehouse)
8. [Stage 5: the 10 business questions](#8-stage-5-the-10-business-questions)
9. [Stage 6: data-quality checks](#9-stage-6-data-quality-checks-qualitydq_checkspy)
10. [Stage 7: dashboard, slides, ERD](#10-stage-7-dashboard-slides-erd)
11. [Worked example: one punch to one CFO number](#11-worked-example-one-employee-day-from-punch-to-cfo-number)
12. [Where to change things](#12-where-to-change-things)

---

## 1. The big picture

```
 data/raw/ (12 files: CSV + JSON)
      │  Stage 1  ingestion/load_raw.py            copy as-is, every column TEXT
      ▼
 raw.*            (exact copy + _source_file, _loaded_at, _row_hash)
      │  Stage 2  transform/stage2_clean.py         Python: dates, duplicates, JSON, roster, clock drift
      │           transform/sql/02_punches.sql      SQL: map punches, fix clock, de-duplicate, night shifts
      ▼
 staging.*        (typed, trimmed, reconciled; bad rows parked in *_rejected / *_log tables)
      │  Stage 3  transform/sql/03_attendance_daily.sql   status, late, early, overtime per day
      ▼
 staging.attendance_daily
      │  Stage 4  warehouse/ddl/*.sql + load_warehouse.sql   star schema, PK/FK enforced
      ▼
 warehouse.*      (4 dimensions + 4 facts + 1 view)
      │  Stage 5  analytics/q01..q10.sql            one SQL file per business question → CSV
      │  Stage 6  quality/dq_checks.py              89 automated checks → warehouse.dq_results
      │  Stage 7  presentation/make_visuals.py      ERD + slides;  dashboard/app.py reads the warehouse
      ▼
 analytics/results/*.csv · presentation/slides.pdf · dashboard
```

`run_pipeline.py` runs every stage in this order. If any stage fails, the pipeline stops with that stage's error.

**The business problem in one line:** payroll pays overtime from *approved requests*, not from *biometric punches*. The pipeline computes overtime from the punches and compares it with what was approved and paid.

## 2. How to run it

```bash
python -m venv .venv
.venv\Scripts\activate                 # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
# put the 12 data files + data_dictionary.md in data/raw/
python run_pipeline.py --fresh         # build everything from zero (~1.5 min)
streamlit run dashboard/app.py         # open the dashboard
```

| Command | What it does |
|---|---|
| `python run_pipeline.py` | Rebuild. Safe to repeat: raw rows already loaded are skipped |
| `python run_pipeline.py --fresh` | Delete `db/` first, as on a new machine |
| `python run_pipeline.py --incremental FILE --period-end 2026-10-31` | Append only the new punches of a 7th month, then rebuild |
| `python quality/dq_checks.py` | Re-run only the data-quality checks |
| `python analytics/run_questions.py` | Re-run only the 10 questions |

## 3. One database, three layers (`pipeline_config.py`)

SQLite has no schemas like PostgreSQL. So three database files are attached to one connection under the names `raw`, `staging` and `warehouse`. Every query can then say `staging.employees` or `warehouse.fact_attendance_daily`, just like PostgreSQL.

```python
def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    for schema in SCHEMAS:                                   # raw, staging, warehouse
        conn.execute(f"ATTACH DATABASE ? AS {schema}", (str(DB_DIR / f"{schema}.db"),))
    conn.execute("PRAGMA foreign_keys = ON")                 # SQLite needs this per connection
    return conn
```

The same file also holds the reporting period (`PERIOD_START`, `PERIOD_END`) and the plant codes used by the holiday file.

## 4. Stage 1: raw load (`ingestion/load_raw.py`)

**Goal:** copy each file into the database exactly as delivered. Nothing is trimmed, parsed or fixed here, so the raw layer is always a faithful copy you can audit against.

- Every column is stored as `TEXT`.
- JSON files (`leave_requests.json`, `shifts.json`) are stored one row per array element, in a single `record_json` column. They are not flattened yet.
- Each row gets three extra columns: `_source_file`, `_loaded_at` and `_row_hash` (a SHA-256 of the row's values).

**Why `_row_hash` matters: idempotency.** The hash is the table's primary key, and rows are inserted with `INSERT OR IGNORE`. Loading the same file twice therefore adds 0 rows, and a new month's file adds only the rows that are really new.

```python
payload = [r + [path.name, loaded_at, row_hash(r)] for r in rows]
conn.executemany(f'INSERT OR IGNORE INTO raw."{table}" ({col_list}) VALUES ({placeholders})', payload)
```

Every load writes one line per file to `raw._load_log`: rows in the file, rows inserted, rows already loaded, and `MATCH`/`MISMATCH`. A mismatch stops the pipeline.

## 5. Stage 2: clean and reconcile

### 5a. Python part (`transform/stage2_clean.py`)
Python handles the work that is awkward in SQL. Each `build_*` function reads one raw table and writes one or more clean `staging` tables through the `write()` helper.

| Function | Problem in the data | What the code does |
|---|---|---|
| `parse_mixed_date` | Dates in 3 formats (`2026-04-01`, `01/04/2026`, `01-Apr-2026`) | Tries each format in turn and fails loudly on anything unknown |
| `build_departments` | Extra spaces, renamed departments | Trims text, keeps `previous_name`, adds the plant code |
| `build_employees` | Same `emp_id` exported twice; department typed as free text | Keeps the row with the latest `updated_at` (rule 1) and logs what differed in `employee_merge_log`. Matches department text to `dept_id` on the current or previous name |
| `build_employment_history` | `effective_to` overlaps or leaves gaps | Rebuilds clean SCD2 ranges: `valid_to = next valid_from − 1 day` (rule 2). Each fix is explained in `effective_to_fix` |
| `build_shifts` | JSON | Unpacks it. NIGHT ends the next day, so a day is added to its end time |
| `build_roster` | Missing roster weeks | Fills a missing week with the previous week's shift (rule 6) and flags it `is_imputed = 1`. Expands to one row per employee per day (`roster_daily`) |
| `build_leave` | Nested approvals in JSON | One row per request plus one per approval step. Valid only if Manager AND HR approved and it was never cancelled (rule 16). Leave days skip Sundays and plant holidays (rule 17) |
| `detect_clock_drift` | One device's clock runs 1 hour fast | See below |

**Clock-drift detection (rule 11)** is found from the data, not hard-coded:
1. For each employee-day on a normal (non-overnight) shift, measure how many minutes after the shift start the first punch happened.
2. For each device and day, take the median of that delay. Compare it with the median of all *other* devices on the same day.
3. If one device is more than 30 minutes off from some day onwards, every day until the end, that is a drift. The correction is the typical difference, rounded to 15 minutes.

Result: `DEV-SITE-01` is off by +60 minutes from 2026-07-01 (median difference 59.8 min after, 0.1 min before). This is written to `staging.device_clock_corrections`.

### 5b. SQL part (`transform/sql/02_punches.sql`)
Every raw punch ends up in exactly one of two tables: `staging.punches` (kept) or `staging.rejected_punches` (with a reason).

1. **Map** each punch to an employee through `device_id + device_user_id`. If there's no mapping (a contractor or visitor), the punch is rejected as `UNMAPPED_DEVICE_USER`.
2. **Correct the clock:** subtract the detected offset for drifting devices.
3. **De-duplicate** with `LAG()`: a punch within 120 seconds of the same employee's previous punch is a `DUPLICATE_WITHIN_2_MIN`.
   ```sql
   CAST(strftime('%s', punch_time) AS INTEGER)
     - CAST(strftime('%s', LAG(punch_time) OVER w) AS INTEGER) AS secs_since_prev
   ...
   WINDOW w AS (PARTITION BY emp_id ORDER BY punch_time, punch_id)
   ```
4. **Night shifts (rules 7 and 10):** a NIGHT shift starting 22:00 ends at 06:00 the next day. A morning punch after a NIGHT day therefore belongs to the *previous* date, unless today is a DAY/GEN shift, in which case it is today's check-in. The result is stored as `shift_date`.

## 6. Stage 3: daily attendance (`transform/sql/03_attendance_daily.sql`)

This builds one row for every employee for every day they were employed in the period. It is the core table that all overtime numbers come from.

**Status (rule 12), checked in this order:**
```sql
CASE WHEN is_sunday = 1 AND punch_count = 0           THEN 'Weekly Off'
     WHEN holiday_name IS NOT NULL AND punch_count = 0 THEN 'Holiday'
     WHEN leave_request_id IS NOT NULL                 THEN 'On Leave'
     WHEN punch_count >= 2                             THEN 'Present'
     WHEN punch_count = 1                              THEN 'Missing Punch'
     ELSE 'Absent' END
```
- **Check-in / check-out:** the first and last punch of the shift date.
- **Late / early departure (rule 13):** only on Present working days, and only beyond the 10-minute grace.
- **Overtime (rules 14 and 15):**
  - On a working day, OT is the time after the shift end.
  - On a Sunday or holiday, all worked time is OT.
  - OT is always rounded *down* to whole half-hours.
  - The calculation uses integer seconds (`secs / 1800 * 0.5`), so there are no floating-point rounding errors.

## 7. Stage 4: star-schema warehouse

| File | What it does |
|---|---|
| `warehouse/ddl/01_dimensions.sql` | `dim_date`, `dim_department`, `dim_shift`, `dim_employee` (SCD2: one row per employment period, with `employee_sk` as the key) |
| `warehouse/ddl/02_facts.sql` | `fact_attendance_daily`, `fact_leave_day`, `fact_overtime_approved`, `fact_payroll_line`, with PRIMARY KEY, FOREIGN KEY and CHECK constraints |
| `warehouse/ddl/03_views.sql` | `v_employee_month`: one row per employee per month with computed, approved and paid OT plus earnings, credited to the right department (rule 3) |
| `warehouse/load_warehouse.sql` | Fills everything from staging |
| `warehouse/build_warehouse.py` | Runs the files above, then `PRAGMA foreign_key_check` (must be 0) |

**The SCD2 join.** An employee who changed department has several `dim_employee` rows. Each fact row is linked to the version that was valid on that row's date:
```sql
JOIN warehouse.dim_employee de
  ON de.emp_id = a.emp_id AND a.work_date BETWEEN de.valid_from AND de.valid_to
```
**Department for monthly numbers (rule 3)** is the department on the month end, or on the separation date if the person left that month. This logic lives only in `v_employee_month`, and questions q05–q09 reuse it.

Diagram: [`warehouse/erd.png`](../warehouse/erd.png)

## 8. Stage 5: the 10 business questions

`analytics/run_questions.py` runs every `analytics/q*.sql` file and saves the result as `analytics/results/<same name>.csv`. Each SQL file starts with a comment stating the question and the business rule used.

| File | Question | SQL techniques |
|---|---|---|
| `q01_headcount.sql` | Month-end headcount by plant and department | CTE, SCD2 date join |
| `q02_attrition.sql` | Monthly attrition rate | opening/closing headcount, average |
| `q03_absenteeism.sql` | Absenteeism by plant, excluding approved leave | conditional sums |
| `q04_late_arrivals.sql` | Top 10 late employees | `RANK()` window, so ties stay visible |
| `q05_ot_computed_vs_approved_vs_paid.sql` | OT computed vs approved vs paid | `v_employee_month` |
| `q06_ot_overpaid_depts.sql` | Departments paid >15% above worked OT | `HAVING`-style filter on totals |
| `q07_paid_zero_attendance.sql` | Paid in a month with zero attendance | anti-pattern detection |
| `q08_paid_after_separation.sql` | Paid after leaving | date comparison |
| `q09_payroll_cost_mom.sql` | Cost per employee, month-over-month | `LAG()` window |
| `q10_leave_overuse.sql` | Annual leave above entitlement | aggregation vs a limit |
| `bonus_recruitment_funnel.sql` | Applied → Hired funnel | conversion and median days per stage |

Example, Q6 in full (the source of Finding 1):
```sql
WITH dept_totals AS (
    SELECT dept_id, SUM(computed_ot_hours) AS computed_ot_hours, SUM(approved_ot_hours) AS approved_ot_hours,
           SUM(paid_ot_hours) AS paid_ot_hours, SUM(paid_ot_amount) AS paid_ot_amount
    FROM warehouse.v_employee_month
    WHERE year_month BETWEEN '2026-04' AND '2026-09'
    GROUP BY dept_id
)
SELECT d.plant, d.dept_id, d.dept_name, ...,
       ROUND(100.0 * (t.paid_ot_hours - t.computed_ot_hours) / NULLIF(t.computed_ot_hours, 0), 2) AS excess_pct
FROM dept_totals t JOIN warehouse.dim_department d ON d.dept_id = t.dept_id
WHERE t.paid_ot_hours > t.computed_ot_hours * 1.15
ORDER BY excess_pct DESC;
```
Result: Stitching (Faisalabad) was paid 7,659 OT hours for 4,906 hours worked, which is +56%, about PKR 1.36M.

## 9. Stage 6: data-quality checks (`quality/dq_checks.py`)

There are 89 checks, each a SQL query that counts the rows *breaking* a rule (0 = PASS). Results are saved in `warehouse.dq_results` with a timestamp. If any check fails, the script exits with code 1, which stops the pipeline.

| Category | Count | Example |
|---|---|---|
| Primary key | 36 | `staging.punches.punch_id` is unique and not null |
| Referential integrity | 14 | every `fact_attendance_daily.employee_sk` exists in `dim_employee` |
| Reconciliation | 18 | raw punches = kept punches + rejected punches |
| Accepted values | 7 | attendance status is one of the 6 allowed values |
| Business sanity | 14 | no SCD2 overlaps or gaps, OT in whole half-hours, no shift over 16 h |

Reconciliation is what proves no data was lost: every raw row is either in staging or in a log or rejected table with a reason.

## 10. Stage 7: dashboard, slides, ERD

- **`dashboard/app.py`** (Streamlit) reads the warehouse and the result CSVs. Its tabs are CFO story, Overtime gap, Payroll leakage, 10 questions (chart, table and SQL), Data quality, Pipeline, and a read-only SQL explorer. The `q()` helper caches each query so the page stays fast.
- **`presentation/make_visuals.py`** draws `warehouse/erd.png` and the 7-slide `presentation/slides.pdf` with matplotlib. It uses the same numbers as the CSVs, so the slides can never disagree with the data.
- **`presentation/cfo_findings.md`** and **`presentation/DEMO.md`** hold the three findings and the 5-minute demo script.

## 11. Worked example: one employee-day, from punch to CFO number

Employee **E10580**, Cutting (Faisalabad), **4 April 2026**, rostered on the **DAY** shift (06:00–14:00, 10-minute grace).

| Step | Table | What happens |
|---|---|---|
| 1 | `raw.biometric_punches` | Two punches on device `DEV-FSD-01`: `06:35:41` and `15:06:08`, stored as text exactly as exported |
| 2 | `staging.punches` | Both map to E10580. The device has no drift and the punches are not duplicates, so both are kept with `shift_date = 2026-04-04` |
| 3 | `staging.attendance_daily` | 2 punches gives **Present**. Check-in 06:35:41 is 35.7 min after 06:00, beyond the 10-min grace, so **late = 1, late_minutes = 35.7**. Check-out 15:06:08 is 3,968 s after 14:00, and 3,968 ÷ 1,800 = 2 whole half-hours, so **ot_hours = 1.0**. Worked = **8.51 h** |
| 4 | `warehouse.fact_attendance_daily` | Same row, linked to E10580's `employee_sk` valid on that date |
| 5 | `warehouse.fact_overtime_approved` | Request `OT009972` approved **1.0 h**, and the computed OT that day is 1.0 h, so they agree |
| 6 | `warehouse.v_employee_month` | Added into E10580's April totals: computed, approved and paid OT |
| 7 | `q04_late_arrivals.csv` | This late day is one of the 58 that make E10580 the **#1 latest employee** |
| 8 | `q05` / `q06` | Department-month OT totals. For Stitching, paid hours run far above computed hours, which is Finding 1 |

The same path, applied to all 322,143 kept punches, produces every number on the dashboard.

## 12. Where to change things

| You want to… | Change |
|---|---|
| Change the reporting period | `PERIOD_START` / `PERIOD_END` in `pipeline_config.py` (or `--period-end`) |
| Change the late grace or the OT rounding | `transform/sql/03_attendance_daily.sql` (grace comes from `shifts.json`) |
| Change the 2-minute duplicate window | `transform/sql/02_punches.sql` (`secs_since_prev <= 120`) and the matching DQ check |
| Add a business question | Add `analytics/q11_<name>.sql`; `run_questions.py` picks it up automatically |
| Add a data-quality check | Add a line to `SANITY` (or another list) in `quality/dq_checks.py` |
| Add a raw file | Add it to `CSV_FILES` / `JSON_FILES` in `ingestion/load_raw.py` and write a `build_*` function in stage 2 |
