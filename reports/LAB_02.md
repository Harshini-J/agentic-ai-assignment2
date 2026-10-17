# Assignment 2 report · A plan RepoMind cannot quietly abandon

Every number here that has a field in `reports/LAB_02.json` goes there too: the
checker reads that file (format: `checks/FORMATS.md`, section 10.10). Give each
number its run count. Mark any vendor figure you cite with its source and the date
you read it.

## Part A · The plan artifact
Your `args` choice, `args_json` or one shape per tool with `oneOf`, and why, in two
sentences. Your strict-mode count, in two sentences: optional fields and union
types against the budgets of 24 and 16, and whether a strict request carrying the
schema was accepted (or that your vendor has no strict mode).

I chose args_json to store each step's arguments as a JSON string, because it works with strict mode (it avoids a free-form object and uses none of the union budget) and it allows the "$fill" placeholder to be used for any argument. Since strict mode cannot validate the string's contents, the executor parses and checks them against the tool's schema before execution.

All schema fields are required and non-nullable, so there are 0 optional fields and 0 union types, within the limits of 24 and 16. My test on issue 4191 returned a valid plan, confirming that Anthropic accepted the schema in strict mode, so `strict_compiles` is true.

## Part B · The validator and the boundary

| Plan | Valid | Failures (step, check) |
|---|---|---|
| `good_export_fix.json` | yes | none |
| `good_triage.json` | yes | none |
| `s18_specimen.json` | no | (2, 2), (3, 3), (5, 1) |

Your re-plan bound, `MAX_REPLANS`, and one line on why. How many of your planner's
plans, in your measured runs, broke the schema or did not end with `post_comment`
(your `schema` lines), out of how many plans.

`MAX_REPLANS = 2` allows the planner to make up to three attempts before escalating the request. Strict validation makes invalid plans less likely, so one or two retries should be enough to handle occasional mistakes. If all three attempts fail, the issue may be with the prompt or planning process, and additional retries would likely waste tokens.

Plans that failed schema validation or did not end with `post_comment` in the measured runs: 2 of 56 planner calls (both re-planned successfully; no run escalated for want of a valid plan).

Each fill-in call receives the issue text and the results of the steps listed in the current step's `depends_on`, rather than the entire history. A search step also receives the previous searches and their results, which helps it avoid repeating queries that have already failed. This keeps each call's context small and lets the dependency graph determine which information each call receives.

## Part C · Revision at a checkpoint
The checkpoint's check, in one sentence, and your revision bound, `MAX_REVISIONS`.

The checkpoint’s check passes if the search finds at least one source file (`.ts` or `.tsx`) under `src/`, outside `src/i18n/`, and fails if it returns only documentation, translation files, or no matches.

`MAX_REVISIONS = 2` allows up to two revisions per run, accepted or rejected. One revision is usually enough to fix a search that finds only documentation or translations, as in issue 4203, where the second search found the parser. The second revision allows another attempt if the first revision is rejected or does not help, without making repeated revisions routine.

## Part D · A second pass before posting
Your four external checks, one line each, and your bound, `MAX_ROUNDS`, in one
line. For each mode, `off`, `self` and `external`, which of slide 41's three gates
it passes: can a check find the error, does the critic know more than the agent,
is there a limit and a log?

**External checks (`verify`):**

1. **Parses:** The draft has a `label:` line with `bug`, `feature`, `question`, or `docs`, and a `file:` line with a path or `none`.
2. **Exists:** If a file is named, it must exist under `fixtures/repo` and cannot point outside that directory.
3. **Seen:** The run's trace must contain a `tool_call` line listing the file in its `paths`, meaning the file was found by a search or read.
4. **Agree:** A `question` label must use `file: none`, and every other label must name a file.

**Bound:** Both modes use `MAX_ROUNDS = 2`. If a draft fails, it is revised once with the reason and checked again. If it still fails, no comment is posted and the run is escalated.

| Mode | Can a check find the error? | Does the critic know more than the agent? | Is there a limit and a log? |
|---|---|---|---|
| `off` | No. The draft is not checked. | No critic is used. | Not applicable because no rounds run. |
| `self` | No. The model gives its opinion, but there is no test to check whether the revised draft is actually better. | No. The same model uses the issue and step results that were available when it wrote the draft. | Yes. `MAX_ROUNDS = 2`, with a `critique` line for each round. |
| `external` | Yes, for the four checks: format, file existence, whether the file was seen, and whether the label agrees with the file. | Yes. It checks the repository and the run's trace, which the drafting call did not check. | Yes. `MAX_ROUNDS = 2`, with a `critique` line for each round. |

