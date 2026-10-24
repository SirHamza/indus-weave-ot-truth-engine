"""Create a synthetic 7th month of punches (Oct 2026) to demo the incremental load.

Takes the 20 Aug - 19 Sep punches, moves them +42 days (same weekday, same 3-week DAY/EVE/NIGHT rotation) and gives them new punch_ids.
Output: data/incoming/biometric_punches_2026_10.csv  (raw files in data/raw are never touched).
"""
import csv
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src, out = ROOT / "data" / "raw" / "biometric_punches.csv", ROOT / "data" / "incoming" / "biometric_punches_2026_10.csv"
out.parent.mkdir(parents=True, exist_ok=True)
with src.open(encoding="utf-8") as fi, out.open("w", newline="", encoding="utf-8") as fo:
    reader, writer = csv.DictReader(fi), csv.writer(fo)
    writer.writerow(reader.fieldnames)
    n = 0
    for row in reader:
        t = datetime.strptime(row["punch_time"], "%Y-%m-%d %H:%M:%S")
        # Copy one month of real punches 6 weeks forward, with new punch IDs so they count as new rows.
        if datetime(2026, 8, 20) <= t < datetime(2026, 9, 20):
            n += 1
            writer.writerow([f"P9{n:07d}", row["device_id"], row["device_user_id"],
                             (t + timedelta(days=42)).strftime("%Y-%m-%d %H:%M:%S")])
print(f"wrote {n} October punches -> {out}")
