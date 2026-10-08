"""`npm run paid:eval -- [--mode vector] [--limit n] [--dry-run]`: the free preflight, then the paid run.

The guard asks before every form, the dry run included. Only `run.evaluate` spends, and it runs only after the
preflight has passed, with the commit the preflight recorded.
"""

import argparse
import asyncio
import json
import os
import sys

from loreos.evaluation import preflight, run

# npm reads a flag given before `--` as its own config, sets npm_config_<name> and drops it from the script's
# arguments, so `npm run paid:eval --limit=5` would start a full paid run. Each maps to its corrected form, and an
# abbreviation argparse would accept (--lim) counts too. ponytail: a misspelling (--limt) is still swallowed silently,
# and npm expands --l and --m into its own --long and --message: `--l N` exits 2 on the stray N, `--m X` runs the
# default mode. Refusing npm_config_message would refuse a user's .npmrc, so both stay.
NPM_SWALLOWED = {"limit": "npm run paid:eval -- --limit N", "mode": "npm run paid:eval -- --mode vector"}


def _swallowed() -> str | None:
    """The corrected form for a paid:eval flag npm took as its own config, if any."""
    for key in os.environ:
        if key.lower().startswith("npm_config_") and (typed := key[len("npm_config_") :].lower().replace("_", "-")):
            for name, form in NPM_SWALLOWED.items():
                if name.startswith(typed):
                    return f"npm took --{typed} as its own option and dropped it; put it after the separator: {form}"
    return None


def _limit(text: str) -> int:
    try:
        limit = int(text)
    except ValueError:
        limit = 0
    if limit < 1:
        raise argparse.ArgumentTypeError(f"{text!r} is not an integer of at least 1")
    return limit


def cli(argv: list[str]) -> int:
    """--help and --dry-run spend nothing; any argument argparse refuses exits 2 before the preflight."""
    if refusal := _swallowed():
        print(refusal, file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser(prog="npm run paid:eval --", description="Score retrieval and answers against eval/questions.jsonl.")
    parser.add_argument("--mode", choices=run.MODES, default="vector", help="the retrieval mode (default: vector)")
    parser.add_argument("--limit", type=_limit, metavar="N", help="run only the first N questions and skip the calibration pass; the result goes to scratch")
    parser.add_argument("--dry-run", action="store_true", help="run only the free preflight and print the plan; no paid call")
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:  # argparse exits 0 after --help and 2 on a bad argument
        return e.code
    # `npm run paid:eval --dry-run` (no `--`) passes no argument and sets npm_config_dry_run; honoured even with other
    # arguments, since a dry run is the safe reading.
    dry_run = args.dry_run or os.environ.get("npm_config_dry_run", "").lower() == "true"
    sha, notes = asyncio.run(preflight.preflight(args.limit))
    if dry_run:
        print("dry run: preflight only, no paid call made")
        return 0
    path = asyncio.run(run.evaluate(args.mode, args.limit, sha, notes))
    result = json.loads(path.read_text(encoding="utf-8"))
    print(f"\nresult: {path}\ndestination: {result['destination']}")
    for note in result["notes"]:
        print(f"note: {note}")
    for name, value in result["metrics"].items():
        print(f"{name}: {value}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    sys.exit(cli(sys.argv[1:]))