The `external` mode passes all three gates but can miss semantic errors, such as choosing the wrong file that was still found during the run. The `self` mode passes only the third gate because it relies on the model's own judgment.

## Part E · Detectors and the diff
How your diff matches a traced call to a plan step.

The diff matches each call to a planned step using `plan_step`, if available. Otherwise, it checks the tool name and fixed arguments. Each step can match only one call, so repeated calls are marked `extra`, and steps that were never executed are marked `skipped`.

**The looping run.** Questions 1 to 3, each with the turns or steps that fired, and
how you answered question 2 without `depends_on`. Question 4, in one sentence.

| Question | Answer | Turns or steps |
|---|---|---|
| 1. Did any two steps do the same thing? | Yes | Turns 1 and 3 (`search "export"`), and turns 2 and 4 (`read ReportsPage.tsx`) |
| 2. Is any step's result never used? | Yes | Turns 3, 4, and 6 |
| 3. Did every planned step execute? | No | Steps 3–6 never ran |

The plan did not include `depends_on` or list any paths in its results, so I used the trace to judge whether the results were used. Turns 3 and 4 repeated the earlier calls and did not provide any new information. Turn 6's result was also unused because the run reached the turn limit before the model could read it.

**Question 4:** No, "identify the bug" and "fix the bug" were steps too coarse to check, the agent kept repeating the same work because it had no clear way to tell whether it was making progress, and eventually reached the turn limit.

**Slide 51's run.** Questions 1 to 3, each with the steps that fired. Question 4, in
one sentence. The diff's label for every step of the plan.

| Question | Answer | Steps |
|---|---|---|
| 1. Did any two steps do the same thing? | Yes | Calls 2 and 4 repeated the same `search_repo "export"` query. |
| 2.  Is any step's result never used? | No | Each step's result was used by the next step through `depends_on`. |
| 3. Did every planned step execute? | No | Step 6, "confirm the button works," did not run. |

**Question 4:** Yes, the plan had the right steps, ending with a check that the button works, but the run stopped before step 6 and reported "fixed" while `test_export_csv` was still failing, so the failure was premature stopping, not a bad plan.

**The diff, step by step:**

| Step | Action | Label |
|---|---|---|
| 1 | Reproduce the export failure | Executed |
| 2 | Locate the handler | Executed |
| 3 | Read the handler | Executed |
| 4 | Patch the handler | Executed |
| 5 | Re-run the failing case | Executed |
| 6 | Confirm the button works | Skipped |

Call 4 is marked `extra` because it repeats the search, and no remaining plan step matches it.


## Part F · What the plan and the second pass bought
Three sweeps a configuration: a pilot, not a settled difference.

| Measure | Agent | Planned, off | Planned, self | Planned, external |
|---|---|---|---|---|
| Passes, of 18 | 16 | 16 | 13 | 14 |
| Per issue, 4201 to 4206, of 3 each | 3 1 3 3 3 3 | 3 3 3 2 3 2 | 3 3 3 0 3 1 | 3 3 3 0 3 2 |
| Spread: the lowest and highest sweep, of 6 | 5 to 6 | 5 to 6 | 4 to 5 | 4 to 5 |
| Tokens per run | 16,558 | 16,676 | 25,582 | 17,651 |
| Latency per run: median, and slowest | 11.3s, 27.6s | 27.2s, 63.8s | 31.0s, 109.0s | 28.9s, 95.3s |
| Plan overhead: the mean share of prompt tokens, and how it changes with run length | | 26.6% | 18.0% | 26.2% |
| Second-pass overhead: the mean share of prompt tokens | | | 31.4% | 1.8% |
| Runs with at least one exact repeat | 0 | 7 | 12 | 8 |
| `off_plan` lines | | 0 | 0 | 0 |
| Revisions per run: mean, and maximum | | 0.67, 2 | 0.78, 2 | 0.78, 2 |
| Second-pass rounds per run: mean, and maximum | | | 1.33, 2 | 1.06, 2 |
| Drafts changed; of those fixed, and broken | | | 6; 1 fixed, 0 broken | 2; 1 fixed, 0 broken |
| Drafts held at the bound | | | 5 | 0 |

