"""A deterministic liquid-handling simulator: executes a JSON plan under the rules in environment.py.

It tracks, per well, the liquid as layers (bottom first) and the set of trace contaminants;
per channel, the tip, the liquid inside it and the traces it carries. Nothing is random.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field

from .environment import (
    LABWARE_TYPES,
    MIN_VOLUME_UL,
    MIX_MIN_CYCLES,
    MIX_MIN_FRACTION,
    N_CHANNELS,
    ROWS,
    TIP_MAX_UL,
)

EPS = 1e-6


class PlanError(Exception):
    """A step broke a rule. `step` is 1-based."""

    def __init__(self, step: int, message: str):
        super().__init__(f"step {step}: {message}")
        self.step = step
        self.message = message


def normalize_well(name: str) -> str:
    """'a01' -> 'A1'."""
    name = str(name).strip().upper()
    if len(name) < 2 or name[0] not in ROWS or not name[1:].isdigit():
        raise ValueError(f"not a well name: {name!r}")
    return f"{name[0]}{int(name[1:])}"


def well_order_column_major(rows: int = 8, cols: int = 12) -> list[str]:
    return [f"{ROWS[r]}{c}" for c in range(1, cols + 1) for r in range(rows)]


def _add(into: dict, comp: dict, scale: float = 1.0) -> None:
    for k, v in comp.items():
        if v * scale > 0:
            into[k] = into.get(k, 0.0) + v * scale


def _same_mix(a: dict, b: dict) -> bool:
    """True if two liquids have the same composition by proportion (buffer on buffer is still one liquid)."""
    ta, tb = sum(a.values()), sum(b.values())
    if ta <= EPS or tb <= EPS:
        return False
    keys = {k for k, v in a.items() if v > EPS} | {k for k, v in b.items() if v > EPS}
    return all(abs(a.get(k, 0.0) / ta - b.get(k, 0.0) / tb) <= 1e-9 for k in keys)


@dataclass
class Well:
    max_ul: float
    dead_ul: float
    layers: list = field(default_factory=list)  # list of {liquid: uL}, bottom first
    traces: set = field(default_factory=set)

    @property
    def volume(self) -> float:
        return sum(sum(layer.values()) for layer in self.layers)

    def composition(self) -> dict:
        out: dict = {}
        for layer in self.layers:
            _add(out, layer)
        return out

    def components(self) -> set:
        """Every liquid present, in volume or as a trace."""
        return {k for k, v in self.composition().items() if v > EPS} | set(self.traces)

    @property
    def homogeneous(self) -> bool:
        layers = [layer for layer in self.layers if sum(layer.values()) > EPS]
        return all(_same_mix(layers[0], layer) for layer in layers[1:])

    def add_layer(self, comp: dict, traces: set) -> None:
        if sum(comp.values()) > EPS:
            if self.layers and _same_mix(self.layers[-1], comp):
                _add(self.layers[-1], comp)  # the same liquid on top of itself stays one layer
            else:
                self.layers.append(dict(comp))
        self.traces |= traces

    def take_from_bottom(self, volume: float) -> dict:
        taken: dict = {}
        remaining = volume
        while remaining > EPS and self.layers:
            layer = self.layers[0]
            lv = sum(layer.values())
            if lv <= remaining + EPS:
                _add(taken, layer)
                remaining -= lv
                self.layers.pop(0)
            else:
                frac = remaining / lv
                _add(taken, layer, frac)
                self.layers[0] = {k: v * (1 - frac) for k, v in layer.items()}
                remaining = 0.0
        return taken

    def homogenize(self) -> None:
        comp = self.composition()
        self.layers = [comp] if sum(comp.values()) > EPS else []

    def concentration(self, liquid: str, stock: float = 1.0) -> float:
        vol = self.volume
        if vol <= EPS:
            return 0.0
        return self.composition().get(liquid, 0.0) / vol * stock


@dataclass
class Tip:
    residue: set = field(default_factory=set)


@dataclass
class Channel:
    tip: Tip | None = None
    content: dict = field(default_factory=dict)
    content_traces: set = field(default_factory=set)

    @property
    def volume(self) -> float:
        return sum(self.content.values())


class Labware:
    def __init__(self, name: str, kind: str, contents: dict | None = None, tips=None):
        if kind not in LABWARE_TYPES:
            raise ValueError(f"unknown labware type {kind!r} for {name!r}")
        self.name = name
        self.kind = kind
        spec = LABWARE_TYPES[kind]
        self.n_rows = spec["rows"]
        self.n_cols = spec["cols"]
        if kind == "tiprack96":
            self.spots: dict = {}
            cols = range(1, 13) if tips in (None, "full") else tips
            for c in range(1, 13):
                for r in ROWS:
                    self.spots[f"{r}{c}"] = Tip() if c in cols else None
            self.wells = {}
        else:
            self.wells = {
                f"{ROWS[r]}{c}": Well(spec["max_ul"], spec["dead_ul"])
                for c in range(1, self.n_cols + 1)
                for r in range(self.n_rows)
            }
            for w, comp in (contents or {}).items():
                self.wells[normalize_well(w)].add_layer(comp, set())

    @property
    def is_reservoir(self) -> bool:
        return self.kind == "reservoir"

    def tips_left(self) -> int:
        return sum(1 for t in self.spots.values() if t is not None)


class Deck:
    def __init__(self, spec: dict):
        self.labware = {}
        for name, item in spec.items():
            self.labware[name] = Labware(
                name, item["type"], contents=item.get("contents"), tips=item.get("tip_columns")
            )
        self.channels = [Channel() for _ in range(N_CHANNELS)]
        self.tips_used = 0

    def __getitem__(self, name: str) -> Labware:
        return self.labware[name]


@dataclass
class RunResult:
    ok: bool
    deck: Deck
    steps_run: int
    error: PlanError | None = None

    def summary(self) -> dict:
        return {
            "completed": self.ok,
            "steps_run": self.steps_run,
            "error": None if self.error is None else str(self.error),
            "tips_used": self.deck.tips_used,
        }


def _channels(step: dict, i: int, default_all: bool = True) -> list[int]:
    chans = step.get("channels")
    if chans is None:
        return list(range(1, N_CHANNELS + 1)) if default_all else []
    if not isinstance(chans, list) or not chans:
        raise PlanError(i, "channels must be a non-empty list")
    for c in chans:
        if not isinstance(c, int) or isinstance(c, bool) or not 1 <= c <= N_CHANNELS:
            raise PlanError(i, f"channel {_short(c)} does not exist")
    if any(b <= a for a, b in zip(chans, chans[1:])):
        raise PlanError(i, "channels must be listed in increasing order without repeats")
    return chans


def _volumes(step: dict, i: int, n: int) -> list[float]:
    v = step.get("volume_ul")
    vols = v if isinstance(v, list) else [v] * n
    if len(vols) != n:
        raise PlanError(i, f"volume_ul has {len(vols)} values for {n} channels")
    out = []
    for x in vols:
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            raise PlanError(i, f"volume_ul {_short(x)} is not a number")
        try:
            v = float(x)
        except OverflowError:
            raise PlanError(i, "volume_ul is too large") from None
        if not math.isfinite(v):
            raise PlanError(i, f"volume_ul {_short(x)} is not a finite number")
        out.append(v)
    return out


def _short(x) -> str:
    text = repr(x)
    return text if len(text) <= 40 else text[:37] + "..."


def _targets(step: dict, i: int, lw: Labware, chans: list[int]) -> list[str]:
    if lw.is_reservoir:
        col = step.get("column")
        if col is not None and (isinstance(col, bool) or not isinstance(col, int) or col != 1):
            raise PlanError(i, f"{lw.name} is a reservoir: give no column or rows")
        if step.get("rows") is not None:
            raise PlanError(i, f"{lw.name} is a reservoir: give no column or rows")
        return ["A1"] * len(chans)
    col = step.get("column")
    if isinstance(col, bool) or not isinstance(col, int) or not 1 <= col <= lw.n_cols:
        raise PlanError(i, f"{lw.name} has no column {_short(col)}")
    rows = step.get("rows")
    if rows is None:
        rows = [ROWS[c - 1] for c in chans]
    if not isinstance(rows, list) or len(rows) != len(chans):
        raise PlanError(i, "rows must list one row per active channel")
    idx = []
    for r in rows:
        r = str(r).strip().upper()
        if r not in ROWS[: lw.n_rows] or len(r) != 1:
            raise PlanError(i, f"{lw.name} has no row {_short(r)}")
        idx.append(ROWS.index(r))
    if any(b <= a for a, b in zip(idx, idx[1:])):
        raise PlanError(i, "rows must be strictly increasing with channel number")
    return [f"{ROWS[r]}{col}" for r in idx]


def _labware(deck: Deck, step: dict, key: str, i: int, kind: str | None = None) -> Labware:
    name = step.get(key)
    if not isinstance(name, str) or name not in deck.labware:
        raise PlanError(i, f"no labware named {_short(name)} on the deck")
    lw = deck[name]
    if kind == "tiprack96" and lw.kind != "tiprack96":
        raise PlanError(i, f"{name} is not a tip rack")
    if kind == "liquid" and lw.kind == "tiprack96":
        raise PlanError(i, f"{name} is a tip rack, not a liquid container")
    return lw


def _touch(ch: Channel, well: Well) -> None:
    well.traces |= ch.tip.residue
    ch.tip.residue |= well.components()


def execute_step(deck: Deck, step: dict, i: int) -> None:
    if not isinstance(step, dict):
        raise PlanError(i, "a step must be a JSON object")
    op = step.get("op")
    if op == "pick_up_tips":
        rack = _labware(deck, step, "rack", i, "tiprack96")
        chans = _channels(step, i)
        spots = _targets(step, i, rack, chans)
        for c, s in zip(chans, spots):
            ch = deck.channels[c - 1]
            if ch.tip is not None:
                raise PlanError(i, f"channel {c} already holds a tip")
            if rack.spots[s] is None:
                raise PlanError(i, f"no tip at {rack.name} {s}")
        for c, s in zip(chans, spots):
            deck.channels[c - 1].tip = rack.spots[s]
            rack.spots[s] = None
            deck.tips_used += 1
    elif op == "drop_tips":
        chans = step.get("channels")
        if chans is None:
            chans = [n + 1 for n, ch in enumerate(deck.channels) if ch.tip is not None]
            if not chans:
                raise PlanError(i, "no channel holds a tip")
        else:
            chans = _channels(step, i)
        for c in chans:
            ch = deck.channels[c - 1]
            if ch.tip is None:
                raise PlanError(i, f"channel {c} holds no tip")
            ch.tip, ch.content, ch.content_traces = None, {}, set()
    elif op == "return_tips":
        rack = _labware(deck, step, "rack", i, "tiprack96")
        chans = _channels(step, i)
        spots = _targets(step, i, rack, chans)
        for c, s in zip(chans, spots):
            ch = deck.channels[c - 1]
            if ch.tip is None:
                raise PlanError(i, f"channel {c} holds no tip")
            if ch.volume > EPS:
                raise PlanError(i, f"channel {c} still holds liquid")
            if rack.spots[s] is not None:
                raise PlanError(i, f"{rack.name} {s} is not empty")
        for c, s in zip(chans, spots):
            ch = deck.channels[c - 1]
            rack.spots[s] = ch.tip
            ch.tip, ch.content, ch.content_traces = None, {}, set()
    elif op in ("aspirate", "dispense", "mix"):
        lw = _labware(deck, step, "labware", i, "liquid")
        chans = _channels(step, i)
        wells = _targets(step, i, lw, chans)
        vols = _volumes(step, i, len(chans))
        if op == "mix":
            cycles = step.get("cycles")
            if isinstance(cycles, bool) or not isinstance(cycles, int) or cycles < 1:
                raise PlanError(i, "mix needs an integer number of cycles of at least 1")
        for c, w, v in zip(chans, wells, vols):
            ch = deck.channels[c - 1]
            well = lw.wells[w]
            where = f"{lw.name}" if lw.is_reservoir else f"{lw.name} {w}"
            if ch.tip is None:
                raise PlanError(i, f"channel {c} holds no tip")
            if v < MIN_VOLUME_UL - EPS:
                raise PlanError(i, f"{v:g} uL is below the {MIN_VOLUME_UL:g} uL minimum")
            if op == "aspirate":
                if ch.volume + v > TIP_MAX_UL + EPS:
                    raise PlanError(i, f"channel {c} would hold {ch.volume + v:g} uL; tips hold {TIP_MAX_UL:g}")
                if v > well.volume - well.dead_ul + EPS:
                    raise PlanError(
                        i, f"{where} holds {well.volume:g} uL; aspirating {v:g} would go below its dead volume"
                    )
                _touch(ch, well)
                _add(ch.content, well.take_from_bottom(v))
                ch.content_traces |= well.traces
            elif op == "dispense":
                if v > ch.volume + EPS:
                    raise PlanError(i, f"channel {c} holds {ch.volume:g} uL, cannot dispense {v:g}")
                if well.volume + v > well.max_ul + EPS:
                    raise PlanError(i, f"{where} would hold {well.volume + v:g} uL; max is {well.max_ul:g}")
                if well.volume > EPS:
                    _touch(ch, well)
                frac = min(1.0, v / ch.volume) if ch.volume > EPS else 0.0
                portion = {k: x * frac for k, x in ch.content.items()}
                ch.content = {k: x * (1 - frac) for k, x in ch.content.items() if x * (1 - frac) > EPS}
                well.add_layer(portion, set(ch.content_traces))
            else:
                if ch.volume > EPS:
                    raise PlanError(i, f"channel {c} must be empty to mix (holds {ch.volume:g} uL)")
                if v > TIP_MAX_UL + EPS:
                    raise PlanError(i, f"mix volume {v:g} uL exceeds the {TIP_MAX_UL:g} uL tip")
                if v > well.volume - well.dead_ul + EPS:
                    raise PlanError(i, f"{where} holds {well.volume:g} uL, too little to mix {v:g}")
                _touch(ch, well)
                if v >= MIX_MIN_FRACTION * well.volume - EPS and step["cycles"] >= MIX_MIN_CYCLES:
                    well.homogenize()
    else:
        raise PlanError(i, f"unknown op {_short(op)}")


def run(deck_spec: dict, plan) -> RunResult:
    deck = Deck(copy.deepcopy(deck_spec))
    if not isinstance(plan, list):
        return RunResult(False, deck, 0, PlanError(0, "the plan must be a JSON list of steps"))
    for n, step in enumerate(plan, start=1):
        try:
            execute_step(deck, step, n)
        except PlanError as e:
            return RunResult(False, deck, n - 1, e)
        except Exception as e:  # malformed input the checks above did not anticipate
            return RunResult(False, deck, n - 1, PlanError(n, f"invalid step ({type(e).__name__})"))
    # A failed step may be partly executed (earlier channels already moved); graders never read a failed run's deck.
    return RunResult(True, deck, len(plan))
