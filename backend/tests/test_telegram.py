import logging
import urllib.error

import anyio
import pytest
from fastapi import HTTPException

from app.models import QueueItem, RoomState, Track
from app.telegram import Pairings, TelegramAPI, TelegramBot, TelegramError

pytestmark = pytest.mark.anyio

TOKEN = "Tok3n_current"
LINK = "https://music.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeAPI:
    def __init__(self):
        self.sent = []  # (chat_id, text)

    def send_message(self, chat_id, text, reply_to=None):
        self.sent.append((chat_id, text))


def state_with(title, artist):
    item = QueueItem(track=Track(video_id="dQw4w9WgXcQ", title=title, artist=artist))
    return RoomState(played=[], now_playing=item, queue=[], is_playing=True, version=1)


class Jam:
    """Stands in for the app: the current invite token and add_link."""

    def __init__(self):
        self.token = TOKEN
        self.added = []  # (text, added_by)
        self.error = None

    async def add_link(self, text, added_by):
        self.added.append((text, added_by))
        if self.error:
            raise self.error
        return state_with("Never Gonna Give You Up", "Rick Astley")


@pytest.fixture
def setup(tmp_path):
    api, jam = FakeAPI(), Jam()
    bot = TelegramBot(api, Pairings(tmp_path / "telegram_users.json"), lambda: jam.token, jam.add_link)
    return bot, api, jam


def message(text, user=7, chat=7, chat_type="private", first_name="Sam"):
    return {"update_id": 1, "message": {"message_id": 3, "text": text, "chat": {"id": chat, "type": chat_type},
                                        "from": {"id": user, "first_name": first_name}}}


def replies(api):
    return [text for _, text in api.sent]


async def test_unpaired_user_is_asked_for_the_invite(setup):
    bot, api, jam = setup
    await bot.handle(message(LINK))
    assert replies(api) == ["Send me the jam's invite link first (ask the host for it)."]
    assert jam.added == []


async def test_invite_link_pairs_user(setup):
    bot, api, jam = setup
    await bot.handle(message(f"join here http://192.168.66.66:8000/join/{TOKEN}"))
    await bot.handle(message(LINK))
    assert replies(api) == [
        "You're in! Send me a YouTube or Spotify link to add it to the queue.",
        "Added “Never Gonna Give You Up” – Rick Astley",
    ]
    assert jam.added == [(LINK, "Sam")]


async def test_start_deep_link_pairs_user(setup):
    bot, api, _ = setup
    await bot.handle(message(f"/start {TOKEN}"))
    assert replies(api) == ["You're in! Send me a YouTube or Spotify link to add it to the queue."]


async def test_expired_invite_link_does_not_pair(setup):
    bot, api, jam = setup
    await bot.handle(message("http://192.168.66.66:8000/join/old_token"))
    await bot.handle(message(LINK))
    assert replies(api) == [
        "That invite link has expired — ask the host for a new one.",
        "Send me the jam's invite link first (ask the host for it).",
    ]
    assert jam.added == []


async def test_paired_user_link_is_added_and_named(setup):
    bot, api, jam = setup
    await bot.handle(message(f"/start {TOKEN}", first_name="A really long first name that goes on and on"))
    await bot.handle(message(f"this one pls {LINK} thanks", first_name="A really long first name that goes on and on"))
    assert jam.added == [(LINK, "A really long first name that goes on an")]
    assert replies(api)[-1] == "Added “Never Gonna Give You Up” – Rick Astley"


async def test_add_error_detail_is_replied(setup):
    bot, api, jam = setup
    await bot.handle(message(f"/start {TOKEN}"))
    jam.error = HTTPException(404, "Couldn't find that song on YouTube Music")
    await bot.handle(message("https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"))
    assert replies(api)[-1] == "Couldn't find that song on YouTube Music"


async def test_plain_text_gets_help(setup):
    bot, api, jam = setup
    await bot.handle(message(f"/start {TOKEN}"))
    await bot.handle(message("hello bot"))
    assert replies(api)[-1] == "Send me a YouTube or Spotify song link."
    assert jam.added == []


async def test_group_add_command(setup):
    bot, api, jam = setup
    await bot.handle(message(f"/start {TOKEN}"))
    await bot.handle(message(f"/add@jam_bot {LINK}", chat=-100, chat_type="supergroup"))
    assert jam.added == [(LINK, "Sam")]
    assert api.sent[-1] == (-100, "Added “Never Gonna Give You Up” – Rick Astley")


async def test_group_chatter_is_ignored(setup):
    bot, api, jam = setup
    await bot.handle(message(f"/start {TOKEN}"))
    sent = len(api.sent)
    await bot.handle(message("what are we listening to?", chat=-100, chat_type="group"))
    await bot.handle(message("lol", user=99, chat=-100, chat_type="group"))  # unpaired, no link: stay quiet
    assert len(api.sent) == sent


