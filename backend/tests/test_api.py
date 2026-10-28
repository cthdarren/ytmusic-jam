ID = "dQw4w9WgXcQ"


def add(client, text, added_by=None):
    return client.post("/api/queue", json={"input": text, "added_by": added_by})


def test_search_returns_tracks(client):
    r = client.get("/api/search", params={"q": "daft punk"})
    assert r.status_code == 200
    assert [t["title"] for t in r.json()] == ["daft punk 1", "daft punk 2"]


def test_search_empty_query_returns_400(client):
    assert client.get("/api/search", params={"q": "   "}).status_code == 400


def test_search_upstream_error_returns_502(client):
    r = client.get("/api/search", params={"q": "boom"})
    assert r.status_code == 502
    assert "detail" in r.json()


def test_state_starts_empty(client):
    assert client.get("/api/state").json() == {
        "played": [], "now_playing": None, "queue": [], "is_playing": False, "version": 0}


def test_add_by_link_starts_playing(client):
    r = add(client, f"https://youtu.be/{ID}", "Sam")
    assert r.status_code == 200
    state = r.json()
    assert state["now_playing"]["track"]["video_id"] == ID
    assert state["now_playing"]["added_by"] == "Sam"
    assert state["is_playing"] is True


def test_add_invalid_link_returns_400(client):
    r = add(client, "https://music.youtube.com/playlist?list=PL123")
    assert r.status_code == 400
    assert r.json()["detail"] == "Not a YouTube link or video id"


def test_add_unknown_video_returns_404(client):
    assert add(client, "missingvid0").status_code == 404


def test_remove(client):
    add(client, "aaaaaaaaaaa")
    item = add(client, "bbbbbbbbbbb").json()["queue"][0]
    r = client.delete(f"/api/queue/{item['id']}")
    assert r.status_code == 200
    assert r.json()["queue"] == []


def test_remove_unknown_returns_404(client):
    assert client.delete("/api/queue/nope").status_code == 404


def test_move_reorders(client):
    for vid in ("aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc", "ddddddddddd"):
        state = add(client, vid).json()
    last = state["queue"][-1]
    r = client.post(f"/api/queue/{last['id']}/move", json={"to_index": 0})
    assert [i["track"]["video_id"] for i in r.json()["queue"]] == ["ddddddddddd", "bbbbbbbbbbb", "ccccccccccc"]


def test_move_unknown_returns_404(client):
    assert client.post("/api/queue/nope/move", json={"to_index": 0}).status_code == 404


def test_next_twice_with_same_expected_id_skips_once(client):
    for vid in ("aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"):
        state = add(client, vid).json()
    current = state["now_playing"]["id"]
    client.post("/api/player/next", json={"expected_item_id": current})
    state = client.post("/api/player/next", json={"expected_item_id": current}).json()
    assert state["now_playing"]["track"]["video_id"] == "bbbbbbbbbbb"
    assert [i["track"]["video_id"] for i in state["queue"]] == ["ccccccccccc"]


def test_set_playing(client):
    add(client, ID)
    assert client.post("/api/player/playing", json={"playing": False}).json()["is_playing"] is False


def test_ws_receives_state_on_connect_and_on_change(client):
    with client.websocket_connect("/ws") as ws:
        first = ws.receive_json()
        assert first["type"] == "state"
        assert first["state"]["version"] == 0
        add(client, ID)
        msg = ws.receive_json()
        assert msg["type"] == "state"
        assert msg["state"]["version"] > 0
        assert msg["state"]["now_playing"]["track"]["video_id"] == ID


def test_spa_fallback_serves_index_for_client_routes(tmp_path, settings):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.conftest import FakeYTM

    static = tmp_path / "dist"
    static.mkdir()
    (static / "index.html").write_text("<div id=root></div>")
    (static / "app.js").write_text("console.log(1)")
    with TestClient(create_app(ytm=FakeYTM(), static_dir=static, settings=settings)) as c:
        assert c.get("/host").text == "<div id=root></div>"
        assert c.get("/app.js").text == "console.log(1)"
        assert c.get("/api/nope").status_code == 404


def test_spa_index_not_cached_and_missing_assets_404(tmp_path, settings):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.conftest import FakeYTM

    static = tmp_path / "dist"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<div id=root></div>")
    with TestClient(create_app(ytm=FakeYTM(), static_dir=static, settings=settings)) as c:
        assert c.get("/host").headers["cache-control"] == "no-cache"
        assert c.get("/").headers["cache-control"] == "no-cache"
        assert c.get("/assets/index-OLDHASH.js").status_code == 404
        assert c.get("/favicon-missing.svg").status_code == 404


def ids(items):
    return [i["track"]["video_id"] for i in items]


def queue_three(client):
    """Queue a, b, c and advance twice so c plays with a, b played. Returns a's item id."""
    first = add(client, "aaaaaaaaaaa").json()["now_playing"]["id"]
    add(client, "bbbbbbbbbbb")
    add(client, "ccccccccccc")
    client.post("/api/player/next", json={"expected_item_id": first})
    second = client.get("/api/state").json()["now_playing"]["id"]
    client.post("/api/player/next", json={"expected_item_id": second})
    return first


def test_play_item_jumps_back(client):
    first = queue_three(client)
    r = client.post(f"/api/queue/{first}/play")
    assert r.status_code == 200
    state = r.json()
    assert state["played"] == []
    assert state["now_playing"]["track"]["video_id"] == "aaaaaaaaaaa"
    assert ids(state["queue"]) == ["bbbbbbbbbbb", "ccccccccccc"]
    assert state["is_playing"] is True


def test_play_unknown_returns_404(client):
    add(client, ID)
    r = client.post("/api/queue/nope/play")
    assert r.status_code == 404
    assert r.json()["detail"] == "That song is no longer in the queue"


def test_clear_is_owner_only(anon_client):
    from tests.conftest import login
    from tests.test_auth import become_guest, use_cookie

    guest_cookie = become_guest(anon_client)
    owner_cookie = login(anon_client)
    add(anon_client, ID)
    use_cookie(anon_client, guest_cookie)
    assert anon_client.post("/api/queue/clear").status_code == 403
    assert anon_client.get("/api/state").json()["now_playing"] is not None
    use_cookie(anon_client, owner_cookie)
    r = anon_client.post("/api/queue/clear")
    assert r.status_code == 200
    state = r.json()
    assert (state["played"], state["now_playing"], state["queue"]) == ([], None, [])


def test_clear_requires_session(anon_client):
    assert anon_client.post("/api/queue/clear").status_code == 401


def test_room_survives_app_restart(settings):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.conftest import FakeYTM, login

    with TestClient(create_app(ytm=FakeYTM(), static_dir=None, settings=settings)) as a:
        login(a)
        queue_three(a)
        before = a.get("/api/state").json()
    with TestClient(create_app(ytm=FakeYTM(), static_dir=None, settings=settings)) as b:
        login(b)
        after = b.get("/api/state").json()
    assert ids(after["played"]) == ids(before["played"]) == ["aaaaaaaaaaa", "bbbbbbbbbbb"]
    assert after["now_playing"]["id"] == before["now_playing"]["id"]
    assert after["is_playing"] is False


def test_ws_broadcasts_jump(client):
    first = queue_three(client)
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        client.post(f"/api/queue/{first}/play")
        assert ws.receive_json()["state"]["now_playing"]["id"] == first
