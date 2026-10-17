"""Way 5, planned: RepoMind with a plan it cannot quietly abandon. This file is yours.

Assignment 2, Parts B, C and D. Like every way, run(ctx) -> None (see ways/__init__.py):

    python run.py --way planned --set dev
    python run.py --way planned --critique self --set dev      # or external; off is the default

The run, in order (checks/FORMATS.md, section 10):

  1. Plan: agent.plan.make_plan(ctx.client, ctx.issue_number, ctx.tools.schemas,
     trace=ctx.trace). The planner never sees the issue.
  2. Check, then validate. First the plan against agent/plan_schema.json, with
     harness.schema.errors (a vendor may accept "strict" and not enforce it), and
     that its last step is post_comment (a plan without one passes the four checks
     and posts nothing); a plan that breaks either writes
     ctx.trace.event("schema", errors=...). Then agent.validator.validate(plan). A
     plan that fails any of these is rejected and re-planned, at most MAX_REPLANS
     times; then the run escalates: ctx.trace.end("escalated", detail), no tool
     call, nothing posted.
  3. Log: ctx.trace.plan(1, plan), before the first tool call.
  4. Execute the steps in order, each tool call through ctx.call_tool, naming the
     plan step it runs for: ctx.call_tool(n, tool, args, plan_step=step["id"]). Where a step
     has arguments marked "$fill", one model call fills them in: offer it that
     step's tool alone, and trace it with ctx.trace.model_call(n,
     response, purpose="execute"). Act on the tool calls a response holds,
     whatever its stop_reason says. The executor may run, retry or halt a step; it
     may not add, drop or reorder one. A call that is not the current step's tool
     never runs: refuse it and write ctx.trace.event("off_plan", step=..., tool=...).
  5. Part C: revise only at one checkpoint, after a search step: the first search
     step, and any search step a revision added or changed, until MAX_REVISIONS is
     spent; and only when the check there fails (a check in code, not in a prompt,
     such as "the search returned at least one source file, not only documentation
     or translations"): revise_plan, which never changes a step that is done but may
     change a failed one to retry it, then check the new version against the schema
     and validate it, write
     ctx.trace.event("revision", checkpoint=..., version=..., valid=...), and log a
     valid one with ctx.trace.plan(version, plan). A revision that fails the
     validator never runs, and counts against the bound.
  6. Part D: before post_comment, the second pass, in the mode ctx.critique names
     (off, self or external), at most MAX_ROUNDS rounds. A round checks the
     current draft (agent.critique.verify, or agent.critique.self_critique) and
     writes ctx.trace.event("critique", round=..., mode=..., result="pass" or
     "fail", reason=..., changed=..., draft=...). A draft that fails, with a round
     left, is rewritten by one model call given the reason, traced with
     purpose="critique", and the next round checks the new draft. A draft still
     failing in the last round is held: not posted, and the run ends escalated.
     Nothing is posted until the last round, and a run posts one comment at most.

The comment is Assignment 1's: two lines, label: and file: (section 1). A run that
finishes its plan can leave its ending to the runner, which writes completed.

Part G's ways/notes.py extends this way without changing it, so build this one with
hooks it can override: for example an executor class whose methods run after every
step, build what each model call sees, and run before the comment.

The checker reads MAX_REPLANS, MAX_REVISIONS and MAX_ROUNDS from this module, and
runs this way against scripted models (harness/scripted.py). You can run them too,
free:

    python run.py --way planned --backend harness.scripted:AlwaysInvalidPlanner --set dev
    python run.py --way planned --backend harness.scripted:OffPlanExecutor --set dev
    python run.py --way planned --critique external --backend harness.scripted:DraftNamesUnseenFile --set dev
"""

from __future__ import annotations

import json

from agent.plan import SCHEMA_PATH, make_plan, revise_plan
from agent.validator import validate
from harness.formats import FILL
from harness.schema import errors

from agent.critique import self_critique, verify

MAX_REPLANS = 2        # Part B: re-plans after a rejected plan before you escalate; say why in your report
MAX_REVISIONS = 2      # Part C: revisions a run (at least 1), accepted and rejected alike; say why in your report
MAX_ROUNDS = 2      # Part D: second-pass rounds a run, 1 or 2, the same in both modes

RESULT_CHARS = 6000

