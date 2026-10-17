"""Assignment 2, Parts A and C: the planner and the reviser. This file is yours.

The contract (checks/FORMATS.md, section 10). The checker calls both functions
directly, with a scripted model that keeps a copy of every request, so keep these
exact signatures. You may add keyword arguments with defaults; the checker passes
only these.

    make_plan(client, issue_number, tool_schemas, trace=None) -> dict
    revise_plan(client, plan, step_results, trace=None) -> dict

    client        harness.client.ModelClient: client.create(system=, messages=, tools=)
    issue_number  the issue to triage, an int
    tool_schemas  the tool definitions, as ctx.tools.schemas gives them
    plan          the active plan, its steps' statuses brought up to date
    step_results  one entry per step that has run (section 10.3)
    trace         a harness.trace.TraceWriter, or None. When you get one, trace your
                  model call: trace.model_call(0, response, purpose="plan") in
                  make_plan, purpose="revise" in revise_plan
    returns       a plan (section 10.1): {"meta": {...}, "steps": [...]}

make_plan writes the plan and stops (Lecture 2, slide 15). Its request carries the
task, the issue number and the tool list, and nothing from the issue: not its body,
not its title. The checker looks for each issue's sentinel string in every request.
The usual way to get the plan back as data: offer the model one tool whose
input_schema is agent/plan_schema.json, and read the plan from its call. Mark an
argument that waits on an earlier step's result "$fill"; the executor fills it in.

revise_plan repairs before it replaces: it never changes a step whose status is
done; it may change a step that failed, to retry it, and any step not yet run. A
step whose step result says "done" comes back unchanged, every field but status,
whatever the model wrote. Its request carries structured step results only (status, counts, paths,
error codes): never the issue's text, and never a step result's `args`, which the
executor may have filled in from the issue.

Keep your prompts in prompts/.
"""

from __future__ import annotations
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "agent" / "plan_schema.json"
PLANNER_PROMPT = "prompts/planner.md"

REVISER_PROMPT = "prompts/reviser.md"
SAFE_FIELDS = ("id", "tool", "status", "count", "paths", "error_code")   # never "args"

def _plan_tool() -> dict:
    """The one tool the planner is offered: its input is the plan itself."""
    return {
        "name": "submit_plan",
        "description": "Submit the triage plan. Call this exactly once.",
        "input_schema": json.loads(SCHEMA_PATH.read_text()),
        "strict": True,
    }


def make_plan(client, issue_number: int, tool_schemas: list[dict], trace=None, feedback=None) -> dict:
    system = (ROOT / PLANNER_PROMPT).read_text()

    #  The request: issue NUMBER and tool list only, never the issue text
    tools_text = json.dumps(
        [{"name": t["name"], "description": t.get("description", ""),
          "input_schema": t.get("input_schema", {})} for t in tool_schemas],
        indent=2,
    )
    message = (f"Write the plan to triage issue #{issue_number}.\n\n"
               f"Tools the plan may use:\n{tools_text}\n\n"
               "Write the plan by calling submit_plan.")

    if feedback:
        message += f"\n\nYour previous plan was rejected. {feedback} Write a corrected plan."

    response = client.create(system=system,
                             messages=[{"role": "user", "content": message}],
                             tools=[_plan_tool()])
    if trace is not None:
        trace.model_call(0, response, purpose="plan")

    plan = {"steps": []}   # default if the model never calls submit_plan
    for call in response.tool_calls:
        if call.name == "submit_plan":
            plan = dict(call.input)  # kept as returned, so the schema check sees it all
            break

    plan["meta"] = {
        "model": response.model,
        "prompt": PLANNER_PROMPT,
        "tools": [t["name"] for t in tool_schemas],
    }
    return plan


def revise_plan(client, plan: dict, step_results: list[dict], trace=None) -> dict:
    system = (ROOT / REVISER_PROMPT).read_text()

    # Structured results only: never a step result's args, which may carry issue text.
    results = [{k: r.get(k) for k in SAFE_FIELDS} for r in step_results]
    message = ("The active plan:\n" + json.dumps({"steps": plan["steps"]}, indent=2)
               + "\n\nResults of the steps that ran:\n" + json.dumps(results, indent=2)
               + "\n\nWrite the revised plan by calling submit_plan.")

    response = client.create(system=system,
                             messages=[{"role": "user", "content": message}],
                             tools=[_plan_tool()])
    if trace is not None:
        trace.model_call(0, response, purpose="revise")

    revised = {"steps": []}   # prose answer -> an empty revision, which the validator rejects
    for call in response.tool_calls:
        if call.name == "submit_plan":
            revised = dict(call.input)
            break

    # Repair before replace: a done step comes back unchanged, in its original place.
    done = {r["id"] for r in step_results if r.get("status") == "done"}
    done |= {s["id"] for s in plan["steps"] if s.get("status") == "done"}
    steps = [s for s in revised.get("steps") or [] if isinstance(s, dict) and s.get("id") not in done]
    for i, s in enumerate(plan["steps"]):
        if s["id"] in done:
            steps.insert(min(i, len(steps)), copy.deepcopy(s))
    revised["steps"] = steps

    revised["meta"] = {**(plan.get("meta") or {}), "model": response.model, "prompt": REVISER_PROMPT}
    return revised
