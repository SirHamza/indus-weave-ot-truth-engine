# Code kaise kaam karta hai (Roman Urdu guide)

Yeh guide aasaan Roman Urdu mein batati hai ke poora pipeline kaise chalta hai: har file kya karti hai, important code kya hai, aur ek asal example jismein ek punch se CFO ke number tak ka safar dikhaya gaya hai.
English version: [`HOW_IT_WORKS.md`](HOW_IT_WORKS.md). Code ki har file mein bhi har step par comments hain, unhein saath saath parhein.

**Fehrist (Contents)**
1. [Asal masla kya hai?](#1-asal-masla-kya-hai)
2. [Pehle yeh 8 cheezein samajh lein](#2-pehle-yeh-8-cheezein-samajh-lein)
3. [Poora pipeline ek nazar mein](#3-poora-pipeline-ek-nazar-mein)
4. [Kaise chalayein](#4-kaise-chalayein)
5. [Ek database, teen layers](#5-ek-database-teen-layers-pipeline_configpy)
6. [Stage 1: raw load](#6-stage-1-raw-load-ingestionload_rawpy)
7. [Stage 2: safai aur milaan](#7-stage-2-safai-aur-milaan-clean--reconcile)
8. [Stage 3: rozana attendance](#8-stage-3-rozana-attendance-transformsql03_attendance_dailysql)
9. [Stage 4: star schema warehouse](#9-stage-4-star-schema-warehouse)
10. [Stage 5: 10 business sawal](#10-stage-5-10-business-sawal)
11. [Stage 6: data quality checks](#11-stage-6-data-quality-checks-qualitydq_checkspy)
12. [Stage 7: dashboard, slides, ERD](#12-stage-7-dashboard-slides-erd)
13. [Asal example: ek punch se CFO ke number tak](#13-asal-example-ek-din-ek-punch-se-cfo-ke-number-tak)
14. [Teen findings kahan se aayi](#14-teen-findings-kahan-se-aayi)
15. [Kuch badalna ho to kahan](#15-kuch-badalna-ho-to-kahan)
16. [Code parhne ka sahi tarteeb](#16-code-parhne-ka-sahi-tarteeb)
17. [Judges ke mumkina sawal aur jawab](#17-judges-ke-mumkina-sawal-aur-jawab)

---

## 1. Asal masla kya hai?

Indus Weave Textiles ka overtime (OT) ka kharcha 6 mahine mein **23% barh gaya**: April mein PKR 2.81M tha, September mein PKR 3.48M ho gaya.
Lekin biometric machine (punch clock) ke mutabiq log utna hi kaam kar rahe hain, OT ke ghante flat hain (lagbhag 6,100 ghante har mahine).

**Wajah:** payroll OT ke paise **approved requests** ki buniyad par deta hai, **asal punches** ki buniyad par nahi. Manager ne jitne ghante approve kar diye, utne pay ho gaye, chahe banda ruka ho ya nahi.

Hamara code yeh karta hai:
1. Asal punches se nikalta hai ke kisne kitna OT **sach mein kiya** (computed).
2. Usay **approved** aur **paid** OT se milata hai.
3. Jahan farq hai, wahan paise ka leak dikhata hai: kul **taqreeban PKR 6.2M**.

## 2. Pehle yeh 8 cheezein samajh lein

| Lafz | Matlab (aasaan zubaan mein) |
|---|---|
| **Database / SQLite** | Data rakhne ki jagah, tables ki shakal mein. SQLite ek file-based database hai, server install karne ki zaroorat nahi |
| **SQL** | Database se sawal poochne ki zubaan, jaise `SELECT ... FROM ... WHERE ...` |
| **Schema / layer** | Tables ka group. Hamare 3 hain: `raw` (kaccha data), `staging` (saaf data), `warehouse` (report ke liye tayyar data) |
| **Idempotent** | Code ko 2 baar chalao to bhi data double nahi hota. Doosri baar 0 naye rows aate hain |
| **Fact table** | Hone wale waqiyat: har din ki attendance, har payroll line, har approved OT |
| **Dimension table** | Waqiye ki tafseel: employee kaun, department kaunsa, date kaunsi, shift kaunsi |
| **SCD2** | Employee ki history sambhalne ka tareeqa. Department badla to purani row band hoti hai (`valid_to`) aur nayi row shuru hoti hai (`valid_from`) |
| **PK / FK** | Primary Key = har row ki unique pehchaan. Foreign Key = doosri table ki row ka hawala; galat hawala database qubool nahi karta |

## 3. Poora pipeline ek nazar mein

```
 data/raw/ (12 files: CSV + JSON)
      │  Stage 1  ingestion/load_raw.py            jaisa mila waisa copy, har column TEXT
      ▼
 raw.*            (exact copy + _source_file, _loaded_at, _row_hash)
      │  Stage 2  transform/stage2_clean.py         Python: dates, duplicates, JSON, roster, clock ki ghalti
      │           transform/sql/02_punches.sql      SQL: punch ko employee se jorna, clock theek, duplicate hatana, night shift
      ▼
 staging.*        (saaf data; kharab rows wajah ke saath *_rejected / *_log tables mein)
      │  Stage 3  transform/sql/03_attendance_daily.sql   har din ka status, late, early, overtime
      ▼
 staging.attendance_daily
      │  Stage 4  warehouse/ddl/*.sql + load_warehouse.sql   star schema, PK/FK lagu
      ▼
 warehouse.*      (4 dimensions + 4 facts + 1 view)
      │  Stage 5  analytics/q01..q10.sql            har sawal ki ek SQL file, jawab CSV mein
      │  Stage 6  quality/dq_checks.py              89 automatic checks, natija warehouse.dq_results mein
      │  Stage 7  presentation/make_visuals.py      ERD + slides;  dashboard/app.py warehouse se parhta hai
      ▼
 analytics/results/*.csv · presentation/slides.pdf · dashboard
```

`run_pipeline.py` yeh saari stages isi tarteeb se chalata hai. Koi stage fail ho jaye to pipeline wahin ruk jata hai aur usi stage ka error dikhata hai.

## 4. Kaise chalayein

```bash
python -m venv .venv
.venv\Scripts\activate                 # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
# 12 data files + data_dictionary.md ko data/raw/ mein rakhein
python run_pipeline.py --fresh         # sab kuch zero se banao (~1.5 minute)
streamlit run dashboard/app.py         # dashboard kholo
```

| Command | Kya karta hai |
|---|---|
| `python run_pipeline.py` | Dobara build. Baar baar chalana safe hai: pehle se load rows skip ho jati hain |
| `python run_pipeline.py --fresh` | Pehle `db/` delete, phir naye computer ki tarah shuru se |
| `python run_pipeline.py --incremental FILE --period-end 2026-10-31` | 7th mahine ke sirf naye punches jorna, phir rebuild |
| `python quality/dq_checks.py` | Sirf data checks dobara chalana |
| `python analytics/run_questions.py` | Sirf 10 sawal dobara chalana |

## 5. Ek database, teen layers (`pipeline_config.py`)

PostgreSQL mein "schemas" hote hain, SQLite mein nahi. Is liye hum teen alag database files ko ek connection par `raw`, `staging` aur `warehouse` naam se jor dete hain (ATTACH). Ab har query `staging.employees` ya `warehouse.fact_attendance_daily` likh sakti hai, bilkul PostgreSQL ki tarah.

```python
def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    for schema in SCHEMAS:                                   # raw, staging, warehouse
        conn.execute(f"ATTACH DATABASE ? AS {schema}", (str(DB_DIR / f"{schema}.db"),))
    conn.execute("PRAGMA foreign_keys = ON")                 # SQLite mein har connection par on karna parta hai
    return conn
```

Isi file mein reporting period (`PERIOD_START`, `PERIOD_END`) aur plant codes bhi hain, jo holiday file mein use hote hain.

## 6. Stage 1: raw load (`ingestion/load_raw.py`)

**Maqsad:** har file ko database mein **bilkul waisa hi** copy karna jaisa mili. Yahan kuch trim, parse ya theek nahi hota. Is tarah raw layer hamesha asal file ki sachi copy rehti hai aur audit ho sakta hai.

- Har column `TEXT` ke tor par save hota hai.
- JSON files (`leave_requests.json`, `shifts.json`) mein har element ek row banta hai, `record_json` column mein. Abhi unhein khola (flatten) nahi jata.
- Har row ke saath 3 extra columns lagte hain: `_source_file` (kis file se aayi), `_loaded_at` (kab load hui), `_row_hash` (row ki values ka SHA-256 fingerprint).

**`_row_hash` kyun zaroori hai? Idempotency.** Hash table ki primary key hai aur rows `INSERT OR IGNORE` se daalte hain. Is liye wahi file doosri baar load karo to 0 rows add hoti hain, aur naye mahine ki file se sirf woh rows aati hain jo sach mein nayi hain.

```python
payload = [r + [path.name, loaded_at, row_hash(r)] for r in rows]
conn.executemany(f'INSERT OR IGNORE INTO raw."{table}" ({col_list}) VALUES ({placeholders})', payload)
```

Har load `raw._load_log` mein har file ki ek line likhta hai: file mein kitni rows, kitni insert hui, kitni pehle se thi, aur `MATCH`/`MISMATCH`. Mismatch ho to pipeline ruk jata hai.

## 7. Stage 2: safai aur milaan (clean + reconcile)

### 7a. Python hissa (`transform/stage2_clean.py`)
Jo kaam SQL mein mushkil hai woh Python karta hai. Har `build_*` function ek raw table parhta hai aur `write()` helper ke zariye ek ya zyada saaf `staging` tables likhta hai.

| Function | Data mein masla | Code kya karta hai |
|---|---|---|
| `parse_mixed_date` | Dates 3 formats mein (`2026-04-01`, `01/04/2026`, `01-Apr-2026`) | Har format baari baari try karta hai; anjaan format par zor se fail hota hai, andaaza nahi lagata |
| `build_departments` | Extra spaces, department ke naam badle hue | Text trim, `previous_name` rakhta hai, plant code jorta hai |
| `build_employees` | Ek `emp_id` do baar export hua; department free text mein likha hai | Sab se naye `updated_at` wali row rakhta hai (rule 1); kya farq tha woh `employee_merge_log` mein likhta hai. Department text ko naye ya purane naam se `dept_id` se milata hai |
| `build_employment_history` | `effective_to` overlap karta hai ya gap chhorta hai | Saaf SCD2 ranges banata hai: `valid_to = agli valid_from − 1 din` (rule 2). Har fix ki wajah `effective_to_fix` mein |
| `build_shifts` | JSON | Kholta hai. NIGHT shift agle din khatam hoti hai, is liye end time mein 1 din jorta hai |
| `build_roster` | Kuch hafton ka roster ghayab | Ghayab hafte mein pichle hafte ki shift (rule 6), flag `is_imputed = 1`. Phir har employee ki har din ki row (`roster_daily`) |
| `build_leave` | JSON ke andar nested approvals | Har request ki ek row, har approval step ki ek row. Leave tabhi valid jab Manager AUR HR dono approve karein aur cancel na hui ho (rule 16). Leave ke din mein Sunday aur plant holiday shamil nahi (rule 17) |
| `detect_clock_drift` | Ek machine ki ghari 1 ghanta aage | Neeche dekhein |

**Clock ki ghalti pakarna (rule 11).** Yeh hard-code nahi, data se khud dhoondha jata hai:
1. Normal shift (jo raat 12 baje paar nahi karti) wale har employee-din ke liye dekho: pehla punch shift shuru hone ke kitne minute baad hua.
2. Har machine aur har din ka median (beech wali value) nikalo. Usi din ki **baaqi sab machines** ke median se milao.
3. Agar ek machine kisi din se le kar aakhir tak har din 30 minute se zyada alag hai, to woh drift hai. Correction woh aam farq hai, 15 minute tak round kiya hua.

Natija: `DEV-SITE-01` 2026-07-01 se **+60 minute** aage hai (pehle median farq 0.1 minute, baad mein 59.8). Yeh `staging.device_clock_corrections` mein likha jata hai.

### 7b. SQL hissa (`transform/sql/02_punches.sql`)
Har raw punch do tables mein se sirf ek mein jata hai: `staging.punches` (rakha gaya) ya `staging.rejected_punches` (wajah ke saath).

1. **Jorna (map):** `device_id + device_user_id` se punch ko employee se jorte hain. Mapping na mile (contractor ya visitor) to punch `UNMAPPED_DEVICE_USER` ke saath reject.
2. **Clock theek karna:** drift wali machine ke punch se pakra hua offset minus.
3. **Duplicate hatana** `LAG()` se: agar usi employee ka pichla punch 120 second ke andar hai to yeh `DUPLICATE_WITHIN_2_MIN` hai.
   ```sql
   CAST(strftime('%s', punch_time) AS INTEGER)
     - CAST(strftime('%s', LAG(punch_time) OVER w) AS INTEGER) AS secs_since_prev
   ...
   WINDOW w AS (PARTITION BY emp_id ORDER BY punch_time, punch_id)
   ```
   `LAG()` har row ke saath usi employee ki **pichli** row ki value la deta hai, is liye do punches ka farq seconds mein nikal aata hai.
4. **Night shift (rule 7 aur 10):** NIGHT shift raat 22:00 shuru ho kar agle din subah 06:00 khatam hoti hai. Is liye NIGHT wale din ke baad subah ka punch **pichli date** ka hai. Lekin agar aaj DAY/GEN shift hai to woh aaj ka check-in hai. Natija `shift_date` mein.

## 8. Stage 3: rozana attendance (`transform/sql/03_attendance_daily.sql`)

Yeh period ke andar har employee ki, uski naukri ke har din ki ek row banata hai. Overtime ke saare numbers isi table se aate hain.

**Status (rule 12), isi tarteeb se check hota hai:**
```sql
CASE WHEN is_sunday = 1 AND punch_count = 0           THEN 'Weekly Off'
     WHEN holiday_name IS NOT NULL AND punch_count = 0 THEN 'Holiday'
     WHEN leave_request_id IS NOT NULL                 THEN 'On Leave'
     WHEN punch_count >= 2                             THEN 'Present'
     WHEN punch_count = 1                              THEN 'Missing Punch'
     ELSE 'Absent' END
```
- **Check-in / check-out:** us shift date ka pehla aur aakhri punch.
- **Late / early (rule 13):** sirf Present working din par, aur sirf 10 minute ki riayat (grace) ke baad.
- **Overtime (rule 14 aur 15):**
  - Working din par OT = shift khatam hone ke **baad** ka waqt.
  - Sunday ya holiday par **saara** kaam OT.
  - OT hamesha poore aadhe ghante tak **neeche** round hota hai. 59 minute = 0.5 ghanta, 60 minute = 1.0 ghanta.
  - Hisaab integer seconds mein hota hai (`secs / 1800 * 0.5`), is liye decimal ki koi ghalti nahi hoti.

## 9. Stage 4: star schema warehouse

| File | Kya karti hai |
|---|---|
| `warehouse/ddl/01_dimensions.sql` | `dim_date`, `dim_department`, `dim_shift`, `dim_employee` (SCD2: har naukri ke daur ki ek row, key `employee_sk`) |
| `warehouse/ddl/02_facts.sql` | `fact_attendance_daily`, `fact_leave_day`, `fact_overtime_approved`, `fact_payroll_line`; PRIMARY KEY, FOREIGN KEY aur CHECK ke saath |
| `warehouse/ddl/03_views.sql` | `v_employee_month`: har employee ke har mahine ki ek row: computed, approved, paid OT aur earnings, sahi department ke naam (rule 3) |
| `warehouse/load_warehouse.sql` | Staging se sab tables bharta hai |
| `warehouse/build_warehouse.py` | Upar wali files chalata hai, phir `PRAGMA foreign_key_check` (0 hona chahiye) |

**SCD2 join.** Jis employee ka department badla, uski `dim_employee` mein kai rows hain. Har fact row us version se judti hai jo **us din** valid tha:
```sql
JOIN warehouse.dim_employee de
  ON de.emp_id = a.emp_id AND a.work_date BETWEEN de.valid_from AND de.valid_to
```
**Mahine ke numbers ka department (rule 3):** mahine ke aakhri din ka department, ya agar banda usi mahine chala gaya to separation date ka department. Yeh logic sirf ek jagah `v_employee_month` mein hai, aur q05 se q09 tak usi ko use karte hain.

Diagram: [`warehouse/erd.png`](../warehouse/erd.png)

## 10. Stage 5: 10 business sawal

`analytics/run_questions.py` har `analytics/q*.sql` file chalata hai aur natija `analytics/results/<wohi naam>.csv` mein save karta hai. Har SQL file ke shuru mein comment hai ke sawal kya hai aur kaunsa rule laga.

| File | Sawal | SQL technique |
|---|---|---|
| `q01_headcount.sql` | Mahine ke aakhir mein plant aur department wise headcount | CTE, SCD2 date join |
| `q02_attrition.sql` | Har mahine attrition rate (kitne log chhor gaye) | opening/closing headcount, average |
| `q03_absenteeism.sql` | Plant wise ghair-hazri, approved leave ko chhor kar | conditional sums |
| `q04_late_arrivals.sql` | Sab se zyada late aane wale 10 log | `RANK()` window, barabar walay bhi dikhte hain |
| `q05_ot_computed_vs_approved_vs_paid.sql` | OT: kiya vs approve hua vs pay hua | `v_employee_month` |
| `q06_ot_overpaid_depts.sql` | Woh departments jinhein kiye se 15% zyada OT pay hua | totals par filter |
| `q07_paid_zero_attendance.sql` | Jinhein us mahine paise mile magar ek din bhi haazir nahi | pattern detection |
| `q08_paid_after_separation.sql` | Naukri chhorne ke baad bhi tankhwah | date comparison |
| `q09_payroll_cost_mom.sql` | Fi employee kharcha, pichle mahine ke muqable | `LAG()` window |
| `q10_leave_overuse.sql` | Annual leave hadd se zyada | aggregation vs limit |
| `bonus_recruitment_funnel.sql` | Applied → Hired funnel | conversion aur har stage ke median din |

Misaal, Q6 poora (Finding 1 yahin se aayi):
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
Matlab: har department ke 6 mahine ke totals nikalo, aur sirf woh dikhao jahan paid OT, computed OT × 1.15 se zyada hai.
Natija: Stitching (Faisalabad) ko 4,906 ghante kaam ke badle 7,659 ghante pay hue, yani **+56%**, taqreeban PKR 1.36M.

## 11. Stage 6: data quality checks (`quality/dq_checks.py`)

89 checks hain. Har check ek SQL query hai jo un rows ko ginti hai jo rule **torti** hain (0 = PASS). Natije time ke saath `warehouse.dq_results` mein save hote hain. Koi check fail ho to script exit code 1 deta hai aur pipeline ruk jata hai, taake ghalat data demo mein na jaye.

| Qism | Tadaad | Misaal |
|---|---|---|
| Primary key | 36 | `staging.punches.punch_id` unique hai aur khaali nahi |
| Referential integrity | 14 | har `fact_attendance_daily.employee_sk` `dim_employee` mein mojood hai |
| Reconciliation | 18 | raw punches = rakhe gaye punches + reject kiye gaye punches |
| Accepted values | 7 | attendance status sirf 6 allowed values mein se ek |
| Business sanity | 14 | SCD2 mein overlap ya gap nahi, OT poore aadhe ghante mein, koi shift 16 ghante se lambi nahi |

Reconciliation saabit karta hai ke koi data gum nahi hua: har raw row ya staging mein hai, ya kisi log/rejected table mein wajah ke saath.

## 12. Stage 7: dashboard, slides, ERD

- **`dashboard/app.py`** (Streamlit) warehouse aur result CSVs parhta hai. Tabs: CFO story, Overtime gap, Payroll leakage, 10 questions (chart, table aur SQL), Data quality, Pipeline, aur read-only SQL explorer. `q()` helper har query cache karta hai, is liye page tez chalta hai.
- **`presentation/make_visuals.py`** matplotlib se `warehouse/erd.png` aur 7 slides wali `presentation/slides.pdf` banata hai. Yeh wahi numbers use karta hai jo CSVs mein hain, is liye slides aur data kabhi alag nahi ho sakte.
- **`presentation/cfo_findings.md`** aur **`presentation/DEMO.md`** mein teen findings aur 5 minute ka demo script hai.

## 13. Asal example: ek din, ek punch se CFO ke number tak

Employee **E10580**, Cutting (Faisalabad), **4 April 2026**, roster par **DAY** shift (06:00–14:00, 10 minute grace).

| Step | Table | Kya hota hai |
|---|---|---|
| 1 | `raw.biometric_punches` | Machine `DEV-FSD-01` par 2 punch: `06:35:41` aur `15:06:08`, bilkul file jaisa text |
| 2 | `staging.punches` | Dono E10580 se jure. Machine mein drift nahi, duplicate nahi, is liye dono rakhe gaye, `shift_date = 2026-04-04` |
| 3 | `staging.attendance_daily` | 2 punch matlab **Present**. Check-in 06:35:41 shift shuru ke 35.7 minute baad, 10 minute grace se zyada, to **late = 1, late_minutes = 35.7**. Check-out 15:06:08 shift khatam (14:00) ke 3,968 second baad; 3,968 ÷ 1,800 = 2 poore aadhe ghante, to **ot_hours = 1.0**. Kaam = **8.51 ghante** |
| 4 | `warehouse.fact_attendance_daily` | Wohi row, us din valid E10580 ke `employee_sk` se juri |
| 5 | `warehouse.fact_overtime_approved` | Request `OT009972` mein **1.0 ghanta** approve hua aur us din computed OT bhi 1.0 hai, to dono barabar hain (sab jagah aisa nahi hota) |
| 6 | `warehouse.v_employee_month` | E10580 ke April ke totals mein jama: computed, approved, paid OT |
| 7 | `q04_late_arrivals.csv` | Yeh late din un 58 dinon mein se ek hai jinki wajah se E10580 **sab se zyada late aane wala #1** hai |
| 8 | `q05` / `q06` | Department aur mahine ke OT totals. Stitching mein paid ghante computed se bohat zyada hain, yahi Finding 1 hai |

Yahi raasta saare 322,143 rakhe gaye punches par chalta hai, aur dashboard ka har number isi tarah banta hai.

## 14. Teen findings kahan se aayi

| Finding | Paisa | Kis query se | Asaan matlab |
|---|---|---|---|
| 1. Stitching ko kaam se 56% zyada OT pay hua | PKR 1.36M | `q05`, `q06` | Approved ghante har mahine barhte gaye (762 se 1,779), asal kaam 764–920 ghante par hi raha |
| 2. 6 log jinhone kabhi punch nahi kiya, phir bhi har mahine tankhwah | PKR 2.88M | `q07` | Device par enroll hi nahi, attendance zero, tankhwah poori. Ho sakta hai "ghost employees" hon |
| 3. 5 log naukri chhorne ke baad bhi tankhwah lete rahe | PKR 1.95M | `q08` | Misaal: E10471 ne 2026-04-23 ko chhora, May se September tak PKR 660,000 milte rahe |

**Teen hal (fixes):**
1. OT punches se pay karo, approved ghanton ki hadd tak.
2. Jis mahine na punch ho na approved leave, us ki salary slip rok lo.
3. `separation_date` ke baad ka koi mahina payroll mein block.

## 15. Kuch badalna ho to kahan

| Aap chahte hain… | Yahan badlein |
|---|---|
| Reporting period badalna | `pipeline_config.py` mein `PERIOD_START` / `PERIOD_END` (ya `--period-end`) |
| Late grace ya OT rounding badalna | `transform/sql/03_attendance_daily.sql` (grace `shifts.json` se aata hai) |
| 2 minute duplicate wali hadd badalna | `transform/sql/02_punches.sql` (`secs_since_prev <= 120`) aur usi ka DQ check |
| Naya business sawal jorna | `analytics/q11_<naam>.sql` banao; `run_questions.py` khud utha lega |
| Naya data check jorna | `quality/dq_checks.py` mein `SANITY` (ya kisi aur list) mein ek line |
| Nayi raw file jorna | `ingestion/load_raw.py` mein `CSV_FILES` / `JSON_FILES` mein add karo, aur stage 2 mein `build_*` function likho |

## 16. Code parhne ka sahi tarteeb

Naye bande ke liye yeh tarteeb sab se aasaan hai:

1. `README.md`: project kya hai, kaise chalana hai.
2. `pipeline_config.py`: database kaise judta hai (50 lines).
3. `run_pipeline.py`: kaunsi stage kab chalti hai (70 lines).
4. `ingestion/load_raw.py`: raw load.
5. `transform/stage2_clean.py`: safai; har `build_*` function alag parhein.
6. `transform/sql/02_punches.sql`, phir `transform/sql/03_attendance_daily.sql`: punch se attendance tak.
7. `warehouse/ddl/*.sql`, phir `warehouse/load_warehouse.sql`: warehouse.
8. `analytics/q01…q10`: har file chhoti hai, shuru ka comment sawal batata hai.
9. `quality/dq_checks.py`: checks ki lists upar hain, chalane wala code neeche.
10. `dashboard/app.py`: aakhir mein.

**Tip:** kisi bhi table ka data dekhna ho to dashboard ke **SQL explorer** tab mein `SELECT * FROM staging.punches LIMIT 20` chalao.

## 17. Judges ke mumkina sawal aur jawab

**Q: PostgreSQL kyun nahi?**
Brief SQLite ki ijazat deta hai. Teen database files ko `raw`, `staging`, `warehouse` naam se attach kiya hai, is liye saari SQL PostgreSQL jaisi schema-qualified hai, aur install ki zaroorat nahi.

**Q: Kaise pata ke koi data gum nahi hua?**
18 reconciliation checks: har raw row ya staging mein hai ya rejected/log table mein wajah ke saath. Jaise 345,280 raw punches = 322,143 rakhe + 23,137 reject (6,962 bina mapping + 16,175 duplicate).

**Q: Code dobara chalayen to data double to nahi hoga?**
Nahi. `_row_hash` primary key hai aur `INSERT OR IGNORE` use hota hai. Doosri baar chalane par saari 12 files mein 0 naye rows aate hain; yeh test kiya hua hai.

**Q: Clock ki ghalti hard-code ki hai?**
Nahi. Har machine ka rozana median baaqi machines se milaya jata hai. `DEV-SITE-01` khud pakri gayi: 1 July se +60 minute.

**Q: Overtime ka hisaab kaise?**
Shift khatam hone ke baad ka waqt, poore aadhe ghante tak neeche round. Integer seconds ÷ 1800, is liye decimal ki ghalti nahi.

**Q: Naya mahina aaye to?**
`python run_pipeline.py --incremental <file> --period-end <date>`. Sirf naye punches add hote hain, phir sab dobara banta hai.