def schema_problems(plan: dict) -> list[str]:
    """The schema check, args_json parsing, and the last-step rule, before the four checks."""
    body = {k: v for k, v in plan.items() if k != "meta"}
    problems = errors(body, json.loads(SCHEMA_PATH.read_text()))
    steps = plan.get("steps") or []

    # args_json is only a string to the schema, so check that it really holds a JSON object.
    for step in steps:
        if not isinstance(step, dict) or not isinstance(step.get("args_json"), str):
            continue   # a missing or non-string args_json is already reported by errors()
        try:
            args = json.loads(step["args_json"])
        except json.JSONDecodeError:
            problems.append(f"step {step.get('id')}: args_json is not valid JSON")
            continue
        if not isinstance(args, dict):
            problems.append(f"step {step.get('id')}: args_json is not a JSON object")

    if not steps or not isinstance(steps[-1], dict) or steps[-1].get("tool") != "post_comment":
        problems.append("the last step does not call post_comment")
    return problems

def _without_status(step: dict) -> dict:
    """A step minus its status, to tell whether a revision changed it."""
    return {k: v for k, v in step.items() if k != "status"}

class PlannedRun:

    def __init__(self, ctx):
        self.ctx = ctx
        self.plan = None
        self.n = 0              # model calls the executor has made (the trace's step number)
        self.results = {}       # step id -> the tool's result text
        self.issue_text = ""
        self.version = 0          # the active plan version
        self.revisions = 0        # revision attempts so far, accepted and rejected
        self.checkpoints = set()  # ids of search steps whose results get checked
        self.step_results = []  # one entry per step that ran
        self.posted = False 

    def make_valid_plan(self):
        """The reject exit: plan, check, validate, re-plan up to MAX_REPLANS."""
        feedback = None
        for attempt in range(1, MAX_REPLANS + 2):
            plan = make_plan(self.ctx.client, self.ctx.issue_number, self.ctx.tools.schemas,
                             trace=self.ctx.trace, feedback=feedback)

            problems = schema_problems(plan)
            if problems:
                self.ctx.trace.event("schema", errors=problems, attempt=attempt)
                feedback = "It broke the plan format: " + "; ".join(problems) + "."
                continue

            result = validate(plan)
            if not result["valid"]:
                self.ctx.trace.event("rejected", failures=result["failures"], attempt=attempt)
                feedback = "It failed these validator checks: " + json.dumps(result["failures"]) + "."
                continue

            return plan
        return None

    def run(self) -> None:
        self.plan = self.make_valid_plan()
        if self.plan is None:
            self.ctx.trace.end("escalated", f"no valid plan in {MAX_REPLANS + 1} attempts")
            return

        for step in self.plan["steps"]:
            step["status"] = "pending"           # nothing has run yet
        self.version = 1
        self.ctx.trace.plan(1, self.plan)        # logged before any tool call

        # The checkpoint: after the first search step.
        first_search = next((s["id"] for s in self.plan["steps"] if s["tool"] == "search_repo"), None)
        if first_search is not None:
            self.checkpoints.add(first_search)

        while True:
            # The next step still to run, in the active version's order.
            step = next((s for s in self.plan["steps"] if s["status"] == "pending"), None)
            if step is None:
                break                             # the plan finished: the runner writes `completed`
            if not self.run_step(step):
                return                            # escalated
            if step["tool"] == "search_repo" and step["id"] in self.checkpoints:
                self.checkpoints.discard(step["id"])
                self.at_checkpoint(step)

    def at_checkpoint(self, step: dict) -> None:
        """The one checkpoint, after a checkpoint search: revise only when the check fails."""
        while self.revisions < MAX_REVISIONS and self.check_fails(step):
            self.revisions += 1
            if self.revise(step):
                return                            # a valid new version is now active

    def check_fails(self, step: dict) -> bool:
        """The checkpoint's check: did the search find at least one source file,
        a .ts or .tsx file under src/ (not a translation)? If not, it fails."""
        content = self.results.get(step["id"], "")
        for line in content.splitlines():
            path = line.split(":", 1)[0]          # each hit is "path:line: text"
            if (path.startswith("src/") and path.endswith((".ts", ".tsx"))
                    and not path.startswith("src/i18n/")):
                return False                       # found a source file: the check passes
        return True                                # only docs, translations, or no matches

    def revise(self, step: dict) -> bool:
        """Revise at the checkpoint, then check, validate and log the new version.
        Returns True if a valid new version is now active."""
        new = revise_plan(self.ctx.client, self.plan, self.step_results, trace=self.ctx.trace)
        version = self.version + 1

        # The new version is checked like a first plan: the schema first, then the four checks.
        problems = schema_problems(new)
        failures = []
        if problems:
            self.ctx.trace.event("schema", errors=problems, version=version)
        else:
            failures = validate(new)["failures"]
        valid = not problems and not failures
        self.ctx.trace.event("revision", checkpoint="after_search", version=version,
                             valid=valid, failures=failures)
        if not valid:
            return False                  # it never runs; the attempt still counts

        # Statuses for the new version: done stays done; a failed step reruns only if
        # the revision changed it; everything else is pending.
        old = {s["id"]: s for s in self.plan["steps"]}
        for s in new["steps"]:
            before = old.get(s["id"])
            changed = before is None or _without_status(before) != _without_status(s)
            if before is not None and before.get("status") == "done":
                s["status"] = "done"
            elif before is not None and before.get("status") == "failed" and not changed:
                s["status"] = "failed"
            else:
                s["status"] = "pending"
                if s["tool"] == "search_repo" and changed:
                    self.checkpoints.add(s["id"])   # a new or changed search is checked again

        self.plan = new
        self.version = version
        self.ctx.trace.plan(version, new)   # only a valid version is logged
        return True

    def run_step(self, step: dict) -> bool:
        """Run one step. Returns False if the run escalated."""
        tool = step["tool"]
        args = json.loads(step["args_json"])

        if any(value == FILL for value in args.values()):
            args = self.fill(step, args)
            if args is None:
                return False

        if tool == "post_comment":
            if self.posted:                         # one comment per run
                self.ctx.trace.end("escalated", f"step {step['id']}: a second post_comment")
                return False
            args = self.before_comment(step, args)  # the second pass, before anything is posted
            if args is None:
                return False                        # held: nothing posted, the run escalated

        # Check the final arguments against the tool's own schema before the call.
        problems = errors(args, self.tool_schema(tool)["input_schema"])
        problems += [f"{key}: still {FILL}" for key, value in args.items() if value == FILL]
        if problems:
            self.ctx.trace.end("escalated", f"step {step['id']}: arguments break {tool}'s schema: "
                               + "; ".join(problems))
            return False

        result = self.ctx.call_tool(self.n, tool, args, plan_step=step["id"])
        self.record(step, args, result)
        if tool == "post_comment" and not result.is_error:
            self.posted = True
        self.after_step(step, result)
        return True

    def record(self, step: dict, args: dict, result) -> None:
        """Mark the step done or failed, keep its result, and add its step result (FORMATS 10.3)."""
        content = result.content or ""
        status, count, paths, code = "done", None, [], None

        if result.is_error:
            status, code = "failed", "tool_error"
        elif step["tool"] == "search_repo":
            if content.strip() == "No matches.":
                status, count, code = "failed", 0, "no_matches"
            else:
                hits = [line for line in content.splitlines() if line.strip()]
                count = len(hits)
                for line in hits:
                    path = line.split(":", 1)[0]
                    if path not in paths:
                        paths.append(path)
        elif step["tool"] == "read_file":
            paths = [args.get("path")]
        elif step["tool"] == "read_issue":
            self.issue_text = content

        step["status"] = status
        self.results[step["id"]] = content[:RESULT_CHARS]
        self.step_results.append({"id": step["id"], "tool": step["tool"], "status": status,
                                  "count": count, "paths": paths, "error_code": code,
                                  "args": args})

    def fill(self, step: dict, args: dict):
        """One model call, offered this step's tool alone. Returns the filled args, or None."""
        self.n += 1
        response = self.ctx.client.create(
            system=self.ctx.prompt("executor.md"),
            messages=[{"role": "user", "content": self.fill_request(step, args)}],
            tools=[self.tool_schema(step["tool"])],
        )
        self.ctx.trace.model_call(self.n, response, purpose="execute")

        # Act on the tool calls whatever stop_reason says; refuse any that is not this step's tool.
        own = None
        for call in response.tool_calls:
            if call.name == step["tool"] and own is None:
                own = call
            elif call.name != step["tool"]:
                self.ctx.trace.event("off_plan", step=step["id"], tool=call.name, input=call.input)

        if own is None:
            self.ctx.trace.end("escalated", f"step {step['id']}: the model made no {step['tool']} call")
            return None

        filled = dict(own.input)
        for key, value in args.items():
            if value != FILL:
                filled[key] = value   # the plan's fixed values win
        return filled

    def fill_request(self, step: dict, args: dict) -> str:
        """What the fill-in call sees: the issue, and the results of the steps
        this one depends on (option B)."""
        fixed = {k: v for k, v in args.items() if v != FILL}
        blanks = [k for k, v in args.items() if v == FILL]
        parts = [
            f"Plan step {step['id']}: {step['action']}",
            f"Tool: {step['tool']}. Fixed arguments: {json.dumps(fixed)}. Fill in: {', '.join(blanks)}.",
            "The issue:\n" + (self.issue_text or "(not read)"),
        ]
        by_id = {s["id"]: s for s in self.plan["steps"]}
        for dep in step.get("depends_on") or []:
            if dep in self.results and by_id[dep]["tool"] != "read_issue":   # the issue is already above
                parts.append(f"Result of step {dep} ({by_id[dep]['tool']}):\n{self.results[dep]}")

        # A search step also sees earlier searches and their results, so it does not repeat one.
        if step["tool"] == "search_repo":
            for r in self.step_results:
                if r["tool"] == "search_repo" and r["id"] not in (step.get("depends_on") or []):
                    parts.append(f'Earlier search for "{r["args"].get("query")}" '
                                 f'(step {r["id"]}):\n{self.results[r["id"]]}')
        return "\n\n".join(parts)

    def rewrite(self, draft: str, reason: str) -> str:
        """One model call, offered no tool, rewrites a failing draft with the reason."""
        self.n += 1
        message = (f"The draft:\n{draft}\n\nWhy it failed: {reason}\n\n"
                   f"Evidence the run gathered:\n{json.dumps(self.evidence(), indent=2)}")
        response = self.ctx.client.create(system=self.ctx.prompt("rewrite.md"),
                                          messages=[{"role": "user", "content": message}],
                                          tools=[])
        self.ctx.trace.model_call(self.n, response, purpose="critique")
        return (response.text or "").strip() or draft

    def evidence(self) -> dict:
        """What the second pass sees: the issue, and what each step returned."""
        return {
            "issue": self.issue_text,
            "steps": [{k: r[k] for k in ("id", "tool", "status", "count", "paths")}
                      for r in self.step_results],
            "results": {str(i): text for i, text in self.results.items()},
        }
    
    
    def before_comment(self, step: dict, args: dict):
        """Hook: the second pass, before post_comment. Returns the args to post,
        or None when the draft is held (the run has escalated)."""
        mode = self.ctx.critique
        if mode == "off":
            return args                               # no second pass: no call, no critique line

        draft = args.get("body") or ""
        for round_no in range(1, MAX_ROUNDS + 1):
            # 1. Check the current draft.
            if mode == "external":
                result = verify(draft, self.ctx)
                passed = result["passed"]
                reason = "; ".join(result["reasons"]) or None
            else:
                self.n += 1
                verdict = self_critique(self.ctx.client, draft, self.evidence(),
                                        trace=self.ctx.trace, step=self.n)
                passed = verdict["decision"] == "accept"
                reason = verdict["reason"]

            # 2. A failing draft, with a round left, is rewritten with the reason (task 3).
            new_draft = draft
            if not passed and round_no < MAX_ROUNDS:
                new_draft = self.rewrite(draft, reason)

            # 3. Log the round.
            self.ctx.trace.event("critique", round=round_no, mode=mode,
                                 result="pass" if passed else "fail",
                                 reason=None if passed else reason,
                                 changed=new_draft != draft, draft=draft)

            # 4. A passing draft is posted; a failing one goes to the next round.
            if passed:
                return {**args, "body": draft}
            draft = new_draft

        # Still failing at the limit: hold it, post nothing, escalate.
        self.ctx.trace.end("escalated", f"the draft still failed after {MAX_ROUNDS} rounds")
        return None

    def tool_schema(self, name: str) -> dict:
        return next(t for t in self.ctx.tools.schemas if t["name"] == name)

    def after_step(self, step: dict, result) -> None:
        """Hook: runs after every step. Part G's notes way writes its progress file here."""
        pass

def run(ctx) -> None:
    PlannedRun(ctx).run()