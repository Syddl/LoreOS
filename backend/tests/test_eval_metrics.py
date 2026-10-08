import pytest

from loreos.evaluation.metrics import percentile, summarize


def row(qid, sources, relevant_hits, cited, grade, search_ms):
    """A result row with ten hits.

    sources: the labeled source count, 0 for an unanswerable question.
    relevant_hits: rank -> the source indices that hit matches; the other ranks match none.
    cited: the cited ranks, each citation copying its hit's relevance, or None for a refusal.
    grade: "faithful", "unfaithful", or "error" for a verdict failure; a refusal has no judge.
    """
    hits = [
        {
            "rank": rank,
            "chunk_id": f"{qid}-{rank}",
            "file": "handbook.md",
            "heading_path": ["Section"],
            "page": None,
            "score": 1 - rank / 100,
            "relevant": relevant_hits.get(rank, []),
        }
        for rank in range(1, 11)
    ]
    citations = [
        {
            "n": n,
            "chunk_id": hits[n - 1]["chunk_id"],
            "file": "handbook.md",
            "heading_path": ["Section"],
            "page": None,
            "source": "handbook.md > Section",
            "text": f"passage {n}",
            "relevant": hits[n - 1]["relevant"],
        }
        for n in cited or []
    ]
    found = cited is not None
    if not found:
        judge = None
    elif grade == "error":
        judge = {"grade": None, "rationale": None, "error": "VerdictError: refusal"}
    else:
        judge = {"grade": grade, "rationale": "One sentence.", "error": None}
    return {
        "id": qid,
        "question": f"Question {qid}?",
        "answerable": sources > 0,
        "sources": [{"file": "handbook.md", "heading_path": [f"Section {i}"]} for i in range(sources)],
        "search_ms": search_ms,
        "hits": hits,
        "answer": {
            "found": found,
            "text": "An answer [1]." if found else "I couldn't find this in your documents.",
            "reason": None if found else "model_not_found",
            "citations": citations,
        },
        "judge": judge,
    }


ROWS = [
    #   id    sources  relevant hits by rank                cited      judge         search_ms
    row("q1", 3, {1: [0], 3: [0], 5: [1], 6: [2]}, [1, 2, 3], "faithful", 120),
    row("q2", 1, {4: [0], 8: [0]}, [1], "unfaithful", 80),
    row("q3", 2, {10: [0, 1]}, None, None, 200),
    row("q4", 2, {2: [0, 1]}, [2], "error", 40),
    row("q5", 0, {}, None, None, 60),
    row("q6", 0, {}, [1], "faithful", 100),
    row("q7", 1, {}, [1, 2], "faithful", 150),
]
# Answerable: q1 q2 q3 q4 q7 (5). Unanswerable: q5 q6 (2). Refused: q3 q5.
#
# recall@5, labeled sources matched by ranks 1-5 / labeled sources:
#   q1 {0, 1} / 3 = 2/3 (source 0 twice counts once; source 2 only at rank 6)
#   q2 {0} / 1 = 1;  q3 {} / 2 = 0 (rank 10 only);  q4 {0, 1} / 2 = 1;  q7 {} / 1 = 0
#   mean (2/3 + 1 + 0 + 1 + 0) / 5 = (8/3) / 5 = 8/15
# MRR@10, 1 / rank of the first relevant hit in ranks 1-10, else 0:
#   q1 1/1;  q2 1/4 (not 1/8);  q3 1/10;  q4 1/2;  q7 0
#   mean (1 + 0.25 + 0.1 + 0.5 + 0) / 5 = 1.85 / 5 = 0.37
# citation accuracy, answerable and answered (q1 q2 q4 q7), pooled:
#   relevant citations: q1 2 of 3 (ranks 1 and 3), q2 0 of 1, q4 1 of 1, q7 0 of 2
#   (2 + 0 + 1 + 0) / (3 + 1 + 1 + 2) = 3/7
#   A per-question mean would give (2/3 + 0 + 1 + 0) / 4 = 5/12. q6's citation is irrelevant
#   but q6 is unanswerable, so it stays out; counting it would give 3/8.
# unanswerable refused: q5 of q5 q6 = 1/2
# answerable refused: q3 of 5 = 1/5
# faithfulness: answered q1 q2 q4 q6 q7; q4's verdict failed and leaves the denominator;
#   faithful q1 q6 q7 of 4 = 3/4 (counting q4 would give 3/5)

CALIBRATION = [
    {"id": "c1", "human": "faithful", "judge": "faithful"},
    {"id": "c2", "human": "faithful", "judge": "unfaithful"},
    {"id": "c3", "human": "unfaithful", "judge": "unfaithful"},
    {"id": "c4", "human": "unfaithful", "judge": None},
    {"id": "c5", "human": "faithful", "judge": "faithful"},
    {"id": "c6", "human": "unfaithful", "judge": "faithful"},
]
# judge agreement: c4's verdict failed and leaves; agree c1 c3 c5 of 5 = 3/5 (counting c4 gives 1/2)
# confusion: human faithful -> judge faithful c1 c5 (2), unfaithful c2 (1);
#            human unfaithful -> judge faithful c6 (1), unfaithful c3 (1); c4 is in no cell


