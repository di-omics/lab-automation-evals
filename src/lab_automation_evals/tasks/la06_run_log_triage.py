"""la06: read a liquid handler's run log and name the wells that must be redone."""

from __future__ import annotations

import json

from ..environment import ROWS
from ..plan import asp, disp, drop, mix, pick
from .common import Control, Task

ID = "la06_run_log_triage"


def run_plan() -> list:
    plan = []
    for c in range(1, 13):
        plan += [pick("tips", c), asp("reagent", 40.0), disp("assay", 40.0, c), mix("assay", 50.0, 3, c), drop()]
    return plan


# (column, op, message, wells harmed)
EVENTS = {
    (2, "pick_up_tips"): ("WARN", "channel 6: tip not seated on first attempt; retry 1 of 2 succeeded", []),
    (4, "pick_up_tips"): ("ERROR", "channel 3: no tip detected after 2 retries; recovery: continue without channel 3", ["C4"]),
    (7, "dispense"): ("ERROR", "channel 5: clot detected, dispense stopped before completion; recovery: tip discarded, channel 5 skipped for this column", ["E7"]),
    (9, "aspirate"): ("ERROR", "channel 8: pressure fault during aspiration (air bubble suspected); aspirated volume estimated at 26.3 of 40.0 uL; recovery: continue", ["H9"]),
    (10, "drop_tips"): ("WARN", "channel 2: tip released early, above the trash chute; recovery: continue", []),
    (11, "aspirate"): ("WARN", "reservoir reagent: liquid level low, about 3.15 mL before this aspiration", []),
    (12, "aspirate"): ("WARN", "channel 1: air detected at the end of aspiration; recovery: dispensed back and aspirated again, 40.0 uL", []),
}
KEY = sorted({w for _, _, ws in EVENTS.values() for w in ws}, key=lambda w: (int(w[1:]), w[0]))


def run_log() -> str:
    lines = ["# run log, simulated liquid handler, 8-channel head", "# plan: plan.json (60 steps)",
             "# reservoir reagent: 6.3 mL at start", ""]
    t = 0
    step = 0
    for c in range(1, 13):
        for op in ("pick_up_tips", "aspirate", "dispense", "mix", "drop_tips"):
            step += 1
            t += {"pick_up_tips": 9, "aspirate": 6, "dispense": 5, "mix": 11, "drop_tips": 7}[op]
            chans = "1-8"
            if c == 4:
                chans = "1,2,4-8"
            if c == 7 and op in ("dispense", "mix", "drop_tips"):
                chans = "1-4,6-8"
            where = {"pick_up_tips": f"tips col {c}", "aspirate": "reagent", "dispense": f"assay col {c}",
                     "mix": f"assay col {c}", "drop_tips": "trash"}[op]
            vol = {"aspirate": " 40.0 uL", "dispense": " 40.0 uL", "mix": " 50.0 uL x3"}.get(op, "")
            if c == 9 and op in ("aspirate", "dispense"):
                chans, vol = "1-7", " 40.0 uL; channel 8 26.3 uL"
            stamp = f"00:{t // 60:02d}:{t % 60:02d}"
            ev = EVENTS.get((c, op))
            if ev:
                level, msg, _ = ev
                lines.append(f"{stamp} step {step:2d} {level:5s} {op} {where}: {msg}")
            lines.append(f"{stamp} step {step:2d} INFO  {op} {where} channels {chans}{vol}: done")
    t += 4
    lines.append(f"00:{t // 60:02d}:{t % 60:02d} run finished with 3 errors and 4 warnings")
    return "\n".join(lines) + "\n"


PROMPT = """\
A reagent-addition run has just finished on the simulated liquid handler (rules in `environment.md`). The log is the robot's own record, including its error recovery. Every well of the 96-well plate `assay` held 60 uL of a different sample; the run was meant to add 40 uL of detection reagent to every well and mix. The plan that ran is `plan.json` and the robot's log is `run_log.txt`.

The plate goes to the reader next. Which wells did not receive the full reagent addition and mix as planned, so their samples must be redone?

Return EXACTLY:

<EVAL_ANSWER>
{"wells_to_repeat": ["<well>", ...]}
</EVAL_ANSWER>"""


def grader() -> dict:
    return {
        "type": "answer_only",
        "config": {
            "plan_key": None,
            "checks": [
                {"name": "wells_to_repeat", "type": "answer_set", "key": "wells_to_repeat", "kind": "well", "value": KEY},
            ],
        },
    }


def build() -> Task:
    every_flag = ["F2", "C4", "E7", "H9", "B10", "A12"]
    controls = [
        Control("reference", {"wells_to_repeat": KEY}, True, "the 3 errors that changed what a well received"),
        Control("lower_case_padded", {"wells_to_repeat": ["c04", "e07", "h09"]}, True, "same wells, other spelling"),
        Control("every_flagged_channel", {"wells_to_repeat": every_flag}, False,
                "repeats a well for every warning, including recovered ones", ["wells_to_repeat"]),
        Control("errors_only_misses_partial", {"wells_to_repeat": ["C4", "E7"]}, False,
                "misses the short aspiration that the robot continued past", ["wells_to_repeat"]),
        Control("channel_as_column", {"wells_to_repeat": ["D3", "G5"]}, False,
                "swaps channel and column", ["wells_to_repeat"]),
        Control("whole_columns", {"wells_to_repeat": [f"{r}{c}" for c in (4, 7, 9) for r in ROWS]}, False,
                "repeats every well in each affected column", ["wells_to_repeat"]),
    ]
    return Task(
        id=ID,
        title="Triage a run log",
        kind="read data and decide",
        prompt=PROMPT,
        deck=None,
        grader=grader(),
        workspace={"plan.json": json.dumps(run_plan(), indent=1) + "\n", "run_log.txt": run_log()},
        controls=controls,
        tests="Reads a robot's error recovery like an operator: which events changed what a well received, and which were recovered.",
        traps=["every warning treated as a failure", "a continued short aspiration missed", "channel and column swapped",
               "whole columns repeated"],
        metadata={"eval_type": "scientific", "kit": "simulated_liquid_handler", "task": "qc", "time_horizon": "small"},
    )
