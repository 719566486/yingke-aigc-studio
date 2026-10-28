import secrets
import uuid
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app import share


@pytest.fixture
def sharing(tmp_path, monkeypatch):
    monkeypatch.setattr(share, "DB", tmp_path / "share.sqlite3")
    monkeypatch.setattr(share, "share_code", lambda: "invitation-for-tests")
    data = {"jobs": {}, "calls": []}

    async def backend(method, path, *, body=None, files=None, params=None):
        data["calls"].append((method, path, body))
        if path == "/api/bootstrap":
            return {"token": "CORE_ONLY_SECRET", "capabilities": {"ffmpeg": True, "tts": True, "kling": True, "voices": ["zf_001"], "llm": True, "data_directory": "PRIVATE_PATH"}, "retention_hours": 72}
        if method == "POST" and path == "/api/jobs":
            old = next((j for j in data["jobs"].values() if j["key"] == body["idempotency"]), None)
            if old:
                return old
            job = {"id": uuid.uuid4().hex, "key": body["idempotency"], "mode": body["mode"], "status": "queued"}
            data["jobs"][job["id"]] = job
            return job
        if path == "/api/jobs":
            return {"jobs": list(data["jobs"].values())}
        if path.startswith("/api/jobs/"):
            return data["jobs"].get(path.split("/")[3], {})
        if method == "POST" and path == "/api/uploads":
            return {"id": uuid.uuid4().hex, "url": "/image"}
        if path == "/api/plan":
            return {"title": "test"}
        raise AssertionError((method, path))

    monkeypatch.setattr(share, "core", backend)
    return data


def login(client):
    response = client.post("/api/share/login", json={"code": "invitation-for-tests"})
    assert response.status_code == 200
    return {"X-Studio-Token": client.get("/api/bootstrap").json()["token"]}


def submission(key=None, mode="kling"):
    return {"idempotency": key or uuid.uuid4().hex, "mode": mode, "paid_consent": True, "plan": {"title": "visitor story"}}


def test_direct_entry_preserves_session_and_quota(sharing):
    with TestClient(share.app) as client:
        response = client.post("/api/share/start")
        assert response.status_code == 200
        assert "HttpOnly" in response.headers["set-cookie"]
        cookie = client.cookies.get(share.COOKIE)
        token = client.get("/api/bootstrap").json()["token"]
        headers = {"X-Studio-Token": token}
        assert client.post("/api/jobs", headers=headers, json=submission()).status_code == 200
        assert client.post("/api/share/start").status_code == 200
        assert client.cookies.get(share.COOKIE) == cookie
        assert client.get("/api/bootstrap").json()["token"] == token
        assert client.post("/api/jobs", headers=headers, json=submission()).status_code == 429


def test_direct_entry_keeps_origin_and_ownership_checks(sharing):
    with TestClient(share.app) as first, TestClient(share.app) as second:
        assert first.post("/api/share/start", headers={"Origin": "https://other.example"}).status_code == 403
        assert first.post("/api/share/start").status_code == 200
        assert second.post("/api/share/start").status_code == 200
        token = first.get("/api/bootstrap").json()["token"]
        assert "CORE_ONLY_SECRET" not in first.get("/api/bootstrap").text
        made = first.post("/api/jobs", headers={"X-Studio-Token": token}, json=submission()).json()
        assert second.get("/api/jobs/" + made["id"]).status_code == 404
        assert second.get("/api/settings").status_code == 403


def test_legacy_login_validates_code_and_never_returns_admin_token(sharing):
    with TestClient(share.app) as client:
        assert client.get("/api/bootstrap").status_code == 401
        assert client.post("/api/share/login", json={"code": "wrong-code"}).status_code == 401
        response = client.post("/api/share/login", json={"code": "invitation-for-tests"})
        assert "HttpOnly" in response.headers["set-cookie"]
        bootstrap = client.get("/api/bootstrap")
        assert "CORE_ONLY_SECRET" not in bootstrap.text
        assert "PRIVATE_PATH" not in bootstrap.text
        assert bootstrap.json()["capabilities"]["llm"] is False


