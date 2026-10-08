"""The paid:eval CLI: what reaches run.evaluate, the paid part, and what stops before it. Both halves are faked."""

import json
import os

import pytest

from loreos.evaluation import preflight, run
from loreos.evaluation.__main__ import cli

SHA = "fedcba9876543210fedcba9876543210fedcba98"
NOTES = ["models: listing models returned 404; the model names are unverified"]
METRICS = {"recall_at_5": 0.5, "judge_agreement": None}


@pytest.fixture
def spy(monkeypatch, tmp_path):
    """Replace the preflight and the run; the list records each call with its arguments."""
    ran: list[tuple] = []

    async def fake_preflight(limit):
        ran.append(("preflight", limit))
        return SHA, NOTES

    async def fake_evaluate(mode, limit, sha, notes):
        ran.append(("evaluate", mode, limit, sha, notes))
        path = tmp_path / "result.json"
        path.write_text(json.dumps({"destination": "scratch", "metrics": METRICS, "notes": ["scratch: --limit 3 was given"]}))
        return path

    monkeypatch.setattr(preflight, "preflight", fake_preflight)
    monkeypatch.setattr(run, "evaluate", fake_evaluate)
    for name in [name for name in os.environ if name.lower().startswith("npm_config_")]:
        monkeypatch.delenv(name)  # npm run check:all sets many; each test sets only the ones it is about
    return ran


def test_no_argument_runs_the_preflight_then_the_whole_run_at_its_commit(spy, tmp_path, capsys):
    assert cli([]) == 0
    assert spy == [("preflight", None), ("evaluate", "vector", None, SHA, NOTES)]
    out = capsys.readouterr().out
    assert str(tmp_path / "result.json") in out and "destination: scratch" in out
    assert "recall_at_5: 0.5" in out and "judge_agreement: None" in out and "scratch: --limit 3 was given" in out


def test_mode_and_limit_reach_the_preflight_and_the_run(spy):
    assert cli(["--mode", "vector", "--limit", "3"]) == 0
    assert spy == [("preflight", 3), ("evaluate", "vector", 3, SHA, NOTES)]


@pytest.mark.parametrize("argv", [["--dry-run"], ["--dry-run", "--limit", "2"]])
def test_dry_run_runs_only_the_preflight(spy, argv, capsys):
    assert cli(argv) == 0
    assert [call[0] for call in spy] == ["preflight"]
    assert "dry run: preflight only, no paid call made" in capsys.readouterr().out


@pytest.mark.parametrize("argv", [[], ["--limit", "2"]])
def test_npm_dry_run_without_the_separator_runs_only_the_preflight(spy, monkeypatch, argv):
    """npm run paid:eval --dry-run: npm keeps the flag, sets npm_config_dry_run and runs the script."""
    monkeypatch.setenv("npm_config_dry_run", "true")
    assert cli(argv) == 0
    assert [call[0] for call in spy] == ["preflight"]


@pytest.mark.parametrize(
    "name, form",
    [
        ("limit", "npm run paid:eval -- --limit N"),
        ("mode", "npm run paid:eval -- --mode vector"),
        ("lim", "npm run paid:eval -- --limit N"),  # argparse would take --lim as --limit; npm takes it too
        ("li", "npm run paid:eval -- --limit N"),
        ("mo", "npm run paid:eval -- --mode vector"),
    ],
)
def test_a_flag_npm_swallowed_is_refused_with_the_separator_form(spy, monkeypatch, capsys, name, form):
    """npm run paid:eval --limit=5: npm takes the flag as its own config and would start a full run without it."""
    monkeypatch.setenv(f"npm_config_{name}", "5")
    assert cli([]) == 2
    assert spy == []
    assert form in capsys.readouterr().err


# npm's own settings, including the two it expands --l and --m into (npm run env --l --m=x shows long and message).
@pytest.mark.parametrize("name", ["loglevel", "user_agent", "cache", "message", "long", "local_prefix"])
def test_npm_s_own_settings_do_not_stop_the_run(spy, monkeypatch, name):
    monkeypatch.setenv(f"npm_config_{name}", "x")
    assert cli(["--dry-run"]) == 0


@pytest.mark.parametrize("argv", [["--limit", "0"], ["--limit", "-1"], ["--limit", "two"], ["--mode", "hybrid"], ["--bogus"], ["now"]])
def test_a_bad_argument_exits_2_before_the_preflight(spy, argv, capsys):
    assert cli(argv) == 2
    assert spy == []
    assert "usage: npm run paid:eval --" in capsys.readouterr().err


def test_a_limit_below_1_says_why(spy, capsys):
    cli(["--limit", "0"])
    assert "an integer of at least 1" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [["-h"], ["--help"]])
def test_help_spends_nothing(spy, argv, capsys):
    assert cli(argv) == 0
    assert spy == []
    assert "--dry-run" in capsys.readouterr().out


def test_a_preflight_that_stops_never_reaches_the_run(spy, monkeypatch):
    async def stopping_preflight(limit):
        spy.append(("preflight", limit))
        raise SystemExit("preflight: the git tree is not clean; commit or remove the changes")

    monkeypatch.setattr(preflight, "preflight", stopping_preflight)
    with pytest.raises(SystemExit, match="the git tree is not clean"):
        cli([])
    assert spy == [("preflight", None)]
