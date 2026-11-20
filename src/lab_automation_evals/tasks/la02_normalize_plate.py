"""la02: normalize 24 DNA samples to 10 ng/uL in 50 uL, with too-concentrated and too-dilute samples."""

from __future__ import annotations

from ..environment import LABWARE_TYPES, MIN_VOLUME_UL, ROWS
from ..plan import asp, disp, drop, mix, pick
from .common import ANSWER_NOTE, Control, Task, deck_file, wells_in_columns

ID = "la02_normalize_plate"
TARGET = 10.0  # ng/uL
FINAL_UL = 50.0
SAMPLE_UL = 30.0
DEAD = LABWARE_TYPES["plate96"]["dead_ul"]

# ng/uL, wells A1..H3 in column order
CONC = {
    "A1": 120.0, "B1": 45.5, "C1": 310.0, "D1": 650.0, "E1": 88.2, "F1": 14.0, "G1": 230.0, "H1": 52.7,
    "A2": 500.0, "B2": 27.3, "C2": 900.0, "D2": 6.0, "E2": 162.4, "F2": 75.0, "G2": 20.8, "H2": 410.0,
    "A3": 33.1, "B3": 17.0, "C3": 1200.0, "D3": 98.6, "E3": 260.5, "F3": 61.9, "G3": 140.0, "H3": 22.4,
}
SAMPLES = list(CONC)


def liquid(w: str) -> str:
    return f"sample_{w}"


DECK = {
    "tips": {"type": "tiprack96"},
    "samples": {"type": "plate96", "contents": {w: {liquid(w): SAMPLE_UL} for w in SAMPLES}},
    "te": {"type": "reservoir", "contents": {"A1": {"te": 30000.0}}},
    "intermediate": {"type": "plate96"},
    "normalized": {"type": "plate96"},
}


def classify(conc: dict = CONC, *, use_dead=True, min_ul=MIN_VOLUME_UL):
    """Return (direct, high, failed): which samples go straight in, need a predilution, or cannot be made."""
    usable = SAMPLE_UL - (DEAD if use_dead else 0.0)
    direct, high, failed = [], [], []
    for w, c in conc.items():
        need = TARGET * FINAL_UL / c
        if c < TARGET or need > usable + 1e-9:
            failed.append(w)
        elif need < min_ul - 1e-9:
            high.append(w)
        else:
            direct.append(w)
    return direct, high, failed


DIRECT, HIGH, FAILED = classify()

PROMPT = f"""\
You are planning a run on a simulated liquid handler. Its rules are in `environment.md` and the deck is in `deck.json`.

Plate `samples` holds 24 genomic DNA samples in wells A1 to H3, 30 uL each. Their concentrations, measured by fluorometry, are in `concentrations.csv`. Normalize every sample into the same well of the empty plate `normalized`: 50 uL at 10 ng/uL in low-TE buffer (reservoir `te`), ready for library prep. Plate `intermediate` is empty and free to use. Rack `tips` is full.

If a sample cannot be brought to 10 ng/uL in 50 uL, leave its well in `normalized` empty and list it in `failed_samples`.

Return EXACTLY:

<EVAL_ANSWER>
{{"plan": [<step>, ...], "failed_samples": ["<well>", ...]}}
</EVAL_ANSWER>

{ANSWER_NOTE}"""


def _rows_ch(wells):
    """Channels and default rows for a set of wells in one column."""
    return [ROWS.index(w[0]) + 1 for w in sorted(wells, key=lambda w: ROWS.index(w[0]))]


def _by_col(wells):
    out = {}
    for w in wells:
        out.setdefault(int(w[1:]), []).append(w)
    return {c: sorted(ws, key=lambda w: ROWS.index(w[0])) for c, ws in sorted(out.items())}


