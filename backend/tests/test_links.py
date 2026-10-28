import pytest

from app.links import parse_video_id

ID = "dQw4w9WgXcQ"


@pytest.mark.parametrize("text", [
    ID, f"  {ID}  ",
    f"https://www.youtube.com/watch?v={ID}",
    f"https://m.youtube.com/watch?feature=share&v={ID}",
    f"https://music.youtube.com/watch?v={ID}&list=RDAMVM{ID}",
    f"https://youtu.be/{ID}?si=abc123",
    f"https://www.youtube.com/shorts/{ID}",
    f"https://www.youtube.com/embed/{ID}",
    f"youtube.com/watch?v={ID}",
])
def test_parses_valid(text):
    assert parse_video_id(text) == ID


@pytest.mark.parametrize("text", [
    "", "hello world", "https://music.youtube.com/playlist?list=PL123",
    "https://example.com/watch?v=dQw4w9WgXcQ", "https://youtu.be/short",
])
def test_rejects_invalid(text):
    assert parse_video_id(text) is None
