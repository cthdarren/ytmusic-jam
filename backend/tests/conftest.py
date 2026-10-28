import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import Track
from app.ytm import UpstreamError


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
def client():
    with TestClient(create_app(ytm=FakeYTM(), static_dir=None)) as c:
        yield c
