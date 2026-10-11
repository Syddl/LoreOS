"""db.engine() against testdb: a connection reset while connecting is retried and counted; any other failure is not."""

import asyncpg
import pytest

from conftest import sql
from loreos.db import CONNECT_ATTEMPTS, RETRIES


def failing_connect(monkeypatch, failures):
    """asyncpg.connect raising each of `failures` in turn, then connecting for real; returns the list of calls."""
    real, calls = asyncpg.connect, []

    async def connect(*args, **kwargs):
        calls.append(1)
        if len(calls) <= len(failures):
            raise failures[len(calls) - 1]
        return await real(*args, **kwargs)

    monkeypatch.setattr(asyncpg, "connect", connect)
    return calls


def reset():
    return ConnectionResetError(64, "The specified network name is no longer available")  # WinError 64, as seen live


def test_a_reset_while_connecting_is_retried_and_counted(db, monkeypatch):
    RETRIES.clear()
    calls = failing_connect(monkeypatch, [reset()] * (CONNECT_ATTEMPTS - 1))
    assert sql("select 1") == [(1,)]
    assert len(calls) == CONNECT_ATTEMPTS
    assert RETRIES["connect_reset"] == CONNECT_ATTEMPTS - 1


def test_a_reset_on_every_attempt_still_stops(db, monkeypatch):
    calls = failing_connect(monkeypatch, [reset()] * CONNECT_ATTEMPTS)
    with pytest.raises(ConnectionResetError):
        sql("select 1")
    assert len(calls) == CONNECT_ATTEMPTS


def test_a_refused_login_is_not_retried(db, monkeypatch):
    calls = failing_connect(monkeypatch, [asyncpg.InvalidPasswordError("password authentication failed")])
    with pytest.raises(Exception, match="password authentication failed"):
        sql("select 1")
    assert len(calls) == 1
