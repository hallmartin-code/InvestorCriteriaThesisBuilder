"""Investor profile API: create, save with server-decided statuses and questions, notes uploads."""

from __future__ import annotations

import pytest
import yaml
from fastapi.testclient import TestClient

import app as web

CLEAR = ("RAILWAY_ENVIRONMENT", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_PROJECT_ID", "RAILWAY_VOLUME_MOUNT_PATH", "MAX_UPLOAD_MB")
PROFILE = "/api/investors/acme-capital/profile"
NOTES = "/api/investors/acme-capital/profile/notes"

COMPLETE_FIELDS = {
    "investor_type": {"status": "provided", "value": "fund"},
    "capital_available_usd": {"status": "provided", "value": 5_000_000},
    "check_size": {"status": "provided", "value": {"min_usd": 100_000, "max_usd": 250_000}},
    "follow_on_reserve_policy": {"status": "no_preference"},
    "return_objective": {"status": "provided", "value": {"text": "Return objective", "target_multiple": None, "target_irr_pct": None}},
    "liquidity_objective": {"status": "provided", "value": "Liquidity objective"},
    "time_horizon_years": {"status": "provided", "value": {"min": 7, "max": 10}},
    "prior_investments": {"status": "provided", "value": [], "affirmed_none": True},
    "stages": {"status": "provided", "value": ["Seed"]},
    "sectors": {"status": "provided", "value": [{"sector": "Sector A", "subsectors": ["Subsector 1"]}]},
    "geographies": {"status": "provided", "value": ["Region A"]},
    "ownership_target_pct": {"status": "no_preference"},
    "round_size": {"status": "provided", "value": {"min_usd": 1_000_000, "max_usd": 3_000_000}},
    "instruments_accepted": {"status": "provided", "value": ["SAFE"]},
    "minimum_traction": {"status": "no_preference"},
    "instant_no_filters": {"status": "provided", "value": ["Condition A"]},
    "thesis_notes": {"status": "no_preference"},
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    for name in CLEAR:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ICB_DATA_DIR", str(tmp_path / "investors"))
    with TestClient(web.app) as c:
        yield c


def create(client, slug="acme-capital", name="Acme Capital"):
    return client.post("/api/investors", json={"slug": slug, "name": name})


def document(fields, slug="acme-capital", name="Acme Capital"):
    return {"schema_version": 1, "slug": slug, "display_name": name, "fields": fields}


def asked(body):
    return {q["field"] for q in body["questions"]}


def test_create_and_list(client):
    assert client.get("/api/investors").json() == []
    response = create(client)
    assert response.status_code == 201
    assert response.json() == {"slug": "acme-capital", "name": "Acme Capital", "approved_pack": None,
                              "inputs_complete": False, "open_questions": 17}
    assert client.get("/api/investors").json() == [response.json()]


def test_list_reports_input_progress_so_screening_can_stay_closed(client):
    create(client)
    client.put(PROFILE, json=document({"investor_type": {"status": "provided", "value": "fund"}}))
    entry = client.get("/api/investors").json()[0]
    assert entry["inputs_complete"] is False and entry["open_questions"] == 16
    client.put(PROFILE, json=document(COMPLETE_FIELDS))
    entry = client.get("/api/investors").json()[0]
    assert entry["inputs_complete"] is True and entry["open_questions"] == 0


def test_duplicate_and_bad_slugs_are_rejected(client):
    create(client)
    assert create(client).status_code == 409
    for slug in ("Acme", "../etc", "-x", ""):
        response = create(client, slug=slug)
        assert response.status_code == 422, slug
        assert response.json()["error"]


def test_incomplete_profile_saves_with_questions(client, tmp_path):
    create(client)
    response = client.put(PROFILE, json=document({"investor_type": {"status": "provided", "value": "fund"}}))
    assert response.status_code == 200
    fields = asked(response.json())
    assert "investor_type" not in fields and "capital_available_usd" in fields and len(fields) == 16
    stored = yaml.safe_load((tmp_path / "investors" / "acme-capital" / "profile.yaml").read_text(encoding="utf-8"))
    assert stored["fields"]["investor_type"] == {"status": "provided", "value": "fund", "source": "intake"}
    assert stored["fields"]["capital_available_usd"]["status"] == "not_provided"


def test_client_cannot_mark_an_incomplete_field_provided(client):
    create(client)
    fields = {"check_size": {"status": "provided", "value": {"min_usd": 100_000, "max_usd": None}}}
    assert "check_size" in asked(client.put(PROFILE, json=document(fields)).json())
    saved = client.get(PROFILE).json()["fields"]["check_size"]
    assert saved["status"] == "not_provided"
    assert saved["value"] == {"min_usd": 100_000, "max_usd": None}


def test_complete_profile_has_no_questions_and_reports_issues(client):
    create(client)
    fields = dict(COMPLETE_FIELDS, capital_available_usd={"status": "provided", "value": 200_000})
    body = client.put(PROFILE, json=document(fields)).json()
    assert body["questions"] == []
    assert body["issues"] == ["The maximum check size is larger than the capital available."]


def test_prior_investment_rows_must_be_complete(client):
    create(client)
    fields = {"prior_investments": {"status": "provided", "value": [{"company": "Company A", "year": 2020}]}}
    body = client.put(PROFILE, json=document(fields)).json()
    question = next(q["question"] for q in body["questions"] if q["field"] == "prior_investments")
    assert question == "Complete investment 1 (stage, sector, check size, outcome)."


@pytest.mark.parametrize(("fields", "fragment"), [
    ({"investor_type": {"status": "no_preference"}}, "cannot be marked No preference"),
    ({"favourite_colour": {"status": "provided", "value": "x"}}, "Unknown profile fields"),
    ({"investor_type": {"status": "provided", "value": "hedge_fund"}}, "investor_type"),
    ({"stages": {"status": "provided", "value": ["Series Z"]}}, "stages"),
])
def test_invalid_documents_are_rejected(client, fields, fragment):
    create(client)
    response = client.put(PROFILE, json=document(fields))
    assert response.status_code == 422
    assert fragment in response.json()["error"]


def test_slug_mismatch_and_unknown_investor(client):
    create(client)
    assert client.put(PROFILE, json=document({}, slug="other")).status_code == 422
    assert client.put("/api/investors/nobody/profile", json=document({}, slug="nobody")).status_code == 404
    assert client.get("/api/investors/nobody/profile").status_code == 404
    assert client.get("/api/investors/Bad.Slug/profile").status_code == 404


def test_profile_before_any_save_is_an_empty_document(client):
    create(client)
    body = client.get(PROFILE).json()
    assert body["display_name"] == "Acme Capital" and body["fields"] == {}


def test_display_name_change_updates_the_list(client):
    create(client)
    client.put(PROFILE, json=document({}, name="Acme Capital Partners"))
    assert client.get("/api/investors").json()[0]["name"] == "Acme Capital Partners"


def test_notes_upload_checks_type_and_content(client, tmp_path):
    create(client)
    ok = client.post(NOTES, files=[("files", ("thesis.pdf", b"%PDF-1.7 test", "application/pdf")),
                                   ("files", ("notes.md", b"# Notes", "text/markdown"))])
    assert ok.status_code == 200
    assert ok.json()["files"] == ["notes.md", "thesis.pdf"]
    fake = client.post(NOTES, files=[("files", ("fake.pdf", b"not a pdf", "application/pdf"))])
    assert fake.status_code == 422 and "does not look like" in fake.json()["error"]
    assert client.post(NOTES, files=[("files", ("run.exe", b"MZ", "application/octet-stream"))]).status_code == 422
    traversal = client.post(NOTES, files=[("files", ("../../evil.txt", b"hi", "text/plain"))])
    assert traversal.status_code == 200 and traversal.json()["saved"] == ["evil.txt"]
    assert (tmp_path / "investors" / "acme-capital" / "notes" / "evil.txt").is_file()


def test_stored_notes_count_as_thesis_notes(client):
    create(client)
    client.post(NOTES, files=[("files", ("thesis.txt", b"text", "text/plain"))])
    assert "thesis_notes" not in asked(client.put(PROFILE, json=document({})).json())


def test_screening_routes_are_still_not_built(client):
    assert client.post("/api/investors/acme-capital/screen").status_code == 503
