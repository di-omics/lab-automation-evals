"""Answer keys re-derived a second way, not read back from the code that wrote them."""

import csv
import io
import json
import math
from pathlib import Path

from lab_automation_evals.grade import grade
from lab_automation_evals.environment import ROWS

ROOT = Path(__file__).resolve().parents[1]


def _rec(task_id):
    return json.loads((ROOT / "evals" / task_id / "eval.json").read_text())


def _ws(task_id, name):
    return (ROOT / "evals" / task_id / "workspace" / name).read_text()


def _check(rec, name):
    return next(c for c in rec["grader"]["config"]["checks"] if c["name"] == name)


def test_la01_targets_are_3_fold_from_100():
    conc = _check(_rec("la01_serial_dilution"), "concentrations")["targets"]
    for r in ROWS:
        for c in range(1, 12):
            (liquid, value), = conc[f"{r}{c}"].items()
            assert math.isclose(value, 100.0 / 3 ** (c - 1), rel_tol=1e-6)
            assert liquid == f"cmpd_{ROWS.index(r) + 1}"


def test_la02_failed_samples_from_the_csv():
    rows = list(csv.DictReader(io.StringIO(_ws("la02_normalize_plate", "concentrations.csv"))))
    usable = 30.0 - 5.0
    failed = sorted(r["well"] for r in rows if float(r["concentration_ng_per_ul"]) < 10
                    or 500.0 / float(r["concentration_ng_per_ul"]) > usable)
    key = _check(_rec("la02_normalize_plate"), "failed_samples")["value"]
    assert sorted(key) == failed == ["B3", "D2", "F1"]


def test_la03_hits_from_the_csv():
    rows = list(csv.DictReader(io.StringIO(_ws("la03_cherry_pick", "screen_results.csv"))))
    hits = sorted(f"{r['plate']}:{r['well']}" for r in rows
                  if 2 <= int(r["well"][1:]) <= 11
                  and float(r["rep1_pct_inhibition"]) >= 50 and float(r["rep2_pct_inhibition"]) >= 50)
    key = _check(_rec("la03_cherry_pick"), "hit_selection")["value"]
    assert sorted(key) == hits and len(hits) == 14


def test_la04_first_faulty_step_by_simulation():
    rec = _rec("la04_find_the_error")
    plan = json.loads(_ws("la04_find_the_error", "colleague_plan.json"))
    cfg = {**rec["grader"]["config"], "checks": [_check(rec, "no_contamination")]}
    first = next(k for k in range(1, len(plan) + 1) if not grade({"corrected_plan": plan[:k]}, cfg)["passed"])
    assert _check(rec, "first_error_step")["accept"] == [first] == [5]


def test_la05_key_from_the_csvs():
    std = [(float(r["volume_ul"]), float(r["absorbance_450"]))
           for r in csv.DictReader(io.StringIO(_ws("la05_dye_qc", "standards.csv")))]
    n = len(std)
    mx = sum(x for x, _ in std) / n
    my = sum(y for _, y in std) / n
    k = sum((x - mx) * (y - my) for x, y in std) / sum((x - mx) ** 2 for x, _ in std)
    b = my - k * mx
    by_ch = {}
    for r in csv.DictReader(io.StringIO(_ws("la05_dye_qc", "qc_plate.csv"))):
        by_ch.setdefault(ROWS.index(r["well"][0]) + 1, []).append((float(r["absorbance_450"]) - b) / k)
    failing, worst = [], None
    for ch, v in sorted(by_ch.items()):
        m = sum(v) / len(v)
        sd = math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))
        if abs(m - 50) / 50 > 0.05 or sd / m > 0.03:
            failing.append(ch)
        if worst is None or abs(m - 50) > abs(worst - 50):
            worst = m
    rec = _rec("la05_dye_qc")
    assert _check(rec, "failing_channels")["value"] == failing == [6]
    assert _check(rec, "decision")["accept"] == ["no_go"]
    assert abs(_check(rec, "worst_channel_mean_ul")["value"] - worst) < 1e-3


def test_la06_key_from_the_log():
    """Map every ERROR line to the well its channel served in that column; WARN lines map to nothing."""
    import re

    log = _ws("la06_run_log_triage", "run_log.txt")
    wells = set()
    column = None
    for line in log.splitlines():
        m = re.search(r"pick_up_tips tips col (\d+)", line)
        if m:
            column = int(m.group(1))
        if " ERROR " in line:
            ch = int(re.search(r"channel (\d+):", line).group(1))
            wells.add(f"{ROWS[ch - 1]}{column}")
    key = _check(_rec("la06_run_log_triage"), "wells_to_repeat")["value"]
    assert sorted(wells) == sorted(key) == ["C4", "E7", "H9"]
    assert sum(" WARN " in line for line in log.splitlines()) == 4
