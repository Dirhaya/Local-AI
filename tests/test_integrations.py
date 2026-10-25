"""Protocol and privacy regression tests; no real accounts or network access."""
from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import integrations as module
from app.deps import get_vault


class FakeVault:
    def __init__(self, network=False):
        self.records = {}
        self.config = {"network_enabled": network, "speech_model_path": ""}

    def list(self, kind):
        return list(self.records.get(kind, {}).values())

    def get(self, kind, key):
        return self.records.get(kind, {}).get(key)

    def put(self, kind, value):
        value = dict(value)
        value.setdefault("id", f"{kind}_{len(self.records.get(kind, {}))}")
        self.records.setdefault(kind, {})[value["id"]] = value
        return value

    def delete(self, kind, key):
        return self.records.get(kind, {}).pop(key, None) is not None

    def settings(self):
        return dict(self.config)

    def check_unlocked(self):
        pass


@pytest.fixture
def client():
    app = FastAPI()
    vault = FakeVault()
    app.include_router(module.router)
    app.dependency_overrides[get_vault] = lambda: vault
    with TestClient(app) as value:
        yield value, vault


ACCOUNT = {
    "label": "Personal", "email": "sultan@example.com", "username": "sultan@example.com",
    "imap_host": "imap.example.com", "smtp_host": "smtp.example.com", "password": "app-secret",
}


def test_account_responses_do_not_return_secrets_and_blank_updates_preserve_them(client):
    http, vault = client
    response = http.post("/api/mail/accounts", json=ACCOUNT)
    assert response.status_code == 200
    account = response.json()
    assert account["has_password"] is True
    assert "app-secret" not in response.text
    assert "password" not in account and "oauth_token" not in account
    assert "app-secret" not in http.get("/api/mail/accounts").text
    updated = http.post("/api/mail/accounts", json=ACCOUNT | {"id": account["id"], "password": ""})
    assert updated.status_code == 200
    assert vault.get("mail_account", account["id"])["password"] == "app-secret"
    changed = http.post("/api/mail/accounts", json=ACCOUNT | {"id": account["id"], "password": "", "smtp_host": "other.example.com"})
    assert changed.status_code == 400


def test_mail_headers_and_tls_ports_are_validated():
    with pytest.raises(ValidationError):
        module.SendMail(account_id="x", to="sultan@example.com\r\nBcc: other@example.com", body="test")
    with pytest.raises(ValidationError):
        module.SendMail(account_id="x", to="sultan@example.com", subject="hello\nBcc: extra", body="test")
    with pytest.raises(ValidationError):
        module.MailAccount(**(ACCOUNT | {"smtp_port": 25}))
    with pytest.raises(ValidationError):
        module.MailAccount(**(ACCOUNT | {"imap_port": 143}))


def test_send_needs_confirmation_and_network_toggle(client, monkeypatch):
    http, vault = client
    account = http.post("/api/mail/accounts", json=ACCOUNT).json()
    sent = []
    monkeypatch.setattr(module, "deliver_mail", lambda account, data: sent.append(data.to))
    body = {"account_id": account["id"], "to": "friend@example.com", "subject": "Hello", "body": "Test"}
    assert http.post("/api/mail/send", json=body).status_code == 400
    assert http.post("/api/mail/send", json=body | {"confirm": True}).status_code == 403
    assert not sent
    vault.config["network_enabled"] = True
    assert http.post("/api/mail/send", json=body | {"confirm": True}).json() == {"sent": True}
    assert sent == ["friend@example.com"]


def test_mail_sync_deduplicates_and_cached_search_needs_no_network(client, monkeypatch):
    http, vault = client
    account = http.post("/api/mail/accounts", json=ACCOUNT).json()
    raw = b"Subject: Flight reservation\r\nFrom: airline@example.com\r\nTo: sultan@example.com\r\nDate: Tue, 01 Sep 2026 10:00:00 +0400\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nBooking reference DXB123."
    message = module.parse_mail(raw, account, "123", "456")
    monkeypatch.setattr(module, "fetch_mail", lambda account, limit, guard=None: [message])
    assert http.post("/api/mail/sync", json={"account_id": account["id"]}).status_code == 403
    vault.config["network_enabled"] = True
    for _ in range(2):
        assert http.post("/api/mail/sync", json={"account_id": account["id"]}).json()["synced"] == 1
    vault.config["network_enabled"] = False
    assert len(http.get("/api/mail?q=dxb123").json()) == 1
    assert http.get("/api/mail?q=unmatched").json() == []
    http.delete(f"/api/mail/accounts/{account['id']}")
    assert http.get("/api/mail").json() == []


def test_html_email_is_inert_plain_text():
    raw = b'''Subject: Offer\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<html><style>hide</style><script>exfiltrate()</script><p>Visible offer</p><img src="https://tracker.example.com/open"></html>'''
    item = module.parse_mail(raw, {"id": "a"}, "1", "0")
    assert item["body"] == "Visible offer"
    assert "<" not in item["body"]


