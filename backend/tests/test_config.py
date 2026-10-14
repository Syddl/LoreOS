import json
import re
from pathlib import Path

import pytest

from loreos import settings

ROOT = Path(__file__).resolve().parents[2]


def env_example() -> dict[str, str]:
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line and not line.startswith("#"))


def test_dev_api_binds_localhost_only():
    command = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["scripts"]["dev:api"]
    assert "--host 127.0.0.1" in command and "0.0.0.0" not in command


def test_env_example_lists_exactly_the_keys_settings_reads():
    read = set(re.findall(r'_env\("([A-Z_]+)"\)', Path(settings.__file__).read_text(encoding="utf-8")))
    assert read == {"DATABASE_URL", "OPENAI_API_KEY", "OPENAI_BASE_URL", "EMBEDDING_MODEL", "ANSWER_MODEL", "JUDGE_MODEL",
                    "ALLOWED_HOSTS", "RERANK"}
    assert set(env_example()) == read


def test_env_example_defaults_match_settings():
    example = env_example()
    assert example["EMBEDDING_MODEL"] == settings.DEFAULT_EMBEDDING_MODEL
    assert example["ANSWER_MODEL"] == settings.DEFAULT_ANSWER_MODEL
    assert example["JUDGE_MODEL"] == settings.DEFAULT_JUDGE_MODEL
    assert example["ALLOWED_HOSTS"] == settings.DEFAULT_ALLOWED_HOSTS
    assert example["RERANK"] == settings.DEFAULT_RERANK == "on"


@pytest.mark.parametrize("value, on", [("", True), ("on", True), ("ON", True), ("off", False), (" Off ", False)])
def test_rerank_is_on_unless_set_off(monkeypatch, value, on):
    monkeypatch.setenv("RERANK", value)
    assert settings.rerank_on() is on


def test_any_other_rerank_value_is_a_startup_problem(monkeypatch):
    monkeypatch.setenv("RERANK", "maybe")
    with pytest.raises(RuntimeError, match="RERANK must be on or off"):
        settings.rerank_on()
    assert settings.startup_problems() == ["RERANK must be on or off; fix it in .env"]


def test_allowed_hosts_splits_the_list_and_defaults_to_localhost(monkeypatch):
    monkeypatch.setenv("ALLOWED_HOSTS", " docs.example.com , ,10.0.0.5 ")
    assert settings.allowed_hosts() == ["docs.example.com", "10.0.0.5"]
    monkeypatch.setenv("ALLOWED_HOSTS", "")
    assert settings.allowed_hosts() == ["localhost", "127.0.0.1"]


def test_startup_problems_name_each_missing_key(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    problems = settings.startup_problems()
    assert len(problems) == 2
    assert "DATABASE_URL is not set" in problems[0] and "OPENAI_API_KEY is not set" in problems[1]
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db.example.com:5432/postgres")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert settings.startup_problems() == []
