import json
import re
from pathlib import Path

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
    assert read == {"DATABASE_URL", "OPENAI_API_KEY", "OPENAI_BASE_URL", "EMBEDDING_MODEL", "ANSWER_MODEL"}
    assert set(env_example()) == read


def test_env_example_model_defaults_match_settings():
    example = env_example()
    assert example["EMBEDDING_MODEL"] == settings.DEFAULT_EMBEDDING_MODEL
    assert example["ANSWER_MODEL"] == settings.DEFAULT_ANSWER_MODEL
