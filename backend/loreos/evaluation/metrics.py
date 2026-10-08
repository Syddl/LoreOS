"""Evaluation metrics: per-question result rows and calibration grades in, the result file's numbers out.

Pure: no I/O, no loreos imports. A metric whose denominator is 0 is None, never 0.
"""

import math

GRADES = ("faithful", "unfaithful")


def summarize(rows: list[dict], calibration: list[dict]) -> dict:
    answerable = [r for r in rows if r["answerable"]]
    unanswerable = [r for r in rows if not r["answerable"]]
    verdicts = [r["judge"] for r in rows if r["answer"]["found"] and r["judge"] is not None]
    grades = [v["grade"] for v in verdicts if v["grade"] is not None]
    cited = [[bool(c["relevant"]) for c in r["answer"]["citations"]] for r in answerable if r["answer"]["found"]]
    graded_pairs = [c for c in calibration if c["judge"] is not None]
    search_ms = [r["search_ms"] for r in rows]
    return {
        "metrics": {
            "recall_at_5": _mean([_recall(r, 5) for r in answerable]),
            "mrr_at_10": _mean([_reciprocal_rank(r, 10) for r in answerable]),
            # pooled over questions, so a question citing more chunks weighs more
            "citation_accuracy": _mean([ok for row in cited for ok in row]),
            "unanswerable_refused": _mean([not r["answer"]["found"] for r in unanswerable]),
            "answerable_refused": _mean([not r["answer"]["found"] for r in answerable]),
            "faithfulness": _mean([g == "faithful" for g in grades]),
            "judge_agreement": _mean([c["judge"] == c["human"] for c in graded_pairs]),
        },
        "judge_confusion": {
            f"human_{h}": {f"judge_{j}": sum(c["human"] == h and c["judge"] == j for c in calibration) for j in GRADES}
            for h in GRADES
        },
        "latency_ms": {"search_p50": percentile(search_ms, 50), "search_p95": percentile(search_ms, 95)},
        "counts": {
            "questions": len(rows),
            "answerable": len(answerable),
            "unanswerable": len(unanswerable),
            "refused": sum(not r["answer"]["found"] for r in rows),
            "judged": len(grades),
            "judge_errors": len(verdicts) - len(grades),
            "calibration_rows": len(calibration),
            "calibration_judge_errors": len(calibration) - len(graded_pairs),
        },
    }


def percentile(values: list[float], q: float) -> float | None:
    """Nearest rank: the k-th smallest value, k = ceil(q / 100 * n), at least 1."""
    if not values:
        return None
    k = max(1, math.ceil(q * len(values) / 100))  # q / 100 * n first would make 7 / 100 * 100 ceil to 8
    return sorted(values)[k - 1]


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _recall(row: dict, k: int) -> float:
    matched = {i for h in row["hits"] if h["rank"] <= k for i in h["relevant"]}
    return len(matched) / len(row["sources"])


def _reciprocal_rank(row: dict, k: int) -> float:
    ranks = [h["rank"] for h in row["hits"] if h["rank"] <= k and h["relevant"]]
    return 1 / min(ranks) if ranks else 0.0
