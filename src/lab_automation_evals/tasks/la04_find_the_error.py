"""la04: review a colleague's reagent-addition plan, find the first faulty step, and fix the plan."""

from __future__ import annotations

import json

from ..plan import asp, disp, drop, mix, pick
from .common import ANSWER_NOTE, Control, Task, deck_file, wells_in_columns

ID = "la04_find_the_error"
SAMPLE_UL = 60.0
REAGENT_UL = 40.0
ALL = wells_in_columns(range(1, 13))

DECK = {
    "tips": {"type": "tiprack96"},
    "reagent": {"type": "reservoir", "contents": {"A1": {"reagent": 20000.0}}},
    "assay": {"type": "plate96", "contents": {w: {f"sample_{w}": SAMPLE_UL} for w in ALL}},
}

ERROR_CLASSES = [
    "volume_below_minimum",
    "exceeds_tip_capacity",
    "overfills_a_well",
    "used_tip_contaminates_a_source",
    "used_tip_carries_one_sample_into_another",
    "mix_too_small",
    "wrong_wells",
    "below_dead_volume",
]
KEY_CLASS = "used_tip_contaminates_a_source"


def colleague_plan() -> list:
    """Saves tips: one set of 8 for the whole plate."""
    plan = [pick("tips", 1)]
    for c in range(1, 13):
        plan += [asp("reagent", REAGENT_UL), disp("assay", REAGENT_UL, c), mix("assay", 50.0, 3, c)]
    plan.append(drop())
    return plan


# Step 1 picks tips; steps 2-4 serve column 1; step 5 is the second trip into the reagent.
KEY_STEP = 5

PROMPT = f"""\
You are reviewing a run on a simulated liquid handler before it goes to the robot. The rules are in `environment.md` and the deck is in `deck.json`.

Intent: every well of plate `assay` holds 60 uL of a different sample. Add 40 uL of detection reagent from reservoir `reagent` to every well and mix, so each well is ready for the reader with 100 uL of its own sample and reagent. Rack `tips` is full.

A colleague wrote `colleague_plan.json` for this. Find the first faulty step: the first step that breaks a rule in `environment.md` or puts a liquid where it does not belong, even as a trace (steps are numbered from 1). Name what goes wrong at that step using one of these classes: {", ".join(f"`{c}`" for c in ERROR_CLASSES)}. Then write a corrected plan that achieves the intent on this deck.

Return EXACTLY:

<EVAL_ANSWER>
{{"first_error_step": <integer>, "error_class": "<class>", "corrected_plan": [<step>, ...]}}
</EVAL_ANSWER>

{ANSWER_NOTE}"""


def corrected(*, mix_vol=50.0, cycles=3, every=1, mixing=True, two_sets=False, reagent=REAGENT_UL) -> list:
    plan = []
    rack_col = 0
    for c in range(1, 13):
        if (c - 1) % every == 0:
            if plan:
                plan.append(drop())
            rack_col += 1
            plan.append(pick("tips", rack_col))
        plan += [asp("reagent", reagent), disp("assay", reagent, c)]
        if two_sets:
            rack_col += 1
            plan += [drop(), pick("tips", rack_col)]
        if mixing:
            plan.append(mix("assay", mix_vol, cycles, c))
    plan.append(drop())
    return plan


