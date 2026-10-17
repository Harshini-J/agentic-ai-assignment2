"""Assignment 2, Part G: scores the six questions of each notes run against its own trace.

Writes `context` into reports/LAB_02.json (checks/FORMATS.md, sections 10.6 and 10.10),
leaving every other section as it is, and prints the Part G table for reports/LAB_02.md.

    python -m eval.part_g
"""

from __future__ import annotations

import json

from harness import ROOT
from harness.trace import read_trace

PART_G_ISSUES = {4203, 4204, 4206}


def score(records: list[dict]) -> dict:
    """One run's context entry. A path's truth is 'yes' if a tool_call line above the
    question has it in its paths (a search returned it, or a read read it)."""
    start = records[0]
    seen, questions = set(), []
    first_question = compaction_before = None
    for i, line in enumerate(records):
        if line["type"] == "tool_call":
            seen.update(line.get("paths") or [])
        elif line["type"] == "compaction" and first_question is None:
            compaction_before = True
        elif line["type"] == "question":
            if first_question is None:
                first_question = i
            truth = "yes" if line["path"] in seen else "no"
            questions.append({"path": line["path"], "truth": truth, "answer": line["answer"]})
    return {
        "run_id": start["run_id"],
        "issue": start["issue"],
        "notes_shown": start.get("notes") == "on",
        "compacted": bool(compaction_before),
        "questions": questions,
        "right": sum(q["answer"] == q["truth"] for q in questions),
    }


def tokens(records: list[dict]) -> int:
    calls = [r for r in records if r["type"] == "model_call"]
    return sum(((c.get("usage") or {}).get("prompt_tokens") or 0)
               + ((c.get("usage") or {}).get("output_tokens") or 0) for c in calls)


def main() -> None:
    entries, cost = [], {True: [], False: []}
    for path in sorted((ROOT / "runs").glob("notes-*.jsonl")):
        records = read_trace(path)
        start = records[0]
        backend = start.get("backend") or ""
        finished = any(r["type"] == "run_end" for r in records)
        if (start.get("lab") != "02" or start.get("way") != "notes" or not finished
                or start.get("issue") not in PART_G_ISSUES
                or backend == "never-stops" or backend.startswith("harness.scripted")):
            continue                                       # Part G's 12 runs only
        entry = score(records)
        entries.append(entry)
        cost[entry["notes_shown"]].append(tokens(records))

    entries.sort(key=lambda e: (e["issue"], e["notes_shown"], e["run_id"]))

    report_path = ROOT / "reports/LAB_02.json"
    report = json.loads(report_path.read_text())
    report["context"] = entries                            # every other section is left as it is
    report_path.write_text(json.dumps(report, indent=2) + "\n")

    print("| Run | Issue | Progress file shown | Compacted before the questions | Answers right, of 6 |")
    print("|---|---|---|---|---|")
    for e in entries:
        print(f"| `{e['run_id']}` | {e['issue']} | {'yes' if e['notes_shown'] else 'no'} | "
              f"{'yes' if e['compacted'] else 'no'} | {e['right']} |")

    print()
    for shown in (False, True):
        group = [e for e in entries if e["notes_shown"] == shown]
        if group:
            right = sum(e["right"] for e in group)
            mean_tok = sum(cost[shown]) / len(cost[shown])
            print(f"notes {'on ' if shown else 'off'}: {len(group)} runs, {right} of {6 * len(group)} answers right, "
                  f"mean {mean_tok:,.0f} tokens per run")

    print("\nWrong answers:")
    for e in entries:
        for q in e["questions"]:
            if q["answer"] != q["truth"]:
                print(f"  {e['run_id']}  notes {'on ' if e['notes_shown'] else 'off'}  "
                      f"{q['path']}: truth {q['truth']}, answered {q['answer']}")


if __name__ == "__main__":
    main()