How the plan overhead changes with run length: the plan call's own share of a run's prompt tokens, over all 54 planned runs, grouped by the run's number of model calls.

| Model calls | Runs | Plan call's mean share |
|---|---|---|
| 4 to 6 | 19 | 17.2% |
| 7 to 9 | 21 | 13.1% |
| 10 or more | 14 | 9.8% |

The plan has a fixed cost, so its share of the total cost decreases as runs get longer.

The tables are generated by `eval/part_f.py` using the data in `runs/` and the tracker. Running `python -m eval.part_f` builds the tables and writes the results to `reports/LAB_02.json`.

Leave a cell empty where a measure does not apply. The script that built this
table: its path, and the command that runs it.

1. **What did the plan buy RepoMind, concretely?** Artifacts and counts, not
   qualities.

   **What the plan bought.** Slide 54 describes four main gains from planning, which I observed in my 54 planned runs:

   - **A plan in the run log:** All 54 runs started with a version-1 plan logged before the first tool call, including the model, prompt, and tool list; revisions added 40 more versions: 27 runs kept their first plan, 14 were revised once (ending at version 2) and 13 twice (ending at version 3), giving 94 plan versions in total.
   - **A validator before any tool call:** There were 56 planner calls. Two plans failed the schema or `post_comment` check and were rejected before any tool ran. All 40 revised plans passed the four validation checks. No run escalated because it could not produce a valid plan, and no run made an off-plan call (0 off_plan lines), so the refusal rule never had to fire.
   - **One approval point instead of one per action:** Each run has one plan with 4–6 steps that could be approved, instead of approving each tool call separately. Since no plans were approved in this assignment, this benefit was not measured.
   - **A diff of the plan against what ran:** Every tool call records its `plan_step`, allowing all 54 runs to be compared against their plans using Part E's diff and detectors. The detectors found exact repeated calls in 27 planned runs.

   Planning did not improve the overall pass count: planned `off` passed 16 of 18 runs, the same as the agent. It improved issue 4202 from 1/3 passes for the agent to 3/3, but lost one run each on issues 4204 and 4206.

2. **Where did it not pay?** Slide 52's four cases, applied to your six issues. On
   which would the plan cost more than the execution?

   Every comparison below is planned `off` against the agent, since `self` and `external` add a second pass's cost on top; tokens are means and times medians, over three runs each.

   - **The task is one step:** never. Every run took several model calls.
   - **The steps are known in advance:** mostly true. Almost every plan followed the same pattern: read the issue, search the repository, read a file, sometimes search and read again, and post a comment. Only the 40 checkpoint revisions changed the steps.
   - **The plan costs more than execution:** on none of the six issues. Planning and revision calls accounted for 15% to 35% of a run's prompt tokens, with the highest share on 4203 (35%) and 4204 (34%) and the lowest on 4202 (15%). Overall, the planned approach used more tokens than the agent on four issues: 4203 (16,166 vs. 13,445), 4204 (23,012 vs. 19,989), 4205 (16,047 vs. 12,133), and 4206 (16,582 vs. 14,370). It was also slower on all six issues. Issue 4205 shows this clearly: the agent answered a question that required no file correctly in all three runs, with a median time of 8.4 seconds. The planned approach took 20.8 seconds and used 32% more tokens for the same answer. Planning used fewer tokens on 4201 (12,827 vs. 21,328) and 4202 (15,419 vs. 18,080). On 4202, it also improved the pass rate from 1/3 to 3/3.
   - **Nothing uses the plan after it is written:** In this assignment, the validator, detectors, and diff used the plan. However, no person approved a plan, so the approval point did not provide a practical benefit.

