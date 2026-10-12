"""python -m loreos.admin reset-password <email>, run through main() with getpass patched."""

import asyncio
import getpass
from types import SimpleNamespace

import pytest

from conftest import sql
from loreos import admin, auth
from loreos.db import system_session

OLD = "old password, long enough"
NEW = "new password, long enough"


def call(fn, *args):
    """fn(conn, *args) inside one system_session; its result."""

    async def go():
        async with system_session() as conn:
            return await fn(conn, *args)

    return asyncio.run(go())


@pytest.fixture
def users(clean):
    """ann with two sessions and bob with one, both on OLD."""
    ann = call(auth.create_user, "ann@example.com", OLD)
    bob = call(auth.create_user, "bob@example.com", OLD)
    for user_id in (ann, ann, bob):
        call(auth.create_session, user_id)
    return ann, bob


@pytest.fixture
def typed(monkeypatch):
    """Set .answers to what the operator types at each getpass prompt; .prompts records each prompt."""
    fake = SimpleNamespace(answers=[], prompts=[])

    def getpass_(prompt="Password: "):
        fake.prompts.append(prompt)
        return fake.answers.pop(0)

    monkeypatch.setattr(getpass, "getpass", getpass_)
    return fake


def accounts():
    return sql("select email, password_hash from loreos.users order by email")


def sessions():
    return sql("select id, user_id from loreos.sessions order by id")


def test_reset_sets_the_new_password_and_ends_only_that_users_sessions(users, typed, capsys):
    ann, bob = users
    bobs_sessions = [row for row in sessions() if row.user_id == bob]
    typed.answers = [NEW, NEW]
    assert admin.main(["reset-password", "  Ann@Example.COM "]) == 0
    assert len(typed.prompts) == 2
    password_hash = sql("select password_hash from loreos.users where id = :u", u=ann)[0][0]
    assert auth.verify_password(password_hash, NEW) is True
    assert auth.verify_password(password_hash, OLD) is False
    assert sessions() == bobs_sessions
    assert "ann@example.com" in capsys.readouterr().out


@pytest.mark.parametrize(
    "email, answers, named",
    [
        ("nobody@example.com", [NEW, NEW], "nobody@example.com"),
        ("ann@example.com", [NEW, NEW + "x"], "differ"),
        ("ann@example.com", ["a" * 11, "a" * 11], "12"),
    ],
    ids=["unknown email", "mismatch", "11 characters"],
)
def test_a_refusal_exits_1_and_changes_nothing(users, typed, capsys, email, answers, named):
    before = accounts(), sessions()
    typed.answers = answers
    assert admin.main(["reset-password", email]) == 1
    assert (accounts(), sessions()) == before
    assert named in capsys.readouterr().err


@pytest.mark.parametrize("argv", [[], ["reset-password"], ["reset", "ann@example.com"], ["reset-password", "a", "b"]])
def test_bad_arguments_print_usage_and_exit_2(argv, typed, capsys):
    assert admin.main(argv) == 2
    assert typed.prompts == []
    assert admin.USAGE in capsys.readouterr().err
