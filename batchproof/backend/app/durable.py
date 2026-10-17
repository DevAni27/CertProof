"""Optional durable exports on Temporal (https://temporal.io).

Off by default. Turn it on by setting CERTPROOF_TEMPORAL_ADDRESS (for example localhost:7233).

Why: a 1,000-certificate export is 40 chunks of Chromium work. If the browser crashes, the laptop
sleeps or the app is closed at chunk 31, a normal run starts again. Here each chunk is its own
Temporal activity with retries, finished chunks are saved to disk, and a restarted worker carries
on from the next chunk instead of from zero.

Privacy: the workflow only ever carries a project id, a content hash and chunk numbers. Recipient
names stay on this computer, in the checkpoint folder, which is deleted when the export finishes.

Run the pieces (three terminals):
    temporal server start-dev
    python -m backend.app.durable            # the worker
    python serve.py                          # the app, with CERTPROOF_TEMPORAL_ADDRESS=localhost:7233
"""
from __future__ import annotations

import asyncio
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.client import Client, WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError, CancelledError
from temporalio.worker import Worker

REFUSED = "ExportRefused"   # a problem retrying cannot fix (project not ready, project changed, bad PDF)


# ---- activities: plain functions that run on the worker, next to the data ------------------------

def _refuse(e) -> ApplicationError:
    return ApplicationError(getattr(e, "message", str(e)), getattr(e, "result", {}) or {}, type=REFUSED, non_retryable=True)


@activity.defn
def plan_export(pid: str) -> dict:
    from . import pipeline
    from .jobs import JobFailure
    try:
        return pipeline.plan_export(pid)
    except JobFailure as e:
        raise _refuse(e)


@activity.defn
def render_chunk(pid: str, intent_hash: str, chunk: int) -> int:
    from . import pipeline
    from .jobs import JobFailure
    try:
        pipeline.render_export_chunk(pid, intent_hash, chunk)
    except JobFailure as e:
        raise _refuse(e)
    return chunk


@activity.defn
def finalize_export(pid: str, intent_hash: str) -> dict:
    from . import pipeline
    from .jobs import JobCtx, JobFailure

    class _NoJob(JobCtx):                     # progress is reported by the workflow, not a job row
        def __init__(self):
            self.job_id, self.cancel = "-", threading.Event()

        def progress(self, done, total, msg=""):
            pass

    try:
        if pipeline.plan_export(pid)["intent_hash"] != intent_hash:
            raise JobFailure("The project changed while the export was running. Start it again.")
        return pipeline.run_export(pid, _NoJob(), checkpoint=True)
    except JobFailure as e:
        raise _refuse(e)


# ---- the workflow: the durable part --------------------------------------------------------------

@workflow.defn
class ExportWorkflow:
    def __init__(self) -> None:
        self.done, self.total = 0, 0

    @workflow.run
    async def run(self, pid: str) -> dict:
        once = RetryPolicy(maximum_attempts=1)
        retry = RetryPolicy(initial_interval=timedelta(seconds=2), backoff_coefficient=2.0, maximum_attempts=4,
                            non_retryable_error_types=[REFUSED])
        plan = await workflow.execute_activity(plan_export, pid, start_to_close_timeout=timedelta(minutes=2), retry_policy=once)
        ih, self.total = plan["intent_hash"], plan["chunks"]
        for ci in range(self.total):
            await workflow.execute_activity(render_chunk, args=[pid, ih, ci], start_to_close_timeout=timedelta(minutes=10),
                                            retry_policy=retry)
            self.done += 1
        return await workflow.execute_activity(finalize_export, args=[pid, ih], start_to_close_timeout=timedelta(minutes=15),
                                               retry_policy=retry)

    @workflow.query
    def progress(self) -> list[int]:
        return [self.done, self.total]


# ---- the app side: start a workflow and follow it from the normal job runner --------------------

def _settings():
    from .config import get_settings
    return get_settings()


async def _drive(pid: str, ctx) -> dict:
    from .jobs import JobFailure
    from .services.rendering.renderer import Cancelled
    s = _settings()
    try:
        client = await Client.connect(s.temporal_address)
    except Exception:
        raise JobFailure(f"Could not reach Temporal at {s.temporal_address}. Start it with: temporal server start-dev")
    handle = await client.start_workflow(ExportWorkflow.run, pid, id=f"certproof-export-{pid}-{uuid.uuid4().hex[:8]}",
                                         task_queue=s.temporal_task_queue)
    result = asyncio.ensure_future(handle.result())
    cancelled = False
    while True:
        done, _ = await asyncio.wait({result}, timeout=1.0)
        if done:
            break
        if ctx.cancel.is_set() and not cancelled:
            cancelled = True
            await handle.cancel()
        try:
            d, t = await handle.query(ExportWorkflow.progress)
            if t:
                ctx.progress(d, t + 1, f"Rendered {d} of {t} parts (durable)")
        except Exception:
            ctx.progress(0, 1, "Waiting for a worker (is `python -m backend.app.durable` running?)")
    try:
        return result.result()
    except WorkflowFailureError as e:
        cause = e.cause
        if isinstance(cause, CancelledError) or cancelled:
            raise Cancelled()
        inner = getattr(cause, "cause", cause)
        if isinstance(inner, ApplicationError) and inner.type == REFUSED:
            raise JobFailure(inner.message, (inner.details[0] if inner.details else {}))
        raise JobFailure("The export failed even after retries. See the Temporal UI for the reason.")


def run_export_durable(pid: str, ctx) -> dict:
    return asyncio.run(_drive(pid, ctx))


# ---- the worker: python -m backend.app.durable --------------------------------------------------

async def _worker() -> None:
    s = _settings()
    if not s.temporal_address:
        raise SystemExit("Set CERTPROOF_TEMPORAL_ADDRESS (for example localhost:7233) first.")
    client = await Client.connect(s.temporal_address)
    print(f"CertProof worker: queue '{s.temporal_task_queue}' on {s.temporal_address}   (Ctrl+C to stop)")
    with ThreadPoolExecutor(max_workers=2) as pool:
        await Worker(client, task_queue=s.temporal_task_queue, workflows=[ExportWorkflow],
                     activities=[plan_export, render_chunk, finalize_export], activity_executor=pool,
                     max_concurrent_activities=1).run()


if __name__ == "__main__":
    import sys
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(_worker())
