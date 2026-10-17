"""Assignment 2, Part D: the second pass before posting. This file is yours.

Two ways to read a drafted comment before it is posted (Lecture 2, slides 31 to 34).
The checker runs your planned way in each mode against scripted models, so keep
these exact signatures (checks/FORMATS.md, section 10.2). You may add keyword
arguments with defaults; the checker passes only these.

    verify(draft, ctx) -> {"passed": bool, "reasons": [str, ...]}

        The external mode: checks in code, against the repository and this run's
        own record. Four checks:
          1. the draft parses: a `label:` line with a known label, and a `file:`
             line with a path or none (section 1; harness.formats.parse_triage_comment);
          2. a path it names exists in the repository (ctx.root / "fixtures" / "repo");
          3. this run saw that path: a search_repo result or a read_file call in this
             run's trace returned it. Each tool_call line's `paths` field lists the
             files it returned; read the trace so far with
             harness.trace.read_trace(ctx.trace.path);
          4. the label and the file agree: a question names none, and every other
             label names a file.
        "reasons" says why each failed check failed; it is empty when all pass.
        verify reads only what the run itself can see: never the answer key, and
        never Assignment 1's grounded check in eval/. The checker flags a second
        pass that does.

    self_critique(client, draft, evidence, trace=None) -> {"decision": "accept" | "revise", "reason": str | None}

        The self mode: one model call that rereads the draft, given the issue and
        what the run's steps returned (`evidence`, a dict of your design), and
        accepts it or asks for a revision with a reason. Given a trace, trace the
        call: trace.model_call(n, response, purpose="critique").

    draft   the comment your executor drafted, the text post_comment would post
    ctx     the run's harness.runner.WayContext
    client  harness.client.ModelClient

The loop that uses them, its rewrite call and MAX_ROUNDS live in ways/planned.py.
Keep your prompts in prompts/.
"""

from __future__ import annotations

import re
import json
from pathlib import Path

from harness.formats import parse_triage_comment
from harness.trace import read_trace

LABELS = ("bug", "feature", "question", "docs")
_FILE_LINE = re.compile(r"(?im)^\s*file\s*:\s*\S")   # a file: line with something after it

ROOT = Path(__file__).resolve().parent.parent
CRITIQUE_PROMPT = "prompts/self_critique.md"
VERDICT_TOOL = {
    "name": "submit_verdict",
    "description": "Give your verdict on the draft. Call this exactly once.",
    "input_schema": {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "enum": ["accept", "revise"]},
            "reason": {"type": "string", "description": "What is wrong, for revise; empty for accept."},
        },
        "required": ["decision", "reason"],
        "additionalProperties": False,
    },
}

def verify(draft: str, ctx) -> dict:
    """The external second pass: four checks in code, against the repository and
    this run's own trace. Never the answer key, never eval/."""

    reasons = []
    label, path = parse_triage_comment(draft)
    if path is not None and path.lower() == "none":
        path = None                                   # "file: none"

    # 1. It parses: a known label, and a file: line (a path or none).
    if label not in LABELS or not _FILE_LINE.search(draft or ""):
        return {"passed": False,
                "reasons": ["parses: needs 'label:' (bug, feature, question or docs) "
                            "and 'file:' (a path, or none)"]}

    if path is not None:
        # 2. The path exists in the repository.
        repo = (ctx.root / "fixtures" / "repo").resolve()
        target = (repo / path).resolve()
        if repo not in target.parents or not target.is_file():
            reasons.append(f"exists: {path} is not a file in the repository")

        # 3. This run saw the path: some tool_call line lists it in its paths.
        seen = {p for line in read_trace(ctx.trace.path) if line.get("type") == "tool_call"
                for p in (line.get("paths") or [])}
        if path not in seen:
            reasons.append(f"seen: this run never saw {path}: no search returned it and no read read it")

    # 4. The label and the file agree.
    if label == "question" and path is not None:
        reasons.append("agree: a question names file: none")
    elif label != "question" and path is None:
        reasons.append(f"agree: a {label} names a file, not none")

    return {"passed": not reasons, "reasons": reasons}

def self_critique(client, draft: str, evidence: dict, trace=None, step = 0) -> dict:
    """The self second pass: one model call rereads the draft, given the issue and
    what the run found, and accepts it or asks for a revision. An opinion, not a check."""
    system = (ROOT / CRITIQUE_PROMPT).read_text()
    message = ("Evidence the run gathered:\n" + json.dumps(evidence, indent=2)
               + "\n\nThe draft comment:\n" + draft
               + "\n\nGive your verdict by calling submit_verdict.")

    response = client.create(system=system,
                             messages=[{"role": "user", "content": message}],
                             tools=[VERDICT_TOOL])

    if trace is not None:
        trace.model_call(step, response, purpose="critique")

    for call in response.tool_calls:
        if call.name == "submit_verdict":
            if call.input.get("decision") == "revise":
                reason = (call.input.get("reason") or "").strip()
                return {"decision": "revise", "reason": reason or "the critic asked for a revision"}
            return {"decision": "accept", "reason": None}

    return {"decision": "accept", "reason": None}