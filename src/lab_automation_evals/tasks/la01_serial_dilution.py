"""la01: an 8-compound, 11-point, 3-fold dose-response plate from 1 mM stocks."""

from __future__ import annotations

from ..environment import ROWS
from ..plan import asp, disp, drop, mix, pick
from .common import ANSWER_NOTE, Control, Task, deck_file, wells_in_columns

ID = "la01_serial_dilution"
STOCK_UM = 1000.0
TOP_UM = 100.0
FOLD = 3.0
FINAL_UL = 100.0
COMPOUNDS = [f"cmpd_{i + 1}" for i in range(8)]

DECK = {
    "tips": {"type": "tiprack96"},
    "source": {"type": "plate96", "contents": {f"{r}1": {COMPOUNDS[i]: 60.0} for i, r in enumerate(ROWS)}},
    "buffer": {"type": "reservoir", "contents": {"A1": {"buffer": 30000.0}}},
    "assay": {"type": "plate96"},
    "waste": {"type": "reservoir"},
}

PROMPT = f"""\
You are planning a run on a simulated liquid handler. Its rules are in `environment.md` and the deck is in `deck.json`.

Eight compounds sit in column 1 of plate `source` (compound 1 `cmpd_1` in A1 down to compound 8 `cmpd_8` in H1), each at 1000 uM in 60 uL. Reservoir `buffer` holds 30 mL of assay buffer, reservoir `waste` is empty, and rack `tips` is full.

Prepare a dose-response plate on the empty plate `assay`. Each compound gets its own row (compound 1 in row A, down to compound 8 in row H): an 11-point, 3-fold dilution series from 100 uM in column 1 down to column 11. Column 12 is a buffer-only control. Every well must end with 100 uL at its stated concentration, ready for the plate reader.

Return EXACTLY:

<EVAL_ANSWER>
{{"plan": [<step>, ...]}}
</EVAL_ANSWER>

{ANSWER_NOTE}"""


def target_um(col: int) -> float:
    return TOP_UM / FOLD ** (col - 1)


