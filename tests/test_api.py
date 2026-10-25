from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

from app.main import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1:8765", headers={"X-Local-AI": "1"}) as c:
        assert c.post("/api/setup", json={"passphrase": "correct horse battery staple"}).status_code == 200
        yield c


def test_csrf_host_and_lock(client):
    assert client.get("/api/tasks", headers={"Host": "evil.example"}).status_code == 403
    assert client.post("/api/tasks", json={"title": "bad"}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/tasks", json={"title": "bad"}, headers={"X-Local-AI": ""}).status_code == 403
    assert client.post("/api/lock").status_code == 200
    assert client.get("/api/tasks").status_code == 401


def test_crud_validation_and_timezone(client):
    item = client.post("/api/tasks", json={"title": "Finish algebra", "due": ""}).json()
    assert client.patch("/api/tasks/" + item["id"], json={"status": "done"}).json()["status"] == "done"
    assert client.post("/api/tasks", json={"title": "bad", "status": "invalid"}).status_code == 422
    assert client.post("/api/events", json={"title": "Class", "start": "2026-10-25T09:00:00", "end": "2026-10-25T10:00:00"}).status_code == 400
    event = client.post("/api/events", json={"title": "Class", "start": "2026-10-25T09:00:00+04:00", "end": "2026-10-25T10:00:00+04:00"})
    assert event.status_code == 200
    assert b"BEGIN:VCALENDAR" in client.get("/api/calendar/export").content


def test_chat_memory_opt_in_and_no_cloud_fallback(client):
    client.post("/api/memories", json={"text": "memory-canary"})
    client.patch("/api/settings", json={"use_memory": True})
    with patch("app.main.ai.generate", return_value="A local answer") as generate:
        response = client.post("/api/chat", json={"message": "Hello", "use_memory": False})
        assert response.status_code == 200
        assert "memory-canary" not in str(generate.call_args.args[1])
        response = client.post("/api/chat", json={"message": "Hello", "use_memory": True})
        assert response.json()["used_memory"]
        assert "memory-canary" in str(generate.call_args.args[1])
    with patch("app.main.ai.models", return_value=[]):
        assert client.post("/api/chat", json={"message": "Hello"}).status_code == 503


def test_summary_task_import_and_edit_invalidates(client):
    item = client.post("/api/notes", json={"title": "Meeting", "body": "Sultan will finish the report tomorrow."}).json()
    answer = '{"summary":"Report discussed.","decisions":[],"actions":["Sultan: finish report tomorrow"]}'
    with patch("app.main.ai.generate", return_value=answer):
        response = client.post(f"/api/notes/{item['id']}/summarize")
        assert response.status_code == 200
    assert len(client.post(f"/api/notes/{item['id']}/tasks").json()["created"]) == 1
    assert client.post(f"/api/notes/{item['id']}/tasks").json()["created"] == []
    response = client.patch(f"/api/notes/{item['id']}", json={"body": "Changed meeting details"})
    assert "summary" not in response.json()


def test_export_and_network_gate(client):
    vault = client.app.state.vault
    vault.put("mail_account", {"password": "credential-canary"})
    assert "credential-canary" not in client.get("/api/export").text
    assert client.post("/api/errands/research", json={"query": "DXB to LHR"}).status_code == 403


def test_deleting_chat_while_model_runs_does_not_resurrect_it(client):
    chat = client.post("/api/chats", json={"title": "Test"}).json()
    def generate(vault, messages):
        vault.delete("chat", chat["id"])
        return "Answer"
    with patch("app.main.ai.generate", side_effect=generate):
        result = client.post("/api/chat", json={"chat_id": chat["id"], "message": "Hello"})
    assert result.status_code == 404
    assert client.get("/api/chats").json() == []
