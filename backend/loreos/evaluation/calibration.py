"""`npm run eval:calibration-draft -- <result file>`: draft eval/judge_calibration.jsonl from a run's answers.

The draft holds no grade. The operator grades each row blind, from its passages alone, and the next run measures the
judge against those grades. Free: it reads a result file and calls no OpenAI endpoint.
Every `dataset.<NAME>` is read at call time, so a test can point the paths at a temporary directory.
"""

import json
import os
import sys
from pathlib import Path

from loreos.evaluation import dataset

USAGE = "usage: npm run eval:calibration-draft -- <result file>"


def draft(result: dict) -> list[dict]:
    """CALIBRATION_ROWS answered rows, spread evenly in id order, each `human: None` and without the judge's verdict."""
    eligible = sorted((row for row in result["questions"] if row["answer"]["found"]), key=lambda row: row["id"])
    wanted = dataset.CALIBRATION_ROWS
    if len(eligible) < wanted:
        raise ValueError(f"the result has {len(eligible)} answered rows and the draft needs {wanted}; "
                         "draft from a full run 1 (npm run paid:eval with no --limit)")
    # The first and last answered rows are both picked; with at least `wanted` rows the step is >= 1, so none twice.
    picked = [eligible[i * (len(eligible) - 1) // (wanted - 1)] for i in range(wanted)]
    return [
        dict(id=row["id"], question=row["question"], answer=row["answer"]["text"],
             passages=[dict(n=c["n"], source=c["source"], text=c["text"]) for c in row["answer"]["citations"]],
             human=None)
        for row in picked
    ]


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(USAGE, file=sys.stderr)
        return 2
    # npm sets INIT_CWD to where the operator ran it; `uv --directory backend` makes the process cwd backend/.
    path = Path(os.environ.get("INIT_CWD") or dataset.ROOT) / argv[0]
    target = dataset.CALIBRATION
    if target.exists():
        print(f"{target} already exists and may hold grades; move it aside yourself to draft again", file=sys.stderr)
        return 1
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"cannot read {path} ({e}); pass the result file of a full npm run paid:eval", file=sys.stderr)
        return 1
    try:
        rows = draft(result)
    except ValueError as e:
        print(f"{path}: {e}", file=sys.stderr)
        return 1
    with target.open("x", encoding="utf-8", newline="\n") as f:  # "x": never replace a file that appeared meanwhile
        f.writelines(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    print(f"wrote {len(rows)} ungraded rows to {target}")
    print('next: set each row\'s "human" to "faithful" or "unfaithful", judging only from its passages; then npm run paid:eval')
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    sys.exit(main(sys.argv[1:]))
