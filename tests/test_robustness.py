"""Hostile answers and messy reader exports fail cleanly; nothing an agent or a reader sends can crash the grader."""

import copy
import json
from pathlib import Path

import pytest

from lab_automation_evals.grade import grade
from lab_automation_evals.reader import csv_to_reads, grade_plan_by_reader, grade_reads, reads_to_csv
from lab_automation_evals.sim import run
from lab_automation_evals.tasks import ALL_TASKS
from lab_automation_evals.tasks import la01_serial_dilution as la01

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = {m.ID: json.loads((ROOT / "evals" / m.ID / "eval.json").read_text()) for m in ALL_TASKS}
PICK = {"op": "pick_up_tips", "rack": "tips", "column": 1}

HOSTILE_PLANS = [
    [{"op": "aspirate", "labware": ["x"], "volume_ul": 5}],
    [{"op": "pick_up_tips", "rack": {}, "column": 1}],
    [PICK, {"op": "aspirate", "labware": "buffer", "volume_ul": 10**400}],
    [PICK, {"op": "aspirate", "labware": "buffer", "volume_ul": float("nan")}],
    [PICK, {"op": "aspirate", "labware": "buffer", "volume_ul": float("inf")}],
    [PICK, {"op": "aspirate", "labware": "buffer", "volume_ul": -5}],
    [PICK, {"op": "aspirate", "labware": "buffer", "column": True, "volume_ul": 5}],
    [PICK, {"op": "mix", "labware": "assay", "column": 1, "volume_ul": 5, "cycles": True}],
    [{"op": "pick_up_tips", "rack": "tips", "column": 1, "channels": [[1]]}],
    [{"op": "pick_up_tips", "rack": "tips", "column": 1, "rows": [None] * 8}],
    [None, 7, "step"],
    {"not": "a list"},
]

HOSTILE_ANSWERS = [
    "[" * 100000 + "]" * 100000,
    '{"decision": "no_go", "failing_channels": [Infinity], "worst_channel_mean_ul": NaN}',
    {"decision": ["no_go"], "failing_channels": {"6": 1}, "worst_channel_mean_ul": 10**400},
    {"failing_channels": [6.5, True, None], "worst_channel_mean_ul": "47"},
    {"hits": [{"source_plate": None, "source_well": 5, "dest_well": []}], "plan": []},
    {"hits": "P1:B3", "plan": None},
    {"wells_to_repeat": [{"well": "C4"}, ["E7"], 10**400]},
    {"first_error_step": 10**400, "error_class": {}, "corrected_plan": [[]]},
    {"failed_samples": [None, 3, "Z99"], "plan": "pick up tips"},
    "",
    "null",
]


@pytest.mark.parametrize("plan", HOSTILE_PLANS)
def test_hostile_plans_stop_cleanly(plan):
    res = run(la01.DECK, plan)
    assert not res.ok and res.error is not None
    g = grade({"plan": plan}, CONFIGS["la01_serial_dilution"]["grader"]["config"])
    assert not g["passed"]


def test_nan_dispense_cannot_overfill():
    plan = [{"op": "pick_up_tips", "rack": "tips", "column": 1, "channels": [1]},
            {"op": "aspirate", "labware": "buffer", "volume_ul": 300, "channels": [1]},
            {"op": "dispense", "labware": "assay", "column": 1, "volume_ul": 300, "channels": [1]},
            {"op": "aspirate", "labware": "buffer", "volume_ul": 300, "channels": [1]},
            {"op": "dispense", "labware": "assay", "column": 1, "volume_ul": float("nan"), "channels": [1]}]
    res = run(la01.DECK, plan)
    assert not res.ok and "finite" in res.error.message


@pytest.mark.parametrize("task_id", list(CONFIGS))
@pytest.mark.parametrize("answer", HOSTILE_ANSWERS, ids=range(len(HOSTILE_ANSWERS)))
def test_hostile_answers_never_crash(task_id, answer):
    g = grade(answer, CONFIGS[task_id]["grader"]["config"])
    assert not g["passed"]
    assert set(g["fields"]) == {c["name"] for c in CONFIGS[task_id]["grader"]["config"]["checks"]}


