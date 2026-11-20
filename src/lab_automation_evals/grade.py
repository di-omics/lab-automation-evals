"""Grader for the `simulated_run` type: run the submitted plan, then check the final deck and the answer.

Every check is binary. A task passes only if every check passes (all-of); `score` is the
share of checks passed, kept for diagnosis.
"""

from __future__ import annotations

import json
import math

from .sim import EPS, normalize_well, run

OPEN_TAG, CLOSE_TAG = "<EVAL_ANSWER>", "</EVAL_ANSWER>"

PLAN_CHECKS = {"run_completes", "well_volumes", "concentrations", "purity", "homogeneous", "empty", "cherry_pick"}
CHECK_TYPES = PLAN_CHECKS | {"answer_choice", "answer_set", "answer_numeric"}


def _reject_constant(name):
    raise ValueError(f"{name} is not allowed in an answer")


def parse_answer(answer):
    """Accept a dict, a JSON string, or text holding <EVAL_ANSWER>{...}</EVAL_ANSWER>. NaN and Infinity are refused."""
    if isinstance(answer, dict):
        return answer
    if isinstance(answer, str):
        text = answer
        start = answer.find(OPEN_TAG)  # str.find, not a regex: linear time on any input
        if start >= 0:
            end = answer.find(CLOSE_TAG, start + len(OPEN_TAG))
            if end >= 0:
                text = answer[start + len(OPEN_TAG) : end]
        try:
            parsed = json.loads(text, parse_constant=_reject_constant)
        except (ValueError, RecursionError):  # JSONDecodeError is a ValueError
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _fmt(x: float) -> str:
    return f"{x:.4g}"


def _check_run(res, chk):
    return res.ok, ("completed" if res.ok else str(res.error))


def _check_volumes(res, chk):
    lw = res.deck[chk["labware"]]
    bad = []
    for w, target in chk["targets"].items():
        vol = lw.wells[w].volume
        if abs(vol - target) > chk["tol_ul"] + EPS:
            bad.append(f"{w} {_fmt(vol)} uL (want {_fmt(target)})")
    return not bad, "all within tolerance" if not bad else f"{len(bad)} wells off: " + "; ".join(bad[:6])


def _check_conc(res, chk):
    lw = res.deck[chk["labware"]]
    stock = chk["stock"]
    bad = []
    for w, targets in chk["targets"].items():
        well = lw.wells[w]
        for liquid, target in targets.items():
            got = well.concentration(liquid, stock[liquid])
            if abs(got - target) > chk["rel_tol"] * abs(target) + EPS:
                bad.append(f"{w} {liquid} {_fmt(got)} (want {_fmt(target)})")
    return not bad, "all within tolerance" if not bad else f"{len(bad)} values off: " + "; ".join(bad[:6])


def _check_purity(res, chk):
    bad = []
    for item in chk["items"]:
        lw = res.deck[item["labware"]]
        allowed = item.get("allowed", {})
        default = item.get("default")
        for w, well in lw.wells.items():
            ok = allowed.get(w, default)
            if ok is None:
                continue
            extra = sorted(well.components() - set(ok))
            if extra:
                where = lw.name if lw.is_reservoir else f"{lw.name} {w}"
                bad.append(f"{where} holds {', '.join(extra[:3])}{'...' if len(extra) > 3 else ''}")
    return not bad, "no foreign liquid anywhere checked" if not bad else f"{len(bad)} contaminated: " + "; ".join(bad[:6])


def _check_homogeneous(res, chk):
    lw = res.deck[chk["labware"]]
    bad = [w for w in chk["wells"] if not lw.wells[w].homogeneous]
    return not bad, "all mixed" if not bad else f"{len(bad)} wells not mixed: " + ", ".join(bad[:8])


def _check_empty(res, chk):
    lw = res.deck[chk["labware"]]
    bad = [w for w in chk["wells"] if lw.wells[w].volume > EPS or lw.wells[w].traces]
    return not bad, "all untouched" if not bad else f"{len(bad)} wells should be empty: " + ", ".join(bad[:8])


def _norm_items(values, kind):
    out = set()
    for v in values:
        if kind == "int":
            if isinstance(v, str) and v.strip().isdigit():
                v = int(v.strip())  # "6" for 6: formatting is not the point of the task
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ValueError(v)
            if isinstance(v, float) and not (math.isfinite(v) and v.is_integer()):
                raise ValueError(v)
            out.add(int(v))
        elif kind == "well":
            out.add(normalize_well(v))
        elif kind == "pick_sources":
            if isinstance(v, dict):
                try:
                    out.add(f"{str(v['source_plate']).strip().upper()}:{normalize_well(v['source_well'])}")
                except (KeyError, TypeError):
                    raise ValueError(v)
            else:
                plate, _, well = str(v).partition(":")
                out.add(f"{plate.strip().upper()}:{normalize_well(well)}")
        else:
            out.add(str(v).strip())
    return out


def _check_answer_choice(ans, chk):
    got = ans.get(chk["key"]) if ans else None
    if isinstance(got, str):
        got = got.strip().lower()
        if got.isdigit() and any(isinstance(a, int) for a in chk["accept"]):
            got = int(got)  # "5" for 5: formatting is not the point of the task
    accept = [a.lower() if isinstance(a, str) else a for a in chk["accept"]]
    ok = not isinstance(got, bool) and got in accept
    text = repr(got)
    return ok, f"answered {text if len(text) <= 40 else text[:37] + '...'}"