def grader() -> dict:
    return {
        "type": "simulated_run",
        "config": {
            "deck": DECK,
            "plan_key": "corrected_plan",
            "checks": [
                {"name": "first_error_step", "type": "answer_choice", "key": "first_error_step", "accept": [KEY_STEP]},
                {"name": "error_class", "type": "answer_choice", "key": "error_class", "accept": [KEY_CLASS]},
                {"name": "run_completes", "type": "run_completes"},
                {"name": "volumes", "type": "well_volumes", "labware": "assay",
                 "targets": {w: SAMPLE_UL + REAGENT_UL for w in ALL}, "tol_ul": 1.0},
                {"name": "reagent_fraction", "type": "concentrations", "labware": "assay", "stock": {"reagent": 1.0},
                 "targets": {w: {"reagent": REAGENT_UL / (SAMPLE_UL + REAGENT_UL)} for w in ALL}, "rel_tol": 0.05},
                {"name": "no_contamination", "type": "purity", "items": [
                    {"labware": "assay", "allowed": {w: [f"sample_{w}", "reagent"] for w in ALL}},
                    {"labware": "reagent", "allowed": {"A1": ["reagent"]}},
                ]},
                {"name": "mixed", "type": "homogeneous", "labware": "assay", "wells": ALL},
            ],
        },
    }


def build() -> Task:
    ref = {"first_error_step": KEY_STEP, "error_class": KEY_CLASS}
    controls = [
        Control("reference", {**ref, "corrected_plan": corrected()}, True,
                "step 5, a used tip back into the reagent; fix: a fresh tip column per plate column"),
        Control("bigger_mix", {**ref, "corrected_plan": corrected(mix_vol=60.0, cycles=5)}, True,
                "same fix with a larger, longer mix"),
        Control("class_in_other_case", {"first_error_step": KEY_STEP, "error_class": KEY_CLASS.upper(),
                                        "corrected_plan": corrected()}, True, "class written in capitals"),
        Control("step_of_first_sample_harm", {**ref, "first_error_step": KEY_STEP + 1, "corrected_plan": corrected()},
                False, "names step 6, where the first sample is harmed, not the step that fouls the reagent",
                ["first_error_step"]),
        Control("names_the_sample_harm", {"first_error_step": KEY_STEP + 1,
                                          "error_class": "used_tip_carries_one_sample_into_another",
                                          "corrected_plan": corrected()}, False,
                "names step 6 and the cross-sample carryover, a later consequence of the step 5 fault",
                ["first_error_step", "error_class"]),
        Control("fix_adds_30_ul", {**ref, "corrected_plan": corrected(reagent=30.0)}, False,
                "fresh tips, but 30 uL of reagent instead of 40", ["volumes", "reagent_fraction"]),
        Control("names_the_mix", {**ref, "error_class": "mix_too_small", "corrected_plan": corrected()}, False,
                "blames the 50 uL mix, which is exactly half the well and enough", ["error_class"]),
        Control("fix_still_shares_tips", {**ref, "corrected_plan": corrected(every=2)}, False,
                "fresh tips every second column only", ["no_contamination"]),
        Control("fix_drops_the_mix", {**ref, "corrected_plan": corrected(mixing=False)}, False,
                "fresh tips but no mix", ["mixed"]),
        Control("fix_runs_out_of_tips", {**ref, "corrected_plan": corrected(two_sets=True)}, False,
                "separate tips for adding and for mixing need 192 tips", ["run_completes"]),
        Control("unchanged_plan", {**ref, "corrected_plan": colleague_plan()}, False,
                "right diagnosis, plan not fixed", ["no_contamination"]),
    ]
    notes = {"assay": "60 uL of a different sample in every well", "reagent": "detection reagent"}
    return Task(
        id=ID,
        title="Find the error in a colleague's plan",
        kind="diagnose and fix",
        prompt=PROMPT,
        deck=DECK,
        grader=grader(),
        workspace={"deck.json": deck_file(DECK, notes), "colleague_plan.json": json.dumps(colleague_plan(), indent=1) + "\n"},
        controls=controls,
        tests="Reviews a plan step by step like a scientist watching the robot, names the fault, and writes a fix that runs.",
        traps=["later symptom named instead of the first fault", "a near-miss mix blamed", "wrong reagent volume",
               "fix that still shares tips", "fix without a mix", "fix that runs out of tips", "plan left unchanged"],
        metadata={"eval_type": "scientific", "kit": "simulated_liquid_handler", "task": "diagnose", "time_horizon": "small"},
    )
