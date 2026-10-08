"""The evaluation's paths and counts, the readers and validators of its files, and the hashes a result records.

Readers elsewhere read these names as `dataset.<NAME>` at call time, so a test can patch them.
"""

import hashlib
import json
import re
from collections import Counter
from pathlib import Path, PureWindowsPath

from loreos import parsing

ROOT = Path(__file__).resolve().parents[3]
EVAL_DIR = ROOT / "eval"
QUESTIONS = EVAL_DIR / "questions.jsonl"
CALIBRATION = EVAL_DIR / "judge_calibration.jsonl"
MANIFEST = EVAL_DIR / "corpus.json"
CORPUS_DIR = EVAL_DIR / "corpus"
RESULTS_DIR = EVAL_DIR / "results"
SCRATCH_DIR = ROOT / "docs" / "sdd" / "p2-evaluation" / "scratch"

CALIBRATION_ROWS = 30
MIN_QUESTIONS = 60
MAX_QUESTIONS = 100
UNANSWERABLE_RANGE = (10, 20)

QUESTION_KEYS = ("id", "question", "answerable", "sources", "note")
SOURCE_KEYS = ("file", "heading_path", "page")
CALIBRATION_KEYS = ("id", "question", "answer", "passages", "human")
PASSAGE_KEYS = ("n", "source", "text")
MANIFEST_SOURCE_KEYS = ("name", "home", "license", "attribution", "files")
GRADES = ("faithful", "unfaithful")
SHA256 = re.compile(r"[0-9a-f]{64}")
HTTP_URL = re.compile(r"https?://[^\s/]+\S*")


class DatasetError(ValueError):
    pass


