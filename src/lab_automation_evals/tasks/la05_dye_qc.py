"""la05: release or hold an 8-channel head from a photometric dye check (simulated data)."""

from __future__ import annotations

import math

from ..environment import ROWS
from .common import Lcg, Task, Control

ID = "la05_dye_qc"
TARGET_UL = 50.0
ACC_LIMIT = 0.05  # +/- 5% of target, per channel
CV_LIMIT = 0.03  # 3%, per channel, sample standard deviation
BLANK = 0.050  # absorbance of a well with no dye
SLOPE = 0.0130  # absorbance per uL of dye in 200 uL (100 uL reads about 1.35)

# true per-channel behaviour (channel i = row i)
CH_MEAN = [52.3, 49.8, 50.4, 49.9, 50.1, 46.9, 50.0, 49.7]
CH_CV = [0.011, 0.009, 0.029, 0.010, 0.012, 0.010, 0.008, 0.011]
STD_VOLS = [0.0, 10.0, 25.0, 50.0, 75.0, 100.0]
STD_WOBBLE = [0.0012, -0.0008, 0.0006, -0.0004, 0.0009, -0.0007]


def _z(rng: Lcg, n: int = 12) -> list:
    """n numbers with mean exactly 0 and sample standard deviation exactly 1."""
    raw = [rng.uniform(-1, 1) for _ in range(n)]
    m = sum(raw) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in raw) / (n - 1))
    return [(x - m) / sd for x in raw]


def make_data():
    rng = Lcg(5050)
    standards = [(v, round(BLANK + SLOPE * v + w, 4)) for v, w in zip(STD_VOLS, STD_WOBBLE)]
    plate = {}
    for i, r in enumerate(ROWS):
        z = _z(rng)
        for c in range(1, 13):
            vol = CH_MEAN[i] * (1 + CH_CV[i] * z[c - 1])
            plate[f"{r}{c}"] = round(BLANK + SLOPE * vol, 4)
    return standards, plate


STANDARDS, PLATE = make_data()


def fit(points, through_origin=False):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    if through_origin:
        return 0.0, sum(x * y for x, y in points) / sum(x * x for x in xs)
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    slope = sum((x - mx) * (y - my) for x, y in points) / sum((x - mx) ** 2 for x in xs)
    return my - slope * mx, slope


def analyse(*, through_origin=False, single_point=False, by="row", ddof=1):
    """Return (decision, failing groups, mean of the group furthest from target)."""
    if single_point:
        a0, a50 = dict(STANDARDS)[0.0], dict(STANDARDS)[50.0]
        to_vol = lambda a: 50.0 * (a - a0) / (a50 - a0)  # noqa: E731
    else:
        b, k = fit(STANDARDS, through_origin)
        to_vol = lambda a: (a - b) / k  # noqa: E731
    groups = {}
    for w, a in PLATE.items():
        key = ROWS.index(w[0]) + 1 if by == "row" else (int(w[1:]) if by == "column" else 1)
        groups.setdefault(key, []).append(to_vol(a))
    failing, worst, worst_dev = [], None, -1.0
    for g, vols in sorted(groups.items()):
        n = len(vols)
        m = sum(vols) / n
        sd = math.sqrt(sum((v - m) ** 2 for v in vols) / (n - ddof))
        if abs(m - TARGET_UL) / TARGET_UL > ACC_LIMIT or sd / m > CV_LIMIT:
            failing.append(g)
        if abs(m - TARGET_UL) > worst_dev:
            worst, worst_dev = m, abs(m - TARGET_UL)
    return ("no_go" if failing else "go"), failing, round(worst, 3)


KEY_DECISION, KEY_FAILING, KEY_WORST = analyse()

SOP = """\
# Pipetting head check, photometric (excerpt)

1. The head dispenses 50 uL of tartrazine working solution into every well of a clear 96-well plate, one column per
   pass. Each well is topped up with 150 uL of buffer, mixed, and read at 450 nm.
2. A standard curve of the same working solution is pipetted by hand with a calibrated pipette into the same plate
   type, topped up with 150 uL of buffer like the head wells, mixed, and read on the same reader. The 0 uL standard
   is the blank.
3. Convert absorbance to delivered volume with a straight-line fit of absorbance against volume over the whole
   standard curve.
4. Acceptance, per channel at 50 uL: the channel's mean delivered volume is within +/-5% of 50 uL (systematic error),
   and its coefficient of variation (sample standard deviation / mean) is at most 3% (random error).
5. The head is released for the day only if every channel passes. Otherwise it is held for service.
"""