3. **What did each second pass buy, and what did it cost?** Which errors each mode
   caught, whether either turned a passing draft into a failing one, what each
   added in tokens and time, what happened to issue 4206 under each, and which of
   slide 41's three gates each mode passes.

   Each mode is compared with planned `off`, which does not use a second pass.

   | | `off` | `self` | `external` |
   |---|---|---|---|
   | First drafts rejected by the check | None (no check) | 6, all wrong | 2, both wrong |
   | Drafts fixed | — | 1 (4203: `src/ingest/parse.ts` to `src/ingest/parser.ts`) | 1 (4201: nonexistent `src/email/templates.ts` to `src/notifications/templates.ts`) |
   | Drafts held at the limit (nothing posted) | — | 5 | 0 |
   | Correct drafts made incorrect | — | 0 | 0 |
   | Wrong drafts allowed through | 2: nonexistent `src/import/dedupe.ts` (4206) and `bug` with `file: none` (4204) | None among the drafts it checked | 3: `src/export/scheduler.ts` (4204), `src/exportUtils.ts` (4206), and the 4204 rewrite to `question` with `file: none` |
   | Passes out of 18 | 16 | 13 | 14 |
   | Tokens per run; second-pass share | 16,676; none | 25,582; 31.4% | 17,651; 1.8% |
   | Latency: median, slowest | 27.2s, 63.8s | 31.0s, 109.0s | 28.9s, 95.3s |
   | Issue 4206: passes out of 3 | 2; one run used a nonexistent path | 1; two wrong files were rejected, then the drafts were held | 2; one run used a wrong file it had read |
   | Slide 41: can a check find the error? | No check | No; it relies on the model's judgment | Yes, for the four checks it runs |
   | Slide 41: does the critic know more? | No critic | No; same model and evidence | Yes; repository and run trace |
   | Slide 41: is there a limit and a log? | Not applicable | Yes; 2 rounds and a `critique` line per round | Yes; 2 rounds and a `critique` line per round |

   Neither second pass turned a correct answer into a wrong one. `self` correctly rejected every wrong draft it checked but fixed only one; the other five were held after the rewrites failed the critic's second review. Since those drafts were already wrong, holding them did not cost any passes. Its lower pass rate than `off` may reflect variation across the three runs per issue.

   `external` added little cost because it only called the model when a draft failed validation. However, it missed wrong files the run had already seen and allowed an incorrect 4204 rewrite through: changing `bug` to `question` with `file: none` passed all four checks but was still wrong. The fourth external failure, 4204 sweep 3, was not a second-pass result: the run escalated before any draft was checked or posted, because the model answered in text and made no `post_comment` call.

4. **Which failure did no detector catch?** Did you see a run that reported success
   before the task was done, and how did you know?

   Seven runs posted a wrong comment but ended normally, as if the task were complete: the agent twice on 4202 (`src/api/reports.ts`), `off` on 4204 (`bug` with `file: none`) and 4206 (`src/import/dedupe.ts`), and `external` twice on 4204 (`src/export/scheduler.ts` and `question` with `file: none`) and once on 4206 (`src/exportUtils.ts`).

   No detector caught the wrong answer itself. In four of the five planned runs, a detector fired, but for a different issue: `repeat_check` flagged a duplicate file read (4206 `off` and 4204 `external`, sweep 1), while `expected_result_check` flagged failed reads of nonexistent files (`src/jobs/weeklySummary.js` and, for `external`, `src/jobs/sendWeeklySummary.js`) on the two 4204 runs. Both still posted a comment with `file: none`. On 4206 `external`, sweep 3, nothing fired because every step ran, no calls repeated, and verification accepted `src/exportUtils.ts` because the file existed and had been seen. The agent's two wrong 4202 runs had no plan, and `repeat_check` found no repeats in any agent run, so no detector applied. I confirmed all seven wrong answers using `check()` in `eval/check_triage.py` against `fixtures/answers.yaml`, which checks the final result independently. The six runs that escalated posted nothing and handed the issue to a person.


## Part G · Note-taking against compaction
Your `COMPACT_AT`, and what your progress file holds.

`COMPACT_AT = 1500` tokens is a test setting, calculated as characters divided by 4, so every run compacts its history. During compaction, all history entries except the newest are replaced with a model-written summary.

The progress file, `runs/<run_id>.progress.json`, is updated after every step. It stores an `about` line explaining that it records progress, `steps_done` (completed step IDs in order), and `paths` (paths returned by searches or read by the run, in order). It does not store search terms. With `--notes on`, this information is shown exactly as written on every executor call and the question call. With `--notes off`, it is saved but never shown.

The questions are asked after the comment is posted, or just before the run ends if it escalates. This follows section 10.6 of `checks/FORMATS.md`, which takes precedence over the handout's instruction to ask before drafting the comment. Therefore, the history includes the posted comment when the questions are asked. This is the same in both settings, so it does not bias the comparison.

