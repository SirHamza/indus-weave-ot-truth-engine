"""One-command rebuild: raw files -> raw -> staging -> warehouse -> answers -> data-quality checks.

    python run_pipeline.py                         # full, idempotent rebuild from data/raw
    python run_pipeline.py --fresh                 # delete the databases first (clean-machine run)
    python run_pipeline.py --incremental data/incoming/biometric_punches_2026_10.csv --period-end 2026-10-31
                                                   # append only NEW punch rows, then rebuild downstream

Each stage runs as its own process so a failure stops the pipeline with that stage's error.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from pipeline_config import DB_DIR, ROOT

STAGES = [
    ("1 ingest raw", ["ingestion/load_raw.py"]),
    ("2 clean -> staging", ["transform/stage2_clean.py"]),
    ("3 attendance_daily", ["transform/stage3_attendance.py"]),
    ("4 warehouse", ["warehouse/build_warehouse.py"]),
    ("5 business questions", ["analytics/run_questions.py"]),
    ("5b recruitment funnel (bonus)", ["analytics/recruitment_funnel.py"]),
    ("6 data-quality checks", ["quality/dq_checks.py"]),
    ("7 ERD + slides", ["presentation/make_visuals.py"]),
]


def run(name: str, args: list[str], env: dict) -> None:
    started = time.time()
    print(f"\n=== Stage {name} ===", flush=True)
    proc = subprocess.run([sys.executable, *args], cwd=ROOT, env=env)
    if proc.returncode != 0:
        raise SystemExit(f"Stage '{name}' failed (exit {proc.returncode}). Fix the error above and re-run.")
    print(f"--- {name} done in {time.time() - started:.1f}s", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fresh", action="store_true", help="drop the SQLite databases before loading")
    ap.add_argument("--incremental", type=Path, help="new biometric punches CSV to append (rows already loaded are skipped)")
    ap.add_argument("--period-end", help="extend attendance beyond 2026-09-30 (e.g. 2026-10-31 for a 7th month)")
    args = ap.parse_args()

    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    if args.period_end:
        env["PERIOD_END"] = args.period_end
    if args.fresh and DB_DIR.exists():
        shutil.rmtree(DB_DIR)
        print(f"Removed {DB_DIR}")

    started = time.time()
    stages = list(STAGES)
    if args.incremental:
        # Pehle baseline raw load (idempotent, 0 naye rows), phir sirf nayi file ke naye rows.
        stages.insert(1, ("1b incremental punches", ["ingestion/load_raw.py", "--file", str(args.incremental),
                                                    "--table", "biometric_punches"]))
    for name, cmd in stages:
        run(name, cmd, env)
    print(f"\nPipeline finished in {time.time() - started:.1f}s. Answers: analytics/results/  DQ: warehouse.dq_results")


if __name__ == "__main__":
    main()