def test_lenient_formatting_where_formatting_is_not_the_point():
    rec = CONFIGS["la04_find_the_error"]
    ref = next(c for c in la01_like("la04_find_the_error") if c.name == "reference").answer
    g = grade({**ref, "first_error_step": "5", "error_class": "  USED_TIP_CONTAMINATES_A_SOURCE "}, rec["grader"]["config"])
    assert g["passed"]


def la01_like(task_id):
    mod = next(m for m in ALL_TASKS if m.ID == task_id)
    return mod.build().controls


def test_same_liquid_twice_stays_one_layer():
    plan = la01.reference()
    i = next(k for k, s in enumerate(plan) if s.get("op") == "dispense" and s.get("column") == 12)
    split = [{"op": "aspirate", "labware": "buffer", "volume_ul": 50.0},
             {"op": "dispense", "labware": "assay", "column": 12, "volume_ul": 50.0}] * 2
    plan = plan[: i - 1] + split + plan[i + 1:]
    assert grade({"plan": plan}, CONFIGS["la01_serial_dilution"]["grader"]["config"])["passed"]


# ---------- reader exports ----------

def _reference_reads():
    task = la01.build()
    g = grade_plan_by_reader(task.controls[0].answer, CONFIGS["la01_serial_dilution"]["grader"]["config"],
                             CONFIGS["la01_serial_dilution"]["physical_grader"])
    return g["reads"]


CFG = la01.READER["checks"]


def _variant(transform):
    return csv_to_reads(transform(reads_to_csv(_reference_reads())))


@pytest.mark.parametrize("name,transform", [
    ("bom", lambda t: chr(0xFEFF) + t),
    ("capital headers", lambda t: t.replace("plate,well,rfu", "Plate,Well,RFU", 1)),
    ("semicolons and decimal commas", lambda t: t.replace(",", ";").replace(".", ",")),
    ("tabs", lambda t: t.replace(",", "\t")),
    ("zero-padded wells", lambda t: "\n".join(
        line.replace(",A1,", ",A01,").replace(",B1,", ",B01,") for line in t.splitlines()) + "\n"),
    ("number-first wells", lambda t: t.replace("assay,C3,", "assay,3C,")),
    ("blank labels", lambda t: t.replace("\nblank,", "\nBlank plate,")),
    ("trailing empty lines", lambda t: t + "\n\n,,\n"),
])
def test_ordinary_reader_exports_parse(name, transform):
    reads = _variant(transform)
    assert not reads["problems"], reads["problems"]
    assert grade_reads(reads, CFG)["passed"], name


@pytest.mark.parametrize("name,transform,expect", [
    ("overflow cell", lambda t: t.replace("assay,A1,", "assay,A1,OVRFLW #", 1), "unreadable or ambiguous value"),
    ("empty cell", lambda t: t.replace("assay,B5,", "assay,B5,,#", 1), "unreadable or ambiguous value"),
    ("spreadsheet summary row", lambda t: t + "Blank SD,,5.1\n", "unknown plate label"),
    ("missing column", lambda t: t.replace("plate,well,rfu", "plate,well,signal_x", 1), "need columns"),
    ("duplicate well", lambda t: t + "assay,A1,150.0\n", "appears twice"),
    ("bad well", lambda t: t + "assay,Q7,150.0\n", "unreadable well"),
    ("unknown plate", lambda t: t + "plate2,A1,150.0\n", "unknown plate label"),
])
def test_unusable_exports_fail_with_a_reason(name, transform, expect):
    reads = _variant(transform)
    g = grade_reads(reads, CFG)
    assert not g["passed"] and not g["fields"]["reader_input"]["passed"]
    assert expect in g["fields"]["reader_input"]["detail"], g["fields"]["reader_input"]["detail"]


