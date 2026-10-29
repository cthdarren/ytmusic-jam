"""Telegram bot: friends send a YouTube or Spotify link and it's queued.

Access works like the web invite: a user sends the bot the jam's invite link (or opens the
bot's deep link) once, and stays allowed while that invite is current. Reset link in the
app therefore signs Telegram users out too.

The bot long-polls Telegram, so the home server needs no public address. The token is part
of every request URL, so errors are reported by method and status only.
"""

import json
import logging
import os
import re
import tempfile
import urllib.error
import urllib.request
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import anyio
from fastapi import HTTPException

from app.models import RoomState

log = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"
JOIN_TOKEN_RE = re.compile(r"/join/([A-Za-z0-9_-]+)")
START_TOKEN_RE = re.compile(r"^/start(?:@\w+)?\s+([A-Za-z0-9_-]+)")
ADD_COMMAND_RE = re.compile(r"^/add(?:@\w+)?\b\s*")
LINK_RE = re.compile(r"\S*(?:youtube\.com/|youtu\.be/|open\.spotify\.com/|spotify:track:)\S*")

ASK_FOR_INVITE = "Send me the jam's invite link first (ask the host for it)."
INVITE_EXPIRED = "That invite link has expired — ask the host for a new one."
PAIRED = "You're in! Send me a YouTube or Spotify link to add it to the queue."
SEND_A_LINK = "Send me a YouTube or Spotify song link."


class TelegramError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class TelegramAPI:
    """Minimal blocking Bot API client (stdlib only)."""

    def __init__(self, token: str) -> None:
        self._token = token

    def call(self, method: str, params: dict[str, Any] | None = None, *, timeout: float = 15) -> Any:
        """Call a Bot API method. `timeout` is the network timeout, separate from Telegram's own
        long-poll `timeout` parameter (which goes in `params`)."""
        request = urllib.request.Request(
            f"{API_BASE}/bot{self._token}/{method}",
            data=json.dumps(params or {}).encode(),
            headers={"Content-Type": "application/json"},
        )
        # Errors are re-raised without chaining: the original carries the URL, i.e. the token.
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read())
        except urllib.error.HTTPError as e:
            status = e.code
        except (OSError, ValueError):
            status = None
        else:
            if body.get("ok"):
                return body.get("result")
            raise TelegramError(f"Telegram {method} was refused", body.get("error_code"))
        raise TelegramError(f"Telegram {method} failed" + (f" ({status})" if status else " (network error)"), status)

    def get_me(self) -> dict:
        return self.call("getMe")

    def get_updates(self, offset: int | None, timeout: int) -> list[dict]:
        params = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset is not None:
            params["offset"] = offset
        return self.call("getUpdates", params, timeout=timeout + 10)

    def send_message(self, chat_id: int, text: str, reply_to: int | None = None) -> None:
        params: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_to is not None:
            params["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
        self.call("sendMessage", params)


class Pairings:
    """Telegram user id -> the invite token they joined with, saved in a small JSON file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._users: dict[str, str] = {}
        try:
            data = json.loads(path.read_text())
            if isinstance(data, dict):
                self._users = {str(k): str(v) for k, v in data.items()}
        except (OSError, ValueError):
            pass

    def token_for(self, user_id: int) -> str | None:
        return self._users.get(str(user_id))

    def pair(self, user_id: int, token: str) -> None:
        self._users[str(user_id)] = token
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".telegram-", suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(self._users, f)
        os.replace(tmp, self.path)


def describe_added(state: RoomState) -> str:
    """Name the song just added: it's last in the queue, or playing if the queue was empty."""
    added = state.queue[-1] if state.queue else state.now_playing
    if added is None:
        return "Added to the queue"
    title, artist = added.track.title, added.track.artist
    return f"Added “{title}” – {artist}" if artist else f"Added “{title}”"


class TelegramBot:
    def __init__(self, api: TelegramAPI, pairings: Pairings, current_token: Callable[[], str],
                 add_link: Callable[[str, str | None], Awaitable[RoomState]]) -> None:
        self.api = api
        self.pairings = pairings
        self.current_token = current_token
        self.add_link = add_link
        self.username: str | None = None

    async def handle(self, update: dict) -> None:
        message = update.get("message") or {}
        text = (message.get("text") or "").strip()
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        if not text or "id" not in chat or "id" not in sender:
            return
        in_group = chat.get("type") != "private"

        async def reply(reply_text: str) -> None:
            try:
                await anyio.to_thread.run_sync(self.api.send_message, chat["id"], reply_text, message.get("message_id"))
            except TelegramError as e:
                log.warning("Couldn't reply on Telegram: %s", e)

        invite = JOIN_TOKEN_RE.search(text) or START_TOKEN_RE.match(text)
        if invite:
            if invite.group(1) == self.current_token():
                self.pairings.pair(sender["id"], invite.group(1))
                await reply(PAIRED)
            else:
                await reply(INVITE_EXPIRED)
            return

        is_add_command = bool(ADD_COMMAND_RE.match(text))
        link = LINK_RE.search(text)
        if in_group and not (link or is_add_command):
            return  # ordinary group chatter
        if self.pairings.token_for(sender["id"]) != self.current_token():
            await reply(ASK_FOR_INVITE)
            return
        if not link:
            await reply(SEND_A_LINK)
            return
        added_by = (sender.get("first_name") or "").strip()[:40] or None
        try:
            state = await self.add_link(link.group(0), added_by)
        except HTTPException as e:
            await reply(str(e.detail))
            return
        await reply(describe_added(state))
