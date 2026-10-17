"""Durable (Temporal) export. There is no Temporal server in the test environment, so these tests cover what
the workflow is made of: the activities run in workflow order, resume after a simulated crash, refuse
correctly, and the workflow definition is valid under Temporal's sandbox. A live server run is manual."""
import io

import pdfplumber
import pytest

pytest.importorskip("temporalio")
from temporalio.exceptions import ApplicationError  # noqa: E402

from backend.app import durable, pipeline  # noqa: E402
from tests.conftest import export_ok, make_project, pdf_bytes, wait_job  # noqa: E402

ROWS = [{"name": f"Person {i:02d} Example", "organisation": "Test Org", "award": "", "recipient_id": f"{i:03d}"} for i in range(1, 31)]


def pages_text(pdf):
    with pdfplumber.open(io.BytesIO(pdf)) as p:
        return [(pg.extract_text() or "") for pg in p.pages]


def test_activities_resume_after_a_crash_and_match_a_normal_export(client, monkeypatch):
    pid = make_project(client, ROWS)
    _, normal = export_ok(client, pid)                      # reference: the ordinary single-process export

    plan = durable.plan_export(pid)
    assert plan["chunks"] == 2 and len(plan["intent_hash"]) == 64
    durable.render_chunk(pid, plan["intent_hash"], 0)
    cp = pipeline.checkpoint_path(pid, plan["intent_hash"])
    assert (cp / "chunk_0.pdf").is_file() and (cp / "chunk_0.json").is_file() and not (cp / "chunk_1.json").exists()

    # "crash": the worker dies here. A new worker repeats the plan and carries on with the next chunk only.
    assert durable.plan_export(pid) == plan
    durable.render_chunk(pid, plan["intent_hash"], 1)
    durable.render_chunk(pid, plan["intent_hash"], 0)       # a retried chunk is a cheap no-op

    # every chunk is on disk, so finishing must not need a browser at all
    import playwright.sync_api as pw
    monkeypatch.setattr(pw, "sync_playwright", lambda: (_ for _ in ()).throw(AssertionError("browser launched again")))
    res = durable.finalize_export(pid, plan["intent_hash"])
    assert res["pages"] == 30 and res["completion"] == normal["report"]["completion"] == "checked"
    assert res["counts"] == normal["report"]["counts"]
    assert not cp.exists()                                  # names on disk are removed when the export is done

    arts = client.get(f"/api/projects/{pid}/artifacts").json()
    art = next(a for a in arts if a["id"] == res["artifact_id"])
    got = pages_text(client.get(f"/api/projects/{pid}/artifacts/{art['id']}/pdf").content)
    want = pages_text(pdf_bytes(client, pid, normal))
    assert got == want and len(got) == 30                   # identical certificates, in the same order


def test_refusals_are_not_retried(client):
    empty = client.post("/api/projects", json={"title": "x"}).json()["id"]
    with pytest.raises(ApplicationError) as e:
        durable.plan_export(empty)
    assert e.value.type == durable.REFUSED and e.value.non_retryable
    pid = make_project(client, ROWS[:3])
    with pytest.raises(ApplicationError) as e:
        durable.render_chunk(pid, "0" * 64, 0)              # the project is not the version that was planned
    assert e.value.type == durable.REFUSED and e.value.non_retryable
    with pytest.raises(ApplicationError):
        durable.finalize_export(pid, "0" * 64)


def test_workflow_definition_is_valid_in_temporals_sandbox():
    from temporalio import workflow
    from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner
    defn = workflow._Definition.must_from_class(durable.ExportWorkflow)
    assert defn.name == "ExportWorkflow" and "progress" in defn.queries
    import asyncio

    async def go():
        SandboxedWorkflowRunner().prepare_workflow(defn)   # re-imports the module under the sandbox restrictions
    asyncio.run(go())


def test_durable_mode_is_off_by_default_and_fails_clearly_without_a_server(client, monkeypatch):
    pid = make_project(client, ROWS[:3])
    export_ok(client, pid)                                  # no CERTPROOF_TEMPORAL_ADDRESS: the normal path
    monkeypatch.setenv("CERTPROOF_TEMPORAL_ADDRESS", "127.0.0.1:9")
    r = client.post(f"/api/projects/{pid}/export")
    j = wait_job(client, r.json()["job_id"], timeout=120)
    assert j["status"] == "failed" and "Could not reach Temporal" in j["message"] and "temporal server start-dev" in j["message"]
