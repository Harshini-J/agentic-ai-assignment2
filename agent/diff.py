"""Assignment 2, Part E: the diff of the plan against what ran. This file is yours.

"The one people skip" (Lecture 2, slide 54). The checker calls it on slide 51's run
in fixtures/traces/s49/, so keep this exact signature (checks/FORMATS.md, section
10.2):

    diff(plan, trace) -> {"steps": {step_id: label}, "extra": [step numbers]}

    steps   every plan step, labelled
              executed   it ran, in plan order
              skipped    it never ran
              reordered  it ran, out of plan order
    extra   the step numbers of tool_call lines that match no plan step

How a call matches a step is yours to decide: by its tool, and by any arguments
the plan fixes (an argument written "$fill" is fixed by nothing). Say how in your
report. Mind slide 51's run: it calls run_tests twice, and only one of those calls
can belong to each run_tests step.
"""

from __future__ import annotations

from agent.detectors import match_calls

def diff(plan: dict, trace: list[dict]) -> dict:
    """The plan against what ran: each plan step executed, skipped or reordered, and the
    tool calls that match no step as extra. Calls are matched to steps as in
    agent.detectors.match_calls: by plan_step when the line has one, otherwise by tool
    and by the arguments the plan fixes."""
    taken, extra = match_calls(plan, trace)
    position = {id(line): i for i, line in enumerate(trace)}   # where each call sits in the trace

    labels, last = {}, -1
    for step in plan.get("steps") or []:
        line = taken.get(step.get("id"))
        if line is None:
            labels[step.get("id")] = "skipped"
        elif position[id(line)] > last:
            labels[step.get("id")] = "executed"
            last = position[id(line)]
        else:
            labels[step.get("id")] = "reordered"   # ran before a step the plan puts earlier
    return {"steps": labels, "extra": extra}