def read_jsonl(path: Path) -> list[dict]:
    """One JSON object per line; blank lines are skipped."""
    rows = []
    # split on "\n" only: str.splitlines would also break a JSON string at a raw U+2028.
    for n, line in enumerate(_text(path).split("\n"), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            raise DatasetError(f"{path}:{n}: not valid JSON ({e.msg}); write one JSON object per line") from e
        if not isinstance(row, dict):
            raise DatasetError(f"{path}:{n}: expected a JSON object, got {type(row).__name__}; write one JSON object per line")
        rows.append(row)
    return rows


def read_manifest(path: Path) -> dict:
    try:
        manifest = json.loads(_text(path))
    except json.JSONDecodeError as e:
        raise DatasetError(f"{path}:{e.lineno}: not valid JSON ({e.msg}); fix the JSON") from e
    if not isinstance(manifest, dict):
        raise DatasetError(f"{path}: expected a JSON object {{sources, files}}; see the corpus manifest in the P2 spec")
    return manifest


def _text(path: Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as e:
        raise DatasetError(f"{path}: not UTF-8 text (byte {e.start}); save it as UTF-8") from e


def question_problems(rows: list[dict]) -> list[str]:
    """Every rule the evaluation set breaks, one line each, naming the row, the rule and the fix."""
    problems = []
    for i, row in enumerate(rows, 1):
        label = _label(row, i)
        problems += _unknown_keys(label, row, QUESTION_KEYS)
        problems += _text_fields(label, row, ("id", "question"))
        if "note" in row and not isinstance(row["note"], str):
            problems.append(f"{label}: note must be a string; quote it or remove it")
        answerable = row.get("answerable")
        if not isinstance(answerable, bool):
            problems.append(f"{label}: answerable must be true or false; set it")
        sources = row.get("sources")
        if not isinstance(sources, list):
            problems.append(f"{label}: sources must be a list; use [] for an unanswerable row")
            continue
        if answerable is True and not sources:
            problems.append(f"{label}: answerable rows label at least one source; add one from outline.txt or set answerable to false")
        if answerable is False and sources:
            problems.append(f"{label}: unanswerable rows have no sources; remove them or set answerable to true")
        for j, source in enumerate(sources, 1):
            problems += _source_problems(f"{label} source {j}", source)
    problems += _duplicate_ids(rows)
    unanswerable = sum(row.get("answerable") is False for row in rows)
    low, high = UNANSWERABLE_RANGE
    if not low <= unanswerable <= high:
        problems.append(f"the set has {unanswerable} unanswerable rows; keep between {low} and {high}")
    return problems


def _source_problems(label: str, source) -> list[str]:
    if not isinstance(source, dict):
        return [f"{label}: a source is an object {{file, heading_path}} or {{file, page}}; rewrite it as one"]
    file = source.get("file")
    if not _filled(file):
        return _unknown_keys(label, source, SOURCE_KEYS) + [f"{label}: file must be the path under eval/corpus/; set it"]
    label = f"{label} ({file})"
    problems = _unknown_keys(label, source, SOURCE_KEYS)
    try:
        kind = parsing.kind_of(file, b"")
    except parsing.UnsupportedType:
        kind = None
    if kind == "md":
        path = source.get("heading_path")
        if not (isinstance(path, list) and path and all(isinstance(h, str) and h for h in path)):
            problems.append(f"{label}: a Markdown source needs heading_path, a non-empty list of headings; copy it from outline.txt")
        if "page" in source:
            problems.append(f"{label}: a Markdown source has no page; remove it")
    elif kind == "pdf":
        page = source.get("page")
        if type(page) is not int or page < 1:  # type(), not isinstance: true is an int to isinstance
            problems.append(f"{label}: a PDF source needs page, the 1-based physical page number; set it")
        if "heading_path" in source:
            problems.append(f"{label}: a PDF source has no heading_path; remove it")
    else:
        what = "a .txt file has no headings or pages" if kind == "txt" else "the file type is not supported"
        problems.append(f"{label}: cannot be labeled, {what}; label a .md or .pdf file")
    return problems


def calibration_problems(rows: list[dict]) -> list[str]:
    """Every rule the judge calibration file breaks, one line each, naming the row, the rule and the fix."""
    problems = []
    if len(rows) != CALIBRATION_ROWS:
        problems.append(f"the calibration file has {len(rows)} rows; it needs exactly {CALIBRATION_ROWS}, as eval:calibration-draft writes")
    for i, row in enumerate(rows, 1):
        label = _label(row, i)
        problems += _unknown_keys(label, row, CALIBRATION_KEYS)
        problems += _text_fields(label, row, ("id", "question", "answer"))
        passages = row.get("passages")
        if not isinstance(passages, list) or not passages:
            problems.append(f"{label}: passages must be a non-empty list of the cited passages; copy them from the result file")
        else:
            for j, passage in enumerate(passages, 1):
                problems += _passage_problems(f"{label} passage {j}", passage)
        human = row.get("human")
        if human is None:
            problems.append(f'{label}: not graded yet; grade it, setting human to "faithful" or "unfaithful"')
        elif human not in GRADES:
            problems.append(f'{label}: human is {human!r}; set it to "faithful" or "unfaithful"')
    return problems + _duplicate_ids(rows)


def _passage_problems(label: str, passage) -> list[str]:
    if not isinstance(passage, dict):
        return [f"{label}: a passage is an object {{n, source, text}}; rewrite it as one"]
    problems = _unknown_keys(label, passage, PASSAGE_KEYS)
    n = passage.get("n")
    if type(n) is not int or n < 1:
        problems.append(f"{label}: n must be the passage's [n] number, an integer of at least 1; copy it from the answer")
    if not isinstance(passage.get("source"), str):
        problems.append(f"{label}: source must be a string; copy it from the result file")
    if not _filled(passage.get("text")):
        problems.append(f"{label}: text must be a non-empty string; copy it from the result file")
    return problems


def manifest_problems(manifest: dict) -> list[str]:
    """Every rule the corpus manifest breaks, one line each, naming the entry, the rule and the fix."""
    problems = []
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        problems.append("sources: must be a non-empty list of {name, home, license, attribution, files}; add each source")
        sources = []
    prefixes = []
    for i, source in enumerate(sources, 1):
        if not isinstance(source, dict):
            problems.append(f"sources[{i}]: must be an object {{name, home, license, attribution, files}}; rewrite it as one")
            continue
        for key in MANIFEST_SOURCE_KEYS:
            if not _filled(source.get(key)):
                problems.append(f"sources[{i}]: {key} must be a non-empty string; fill it in")
        if _filled(source.get("files")):
            prefixes.append(source["files"])
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        problems.append("files: must be a non-empty list of {file, url, sha256}; add each corpus file")
        files = []
    names = []
    for i, entry in enumerate(files, 1):
        if not isinstance(entry, dict):
            problems.append(f"files[{i}]: must be an object {{file, url, sha256}}; rewrite it as one")
            continue
        file = entry.get("file")
        label = file if _filled(file) else f"files[{i}]"
        if not _filled(file) or "\\" in file or file.startswith("/") or PureWindowsPath(file).drive or {"..", ".", ""} & set(file.split("/")):
            problems.append(f"{label}: file must be a relative path under eval/corpus/ with forward slashes and no '..'; fix it")
        else:
            names.append(file)
            covering = sum(file.startswith(prefix) for prefix in prefixes)
            if covering != 1:
                problems.append(f"{label}: falls under {covering} sources' files prefixes; make exactly one source cover it")
        if not isinstance(entry.get("url"), str) or not HTTP_URL.fullmatch(entry["url"]):
            problems.append(f"{label}: url must be an http or https URL; set it")
        if not isinstance(entry.get("sha256"), str) or not SHA256.fullmatch(entry["sha256"]):
            problems.append(f"{label}: sha256 must be 64 lowercase hex characters; set it to the file's sha256")
    problems += [f"{name}: listed {n} times; keep one entry" for name, n in Counter(names).items() if n > 1]
    return problems


def text_hash(path: Path) -> str:
    """sha256 of the file with CRLF read as LF, so a Windows checkout hashes as the committed file does."""
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def corpus_hash(manifest: dict) -> str:
    """sha256 over each file's `file\\tsha256` line, sorted by file, so manifest order does not matter."""
    lines = "".join(f"{f['file']}\t{f['sha256']}\n" for f in sorted(manifest["files"], key=lambda f: f["file"]))
    return hashlib.sha256(lines.encode()).hexdigest()


def _filled(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _label(row: dict, i: int) -> str:
    return row["id"] if _filled(row.get("id")) else f"row {i}"


def _text_fields(label: str, row: dict, keys: tuple[str, ...]) -> list[str]:
    return [f"{label}: {key} must be a non-empty string; fill it in" for key in keys if not _filled(row.get(key))]


def _unknown_keys(label: str, obj: dict, known: tuple[str, ...]) -> list[str]:
    return [f"{label}: unknown key {key!r}; the keys are {', '.join(known)}" for key in obj if key not in known]


def _duplicate_ids(rows: list[dict]) -> list[str]:
    counts = Counter(row["id"] for row in rows if _filled(row.get("id")))
    return [f"{id_}: the id is used by {n} rows; give each row its own id" for id_, n in counts.items() if n > 1]
