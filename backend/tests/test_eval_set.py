"""The evaluation set, calibration and manifest validators, the readers and hashes, and the committed files."""

import hashlib

import pytest

from loreos.evaluation import dataset

HANDBOOK = "handbook/engineering/on-call.md"
CSF = "nist-csf-2.0.pdf"


def questions(unanswerable=10):
    """A valid set: `unanswerable` rows with no sources, then one Markdown-labeled and one PDF-labeled row."""
    rows = [
        {"id": f"u{i}", "question": f"Does the corpus cover topic {i}?", "answerable": False, "sources": []}
        for i in range(1, unanswerable + 1)
    ]
    rows.append({"id": "md", "question": "Who answers a page?", "answerable": True,
                 "sources": [{"file": HANDBOOK, "heading_path": ["On-call", "Escalation"]}]})
    rows.append({"id": "pdf", "question": "What are the CSF functions?", "answerable": True,
                 "sources": [{"file": CSF, "page": 7}], "note": "physical page, not the printed folio"})
    return rows


def md_source(rows):
    return rows[-2]["sources"][0]


def pdf_source(rows):
    return rows[-1]["sources"][0]


# One case per rule: (mutation of a valid set, the row its one problem names, a fragment of that problem).
QUESTION_RULES = {
    "missing-question": (lambda r: r[0].pop("question"), "u1", "question"),
    "empty-id": (lambda r: r[0].update(id=""), "row 1", "id"),
    "answerable-not-bool": (lambda r: r[-2].update(answerable="yes"), "md", "answerable"),
    "note-not-string": (lambda r: r[-1].update(note=3), "pdf", "note"),
    "unknown-key": (lambda r: r[0].update(heading=["On-call"]), "u1", "unknown key 'heading'"),
    "duplicate-id": (lambda r: r[1].update(id="u1"), "u1", "id"),
    "sourced-unanswerable": (lambda r: r[0].update(sources=[{"file": HANDBOOK, "heading_path": ["On-call"]}]), "u1",
                             "unanswerable rows have no sources"),
    "unsourced-answerable": (lambda r: r[-2].update(sources=[]), "md", "answerable rows label at least one source"),
    "sources-not-list": (lambda r: r[0].update(sources=None), "u1", "sources"),
    "source-not-object": (lambda r: r[-2].update(sources=[HANDBOOK]), "md source 1", "object"),
    "source-unknown-key": (lambda r: md_source(r).update(heading=["On-call"]), "md source 1", "unknown key 'heading'"),
    "source-missing-file": (lambda r: md_source(r).pop("file"), "md source 1", "file"),
    "md-without-heading-path": (lambda r: md_source(r).pop("heading_path"), "md source 1", "heading_path"),
    "md-empty-heading-path": (lambda r: md_source(r).update(heading_path=[]), "md source 1", "heading_path"),
    "md-heading-not-string": (lambda r: md_source(r).update(heading_path=["On-call", 3]), "md source 1", "heading_path"),
    "md-empty-heading": (lambda r: md_source(r).update(heading_path=["On-call", ""]), "md source 1", "heading_path"),
    "md-with-page": (lambda r: md_source(r).update(page=2), "md source 1", "no page"),
    "pdf-without-page": (lambda r: pdf_source(r).pop("page"), "pdf source 1", "page"),
    "pdf-page-zero": (lambda r: pdf_source(r).update(page=0), "pdf source 1", "page"),
    "pdf-page-bool": (lambda r: pdf_source(r).update(page=True), "pdf source 1", "page"),
    "pdf-page-string": (lambda r: pdf_source(r).update(page="7"), "pdf source 1", "page"),
    "pdf-with-heading-path": (lambda r: pdf_source(r).update(heading_path=["Govern"]), "pdf source 1", "no heading_path"),
    "txt-source": (lambda r: md_source(r).update(file="notes.txt"), "md source 1", "cannot be labeled"),
    "unsupported-source": (lambda r: md_source(r).update(file="slides.docx"), "md source 1", "cannot be labeled"),
}


def test_paths_and_counts():
    assert (dataset.ROOT / "backend" / "loreos" / "evaluation" / "dataset.py").is_file()
    assert dataset.EVAL_DIR == dataset.ROOT / "eval"
    assert (dataset.QUESTIONS, dataset.CALIBRATION, dataset.MANIFEST) == (
        dataset.EVAL_DIR / "questions.jsonl", dataset.EVAL_DIR / "judge_calibration.jsonl", dataset.EVAL_DIR / "corpus.json")
    assert (dataset.CORPUS_DIR, dataset.RESULTS_DIR) == (dataset.EVAL_DIR / "corpus", dataset.EVAL_DIR / "results")
    assert dataset.SCRATCH_DIR == dataset.ROOT / "docs" / "sdd" / "p2-evaluation" / "scratch"
    assert (dataset.CALIBRATION_ROWS, dataset.MIN_QUESTIONS, dataset.MAX_QUESTIONS) == (30, 60, 100)
    assert dataset.UNANSWERABLE_RANGE == (10, 20)


