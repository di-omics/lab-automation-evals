"""Small constructors for plan steps, used by the reference solutions and the scripted controls."""

from __future__ import annotations


def _opt(step: dict, channels=None, rows=None) -> dict:
    if channels is not None:
        step["channels"] = list(channels)
    if rows is not None:
        step["rows"] = list(rows)
    return step


def _vol(v):
    if isinstance(v, (list, tuple)):
        return [round(float(x), 4) for x in v]
    return round(float(v), 4)


def pick(rack: str, column: int, channels=None, rows=None) -> dict:
    return _opt({"op": "pick_up_tips", "rack": rack, "column": column}, channels, rows)


def drop(channels=None) -> dict:
    return _opt({"op": "drop_tips"}, channels)


def ret(rack: str, column: int, channels=None, rows=None) -> dict:
    return _opt({"op": "return_tips", "rack": rack, "column": column}, channels, rows)


def asp(labware: str, volume, column=None, channels=None, rows=None) -> dict:
    step = {"op": "aspirate", "labware": labware}
    if column is not None:
        step["column"] = column
    step["volume_ul"] = _vol(volume)
    return _opt(step, channels, rows)


def disp(labware: str, volume, column=None, channels=None, rows=None) -> dict:
    step = {"op": "dispense", "labware": labware}
    if column is not None:
        step["column"] = column
    step["volume_ul"] = _vol(volume)
    return _opt(step, channels, rows)


def mix(labware: str, volume, cycles: int, column=None, channels=None, rows=None) -> dict:
    step = {"op": "mix", "labware": labware}
    if column is not None:
        step["column"] = column
    step["volume_ul"] = _vol(volume)
    step["cycles"] = cycles
    return _opt(step, channels, rows)
