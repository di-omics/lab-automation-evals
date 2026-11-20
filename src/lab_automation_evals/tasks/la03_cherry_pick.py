"""la03: pick hits from a duplicate screen of 2 compound plates into a packed hit plate."""

from __future__ import annotations

from ..environment import ROWS
from ..plan import asp, disp, drop, pick
from ..sim import well_order_column_major
from .common import ANSWER_NOTE, Control, Lcg, Task, deck_file

ID = "la03_cherry_pick"
PLATES = ["P1", "P2"]
SOURCE_UL = 40.0
PICK_UL = 10.0
HIT_CUTOFF = 50.0

# Designed wells; every other test well gets a low value from the generator.
DESIGNED = {
    # true hits: both replicates >= 50
    ("P1", "B3"): (78.2, 81.5), ("P1", "E5"): (64.0, 59.3), ("P1", "H5"): (91.7, 88.4),
    ("P1", "A8"): (55.1, 62.9), ("P1", "D9"): (50.0, 57.2), ("P1", "G10"): (70.3, 73.8),
    ("P1", "C11"): (52.6, 51.1),
    ("P2", "A2"): (83.9, 79.0), ("P2", "F4"): (61.2, 66.7), ("P2", "C6"): (95.0, 92.3),
    ("P2", "H7"): (57.8, 50.0), ("P2", "B9"): (68.4, 71.9), ("P2", "E9"): (59.9, 54.6),
    ("P2", "D11"): (88.1, 84.0),
    # mean >= 50 but one replicate below 50
    ("P1", "F2"): (72.4, 41.0), ("P1", "A6"): (49.9, 58.3), ("P2", "G3"): (38.2, 66.1),
    ("P2", "E10"): (63.0, 46.5),
}


def liquid(plate: str, well: str) -> str:
    col = int(well[1:])
    if col == 1:
        return "dmso"
    if col == 12:
        return "reference_inhibitor"
    return f"{plate}_{well}"


def screen() -> list:
    """Rows of (plate, well, rep1, rep2) for all 192 wells."""
    rng = Lcg(20261119)
    out = []
    for plate in PLATES:
        for well in well_order_column_major():
            col = int(well[1:])
            if col == 1:
                r1, r2 = rng.uniform(-6, 6), rng.uniform(-6, 6)
            elif col == 12:
                r1, r2 = rng.uniform(95, 102), rng.uniform(95, 102)
            elif (plate, well) in DESIGNED:
                r1, r2 = DESIGNED[(plate, well)]
            else:
                r1, r2 = rng.uniform(-12, 38), rng.uniform(-12, 38)
            out.append((plate, well, round(r1, 1), round(r2, 1)))
    return out


def select(rows, rule="both", skip_controls=True) -> list:
    hits = []
    for plate, well, r1, r2 in rows:
        col = int(well[1:])
        if skip_controls and col in (1, 12):
            continue
        ok = (r1 >= HIT_CUTOFF and r2 >= HIT_CUTOFF) if rule == "both" else ((r1 + r2) / 2 >= HIT_CUTOFF)
        if ok:
            hits.append((plate, well))
    return hits


SCREEN = screen()
HITS = select(SCREEN)
PACKED = well_order_column_major()

DECK = {
    "tips": {"type": "tiprack96"},
    "P1": {"type": "plate96", "contents": {w: {liquid("P1", w): SOURCE_UL} for w in PACKED}},
    "P2": {"type": "plate96", "contents": {w: {liquid("P2", w): SOURCE_UL} for w in PACKED}},
    "hits": {"type": "plate96"},
}

LAYOUT = """\
# Compound plates P1 and P2

- 96-well plates, 40 uL per well.
- Columns 2 to 11: test compounds, one compound per well.
- Column 1: DMSO vehicle (negative control).
- Column 12: reference inhibitor (positive control).
- The screen was run in duplicate (rep1, rep2) on assay plates mapped well for well to these plates.
"""

PROMPT = f"""\
You are planning a run on a simulated liquid handler. Its rules are in `environment.md` and the deck is in `deck.json`.

Two compound plates, `P1` and `P2`, were screened in duplicate. `screen_results.csv` gives percent inhibition for every well and `plate_layout.md` describes the plates. A hit is a compound with at least 50% inhibition in both replicates.

Cherry-pick 10 uL of every hit into the empty plate `hits`, packed from A1 in column order (A1, B1, ... H1, A2, ...), and report where each hit went. Rack `tips` is full.

Return EXACTLY:

<EVAL_ANSWER>
{{"hits": [{{"source_plate": "P1", "source_well": "<well>", "dest_well": "<well>"}}, ...], "plan": [<step>, ...]}}
</EVAL_ANSWER>

{ANSWER_NOTE}"""


def assign(hits) -> list:
    return [{"source_plate": p, "source_well": w, "dest_well": PACKED[i]} for i, (p, w) in enumerate(hits)]


def single_channel_plan(mapping, channel=1, one_tip=False) -> list:
    ch = [channel]
    plan = []
    tip_spots = iter(PACKED)
    if one_tip:
        s = next(tip_spots)
        plan.append(pick("tips", int(s[1:]), ch, [s[0]]))
    for m in mapping:
        sw, dw = m["source_well"], m["dest_well"]
        if not one_tip:
            s = next(tip_spots)
            plan.append(pick("tips", int(s[1:]), ch, [s[0]]))
        plan += [asp(m["source_plate"], PICK_UL, int(sw[1:]), ch, [sw[0]]),
                 disp("hits", PICK_UL, int(dw[1:]), ch, [dw[0]])]
        if not one_tip:
            plan.append(drop())
    if one_tip:
        plan.append(drop())
    return plan


