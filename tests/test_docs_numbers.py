"""Every number the README and docs state is recomputed from the result tables."""

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _flat(path):
    return " ".join((ROOT / path).read_text().split())


README = _flat("README.md")
SCIENTISTS = _flat("docs/WORKING_WITH_SCIENTISTS.md")
PLATE_READER = _flat("docs/PLATE_READER.md")
CONTROLS = list(csv.DictReader(open(ROOT / "results/controls.csv")))
READER = list(csv.DictReader(open(ROOT / "results/reader_controls.csv")))
NOISE = {r["reader_cv"]: r for r in csv.DictReader(open(ROOT / "results/reader_noise.csv"))}


def test_control_counts():
    n = len(CONTROLS)
    n_pass = sum(r["expected"] == "pass" for r in CONTROLS)
    n_fail = sum(r["expected"] == "fail" for r in CONTROLS)
    assert all(r["behaves_as_expected"] == "yes" for r in CONTROLS)
    assert f"{n} controls in all: {n_pass} must pass, {n_fail} must fail, and all {n} do" in README


def test_reader_counts():
    wrong = [r for r in READER if r["simulator_grader"] == "fail"]
    no_plate = [r for r in wrong if r["reader_failed_checks"] == "run_completes"]
    readable = [r for r in wrong if r not in no_plate]
    caught = [r for r in readable if r["reader_observed"] == "fail"]
    missed = len(readable) - len(caught)
    assert all(r["behaves_as_expected"] == "yes" for r in READER)
    assert f"Of the {len(wrong)} named mistakes, {len(no_plate)} stops the run" in README
    assert f"Of the {len(readable)} that leave a plate, the reader grader catches {len(caught)}" in README
    assert f"misses {missed} of the {len(readable)} named mistakes that leave a plate to read" in SCIENTISTS
    assert f"the other {len(readable)} show {missed} blind spots" in PLATE_READER
    assert f"Of the {len(wrong)} named mistakes on la01, {len(no_plate)} stops the run" in PLATE_READER


def test_noise_table():
    n2, n3, n4, n5 = (NOISE[k] for k in ("0.02", "0.03", "0.04", "0.05"))
    d = n2["draws"]
    assert n2["reference_passed"] == n3["reference_passed"] == d
    refused4 = n4["reference_plate_refused"]
    assert (f"At the modelled reader noise (2% CV) and at 3%, the correct plan passes in {d} of {d} draws. "
            f"At 4% it passes in {n4['reference_passed']} ({refused4} plate{'' if refused4 == '1' else 's'} refused "
            f"as unusable, {n4['reference_wrong_verdict']} wrong verdicts); at 5%, in {n5['reference_passed']} "
            f"({n5['reference_plate_refused']} refused, {n5['reference_wrong_verdict']} wrong).") in README
    for cv, label in (("0.02", "2% (modelled)"), ("0.03", "3%"), ("0.04", "4%"), ("0.05", "5%")):
        r = NOISE[cv]
        row = (f"| {label} | {r['reference_passed']} of {r['draws']} | {r['reference_plate_refused']} | "
               f"{r['reference_wrong_verdict']} |")
        assert row in PLATE_READER, row
    m = n2["mistakes"]
    assert all(r["mistakes_caught_in_every_draw"] == m for r in NOISE.values())
    per = n2["draws_per_mistake"]
    assert f"each of the {m} mistakes the reader can see is caught in all {per} draws" in PLATE_READER
    assert f"Every mistake the reader can see is caught in all {per} draws at every noise level" in README


def test_decision_alone_is_not_enough():
    wrong = [r for r in CONTROLS if r["task"] == "la05_dye_qc" and r["expected"] == "fail"]
    right_call = [r for r in wrong if "decision" not in r["failed_checks"].split()]
    assert f"{len(right_call)} of the {len(wrong)} scripted wrong answers still reach the right call" in README
    assert f"would pass all {len(right_call)}" in README


def test_task_count():
    assert README.startswith("# lab-automation-evals")
    assert f"{len({r['task'] for r in CONTROLS})} evaluation tasks" in README


def test_agent_runs():
    runs = list(csv.DictReader(open(ROOT / "results/agent_runs.csv")))
    n_pass = sum(r["passed"] == "pass" for r in runs)
    assert f"First agent runs: {n_pass} of {len(runs)} passed" in README
    assert len({r["task"] for r in runs}) == len(runs)  # one run per task
