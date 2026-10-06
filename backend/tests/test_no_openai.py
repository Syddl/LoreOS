import asyncio
import time

import openai
import pytest

from loreos import llm


def test_real_client_under_the_test_env_cannot_reach_openai():
    client = llm.client()
    assert client.base_url.host == "0.0.0.0"
    assert client.api_key == "sk-test-not-a-real-key"
    start = time.monotonic()
    with pytest.raises(openai.APIConnectionError):
        asyncio.run(client.with_options(max_retries=0).embeddings.create(model="x", input=["x"]))
    assert time.monotonic() - start < 1
