"""Background generation jobs so the interface never blocks. Progress values come from the real GA run."""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from database import session_scope
from database.models import User
from services.common import ServiceError
from services.generation_service import GenerationParams, PrecheckFailed, run_generation

log = logging.getLogger(__name__)


@dataclass
class Job:
    id: str
    status: str = "RUNNING"          # RUNNING | COMPLETED | FAILED | STOPPED
    started: float = field(default_factory=time.time)
    history: List[dict] = field(default_factory=list)
    latest: Dict = field(default_factory=dict)
    timetable_id: Optional[int] = None
    error: str = ""
    issues: list = field(default_factory=list)
    stop: threading.Event = field(default_factory=threading.Event)
    owner_id: Optional[int] = None


_jobs: Dict[str, Job] = {}
_lock = threading.Lock()


def start_job(actor: User, params: GenerationParams) -> Job:
    job = Job(id=uuid.uuid4().hex[:12], owner_id=actor.id)
    with _lock:
        _jobs[job.id] = job
    thread = threading.Thread(target=_work, args=(job, actor, params), daemon=True, name=f"gen-{job.id}")
    thread.start()
    return job


def _work(job: Job, actor: User, params: GenerationParams) -> None:
    def progress(row: dict) -> None:
        job.latest = row
        job.history.append(row)
    try:
        with session_scope() as s:
            outcome = run_generation(s, actor, params, progress=progress, should_stop=job.stop.is_set)
        job.timetable_id = outcome.timetable_id
        job.status = "STOPPED" if outcome.result.interrupted else "COMPLETED"
    except PrecheckFailed as exc:
        job.status, job.error, job.issues = "FAILED", str(exc), exc.issues
    except ServiceError as exc:
        job.status, job.error = "FAILED", str(exc)
    except Exception:  # noqa: BLE001
        log.exception("Unexpected generation job failure")
        job.status, job.error = "FAILED", "Generation failed unexpectedly. No timetable was saved."


def get_job(job_id: Optional[str]) -> Optional[Job]:
    return _jobs.get(job_id) if job_id else None
