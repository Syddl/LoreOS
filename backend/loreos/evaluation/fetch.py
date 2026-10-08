"""`npm run eval:fetch`: download the evaluation corpus that eval/corpus.json pins, verifying each file by sha256,
then write eval/corpus/outline.txt, the headings and pages that labels are written from.

Also owns the corpus checks (`corpus_problems`, `corpus_outline`), which fetch and the evaluation preflight both use.
Free: it calls no OpenAI endpoint.
"""

import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from loreos import parsing
from loreos.evaluation import dataset, labels, run
from loreos.ingest import sha256

TIMEOUT_SECONDS = 60
FIX = "run npm run eval:fetch"


def corpus_problems(manifest: dict, corpus_dir: Path) -> list[str]:
    """One problem per manifest file whose raw bytes under corpus_dir are missing, outside it, or not the pinned sha256."""
    problems = []
    for item in manifest["files"]:
        file, target = item["file"], _target(corpus_dir, item["file"])
        if target is None:
            problems.append(f"{file}: refused, the path is not a file under {corpus_dir}; fix its file in eval/corpus.json")
        elif not target.is_file():
            problems.append(f"{file}: missing from {corpus_dir}; {FIX}")
        elif (got := sha256(target.read_bytes())) != item["sha256"]:
            problems.append(f"{file}: sha256 is {got}, expected {item['sha256']}; {FIX}")
    return problems


def corpus_outline(corpus: dict[str, bytes]) -> tuple[list[labels.OutlineEntry], list[str]]:
    """The outline of every file that parses, and one problem per file that does not, naming it."""
    entries, problems = [], []
    for file in sorted(corpus):
        try:
            entries += labels.outline({file: corpus[file]})
        except (parsing.ParseError, parsing.UnsupportedType) as e:
            problems.append(f"{file}: cannot be parsed ({e}); pin a file the parser reads in eval/corpus.json")
    return entries, problems


def fetch(manifest: dict, corpus_dir: Path) -> list[str]:
    """Download every file corpus_problems finds bad; one problem per file that could not be made good.

    A file lands at its path only after its hash matches, and a failure leaves nothing there: a present file
    with the wrong bytes is removed when its re-fetch fails, so the run never reads unverified bytes.
    """
    problems = []
    for item in manifest["files"]:
        if not (found := corpus_problems({"files": [item]}, corpus_dir)):
            continue
        if (target := _target(corpus_dir, item["file"])) is None:
            problems += found
        elif problem := _download(item, target):
            target.unlink(missing_ok=True)
            problems.append(problem)
    return problems


def _download(item: dict, target: Path) -> str | None:
    """Write the url's bytes to target once their sha256 matches; the problem when they could not be."""
    file, url, expected = item["file"], item["url"], item["sha256"]
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
            data = response.read()
    except urllib.error.HTTPError as e:
        return f"{file}: HTTP {e.code} from {url}; fix its url in eval/corpus.json"
    except OSError as e:  # URLError, and a timeout or reset during the read
        return f"{file}: {getattr(e, 'reason', e)} fetching {url}; check the network, then {FIX}"
    if (got := sha256(data)) != expected:
        return f"{file}: downloaded sha256 {got}, expected {expected}, from {url}; pin a url that serves the expected bytes"
    part = target.with_name(target.name + ".part")
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(data)
    os.replace(part, target)
    print(f"downloaded {file} ({len(data)} bytes)")
    return None


def _target(corpus_dir: Path, file: str) -> Path | None:
    """Where a manifest file lives; None when its path would resolve outside corpus_dir, or to corpus_dir itself."""
    root = corpus_dir.resolve()
    target = (root / file).resolve()
    return target if root in target.parents else None


def main() -> int:
    manifest = dataset.read_manifest(dataset.MANIFEST)
    corpus_dir = dataset.CORPUS_DIR
    total = len(manifest["files"])
    present = total - len(corpus_problems(manifest, corpus_dir))
    problems = fetch(manifest, corpus_dir)
    # Each file is exactly one of: already present, downloaded, or one problem.
    print(f"{corpus_dir}: downloaded {total - present - len(problems)}, already present {present}, problems {len(problems)}")
    if not problems:
        entries, problems = corpus_outline(run.load_corpus(manifest))
        if not problems:
            outline = corpus_dir / "outline.txt"
            outline.write_text(labels.render_outline(entries), encoding="utf-8", newline="\n")
            print(f"wrote {outline} ({len(entries)} sections)")
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    sys.exit(main())
