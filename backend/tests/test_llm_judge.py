import asyncio
import re
import uuid
from collections import Counter
from types import SimpleNamespace

import httpx2  # the SDK's own HTTP module, to build the request its errors carry
import openai
import pydantic
import pytest

from loreos import llm, settings
from loreos.embeddings import EMBEDDING_DIM
from loreos.retrieval import Hit

PASSAGES = [
    {"n": 2, "source": "handbook.md > Releases", "text": "We ship on Tuesdays."},
    {"n": 4, "source": "csf.pdf, page 7", "text": "Rollbacks need approval."},
]
VERDICT = llm.Verdict(rationale="Every claim is supported.", grade="faithful")
REQUEST = httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")


def completion(parsed, usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20), refusal=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed, refusal=refusal))], usage=usage)


class FakeOpenAI:
    """Stands in for AsyncOpenAI: records each call's kwargs; parse returns or raises .reply."""

    def __init__(self):
        self.reply = completion(VERDICT)
        self.parse_calls: list[dict] = []
        self.embed_calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(parse=self.parse))
        self.embeddings = SimpleNamespace(create=self.create)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def parse(self, **kwargs):
        self.parse_calls.append(kwargs)
        if isinstance(self.reply, BaseException):
            raise self.reply
        return self.reply

    async def create(self, **kwargs):
        self.embed_calls.append(kwargs)
        data = [SimpleNamespace(index=i, embedding=[0.0] * EMBEDDING_DIM) for i, _ in enumerate(kwargs["input"])]
        return SimpleNamespace(data=data, usage=SimpleNamespace(prompt_tokens=len(kwargs["input"])))


@pytest.fixture(autouse=True)
def usage():
    llm.USAGE.clear()
    yield
    llm.USAGE.clear()


@pytest.fixture
def fake_openai(monkeypatch):
    fake = FakeOpenAI()
    monkeypatch.setattr(llm, "client", lambda: fake)
    return fake


def judge():
    return asyncio.run(llm.judge("When do we ship?", "On Tuesdays [2].", PASSAGES))


def test_the_judge_gets_only_the_given_passages_with_their_numbers(fake_openai):
    assert judge() == VERDICT
    assert fake_openai.parse_calls[0]["messages"][1] == {
        "role": "user",
        "content": "Question: When do we ship?\n\nPassages:\n\n"
        "[2] handbook.md > Releases\nWe ship on Tuesdays.\n\n[4] csf.pdf, page 7\nRollbacks need approval.\n\n"
        "Answer: On Tuesdays [2].",
    }


def test_the_judge_request_uses_the_judge_model_low_effort_and_no_sampling_knobs(fake_openai, monkeypatch):
    monkeypatch.setenv("JUDGE_MODEL", "judge-under-test")
    judge()
    call = fake_openai.parse_calls[0]
    assert call["model"] == settings.judge_model() == "judge-under-test"
    assert call["reasoning_effort"] == "low"
    assert call["response_format"] is llm.Verdict
    assert call["messages"][0] == {"role": "system", "content": llm.JUDGE_SYSTEM}
    assert not {"temperature", "top_p", "seed", "max_tokens", "max_completion_tokens"} & call.keys()
    assert list(llm.Verdict.model_fields) == ["rationale", "grade"]  # the rationale is generated first


def test_usage_counts_every_embedding_batch_the_answer_and_the_judge(fake_openai, monkeypatch):
    monkeypatch.setattr(llm, "EMBED_BATCH", 2)
    asyncio.run(llm.embed(["a", "b", "c"]))
    assert len(fake_openai.embed_calls) == 2
    fake_openai.reply = completion(
        llm.Draft(found=True, text="On Tuesdays [1]."), usage=SimpleNamespace(prompt_tokens=50, completion_tokens=5)
    )
    hit = Hit(uuid.uuid4(), uuid.uuid4(), "handbook.md", ["Releases"], None, "We ship on Tuesdays.", 0.9)
    asyncio.run(llm.draft_answer("When do we ship?", [hit]))
    fake_openai.reply = completion(VERDICT)
    judge()
    assert llm.USAGE == Counter(embedding_input=3, answer_input=50, answer_output=5, judge_input=100, judge_output=20)