def reference(*, pre_fold=10.0, te_first=True, mix_after_sample=True, single_channel=False,
              direct=None, high=None, failed=None, one_tip=False, te_tips_reused=False,
              final_ul=FINAL_UL, round_whole_ul=False) -> list:
    direct = DIRECT if direct is None else direct
    high = HIGH if high is None else high
    made = set(direct) | set(high)
    sample_ul = {}
    for w in direct:
        sample_ul[w] = min(TARGET * final_ul / CONC[w], SAMPLE_UL - DEAD)
    pre_sample = FINAL_UL / pre_fold  # volume of neat sample in a 50 uL predilution
    for w in high:
        sample_ul[w] = TARGET * final_ul / (CONC[w] / pre_fold)
    if round_whole_ul:
        sample_ul = {w: max(1.0, float(round(v))) for w, v in sample_ul.items()}
    te_ul = {w: final_ul - sample_ul[w] for w in made}

    plan = []
    rack = iter(range(1, 13))
    te_before = te_first and not te_tips_reused

    def te_pass(dest, wells_vols):
        steps = []
        for c, ws in _by_col(list(wells_vols)).items():
            ch = _rows_ch(ws)
            vols = [round(wells_vols[w], 4) for w in ws]
            steps += [asp("te", vols, channels=ch), disp(dest, vols, c, channels=ch)]
        return steps

    # 1. TE into the predilution wells (empty, contact-free) and, if te_first, into the destination
    plan.append(pick("tips", next(rack)))
    plan += te_pass("intermediate", {w: FINAL_UL - pre_sample for w in high})
    if te_before:
        plan += te_pass("normalized", te_ul)
    plan.append(drop())

    # 2. samples, one clean tip per sample
    if one_tip:
        plan.append(pick("tips", next(rack), channels=[1], rows=["A"]))
        for w in sorted(made, key=lambda w: (int(w[1:]), ROWS.index(w[0]))):
            c, r = int(w[1:]), w[0]
            if w in high:
                plan += [asp("samples", pre_sample, c, [1], [r]), disp("intermediate", pre_sample, c, [1], [r]),
                         mix("intermediate", 25.0, 3, c, [1], [r]), asp("intermediate", sample_ul[w], c, [1], [r])]
            else:
                plan.append(asp("samples", sample_ul[w], c, [1], [r]))
            plan += [disp("normalized", sample_ul[w], c, [1], [r]), mix("normalized", 25.0, 3, c, [1], [r])]
        plan.append(drop())
        return plan

    for c, ws in _by_col(made).items():
        rc = next(rack)
        d = [w for w in ws if w in direct]
        h = [w for w in ws if w in high]
        if single_channel:
            for w in d + h:
                r = w[0]
                plan.append(pick("tips", rc, channels=[1], rows=[r]))
                if w in high:
                    plan += [asp("samples", pre_sample, c, [1], [r]), disp("intermediate", pre_sample, c, [1], [r]),
                             mix("intermediate", 25.0, 3, c, [1], [r]), asp("intermediate", sample_ul[w], c, [1], [r])]
                else:
                    plan.append(asp("samples", sample_ul[w], c, [1], [r]))
                plan.append(disp("normalized", sample_ul[w], c, [1], [r]))
                if mix_after_sample and te_before:
                    plan.append(mix("normalized", 25.0, 3, c, [1], [r]))
                plan.append(drop())
            continue
        if d:
            ch = _rows_ch(d)
            vols = [round(sample_ul[w], 4) for w in d]
            plan += [pick("tips", rc, channels=ch), asp("samples", vols, c, channels=ch), disp("normalized", vols, c, channels=ch)]
            if mix_after_sample and te_before:
                plan.append(mix("normalized", 25.0, 3, c, channels=ch))
            plan.append(drop(channels=ch))
        if h:
            ch = _rows_ch(h)
            vols = [round(sample_ul[w], 4) for w in h]
            plan += [pick("tips", rc, channels=ch), asp("samples", pre_sample, c, channels=ch),
                     disp("intermediate", pre_sample, c, channels=ch), mix("intermediate", 25.0, 3, c, channels=ch),
                     asp("intermediate", vols, c, channels=ch), disp("normalized", vols, c, channels=ch)]
            if mix_after_sample and te_before:
                plan.append(mix("normalized", 25.0, 3, c, channels=ch))
            plan.append(drop(channels=ch))

    # 3. TE after the samples
    if not te_first:
        for c, ws in _by_col(made).items():
            ch = _rows_ch(ws)
            vols = [round(te_ul[w], 4) for w in ws]
            plan += [pick("tips", next(rack), channels=ch), asp("te", vols, channels=ch),
                     disp("normalized", vols, c, channels=ch)]
            if mix_after_sample:
                plan.append(mix("normalized", 25.0, 3, c, channels=ch))
            plan.append(drop(channels=ch))
    if te_tips_reused:
        plan.append(pick("tips", next(rack)))
        for c, ws in _by_col(made).items():
            ch = _rows_ch(ws)
            vols = [round(te_ul[w], 4) for w in ws]
            plan += [asp("te", vols, channels=ch), disp("normalized", vols, c, channels=ch),
                     mix("normalized", 25.0, 3, c, channels=ch)]
        plan.append(drop())
    return plan


def direct_tiny_volumes() -> list:
    """Pipettes the concentrated samples neat, below the 1 uL minimum."""
    return reference(direct=DIRECT + HIGH, high=[])


def grader() -> dict:
    made = DIRECT + HIGH
    dest_all = wells_in_columns(range(1, 13))
    return {
        "type": "simulated_run",
        "config": {
            "deck": DECK,
            "plan_key": "plan",
            "checks": [
                {"name": "run_completes", "type": "run_completes"},
                {"name": "volumes", "type": "well_volumes", "labware": "normalized",
                 "targets": {w: FINAL_UL for w in made}, "tol_ul": 1.0},
                {"name": "concentrations", "type": "concentrations", "labware": "normalized",
                 "stock": {liquid(w): CONC[w] for w in made}, "targets": {w: {liquid(w): TARGET} for w in made},
                 "rel_tol": 0.05},
                {"name": "no_contamination", "type": "purity", "items": [
                    {"labware": "normalized", "allowed": {w: [liquid(w), "te"] for w in made}},
                    {"labware": "samples", "allowed": {w: [liquid(w)] for w in SAMPLES}},
                    {"labware": "te", "allowed": {"A1": ["te"]}},
                ]},
                {"name": "mixed", "type": "homogeneous", "labware": "normalized", "wells": made},
                {"name": "failed_wells_empty", "type": "empty", "labware": "normalized",
                 "wells": [w for w in dest_all if w not in made]},
                {"name": "failed_samples", "type": "answer_set", "key": "failed_samples", "kind": "well", "value": FAILED},
            ],
        },
    }


