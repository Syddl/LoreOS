import asyncio
import logging
import uuid

from loreos import llm
from loreos.answering import REFUSAL, answer_from_hits
from loreos.retrieval import Hit

HITS = [Hit(uuid.uuid4(), uuid.uuid4(), "handbook.md", ["Releases"], None, f"passage {i}", 0.9) for i in (1, 2, 3)]


def run(hits=HITS):
    return asyncio.run(answer_from_hits("When do we ship?", hits))


def test_refusal_text():
    assert REFUSAL == "I couldn't find this in your documents."


def test_markers_map_to_their_passages_and_out_of_range_markers_go(fake_draft):
    fake_draft.reply = llm.Draft(found=True, text="We ship on Tuesdays [2]. Rollbacks need approval [3] [9][0].")
    result = run()
    assert (result.found, result.reason) == (True, None)
    assert result.text == "We ship on Tuesdays [2]. Rollbacks need approval [3]."
    assert [(c.n, c.chunk_id, c.text) for c in result.citations] == [
        (2, HITS[1].chunk_id, "passage 2"),
        (3, HITS[2].chunk_id, "passage 3"),
    ]
    assert result.citations[0].filename == "handbook.md" and result.citations[0].heading_path == ["Releases"]


def test_no_valid_marker_is_a_refusal(fake_draft):
    fake_draft.reply = llm.Draft(found=True, text="We ship on Tuesdays [4] [0].")
    result = run()
    assert (result.found, result.text, result.citations, result.reason) == (False, REFUSAL, [], "no_valid_citation")


def test_model_not_found_is_a_refusal(fake_draft):
    fake_draft.reply = llm.Draft(found=False, text="The passages do not say [1].")
    result = run()
    assert (result.found, result.text, result.citations, result.reason) == (False, REFUSAL, [], "model_not_found")


def test_no_hits_refuses_without_drafting(fake_draft):
    result = run([])
    assert (result.found, result.text, result.reason) == (False, REFUSAL, "no_chunks")
    assert fake_draft.calls == []


def test_the_log_line_carries_the_reason(fake_draft, caplog):
    fake_draft.reply = llm.Draft(found=False, text="")
    with caplog.at_level(logging.INFO, logger="loreos.answering"):
        run()
    assert "ask found=false reason=model_not_found" in caplog.text
