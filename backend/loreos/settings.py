"""Environment settings, read when used, never at import."""

import functools
import os
from pathlib import Path

from sqlalchemy.engine import make_url

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"  # the repo root's .env
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_ANSWER_MODEL = "gpt-5.4-mini"


@functools.cache
def _load_env_file() -> None:
    """Copy KEY=VALUE lines from the repo's .env into os.environ; a variable already set wins."""
    if not ENV_FILE.is_file():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and not key.lstrip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _env(name: str) -> str | None:
    _load_env_file()
    return os.environ.get(name, "").strip() or None


def database_url() -> str:
    """DATABASE_URL rewritten for the asyncpg driver."""
    raw = _env("DATABASE_URL")
    if not raw:
        raise RuntimeError("DATABASE_URL is not set; add the session pooler connection string to .env")
    url = make_url(raw)
    if url.port == 6543:
        raise RuntimeError(
            "DATABASE_URL uses port 6543, the transaction pooler, which breaks asyncpg's prepared statements; "
            "use the session pooler connection string (port 5432)"
        )
    return url.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False)


def openai_api_key() -> str:
    key = _env("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set; add it to .env")
    return key


def openai_base_url() -> str | None:
    return _env("OPENAI_BASE_URL")


def embedding_model() -> str:
    return _env("EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL


def answer_model() -> str:
    return _env("ANSWER_MODEL") or DEFAULT_ANSWER_MODEL