| Run | Issue | Progress file shown | Compacted before the questions | Answers right, of 6 |
|---|---|---|---|---|
| `notes-4203-s01-e3686b` | 4203 | no | yes | 6 |
| `notes-4203-s02-e84915` | 4203 | no | yes | 6 |
| `notes-4203-s01-b8721b` | 4203 | yes | yes | 6 |
| `notes-4203-s02-0306c5` | 4203 | yes | yes | 6 |
| `notes-4204-s01-2ab1d7` | 4204 | no | yes | 6 |
| `notes-4204-s02-0c2cfa` | 4204 | no | yes | 6 |
| `notes-4204-s01-bbb264` | 4204 | yes | yes | 6 |
| `notes-4204-s02-78daff` | 4204 | yes | yes | 6 |
| `notes-4206-s01-698bea` | 4206 | no | yes | 3 |
| `notes-4206-s02-b20fe1` | 4206 | no | yes | 5 |
| `notes-4206-s01-28faca` | 4206 | yes | yes | 6 |
| `notes-4206-s02-f49f1b` | 4206 | yes | yes | 6 |

The table is built by `eval/part_g.py` from the 12 runs' traces, with `python -m eval.part_g`, which also writes `context` in `reports/LAB_02.json`. Totals: 32 of 36 answers right without the file, 36 of 36 with it.

1. **What did the progress file keep that compaction lost,** and what did the file
   cost in tokens?

   All four wrong answers came from runs without the progress file, both on issue 4206. Three were documentation paths that appeared only in the `currency` search results, and compaction removed them from the run's memory: `CHANGELOG.md` (forgotten in both runs) and `docs/API.md` (forgotten in one). Each was answered "no" when asked whether the run had seen it. The summary kept details of the code files the run had read, but dropped the documentation paths that only appeared in search results. The fourth answer was "yes" for `src/db/migrations/002_currency.sql`, which the run had never seen. The search returned a changelog line, "currency (migration 002)", whose wording matches the file name. The model may have mistaken seeing a reference to the migration for seeing the actual file. With the progress file, all 36 answers were correct, because it recorded every path and compaction did not affect it.

   The file was small: 87 to 120 tokens, shown on 5 to 8 calls. That adds at most about 470 to 960 prompt tokens per run, roughly 3 to 4% of a run's prompt tokens. Average tokens per run were actually higher without the file (28,589 against 25,334), but each run took a different path. With six runs per setting, that comparison can't measure the file's cost.

2. **Which context operations did RepoMind need?** Structured note-taking,
   sub-agent isolation, just-in-time retrieval and compaction, in that order: for
   each, whether your longest run in Part F needed it, and what it would have cost.

   My longest Part F run is `planned-4204-s02-23d2f4` (a `self` run on 4204): 35,652 prompt tokens over 13 model calls (1 plan, 7 execute, 2 revise, 3 critique) and 7 tool calls, with prompts from 1,135 to at most 5,322 tokens.

   | Operation | Needed in the longest run? | What it would have cost |
   |---|---|---|
   | Structured note-taking | No: the plan already records each step and its status outside the conversation. | 7 file writes and about 610–840 prompt tokens (87–120 tokens per executor call), roughly 2% of the run. |
   | Sub-agent isolation | No: triaging one issue is a single task with nothing to split off. | A fresh context for each sub-task, costing at least about 1,100 tokens each, plus any information left out of the sub-agent's summary. |
   | Just-in-time retrieval | Yes, and already in use: the run fetched its one file (about 660 tokens) only when the read step needed it, with the path taken from the search results. | One fetch, with no extra model call. |
   | Compaction | No: the largest prompt was 5,322 tokens, far below the model's context limit. | A summarizing call each time the history crossed the threshold, plus the risk of losing information. In Part G, the 6 runs without the progress file forgot 3 previously seen paths and claimed 1 unseen path. |

## Assistance
Which AI tool, what it wrote, and what you checked.

AI tools: Anthropic Claude Code; GitHub Copilot (inline autocomplete in VS Code)

Date: 12 - 16 October 2026