async def test_reset_link_revokes_telegram_users(setup):
    bot, api, jam = setup
    await bot.handle(message(f"/start {TOKEN}"))
    jam.token = "brand_new_token"  # host pressed Reset link
    await bot.handle(message(LINK))
    assert replies(api)[-1] == "Send me the jam's invite link first (ask the host for it)."
    assert jam.added == []


async def test_pairings_persist(tmp_path):
    path = tmp_path / "telegram_users.json"
    Pairings(path).pair(7, TOKEN)
    assert Pairings(path).token_for(7) == TOKEN
    assert Pairings(path).token_for(8) is None


def test_corrupt_pairings_file_starts_empty(tmp_path):
    path = tmp_path / "telegram_users.json"
    path.write_text("{oops")
    assert Pairings(path).token_for(7) is None


def test_api_errors_never_log_the_token(monkeypatch, caplog):
    secret = "123456:SECRET-bot-token"
    api = TelegramAPI(secret)

    def urlopen(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", None, None)

    monkeypatch.setattr("app.telegram.urllib.request.urlopen", urlopen)
    caplog.set_level(logging.DEBUG)
    with pytest.raises(TelegramError) as exc:
        api.call("getMe")
    assert exc.value.status == 401
    assert secret not in str(exc.value) and secret not in repr(exc.value.__cause__ or "")
    assert secret not in caplog.text

    def offline(request, timeout=None):
        raise urllib.error.URLError(f"failed to reach {request.full_url}")

    monkeypatch.setattr("app.telegram.urllib.request.urlopen", offline)
    with pytest.raises(TelegramError) as exc:
        api.call("getUpdates")
    assert exc.value.status is None
    assert secret not in str(exc.value)
    assert exc.value.__cause__ is None  # the original error (with the URL) isn't chained


def test_get_updates_sends_long_poll_params(monkeypatch):
    import json as _json

    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"ok": true, "result": []}'

    def urlopen(request, timeout=None):
        seen["body"] = _json.loads(request.data)
        seen["timeout"] = timeout
        seen["method"] = request.full_url.rsplit("/", 1)[1]
        return Response()

    monkeypatch.setattr("app.telegram.urllib.request.urlopen", urlopen)
    assert TelegramAPI("t").get_updates(offset=42, timeout=50) == []
    assert seen == {"method": "getUpdates", "timeout": 60,
                    "body": {"timeout": 50, "allowed_updates": ["message"], "offset": 42}}


class PollingAPI(FakeAPI):
    """Serves batches of updates, then errors, recording each getUpdates offset."""

    def __init__(self, batches):
        super().__init__()
        self.batches = list(batches)
        self.offsets = []

    def get_me(self):
        return {"username": "jam_bot"}

    def get_updates(self, offset, timeout):
        self.offsets.append(offset)
        if not self.batches:
            raise TelegramError("Telegram getUpdates failed (401)", 401)
        batch = self.batches.pop(0)
        if isinstance(batch, Exception):
            raise batch
        return batch


def update(update_id, text, user=7):
    u = message(text, user=user)
    u["update_id"] = update_id
    return u


async def test_offset_advances(tmp_path):
    api, jam = PollingAPI([[update(5, "hi"), update(6, "hey")], [update(9, "yo")]]), Jam()
    bot = TelegramBot(api, Pairings(tmp_path / "t.json"), lambda: jam.token, jam.add_link)
    await bot.run(sleep=lambda s: anyio.sleep(0))
    assert api.offsets == [None, 7, 10]
    assert bot.username == "jam_bot"


async def test_bad_token_stops_polling(tmp_path):
    api, jam = PollingAPI([]), Jam()
    bot = TelegramBot(api, Pairings(tmp_path / "t.json"), lambda: jam.token, jam.add_link)
    await bot.run(sleep=lambda s: anyio.sleep(0))  # returns instead of polling forever
    assert api.offsets == [None]


async def test_network_error_backs_off(tmp_path):
    errors = [TelegramError("Telegram getUpdates failed (network error)")] * 6
    api, jam = PollingAPI(errors + [TelegramError("conflict", 409)]), Jam()
    bot = TelegramBot(api, Pairings(tmp_path / "t.json"), lambda: jam.token, jam.add_link)
    waits = []

    async def sleep(seconds):
        waits.append(seconds)

    await bot.run(sleep=sleep)
    assert waits == [5, 10, 20, 40, 60, 60, 60]  # doubling, capped at 60; 409 waits 60


async def test_slow_add_does_not_block_next_update(tmp_path):
    import time

    jam = Jam()
    started = []

    async def slow_add(text, added_by):
        started.append(time.monotonic())
        await anyio.sleep(0.3)
        return state_with("Song", "Artist")

    pairings = Pairings(tmp_path / "t.json")
    pairings.pair(1, TOKEN)
    pairings.pair(2, TOKEN)
    api = PollingAPI([[update(1, LINK, user=1), update(2, LINK, user=2)]])
    bot = TelegramBot(api, pairings, lambda: jam.token, slow_add)
    await bot.run(sleep=lambda s: anyio.sleep(0))
    await anyio.sleep(0.5)
    assert len(started) == 2 and started[1] - started[0] < 0.2
    assert len(api.sent) == 2
