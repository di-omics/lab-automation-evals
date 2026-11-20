"""The simulator obeys each rule in environment.md."""

import pytest

from lab_automation_evals.plan import asp, disp, drop, mix, pick, ret
from lab_automation_evals.sim import normalize_well, run

DECK = {
    "tips": {"type": "tiprack96"},
    "src": {"type": "plate96", "contents": {"A1": {"x": 100.0}, "B1": {"y": 100.0}}},
    "buf": {"type": "reservoir", "contents": {"A1": {"buf": 10000.0}}},
    "dst": {"type": "plate96"},
}
ONE = dict(channels=[1])


def _run(plan):
    return run(DECK, plan)


def test_clean_transfer_and_contact_free_dispense():
    r = _run([pick("tips", 1, **ONE), asp("src", 20, 1, **ONE), disp("dst", 20, 1, **ONE), drop()])
    assert r.ok
    assert r.deck["dst"].wells["A1"].composition() == {"x": 20.0}
    assert r.deck["dst"].wells["A1"].traces == set()


def test_dead_volume_and_minimum_and_tip_capacity():
    assert not _run([pick("tips", 1, **ONE), asp("src", 96, 1, **ONE)]).ok  # 100 uL well keeps 5 uL
    assert _run([pick("tips", 1, **ONE), asp("src", 95, 1, **ONE)]).ok
    r = _run([pick("tips", 1, **ONE), asp("src", 0.5, 1, **ONE)])
    assert not r.ok and "minimum" in r.error.message
    r = _run([pick("tips", 1, **ONE), asp("buf", 301, **ONE)])
    assert not r.ok and "tips hold" in r.error.message


def test_overfill_and_missing_tip_and_double_pickup():
    plan = [pick("tips", 1, **ONE)] + [asp("buf", 100, **ONE), disp("dst", 100, 1, **ONE)] * 3
    assert _run(plan).ok
    assert not _run(plan + [asp("buf", 10, **ONE), disp("dst", 10, 1, **ONE)]).ok
    assert not _run([asp("buf", 10, **ONE)]).ok
    assert not _run([pick("tips", 1, **ONE), pick("tips", 2, **ONE)]).ok
    assert not _run([pick("tips", 1, **ONE), drop(), pick("tips", 1, **ONE)]).ok  # that spot is now empty


def test_layers_bottom_first_and_mix_threshold():
    base = [pick("tips", 1, **ONE), asp("buf", 90, **ONE), disp("dst", 90, 1, **ONE), drop(),
            pick("tips", 2, **ONE), asp("src", 10, 1, **ONE), disp("dst", 10, 1, **ONE)]
    r = _run(base + [asp("dst", 50, 1, **ONE)])
    assert r.deck.channels[0].content == {"buf": 50.0}  # unmixed: the bottom layer comes first
    r = _run(base + [mix("dst", 49, 3, 1, **ONE)])
    assert not r.deck["dst"].wells["A1"].homogeneous  # below half the well volume
    r = _run(base + [mix("dst", 50, 2, 1, **ONE)])
    assert not r.deck["dst"].wells["A1"].homogeneous  # fewer than 3 cycles
    r = _run(base + [mix("dst", 50, 3, 1, **ONE)])
    assert r.deck["dst"].wells["A1"].homogeneous
    assert not _run(base[:-1] + [mix("dst", 50, 3, 1, **ONE)]).ok  # tip still holds liquid


def test_traces_travel_and_stay_on_returned_tips():
    plan = [pick("tips", 1, **ONE), asp("src", 10, 1, **ONE), disp("dst", 10, 1, **ONE),
            asp("src", 10, 1, rows=["B"], **ONE)]
    r = _run(plan)
    assert "x" in r.deck["src"].wells["B1"].traces  # the used tip fouled the y well
    plan = [pick("tips", 1, **ONE), asp("src", 10, 1, **ONE), disp("dst", 10, 1, **ONE), ret("tips", 1, **ONE),
            pick("tips", 1, **ONE), asp("buf", 10, **ONE)]
    r = _run(plan)
    assert "x" in r.deck["buf"].wells["A1"].traces


def test_channel_rows_must_rise():
    assert _run([pick("tips", 1, channels=[1, 2], rows=["A", "C"])]).ok
    assert not _run([pick("tips", 1, channels=[1, 2], rows=["C", "A"])]).ok
    assert not _run([pick("tips", 1, channels=[2, 1])]).ok


@pytest.mark.parametrize("bad", ["not a list", [{"op": "fly"}], [{"op": "aspirate", "labware": "nope"}],
                                 [pick("tips", 13)],
                                 [pick("tips", 1, **ONE), {"op": "aspirate", "labware": "src", "column": 1,
                                                           "volume_ul": "ten", "channels": [1]}]])
def test_malformed_plans_stop_cleanly(bad):
    assert not run(DECK, bad).ok


def test_well_names():
    assert normalize_well("a01") == "A1"
    with pytest.raises(ValueError):
        normalize_well("I1")
