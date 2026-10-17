# ARCHITECTURE.md · RepoMind on the seven layers

For each layer: what does this job, and where is it enforced. Cite code as a file
path and line number joined by a colon, inside backticks; a checker opens every
reference (`checks/FORMATS.md`, section 8). A layer held only by a sentence in a
prompt (any file under `prompts/`) is **EMPTY**, and so is a layer nothing does
yet. Status is one of: present, partial (say what is missing), or **EMPTY**. Each
assignment brings this file up to date.

What each layer is for (Lecture 1, slides 40 to 42):

- **Model**: reasoning, choosing tools, generating text.
- **Harness**: runs the loop, builds each prompt, trims old history.
- **Tools**: where the system acts on the world.
- **Memory & State**: what survives a step, a session, a restart.
- **Control & Policy**: what the system may do, and when it must ask.
- **Observability**: a step-by-step record of what it did.
- **Evaluation**: measuring quality, before and after release.

The table below is RepoMind as Assignment 2 leaves it: the Harness row now cites the validator and the boundary, and Memory & State and Control & Policy are no longer empty.

| Layer | What does this job | Where it is enforced | Status |
|---|---|---|---|
| Model | the configured model plans, fills in each step's arguments, runs the second pass and writes the compaction summary; called only through the metered client | `harness/client.py:116` | present |
| Harness | `PlannedRun` makes a plan, validates it, re-plans up to `MAX_REPLANS`, logs plan v1 before any tool runs, runs the steps in order, refuses any call outside the active step, and revises at one checkpoint after the first search, only when its check fails (up to `MAX_REVISIONS`); the notes way trims old history by compacting it; the plain agent way still runs `run_loop` with three bounds checked before every call | plan loop at `ways/planned.py:122`; validator at `agent/validator.py:36`; v1 logged at `ways/planned.py:153`; boundary at `ways/planned.py:305`; revision at `ways/planned.py:173`; compaction at `ways/notes.py:157`; bounds at `agent/loop.py:38`, `agent/loop.py:41`, `agent/loop.py:44` | present |
| Tools | four tools behind one registry; the executor runs only the active step's tool; `post_comment` stamps the run_id | registry at `tools/__init__.py:52`; run_id stamp at `harness/tracker.py:60`; off-plan call refused at `ways/planned.py:305` | present |
| Memory & State | the versioned plan holds each step's status; in the notes way, a progress file and a compacted history | `ways/notes.py:115`, `ways/notes.py:157`, `ways/notes.py:175` | partial: survives a step, but nothing carries into a later run |
| Control & Policy | the validator rejects a bad plan; one post per run, after the second pass when it is on; re-plans, revisions and rounds capped; a failure ends escalated with nothing posted; the agent way's loop is bounded in steps, tokens and time | `agent/validator.py:36`; caps at `ways/planned.py:76`, `ways/planned.py:77`, `ways/planned.py:78`; one post at `ways/planned.py:240`; hold at `ways/planned.py:399`; bounds at `agent/loop.py:38`, `agent/loop.py:41`, `agent/loop.py:44` | partial: no person approves a plan or a write |
| Observability | one trace line per model and tool call, plus `plan`, `schema`, `rejected`, `off_plan`, `revision`, `critique`, `compaction` and `question` events; three detectors and a plan-vs-trace diff read them back | model call at `harness/trace.py:54`; tool call at `harness/trace.py:75`; events at `ways/planned.py:131`, `ways/planned.py:137`, `ways/planned.py:305`, `ways/planned.py:203`, `ways/planned.py:388`, `ways/notes.py:175`, `ways/notes.py:217`; detectors at `agent/detectors.py:85`, `agent/detectors.py:93`, `agent/detectors.py:103`; diff at `agent/diff.py:25` | partial: read after the run, no live alerts |
| Evaluation | the grounded check reads the tracker, never the agent; a second pass before posting (`off`, `self`, `external`); Part F compares configurations, Part G scores the notes runs; a ledger caps spend | grounded check at `eval/check_triage.py:7`; second pass at `ways/planned.py:361`; `eval/part_f.py:197`, `eval/part_g.py:51`; ledger total at `harness/runner.py:109` | partial: offline only |

**Empty layers:** 0 of 7, and four are partial. Assignment 1 left two empty (Memory & State and Control & Policy). Assignment 2 fills both in code: the plan, the progress file and the compaction hold run state, and the validator, the one-post rule, the off-plan refusal and, when it is on, the second pass hold the write policy. They stay partial because nothing carries into a later run and no person approves a plan or a write.