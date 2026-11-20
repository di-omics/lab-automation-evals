# lab-automation-evals

[![ci](https://github.com/di-omics/lab-automation-evals/actions/workflows/ci.yml/badge.svg)](https://github.com/di-omics/lab-automation-evals/actions/workflows/ci.yml)

**Can an AI agent run lab work, not just analyze the data afterwards?**

6 evaluation tasks for AI agents on liquid handling. In the 3 planning tasks the agent writes a robot plan, and the
grader runs that plan on a simulated liquid handler and checks what ends up in the wells: volumes, concentrations,
mixing and contamination. The other 3 tasks ask the agent to find the fault in a colleague's plan, release or hold a
pipetting head from a dye check, and triage a robot's run log.

Public benchmarks for biology agents mostly grade data analysis; none of the 21 boards on benchmarks.bio grades
whether an agent can run the experiment. This suite grades execution: a plan can read well and still put compound
in a control column, leave a well unmixed, or go back into a reagent with a used tip.

## The tasks

| Task | The agent has to | Named mistakes the grader must catch |
|---|---|---|
| `la01_serial_dilution` | plan an 8-compound, 11-point, 3-fold dose-response plate | no mixing, no final discard, series stopped early, wrong ratio, wrong top dilution, used tips in the buffer, series into the control, one tip across rows, tip overfilled |
| `la02_normalize_plate` | normalize 24 DNA samples to 10 ng/uL in 50 uL | sub-minimum volumes, dead volume ignored, unreachable samples filled, volumes rounded, overage added, one tip across samples, no mix, TE tips reused, failures not reported |
| `la03_cherry_pick` | pick the hits of a duplicate screen into a packed plate and report the map | positive controls picked, replicates averaged, one tip for all, report disagrees with the plate, not packed, channels crossing |
| `la04_find_the_error` | find the first faulty step in a colleague's plan, name it, fix the plan | a later symptom named, a near-miss blamed, fixes that still share tips, drop the mix, add the wrong volume, or run out of tips |
| `la05_dye_qc` | release or hold an 8-channel head from a photometric dye check | fit forced through zero, columns read as channels, whole-plate statistics, plate mean only, blank not removed |
| `la06_run_log_triage` | name the wells to redo from a robot's error log | every warning treated as a failure, a continued short aspiration missed, channel and column swapped |

Each task's prompt, workspace files and grader are in `evals/<task>/`. Full detail, check by check:
[docs/TASKS.md](docs/TASKS.md).

## First agent runs: 6 of 6 passed

One blind run per task by Claude Opus 5.5, as a Claude Code subagent with a shell and Python but no simulator, each
given only that task's prompt and files ([results/agent_runs.csv](results/agent_runs.csv); answers, approaches and
the agents' own doubts in [results/agent_runs/](results/agent_runs/)). Every run passed every check.

- **The tasks are solvable as written, and the keys hold up.** An independent solver reached every answer key. The
  agents' doubts about the wording were used to clarify the rules and 3 task files after the runs; the run records
  keep a checksum of the files each agent saw.
- **The tasks are not hard yet.** With the rules written down, each agent wrote its own checker or simulator from
  `environment.md` and passed. That is the case for the next version: tasks where the rules are not all handed
  over, with real feedback from an instrument, over several rounds.
- **Not benchmark-grade.** 1 run per task, 1 model, and the blinding was by instruction, not enforced.

## How grading works

- **One simulated workcell for every task**, with its rules written down: [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md).
  An 8-channel head, 300 uL tips, a 1 uL minimum volume, dead volumes, liquids that layer until mixed, and tips that
  carry traces of everything they touched. The agent gets the same file.
- **Plans are JSON**, so any agent harness can produce one and the grader never runs agent code.
- **Every check is pass or fail**, and a task passes only if every check passes. Malformed answers fail; they never
  crash the grader.
- **Scripted controls validate every task before any model is run.** Correct answers must pass; most are
  variants of each task's reference (other tip strategies, other mixes, other predilutions), written by the same
  author. Every named mistake must fail, and fail on the check written for it. 61 controls in all: 20 must
  pass, 41 must fail, and all 61 do ([results/controls.csv](results/controls.csv)). A test also confirms that every
  check except `run_completes` is failed by at least one named mistake whose run completes, so no check is
  decoration.
- **Main answer keys are re-derived.** The tests recompute each task's main key from the workspace files with a
  second implementation: la05 and la06 in full, la02's failed samples, la03's hits, la04's first faulty step (by
  simulation) and la01's targets from the dilution scheme. The same author wrote both, so this catches slips; the
  blind runs above are the independent check.

## A plate reader as the grader

Physical execution is easy to grade if you can measure it. Run the same la01 plan on a real liquid handler with a
fluorescent dye in place of the compounds, read the plate together with blanks and a hand-made standard at the top
concentration, and the reader output is enough to grade it: clean control wells, equal top wells at the standard's
level, and every column the reader should see at its expected signal ([docs/PLATE_READER.md](docs/PLATE_READER.md)).
`lae grade-reads` grades a reader export directly.

Graded only from simulated reader output, the la01 controls show what a plate reader can and cannot see. Of the
9 named mistakes, 1 stops the run, so there is no plate to read. Of the 8 that leave a plate, the reader grader
catches 6. Both misses leave their error below the detection limit: an extra 50 uL left in the most dilute column,
and a series run one column too far into the controls ([results/reader_controls.csv](results/reader_controls.csv)).

The reader grader was also run on fresh noise draws, not just the shipped one
([results/reader_noise.csv](results/reader_noise.csv)). At the modelled reader noise (2% CV) and at 3%, the correct
plan passes in 200 of 200 draws. At 4% it passes in 197 (0 plates refused as unusable, 3 wrong verdicts); at 5%, in
176 (9 refused, 15 wrong). Every mistake the reader can see is caught in all 50 draws at every noise level.

## What the controls already show

- **The decision alone is not enough.** On la05, 4 of the 5 scripted wrong answers still reach the right call (hold
  the head). Only the per-channel fields catch them. Grading the decision alone would pass all 4.
- **What a mistake does depends on the physics.** Without a mix, a serial dilution draws diluent from the bottom of
  the well: the series collapses after the first column, so the mistake is a wrong concentration, not a style point.
- **A reader needs a standard.** Ratios between columns cannot tell a plate that is a third too weak everywhere (a
  1:15 top instead of 1:10) from a right one. A hand-made standard at the top concentration, read on a second plate,
  catches it.

## Use it

```bash
pip install -e ".[dev]"
lae grade la01_serial_dilution my_answer.json          # JSON, or text holding <EVAL_ANSWER>...</EVAL_ANSWER>
lae grade-reads la01_serial_dilution reader_export.csv  # plate,well,rfu; plate = assay, blank or standard
python -m lab_automation_evals.build                    # rebuild evals/, results/, docs/ and rerun every control
python -m pytest -q
```

Standard library only. The task files use LatchBio's public eval keys (`id`, `canary`, `task`, `data_node`,
`grader`, `metadata`, `notes`). The plan tasks use a grader type of their own, `simulated_run`, implemented in
`src/lab_automation_evals/grade.py`.

