"""Command line: grade an answer, or rebuild the suite.

    lae grade la01_serial_dilution answer.json     # answer as JSON or as text with <EVAL_ANSWER>...</EVAL_ANSWER>
    lae grade-reads la01_serial_dilution reads.csv # a plate-reader export: plate,well,rfu (plate = assay or blank)
    lae build
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .build import ROOT
from .build import main as build_main
from .grade import grade
from .reader import csv_to_reads, grade_reads, read_export


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="lae")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("grade", help="grade one answer against one task")
    g.add_argument("task_id")
    g.add_argument("answer", type=Path)
    r = sub.add_parser("grade-reads", help="grade a plate-reader export for a task that has a physical grader")
    r.add_argument("task_id")
    r.add_argument("reads", type=Path)
    sub.add_parser("build", help="rebuild evals/, results/ and docs/ and check every scripted control")
    args = ap.parse_args(argv)
    if args.cmd == "build":
        return build_main()
    if args.cmd == "grade-reads":
        rec = json.loads((ROOT / "evals" / args.task_id / "eval.json").read_text())
        if "physical_grader" not in rec:
            ap.error(f"{args.task_id} has no plate-reader grader")
        result = grade_reads(csv_to_reads(read_export(args.reads)), rec["physical_grader"]["checks"])
        print(json.dumps(result, indent=1))
        return 0 if result["passed"] else 1
    rec = json.loads((ROOT / "evals" / args.task_id / "eval.json").read_text())
    result = grade(args.answer.read_text(), rec["grader"]["config"])
    print(json.dumps(result, indent=1))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
