"""HTTP API and the built UI: the hosts, Origin and body-size rules, health, the routers, then the UI fallback."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path, PurePath
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text
from starlette.datastructures import Headers
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.routing import Match
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from loreos import rerank, retrieval, settings, verify_rls
from loreos.db import engine
from loreos.routes import auth as auth_routes
from loreos.routes import documents, workspaces
from loreos.routes.documents import MAX_UPLOAD_BYTES

MAX_REQUEST_BYTES = MAX_UPLOAD_BYTES + 64 * 1024  # room for the multipart envelope around a file at the cap
TOO_LARGE = f"the request is over {MAX_UPLOAD_BYTES // (1024 * 1024)} MB; split the file or upload a smaller one"
# Every other request. FastAPI parses a JSON body before any dependency runs, so login, signup, invite accept and
# ask would otherwise parse up to the upload cap before an auth check or a rate limit.
MAX_BODY_BYTES = 64 * 1024
TOO_LARGE_BODY = f"the request is over {MAX_BODY_BYTES // 1024} KB; only a document upload may be larger"
UPLOAD = next(route for route in documents.router.routes if route.endpoint is documents.add_document)
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"  # the repo root's frontend build
WRITES = {"POST", "PUT", "PATCH", "DELETE"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("loreos.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Refuse to start, naming each missing or wrong setting, rather than fail on the first request (behaviour 19).

    Then verify_rls, as the worker does: a loreos_app that RLS does not bind would serve with only the app's filters.
    Last, the reranker model when the api serves with it, so a missing model stops startup, not the first question.
    The worker never searches, so it never loads it.
    """
    problems = settings.startup_problems() or await verify_rls.isolation_problems()
    if not problems and retrieval.serving_mode() == "hybrid_rerank":
        try:
            rerank.model()
        except RuntimeError as e:
            problems = [str(e)]
    for problem in problems:
        log.error(problem)
    if problems:
        raise RuntimeError("the api cannot start: " + "; ".join(problems))
    yield


app = FastAPI(title="LoreOS", lifespan=lifespan)


class BodyLimit:
    """413 past MAX_REQUEST_BYTES on the upload route, past MAX_BODY_BYTES on every other, read per request,
    whether or not the body declares its length.

    A declared Content-Length over the cap is refused before the app runs. A chunked body declares none, so
    receive is wrapped to count bytes as they arrive: past the cap it raises, and FastAPI's handler answers 413
    while the route is still reading, before anything is parsed or stored.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if UPLOAD.matches(scope)[0] is Match.FULL:  # the route's own path and method
            cap, too_large = MAX_REQUEST_BYTES, TOO_LARGE
        else:
            cap, too_large = MAX_BODY_BYTES, TOO_LARGE_BODY
        if int(Headers(scope=scope).get("content-length") or 0) > cap:
            return await JSONResponse({"detail": too_large}, status_code=413)(scope, receive, send)
        received = 0

        async def counted() -> Message:
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > cap:
                raise HTTPException(413, too_large)
            return message

        await self.app(scope, counted, send)


async def same_origin_writes(request: Request, call_next):
    """Behaviour 9: a write without an API key needs an Origin whose host:port is the Host it was sent to.

    Browsers send Origin on every POST, PUT, PATCH and DELETE, same-origin ones included, so a missing or
    "null" Origin is refused; P1 let a missing one through. Only a Bearer request is exempt: current_member
    then authenticates by the key alone and never reads the cookie, and another site's page cannot add an
    Authorization header without a CORS preflight, which this api never answers.
    """
    scheme = (request.headers.get("authorization") or "").partition(" ")[0]
    if request.method in WRITES and scheme.lower() != "bearer":
        origin = request.headers.get("origin")
        if origin is None or urlsplit(origin).netloc.lower() != request.headers.get("host", "").lower():
            return JSONResponse(
                {"detail": "cross-origin write refused: send it from this site's own pages, or with an API key"},
                status_code=403,
            )
    return await call_next(request)


# The last added runs first: the Host check, then the Origin rule, then the body limit.
app.add_middleware(BodyLimit)
app.add_middleware(BaseHTTPMiddleware, dispatch=same_origin_writes)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts())


def _field(loc: tuple) -> str:
    """('body', 'question') gives 'question'; a missing body stays 'body'."""
    return ".".join(str(part) for part in loc[1:] or loc)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Every error is {detail: str}; FastAPI's default list would reach the UI as the bare status text."""
    detail = "; ".join(f"{_field(error['loc'])}: {error['msg']}" for error in exc.errors())
    return JSONResponse({"detail": detail}, status_code=422)


@app.get("/api/health")
async def health() -> dict:
    """200 when the database answers; the compose healthcheck. Any failure is 503, logged by its class only."""
    try:
        async with engine().connect() as conn:
            await conn.execute(text("select 1"))
    except Exception as e:
        log.warning("health failed class=%s", type(e).__name__)
        raise HTTPException(503, "the database is not answering; check DATABASE_URL and that the database is up") from e
    return {"status": "ok"}


app.include_router(auth_routes.router)
app.include_router(workspaces.router)
app.include_router(documents.router)


@app.get("/{path:path}", include_in_schema=False)
async def ui(path: str) -> FileResponse:
    """The built UI, last: a file inside DIST, else index.html for the app's own routes. An api path gets a JSON 404.

    Starlette has already decoded the path, so %2e%2e arrives as "..". A path with a root, a drive or a ".." is
    refused before it touches the filesystem: on Windows, resolving \\\\host\\share dials out to that host. Then
    the resolved file must still be inside DIST, so a link inside the build cannot lead out of it either.
    """
    if path == "api" or path.startswith("api/"):
        raise HTTPException(404, "no such API route")
    dist = DIST.resolve()
    if not (dist / "index.html").is_file():
        raise HTTPException(404, "the UI is not built; run npm run build --prefix frontend")
    relative = PurePath(path)
    if not relative.anchor and ".." not in relative.parts:
        file = (dist / relative).resolve()
        if file.is_relative_to(dist) and file.is_file():
            return FileResponse(file)
    return FileResponse(dist / "index.html")
