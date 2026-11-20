"""Every scripted control behaves as declared, graded from the shipped eval.json files."""

import json
from pathlib import Path

import pytest

from lab_automation_evals.grade import grade, parse_answer
from lab_automation_evals.reader import csv_to_reads, grade_plan_by_reader, grade_reads
from lab_automation_evals.tasks import ALL_TASKS

ROOT = Path(__file__).resolve().parents[1]
TASKS = [m.build() for m in ALL_TASKS]
CASES = [(t, c) for t in TASKS for c in t.controls]


def _shipped(task_id):
    return json.loads((ROOT / "evals" / task_id / "eval.json").read_text())


@pytest.mark.parametrize("task,control", CASES, ids=[f"{t.id}:{c.name}" for t, c in CASES])
def test_control(task, control):
    g = grade(control.answer, _shipped(task.id)["grader"]["config"])
    failed = {k for k, v in g["fields"].items() if not v["passed"]}
    assert g["passed"] == control.expect_pass, failed
    assert set(control.must_fail) <= failed


def test_every_task_has_passing_and_failing_controls():
    for t in TASKS:
        assert sum(c.expect_pass for c in t.controls) >= 2, t.id
        wrong = [c for c in t.controls if not c.expect_pass]
        assert len(wrong) >= 4, t.id
        assert all(c.must_fail for c in wrong), t.id


def test_every_check_is_failed_by_a_named_mistake_that_runs():
    """No check is decoration: for each one, a named mistake whose run completes fails it.

    `run_completes` is the exception: only a run that stops can fail it, and some control must."""
    for t in TASKS:
        cfg = _shipped(t.id)["grader"]["config"]
        hit_by_completed, hit_any = set(), set()
        for c in t.controls:
            if c.expect_pass:
                continue
            g = grade(c.answer, cfg)
            failed = {k for k, v in g["fields"].items() if not v["passed"]}
            hit_any |= failed
            if g.get("run", {}).get("completed", True):
                hit_by_completed |= failed
        for chk in cfg["checks"]:
            pool = hit_any if chk["type"] == "run_completes" else hit_by_completed
            assert chk["name"] in pool, (t.id, chk["name"])


def test_reader_grader_matches_declared_expectations():
    for t in TASKS:
        if not t.physical:
            continue
        rec = _shipped(t.id)
        for c in t.controls:
            g = grade_plan_by_reader(c.answer, rec["grader"]["config"], rec["physical_grader"])
            assert g["passed"] == t.reader_expect[c.name][0], c.name


def test_shipped_reference_reads_pass_and_tampering_fails():
    text = (ROOT / "evals/la01_serial_dilution/physical/simulated_reads_reference.csv").read_text()
    cfg = _shipped("la01_serial_dilution")["physical_grader"]["checks"]
    reads = csv_to_reads(text)
    assert grade_reads(reads, cfg)["passed"]
    reads["assay"]["C12"] += 500.0  # dye in a control well
    assert not grade_reads(reads, cfg)["fields"]["controls_clean"]["passed"]


def test_answer_parsing():
    assert parse_answer('noise <EVAL_ANSWER>{"a": 1}</EVAL_ANSWER> noise') == {"a": 1}
    assert parse_answer('{"a": 1}') == {"a": 1}
    assert parse_answer("[1, 2]") is None
    assert parse_answer("not json") is None
    t = TASKS[0]
    g = grade("I could not do it.", _shipped(t.id)["grader"]["config"])
    assert not g["passed"] and g["score"] == 0.0
