import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.audio import AudioPaused, AudioUnavailable
from app.main import create_app
from app.models import Track
from app.settings import Settings
from app.ytm import UpstreamError

OWNER = {"username": "me", "password": "pw"}


class FakeYTM:
    def __init__(self):
        self.searches = []  # (query, kind, limit) per call
        self.results = None  # set to a list of Tracks to override the canned results

    def search(self, query, kind="songs", limit=20):
        self.searches.append((query, kind, limit))
        if self.results is not None:
            return self.results
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


class FakeDownloader:
    """Stands in for yt-dlp: writes `size` bytes as <id>.webm, records calls, can fail or be slow."""

    def __init__(self, size=100, fail=(), delay=0.0):
        self.size = size
        self.fail = set(fail)
        self.delay = delay
        self.calls = []
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0  # most downloads seen running at the same time
        self.paused = []  # downloads stopped through their cancel event

    def __call__(self, video_id, dest_dir, cookies_file, cancel=None):
        with self.lock:
            self.calls.append((video_id, cookies_file))
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            deadline = time.monotonic() + self.delay
            while time.monotonic() < deadline:
                if cancel is not None and cancel.is_set():
                    with self.lock:
                        self.paused.append(video_id)
                    raise AudioPaused(video_id)
                time.sleep(0.01)
        finally:
            with self.lock:
                self.active -= 1
        if video_id in self.fail:
            raise AudioUnavailable(f"{video_id} is unavailable")
        path = dest_dir / f"{video_id}.webm"
        path.write_bytes(bytes(range(256)) * (self.size // 256) + bytes(self.size % 256))
        return path

    def downloaded(self):
        with self.lock:
            return {vid for vid, _ in self.calls}


@pytest.fixture(autouse=True)
def fake_downloader(monkeypatch):
    """Never run the real yt-dlp in tests: every app gets this fake downloader."""
    fake = FakeDownloader(size=1000)
    monkeypatch.setattr("app.main.ytdlp_download", fake)
    return fake


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
def fake_ytm():
    return FakeYTM()


@pytest.fixture
def anon_client(settings, fake_ytm):
    with TestClient(create_app(ytm=fake_ytm, static_dir=None, settings=settings)) as c:
        yield c


@pytest.fixture
def client(anon_client):
    """A client logged in as the owner."""
    login(anon_client)
    return anon_client


def next_state(ws, limit=20):
    """Read websocket messages until a room "state" arrives (skipping "ready" updates)."""
    for _ in range(limit):
        msg = ws.receive_json()
        if msg["type"] == "state":
            return msg
    raise AssertionError("no state message")
