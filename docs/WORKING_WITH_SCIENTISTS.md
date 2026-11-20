# Building an eval with scientists

An eval is only as good as the scientific judgment written into it. This is the method these tasks follow, and what
a reviewing scientist still has to settle before any task counts.

## The method

1. **Start from a decision, not a dataset.** Ask the scientist: "Show me a result that looks right but would make
   you do the wrong thing next." For a dilution plate, that might be a plate where every well has the right volume
   and the control column holds compound. The task is built around catching that.

2. **Write the decision rule and the acceptance rule together.** The acceptance rule: the reference answer and every
   defensible variant pass, and every named wrong analysis fails, on the check written for it. These scripted
   controls are written and run before any model sees the task.

3. **A second scientist solves it blind**, from the prompt and workspace files alone. (For these tasks a blind AI
   run per task has been done, and its doubts were used; a blind scientist has not.) Each disagreement is resolved
   in one of 3 ways:
   - the question was ambiguous: fix the prompt;
   - both answers are defensible: widen what passes, and add the new answer as a passing control;
   - one answer is wrong: add it as a named mistake that must fail.

4. **Write down the physics.** Every modelling choice the grader relies on goes into
   [ENVIRONMENT.md](ENVIRONMENT.md), where a scientist can dispute it. An unwritten assumption cannot be reviewed.

5. **Validate the task like an assay.** Positive controls (correct plans pass), negative controls (named mistakes
   fail), and a measured readout where one exists. A task without both kinds of control does not ship. Once models
   run, ask the questions you would ask of any assay: is there headroom above the best model, and do repeats agree?

6. **Check what the grader can see.** The plate-reader grader for la01 misses 2 of the 8 named mistakes that
   leave a plate to read, because both leave their error below its detection limit. That is a property of the
   readout, not of the agent. Either the protocol changes (a second dye, a volume check) or the limit is stated next
   to every score.

## Open questions for review

None of these has been reviewed by a person yet.

| Task | What a scientist needs to settle |
|---|---|
| all | The contact rule: dispensing into a well that already holds liquid counts as contact. Many protocols dispense above the liquid and would call that contact-free. Is the stricter rule the right default? |
| all | The mix rule: at least half the well volume and at least 3 cycles, or nothing. Is a partial mix better modelled as partial? |
| all | The trace model: any contact leaves a trace, and a trace of a foreign liquid fails the plate. Is that too strict for reagents that do not interfere? |
| la01 | Is 5% the right tolerance on concentration for a dose-response plate? |
| la02 | Is a 1:10 predilution the expected fix below the 1 uL minimum, or should a different final volume also pass? |
| la02 | Boundary cases on purpose: A2 needs exactly the 1 uL minimum; G2 leaves 0.96 uL of sample spare and H3 2.7 uL. A scientist who keeps re-run volume would call G2 failed; the prompt as written says it can be made. Which should pass? |
| la03 | The hit rule is given. Should the task instead give the assay and let the agent set the rule? |
| la04 | The key is step 5, the first trip back into the reagent with a used tip; the prompt defines a faulty step as one that breaks a rule or puts a liquid where it does not belong. Would a scientist name step 1 (one tip set for the whole plate) instead? |
| la05 | Are +/-5% accuracy and 3% CV per channel the right acceptance criteria at 50 uL? Channel 1 (+4.6%) and channel 3 (CV 2.9%) are near misses on purpose. |
| la01 reader | Are the reader thresholds (6 SD for a clean control, each visible column within 20% of its expected signal, top wells within 10% of the standard) right for a real fluorescence reader? |
| la06 | Is a low-reservoir warning with 3.15 mL left (above the 2 mL dead volume) safe to ignore? C4 got no reagent at all and could be rescued by adding it now rather than redone: should the task ask which wells need action instead of which to redo? |
