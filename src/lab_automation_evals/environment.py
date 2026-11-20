"""The simulated workcell every task shares: its constants and the rules text agents receive.

The rules text is the single source for `docs/ENVIRONMENT.md` and for the `environment.md`
file placed in every task workspace, so the agent and the grader read the same physics.
"""

N_CHANNELS = 8
ROWS = "ABCDEFGH"

TIP_MAX_UL = 300.0
MIN_VOLUME_UL = 1.0
MIX_MIN_FRACTION = 0.5
MIX_MIN_CYCLES = 3

LABWARE_TYPES = {
    "plate96": {"rows": 8, "cols": 12, "max_ul": 300.0, "dead_ul": 5.0},
    "reservoir": {"rows": 1, "cols": 1, "max_ul": 100000.0, "dead_ul": 2000.0},
    "tiprack96": {"rows": 8, "cols": 12},
}

RULES_MD = """\
# The simulated workcell

Every task in this suite runs on the same simulated liquid handler. These are its rules.
The grader executes plans with exactly these rules; nothing else is assumed.

## Hardware

- One pipetting head with 8 independent channels, numbered 1 to 8.
- Tips hold at most 300 uL. Every tip comes from a 96-position tip rack.
- The smallest volume a channel can aspirate or dispense is 1 uL.
- All active channels in one step work in the same plate column. Within a step, channels act one
  after another, in channel order.
- By default channel `i` serves row `i` (channel 1 row A ... channel 8 row H). A step may
  instead give `rows`: one row per active channel, in strictly increasing order. The channels
  move independently, so they need not be one row apart, but they cannot cross, and two
  channels never enter the same plate well.
- A reservoir is one large trough: every active channel reaches it in the same step.

## Labware

| Type | Wells | Max volume per well | Dead volume per well |
|---|---|---|---|
| `plate96` | 8 rows (A-H) x 12 columns | 300 uL | 5 uL |
| `reservoir` | 1 (address it with no column and no rows) | 100 mL | 2 mL |
| `tiprack96` | 8 x 12 tip positions | - | - |

You cannot aspirate into the dead volume: a well must keep at least its dead volume. In
`deck.json`, a reservoir's contents are listed under `A1`, its only well. Volumes are real
numbers; there is no volume step.

## Liquids

- Liquid added to a well forms a new layer on top of what is there, unless it is the same liquid as the
  top layer (buffer on buffer stays one layer).
- Channels aspirate from the bottom of a well. In a well that has not been mixed since its
  last addition, you draw the bottom layer first.
- A `mix` makes the well homogeneous only if its volume is at least half the liquid in the
  well and it runs at least 3 cycles. A smaller mix changes nothing. Mixing needs an empty
  tip, and the mix volume can be at most 300 uL and at most what can be aspirated from the
  well (its volume minus its dead volume).
- Liquid inside a tip counts as mixed. A dispense cannot push out more than the tip holds.
- A well is homogeneous when it holds one layer: one liquid, or liquids mixed since the last
  addition. A well is ready for the next instrument only if it is homogeneous.

## Contact and carryover

- A tip touches the liquid in a well when it aspirates, when it mixes, and when it
  dispenses into a well that already holds liquid. Dispensing into an empty well is
  contact-free.
- On every touch, the tip leaves in the well a trace of everything it has touched before,
  and picks up a trace of everything in the well. Traces never leave a tip: discarding the
  tip is the only way to lose them.
- Liquid aspirated from a well carries that well's traces with it, including any the tip has
  just left there. A contact-free dispense adds the liquid and the traces it carries, and
  nothing from the tip itself.
- A trace has no volume that matters for concentrations, but a trace of a liquid that the
  task does not mean to be in that well counts as contamination.
- A tip returned to a rack keeps its traces.

## The plan format

A plan is a JSON list of steps, executed in order. Steps are numbered from 1.

```json
{"op": "pick_up_tips", "rack": "tips", "column": 1}
{"op": "aspirate", "labware": "buffer", "volume_ul": 100}
{"op": "dispense", "labware": "assay", "column": 2, "volume_ul": 100}
{"op": "mix", "labware": "assay", "column": 2, "volume_ul": 75, "cycles": 3}
{"op": "drop_tips"}
```

| Op | Fields | What it does |
|---|---|---|
| `pick_up_tips` | `rack`, `column`, optional `channels`, `rows` | Each active channel picks up the tip at its row in that rack column. |
| `aspirate` | `labware`, `column` (not for a reservoir), `volume_ul`, optional `channels`, `rows` | Draws liquid into each active channel's tip. |
| `dispense` | same as `aspirate` | Pushes liquid out of each active channel's tip. |
| `mix` | same as `aspirate`, plus `cycles` | Aspirates and dispenses back `cycles` times. |
| `drop_tips` | optional `channels` | Discards tips to the trash. |
| `return_tips` | `rack`, `column`, optional `channels`, `rows` | Puts tips back into empty rack positions. |

- `channels` is a list such as `[1, 2, 3]`. When it is absent, all 8 channels are active
  (for `drop_tips`, every channel that holds a tip).
- `rows` is a list of row letters, one per active channel, such as `["B", "E"]`.
- `volume_ul` is one finite number for every active channel, or a list with one number per
  active channel.
- `pick_up_tips` needs every active channel to be empty.
- `drop_tips` discards the tips and any liquid still in them. Without `channels` it needs at
  least one channel holding a tip; with `channels`, every listed channel must hold one.
- `return_tips` needs empty tips, and each rack position must be empty.
- A step that breaks a rule stops the run at that step, as a real robot would, and the task
  fails.
"""
