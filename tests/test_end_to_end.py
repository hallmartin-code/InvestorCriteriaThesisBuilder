"""The whole flow through the API with the model stubbed: inputs -> pack -> screening -> decision."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

import app as web
from icb.llm.client import ModelResult
from test_criteria import draft_data
from test_profile_api import COMPLETE_FIELDS
from test_screen import extraction_payload, make_pdf

SLUG = "acme-capital"
PROFILE = f"/api/investors/{SLUG}/profile"
ENV = ("RAILWAY_ENVIRONMENT", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_PROJECT_ID", "RAILWAY_VOLUME_MOUNT_PATH")


@pytest.fixture
def client(tmp_path, monkeypatch):
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ICB_DATA_DIR", str(tmp_path / "investors"))
    monkeypatch.setenv("ICB_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    def fake_call(**kwargs):
        data = draft_data() if kwargs["schema_name"] == "criteria_draft" else extraction_payload()
        return ModelResult(data=data, model="claude-opus-5", input_tokens=10, output_tokens=5, corrected=False)

    monkeypatch.setattr("icb.llm.client.call_json", fake_call)
    monkeypatch.setattr("icb.criteria.build.llm.call_json", fake_call)
    monkeypatch.setattr("icb.screen.extract.llm.call_json", fake_call)
    with TestClient(web.app) as c:
        yield c


def wait_for(client, job_id, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["state"] in {"done", "failed"}:
            return body
        time.sleep(0.05)
    raise AssertionError("the job did not finish")


def setup_investor(client, fields=None):
    client.post("/api/investors", json={"slug": SLUG, "name": "Acme Capital"})
    client.put(PROFILE, json={"schema_version": 1, "slug": SLUG, "display_name": "Acme Capital",
                              "fields": fields if fields is not None else COMPLETE_FIELDS})


def test_screening_needs_an_approved_pack_even_when_inputs_are_complete(client):
    setup_investor(client)
    response = client.post(f"/api/investors/{SLUG}/screen",
                           files=[("deck", ("deck.pdf", make_pdf(2), "application/pdf"))])
    assert response.status_code == 422
    assert "no approved Criteria Pack" in response.json()["error"]


def test_criteria_build_refuses_while_inputs_are_missing(client):
    setup_investor(client, fields={"investor_type": {"status": "provided", "value": "fund"}})
    response = client.post(f"/api/investors/{SLUG}/criteria/build")
    assert response.status_code == 422 and "still needed" in response.json()["error"]


def test_inputs_to_pack_to_scorecard_to_decision(client):
    setup_investor(client)

    build = client.post(f"/api/investors/{SLUG}/criteria/build")
    assert build.status_code == 200
    summary = wait_for(client, build.json()["job_id"])["result"]
    assert summary["version"] == 1 and summary["status"] == "draft"
    assert len(summary["factors"]) == 6 and summary["open_questions"] == []

    draft = client.get(f"/api/investors/{SLUG}/criteria/draft").json()
    assert draft["draft"]["advance_threshold"] == 3.5

    approved = client.post(f"/api/investors/{SLUG}/criteria/approve", json={}).json()
    assert approved["status"] == "approved" and approved["hash"]
    listed = client.get("/api/investors").json()[0]
    assert listed["approved_pack"] == {"version": 1, "hash": approved["hash"],
                                       "approved_at": approved["approved_at"]}

    screen = client.post(f"/api/investors/{SLUG}/screen",
                         files=[("deck", ("deck.pdf", make_pdf(3), "application/pdf"))], data={"email": "false"})
    assert screen.status_code == 200
    job = wait_for(client, screen.json()["job_id"])
    assert job["state"] == "done", job["error"]
    result = job["result"]
    assert result["decision"] == "ADVANCE" and result["rule"] == 4
    assert result["pack"]["hash"] == approved["hash"]

    job_id = screen.json()["job_id"]
    pdf = client.get(f"/api/jobs/{job_id}/pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    extraction = client.get(f"/api/jobs/{job_id}/json").json()
    assert extraction["decision"]["rule_sentence"].startswith("Rule 4:")

    override = client.post(f"/api/investors/{SLUG}/decisions", json={
        "job_id": job_id, "final_decision": "PASS", "reviewer_initials": "hm"})
    assert override.status_code == 422 and "reason" in override.json()["error"]

    recorded = client.post(f"/api/investors/{SLUG}/decisions", json={
        "job_id": job_id, "final_decision": "PASS", "reviewer_initials": "hm",
        "exception_reason": "The customer contracts are with a single related party."}).json()
    assert recorded["override"] is True and recorded["reviewer_initials"] == "HM"

    agreed = client.post(f"/api/investors/{SLUG}/decisions", json={
        "job_id": job_id, "final_decision": "ADVANCE", "reviewer_initials": "HM"}).json()
    assert agreed["override"] is False


def test_the_decision_log_records_every_step(client, tmp_path):
    setup_investor(client)
    wait_for(client, client.post(f"/api/investors/{SLUG}/criteria/build").json()["job_id"])
    client.post(f"/api/investors/{SLUG}/criteria/approve", json={})
    job_id = client.post(f"/api/investors/{SLUG}/screen",
                         files=[("deck", ("deck.pdf", make_pdf(2), "application/pdf"))]).json()["job_id"]
    wait_for(client, job_id)
    client.post(f"/api/investors/{SLUG}/decisions", json={
        "job_id": job_id, "final_decision": "ADVANCE", "reviewer_initials": "HM"})

    log = (tmp_path / "investors" / SLUG / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(log) == 2
    assert '"type": "screening"' in log[0] and '"type": "decision"' in log[1]
