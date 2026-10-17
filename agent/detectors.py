"""Assignment 2, Part E: three detectors, and Lecture 2's ladder. This file is yours.

Three of the four plan failures have a detector of a few lines over a trace
(Lecture 2, slides 45 to 49); the validator is the fourth. The checker calls these
on fixtures/traces/, so keep these exact signatures (checks/FORMATS.md, section
10.2):

    repeat_check(trace) -> list[list]
        Circular reasoning. Exact repeats: two tool_call lines with the same tool
        and the same arguments. Returns each group of repeats as the step numbers
        of its tool_call lines, e.g. [[1, 3], [2, 4]].

    orphan_check(plan) -> list
        Hallucinated steps. The ids of steps, other than the last, whose result no
        later step uses: no later step lists them in depends_on.

    expected_result_check(plan, trace) -> list
        Premature stopping, in part. The ids of plan steps that did not run and
        return their result. It catches skipped steps, not a plan too short.

    ladder(plan, trace) -> {"q1": {"fired": bool, "ids": [...]}, "q2": ..., "q3": ...}
        Lecture 2's questions 1 to 3 (slide 50), in order: did any two steps do
        the same thing; is any step's result never used; did every planned step
        execute. "ids" says what fired: groups of step numbers for q1, step ids
        (or, from a trace, step numbers) for q2 and q3. Question 4 needs
        judgment, so it goes in your report, not here.

    plan    a plan (section 10.1)
    trace   a list of trace lines, as harness.trace.read_trace returns them

A plan with no depends_on cannot answer question 2 from the plan. Answer it from
the trace, and say how in your report.
"""

from __future__ import annotations
import json

FILL = "$fill"

def _step_args(step: dict) -> dict:
    """A step's arguments, written as `args` (an object) or `args_json` (a string)."""
    if isinstance(step.get("args"), dict):
        return step["args"]
    try:
        args = json.loads(step.get("args_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return args if isinstance(args, dict) else {}


def _matches(step: dict, line: dict) -> bool:
    """A call matches a step by plan_step when the line has one, otherwise by its tool
    and by every argument the plan fixes (anything that is not $fill)."""

    # Case 1: the call has a plan_step label (your own runs): just read it.
    if line.get("plan_step") is not None:
        return line["plan_step"] == step.get("id")
    
    # Case 2: no label (the fixture runs): match by tool and fixed arguments.
    if not step.get("tool") or line.get("name") != step["tool"]:
        return False
    given = line.get("input") or {}
    return all(given.get(k) == v for k, v in _step_args(step).items() if v != FILL)


def match_calls(plan: dict, trace: list[dict]):
    """Each tool_call, in order, goes to the first plan step it matches that no earlier
    call has taken. Returns ({step id: tool_call line}, [step numbers of extra calls])."""
    taken, extra = {}, []
    for line in trace:
        if line.get("type") != "tool_call":
            continue
        step = next((s for s in plan.get("steps") or []
                     if s.get("id") not in taken and _matches(s, line)), None)
        if step is None:
            extra.append(line.get("step"))
        else:
            taken[step["id"]] = line
    return taken, extra

def _call_key(line: dict) -> tuple:
    """A tool call's identity: its tool and its arguments, compared as sorted JSON."""
    return line.get("name"), json.dumps(line.get("input"), sort_keys=True)

def repeat_check(trace: list[dict]) -> list[list]:
    """Circular reasoning: groups of tool_call step numbers with the same tool and input."""
    groups = {}
    for line in trace:
        if line.get("type") == "tool_call":
            groups.setdefault(_call_key(line), []).append(line.get("step"))
    return [steps for steps in groups.values() if len(steps) > 1]

def orphan_check(plan: dict) -> list:
    """Hallucinated steps: ids of steps, other than the last, that no later step uses."""
    steps = plan.get("steps") or []
    orphans = []
    for i, step in enumerate(steps[:-1]):
        used = any(step.get("id") in (later.get("depends_on") or []) for later in steps[i + 1:])
        if not used:
            orphans.append(step.get("id"))
    return orphans

def expected_result_check(plan: dict, trace: list[dict]) -> list:
    """Premature stopping, in part: ids of plan steps that never ran, or whose call errored."""
    taken, _ = match_calls(plan, trace)
    return [s.get("id") for s in plan.get("steps") or []
            if s.get("id") not in taken or taken[s["id"]].get("is_error")]

def _unused_from_trace(trace: list[dict]) -> list:
    """A plan with no depends_on cannot answer question 2 from the plan. Answer it from
    the trace, as a judgment: a call's result was never used if it is a later copy of an
    identical earlier call, or the run's last tool call with no model call after it."""
    unused = [step for group in repeat_check(trace) for step in group[1:]]
    calls = [i for i, line in enumerate(trace) if line.get("type") == "tool_call"]
    if calls:
        last = calls[-1]
        if not any(line.get("type") == "model_call" for line in trace[last + 1:]):
            unused.append(trace[last].get("step"))
    return sorted(set(unused))


def ladder(plan: dict, trace: list[dict]) -> dict:
    """Lecture 2's questions 1 to 3. Question 4 needs judgment: it is in the report."""
    q1 = repeat_check(trace)
    has_deps = any("depends_on" in s for s in plan.get("steps") or [])
    q2 = orphan_check(plan) if has_deps else _unused_from_trace(trace)
    q3 = expected_result_check(plan, trace)
    return {q: {"fired": bool(ids), "ids": ids} for q, ids in (("q1", q1), ("q2", q2), ("q3", q3))}


if __name__ == "__main__":
    from pathlib import Path

    from harness.trace import read_trace

    root = Path(__file__).resolve().parent.parent / "fixtures" / "traces"
    for run in ("looping", "s49"):
        plan = json.loads((root / run / "plan.json").read_text())
        trace = read_trace(root / run / "trace.jsonl")
        print(run, json.dumps(ladder(plan, trace)))