def test_valid_set_passes():
    assert dataset.question_problems(questions()) == []


@pytest.mark.parametrize("mutate, label, fragment", QUESTION_RULES.values(), ids=QUESTION_RULES.keys())
def test_question_rule(mutate, label, fragment):
    rows = questions()
    mutate(rows)
    problems = dataset.question_problems(rows)
    assert len(problems) == 1, problems
    assert problems[0].startswith(f"{label}: ") or problems[0].startswith(f"{label} ("), problems
    assert fragment in problems[0] and "; " in problems[0], "names the rule broken, then the fix"


@pytest.mark.parametrize("count, valid", [(9, False), (10, True), (20, True), (21, False)])
def test_unanswerable_count_range(count, valid):
    problems = dataset.question_problems(questions(unanswerable=count))
    if valid:
        assert problems == []
    else:
        assert len(problems) == 1 and f"{count} unanswerable" in problems[0], problems


def calibration(rows=None):
    """A valid calibration file: CALIBRATION_ROWS graded rows, each citing one passage under its original number."""
    return [
        {"id": f"c{i}", "question": f"Question {i}?", "answer": f"Answer {i} [2].",
         "passages": [{"n": 2, "source": f"{HANDBOOK} > On-call", "text": f"Passage {i}."}],
         "human": "faithful" if i % 2 else "unfaithful"}
        for i in range(1, (rows or dataset.CALIBRATION_ROWS) + 1)
    ]


def passage(rows):
    return rows[0]["passages"][0]


CALIBRATION_RULES = {
    "too-few-rows": (lambda r: r.pop(), "the calibration file", "29 rows"),
    "too-many-rows": (lambda r: r.append({**r[0], "id": "c31"}), "the calibration file", "31 rows"),
    "duplicate-id": (lambda r: r[1].update(id="c1"), "c1", "id"),
    "ungraded": (lambda r: r[0].update(human=None), "c1", "not graded yet"),
    "grade-missing": (lambda r: r[0].pop("human"), "c1", "not graded yet"),
    "bad-grade": (lambda r: r[0].update(human="yes"), "c1", "human"),
    "empty-answer": (lambda r: r[0].update(answer=""), "c1", "answer"),
    "missing-question": (lambda r: r[0].pop("question"), "c1", "question"),
    "unknown-key": (lambda r: r[0].update(judge="faithful"), "c1", "unknown key 'judge'"),
    "no-passages": (lambda r: r[0].update(passages=[]), "c1", "passages"),
    "passage-not-object": (lambda r: r[0].update(passages=["Passage."]), "c1 passage 1", "object"),
    "passage-n-zero": (lambda r: passage(r).update(n=0), "c1 passage 1", "n"),
    "passage-n-bool": (lambda r: passage(r).update(n=True), "c1 passage 1", "n"),
    "passage-source-not-string": (lambda r: passage(r).update(source=None), "c1 passage 1", "source"),
    "passage-empty-text": (lambda r: passage(r).update(text=""), "c1 passage 1", "text"),
    "passage-unknown-key": (lambda r: passage(r).update(score=0.5), "c1 passage 1", "unknown key 'score'"),
}


def test_valid_calibration_passes():
    assert dataset.calibration_problems(calibration()) == []


@pytest.mark.parametrize("mutate, label, fragment", CALIBRATION_RULES.values(), ids=CALIBRATION_RULES.keys())
def test_calibration_rule(mutate, label, fragment):
    rows = calibration()
    mutate(rows)
    problems = dataset.calibration_problems(rows)
    assert len(problems) == 1, problems
    assert problems[0].startswith(f"{label}: ") or problems[0].startswith(f"{label} "), problems
    assert fragment in problems[0] and "; " in problems[0], "names the rule broken, then the fix"


def manifest():
    """A valid manifest: one handbook file and one PDF, each under exactly one source prefix."""
    return {
        "sources": [
            {"name": "GitLab Handbook", "home": "https://handbook.gitlab.com", "license": "CC BY-SA 4.0",
             "attribution": "GitLab Inc. and contributors", "files": "handbook/"},
            {"name": "NIST Cybersecurity Framework 2.0", "home": "https://www.nist.gov/cyberframework",
             "license": "US government work", "attribution": "National Institute of Standards and Technology",
             "files": "nist-csf"},
        ],
        "files": [
            {"file": HANDBOOK, "url": f"https://gitlab.com/handbook/-/raw/{'0' * 40}/content/{HANDBOOK}", "sha256": "a" * 64},
            {"file": CSF, "url": f"https://web.archive.org/web/2024id_/https://nvlpubs.nist.gov/{CSF}", "sha256": "b" * 64},
        ],
    }