def test_a_response_without_usage_is_counted_as_such(fake_openai):
    fake_openai.reply = completion(VERDICT, usage=None)
    judge()
    assert llm.USAGE == Counter(responses_without_usage=1)


def test_a_refusal_is_a_verdict_error_and_its_tokens_still_count(fake_openai):
    fake_openai.reply = completion(None, refusal="I can't grade this.")
    with pytest.raises(llm.VerdictError, match=rf"{re.escape(settings.judge_model())}.*I can't grade this"):
        judge()
    assert llm.USAGE["judge_input"] == 100


@pytest.mark.parametrize("error", [openai.LengthFinishReasonError, openai.ContentFilterFinishReasonError])
def test_a_length_or_content_filter_stop_is_a_verdict_error_and_its_tokens_still_count(fake_openai, error):
    fake_openai.reply = error(completion=completion(None))
    with pytest.raises(llm.VerdictError, match=rf"{re.escape(settings.judge_model())}.*{error.__name__}"):
        judge()
    assert llm.USAGE["judge_input"] == 100


def test_a_reply_outside_the_verdict_schema_is_a_verdict_error(fake_openai):
    """A server that does not enforce the schema can send a grade parse() rejects with a ValidationError."""
    try:
        llm.Verdict.model_validate_json('{"rationale": "x", "grade": "partly"}')
    except pydantic.ValidationError as e:
        fake_openai.reply = e
    with pytest.raises(llm.VerdictError, match=rf"{re.escape(settings.judge_model())}.*schema"):
        judge()
    assert llm.USAGE == Counter(responses_without_usage=1)


def test_a_draft_outside_the_schema_is_counted_and_raised_unchanged(fake_openai):
    try:
        llm.Draft.model_validate_json('{"found": "maybe"}')
    except pydantic.ValidationError as e:
        fake_openai.reply = e
    hit = Hit(uuid.uuid4(), uuid.uuid4(), "handbook.md", ["Releases"], None, "We ship on Tuesdays.", 0.9)
    with pytest.raises(pydantic.ValidationError) as caught:
        asyncio.run(llm.draft_answer("When do we ship?", [hit]))
    assert caught.value is fake_openai.reply
    assert llm.USAGE == Counter(responses_without_usage=1)


@pytest.mark.parametrize("error", [openai.LengthFinishReasonError, openai.ContentFilterFinishReasonError])
def test_a_length_or_content_filter_stop_while_answering_still_counts_its_tokens(fake_openai, error):
    fake_openai.reply = error(completion=completion(None))
    hit = Hit(uuid.uuid4(), uuid.uuid4(), "handbook.md", ["Releases"], None, "We ship on Tuesdays.", 0.9)
    with pytest.raises(error):
        asyncio.run(llm.draft_answer("When do we ship?", [hit]))
    assert llm.USAGE == Counter(answer_input=100, answer_output=20)


@pytest.mark.parametrize(
    "error",
    [
        openai.APIConnectionError(request=REQUEST),
        openai.BadRequestError("bad request", response=httpx2.Response(400, request=REQUEST), body=None),
    ],
    ids=["connection", "bad_request"],
)
def test_an_api_error_propagates_unchanged(fake_openai, error):
    fake_openai.reply = error
    with pytest.raises(openai.APIError) as caught:
        judge()
    assert caught.value is error


def test_fake_judge_records_each_call_and_raises_an_exception_reply(fake_judge):
    assert judge() == fake_judge.reply
    fake_judge.reply = llm.VerdictError("no verdict")
    with pytest.raises(llm.VerdictError):
        judge()
    assert fake_judge.calls == [("When do we ship?", "On Tuesdays [2].", PASSAGES)] * 2
