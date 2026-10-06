"""The only place LoreOS calls OpenAI: embeddings and answer drafts. Every call here costs money."""

from typing import TYPE_CHECKING

from openai import AsyncOpenAI, BadRequestError
from pydantic import BaseModel

from loreos import settings
from loreos.embeddings import EMBEDDING_DIM

if TYPE_CHECKING:
    from loreos.retrieval import Hit

EMBED_BATCH = 100

SYSTEM = (
    "You answer questions using only the numbered passages from the user's documents. "
    "Cite every claim with its passage number in square brackets, like [1] or [2][3]. "
    "Use no outside knowledge. If the passages do not answer the question, set found to false."
)


class Draft(BaseModel):
    found: bool
    text: str


def client() -> AsyncOpenAI:
    """A new client per call, so none outlives the event loop it was made on."""
    return AsyncOpenAI(api_key=settings.openai_api_key(), base_url=settings.openai_base_url())


async def embed(texts: list[str]) -> list[list[float]]:
    model = settings.embedding_model()
    vectors: list[list[float]] = []
    async with client() as openai:
        for start in range(0, len(texts), EMBED_BATCH):
            response = await openai.embeddings.create(model=model, input=texts[start : start + EMBED_BATCH])
            vectors += [d.embedding for d in sorted(response.data, key=lambda d: d.index)]
    if wrong := next((len(v) for v in vectors if len(v) != EMBEDDING_DIM), None):
        raise ValueError(
            f"{model} returned {wrong} dimensions and LoreOS stores {EMBEDDING_DIM}; "
            f"set EMBEDDING_MODEL to a {EMBEDDING_DIM}-dimension model such as text-embedding-3-small"
        )
    return vectors


async def draft_answer(question: str, hits: list["Hit"]) -> Draft:
    passages = "\n\n".join(f"[{n}] {_source(hit)}\n{hit.text}" for n, hit in enumerate(hits, 1))
    model = settings.answer_model()
    async with client() as openai:
        try:
            completion = await openai.chat.completions.parse(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": f"Passages:\n\n{passages}\n\nQuestion: {question}"},
                ],
                response_format=Draft,
            )
        except BadRequestError as e:
            raise RuntimeError(
                f"{model} rejected the answer request ({e.message}); a server behind OPENAI_BASE_URL "
                "may not support structured output (response_format json_schema)"
            ) from e
    message = completion.choices[0].message
    if message.parsed is None:
        raise RuntimeError(f"{model} returned no structured answer (refusal: {message.refusal!r})")
    return message.parsed


def _source(hit: "Hit") -> str:
    where = " > ".join(hit.heading_path)
    page = f", page {hit.page}" if hit.page else ""
    return f"{hit.filename}{' > ' + where if where else ''}{page}"
