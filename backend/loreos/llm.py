"""The only place LoreOS calls OpenAI: embeddings, answer drafts, and the evaluation's grading of answers.

Every call here costs money, and USAGE counts the tokens each response reports.
"""

import collections
from typing import TYPE_CHECKING, Literal

from openai import AsyncOpenAI, BadRequestError, ContentFilterFinishReasonError, LengthFinishReasonError
from pydantic import BaseModel, ValidationError

from loreos import settings
from loreos.embeddings import EMBEDDING_DIM

if TYPE_CHECKING:
    from openai.types import CompletionUsage
    from openai.types.create_embedding_response import Usage as EmbeddingUsage

    from loreos.answering import Citation
    from loreos.retrieval import Hit

EMBED_BATCH = 100

# Keys: embedding_input, answer_input, answer_output, judge_input, judge_output, and
# responses_without_usage for each response whose tokens could not be read.
USAGE: collections.Counter[str] = collections.Counter()

SYSTEM = (
    "You answer questions using only the numbered passages from the user's documents. "
    "Cite every claim with its passage number in square brackets, like [1] or [2][3]. "
    "Use no outside knowledge. If the passages do not answer the question, set found to false."
)

JUDGE_SYSTEM = (
    "You grade whether an answer is faithful to the numbered passages it cites. "
    "Split the answer into its factual claims. "
    "A claim is supported only if the passages state it or directly imply it; "
    "paraphrase counts, but outside knowledge does not, even when the claim is true. "
    "Markers like [2] point to the passage with that number. "
    'Grade "faithful" only if every claim is supported; one unsupported or contradicted claim makes it "unfaithful". '
    "Do not penalise hedges or statements that something is not covered. "
    "Write a one-sentence rationale naming the first unsupported claim, "
    "or confirming that all claims are supported, before the grade."
)


class Draft(BaseModel):
    found: bool
    text: str


class Verdict(BaseModel):
    rationale: str  # first, so the model writes it before it commits to a grade
    grade: Literal["faithful", "unfaithful"]


class VerdictError(RuntimeError):
    """The judge gave no verdict: a refusal, no parsed output, output outside the schema, or a length or content-filter stop."""


def client() -> AsyncOpenAI:
    """A new client per call, so none outlives the event loop it was made on."""
    return AsyncOpenAI(api_key=settings.openai_api_key(), base_url=settings.openai_base_url())


def _count(kind: str, usage: "CompletionUsage | EmbeddingUsage | None") -> None:
    """Add one response's tokens to USAGE; completion_tokens already includes reasoning tokens."""
    if usage is None:
        USAGE["responses_without_usage"] += 1
        return
    USAGE[f"{kind}_input"] += usage.prompt_tokens
    if kind != "embedding":
        USAGE[f"{kind}_output"] += usage.completion_tokens


async def embed(texts: list[str]) -> list[list[float]]:
    model = settings.embedding_model()
    vectors: list[list[float]] = []
    async with client() as openai:
        for start in range(0, len(texts), EMBED_BATCH):
            response = await openai.embeddings.create(model=model, input=texts[start : start + EMBED_BATCH])
            _count("embedding", response.usage)
            vectors += [d.embedding for d in sorted(response.data, key=lambda d: d.index)]
    if (wrong := next((len(v) for v in vectors if len(v) != EMBEDDING_DIM), None)) is not None:
        raise ValueError(
            f"{model} returned {wrong} dimensions and LoreOS stores {EMBEDDING_DIM}; "
            f"set EMBEDDING_MODEL to a {EMBEDDING_DIM}-dimension model such as text-embedding-3-small"
        )
    return vectors


async def draft_answer(question: str, hits: list["Hit"]) -> Draft:
    passages = "\n\n".join(f"[{n}] {source_label(hit)}\n{hit.text}" for n, hit in enumerate(hits, 1))
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
        except (LengthFinishReasonError, ContentFilterFinishReasonError) as e:
            _count("answer", e.completion.usage if e.completion else None)  # billed, so counted, then raised as before
            raise
    _count("answer", completion.usage)
    message = completion.choices[0].message
    if message.parsed is None:
        raise RuntimeError(f"{model} returned no structured answer (refusal: {message.refusal!r})")
    return message.parsed


async def judge(question: str, answer: str, passages: list[dict]) -> Verdict:
    """Grade an answer against only the passages given ({n, source, text}), each under its own n."""
    cited = "\n\n".join(f"[{p['n']}] {p['source']}\n{p['text']}" for p in passages)
    model = settings.judge_model()
    async with client() as openai:
        try:
            completion = await openai.chat.completions.parse(
                model=model,
                messages=[
                    {"role": "system", "content": JUDGE_SYSTEM},
                    {"role": "user", "content": f"Question: {question}\n\nPassages:\n\n{cited}\n\nAnswer: {answer}"},
                ],
                response_format=Verdict,
                reasoning_effort="low",
            )
        except (LengthFinishReasonError, ContentFilterFinishReasonError) as e:
            # API errors are not caught here: they stop the run, while a verdict failure is one row's.
            _count("judge", e.completion.usage if e.completion else None)
            raise VerdictError(f"{model} stopped before a verdict ({type(e).__name__})") from e
        except ValidationError as e:  # a server that does not enforce the schema; parse() drops the usage
            _count("judge", None)
            raise VerdictError(f"{model} returned a verdict outside the schema ({e.error_count()} errors)") from e
    _count("judge", completion.usage)
    message = completion.choices[0].message
    if message.parsed is None:
        raise VerdictError(f"{model} returned no verdict (refusal: {message.refusal!r})")
    return message.parsed


def source_label(hit: "Hit | Citation") -> str:
    where = " > ".join(hit.heading_path)
    page = f", page {hit.page}" if hit.page else ""
    return f"{hit.filename}{' > ' + where if where else ''}{page}"
