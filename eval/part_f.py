"""Assignment 2, Part F: the results table, built from runs/ and the tracker.

Writes `results` into reports/LAB_02.json (checks/FORMATS.md, section 10.10), leaving
every other section as it is, and prints the Part F table for reports/LAB_02.md.

    python -m eval.part_f
"""

from __future__ import annotations

import json
import math
from collections import defaultdict

import yaml

from agent.detectors import repeat_check
from eval.check_triage import check
from harness import ROOT
from harness.formats import normalize_path, parse_triage_comment
from harness.trace import read_trace
from harness.tracker import Tracker

CONFIGS = ("agent", "planned_off", "planned_self", "planned_external")
PLANNED = ("planned_off", "planned_self", "planned_external")
SECOND_PASS = ("planned_self", "planned_external")


def nearest_rank(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(pct / 100 * len(ordered)) - 1)]


def config_of(start: dict) -> str | None:
    if start.get("way") == "agent":
        return "agent"
    if start.get("way") == "planned":
        return f"planned_{start.get('critique') or 'off'}"
    return None                                    # notes runs and others are not Part F's


def _file(value) -> str | None:
    if value is None or str(value).strip().lower() == "none":
        return None
    return normalize_path(str(value))


def draft_passes(draft: str, answer: dict) -> bool:
    """Section 6's rule applied to a draft's text: its label and file match the answer."""
    label, path = parse_triage_comment(draft or "")
    return label == str(answer.get("label", "")).lower() and _file(path) == _file(answer.get("file"))


def prompt_tokens(call: dict) -> int:
    return (call.get("usage") or {}).get("prompt_tokens") or 0


def share(calls: list[dict], purposes: tuple) -> float:
    total = sum(prompt_tokens(c) for c in calls)
    part = sum(prompt_tokens(c) for c in calls if c.get("purpose") in purposes)
    return part / total if total else 0.0


def collect() -> dict:
    answers = {int(k): v for k, v in
               yaml.safe_load((ROOT / "fixtures/answers.yaml").read_text())["eval"].items()}
    tracker = Tracker(ROOT)

    posted = defaultdict(int)                      # run_id -> comments it posted
    comments = ROOT / "tracker" / "comments.jsonl"
    if comments.exists():
        for line in comments.read_text().splitlines():
            if line.strip():
                posted[json.loads(line)["run_id"]] += 1

    by_config = defaultdict(list)
    for path in sorted((ROOT / "runs").glob("*.jsonl")):
        if path.name.startswith("_"):
            continue
        records = read_trace(path)
        start = records[0]
        backend = start.get("backend") or ""
        if (start.get("type") != "run_start" or start.get("lab") != "02"
                or start.get("issue") not in answers
                or backend == "never-stops" or backend.startswith("harness.scripted")):
            continue
        config = config_of(start)
        run_end = next((r for r in records if r["type"] == "run_end"), None)
        end = next((r for r in records if r["type"] == "end"), {})
        if config is None or run_end is None or end.get("terminal_reason") in ("quota", "rate_limited"):
            continue                               # not a finished run (section 9)

        calls = [r for r in records if r["type"] == "model_call"]
        critiques = [r for r in records if r["type"] == "critique"]
        answer = answers[start["issue"]]
        by_config[config].append({
            "issue": start["issue"],
            "sweep": start.get("sweep"),
            "ok": check(tracker, start["run_id"], start["issue"], answer),
            "tokens": sum(prompt_tokens(c) + ((c.get("usage") or {}).get("output_tokens") or 0)
                          for c in calls),
            "latency": run_end["elapsed_s"],
            "n_calls": len(calls),
            "plan_share": share(calls, ("plan", "revise")),
            "plan_call_share": share(calls, ("plan",)),
            "critique_share": share(calls, ("critique",)),
            "repeat": bool(repeat_check(records)),
            "off_plan": sum(1 for r in records if r["type"] == "off_plan"),
            "revisions": sum(1 for r in records if r["type"] == "revision"),
            "rounds": len(critiques),
            "changed": any(r.get("changed") for r in critiques),
            "first_draft_ok": draft_passes(critiques[0].get("draft"), answer) if critiques else None,
            "held": bool(critiques) and critiques[-1].get("result") == "fail"
                    and posted[start["run_id"]] == 0,
        })
    return {"answers": answers, "by_config": by_config}