def build() -> Task:
    d_nodead, h_nodead, f_nodead = classify(use_dead=False)
    controls = [
        Control("reference", {"plan": reference(), "failed_samples": FAILED}, True,
                "TE first into empty wells, one clean tip per sample, 1:10 predilution for samples above 500 ng/uL"),
        Control("te_after_sample", {"plan": reference(te_first=False), "failed_samples": FAILED}, True,
                "sample first, then TE with a fresh tip per well and a mix"),
        Control("predilute_1_in_20", {"plan": reference(pre_fold=20.0), "failed_samples": FAILED}, True,
                "a 1:20 predilution instead of 1:10"),
        Control("single_channel", {"plan": reference(single_channel=True), "failed_samples": FAILED}, True,
                "one channel, one sample at a time"),
        Control("direct_tiny_volumes", {"plan": direct_tiny_volumes(), "failed_samples": FAILED}, False,
                "pipettes concentrated samples neat at under 1 uL", ["run_completes"]),
        Control("ignores_dead_volume_crash", {"plan": _uncapped(d_nodead, h_nodead), "failed_samples": f_nodead}, False,
                "plans 35.7 uL from a 30 uL well with a 5 uL dead volume", ["run_completes"]),
        Control("low_samples_filled_anyway", {"plan": reference(direct=d_nodead, high=h_nodead), "failed_samples": f_nodead},
                False, "ignores the dead volume, so it fills B3 (17 ng/uL) with all the sample it can reach and does not report it",
                ["failed_wells_empty", "failed_samples"]),
        Control("one_tip_for_all_samples", {"plan": reference(one_tip=True), "failed_samples": FAILED}, False,
                "one tip carries DNA from sample to sample", ["no_contamination"]),
        Control("no_mix_after_sample", {"plan": reference(mix_after_sample=False), "failed_samples": FAILED}, False,
                "adds the sample to TE and never mixes", ["mixed"]),
        Control("te_tips_reused_after_contact", {"plan": reference(te_tips_reused=True), "failed_samples": FAILED}, False,
                "adds TE after the samples with the same tips, back and forth to the reservoir", ["no_contamination"]),
        Control("rounds_to_whole_microliters", {"plan": reference(round_whole_ul=True), "failed_samples": FAILED},
                False, "rounds every sample volume to a whole microliter (1.22 uL becomes 1 uL)", ["concentrations"]),
        Control("adds_2_ul_overage", {"plan": reference(final_ul=52.0), "failed_samples": FAILED}, False,
                "right concentration, but 52 uL per well to allow for pipetting loss", ["volumes"]),
        Control("forgot_failed_list", {"plan": reference(), "failed_samples": []}, False,
                "correct plate, empty failed list", ["failed_samples"]),
    ]
    csv = "well,concentration_ng_per_ul\n" + "".join(f"{w},{CONC[w]:.1f}\n" for w in SAMPLES)
    notes = {
        "samples": "genomic DNA, 30 uL per well; concentrations in concentrations.csv",
        "te": "low-TE buffer",
        "intermediate": "empty plate, free to use",
        "normalized": "empty destination plate",
    }
    return Task(
        id=ID,
        title="DNA normalization with out-of-range samples",
        kind="plan",
        prompt=PROMPT,
        deck=DECK,
        grader=grader(),
        workspace={"deck.json": deck_file(DECK, notes), "concentrations.csv": csv},
        controls=controls,
        tests="Normalizes a plate with per-channel volumes: predilution below the minimum volume, dead volume, which samples cannot be made.",
        traps=["sub-minimum volumes pipetted neat", "dead volume ignored", "unreachable samples filled anyway",
               "volumes rounded to whole microliters", "wrong final volume",
               "one tip across samples", "no mix after the sample", "TE tips reused after touching DNA",
               "failed samples not reported"],
        metadata={"eval_type": "scientific", "kit": "simulated_liquid_handler", "task": "plan", "time_horizon": "small"},
    )


def _uncapped(direct, high) -> list:
    """Like reference(), but plans the full calculated sample volume even past the dead volume."""
    plan = reference(direct=direct, high=high)
    for step in plan:
        if step.get("op") == "aspirate" and step.get("labware") == "samples" and isinstance(step["volume_ul"], list):
            ch = step["channels"]
            col = step["column"]
            step["volume_ul"] = [round(TARGET * FINAL_UL / CONC[f"{ROWS[c - 1]}{col}"], 4) for c in ch]
    return plan
