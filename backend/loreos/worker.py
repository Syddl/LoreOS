"""The background worker: npm run paid:worker (python -m loreos.worker). It claims queued documents, processes them
and retries failures. Embedding calls OpenAI, so every run costs money.

One document at a time:
- claim: one `for update skip locked` statement in system_session takes the oldest due pending row, or a processing
  row whose lease ran out (counted as a transient failure; the third count fails it without processing);
- process: ingest.run_stages inside the document's workspace_session, which holds the row lock until it commits;
- record: a failure is classified, then written in a new system_session, fenced on the claim's lease, so a worker
  whose transaction was killed meanwhile writes nothing on a row another claim holds.
"""

import asyncio
import logging
import signal
import sys

import openai
from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from loreos import fetch_url, ingest, llm, parsing, settings, verify_rls
from loreos.db import system_session, workspace_session

log = logging.getLogger("loreos.worker")

LEASE = 600  # seconds. Only recovers a crashed worker: a live one holds the row lock, so the lease is never extended
POLL_S = 2
BACKOFF_S = (30, 120)  # before the second and the third attempt
MAX_ATTEMPTS = 3
SYSTEMIC_PAUSE_S = 300
LEASE_ERROR = "lease: transient: the worker stopped before finishing (lease expired)"
PERMANENT_ERRORS = (parsing.UnsupportedType, parsing.ParseError, fetch_url.Refused, fetch_url.TooLarge, fetch_url.UnsupportedContent)
SYSTEMIC_ERRORS = (openai.AuthenticationError, openai.PermissionDeniedError, openai.NotFoundError, llm.EmbeddingDimensionError)

CLAIM = text(
    """
    with due as (
        select id, status = 'processing' as expired, status = 'processing' and attempts + 1 >= :max_attempts as final
        from loreos.documents
        where (status = 'pending' and (next_attempt_at is null or next_attempt_at <= now()))
           or (status = 'processing' and locked_until <= now())
        order by created_at
        limit 1
        for update skip locked
    )
    update loreos.documents d
    set attempts = d.attempts + cast(due.expired as int),
        error = case when due.expired then :lease_error else d.error end,
        status = case when due.final then 'failed' else 'processing' end,
        locked_until = case when due.final then null else clock_timestamp() + make_interval(secs => :lease) end,
        next_attempt_at = null
    from due
    where d.id = due.id
    returning d.id, d.workspace_id, d.status, d.attempts, d.locked_until, due.expired
    """
)
RECORD = text(
    "update loreos.documents set status = :status, attempts = attempts + :counted, error = :error, "
    "next_attempt_at = clock_timestamp() + make_interval(secs => :delay), locked_until = null "
    "where id = :d and workspace_id = :w and locked_until = :claimed_lease"
)
RELEASE = text(
    "update loreos.documents set status = 'pending', next_attempt_at = null, locked_until = null where id = :d "
    "and workspace_id = :w and locked_until = :claimed_lease"
)
DELETE_CHUNKS = text("delete from loreos.chunks where document_id = :d and workspace_id = :w")
LOST = "worker lost document=%s: another claim holds it, so nothing was written"


def classify(exc: BaseException) -> str:
    """permanent, systemic or transient, by exception class, HTTP status and error code; never by message."""
    if isinstance(exc, PERMANENT_ERRORS):
        return "permanent"
    if isinstance(exc, fetch_url.HTTPStatus):
        return "permanent" if 400 <= exc.status < 500 else "transient"
    if isinstance(exc, openai.BadRequestError):
        return "systemic" if exc.code == "model_not_found" else "permanent"
    if isinstance(exc, SYSTEMIC_ERRORS) or (isinstance(exc, openai.RateLimitError) and exc.code == "insufficient_quota"):
        return "systemic"
    # Class 42 (42501 insufficient privilege, a missing table or column) and 3F (a missing schema): a grant or a
    # migration to fix, not the document.
    if isinstance(exc, DBAPIError) and (getattr(exc.orig, "sqlstate", None) or "")[:2] in ("42", "3F"):
        return "systemic"
    # Bounded by MAX_ATTEMPTS: other rate limits, OpenAI 5xx, timeouts and connection errors, HTTP 5xx, TimeoutError,
    # httpx2.TransportError, OSError, a lost database connection, and anything unclassified.
    return "transient"


