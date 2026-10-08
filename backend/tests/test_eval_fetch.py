"""eval:fetch against a local HTTP server: a file lands only after its sha256 matches, and a good file is never fetched again."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from loreos.evaluation.fetch import corpus_problems, fetch
from loreos.ingest import sha256

BODY = b"# Handbook\n\nBody text.\n"
FILE = "handbook/values.md"


@pytest.fixture
def server():
    """Serves .files (url path -> bytes) and 404s anything else; .requests records every path asked for."""
    state = SimpleNamespace(files={}, requests=[])

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state.requests.append(self.path)
            body = state.files.get(self.path)
            if body is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    state.base = f"http://127.0.0.1:{httpd.server_port}"
    yield state
    httpd.shutdown()
    httpd.server_close()


def manifest(*files: dict) -> dict:
    return {"sources": [], "files": list(files)}


def served(server, file: str, body: bytes, digest: str | None = None) -> dict:
    """A manifest entry for a file the server holds; digest overrides the true sha256."""
    server.files[f"/{file}"] = body
    return {"file": file, "url": f"{server.base}/{file}", "sha256": digest or sha256(body)}


def files_under(path) -> list:
    return [p for p in path.rglob("*") if p.is_file()]


def test_a_good_file_is_written(server, tmp_path):
    assert fetch(manifest(served(server, FILE, BODY)), tmp_path) == []
    assert (tmp_path / FILE).read_bytes() == BODY
    assert files_under(tmp_path) == [tmp_path / FILE]


def test_a_wrong_sha256_fails_naming_the_file_and_leaves_nothing(server, tmp_path):
    expected = "0" * 64
    problems = fetch(manifest(served(server, FILE, BODY, digest=expected)), tmp_path)
    assert len(problems) == 1
    assert FILE in problems[0] and expected in problems[0] and sha256(BODY) in problems[0]
    assert files_under(tmp_path) == []


def test_a_404_fails_naming_the_file_and_leaves_nothing(server, tmp_path):
    entry = {"file": FILE, "url": f"{server.base}/gone.md", "sha256": sha256(BODY)}
    problems = fetch(manifest(entry), tmp_path)
    assert len(problems) == 1
    assert FILE in problems[0] and "404" in problems[0] and entry["url"] in problems[0]
    assert files_under(tmp_path) == []


def test_one_bad_file_does_not_stop_the_others(server, tmp_path):
    bad = {"file": "handbook/gone.md", "url": f"{server.base}/gone.md", "sha256": sha256(BODY)}
    problems = fetch(manifest(bad, served(server, FILE, BODY)), tmp_path)
    assert len(problems) == 1 and "handbook/gone.md" in problems[0]
    assert (tmp_path / FILE).read_bytes() == BODY


def test_a_second_fetch_makes_no_request(server, tmp_path):
    files = manifest(served(server, FILE, BODY))
    assert fetch(files, tmp_path) == []
    assert fetch(files, tmp_path) == []
    assert server.requests == [f"/{FILE}"]


def test_a_path_outside_the_corpus_is_refused_with_no_request(server, tmp_path):
    corpus = tmp_path / "corpus"
    problems = fetch(manifest(served(server, "../escape.md", BODY)), corpus)
    assert len(problems) == 1 and "../escape.md" in problems[0]
    assert server.requests == []
    assert files_under(tmp_path) == []


def test_corpus_problems_names_a_missing_and_a_changed_file(tmp_path):
    (tmp_path / "good.md").write_bytes(BODY)
    (tmp_path / "changed.md").write_bytes(BODY + b"edited\n")
    files = manifest(
        {"file": "good.md", "url": "http://unused.invalid/good.md", "sha256": sha256(BODY)},
        {"file": "changed.md", "url": "http://unused.invalid/changed.md", "sha256": sha256(BODY)},
        {"file": "missing.md", "url": "http://unused.invalid/missing.md", "sha256": sha256(BODY)},
    )
    problems = corpus_problems(files, tmp_path)
    assert len(problems) == 2
    assert "changed.md" in problems[0] and "missing.md" in problems[1]
    assert all("npm run eval:fetch" in p for p in problems)
