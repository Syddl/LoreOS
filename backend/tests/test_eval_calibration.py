"""eval:calibration-draft: 30 answered rows of a run, spread by id, ungraded, with no trace of the judge's verdict."""

import json

import pytest

from loreos.evaluation import calibration, dataset

RATIONALE = "The second claim is not in passage [3]."
REFUSAL = "I couldn't find this in your documents."


@pytest.fixture(autouse=True)
def target(tmp_path, monkeypatch):
    """The calibration file under tmp_path, the repo root elsewhere and no INIT_CWD, so no test touches eval/."""
    path = tmp_path / "judge_calibration.jsonl"
    monkeypatch.setattr(dataset, "CALIBRATION", path)
    monkeypatch.setattr(dataset, "ROOT", tmp_path / "root")
    monkeypatch.delenv("INIT_CWD", raising=False)
    return path


def citation(qid: str, n: int) -> dict:
    return {"n": n, "chunk_id": f"chunk-{qid}-{n}", "file": "handbook/values.md", "heading_path": ["Values", "Results"],
            "page": None, "source": "handbook/values.md > Values > Results", "text": f"Passage {n} for {qid}, café.",
            "relevant": [0]}


def row(qid: str, found: bool) -> dict:
    """One question row as run._row writes it; an answered row carries a judge grade and rationale."""
    if found:
        answer = {"found": True, "text": f"Answer to {qid} [1][3].", "reason": None, "citations": [citation(qid, 1), citation(qid, 3)]}
        judge = {"grade": "unfaithful", "rationale": RATIONALE, "error": None}
    else:
        answer = {"found": False, "text": REFUSAL, "reason": "model_not_found", "citations": []}
        judge = None
    return {"id": qid, "question": f"What does {qid} ask, café?", "answerable": True, "sources": [], "search_ms": 12.5,
            "hits": [], "answer": answer, "judge": judge}


def result(answered: int, refused: int = 0) -> dict:
    """A result whose refused rows sit between answered ones by id, listed in reverse id order so the draft must sort."""
    rows = [row(f"q{2 * i + 1:03}", True) for i in range(answered)]
    rows += [row(f"q{2 * i + 2:03}", False) for i in range(refused)]
    return {"schema": 1, "destination": "scratch", "questions": sorted(rows, key=lambda r: r["id"], reverse=True)}


def answered_ids(data: dict) -> list[str]:
    return sorted(r["id"] for r in data["questions"] if r["answer"]["found"])


def write(path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_40_answered_rows_give_30_spread_across_them():
    data = result(40, refused=10)
    eligible = answered_ids(data)
    ids = [r["id"] for r in calibration.draft(data)]
    assert len(ids) == dataset.CALIBRATION_ROWS == 30
    assert len(set(ids)) == 30 and ids == sorted(ids) and set(ids) <= set(eligible)
    assert ids[0] == eligible[0] and ids[-1] == eligible[-1]
    gaps = {eligible.index(b) - eligible.index(a) for a, b in zip(ids, ids[1:])}
    assert gaps == {1, 2}  # even: never a run of skipped rows


def test_refused_rows_are_never_picked():
    data = result(30, refused=20)
    assert [r["id"] for r in calibration.draft(data)] == answered_ids(data)


def test_a_row_is_the_answer_its_cited_passages_and_no_grade():
    picked = calibration.draft(result(30))[0]
    assert picked == {
        "id": "q001",
        "question": "What does q001 ask, café?",
        "answer": "Answer to q001 [1][3].",
        "passages": [
            {"n": 1, "source": "handbook/values.md > Values > Results", "text": "Passage 1 for q001, café."},
            {"n": 3, "source": "handbook/values.md > Values > Results", "text": "Passage 3 for q001, café."},
        ],
        "human": None,
    }
    assert list(picked) == list(dataset.CALIBRATION_KEYS)


def test_no_row_carries_the_judge_grade_or_rationale():
    for picked in calibration.draft(result(40, refused=5)):
        assert "judge" not in picked and picked["human"] is None
        text = json.dumps(picked)
        assert "unfaithful" not in text and RATIONALE not in text


def test_main_writes_jsonl_the_validator_accepts_once_graded(tmp_path, target, capsys):
    data = result(40, refused=5)
    assert calibration.main([str(write(tmp_path / "run1.json", data))]) == 0
    raw = target.read_bytes()
    assert b"\r" not in raw and raw.endswith(b"\n") and raw.count(b"\n") == 30
    assert "café".encode() in raw  # UTF-8, not a \u escape
    rows = dataset.read_jsonl(target)
    assert rows == calibration.draft(data)
    out = capsys.readouterr().out
    assert str(target) in out and '"faithful"' in out and '"unfaithful"' in out and "passages" in out
    for graded in rows:
        graded["human"] = "faithful"
    assert dataset.calibration_problems(rows) == []


def test_an_existing_calibration_file_is_never_overwritten(tmp_path, target, capsys):
    target.write_bytes(b'{"id": "q001", "human": "faithful"}\r\n')
    assert calibration.main([str(write(tmp_path / "run1.json", result(40)))]) == 1
    assert target.read_bytes() == b'{"id": "q001", "human": "faithful"}\r\n'
    assert str(target) in capsys.readouterr().err


def test_29_answered_rows_exit_1_and_write_nothing(tmp_path, target, capsys):
    assert calibration.main([str(write(tmp_path / "run1.json", result(29, refused=20)))]) == 1
    assert not target.exists()
    err = capsys.readouterr().err
    assert "29" in err and "run 1" in err


def test_a_missing_result_file_exits_1_naming_it(tmp_path, target, capsys):
    assert calibration.main([str(tmp_path / "missing.json")]) == 1
    assert not target.exists()
    assert "missing.json" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [[], ["a.json", "b.json"]], ids=["none", "two"])
def test_anything_but_one_argument_prints_usage_and_exits_2(argv, target, capsys):
    assert calibration.main(argv) == 2
    assert not target.exists()
    assert "usage" in capsys.readouterr().err


@pytest.mark.parametrize("init_cwd", [True, False], ids=["init-cwd", "repo-root"])
def test_a_relative_path_resolves_against_init_cwd_else_the_repo_root(init_cwd, tmp_path, target, monkeypatch):
    base = tmp_path / "operator-cwd" if init_cwd else dataset.ROOT
    if init_cwd:
        monkeypatch.setenv("INIT_CWD", str(base))
    write(base / "scratch" / "run1.json", result(30))
    monkeypatch.chdir(tmp_path)  # the process cwd holds no such file, so it is never what resolves the path
    assert calibration.main(["scratch/run1.json"]) == 0
    assert len(dataset.read_jsonl(target)) == 30