Understanding the existing codebase: Claude Code helped me understand the starter code before I wrote my own: what the harness provides (`harness/client.py`, `harness/trace.py`, `harness/runner.py`, `harness/tracker.py`), what `ctx` provides (`ctx.prompt`, `ctx.call_tool`, `ctx.issue_number`, `ctx.repo_summary`), how the Assignment 1 way (`agent/loop.py`) is reused as the baseline, and where each format is defined in `checks/FORMATS.md` (the plan, the trace lines and `reports/LAB_02.json`).

I used it to explain parts of the assignment I didn't understand.

- **Part A:** what the plan artifact must hold, the choice between `args_json` and one shape per tool with `oneOf`, and how the strict-mode budgets (24 optional fields, 16 union types) are counted.
- **Part B:** what each of the validator's four checks tests, why the `s18_specimen.json` plan fails where it does, how `MAX_REPLANS` bounds re-planning, how the executor's boundary refuses an off-plan call and logs it as `off_plan`, and how `"$fill"` arguments are filled in at run time by one model call that sees the issue and the results of the steps the current step depends on.
- **Part C:** what the checkpoint after the first `search_repo` step checks, why `revise_plan` must keep finished steps unchanged, why the reviser sees only structured step results and never the issue text (so untrusted text cannot reshape the plan), and how `MAX_REVISIONS` bounds the revisions per run.
- **Part D:** what the four external checks in `verify` test (parses, exists, seen, agree), how the `self` and `external` second passes differ, and how `MAX_ROUNDS` bounds them.
- **Part E:** how a traced call is matched to a plan step, what the detectors (`repeat_check`, `orphan_check`, `expected_result_check`) and the ladder questions ask, and what the diff labels (`executed`, `skipped`, `reordered`, `extra`) mean.
- **Part F:** how each measure in the results table is calculated from the traces and the tracker (passes, spread, plan overhead, second-pass overhead, repeats, revisions), and what each of the four questions asks for.
- **Part G:** how the progress file differs from compaction, how `COMPACT_AT` works, and why the six questions are asked at the end of every run (`checks/FORMATS.md` section 10.6 takes precedence over the handout).

**What it wrote:**

- GitHub Copilot: inline autocomplete suggestions while I was coding
- Claude Code: `ARCHITECTURE.md`, searched the repo and identified where the model call and tools are invoked
- Claude Code: one-off commands for reading traces, counting plan artifacts, finding failed runs
- Claude Code: drafts of all the prompts in `prompts/` (`planner.md`, `executor.md`, `reviser.md`, and `self_critique.md` and `rewrite.md`), which I edited
- Claude Code: `eval/part_f.py` and `eval/part_g.py`, which build the Part F table and the Part G scores
- Claude Code: drafts of `agent/plan_schema.json`, `make_plan` and `revise_plan` in `agent/plan.py`, and `agent/validator.py`, which I edited and tested
- Claude Code: drafts of `ways/planned.py` (the reject exit and schema check, the executor and its off-plan boundary, the revision checkpoint, and the second-pass loop), which I edited and tested
- Claude Code: drafts of `verify` and `self_critique` in `agent/critique.py`, `agent/detectors.py`, `agent/diff.py` and `ways/notes.py`

**What I checked:**

- **Prompts in `prompts/`:** Tested each on dev issues, reviewed traces, and updated `executor.md` and `planner.md` based on repeated searches and incorrect result limits.
- **`agent/plan_schema.json`, `make_plan`, and `agent/validator.py`:** Verified strict-mode limits (0 optional fields, 0 union types), tested a real planner call on issue 4191, and checked validator results.
- **`ways/planned.py`:** Tested scripted models for invalid plans, schema errors, missing comments, and off-plan calls. Verified checkpointing, revision validation, version logging, and preservation of completed steps.
- **`agent/critique.py` and the second pass:** Tested seen/unseen file checks and ran real `self` and `external` modes on dev issues.
- **`agent/detectors.py` and `agent/diff.py`:** Checked outputs against slide 51 and the handout's expected answers.
- **`ways/notes.py`:** Tested scripted triage, progress-file contents, and compaction; confirmed all 12 Part G runs compacted before their questions.
- **`eval/part_f.py` and `eval/part_g.py`:** Matched results against tracker counts and recomputed per-issue results.
- **72 Part F runs:** Checked endings and latency; reran external tests affected by laptop sleep and spending-limit failures.
- **`ARCHITECTURE.md`:** Verified every `file:line` reference against the source code.
- **Autocomplete suggestions:** Manually checked every suggestion.
