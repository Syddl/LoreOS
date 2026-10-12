"""Documents and ask, under a workspace: add a file or a URL, list, get, delete (owner), and ask.

Every route runs in workspace_session, so RLS binds what it reads and writes. The worker processes what is
added here; nothing in this file spends.
"""

import uuid
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, StringConstraints, ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from starlette.datastructures import UploadFile

from loreos import answering, fetch_url, ingest, parsing
from loreos.auth import Member, current_member, require_owner
from loreos.db import workspace_session

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
BUSY = "the document is being processed; try again shortly"
LOCK_NOT_AVAILABLE = "55P03"  # the lock_timeout fired: the worker holds the row

router = APIRouter(prefix="/api/workspaces/{workspace_id}")
Reader = Annotated[Member, Depends(current_member)]
Owner = Annotated[Member, Depends(require_owner)]


class UrlRequest(BaseModel):
    url: str


class AskRequest(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


@contextmanager
def busy_is_409():
    """A row the worker is processing: its lock timeout answers 409 rather than a 500."""
    try:
        yield
    except DBAPIError as e:
        if getattr(e.orig, "sqlstate", None) == LOCK_NOT_AVAILABLE:
            raise HTTPException(409, BUSY) from e
        raise


@router.post("/documents", status_code=202)
async def add_document(request: Request, response: Response, member: Reader) -> ingest.Document:
    """A multipart `file`, or JSON {url}, stored as pending for the worker. The same file again is 200, as stored."""
    media_type = (request.headers.get("content-type") or "").partition(";")[0].strip().lower()
    if media_type == "application/json":
        return await _add_url(await request.body(), member.workspace_id)
    if media_type != "multipart/form-data":
        raise HTTPException(415, 'send a file as multipart/form-data in the field "file", or JSON {"url": "https://..."}')
    async with request.form(max_files=1) as form:
        file = form.get("file")
        if not isinstance(file, UploadFile):
            raise HTTPException(422, 'send the file in the multipart field "file"')
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        filename = PurePosixPath((file.filename or "upload").replace("\\", "/")).name
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "the file is over 20 MB; split it or upload a smaller file")
    try:
        parsing.kind_of(filename, data)
    except parsing.UnsupportedType as e:
        raise HTTPException(415, str(e)) from e
    async with workspace_session(member.workspace_id) as session:
        existing = await ingest.find_by_sha(session, member.workspace_id, ingest.sha256(data))
        document = await ingest.enqueue(session, member.workspace_id, filename, data)
    if existing and existing.status != "failed":
        response.status_code = 200
    return document


async def _add_url(body: bytes, workspace_id: uuid.UUID) -> ingest.Document:
    """Queued, or queued again, so the worker fetches it again. enqueue_url's lock_timeout lasts the whole session."""
    try:
        url = UrlRequest.model_validate_json(body).url
    except ValidationError as e:
        raise HTTPException(422, 'send JSON {"url": "https://..."} with the page\'s address') from e
    try:
        with busy_is_409():
            async with workspace_session(workspace_id) as session:
                return await ingest.enqueue_url(session, workspace_id, url)
    except fetch_url.Refused as e:
        raise HTTPException(422, str(e)) from e


@router.get("/documents")
async def list_documents(member: Reader) -> list[ingest.Document]:
    async with workspace_session(member.workspace_id) as session:
        return await ingest.list_documents(session, member.workspace_id)


@router.get("/documents/{document_id}")
async def get_document(document_id: uuid.UUID, member: Reader) -> ingest.Document:
    async with workspace_session(member.workspace_id) as session:
        document = await ingest.get_document(session, member.workspace_id, document_id)
    if document is None:
        raise HTTPException(404, "no such document")
    return document


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(document_id: uuid.UUID, member: Owner) -> Response:
    """The document and, by cascade, its chunks. Waits at most 2 s for the worker's row lock, then 409."""
    with busy_is_409():
        async with workspace_session(member.workspace_id) as session:
            await session.execute(ingest.LOCK_TIMEOUT)
            deleted = await session.scalar(
                text("delete from loreos.documents where id = :d and workspace_id = :w returning id"),
                {"d": document_id, "w": member.workspace_id},
            )
    if deleted is None:
        raise HTTPException(404, "no such document")
    return Response(status_code=204)


@router.post("/ask")
async def ask(body: AskRequest, member: Reader) -> dict:
    """Every Answer field, with `text` named `answer`: one mapping, so a field P3 adds reaches the client."""
    async with workspace_session(member.workspace_id) as session:
        result = await answering.answer(session, member.workspace_id, body.question)
    fields = asdict(result)
    fields["answer"] = fields.pop("text")
    return fields
