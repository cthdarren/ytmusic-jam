import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import create_app
from app.settings import Settings
from tests.conftest import OWNER, FakeYTM, join_url_token, login


def use_cookie(client: TestClient, value: str) -> None:
    """Swap identity; clear first so the server-set cookie doesn't shadow this one."""
    client.cookies.clear()
    client.cookies.set("jam_session", value)


def become_guest(client: TestClient) -> str:
    """Log in as owner, grab the join link, then swap to a guest session."""
    login(client)
    token = join_url_token(client)
    client.cookies.clear()
    r = client.get(f"/join/{token}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    return client.cookies["jam_session"]


def test_api_requires_session(anon_client):
    assert anon_client.get("/api/state").status_code == 401
    assert anon_client.get("/api/auth/me").status_code == 401
    assert anon_client.post("/api/queue", json={"input": "dQw4w9WgXcQ"}).status_code == 401


def test_ws_rejects_anon(anon_client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with anon_client.websocket_connect("/ws") as ws:
            ws.receive_json()
    assert exc.value.code == 4401


def test_login_success_sets_cookie_and_me_is_owner(anon_client):
    r = anon_client.post("/api/auth/login", json=OWNER)
    assert r.status_code == 200
    assert r.json() == {"role": "owner"}
    assert anon_client.get("/api/auth/me").json() == {"role": "owner"}
    assert anon_client.get("/api/state").status_code == 200


def test_login_wrong_password_401(anon_client):
    r = anon_client.post("/api/auth/login", json={"username": "me", "password": "nope"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Wrong username or password"
    assert "jam_session" not in anon_client.cookies


def test_login_cookie_not_secure_by_default(anon_client):
    header = anon_client.post("/api/auth/login", json=OWNER).headers["set-cookie"].lower()
    assert "httponly" in header
    assert "samesite=lax" in header
    assert "secure" not in header.replace("httponly", "")


def test_login_cookie_secure_when_configured(settings):
    settings.cookie_secure = True
    with TestClient(create_app(ytm=FakeYTM(), static_dir=None, settings=settings)) as c:
        header = c.post("/api/auth/login", json=OWNER).headers["set-cookie"].lower()
    assert "; secure" in header


def test_login_rate_limited_after_5_failures(anon_client):
    for _ in range(5):
        assert anon_client.post("/api/auth/login", json={**OWNER, "password": "x"}).status_code == 401
    assert anon_client.post("/api/auth/login", json=OWNER).status_code == 429


def test_logout_clears_session(client):
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/state").status_code == 401


def test_tampered_cookie_rejected(anon_client):
    use_cookie(anon_client, "not-a-real-signature")
    assert anon_client.get("/api/state").status_code == 401


def test_join_link_gives_guest_session(anon_client):
    become_guest(anon_client)
    assert anon_client.get("/api/auth/me").json() == {"role": "guest"}
    assert anon_client.get("/api/state").status_code == 200
    assert anon_client.post("/api/queue", json={"input": "dQw4w9WgXcQ"}).status_code == 200


def test_join_url_uses_request_host(client):
    url = client.get("/api/join").json()["url"]
    assert url.startswith("http://testserver/join/")


def test_join_link_keeps_owner_session(client):
    token = join_url_token(client)
    client.get(f"/join/{token}", follow_redirects=False)
    assert client.get("/api/auth/me").json() == {"role": "owner"}


def test_guest_cannot_view_or_reset_join(anon_client):
    become_guest(anon_client)
    assert anon_client.get("/api/join").status_code == 403
    assert anon_client.post("/api/join/reset").status_code == 403


def test_bad_join_token_redirects_invalid(anon_client):
    r = anon_client.get("/join/wrong-token", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/?join=invalid"
    assert "jam_session" not in anon_client.cookies


def test_reset_invalidates_guest_cookie(anon_client):
    guest_cookie = become_guest(anon_client)
    owner_cookie = login(anon_client)
    old_token = join_url_token(anon_client)
    new_url = anon_client.post("/api/join/reset").json()["url"]
    assert old_token not in new_url
    assert anon_client.get("/api/state").status_code == 200

    use_cookie(anon_client, guest_cookie)
    assert anon_client.get("/api/state").status_code == 401
    use_cookie(anon_client, owner_cookie)
    assert anon_client.get(f"/join/{old_token}", follow_redirects=False).headers["location"] == "/?join=invalid"


def test_reset_closes_guest_websockets(anon_client):
    guest_cookie = become_guest(anon_client)
    owner_cookie = login(anon_client)

    use_cookie(anon_client, guest_cookie)
    with anon_client.websocket_connect("/ws") as guest_ws:
        guest_ws.receive_json()
        use_cookie(anon_client, owner_cookie)
        with anon_client.websocket_connect("/ws") as owner_ws:
            owner_ws.receive_json()
            anon_client.post("/api/join/reset")
            with pytest.raises(WebSocketDisconnect) as exc:
                guest_ws.receive_json()
            assert exc.value.code == 4401
            anon_client.post("/api/queue", json={"input": "dQw4w9WgXcQ"})
            assert owner_ws.receive_json()["state"]["version"] == 1


def test_join_token_persists_across_app_instances(settings):
    with TestClient(create_app(ytm=FakeYTM(), static_dir=None, settings=settings)) as a:
        login(a)
        token_a = join_url_token(a)
    with TestClient(create_app(ytm=FakeYTM(), static_dir=None, settings=settings)) as b:
        login(b)
        assert join_url_token(b) == token_a


def test_missing_env_raises(monkeypatch):
    monkeypatch.setenv("JAM_USERNAME", "me")
    monkeypatch.delenv("JAM_PASSWORD", raising=False)
    monkeypatch.delenv("JAM_SECRET", raising=False)
    with pytest.raises(RuntimeError) as exc:
        Settings.from_env()
    assert "JAM_PASSWORD" in str(exc.value)
    assert "JAM_SECRET" in str(exc.value)


def test_settings_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("JAM_USERNAME", "me")
    monkeypatch.setenv("JAM_PASSWORD", "pw")
    monkeypatch.setenv("JAM_SECRET", "x" * 32)
    monkeypatch.setenv("JAM_COOKIE_SECURE", "true")
    monkeypatch.setenv("JAM_DATA_DIR", str(tmp_path))
    s = Settings.from_env()
    assert (s.username, s.password, s.cookie_secure, s.data_dir) == ("me", "pw", True, tmp_path)
