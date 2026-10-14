import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from loreos import llm, rerank, retrieval, smoke, verify_rls


@pytest.fixture
def spy(monkeypatch):
    """Replace the preflight and the paid flow; the list records which ran."""
    ran: list[str] = []

    async def preflight():
        ran.append("preflight")

    async def paid_flow():
        ran.append("paid")
        return 0

    monkeypatch.setattr(smoke, "preflight", preflight)
    monkeypatch.setattr(smoke, "main", paid_flow)
    return ran


def test_dry_run_runs_only_the_free_preflight(spy):
    assert smoke.cli(["--dry-run"]) == 0
    assert spy == ["preflight"]


def test_npm_dry_run_without_the_separator_runs_only_the_preflight(spy, monkeypatch):
    """npm run paid:smoke --dry-run: npm keeps the flag, sets npm_config_dry_run and runs the script."""
    monkeypatch.setenv("npm_config_dry_run", "true")
    assert smoke.cli([]) == 0
    assert spy == ["preflight"]


@pytest.mark.parametrize("argv", [["-h"], ["--help"]])
def test_help_spends_nothing(spy, argv, capsys):
    assert smoke.cli(argv) == 0
    assert spy == [] and "--dry-run" in capsys.readouterr().out


@pytest.mark.parametrize("argv", [["--bogus"], ["--dry-run", "--help"], ["now"]])
def test_any_other_argument_is_refused_before_spending(spy, argv):
    assert smoke.cli(argv) == 2
    assert spy == []


def test_no_argument_runs_the_paid_flow(spy, monkeypatch):
    monkeypatch.delenv("npm_config_dry_run", raising=False)
    assert smoke.cli([]) == 0
    assert spy == ["paid"]


@pytest.fixture
def listed(monkeypatch):
    """Replace llm.client; the list records each models listing, the preflight's first call to OpenAI."""
    calls: list[str] = []

    async def list_models():
        calls.append("models")

    @asynccontextmanager
    async def client():
        yield SimpleNamespace(models=SimpleNamespace(list=list_models))

    monkeypatch.setattr(llm, "client", client)
    return calls


def test_preflight_stops_on_a_missing_grant_before_calling_openai(db, listed, monkeypatch):
    missing = "loreos_app lacks USAGE on schema extensions"

    async def problems(conn):
        return [missing]

    monkeypatch.setattr(verify_rls, "problems", problems)
    with pytest.raises(SystemExit) as stopped:
        asyncio.run(smoke.preflight())
    assert missing in str(stopped.value) and "run npm run db:verify-rls" in str(stopped.value)
    assert listed == []


def test_preflight_with_the_grants_in_place_reaches_openai(db, listed):
    asyncio.run(smoke.preflight())
    assert listed == ["models"]


def test_preflight_stops_on_a_reranker_that_cannot_load_before_anything_is_paid(db, listed, monkeypatch):
    """With hybrid_rerank serving, ingest would pay for the embedding before answering loads the model."""

    def fail():
        raise RuntimeError("the reranker model could not load (faked); or set RERANK=off")

    monkeypatch.setattr(retrieval, "DEFAULT_MODE", "hybrid_rerank")
    monkeypatch.setattr(rerank, "model", fail)
    with pytest.raises(SystemExit, match=r"^preflight: .*RERANK=off"):
        asyncio.run(smoke.preflight())
    assert listed == []


@pytest.mark.parametrize("default, switch", [("vector", "on"), ("hybrid", "on"), ("hybrid_rerank", "off")])
def test_preflight_never_loads_the_reranker_when_the_api_would_not_use_it(db, listed, monkeypatch, default, switch):
    monkeypatch.setattr(retrieval, "DEFAULT_MODE", default)
    monkeypatch.setenv("RERANK", switch)
    monkeypatch.setattr(rerank, "model", lambda: pytest.fail(f"loaded the reranker for {retrieval.serving_mode()} serving"))
    asyncio.run(smoke.preflight())
    assert listed == ["models"]