def _check_answer_set(ans, chk):
    got = ans.get(chk["key"]) if ans else None
    if not isinstance(got, list):
        return False, f"{chk['key']} is not a list"
    try:
        got_set = _norm_items(got, chk.get("kind"))
    except ValueError as e:
        return False, f"unreadable item {e}"
    want = _norm_items(chk["value"], chk.get("kind"))
    if got_set == want:
        return True, f"{len(got_set)} items, all correct"
    missing, extra = sorted(want - got_set, key=str), sorted(got_set - want, key=str)
    return False, f"missing {len(missing)}, extra {len(extra)}"


def _check_answer_numeric(ans, chk):
    got = ans.get(chk["key"]) if ans else None
    if isinstance(got, str):
        try:
            got = float(got.strip())  # "46.9" for 46.9
        except ValueError:
            return False, f"{chk['key']} is not a number"
    if isinstance(got, bool) or not isinstance(got, (int, float)):
        return False, f"{chk['key']} is not a number"
    try:
        got = float(got)
    except OverflowError:
        return False, f"{chk['key']} is out of range"
    if not math.isfinite(got):
        return False, f"{chk['key']} is not a finite number"
    return abs(got - chk["value"]) <= chk["tol"] + 1e-9, f"answered {_fmt(got)}"


def _check_cherry_pick(res, ans, chk):
    """The hit map must match the plate: packed destination wells, one hit each, right volume."""
    dest = res.deck[chk["labware"]]
    entries = ans.get(chk["map_key"]) if ans else None
    if not isinstance(entries, list):
        return False, f"{chk['map_key']} is not a list"
    mapped = {}
    try:
        for e in entries:
            src = f"{str(e['source_plate']).strip().upper()}:{normalize_well(e['source_well'])}"
            mapped[normalize_well(e["dest_well"])] = src
    except (KeyError, TypeError, ValueError):
        return False, "a map entry lacks source_plate, source_well or dest_well"
    if len(mapped) != len(entries):
        return False, "two map entries share a destination well"
    if len(set(mapped.values())) != len(mapped):
        return False, "a source well is listed twice"
    if not entries:
        return False, "the map is empty"
    packed = chk["packed_order"][: len(mapped)]
    if set(mapped) != set(packed):
        return False, "picks are not packed into the first destination wells in column order"
    bad = []
    for w, src in mapped.items():
        well = dest.wells[w]
        liquid = chk["liquid_of"].get(src)
        if liquid is None:
            bad.append(f"{w}: no such source {src}")
            continue
        if abs(well.volume - chk["volume_ul"]) > chk["tol_ul"] + EPS:
            bad.append(f"{w} holds {_fmt(well.volume)} uL")
        elif well.components() != {liquid}:
            bad.append(f"{w} does not hold only {src}")
    for w in chk["packed_order"][len(mapped):]:
        if dest.wells[w].volume > EPS or dest.wells[w].traces:
            bad.append(f"{w} should be empty")
    return not bad, "map matches the plate" if not bad else "; ".join(bad[:6])


def grade(answer, config: dict) -> dict:
    unknown = [c["type"] for c in config["checks"] if c["type"] not in CHECK_TYPES]
    if unknown:
        raise ValueError(f"unknown check type(s) in the grader config: {unknown}")  # a broken task, not a broken answer
    ans = parse_answer(answer)
    fields = {}
    res = None
    plan_key = config.get("plan_key")
    if plan_key:
        plan = ans.get(plan_key) if ans else None
        res = run(config["deck"], plan if plan is not None else "missing")
    for chk in config["checks"]:
        try:
            ok, detail = _run_check(chk, ans, res)
        except Exception as e:  # an answer shape no check anticipated: fail the field, never crash
            ok, detail = False, f"could not grade this field ({type(e).__name__})"
        fields[chk["name"]] = {"passed": bool(ok), "detail": detail}
    n_pass = sum(f["passed"] for f in fields.values())
    out = {
        "passed": n_pass == len(fields),
        "score": round(n_pass / len(fields), 4) if fields else 0.0,
        "fields": fields,
    }
    if res is not None:
        out["run"] = res.summary()
    return out


def _run_check(chk, ans, res):
    t = chk["type"]
    if ans is None:
        return False, "no parsable answer"
    if t in PLAN_CHECKS and (res is None or (not res.ok and t != "run_completes")):
        return False, "the run did not complete"
    if t == "run_completes":
        return _check_run(res, chk)
    if t == "well_volumes":
        return _check_volumes(res, chk)
    if t == "concentrations":
        return _check_conc(res, chk)
    if t == "purity":
        return _check_purity(res, chk)
    if t == "homogeneous":
        return _check_homogeneous(res, chk)
    if t == "empty":
        return _check_empty(res, chk)
    if t == "cherry_pick":
        return _check_cherry_pick(res, ans, chk)
    if t == "answer_choice":
        return _check_answer_choice(ans, chk)
    if t == "answer_set":
        return _check_answer_set(ans, chk)
    return _check_answer_numeric(ans, chk)
