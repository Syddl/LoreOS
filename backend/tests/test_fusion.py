"""fusion.rrf: reciprocal rank fusion of chunk-id rankings.

Proves: the order and scores against hand-computed sums at k = 60; an id in one list only still ranks; an exact
tie breaks on the best single rank, then on the id; empty input gives an empty list.
Does NOT exercise: whether k = 60 suits this corpus (the evaluation measures the fused order, not k).
"""

import uuid

import pytest

from loreos.fusion import RRF_K, rrf

A, B, C, D = (uuid.UUID(int=n) for n in (1, 2, 3, 4))
FILLERS = [uuid.UUID(int=100 + n) for n in range(8)]


def test_hand_computed_order_and_scores_at_k_60():
    fused = rrf([[A, B, C], [B, C, D], [C, A]])
    # C: 1/63 + 1/62 + 1/61. A: 1/61 + 1/62 and B: 1/62 + 1/61 tie exactly, both best at rank 1, so A by id. D: 1/63.
    assert RRF_K == 60
    assert [id_ for id_, _ in fused] == [C, A, B, D]
    scores = dict(fused)
    assert scores[C] == pytest.approx(1 / 63 + 1 / 62 + 1 / 61)
    assert scores[A] == scores[B] == pytest.approx(1 / 61 + 1 / 62)
    assert scores[D] == pytest.approx(1 / 63)


def test_an_id_in_one_list_only_still_ranks():
    assert [id_ for id_, _ in rrf([[A], [B, A]])] == [A, B]


def test_an_exact_tie_breaks_on_the_best_single_rank():
    # At k = 0, late at ranks 2 and 6 scores 1/2 + 1/6, and early at ranks 3 and 3 scores 1/3 + 1/3: both 2/3.
    # early has the lower id, so only the best-rank rule puts late (best rank 2) first.
    early, late = uuid.UUID(int=10), uuid.UUID(int=20)
    f = FILLERS
    first = [f[0], late, early, f[1]]
    second = [f[2], f[3], early, f[4], f[5], late]
    order = [id_ for id_, _ in rrf([first, second], k=0)]
    assert order.index(late) < order.index(early)


def test_an_exact_tie_on_both_breaks_on_the_id():
    assert [id_ for id_, _ in rrf([[B, A], [A, B]])] == [A, B]


def test_empty_input_gives_nothing():
    assert rrf([]) == [] and rrf([[], []]) == []
