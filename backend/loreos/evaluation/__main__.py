"""`npm run paid:eval -- [--mode M|all] [--chunk-tokens N] [--chunk-overlap N] [--limit n] [--dry-run]`: the free
preflight, then the paid run, once per mode.

The guard asks before every form, the dry run included. Only `run.evaluate` spends, and it runs only after the
preflight has passed, with the commit the preflight recorded.
"""

import argparse
import asyncio
import json
import os
import sys

from loreos import chunking, settings
from loreos.evaluation import preflight, run

# npm reads a flag given before `--` as its own config, sets npm_config_<name> and drops it from the script's
# arguments, so `npm run paid:eval --limit=5` would start a full paid run. Each maps to its corrected form, and an
# abbreviation argparse would accept (--lim) counts too. ponytail: a misspelling (--limt) is still swallowed silently,
# and npm expands --l and --m into its own --long and --message: `--l N` exits 2 on the stray N, `--m X` runs the
# default mode. Refusing npm_config_message would refuse a user's .npmrc, so both stay.
CHUNK_FORM = "npm run paid:eval -- --chunk-tokens N --chunk-overlap N"
NPM_SWALLOWED = {
    "limit": "npm run paid:eval -- --limit N",
    "mode": "npm run paid:eval -- --mode vector",
    "chunk-tokens": CHUNK_FORM,
    "chunk-overlap": CHUNK_FORM,
}
MIN_CHUNK_TOKENS = 50
# text-embedding-3-small takes 8191 tokens per input, and ingest adds the heading path to each chunk: over this, ingest
# would pay for the earlier files' embeddings before the API refused one.
MAX_CHUNK_TOKENS = 8000


def _swallowed() -> str | None:
    """The corrected form for a paid:eval flag npm took as its own config, if any."""
    for key in os.environ:
        if key.lower().startswith("npm_config_") and (typed := key[len("npm_config_") :].lower().replace("_", "-")):
            for name, form in NPM_SWALLOWED.items():
                if name.startswith(typed):
                    return f"npm took --{typed} as its own option and dropped it; put it after the separator: {form}"
    return None


def _at_least(lowest: int, highest: int | None = None):
    def parse(text: str) -> int:
        try:
            value = int(text)
        except ValueError:
            value = lowest - 1
        if value < lowest or (highest is not None and value > highest):
            span = f"from {lowest} to {highest}" if highest is not None else f"of at least {lowest}"
            raise argparse.ArgumentTypeError(f"{text!r} is not an integer {span}")
        return value

    return parse


_limit = _at_least(1)


def cli(argv: list[str]) -> int:
    """--help and --dry-run spend nothing; any argument argparse refuses exits 2 before the preflight."""
    if refusal := _swallowed():
        print(refusal, file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser(prog="npm run paid:eval --", description="Score retrieval and answers against eval/questions.jsonl.")
    parser.add_argument("--mode", choices=(*run.MODES, "all"), default="vector",
                        help="the retrieval mode, or all to run each of them from one commit (default: vector)")
    parser.add_argument("--chunk-tokens", type=_at_least(MIN_CHUNK_TOKENS, MAX_CHUNK_TOKENS), metavar="N",
                        help=f"the chunker's token budget for this run (default: {chunking.CHUNK_TOKENS}, from chunking.py)")
    parser.add_argument("--chunk-overlap", type=_at_least(0), metavar="N",
                        help=f"the overlap between chunks for this run, under the budget (default: {chunking.CHUNK_OVERLAP})")
    parser.add_argument("--limit", type=_limit, metavar="N", help="run only the first N questions and skip the calibration pass; the result goes to scratch")
    parser.add_argument("--dry-run", action="store_true", help="run only the free preflight and print the plan; no paid call")
    try:
        args = parser.parse_args(argv)
        tokens = chunking.CHUNK_TOKENS if args.chunk_tokens is None else args.chunk_tokens
        overlap = chunking.CHUNK_OVERLAP if args.chunk_overlap is None else args.chunk_overlap
        if overlap >= tokens:
            parser.error(f"--chunk-overlap {overlap} must be under the token budget {tokens}")
    except SystemExit as e:  # argparse exits 0 after --help and 2 on a bad argument
        return e.code
    modes = run.MODES if args.mode == "all" else (args.mode,)
    try:
        rerank_on = settings.rerank_on()
    except RuntimeError as e:  # a RERANK value other than on or off
        print(f"paid:eval: {e}", file=sys.stderr)
        return 2
    if "hybrid_rerank" in modes and not rerank_on:
        print(f"paid:eval: RERANK=off, so --mode {args.mode} cannot run hybrid_rerank and its result would carry a mode it "
              "did not run; set RERANK=on, or run --mode vector or --mode hybrid", file=sys.stderr)
        return 2
    # Read when called by the chunker, the workspace key, the preflight's plan and the result's settings.
    chunking.CHUNK_TOKENS, chunking.CHUNK_OVERLAP = tokens, overlap
    # `npm run paid:eval --dry-run` (no `--`) passes no argument and sets npm_config_dry_run; honoured even with other
    # arguments, since a dry run is the safe reading.
    dry_run = args.dry_run or os.environ.get("npm_config_dry_run", "").lower() == "true"
    sha, notes = asyncio.run(preflight.preflight(args.limit, modes))
    if dry_run:
        print("dry run: preflight only, no paid call made")
        return 0
    for mode in modes:
        path = asyncio.run(run.evaluate(mode, args.limit, sha, notes))
        result = json.loads(path.read_text(encoding="utf-8"))
        print(f"\nmode: {mode}\nresult: {path}\ndestination: {result['destination']}")
        for note in result["notes"]:
            print(f"note: {note}")
        for name, value in result["metrics"].items():
            print(f"{name}: {value}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    sys.exit(cli(sys.argv[1:]))
