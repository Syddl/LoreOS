import pytest

from loreos import smoke


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


@pytest.mark.parametrize("argv", [["-h"], ["--help"]])
def test_help_spends_nothing(spy, argv, capsys):
    assert smoke.cli(argv) == 0
    assert spy == [] and "--dry-run" in capsys.readouterr().out


@pytest.mark.parametrize("argv", [["--bogus"], ["--dry-run", "--help"], ["now"]])
def test_any_other_argument_is_refused_before_spending(spy, argv):
    assert smoke.cli(argv) == 2
    assert spy == []


def test_no_argument_runs_the_paid_flow(spy):
    assert smoke.cli([]) == 0
    assert spy == ["paid"]