MANIFEST_RULES = {
    "dotdot-path": (lambda m: m["files"][0].update(file="handbook/../on-call.md"), "handbook/../on-call.md", "relative path"),
    "leading-slash": (lambda m: m["files"][0].update(file="/handbook/on-call.md"), "/handbook/on-call.md", "relative path"),
    "backslash": (lambda m: m["files"][0].update(file="handbook\\on-call.md"), "handbook\\on-call.md", "forward slashes"),
    "missing-file": (lambda m: m["files"][0].pop("file"), "files[1]", "file"),
    "ftp-url": (lambda m: m["files"][0].update(url="ftp://gitlab.com/on-call.md"), HANDBOOK, "url"),
    "missing-url": (lambda m: m["files"][0].pop("url"), HANDBOOK, "url"),
    "short-sha256": (lambda m: m["files"][0].update(sha256="a" * 63), HANDBOOK, "sha256"),
    "uppercase-sha256": (lambda m: m["files"][0].update(sha256="A" * 64), HANDBOOK, "sha256"),
    "duplicate-file": (lambda m: m["files"][1].update(file=HANDBOOK), HANDBOOK, "listed 2 times"),
    "uncovered-file": (lambda m: m["files"][1].update(file="osha-3885.pdf"), "osha-3885.pdf", "0 sources"),
    "covered-twice": (lambda m: m["sources"].append({**m["sources"][0], "files": "handbook/engineering/"}), HANDBOOK,
                      "2 sources"),
    "source-missing-license": (lambda m: m["sources"][0].pop("license"), "sources[1]", "license"),
    "source-empty-attribution": (lambda m: m["sources"][1].update(attribution=""), "sources[2]", "attribution"),
    "no-files": (lambda m: m.pop("files"), "files", "non-empty list"),
}


def test_valid_manifest_passes():
    assert dataset.manifest_problems(manifest()) == []


@pytest.mark.parametrize("mutate, label, fragment", MANIFEST_RULES.values(), ids=MANIFEST_RULES.keys())
def test_manifest_rule(mutate, label, fragment):
    m = manifest()
    mutate(m)
    problems = dataset.manifest_problems(m)
    assert len(problems) == 1, problems
    assert problems[0].startswith(f"{label}: "), problems
    assert fragment in problems[0] and "; " in problems[0], "names the rule broken, then the fix"


def test_read_jsonl_skips_blank_lines(tmp_path):
    path = tmp_path / "set.jsonl"
    path.write_bytes(b'{"id": "a"}\r\n\r\n   \n{"id": "b", "question": "caf\xc3\xa9\xe2\x80\xa8?"}\n')
    assert dataset.read_jsonl(path) == [{"id": "a"}, {"id": "b", "question": "café ?"}]


@pytest.mark.parametrize("bad, what", [("{not json", "not valid JSON"), ("[1, 2]", "JSON object")])
def test_read_jsonl_names_the_path_and_line(tmp_path, bad, what):
    path = tmp_path / "set.jsonl"
    path.write_text(f'{{"id": "a"}}\n\n{bad}\n', encoding="utf-8")
    with pytest.raises(dataset.DatasetError, match="; ") as e:
        dataset.read_jsonl(path)
    assert str(e.value).startswith(f"{path}:3: ") and what in str(e.value)


def test_read_manifest(tmp_path):
    path = tmp_path / "corpus.json"
    path.write_text('{"sources": [], "files": []}', encoding="utf-8")
    assert dataset.read_manifest(path) == {"sources": [], "files": []}
    path.write_text('{"sources": [],\n "files": [}', encoding="utf-8")
    with pytest.raises(dataset.DatasetError) as e:
        dataset.read_manifest(path)
    assert str(e.value).startswith(f"{path}:2: ")


def test_text_hash_reads_crlf_as_lf(tmp_path):
    lf, crlf = tmp_path / "lf.jsonl", tmp_path / "crlf.jsonl"
    lf.write_bytes(b'{"id": "a"}\n{"id": "b"}\n')
    crlf.write_bytes(b'{"id": "a"}\r\n{"id": "b"}\r\n')
    assert dataset.text_hash(lf) == dataset.text_hash(crlf) == hashlib.sha256(lf.read_bytes()).hexdigest()


def test_corpus_hash_is_over_sorted_file_lines():
    m = manifest()
    expected = hashlib.sha256(f"{HANDBOOK}\t{'a' * 64}\n{CSF}\t{'b' * 64}\n".encode()).hexdigest()
    assert dataset.corpus_hash(m) == expected
    m["files"].reverse()
    assert dataset.corpus_hash(m) == expected, "file order in the manifest does not change the hash"


def committed(path, writer):
    """The committed file at path, or a skip naming it and who writes it."""
    if not path.exists():
        pytest.skip(f"{path.relative_to(dataset.ROOT).as_posix()} is not committed yet; {writer}")
    return path


def test_committed_set_is_valid():
    path = committed(dataset.QUESTIONS, "the operator writes it by hand (brief decision 10)")
    assert dataset.question_problems(dataset.read_jsonl(path)) == []


def test_committed_calibration_is_valid():
    path = committed(dataset.CALIBRATION, "npm run eval:calibration-draft -- <result file> drafts it, then grade every row")
    assert dataset.calibration_problems(dataset.read_jsonl(path)) == []


def test_committed_manifest_is_valid():
    path = committed(dataset.MANIFEST, "task 3.3 writes it")
    assert dataset.manifest_problems(dataset.read_manifest(path)) == []
