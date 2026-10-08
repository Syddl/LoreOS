"""`npm run eval:fetch`: download the evaluation corpus that eval/corpus.json pins, verifying each file by sha256.

Also owns the corpus check (`corpus_problems`), which fetch's skip and the evaluation preflight both use.
Free: it calls no OpenAI endpoint.
"""

import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from loreos.ingest import sha256

TIMEOUT_SECONDS = 60
FIX = "run npm run eval:fetch"


def corpus_problems(manifest: dict, corpus_dir: Path) -> list[str]:
    """One problem per manifest file whose raw bytes under corpus_dir are missing, outside it, or not the pinned sha256."""
    problems = []
    for item in manifest["files"]:
        file, target = item["file"], _target(corpus_dir, item["file"])
        if target is None:
            problems.append(f"{file}: refused, the path leaves {corpus_dir}; fix its file in eval/corpus.json")
        elif not target.is_file():
            problems.append(f"{file}: missing from {corpus_dir}; {FIX}")
        elif (got := sha256(target.read_bytes())) != item["sha256"]:
            problems.append(f"{file}: sha256 is {got}, expected {item['sha256']}; {FIX}")
    return problems


def fetch(manifest: dict, corpus_dir: Path) -> list[str]:
    """Download every file corpus_problems finds bad; one problem per file that could not be made good.

    A file lands at its path only after its hash matches, so a failure leaves nothing there.
    """
    problems = []
    for item in manifest["files"]:
        file, url, expected = item["file"], item["url"], item["sha256"]
        if not (found := corpus_problems({"files": [item]}, corpus_dir)):
            continue
        if (target := _target(corpus_dir, file)) is None:
            problems += found
            continue
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
                data = response.read()
        except urllib.error.HTTPError as e:
            problems.append(f"{file}: HTTP {e.code} from {url}; fix its url in eval/corpus.json")
            continue
        except OSError as e:  # URLError, and a timeout or reset during the read
            problems.append(f"{file}: {getattr(e, 'reason', e)} fetching {url}; check the network, then {FIX}")
            continue
        part = target.with_name(target.name + ".part")
        part.parent.mkdir(parents=True, exist_ok=True)
        part.write_bytes(data)
        if (got := sha256(data)) != expected:
            part.unlink()
            problems.append(f"{file}: downloaded sha256 {got}, expected {expected}, from {url}; pin a url that serves the expected bytes")
            continue
        os.replace(part, target)
        print(f"downloaded {file} ({len(data)} bytes)")
    return problems


def _target(corpus_dir: Path, file: str) -> Path | None:
    """Where a manifest file lives; None when its path would resolve outside corpus_dir."""
    root = corpus_dir.resolve()
    target = (root / file).resolve()
    return target if target.is_relative_to(root) else None


def main() -> int:
    from loreos.evaluation import dataset

    manifest = dataset.read_manifest(dataset.MANIFEST)
    corpus_dir = dataset.CORPUS_DIR
    total = len(manifest["files"])
    present = total - len(corpus_problems(manifest, corpus_dir))
    problems = fetch(manifest, corpus_dir)
    # Each file is exactly one of: already present, downloaded, or one problem.
    print(f"{corpus_dir}: downloaded {total - present - len(problems)}, already present {present}, problems {len(problems)}")
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    sys.exit(main())