def batched_plan(mapping) -> list:
    """Group consecutive picks that share a source plate and column, with rows rising in source and destination."""
    groups = []
    for m in mapping:
        g = groups[-1] if groups else None
        if (g and len(g) < 8 and g[-1]["source_plate"] == m["source_plate"]
                and g[-1]["source_well"][1:] == m["source_well"][1:]
                and g[-1]["dest_well"][1:] == m["dest_well"][1:]
                and ROWS.index(m["source_well"][0]) > ROWS.index(g[-1]["source_well"][0])
                and ROWS.index(m["dest_well"][0]) > ROWS.index(g[-1]["dest_well"][0])):
            g.append(m)
        else:
            groups.append([m])
    plan = []
    for k, g in enumerate(groups, start=1):
        ch = list(range(1, len(g) + 1))
        plan += [pick("tips", k, ch, list(ROWS[: len(g)])),
                 asp(g[0]["source_plate"], PICK_UL, int(g[0]["source_well"][1:]), ch, [m["source_well"][0] for m in g]),
                 disp("hits", PICK_UL, int(g[0]["dest_well"][1:]), ch, [m["dest_well"][0] for m in g]),
                 drop()]
    return plan


def grader() -> dict:
    liquid_of = {f"{p}:{w}": liquid(p, w) for p in PLATES for w in PACKED}
    return {
        "type": "simulated_run",
        "config": {
            "deck": DECK,
            "plan_key": "plan",
            "checks": [
                {"name": "run_completes", "type": "run_completes"},
                {"name": "hit_selection", "type": "answer_set", "key": "hits", "kind": "pick_sources",
                 "value": [f"{p}:{w}" for p, w in HITS]},
                {"name": "plate_matches_map", "type": "cherry_pick", "labware": "hits", "map_key": "hits",
                 "volume_ul": PICK_UL, "tol_ul": 0.5, "packed_order": PACKED, "liquid_of": liquid_of},
                {"name": "no_contamination", "type": "purity", "items": [
                    {"labware": p, "allowed": {w: [liquid(p, w)] for w in PACKED}} for p in PLATES
                ]},
            ],
        },
    }


def build() -> Task:
    ref_map = assign(HITS)
    # a different but equally valid order: P2 hits first
    alt_hits = [h for h in HITS if h[0] == "P2"] + [h for h in HITS if h[0] == "P1"]
    alt_map = assign(alt_hits)
    with_controls = select(SCREEN, skip_controls=False)
    averaged = select(SCREEN, rule="mean")
    swapped = [dict(m) for m in ref_map]
    swapped[0]["dest_well"], swapped[1]["dest_well"] = swapped[1]["dest_well"], swapped[0]["dest_well"]
    shifted = [{**m, "dest_well": PACKED[i + 1]} for i, m in enumerate(ref_map)]
    crossing = single_channel_plan(ref_map)
    crossing[0:4] = [pick("tips", 1, [1, 2]),
                     asp(ref_map[0]["source_plate"], PICK_UL, 3, [1, 2], ["D", "B"]),
                     disp("hits", PICK_UL, 1, [1, 2]), drop()]
    controls = [
        Control("reference", {"hits": ref_map, "plan": single_channel_plan(ref_map)}, True,
                "one clean tip per hit, channel 1 reaching each row"),
        Control("batched_channels", {"hits": ref_map, "plan": batched_plan(ref_map)}, True,
                "several channels at once wherever rows rise in both plates"),
        Control("other_valid_order", {"hits": alt_map, "plan": single_channel_plan(alt_map, channel=8)}, True,
                "P2 hits first, channel 8 only; still packed from A1"),
        Control("picks_positive_controls", {"hits": assign(with_controls), "plan": single_channel_plan(assign(with_controls))},
                False, "thresholds every well, so the reference inhibitor column comes along", ["hit_selection"]),
        Control("averages_replicates", {"hits": assign(averaged), "plan": single_channel_plan(assign(averaged))}, False,
                "calls a hit on the mean of the replicates", ["hit_selection"]),
        Control("one_tip_for_all", {"hits": ref_map, "plan": single_channel_plan(ref_map, one_tip=True)}, False,
                "one tip carries compound into the next source well", ["no_contamination", "plate_matches_map"]),
        Control("map_disagrees_with_plate", {"hits": swapped, "plan": single_channel_plan(ref_map)}, False,
                "the report swaps 2 destination wells", ["plate_matches_map"]),
        Control("not_packed_from_a1", {"hits": shifted, "plan": single_channel_plan(shifted)}, False,
                "starts at B1", ["plate_matches_map"]),
        Control("channels_cross", {"hits": ref_map, "plan": crossing}, False,
                "asks channel 1 for row D and channel 2 for row B in one step", ["run_completes"]),
    ]
    csv = "plate,well,rep1_pct_inhibition,rep2_pct_inhibition\n" + "".join(
        f"{p},{w},{r1:.1f},{r2:.1f}\n" for p, w, r1, r2 in SCREEN)
    notes = {"P1": "compound plate, see plate_layout.md", "P2": "compound plate, see plate_layout.md",
             "hits": "empty destination plate"}
    return Task(
        id=ID,
        title="Hit picking from a duplicate screen",
        kind="plan",
        prompt=PROMPT,
        deck=DECK,
        grader=grader(),
        workspace={"deck.json": deck_file(DECK, notes), "screen_results.csv": csv, "plate_layout.md": LAYOUT},
        controls=controls,
        tests="Reads a screen, applies the hit rule, and plans picks a channel head can make; the reported map must match the plate.",
        traps=["positive controls picked as hits", "replicates averaged", "one tip across compounds",
               "report disagrees with the plate", "not packed from A1", "channels asked to cross"],
        metadata={"eval_type": "scientific", "kit": "simulated_liquid_handler", "task": "plan", "time_horizon": "small"},
    )