async def claim() -> Row | None:
    """Claim the oldest due document under a new lease; None when nothing is due. A third expired lease fails it here."""
    async with system_session() as conn:
        params = {"max_attempts": MAX_ATTEMPTS, "lease": LEASE, "lease_error": LEASE_ERROR}
        claimed = (await conn.execute(CLAIM, params)).one_or_none()
        if claimed and claimed.status == "failed":  # failed always drops the chunks: search does not filter by status
            await conn.execute(DELETE_CHUNKS, {"d": claimed.id, "w": claimed.workspace_id})
    return claimed


async def record_failure(claimed: Row, stage: str, klass: str, error: BaseException) -> None:
    """Write the failure on the row while it still holds this claim's lease; a stale worker writes nothing."""
    counted = klass != "systemic"  # a systemic failure is the deployment's, so the document keeps its attempts
    attempts = claimed.attempts + counted
    if klass == "permanent" or attempts >= MAX_ATTEMPTS:
        status, delay = "failed", None
    else:
        status, delay = "pending", (BACKOFF_S[attempts - 1] if counted else SYSTEMIC_PAUSE_S)
    ids = {"d": claimed.id, "w": claimed.workspace_id}
    message = ingest.scrub(f"{stage}: {klass}: {type(error).__name__}: {error}")
    params = {**ids, "claimed_lease": claimed.locked_until, "status": status, "counted": int(counted), "delay": delay, "error": message}
    async with system_session() as conn:
        written = (await conn.execute(RECORD, params)).rowcount
        if written and status == "failed":
            await conn.execute(DELETE_CHUNKS, ids)
    if not written:
        log.warning(LOST, claimed.id)


async def release(claimed: Row) -> None:
    """Back to pending, uncounted, for the next start to take; fenced like a failure record."""
    async with system_session() as conn:
        params = {"d": claimed.id, "w": claimed.workspace_id, "claimed_lease": claimed.locked_until}
        written = (await conn.execute(RELEASE, params)).rowcount
    if not written:
        log.warning(LOST, claimed.id)


async def run_once() -> str | None:
    """Claim and process one document: processed, permanent, transient or systemic; None when nothing was due."""
    claimed = await claim()
    if claimed is None:
        return None
    if claimed.expired:
        log.warning("worker failed document=%s stage=lease class=transient", claimed.id)
    if claimed.status == "failed":
        return "transient"
    log.info("worker claimed document=%s", claimed.id)
    try:
        async with workspace_session(claimed.workspace_id) as session:
            # A killed or hung worker's row lock is freed within one lease.
            await session.execute(text(f"set local idle_in_transaction_session_timeout = '{LEASE}s'"))
            count = await ingest.run_stages(session, claimed.workspace_id, claimed.id)
    except (asyncio.CancelledError, KeyboardInterrupt):
        await release(claimed)
        log.info("worker released document=%s", claimed.id)
        raise
    except Exception as e:  # classified below; a StageError carries the stage, anything else failed around the stages
        stage, error = (e.stage, e.__cause__) if isinstance(e, ingest.StageError) else ("store", e)
        klass = classify(error)
        log.warning("worker failed document=%s stage=%s class=%s", claimed.id, stage, klass)
        await record_failure(claimed, stage, klass, error)
        return klass
    log.info("worker processed document=%s chunks=%d", claimed.id, count)
    return "processed"


async def serve() -> None:
    """Process until stopped: poll every POLL_S while idle, and pause SYSTEMIC_PAUSE_S after a systemic failure."""
    if sys.platform != "win32":  # docker compose stop sends SIGTERM; cancelling releases the claim as Ctrl-C does
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, asyncio.current_task().cancel)
    while True:
        try:
            result = await run_once()
        except (SQLAlchemyError, OSError) as e:  # the database, during a claim or a record: wait, then carry on
            log.error("worker database error: %s: %s", type(e).__name__, getattr(e, "orig", None) or e)
            result = None
        if result == "systemic":
            log.warning("worker paused class=systemic seconds=%d", SYSTEMIC_PAUSE_S)
            await asyncio.sleep(SYSTEMIC_PAUSE_S)
        elif result is None:
            await asyncio.sleep(POLL_S)


async def _rls_problems() -> list[str]:
    async with system_session() as conn:
        return await verify_rls.problems(conn)


def main() -> int:
    """Check the settings, then the grants, before any claim; exit 1 naming each problem."""
    # Without the grant check, a missing grant fails every store after the embedding is paid for.
    if problems := settings.startup_problems() or asyncio.run(_rls_problems()):
        for problem in problems:
            print(f"worker: {problem}", file=sys.stderr)
        return 1
    try:
        asyncio.run(serve())
    except (asyncio.CancelledError, KeyboardInterrupt):  # SIGTERM or Ctrl-C; the claim in hand was released
        log.info("worker stopped")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    sys.exit(main())
