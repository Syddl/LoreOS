"""Reciprocal rank fusion: merge rankings of chunk ids into one order. Pure."""

import uuid
from fractions import Fraction

RRF_K = 60  # the usual constant, not tuned here


def rrf(rankings: list[list[uuid.UUID]], k: int = RRF_K) -> list[tuple[uuid.UUID, float]]:
    """(id, score) pairs, best first. An id's score is the sum of 1 / (k + rank) over the rankings that hold it,
    rank counted from 1. Summed exactly, so a tie is a real tie: it breaks on the best single rank, then on the id."""
    scores: dict[uuid.UUID, Fraction] = {}
    best: dict[uuid.UUID, int] = {}
    for ranking in rankings:
        for rank, id_ in enumerate(ranking, 1):
            scores[id_] = scores.get(id_, Fraction(0)) + Fraction(1, k + rank)
            best[id_] = min(best.get(id_, rank), rank)
    order = sorted(scores, key=lambda id_: (-scores[id_], best[id_], id_))
    return [(id_, float(scores[id_])) for id_ in order]
