"""The local cross-encoder reranker: fastembed on the CPU through onnxruntime, no PyTorch.

Imports nothing from loreos at module level: retrieval imports this module, and ingest imports retrieval, so a
module-level import of either closes a cycle. fastembed itself is imported in model(), since importing it takes about
a second that the api and the tests should not pay unless the reranker is used.
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    from loreos.retrieval import Hit

# Apache-2.0, 0.08 GB; fastembed cuts each (question, passage) pair at 512 tokens (spec behaviour 5, decision 0010).
RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"


@functools.cache
def model() -> TextCrossEncoder:
    """The cross-encoder, loaded once per process; downloads it on first use. Raises RuntimeError with the fix."""
    from fastembed.common.utils import define_cache_dir
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    cache = define_cache_dir()  # FASTEMBED_CACHE_PATH, else a fastembed_cache folder in the temp directory
    try:
        return TextCrossEncoder(RERANK_MODEL)
    except Exception as e:  # a failed download, a corrupt file, onnxruntime refusing the model: all need the same fixes
        raise RuntimeError(
            f"the reranker model {RERANK_MODEL} could not load from {cache} ({type(e).__name__}: {e}); the first load "
            f"downloads it and needs network access, a corrupt cache is fixed by deleting {cache}, or set RERANK=off "
            "to serve without the reranker"
        ) from e


def rerank(query: str, hits: list[Hit]) -> list[Hit]:
    """The hits rescored by the cross-encoder on the text each was embedded from, best first; ties keep input order.
    Synchronous and CPU-bound: an async caller runs it in a thread."""
    from loreos.ingest import embedding_input

    if not hits:
        return []
    passages = [embedding_input(hit) for hit in hits]
    for hit, score in zip(hits, model().rerank(query, passages), strict=True):
        hit.score = float(score)
    return sorted(hits, key=lambda hit: -hit.score)
