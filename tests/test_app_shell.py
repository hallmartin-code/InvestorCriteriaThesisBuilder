"""Deployable web shell: password gate, health check, config injection, public icons."""

from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

import app as web

AUTH = ("ten", "secret")
ENV_VARS = (
    "RAILWAY_ENVIRONMENT", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_PROJECT_ID", "RAILWAY_VOLUME_MOUNT_PATH",
    "APP_PASSWORD", "APP_USERNAME", "ANTHROPIC_API_KEY", "RESEND_API_KEY", "ICB_REPORT_EMAIL_TO", "ICB_DATA_DIR",
)


@pytest.fixture
def client(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APP_PASSWORD", "secret")
    with TestClient(web.app) as c:
        yield c


def test_page_requires_login(client):
    assert client.get("/").status_code == 401
    assert client.get("/", auth=("ten", "wrong")).status_code == 401
    assert client.get("/", auth=AUTH).status_code == 200


def test_railway_without_password_refuses_everything_but_health(client, monkeypatch):
    monkeypatch.delenv("APP_PASSWORD")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
    response = client.get("/")
    assert response.status_code == 503
    assert response.json() == {"error": "Set APP_PASSWORD before using this deployment."}
    assert client.get("/api/investors").status_code == 503
    assert client.get("/healthz").status_code == 200


def test_config_is_injected_and_cannot_break_out_of_script(client, monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("ICB_REPORT_EMAIL_TO", "</script><b>@example.com")
    page = client.get("/", auth=AUTH).text
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
    assert body["auth_enabled"] is True and body["api_key_set"] is True
    assert body["analysis_available"] is False
    assert "sentinel" not in response.text


def test_data_dir_is_persistent_only_on_a_volume(client, monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
    monkeypatch.setenv("ICB_DATA_DIR", "/data/investors")
    assert client.get("/healthz").json()["data_dir_persistent"] is False
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", "/data")
    assert client.get("/healthz").json()["data_dir_persistent"] is True


def test_icons_load_without_login(client):
    page = client.get("/", auth=AUTH).text
    hrefs = re.findall(r'<link rel="(?:icon|apple-touch-icon)"[^>]*href="([^"]+)"', page)
    assert hrefs
    for href in [*hrefs, "favicon.ico"]:
        response = client.get("/" + href)
        assert response.status_code == 200, href
        assert response.content[:4] in (b"\x00\x00\x01\x00", b"\x89PNG"), href
    manifest = client.get("/public/site.webmanifest").json()
    for icon in manifest["icons"]:
        assert client.get("/public/" + icon["src"]).content[:4] == b"\x89PNG", icon["src"]


def test_api_answers_not_built_behind_login(client):
    assert client.get("/api/investors").status_code == 401
    response = client.get("/api/investors", auth=AUTH)
    assert response.status_code == 503
    assert "not deployed yet" in response.json()["error"]
