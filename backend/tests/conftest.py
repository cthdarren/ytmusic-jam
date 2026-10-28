import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import Track
from app.settings import Settings
from app.ytm import UpstreamError

OWNER = {"username": "me", "password": "pw"}


class FakeYTM:
    def search(self, query, kind="songs", limit=20):
        if query == "boom":
            raise UpstreamError("youtube is down")
        return [
            Track(video_id="aaaaaaaaaaa", title=f"{query} 1", artist="A"),
            Track(video_id="bbbbbbbbbbb", title=f"{query} 2", artist="B"),
        ]

    def get_track(self, video_id):
        if video_id == "missingvid0":
            raise LookupError("not found")
        return Track(video_id=video_id, title=f"T-{video_id}", artist="Artist")


@pytest.fixture
def settings(tmp_path):
    return Settings(username="me", password="pw", secret="s" * 32, data_dir=tmp_path)


def login(client: TestClient) -> str:
    r = client.post("/api/auth/login", json=OWNER)
    assert r.status_code == 200, r.text
    return client.cookies["jam_session"]


def join_url_token(client: TestClient) -> str:
    """Token from the owner's join link; `client` must hold an owner cookie."""
    return client.get("/api/join").json()["url"].rsplit("/join/", 1)[1]


@pytest.fixture
def anon_client(settings):
    with TestClient(create_app(ytm=FakeYTM(), static_dir=None, settings=settings)) as c:
        yield c


@pytest.fixture
def client(anon_client):
    """A client logged in as the owner."""
    login(anon_client)
    return anon_client