def _buffer_fill(cols, vol: float, multi: bool) -> list:
    steps = []
    cols = list(cols)
    if multi:
        per = int(300 // vol)
        for i in range(0, len(cols), per):
            chunk = cols[i : i + per]
            steps.append(asp("buffer", vol * len(chunk)))
            steps += [disp("assay", vol, c) for c in chunk]
    else:
        for c in cols:
            steps += [asp("buffer", vol), disp("assay", vol, c)]
    return steps


def reference(*, multi=False, mix_vol=75.0, cycles=3, mixing=True, discard=True, last=11, transfer=50.0,
              top_stock=15.0, top_buffer=135.0, body_buffer=100.0) -> list:
    plan = [pick("tips", 1), asp("buffer", top_buffer), disp("assay", top_buffer, 1)]
    plan += _buffer_fill(range(2, 13), body_buffer, multi)
    plan.append(drop())
    plan += [pick("tips", 2), asp("source", top_stock, 1), disp("assay", top_stock, 1)]
    if mixing:
        plan.append(mix("assay", mix_vol, cycles, 1))
    for c in range(1, last):
        plan += [asp("assay", transfer, c), disp("assay", transfer, c + 1)]
        if mixing:
            plan.append(mix("assay", mix_vol, cycles, c + 1))
    if discard:
        plan += [asp("assay", transfer, last), disp("waste", transfer)]
    plan.append(drop())
    return plan


def fresh_tips_every_transfer() -> list:
    plan = [pick("tips", 1), asp("buffer", 135.0), disp("assay", 135.0, 1)]
    for c in range(2, 13):
        plan += [asp("buffer", 100.0), disp("assay", 100.0, c)]
    plan += [drop(), pick("tips", 2), asp("source", 15.0, 1), disp("assay", 15.0, 1), mix("assay", 75.0, 3, 1), drop()]
    for c in range(1, 11):
        plan += [pick("tips", c + 2), asp("assay", 50.0, c), disp("assay", 50.0, c + 1), mix("assay", 75.0, 3, c + 1)]
        if c == 10:
            plan += [asp("assay", 50.0, 11), disp("waste", 50.0)]
        plan.append(drop())
    return plan


def stock_first_then_buffer() -> list:
    plan = [pick("tips", 1)]
    for c in range(2, 13):
        plan += [asp("buffer", 100.0), disp("assay", 100.0, c)]
    plan += [drop(), pick("tips", 2), asp("source", 15.0, 1), disp("assay", 15.0, 1), drop()]
    plan += [pick("tips", 3), asp("buffer", 135.0), disp("assay", 135.0, 1), mix("assay", 75.0, 3, 1)]
    for c in range(1, 11):
        plan += [asp("assay", 50.0, c), disp("assay", 50.0, c + 1), mix("assay", 75.0, 3, c + 1)]
    plan += [asp("assay", 50.0, 11), disp("waste", 50.0), drop()]
    return plan


def buffer_with_used_tips() -> list:
    """Top well built stock-first, then the same tips go back into the buffer for every column."""
    plan = [pick("tips", 1), asp("source", 15.0, 1), disp("assay", 15.0, 1), asp("buffer", 135.0), disp("assay", 135.0, 1)]
    for c in range(2, 13):
        plan += [asp("buffer", 100.0), disp("assay", 100.0, c)]
    plan += [drop(), pick("tips", 2), mix("assay", 75.0, 3, 1)]
    for c in range(1, 11):
        plan += [asp("assay", 50.0, c), disp("assay", 50.0, c + 1), mix("assay", 75.0, 3, c + 1)]
    plan += [asp("assay", 50.0, 11), disp("waste", 50.0), drop()]
    return plan


def series_into_control() -> list:
    plan = reference(discard=False, last=12)
    plan = plan[:-1] + [asp("assay", 50.0, 12), disp("waste", 50.0), drop()]
    return plan


def one_tip_all_rows() -> list:
    """A single channel serves every row with one tip, as a hand pipettor might."""
    one = [1]
    plan = [pick("tips", 1, channels=one, rows=["A"])]
    for c in range(1, 13):
        for r in ROWS:
            v = 135.0 if c == 1 else 100.0
            plan += [asp("buffer", v, channels=one), disp("assay", v, c, channels=one, rows=[r])]
    plan += [drop(), pick("tips", 2, channels=one, rows=["A"])]
    for r in ROWS:
        plan += [asp("source", 15.0, 1, channels=one, rows=[r]), disp("assay", 15.0, 1, channels=one, rows=[r]),
                 mix("assay", 75.0, 3, 1, channels=one, rows=[r])]
        for c in range(1, 11):
            plan += [asp("assay", 50.0, c, channels=one, rows=[r]), disp("assay", 50.0, c + 1, channels=one, rows=[r]),
                     mix("assay", 75.0, 3, c + 1, channels=one, rows=[r])]
        plan += [asp("assay", 50.0, 11, channels=one, rows=[r]), disp("waste", 50.0, channels=one)]
    plan.append(drop())
    return plan


def overfilled_tip() -> list:
    plan = reference()
    plan[1] = asp("buffer", 1235.0)
    return plan


def grader() -> dict:
    all_wells = wells_in_columns(range(1, 13))
    conc = {}
    allowed = {}
    for i, r in enumerate(ROWS):
        for c in range(1, 12):
            conc[f"{r}{c}"] = {COMPOUNDS[i]: target_um(c)}
            allowed[f"{r}{c}"] = [COMPOUNDS[i], "buffer"]
        allowed[f"{r}12"] = ["buffer"]
    return {
        "type": "simulated_run",
        "config": {
            "deck": DECK,
            "plan_key": "plan",
            "checks": [
                {"name": "run_completes", "type": "run_completes"},
                {"name": "volumes", "type": "well_volumes", "labware": "assay",
                 "targets": {w: FINAL_UL for w in all_wells}, "tol_ul": 2.0},
                {"name": "concentrations", "type": "concentrations", "labware": "assay",
                 "stock": {c: STOCK_UM for c in COMPOUNDS}, "targets": conc, "rel_tol": 0.05},
                {"name": "no_contamination", "type": "purity", "items": [
                    {"labware": "assay", "allowed": allowed},
                    {"labware": "buffer", "allowed": {"A1": ["buffer"]}},
                    {"labware": "source", "allowed": {f"{r}1": [COMPOUNDS[i]] for i, r in enumerate(ROWS)}},
                ]},
                {"name": "mixed", "type": "homogeneous", "labware": "assay", "wells": all_wells},
            ],
        },
    }


READER = {
    "type": "plate_reader",
    "note": ("Run the same plan with a fluorescent dye in place of the 8 compound stocks and read the plate. On a second "
             "plate, read 8 wells of plain buffer (blanks) and 8 wells of a hand-made dye solution at the top "
             "concentration (standards). The grader sees only the reader output. Thresholds are set for the simulated "
             "reader; no real plate has been graded yet."),
    "labware": "assay",
    "model": {"dyes": {c: STOCK_UM for c in COMPOUNDS}, "gain": 2000.0, "background": 150.0, "sd_add": 4.0,
              "cv": 0.02, "saturation": 260000.0, "standard_conc": TOP_UM},
    "checks": {"min_blanks": 8, "min_standards": 4, "saturation": 260000.0, "min_blank_sd": 4.0,
               "max_standard_cv": 0.08, "control_cols": [12], "control_sd": 6.0,
               "top_col": 1, "top_tol": 0.10, "top_tol_cap": 0.20, "standard_tol": 0.10, "standard_tol_cap": 0.12,
               "k_cv": 4.0, "series_cols": list(range(1, 12)), "fold": FOLD, "fold_tol": 0.10,
               "visible_sd": 50.0, "column_tol": 0.20, "column_tol_cap": 0.30, "min_points": 5},
}

# What the plate reader alone should conclude about each scripted control, and why.
READER_EXPECT = {
    "reference": (True, ""),
    "multi_dispense_buffer": (True, ""),
    "fresh_tips_every_transfer": (True, ""),
    "stock_first_then_buffer": (True, ""),
    "bigger_mix": (True, ""),
    "no_mixing": (False, "column 1 holds 1.5 x the top concentration and saturates the reader, so the plate is refused; the series also collapses after column 1"),
    "no_final_discard": (True, "BLIND SPOT: the extra 50 uL sits in column 11, below the reader's detection limit"),
    "two_fold_series": (False, "the series falls 2-fold per column, not 3-fold"),
    "top_diluted_1_in_15": (False, "the top wells read 0.67 x the hand-made standard"),
    "series_stops_at_column_5": (False, "columns 6 and 7 read as blank where the series should still be visible"),
    "buffer_with_used_tips": (False, "carryover lights up the control column"),
    "series_into_control": (True, "BLIND SPOT: the control column gets 1/177,147 of the top concentration, below the detection limit"),
    "one_tip_all_rows": (False, "carryover from earlier rows puts a floor under the low end of each later series"),
    "overfilled_tip": (False, "NO PLATE: the run stops, so there is nothing to read"),
}


def build() -> Task:
    controls = [
        Control("reference", {"plan": reference()}, True, "buffer first, 15 uL stock into 135 uL, 50 uL transfers with a mix each time, 50 uL discarded from column 11"),
        Control("multi_dispense_buffer", {"plan": reference(multi=True)}, True, "buffer laid down 3 wells per aspirate into empty wells"),
        Control("fresh_tips_every_transfer", {"plan": fresh_tips_every_transfer()}, True, "a new tip column for each transfer (uses all 96 tips)"),
        Control("stock_first_then_buffer", {"plan": stock_first_then_buffer()}, True, "stock into the empty top well, then buffer with a separate clean tip set"),
        Control("bigger_mix", {"plan": reference(mix_vol=100.0, cycles=5)}, True, "larger, longer mixes"),
        Control("no_mixing", {"plan": reference(mixing=False)}, False, "never mixes, so each transfer draws the bottom layer",
                ["concentrations", "mixed"]),
        Control("no_final_discard", {"plan": reference(discard=False)}, False, "forgets to remove 50 uL from column 11",
                ["volumes"]),
        Control("series_stops_at_column_5", {"plan": reference(last=5)}, False,
                "stops the series at column 5 and leaves columns 6 to 11 as buffer", ["concentrations"]),
        Control("top_diluted_1_in_15", {"plan": reference(top_stock=10.0, top_buffer=140.0)}, False,
                "makes the top well 1:15 instead of 1:10, so every well is a third low", ["concentrations"]),
        Control("two_fold_series", {"plan": reference(transfer=100.0, top_stock=20.0, top_buffer=180.0, mix_vol=100.0)}, False,
                "a 2-fold series instead of 3-fold", ["concentrations"]),
        Control("buffer_with_used_tips", {"plan": buffer_with_used_tips()}, False,
                "goes back into the buffer with tips that touched compound", ["no_contamination"]),
        Control("series_into_control", {"plan": series_into_control()}, False, "runs the series into the control column",
                ["no_contamination"]),
        Control("one_tip_all_rows", {"plan": one_tip_all_rows()}, False, "one tip carries compound between rows",
                ["no_contamination"]),
        Control("overfilled_tip", {"plan": overfilled_tip()}, False, "asks a 300 uL tip for 1235 uL", ["run_completes"]),
    ]
    notes = {
        "source": "1000 uM stocks, compound 1 in A1 ... compound 8 in H1",
        "buffer": "assay buffer",
        "assay": "empty destination plate",
        "waste": "empty reservoir for discarded liquid",
    }
    return Task(
        id=ID,
        title="Dose-response plate by serial dilution",
        kind="plan",
        prompt=PROMPT,
        deck=DECK,
        grader=grader(),
        workspace={"deck.json": deck_file(DECK, notes)},
        controls=controls,
        tests="Plans a full 8 x 11 serial dilution: volume bookkeeping, mixing between transfers, the last-column discard, clean controls.",
        traps=["no mixing between transfers", "no discard from the last column", "wrong dilution ratio", "wrong top dilution",
               "series stopped early",
               "used tips back into the buffer", "series run into the control column", "one tip across rows",
               "tip capacity exceeded"],
        metadata={"eval_type": "scientific", "kit": "simulated_liquid_handler", "task": "plan", "time_horizon": "small"},
        physical=READER,
        reader_expect=READER_EXPECT,
    )