PROMPT = """\
Before today's run, the 8-channel pipetting head of the simulated liquid handler (rules in `environment.md`) was checked with a dye test following `sop.md`. The readings are in `qc_plate.csv` (one absorbance per well) and the hand-pipetted standard curve is in `standards.csv`. These readings are simulated.

Decide whether the head is released for today.

Return EXACTLY:

<EVAL_ANSWER>
{"decision": "go" or "no_go", "failing_channels": [<channel number>, ...], "worst_channel_mean_ul": <number>}
</EVAL_ANSWER>

`failing_channels`: every channel that fails the acceptance criteria (an empty list if none).
`worst_channel_mean_ul`: the mean delivered volume, in uL, of the channel whose mean is furthest from 50 uL."""


def grader() -> dict:
    return {
        "type": "answer_only",
        "config": {
            "plan_key": None,
            "checks": [
                {"name": "decision", "type": "answer_choice", "key": "decision", "accept": [KEY_DECISION]},
                {"name": "failing_channels", "type": "answer_set", "key": "failing_channels", "kind": "int",
                 "value": KEY_FAILING},
                {"name": "worst_channel_mean_ul", "type": "answer_numeric", "key": "worst_channel_mean_ul",
                 "value": KEY_WORST, "tol": 0.5},
            ],
        },
    }


def _answer(result) -> dict:
    d, f, w = result
    return {"decision": d, "failing_channels": f, "worst_channel_mean_ul": w}


def _answer_plate_mean() -> dict:
    b, k = fit(STANDARDS)
    vols = [(a - b) / k for a in PLATE.values()]
    m = sum(vols) / len(vols)
    ok = abs(m - TARGET_UL) / TARGET_UL <= ACC_LIMIT
    return {"decision": "go" if ok else "no_go", "failing_channels": [], "worst_channel_mean_ul": round(m, 3)}


def build() -> Task:
    controls = [
        Control("reference", _answer(analyse()), True, "line with intercept, per channel (row), sample SD"),
        Control("single_point_at_50", _answer(analyse(single_point=True)), True,
                "calibrates on the blank and the 50 uL standard alone, which sits at the target"),
        Control("population_sd", _answer(analyse(ddof=0)), True, "CV with the population SD"),
        Control("line_through_origin", _answer(analyse(through_origin=True)), False,
                "forces the fit through zero, ignoring the blank; still says no_go, but fails channel 1 instead of 6",
                ["failing_channels"]),
        Control("columns_as_channels", _answer(analyse(by="column")), False,
                "groups by column, not by channel; still says no_go, for the wrong reason", ["failing_channels"]),
        Control("whole_plate_only", _answer(analyse(by="plate")), False,
                "judges the plate as a whole; still says no_go, for the wrong reason", ["failing_channels"]),
        Control("plate_mean_accuracy_only", _answer_plate_mean(), False,
                "checks only that the whole-plate mean is within 5%, so it releases the head", ["decision"]),
        Control("raw_absorbance_ratio", {"decision": "no_go", "failing_channels": KEY_FAILING,
                                         "worst_channel_mean_ul": round(sum(PLATE[f"F{c}"] for c in range(1, 13)) / 12 / SLOPE, 3)},
                False, "divides absorbance by the slope without removing the blank", ["worst_channel_mean_ul"]),
    ]
    std_csv = "volume_ul,absorbance_450\n" + "".join(f"{v:.1f},{a:.4f}\n" for v, a in STANDARDS)
    plate_csv = "well,absorbance_450\n" + "".join(f"{w},{PLATE[w]:.4f}\n" for w in PLATE)
    return Task(
        id=ID,
        title="Release or hold the pipetting head",
        kind="read data and decide",
        prompt=PROMPT,
        deck=None,
        grader=grader(),
        workspace={"sop.md": SOP, "standards.csv": std_csv, "qc_plate.csv": plate_csv},
        controls=controls,
        tests="Turns a dye check into a release decision: calibration with a blank, per-channel statistics, the channel-to-row map.",
        traps=["fit forced through zero", "columns treated as channels", "whole-plate statistics only",
               "whole-plate mean only", "blank not removed"],
        metadata={"eval_type": "scientific", "kit": "simulated_liquid_handler", "task": "qc", "time_horizon": "small"},
    )
