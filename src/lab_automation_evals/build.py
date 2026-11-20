"""Write every task to evals/, grade every scripted control from the written files, and write the tables and docs.

    python -m lab_automation_evals.build

Running it twice changes nothing; CI fails if a rebuild changes any tracked file.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path

from .environment import RULES_MD
from .grade import grade
from .reader import grade_plan_by_reader, reads_to_csv
from .tasks import ALL_TASKS
from .tasks.common import CANARY

ROOT = Path(__file__).resolve().parents[2]


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _json(obj) -> str:
    return json.dumps(obj, indent=1, sort_keys=False) + "\n"


def eval_record(task, files: dict) -> dict:
    return {
        "id": task.id,
        "canary": CANARY,
        "task": task.prompt,
        "data_node": None,
        "data_files": [
            {"name": name, "path": f"evals/{task.id}/workspace/{name}",
             "sha256": hashlib.sha256(text.encode()).hexdigest(), "bytes": len(text.encode())}
            for name, text in files.items()
        ],
        "grader": task.grader,
        "metadata": {**task.metadata, "title": task.title, "kind": task.kind},
        "notes": f"{task.tests} Named wrong analyses the scripted controls cover: {'; '.join(task.traps)}.",
        **({"physical_grader": task.physical} if task.physical else {}),
    }


def run_controls(task, grader: dict) -> list:
    rows = []
    for c in task.controls:
        g = grade(c.answer, grader["config"])
        failed = [k for k, v in g["fields"].items() if not v["passed"]]
        behaves = g["passed"] == c.expect_pass and all(f in failed for f in c.must_fail)
        rows.append({
            "task": task.id,
            "control": c.name,
            "expected": "pass" if c.expect_pass else "fail",
            "observed": "pass" if g["passed"] else "fail",
            "behaves_as_expected": "yes" if behaves else "NO",
            "failed_checks": " ".join(failed),
            "score": f"{g['score']:.4f}",
            "tips_used": g.get("run", {}).get("tips_used", ""),
            "what_it_does": c.why,
        })
    return rows


def run_reader_controls(task, rec: dict) -> tuple[list, str]:
    rows, ref_csv = [], ""
    for c in task.controls:
        g = grade_plan_by_reader(c.answer, rec["grader"]["config"], rec["physical_grader"])
        expect_pass, why = task.reader_expect[c.name]
        failed = [k for k, v in g["fields"].items() if not v["passed"]]
        rows.append({
            "task": task.id,
            "control": c.name,
            "simulator_grader": "pass" if c.expect_pass else "fail",
            "reader_expected": "pass" if expect_pass else "fail",
            "reader_observed": "pass" if g["passed"] else "fail",
            "behaves_as_expected": "yes" if g["passed"] == expect_pass else "NO",
            "reader_failed_checks": " ".join(failed),
            "why": why,
        })
        if c.name == "reference":
            ref_csv = reads_to_csv(g["reads"])
    return rows, ref_csv


NOISE_CVS = (0.02, 0.03, 0.04, 0.05)
NOISE_DRAWS = 200
MISTAKE_DRAWS = 50


def reader_noise_rows(task, rec: dict) -> list:
    """How the reader grader holds up as the reader gets noisier than modelled (fresh noise draws, not the shipped one)."""
    import copy

    out = []
    cfg = rec["grader"]["config"]
    ref = next(c for c in task.controls if c.name == "reference").answer
    mistakes = [c for c in task.controls if not task.reader_expect[c.name][0]
                and grade(c.answer, cfg).get("run", {}).get("completed")]
    for cv in NOISE_CVS:
        reader = copy.deepcopy(rec["physical_grader"])
        reader["model"]["cv"] = cv
        passed = refused = wrong = 0
        for k in range(NOISE_DRAWS):
            g = grade_plan_by_reader(ref, cfg, reader, tag=f"noise{cv}:{k}")
            if g["passed"]:
                passed += 1
            elif not g["fields"]["reader_input"]["passed"]:
                refused += 1
            else:
                wrong += 1
        always = sum(all(not grade_plan_by_reader(c.answer, cfg, reader, tag=f"noise{cv}:{k}")["passed"]
                         for k in range(MISTAKE_DRAWS)) for c in mistakes)
        out.append({"reader_cv": f"{cv:.2f}", "draws": NOISE_DRAWS, "reference_passed": passed,
                    "reference_plate_refused": refused, "reference_wrong_verdict": wrong,
                    "mistakes_caught_in_every_draw": always, "mistakes": len(mistakes),
                    "draws_per_mistake": MISTAKE_DRAWS})
    return out


def reader_md(rows) -> str:
    out = ["", "## The plate-reader grader (la01)", "",
           "The same plans, graded only from what a plate reader would see after the run with a fluorescent dye in "
           "place of the compounds: clean control wells, equal top wells, and a 3-fold drop between neighbouring "
           "columns above the detection limit. See [PLATE_READER.md](PLATE_READER.md).", "",
           "| Control | Simulator grader | Reader grader | Note |", "|---|---|---|---|"]
    for r in rows:
        out.append(f"| `{r['control']}` | {r['simulator_grader']} | {r['reader_observed']} | {r['why'] or '-'} |")
    return "\n".join(out) + "\n"


def tasks_md(tasks, rows) -> str:
    out = ["# The tasks", "",
           "Generated by `python -m lab_automation_evals.build`. Do not edit by hand.", "",
           "| Task | Kind | What it tests | Checks | Controls that must pass | Named mistakes that must fail |",
           "|---|---|---|---|---|---|"]
    for t in tasks:
        mine = [r for r in rows if r["task"] == t.id]
        n_pass = sum(r["expected"] == "pass" for r in mine)
        n_fail = sum(r["expected"] == "fail" for r in mine)
        checks = ", ".join(f"`{c['name']}`" for c in t.grader["config"]["checks"])
        out.append(f"| [`{t.id}`](../evals/{t.id}/eval.json) | {t.kind} | {t.tests} | {checks} | {n_pass} | {n_fail} |")
    out += ["", "## Scripted controls, task by task", ""]
    for t in tasks:
        out += [f"### {t.id}: {t.title}", "", "| Control | Expected | Observed | Fails on | What it does |",
                "|---|---|---|---|---|"]
        for r in rows:
            if r["task"] == t.id:
                fails = ", ".join(f"`{x}`" for x in r["failed_checks"].split()) or "-"
                out.append(f"| `{r['control']}` | {r['expected']} | {r['observed']} | {fails} | {r['what_it_does']} |")
        out.append("")
    return "\n".join(out)


def main() -> int:
    tasks = [t.build() for t in ALL_TASKS]
    manifest = []
    rows = []
    reader_rows = []
    noise_rows = []
    for t in tasks:
        files = {"environment.md": RULES_MD}
        for name, content in t.workspace.items():
            files[name] = content if isinstance(content, str) else _json(content)
        base = ROOT / "evals" / t.id
        for name, text in files.items():
            _write(base / "workspace" / name, text)
        rec = eval_record(t, files)
        _write(base / "eval.json", _json(rec))
        written = json.loads((base / "eval.json").read_text())
        rows += run_controls(t, written["grader"])
        if t.physical:
            rrows, ref_csv = run_reader_controls(t, written)
            reader_rows += rrows
            noise_rows += reader_noise_rows(t, written)
            _write(base / "physical" / "simulated_reads_reference.csv", ref_csv)
        manifest.append({"id": t.id, "title": t.title, "kind": t.kind, "path": f"evals/{t.id}/eval.json"})
    _write(ROOT / "evals" / "manifest.json", _json({"canary": CANARY, "tasks": manifest}))
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0]), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    _write(ROOT / "results" / "controls.csv", buf.getvalue())
    _write(ROOT / "docs" / "ENVIRONMENT.md", RULES_MD)
    _write(ROOT / "docs" / "TASKS.md", tasks_md(tasks, rows) + reader_md(reader_rows))
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(reader_rows[0]), lineterminator="\n")
    w.writeheader()
    w.writerows(reader_rows)
    _write(ROOT / "results" / "reader_controls.csv", buf.getvalue())
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(noise_rows[0]), lineterminator="\n")
    w.writeheader()
    w.writerows(noise_rows)
    _write(ROOT / "results" / "reader_noise.csv", buf.getvalue())
    from .agent_runs import main as write_agent_runs

    write_agent_runs()
    bad = [r for r in rows + reader_rows if r["behaves_as_expected"] != "yes"]
    n = len(rows)
    nb = len([r for r in bad if r in rows])
    print(f"{len(tasks)} tasks, {n} scripted controls, {n - nb} behave as expected")
    blind = sum(1 for r in reader_rows if r["simulator_grader"] == "fail" and r["reader_observed"] == "pass")
    print(f"plate-reader grader: {len(reader_rows)} controls, "
          f"{sum(r['behaves_as_expected'] == 'yes' for r in reader_rows)} behave as expected, {blind} known blind spots")
    for r in bad:
        print("  MISBEHAVES:", r)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