def test_fetch_mail_uses_readonly_and_peek(monkeypatch):
    calls = []
    class FakeIMAP:
        def __init__(self, host, port, **kwargs):
            assert port == 993 and kwargs["ssl_context"].check_hostname
        def login(self, username, password):
            pass
        def select(self, name, readonly):
            calls.append(("select", readonly))
            return "OK", []
        def response(self, name):
            return name, [b"99"]
        def uid(self, action, *args):
            calls.append((action, args))
            if action == "search":
                return "OK", [b"1 2 3"]
            return "OK", [(b"header", b"Subject: test\r\n\r\nbody")]
        def logout(self):
            calls.append(("logout",))
    monkeypatch.setattr(module.imaplib, "IMAP4_SSL", FakeIMAP)
    result = module.fetch_mail(ACCOUNT | {"id": "a"}, limit=2)
    assert len(result) == 2
    assert calls[0] == ("select", True)
    fetch_calls = [entry for entry in calls if entry[0] == "fetch"]
    assert len(fetch_calls) == 2 and "BODY.PEEK[]" in fetch_calls[0][1][1]
    assert calls[-1] == ("logout",)


ICS = b'''BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//EN\r\nBEGIN:VEVENT\r\nUID:event-1\r\nDTSTART:20261025T100000\r\nDTEND:20261025T110000\r\nSUMMARY:Study session\r\nDESCRIPTION:Bring notes\r\nEND:VEVENT\r\nBEGIN:VEVENT\r\nUID:event-2\r\nDTSTART;VALUE=DATE:20261026\r\nDTEND;VALUE=DATE:20261027\r\nSUMMARY:Study day\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n'''


def test_ics_import_applies_floating_timezone_and_roundtrips_all_day(client):
    http, vault = client
    response = http.post("/api/calendar/import", files={"file": ("events.ics", ICS, "text/calendar")})
    assert response.status_code == 200 and response.json()["imported"] == 2
    events = vault.list("event")
    study = next(item for item in events if item["title"] == "Study session")
    assert study["start"] == "2026-10-25T10:00:00+04:00"
    assert any(item["all_day"] for item in events)
    http.post("/api/calendar/import", files={"file": ("events.ics", ICS)})
    assert len(vault.list("event")) == 2
    exported = http.get("/api/calendar/export")
    assert exported.status_code == 200 and "text/calendar" in exported.headers["content-type"]
    imported, warnings = module.parse_ics(exported.content)
    assert len(imported) == 2 and any(item["all_day"] for item in imported)


def test_recurring_import_creates_distinct_occurrences():
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y%m%dT100000Z")
    content = f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:repeat\r\nDTSTART:{tomorrow}\r\nDURATION:PT1H\r\nRRULE:FREQ=DAILY;COUNT=3\r\nSUMMARY:Daily study\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n".encode()
    events, warnings = module.parse_ics(content)
    assert len(events) == 3
    assert len({item["id"] for item in events}) == 3
    assert warnings and "365 days" in warnings[0]


def test_caldav_rejects_private_urls_and_does_not_reuse_credentials_for_changed_url(client, monkeypatch):
    http, vault = client
    vault.config["network_enabled"] = True
    vault.put("calendar_account", {"id": "caldav", "url": "https://calendar.example.com/old/", "username": "u", "password": "secret"})
    assert "secret" not in http.get("/api/calendar/config").text
    request = {"url": "https://calendar.example.com/new/", "username": "u", "password": ""}
    assert http.post("/api/calendar/sync", json=request).status_code == 400


def test_speech_never_downloads_model(tmp_path, monkeypatch):
    (tmp_path / "model.bin").write_bytes(b"model")
    captures = []
    fake_module = types.ModuleType("faster_whisper")
    class FakeWhisper:
        def __init__(self, path, **kwargs):
            captures.append((path, kwargs))
        def transcribe(self, path, **kwargs):
            return iter([types.SimpleNamespace(text="Hello Sultan")]), types.SimpleNamespace(language="en")
    fake_module.WhisperModel = FakeWhisper
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)
    monkeypatch.setattr(module, "_speech_models", {})
    result = module.transcribe_audio(tmp_path / "input.wav", str(tmp_path))
    assert result == {"text": "Hello Sultan", "language": "en"}
    assert captures[0][1]["local_files_only"] is True
    assert captures[0][1]["device"] == "cpu"


def test_transcription_deletes_temporary_audio_on_error(client, monkeypatch):
    http, vault = client
    vault.config["speech_model_path"] = "/downloaded/model"
    paths = []
    def fail(path, model_path, language):
        paths.append(path)
        assert path.exists()
        raise HTTPException(400, "Invalid audio")
    monkeypatch.setattr(module, "transcribe_audio", fail)
    response = http.post("/api/transcribe", files={"file": ("recording.wav", b"audio", "audio/wav")})
    assert response.status_code == 400
    assert paths and not paths[0].exists()


def test_empty_files_are_rejected(client):
    http, _ = client
    assert http.post("/api/calendar/import", files={"file": ("empty.ics", b"")}).status_code == 400