def test_missing_or_nan_controls_never_count_as_clean():
    reads = _reference_reads()
    for r in "ABCDEFGH":
        del reads["assay"][f"{r}12"]
    assert not grade_reads(reads, CFG)["fields"]["controls_clean"]["passed"]
    reads = _reference_reads()
    reads["assay"]["D12"] = float("nan")
    reads["blank"][0] = float("nan")
    g = grade_reads(reads, CFG)
    assert not g["passed"] and not g["fields"]["controls_clean"]["passed"]


def test_scaled_plate_fails_against_the_standard():
    reads = _reference_reads()
    for factor in (0.5, 1.5):
        scaled = copy.deepcopy(reads)
        b = sum(scaled["blank"]) / len(scaled["blank"])
        scaled["assay"] = {w: b + (v - b) * factor for w, v in scaled["assay"].items()}
        g = grade_reads(scaled, CFG)
        assert not g["fields"]["top_matches_standard"]["passed"], factor


def test_reader_verdicts_hold_across_fresh_noise():
    """Each control's reader verdict is the same on 60 independent noise draws, not just the shipped one."""
    task = la01.build()
    rec = CONFIGS["la01_serial_dilution"]
    for c in task.controls:
        want = la01.READER_EXPECT[c.name][0]
        for k in range(60):
            g = grade_plan_by_reader(c.answer, rec["grader"]["config"], rec["physical_grader"], tag=f"draw{k}")
            assert g["passed"] == want, (c.name, k, g["fields"])


def test_ambiguous_thousands_or_decimals_are_refused_not_guessed():
    from lab_automation_evals.reader import _decimal_mark, _number

    assert _number("12,345", None) is None and _number("12.345", None) is None
    assert _number("12,345", ".") == 12345.0 and _number("12,345", ",") == 12.345
    assert _number("1,234.5", None) == 1234.5 and _number("1.234,5", None) == 1234.5
    assert _decimal_mark(["150.2", "12,345"]) == "."  # 150.2 settles it: the comma groups thousands
    assert _decimal_mark(["150,25", "1.234"]) == ","
    assert _decimal_mark(["12,345", "98,765"]) is None
    reads = csv_to_reads("plate,well,rfu\nassay,A1,\"12,345\"\n")
    assert reads["problems"] and "ambiguous" in reads["problems"][0]


def test_utf16_and_latin1_exports_are_read(tmp_path):
    from lab_automation_evals.reader import read_export

    text = reads_to_csv(_reference_reads())
    (tmp_path / "u16.csv").write_bytes(text.encode("utf-16"))
    (tmp_path / "l1.csv").write_bytes(text.replace("rfu", "rfu (" + chr(0xB5) + "W)", 1).encode("latin-1"))
    assert grade_reads(csv_to_reads(read_export(tmp_path / "u16.csv")), CFG)["passed"]
    reads = csv_to_reads(read_export(tmp_path / "l1.csv"))
    assert reads["problems"]  # the value column is no longer called rfu: refused with a reason, not a crash


def test_one_stray_standard_cannot_rescue_a_weak_plate():
    reads = _reference_reads()
    b = sum(reads["blank"]) / len(reads["blank"])
    reads["assay"] = {w: b + (v - b) * 0.80 for w, v in reads["assay"].items()}
    for bump in (1.16, 1.3, 1.6):
        r = copy.deepcopy(reads)
        r["standard"][0] *= bump
        assert not grade_reads(r, CFG)["passed"], bump


def test_numbers_as_strings_where_formatting_is_not_the_point():
    rec = CONFIGS["la05_dye_qc"]["grader"]["config"]
    ref = next(c for c in la01_like("la05_dye_qc") if c.name == "reference").answer
    as_strings = {"decision": ref["decision"], "failing_channels": [str(c) for c in ref["failing_channels"]],
                  "worst_channel_mean_ul": str(ref["worst_channel_mean_ul"])}
    assert grade(as_strings, rec)["passed"]


def test_unclosed_answer_tags_parse_in_linear_time():
    import time

    from lab_automation_evals.grade import parse_answer

    t = time.perf_counter()
    assert parse_answer("<EVAL_ANSWER>" * 100000) is None
    assert time.perf_counter() - t < 1.0
