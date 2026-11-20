# Grading a real run with a plate reader

A plan graded in the simulator can also be run on a real liquid handler and graded from a plate reader alone. This
page describes the version for `la01_serial_dilution`. **No real plate has been graded yet**; the thresholds below
are set for the simulated reader and need checking against a first real plate.

## The idea

Replace the 8 compound stocks with a fluorescent dye. Everything else stays the same: deck, plan, volumes. After the
run, the reader measures how much dye ended up in every well. A correct 3-fold series falls 3-fold per column, the
control column reads as blank, the 8 top wells read alike, and the top wells read like a hand-made solution at the
top concentration. The grader needs no access to the robot, the plan or the volumes: only the reader export.

## What you need

- An 8-channel liquid handler and a driver that can execute the plan's steps. The plan format is robot-agnostic.
  A translation to a specific driver is not included yet.
- A fluorescence plate reader and black 96-well plates.
- A fluorescent dye in assay buffer, at a stock that puts the top well (1:10 of the stock) inside the reader's
  linear range.

## Steps

1. Load the deck as in `evals/la01_serial_dilution/workspace/deck.json`, with dye stock in source wells A1 to H1.
2. Run the plan.
3. By hand, make the top concentration from the same stock (1:10 in assay buffer).
4. Read the assay plate at the dye's wavelengths. On a second plate, read 8 wells of plain assay buffer (blanks) and
   8 wells of the hand-made top solution (standards), 100 uL each.
5. Export one CSV with the columns `plate,well,rfu`, where `plate` is `assay`, `blank` or `standard`. Headers in any
   case, comma, semicolon or tab separators, decimal commas and wells written `A01` or `1A` are all read.
6. Grade it:

```bash
lae grade-reads la01_serial_dilution reader_export.csv
```

An example export, from the simulated reader on the reference plan, is
`evals/la01_serial_dilution/physical/simulated_reads_reference.csv`.

## What the reader grader checks

All thresholds are in `physical_grader` in `evals/la01_serial_dilution/eval.json`. Signal means the reading minus
the blank mean. SD means the blank standard deviation, never taken below 4 RFU (the modelled reader's noise floor).
CV means the spread of the 8 standards.

| Check | Passes when |
|---|---|
| `reader_input` | all 96 assay wells are readable, with at least 8 blanks and 4 standards, no well at the reader's ceiling, and the standards agree (robust CV, from the median absolute deviation, at most 8%) |
| `controls_clean` | every well in column 12 reads below 6 SD |
| `tops_equal` | the 8 wells of column 1 are within 10% of their median, widened to 4 x CV for a noisier reader, at most 20% |
| `top_matches_standard` | the median top well is within 10% of the median standard, widened to 4 x its standard error, at most 12% |
| `dilution_series` | every column whose expected signal (the standard divided by 3 for each column after the first) is above 50 SD reads within 20% of it (widened with the expected noise, at most 30%), in every row; at least 5 such columns; and a straight-line fit of log signal against column gives 3-fold per column +/- 10% |

An unreadable, ambiguous or incomplete export fails `reader_input` with the reason, and then fails every other
check. A number such as `12,345` with no other value in the file to settle whether the comma marks thousands or
decimals is refused rather than guessed, and rows with any other plate label (a spreadsheet's `Blank SD` summary
row, say) are refused rather than counted.

## What it can and cannot see

Of the 9 named mistakes on la01, 1 stops the run. Graded this way, the other 8 show 2 blind spots, both below the
detection limit ([results/reader_controls.csv](../results/reader_controls.csv)):

- an extra 50 uL left in column 11, the most dilute column;
- a series run one column too far, which puts 1/177,147 of the top concentration into the control column.

Other mistakes outside the scripted set that this reader cannot see, by construction:

- a series that stops at column 7 or later (columns 8 to 11 sit below the visibility limit); one that stops at
  column 6 is caught in about 2 of 3 noise draws, and one that stops at column 5 or earlier is always caught;
- compounds swapped between rows: one dye stands in for every compound;
- extra buffer that lowers the concentration but keeps the amount of dye in a well the same, since the simulated
  reader's signal follows the amount of dye.

A volume check (weighing the plate, or a second dye in the buffer) would catch the first blind spot and the last.

## How much noise it tolerates

The reference plan, read with fresh noise draws at increasing reader noise
([results/reader_noise.csv](../results/reader_noise.csv)):

| Reader CV | Correct plan passes | Plate refused as unusable | Wrong verdict |
|---|---|---|---|
| 2% (modelled) | 200 of 200 | 0 | 0 |
| 3% | 200 of 200 | 0 | 0 |
| 4% | 197 of 200 | 0 | 3 |
| 5% | 176 of 200 | 9 | 15 |

At every noise level, each of the 6 mistakes the reader can see is caught in all 50 draws.

## How the simulated reader works

Signal is proportional to the amount of dye in the well (concentration times fill volume), plus a background of
150 RFU, with 2% noise and 4 RFU of additive noise, saturating at 260,000 RFU. That roughly matches a reader whose
signal grows with fill height; how strongly a real reader responds to fill volume depends on the instrument, and a
reader that corrects for it would not see a volume error at all. A trace of a liquid that is not otherwise in the
well reads as 0.05% of its stock: a modelling choice, not a measured carryover. A liquid already present by volume
adds nothing for its traces. The noise is deterministic, so every rebuild gives the same reads.