def test_metrics_on_the_fixture():
    assert summarize(ROWS, CALIBRATION)["metrics"] == pytest.approx(
        {
            "recall_at_5": 8 / 15,
            "mrr_at_10": 0.37,
            "citation_accuracy": 3 / 7,
            "unanswerable_refused": 1 / 2,
            "answerable_refused": 1 / 5,
            "faithfulness": 3 / 4,
            "judge_agreement": 3 / 5,
        }
    )


def test_counts_confusion_and_latency_on_the_fixture():
    summary = summarize(ROWS, CALIBRATION)
    assert summary["counts"] == {
        "questions": 7,
        "answerable": 5,
        "unanswerable": 2,
        "refused": 2,  # q3 q5
        "judged": 4,  # q1 q2 q6 q7
        "judge_errors": 1,  # q4
        "calibration_rows": 6,
        "calibration_judge_errors": 1,  # c4
    }
    assert summary["judge_confusion"] == {
        "human_faithful": {"judge_faithful": 2, "judge_unfaithful": 1},
        "human_unfaithful": {"judge_faithful": 1, "judge_unfaithful": 1},
    }
    # search_ms sorted: 40 60 80 100 120 150 200, n = 7
    # p50 k = ceil(0.50 * 7) = ceil(3.5) = 4 -> 100;  p95 k = ceil(0.95 * 7) = ceil(6.65) = 7 -> 200
    assert summary["latency_ms"] == {"search_p50": 100, "search_p95": 200}


def test_a_calibration_verdict_failure_leaves_the_agreement_denominator():
    calibration = [
        {"id": "c1", "human": "unfaithful", "judge": "unfaithful"},
        {"id": "c2", "human": "unfaithful", "judge": None},
    ]
    summary = summarize([], calibration)
    assert summary["metrics"]["judge_agreement"] == 1.0  # 1 of 1 graded, not 1 of 2
    assert summary["judge_confusion"]["human_unfaithful"] == {"judge_faithful": 0, "judge_unfaithful": 1}
    assert (summary["counts"]["calibration_rows"], summary["counts"]["calibration_judge_errors"]) == (2, 1)


NONE = dict.fromkeys(
    [
        "recall_at_5",
        "mrr_at_10",
        "citation_accuracy",
        "unanswerable_refused",
        "answerable_refused",
        "faithfulness",
        "judge_agreement",
    ]
)


@pytest.mark.parametrize(
    ("rows", "calibration", "values"),
    [
        pytest.param([], [], {}, id="nothing"),
        pytest.param(
            [row("u1", 0, {}, None, None, 10)],
            [{"id": "c1", "human": "faithful", "judge": None}],
            {"unanswerable_refused": 1.0},
            id="unanswerable-only-and-every-calibration-verdict-failed",
        ),
        pytest.param(
            [row("a1", 1, {1: [0]}, None, None, 10)],
            [],
            {"recall_at_5": 1.0, "mrr_at_10": 1.0, "answerable_refused": 1.0},
            id="answerable-only-and-refused",
        ),
        pytest.param(
            [row("a1", 1, {1: [0]}, [1], "error", 10)],
            [],
            {"recall_at_5": 1.0, "mrr_at_10": 1.0, "citation_accuracy": 1.0, "answerable_refused": 0.0},
            id="the-only-answer-has-a-verdict-failure",
        ),
    ],
)
def test_a_zero_denominator_gives_none(rows, calibration, values):
    assert summarize(rows, calibration)["metrics"] == NONE | values


def test_an_empty_run_has_no_latency_and_zero_counts():
    summary = summarize([], [])
    assert summary["latency_ms"] == {"search_p50": None, "search_p95": None}
    assert set(summary["counts"].values()) == {0}
    assert summary["judge_confusion"] == {
        "human_faithful": {"judge_faithful": 0, "judge_unfaithful": 0},
        "human_unfaithful": {"judge_faithful": 0, "judge_unfaithful": 0},
    }


def test_percentile_by_nearest_rank():
    values = list(range(20, 0, -1))  # 20 down to 1, so the function has to sort
    # k = ceil(q / 100 * n), at least 1: p50 k = 10, p95 k = 19, p0 k = max(0, 1) = 1, p100 k = 20
    assert [percentile(values, q) for q in (50, 95, 0, 100)] == [10, 19, 1, 20]
    assert percentile([5, 1, 3], 50) == 3  # k = ceil(1.5) = 2
    assert percentile([], 50) is None