def test_public_settings_are_blocked(sharing):
    with TestClient(share.app) as client:
        h = login(client)
        for method, path in [("GET", "/api/settings"), ("PUT", "/api/settings"), ("POST", "/api/settings/check-kling")]:
            assert client.request(method, path, headers=h, json={}).status_code == 403
        assert not any("settings" in path for _, path, _ in sharing["calls"])


def test_csrf_and_origin_are_enforced(sharing):
    with TestClient(share.app) as client:
        h = login(client)
        assert client.post("/api/jobs", json=submission()).status_code == 403
        assert client.post("/api/jobs", headers={**h, "Origin": "https://other.example"}, json=submission()).status_code == 403


def test_guest_can_only_see_their_jobs(sharing):
    with TestClient(share.app) as first, TestClient(share.app) as second:
        h1, h2 = login(first), login(second)
        made = first.post("/api/jobs", headers=h1, json=submission()).json()
        assert first.get("/api/jobs/" + made["id"]).status_code == 200
        assert second.get("/api/jobs").json()["jobs"] == []
        assert second.get("/api/jobs/" + made["id"]).status_code == 404
        assert second.get("/api/jobs/" + made["id"] + "/file/video").status_code == 404
        assert second.delete("/api/jobs/" + made["id"], headers=h2).status_code == 404


def test_repeat_submission_does_not_create_another_paid_job(sharing):
    with TestClient(share.app) as client:
        h = login(client)
        body = submission()
        first = client.post("/api/jobs", headers=h, json=body).json()
        second = client.post("/api/jobs", headers=h, json=body).json()
        assert first["id"] == second["id"]
        assert len([1 for method, path, _ in sharing["calls"] if method == "POST" and path == "/api/jobs"]) == 1
        assert client.post("/api/jobs", headers=h, json=submission()).status_code == 429


def test_activity_daily_budget_is_shared_across_guests(sharing, monkeypatch):
    monkeypatch.setattr(share, "DAILY_LIMIT", 1)
    with TestClient(share.app) as first, TestClient(share.app) as second:
        h1, h2 = login(first), login(second)
        assert first.post("/api/jobs", headers=h1, json=submission()).status_code == 200
        assert second.post("/api/jobs", headers=h2, json=submission()).status_code == 429


def test_uploads_are_bound_to_their_guest(sharing):
    with TestClient(share.app) as first, TestClient(share.app) as second:
        h1, h2 = login(first), login(second)
        uploaded = first.post("/api/uploads", headers=h1, files={"image": ("test.png", b"fake", "image/png")}).json()
        body = submission()
        body["reference_id"] = uploaded["id"]
        assert second.post("/api/jobs", headers=h2, json=body).status_code == 404


def test_visitors_cannot_attach_arbitrary_provider_tasks(sharing):
    with TestClient(share.app) as client:
        h = login(client)
        made = client.post("/api/jobs", headers=h, json=submission()).json()
        response = client.post("/api/jobs/" + made["id"] + "/resume", headers=h, json={"provider_id": "someone-elses-task"})
        assert response.status_code == 403


def test_additional_text_model_spending_is_not_public(sharing):
    with TestClient(share.app) as client:
        h = login(client)
        assert client.post("/api/plan", headers=h, json={"use_llm": True}).status_code == 400


def test_portal_health_discloses_no_keys(sharing):
    with TestClient(share.app) as client:
        response = client.get("/api/share/ping")
        assert response.json() == {"online": True}
        assert response.headers["access-control-allow-origin"] == "*"
        assert "CORE_ONLY_SECRET" not in response.text


def test_public_cookie_is_secure_even_behind_http_relay(sharing):
    with TestClient(share.app, base_url="http://visitor.lhr.life") as client:
        response = client.post("/api/share/login", json={"code": "invitation-for-tests"})
        assert response.status_code == 200
        assert "Secure" in response.headers["set-cookie"]
