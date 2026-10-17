"""Way 6, notes: the planned way with a progress file and a compaction. This file is yours.

Assignment 2, Part G. Your planned way with the second pass off, plus two things,
so that Part F's configurations stay as they were (checks/FORMATS.md, section 10):

    python run.py --way notes --notes off --issues 4203,4204,4206 --runs 2
    python run.py --way notes --notes on --issues 4203,4204,4206 --runs 2

  1. A progress file, ctx.progress_path (runs/<run_id>.progress.json): JSON outside
     the conversation, written after every step, holding at least
       "steps_done"  the ids of the steps that have run, in order
       "paths"       every path a search returned or a read read, in order
     and never a search term: terms come from the issue's text. Say in the file what
     it records (an "about" line, or labelled keys): a bare list of paths can be read
     as a to-do list. With ctx.notes == "on", every executor call and the questions'
     call after its first write show the model the file's text, exactly as written
     (not the planner, not the reviser). With "off", it is still written, and never
     shown.
  2. A history and a compaction: every model call sees the run's history so far,
     its step results oldest first. Once that history passes COMPACT_AT tokens, the
     oldest entries become a model-written summary and the recent ones stay as
     they were. Write ctx.trace.event("compaction", threshold=COMPACT_AT, tokens=...)
     each time. It runs whatever ctx.notes says. A low threshold is a test setting
     here, not advice.

Then, at the end of the run, however it ended (comment posted, escalated, halted),
one model call asks six closed questions, each "Has this run seen `<path>`: did a
search return it, or did you read it?", and returns six answers, yes or no: about
the three earliest paths the run saw (its tool_call lines returned them; all of
them, if it saw fewer), and paths it did not see for the rest. If the run has not
compacted yet, compact its history once first. Write each answer as
ctx.trace.event("question", path=..., answer=...), the six together.

Part G's 12 runs are the ones on issues 4203, 4204 and 4206; a notes run on a
development issue is development, and reports/LAB_02.json's context leaves it out.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from harness.formats import FILL
from harness.trace import read_trace
from ways.planned import PlannedRun

COMPACT_AT = 1500     # tokens (characters / 4); low enough that every run compacts: a test setting
KEEP_RECENT = 1       # history entries kept as they were at a compaction
ABOUT = ("A record of this run's progress: the steps it has already run, and the paths it has "
         "already seen (a search returned them, or a read read them). Not a list of things to do.")


def _tokens(text: str) -> int:
    return len(text) // 4


class _TraceGuard:
    """ctx.trace, except that end() first runs the run's closing hook, so a run that ends
    early (escalated, halted) still compacts and asks its questions. planned.py is unchanged."""

    def __init__(self, trace, before_end):
        self._trace, self._before_end = trace, before_end

    def end(self, reason, detail=None):
        self._before_end()
        return self._trace.end(reason, detail)

    def __getattr__(self, name):
        return getattr(self._trace, name)


class _CtxGuard:
    """ctx, with its trace wrapped by _TraceGuard."""

    def __init__(self, ctx, trace):
        self._ctx, self.trace = ctx, trace

    def __getattr__(self, name):
        return getattr(self._ctx, name)


class NotesRun(PlannedRun):
    """The planned way, second pass off, with a history, a progress file and a compaction."""

    def __init__(self, ctx):
        self.real_ctx = ctx
        super().__init__(_CtxGuard(ctx, _TraceGuard(ctx.trace, self._before_end)))
        self.history = []          # step results, oldest first (a summary replaces old ones)
        self.compacted = False
        self.asked = False
        self.notes_written = False

    # ---- the run ----

    def run(self) -> None:
        super().run()
        self.ask_questions()       # a run that ended without posting still asks (once)

    def before_comment(self, step: dict, args: dict):
        return args                # the second pass is off in this way

    def _before_end(self) -> None:
        self.ask_questions()       # just before the run ends, however it ends

    # ---- the history and the progress file ----

    def after_step(self, step: dict, result) -> None:
        r = self.step_results[-1]
        if step["tool"] != "read_issue":                    # the issue is shown on its own
            self.history.append(f"Step {step['id']}: {step['tool']} {json.dumps(r['args'])} "
                                f"({r['status']})\n{self.results.get(step['id'], '')}")
        self.write_progress()

    def write_progress(self) -> None:
        paths = []
        for r in self.step_results:
            for p in r["paths"] or []:
                if p and p not in paths:
                    paths.append(p)
        data = {"about": ABOUT,
                "steps_done": [r["id"] for r in self.step_results],
                "paths": paths}                              # never a search term
        Path(self.real_ctx.progress_path).write_text(json.dumps(data, indent=2) + "\n")
        self.notes_written = True

    def notes_text(self) -> str | None:
        """The progress file's text, exactly as written: only with --notes on, after its first write."""
        if self.real_ctx.notes != "on" or not self.notes_written:
            return None
        return Path(self.real_ctx.progress_path).read_text()

    def context_parts(self) -> list[str]:
        parts = []
        if self.history:
            parts.append("The run's history so far, oldest first:\n\n" + "\n\n".join(self.history))
        notes = self.notes_text()
        if notes:
            parts.append("The run's progress file:\n" + notes)
        return parts

    # ---- what each executor call sees ----

    def fill_request(self, step: dict, args: dict) -> str:
        self.maybe_compact()
        fixed = {k: v for k, v in args.items() if v != FILL}
        blanks = [k for k, v in args.items() if v == FILL]
        parts = [
            f"Plan step {step['id']}: {step['action']}",
            f"Tool: {step['tool']}. Fixed arguments: {json.dumps(fixed)}. Fill in: {', '.join(blanks)}.",
            "The issue:\n" + (self.issue_text or "(not read)"),
        ]
        return "\n\n".join(parts + self.context_parts())

    # ---- the compaction ----

    def maybe_compact(self, force: bool = False) -> None:
        size = _tokens("\n\n".join(self.history))
        if size <= COMPACT_AT and not force:
            return
        old, recent = self.history[:-KEEP_RECENT], self.history[-KEEP_RECENT:]
        if force and not old:
            old, recent = self.history, []
        if old:
            self.n += 1
            response = self.ctx.client.create(
                system="You summarize an agent's earlier step results for its own later use. Be brief.",
                messages=[{"role": "user", "content": "Summarize these earlier step results:\n\n"
                                                      + "\n\n".join(old)}],
                tools=[],
            )
            self.ctx.trace.model_call(self.n, response)    # purpose null: a compaction's summary
            summary = (response.text or "").strip()
            self.history = ([f"Summary of earlier steps:\n{summary}"] if summary else []) + recent
        self.ctx.trace.event("compaction", threshold=COMPACT_AT, tokens=size,
                             summarized=len(old), kept=len(recent))
        self.compacted = True

    # ---- the six questions ----

    def ask_questions(self) -> None:
        if self.asked:
            return
        self.asked = True
        if not self.compacted:
            self.maybe_compact(force=True)                 # every run asks after a compaction

        seen = []                                          # truth: the trace's own tool_call lines
        for line in read_trace(self.real_ctx.trace.path):
            if line.get("type") == "tool_call":
                for p in line.get("paths") or []:
                    if p not in seen:
                        seen.append(p)
        paths = seen[:3]
        repo = Path(self.real_ctx.root) / "fixtures" / "repo"
        unseen = [f.relative_to(repo).as_posix() for f in sorted(repo.rglob("*"))
                  if f.is_file() and not ({"config", "node_modules", ".git"} & set(f.relative_to(repo).parts))
                  and f.relative_to(repo).as_posix() not in seen]
        need = 6 - len(paths)
        stride = max(1, len(unseen) // max(1, need))
        paths += unseen[::stride][:need]                   # real files, spread across the repo
        paths = sorted(paths)                              # no order that gives the answer away

        questions = "\n".join(f"{i}. Has this run seen `{p}`: did a search return it, or did you read it?"
                              for i, p in enumerate(paths, 1))
        parts = ["Answer each question below with yes or no, one line each, as `1. yes` or `1. no`.",
                 questions] + self.context_parts()
        self.n += 1
        response = self.ctx.client.create(
            system="You answer questions about your own run, from what you have been shown.",
            messages=[{"role": "user", "content": "\n\n".join(parts)}],
            tools=[],
        )
        self.ctx.trace.model_call(self.n, response)        # purpose null: the questions' call
        answers = self._parse(response.text or "", len(paths))
        for p, a in zip(paths, answers):
            self.ctx.trace.event("question", path=p, answer=a)

    @staticmethod
    def _parse(text: str, n: int) -> list[str]:
        found = {}
        for line in text.splitlines():
            m = re.match(r"\s*(\d+)\D+?\b(yes|no)\b", line, re.IGNORECASE)
            if m:
                found[int(m.group(1))] = m.group(2).lower()
        if not found:                                       # a single bare yes or no
            single = re.search(r"\b(yes|no)\b", text, re.IGNORECASE)
            default = single.group(1).lower() if single else "no"
            return [default] * n
        return [found.get(i, "no") for i in range(1, n + 1)]


def run(ctx) -> None:
    NotesRun(ctx).run()