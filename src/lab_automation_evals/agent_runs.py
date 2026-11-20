"""Grade recorded agent runs and write results/agent_runs.csv.

Each run lives in results/agent_runs/<batch>/<task_id>.json as:
    {"task": ..., "model": ..., "harness": ..., "date": ..., "blinding": ..., "answer": {...}, "approach": ..., "doubts": ...}

    python -m lab_automation_evals.agent_runs
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from .grade import grade

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "results" / "agent_runs"


def grade_all() -> list:
    rows = []
    for path in sorted(RUNS.glob("*/*.json")):
        run = json.loads(path.read_text())
        rec = json.loads((ROOT / "evals" / run["task"] / "eval.json").read_text())
        g = grade(run["answer"], rec["grader"]["config"])
        rows.append({
            "batch": path.parent.name,
            "task": run["task"],
            "model": run["model"],
            "harness": run["harness"],
            "date": run["date"],
            "passed": "pass" if g["passed"] else "fail",
            "score": f"{g['score']:.4f}",
            "failed_checks": " ".join(k for k, v in g["fields"].items() if not v["passed"]),
            "tips_used": g.get("run", {}).get("tips_used", ""),
            "file": str(path.relative_to(ROOT)),
        })
    return rows


def main() -> int:
    rows = grade_all()
    if not rows:
        print("no recorded agent runs")
        return 0
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0]), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    (ROOT / "results" / "agent_runs.csv").write_text(buf.getvalue())
    for r in rows:
        print(f"{r['batch']} {r['task']:24s} {r['passed']}  {r['failed_checks']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