## Working with scientists

How these tasks are meant to be built and reviewed with domain scientists, and what the review has to settle before a
task counts: [docs/WORKING_WITH_SCIENTISTS.md](docs/WORKING_WITH_SCIENTISTS.md).

## Where things are

| Path | What it holds |
|---|---|
| `src/lab_automation_evals/environment.py` | the workcell's constants and the rules text |
| `src/lab_automation_evals/sim.py` | the simulator |
| `src/lab_automation_evals/grade.py` | the grader |
| `src/lab_automation_evals/reader.py` | the simulated plate reader and the reader grader |
| `src/lab_automation_evals/agent_runs.py` | grades the recorded agent runs |
| `src/lab_automation_evals/tasks/` | one module per task: prompt, deck, data, grader, scripted controls |
| `evals/` | generated: `eval.json` and workspace files per task |
| `results/` | generated: every control's outcome, the reader tables, the agent runs |
| `docs/` | the rules, the task tables (generated), the plate-reader protocol, the review method |

## Limits

- **No person has reviewed the tasks or the keys yet.** The tasks, checks and controls were written by AI models.
  AI reviewers then attacked them in 2 rounds, on the code and on the science; their findings are fixed or listed as
  open questions. That is not a scientist's review.
- **The simulator is a simplification.** Layers, the mix threshold, the contact rule and the trace model are
  modelling choices, written down in [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md) so a scientist can dispute them.
  There are no liquid classes, speeds or heights.
- **The plate-reader thresholds are set for the simulated reader.** No real plate has been graded yet. The
  simulated reader scales signal with the amount of dye in a well; how strongly a real reader responds to fill
  volume depends on the instrument.
- The data in la02, la03, la05 and la06 are simulated. Not affiliated with LatchBio.

## License

MIT. See [LICENSE](LICENSE).
