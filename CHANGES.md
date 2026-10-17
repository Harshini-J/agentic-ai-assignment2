# CHANGES.md

Three lines per assignment: what it added, what it removed, what it constrained.
Removals are logged like additions.

## Assignment 1
- **Added:** a bounded tool loop; four ways to triage an issue (a direct call, a workflow, an agent, and a hybrid of the two); a grounded success check that reads the tracker; a results script
- **Removed:** nothing
- **Constrained:** every agent run to three bounds checked in code (steps, tokens, wall clock); success to what the tracker holds for the run's ID

## Assignment 2
- **Added:** a plan artifact the model writes and a validator checks before any tool runs; one revision checkpoint after the first search; a second pass before posting in three modes (`off`, `self`, `external`); three detectors (repeat, orphan and expected-result checks) and a diff of the plan against the trace; a progress file and a compaction, with six questions at the end of each notes run
- **Removed:** nothing
- **Constrained:** the executor to the active plan (an off-plan call is refused and logged as `off_plan`); the comment to one post, made only after the second pass's last round; re-planning, revising and second-pass rounds to `MAX_REPLANS = 2`, `MAX_REVISIONS = 2` and `MAX_ROUNDS = 2`; a run with no valid plan, or whose draft is still failing at the last round, ends escalated with nothing posted.
