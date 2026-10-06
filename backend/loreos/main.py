"""HTTP API. P1 serves one workspace with no login on 127.0.0.1; every upload and question spends OpenAI money."""

import logging
import uuid
from pathlib import PurePosixPath
from typing import Annotated

from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, StringConstraints
from starlette.middleware.trustedhost import TrustedHostMiddleware

from loreos import answering, ingest, parsing
from loreos.db import workspace_session
from loreos.workspaces import DEFAULT_WORKSPACE_ID

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_REQUEST_BYTES = MAX_UPLOAD_BYTES + 64 * 1024  # room for the multipart envelope around a file at the cap
# P1 has no login, so only this machine may drive it: the Host check stops DNS rebinding, the Origin
# check stops another site's page from posting here. P4's login and deployment hosts replace this.
LOCAL_HOSTS = ["127.0.0.1", "localhost"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
app = FastAPI(title="LoreOS")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=LOCAL_HOSTS)


@app.middleware("http")
async def refuse_cross_origin_writes(request: Request, call_next):
    """A browser sends Origin on a cross-origin POST; curl and the TestClient send none.

    Same origin means the Origin's host:port is the Host the request was sent to, so a page on
    another local port (another dev server) is refused too. A body declared over the upload cap is
    refused here, before Starlette receives and spools it.
    """
    origin = request.headers.get("origin")
    if request.method not in ("GET", "HEAD") and origin is not None and urlsplit(origin).netloc != request.headers.get("host"):
        return JSONResponse({"detail": f"cross-origin request from {origin} refused"}, status_code=403)
    if int(request.headers.get("content-length") or 0) > MAX_REQUEST_BYTES:
        return JSONResponse({"detail": "the request is over 20 MB; split the file or upload a smaller one"}, status_code=413)
    return await call_next(request)


class AskRequest(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


@app.post("/api/documents")
async def upload_document(file: UploadFile, response: Response) -> ingest.Document:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "the file is over 20 MB; split it or upload a smaller file")
    filename = PurePosixPath((file.filename or "upload").replace("\\", "/")).name
    try:
        parsing.kind_of(filename, data)
    except parsing.UnsupportedType as e:
        raise HTTPException(415, str(e)) from e
    async with workspace_session(DEFAULT_WORKSPACE_ID) as session:
        existing = await ingest.find_by_sha(session, DEFAULT_WORKSPACE_ID, ingest.sha256(data))
        document = await ingest.ingest(session, DEFAULT_WORKSPACE_ID, filename, data)
    response.status_code = 200 if existing else 201
    return document


@app.get("/api/documents")
async def list_documents() -> list[ingest.Document]:
    async with workspace_session(DEFAULT_WORKSPACE_ID) as session:
        return await ingest.list_documents(session, DEFAULT_WORKSPACE_ID)


@app.get("/api/documents/{document_id}")
async def get_document(document_id: uuid.UUID) -> ingest.Document:
    async with workspace_session(DEFAULT_WORKSPACE_ID) as session:
        document = await ingest.get_document(session, DEFAULT_WORKSPACE_ID, document_id)
    if not document:
        raise HTTPException(404, "no such document")
    return document


@app.post("/api/ask")
async def ask(body: AskRequest) -> dict:
    async with workspace_session(DEFAULT_WORKSPACE_ID) as session:
        result = await answering.answer(session, DEFAULT_WORKSPACE_ID, body.question)
    return {
        "found": result.found,
        "answer": result.text,
        "reason": result.reason,
        "citations": jsonable_encoder(result.citations),
    }