def summarize(runs: list[dict], config: str, answers: dict) -> dict:
    n = len(runs) or 1
    sweeps = defaultdict(int)
    for r in runs:
        sweeps[r["sweep"]] += r["ok"]
    planned, second = config in PLANNED, config in SECOND_PASS
    changed = [r for r in runs if r["changed"]]
    return {
        "runs": len(runs),
        "passes": sum(r["ok"] for r in runs),
        "per_issue": {str(i): sum(r["ok"] for r in runs if r["issue"] == i) for i in sorted(answers)},
        "sweep_min": min(sweeps.values()) if sweeps else None,
        "sweep_max": max(sweeps.values()) if sweeps else None,
        "mean_tokens": sum(r["tokens"] for r in runs) / n,
        "p50_latency_s": nearest_rank([r["latency"] for r in runs], 50),
        "max_latency_s": max((r["latency"] for r in runs), default=None),
        "plan_overhead_share": sum(r["plan_share"] for r in runs) / n if planned else None,
        "critique_overhead_share": sum(r["critique_share"] for r in runs) / n if second else None,
        "runs_with_repeat": sum(r["repeat"] for r in runs),
        "off_plan": sum(r["off_plan"] for r in runs) if planned else None,
        "revisions_mean": sum(r["revisions"] for r in runs) / n if planned else None,
        "revisions_max": max((r["revisions"] for r in runs), default=0) if planned else None,
        "rounds_mean": sum(r["rounds"] for r in runs) / n if second else None,
        "rounds_max": max((r["rounds"] for r in runs), default=0) if second else None,
        "drafts_changed": len(changed) if second else None,
        "drafts_fixed": sum(1 for r in changed if r["first_draft_ok"] is False and r["ok"]) if second else None,
        "drafts_broken": sum(1 for r in changed if r["first_draft_ok"] is True and not r["ok"]) if second else None,
        "drafts_held": sum(r["held"] for r in runs) if second else None,
    }


def table(results: dict, by_config: dict) -> str:
    def cell(config, text):
        return text if text is not None else ""

    def pct(x):
        return None if x is None else f"{100 * x:.1f}%"

    rows = [
        ("Passes, of 18", lambda c, r: str(r["passes"])),
        ("Per issue, 4201 to 4206, of 3 each", lambda c, r: " ".join(str(v) for v in r["per_issue"].values())),
        ("Spread: the lowest and highest sweep, of 6", lambda c, r: f"{r['sweep_min']} to {r['sweep_max']}"),
        ("Tokens per run (mean)", lambda c, r: f"{r['mean_tokens']:,.0f}"),
        ("Latency per run: median, and slowest", lambda c, r: f"{r['p50_latency_s']:.1f}s, {r['max_latency_s']:.1f}s"),
        ("Plan overhead: mean share of prompt tokens", lambda c, r: pct(r["plan_overhead_share"])),
        ("Second-pass overhead: mean share of prompt tokens", lambda c, r: pct(r["critique_overhead_share"])),
        ("Runs with at least one exact repeat", lambda c, r: str(r["runs_with_repeat"])),
        ("`off_plan` lines", lambda c, r: None if r["off_plan"] is None else str(r["off_plan"])),
        ("Revisions per run: mean, and maximum",
         lambda c, r: None if r["revisions_mean"] is None else f"{r['revisions_mean']:.2f}, {r['revisions_max']}"),
        ("Second-pass rounds per run: mean, and maximum",
         lambda c, r: None if r["rounds_mean"] is None else f"{r['rounds_mean']:.2f}, {r['rounds_max']}"),
        ("Drafts changed; of those fixed, and broken",
         lambda c, r: None if r["drafts_changed"] is None
         else f"{r['drafts_changed']}; {r['drafts_fixed']} fixed, {r['drafts_broken']} broken"),
        ("Drafts held at the bound", lambda c, r: None if r["drafts_held"] is None else str(r["drafts_held"])),
    ]
    out = ["| Measure | Agent | Planned, off | Planned, self | Planned, external |",
           "|---|---|---|---|---|"]
    for name, fn in rows:
        out.append(f"| {name} | " + " | ".join(cell(c, fn(c, results[c])) for c in CONFIGS) + " |")

    # The plan call's share, grouped by the run's number of model calls.
    out += ["", "Plan call's share of prompt tokens, by the run's number of model calls (planned runs):", "",
            "| Model calls | Runs | Plan call's mean share |", "|---|---|---|"]
    groups = defaultdict(list)
    for config in PLANNED:
        for r in by_config[config]:
            groups["4 to 6" if r["n_calls"] <= 6 else "7 to 9" if r["n_calls"] <= 9 else "10 or more"].append(r)
    for name in ("4 to 6", "7 to 9", "10 or more"):
        rs = groups.get(name, [])
        if rs:
            out.append(f"| {name} | {len(rs)} | {pct(sum(r['plan_call_share'] for r in rs) / len(rs))} |")
    return "\n".join(out)


def main() -> None:
    data = collect()
    results = {c: summarize(data["by_config"][c], c, data["answers"]) for c in CONFIGS}

    path = ROOT / "reports/LAB_02.json"
    report = json.loads(path.read_text())
    report["results"] = results                    # every other section is left as it is
    path.write_text(json.dumps(report, indent=2) + "\n")

    print(table(results, data["by_config"]))


if __name__ == "__main__":
    main()