"""A small persistent job queue processed by one in-process worker thread.

Stands in for ARQ + Redis in the MVP: jobs live in the `jobs` table, so a restart loses nothing, and a single
FIFO worker guarantees a session review runs after that session's pending tag/evaluate jobs. Swapping in ARQ
later means replacing `enqueue` and `Worker` only; handlers stay the same."""

import logging
import threading
from collections.abc import Callable

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import Job

log = logging.getLogger("enki.jobs")

Handler = Callable[[Session, dict], None]
HANDLERS: dict[str, Handler] = {}
_wake = threading.Event()


def handler(kind: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn

    return register


def enqueue(db: Session, kind: str, payload: dict, session_id: int | None = None) -> Job:
    job = Job(kind=kind, payload=payload, session_id=session_id)
    db.add(job)
    db.commit()
    _wake.set()
    return job


def _claim_next() -> int | None:
    with SessionLocal() as db:
        job = db.scalars(select(Job).where(Job.status == "queued").order_by(Job.id).limit(1)).first()
        if job is None:
            return None
        job.status = "running"
        db.commit()
        return job.id


def _run(job_id: int) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        kind, payload = job.kind, dict(job.payload)
    try:
        with SessionLocal() as db:
            HANDLERS[kind](db, payload)
            db.commit()
        status, error = "done", None
    except Exception as e:  # a failed job must not kill the worker
        log.exception("job %s (%s) failed", job_id, kind)
        status, error = "failed", f"{type(e).__name__}: {e}"
    with SessionLocal() as db:
        db.execute(update(Job).where(Job.id == job_id).values(status=status, error=error))
        db.commit()


def run_pending() -> int:
    """Process every queued job synchronously. Used by tests and the offline demo."""
    n = 0
    while (job_id := _claim_next()) is not None:
        _run(job_id)
        n += 1
    return n


class Worker:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="enki-worker", daemon=True)

    def start(self) -> None:
        with SessionLocal() as db:  # jobs interrupted by a restart go back in the queue
            db.execute(update(Job).where(Job.status == "running").values(status="queued"))
            db.commit()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        _wake.set()
        self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            job_id = _claim_next()
            if job_id is None:
                _wake.wait(timeout=2)
                _wake.clear()
                continue
            _run(job_id)
