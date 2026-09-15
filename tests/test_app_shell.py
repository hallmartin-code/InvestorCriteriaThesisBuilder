"""Deployable web shell: open access, health check, config injection, public icons."""

from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

import app as web

ENV_VARS = (
    "RAILWAY_ENVIRONMENT", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_PROJECT_ID", "RAILWAY_VOLUME_MOUNT_PATH",
    "APP_PASSWORD", "APP_USERNAME", "ANTHROPIC_API_KEY", "RESEND_API_KEY", "ICB_REPORT_EMAIL_TO", "ICB_DATA_DIR",
)


@pytest.fixture
def client(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    with TestClient(web.app) as c:
        yield c


def test_page_is_open_without_sign_in(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "WWW-Authenticate" not in response.headers


def test_open_on_railway_even_if_a_password_variable_lingers(client, monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
    monkeypatch.setenv("APP_PASSWORD", "left-over")
    assert client.get("/").status_code == 200
    assert client.get("/api/jobs/example").status_code == 503  # not built yet, but not a login wall


def test_config_is_injected_and_cannot_break_out_of_script(client, monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("ICB_REPORT_EMAIL_TO", "</script><b>@example.com")
    page = client.get("/").text
    assert "{{CONFIG_JSON}}" not in page
    raw = re.search(r'<script id="app-config" type="application/json">(.*?)</script>', page, re.S).group(1)
    assert "</script>" not in raw
    config = json.loads(raw)
    assert config["email_enabled"] is True
    assert config["email_to"] == "</script><b>@example.com"
    assert "preview" not in config


def test_health_reports_state_without_secrets(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-sentinel-value")
    response = client.get("/healthz")
    body = response.json()
    assert response.status_code == 200
    assert body["api_key_set"] is True
    assert body["analysis_available"] is False
    assert "auth_enabled" not in body
    assert "sentinel" not in response.text


def test_data_dir_is_persistent_only_on_a_volume(client, monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
    monkeypatch.setenv("ICB_DATA_DIR", "/data/investors")
    assert client.get("/healthz").json()["data_dir_persistent"] is False
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", "/data")
    assert client.get("/healthz").json()["data_dir_persistent"] is True


def test_icons_are_referenced_and_load(client):
    page = client.get("/").text
    hrefs = re.findall(r'<link rel="(?:icon|apple-touch-icon)"[^>]*href="([^"]+)"', page)
    assert hrefs
    for href in [*hrefs, "favicon.ico"]:
        response = client.get("/" + href)
        assert response.status_code == 200, href
        assert response.content[:4] in (b"\x00\x00\x01\x00", b"\x89PNG"), href
    manifest = client.get("/public/site.webmanifest").json()
    for icon in manifest["icons"]:
        assert client.get("/public/" + icon["src"]).content[:4] == b"\x89PNG", icon["src"]


def test_api_answers_not_built(client):
    response = client.get("/api/jobs/example")
    assert response.status_code == 503
    assert "not deployed yet" in response.json()["error"]
