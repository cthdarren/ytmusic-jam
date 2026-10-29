# Telegram Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Friends send a YouTube or Spotify link to a Telegram bot and it's queued. They get access by sending the bot the jam's invite link once, and the host's **Reset link** revokes them too.

**Architecture:**
- **Inside the server:** the bot runs in the existing FastAPI process as a background task, started in the lifespan only when `JAM_TELEGRAM_TOKEN` is set.
- **Polling:** it long-polls Telegram's Bot API (`getUpdates`) with stdlib `urllib` in a thread. That needs no new dependency and no inbound port, domain or HTTPS.
- **Adding songs:** messages go through the same "add a link" function the web API uses (extracted from `POST /api/queue`), so YouTube links, Spotify matching, broadcasts and preloading all behave identically.
- **Access:** Telegram users are paired by invite token and stored in `data_dir/telegram_users.json`. A pairing is valid only while its token is the current join token, the same rule as guest cookies.

**Tech Stack:** stdlib `urllib`/`json` and the existing FastAPI/anyio. No new packages.

**Spec (user):**
- "how feasible it is to integrate this into a telegram bot, where you would just paste the link and it would queue it up"
- Access: "plan the telegram bot with invite link access", chosen from the options offered (group chat / invite link / fixed ID list).
- Agreed behaviour from the proposal:
  - long polling, so the home server needs no public address;
  - the reply names the added song;
  - errors reply with the reason;
  - songs are added under the sender's Telegram first name;
  - Reset link cuts off Telegram users too.
- Not requested: the `/now`, `/queue` and `/skip` extras and search buttons. These are out of scope.

## Global Constraints

- Config:
  - `JAM_TELEGRAM_TOKEN` is optional. With no token there's no bot and nothing changes.
  - The token is a secret: it must never appear in logs. Telegram puts it in the URL path, so log only method names and status codes, never URLs or raw exception text from urllib.
- Pairing:
  - A user is paired by sending the invite link (`…/join/{token}`, anywhere in the message) or `/start {token}` (the Telegram deep link `https://t.me/{bot_username}?start={token}`).
  - Stored as `{telegram_user_id: token}` in `data_dir/telegram_users.json`, written atomically.
  - A user is authorised iff their stored token equals `auth.join_token`.
- Chats: private chats accept any message. In groups the bot only sees `/add <link>` (and `/start`) unless the host disables privacy mode in @BotFather. Authorisation is per *sender*, not per chat.
- Reply texts (exact):
  - Unpaired: `Send me the jam's invite link first (ask the host for it).`
  - Expired invite: `That invite link has expired — ask the host for a new one.`
  - Paired: `You're in! Send me a YouTube or Spotify link to add it to the queue.`
  - Added: `` Added “{title}” – {artist} `` (no ` – {artist}` if the artist is empty)
  - Not a link: `Send me a YouTube or Spotify song link.`
  - Add failed: the API's `detail` text verbatim (e.g. `Couldn't find that song on YouTube Music`).
- `added_by` is the sender's `first_name`, trimmed to 40 characters.
- Polling:
  - `getUpdates` with `timeout=50` and the `allowed_updates=["message"]` parameter; the offset is kept in memory.
  - Network or 5xx error: back off 5 s, doubling to 60 s.
  - 401 (bad token): log once and stop the bot. The app keeps running.
  - 409 (another poller): back off 60 s.
- `GET /api/join` adds `telegram_url` (`https://t.me/{bot_username}?start={token}`) when the bot is running (from `getMe` at startup). The Invite dialog then shows an **Add on Telegram** link.

## Review Focus

1. **Reset link.** Paired Telegram users must be refused straight away, before any restart (`test_reset_link_revokes_telegram_users`).
2. **Stale invite links.** An old link pasted into Telegram must not pair (`test_expired_invite_link_does_not_pair`).
3. **The token in logs.** A urllib error message contains the request URL, and so the token (`test_api_errors_never_log_the_token`).
4. **A slow Spotify match.** About 5 s of work must not block other messages or the web app (the bot handles each update in its own task; `test_slow_add_does_not_block_next_update`).
5. **Restart.** Pairings survive (`test_pairings_persist`). Updates already answered aren't processed twice within one run (`test_offset_advances`).

---

## File Structure

```
backend/app/telegram.py      TelegramAPI (urllib), Pairings (json store), TelegramBot (message handling + poll loop)
backend/app/main.py          extract add_link(); start/stop bot in lifespan; telegram_url in /api/join
backend/app/settings.py      telegram_token
backend/tests/test_telegram.py
frontend/src/components/InviteDialog.tsx   "Add on Telegram" link
README.md, .env.example
```

### Task 1: Shared "add a link" function (refactor, no behaviour change)

**Files:** `backend/app/main.py`

**Interfaces:**
- Produces `async def add_link(text: str, added_by: str | None) -> RoomState` inside `create_app`. This is the body of today's `POST /api/queue`, raising the same `HTTPException`s. The route becomes a one-line call.

- [ ] Steps:
  1. Run `timeout 150 uv run pytest -q`. Expected: 190 pass.
  2. Refactor.
  3. Run again. Expected: 190 pass, and every `/api/queue` test unchanged.
  4. Commit `refactor(backend): share add-a-link logic`.

### Task 2: `telegram.py`: API client, pairings, message handling

**Files:** create `backend/app/telegram.py` and `backend/tests/test_telegram.py`.

**Interfaces:**
- `class TelegramError(Exception)` with `.status: int | None`.
- `TelegramAPI(token)`, blocking:
  - `call(method: str, **params) -> Any` POSTs JSON to `https://api.telegram.org/bot{token}/{method}`.
  - It raises `TelegramError` with a message containing only the method and the status, never the URL.
  - Wrappers: `get_me()`, `get_updates(offset, timeout)` and `send_message(chat_id, text, reply_to)`.
- `Pairings(path)`: `token_for(user_id) -> str | None`, `pair(user_id, token)`, persisted atomically.
- `TelegramBot`:
  - Constructor: `TelegramBot(api, pairings, current_token: Callable[[], str], add_link: Callable[[str, str | None], Awaitable[RoomState]])`.
  - `async handle(update: dict) -> None` sends exactly one reply per message.
  - The added song is named with the same rule as the frontend's `describeAdded` (last queued item, or now playing).
- Token extraction: `/join/(?P<t>[A-Za-z0-9_-]+)` anywhere in the text, or `/start (?P<t>…)`.

- [ ] Tests (fake API recording `send_message`; fake `add_link`):
  - `test_unpaired_user_is_asked_for_the_invite`
  - `test_invite_link_pairs_user`
  - `test_start_deep_link_pairs_user`
  - `test_expired_invite_link_does_not_pair`
  - `test_paired_user_link_is_added_and_named` (also asserts `added_by` is the first name)
  - `test_add_error_detail_is_replied` (an `HTTPException(404, …)` from `add_link`)
  - `test_plain_text_gets_help`
  - `test_group_add_command`
  - `test_reset_link_revokes_telegram_users` (`current_token` changes and the user is refused)
  - `test_pairings_persist`
  - `test_api_errors_never_log_the_token` (urlopen patched to raise `HTTPError`/`URLError` with the URL; `str(TelegramError)` and the captured logs don't contain the token)
- [ ] Run (FAIL), implement, run (PASS), commit `feat(backend): Telegram bot message handling with invite-link pairing`.

### Task 3: Poll loop + app wiring

**Files:** `backend/app/telegram.py` (`async run()`), `backend/app/main.py`, `backend/app/settings.py`, `backend/tests/test_telegram.py`, `backend/tests/test_api.py`, `backend/tests/test_auth.py`

**Interfaces:**
- `TelegramBot.run()` polls forever, spawning `asyncio.create_task(self.handle(u))` per update (with strong refs). It applies the error/backoff rules in Global Constraints and stops on 401.
- `TelegramBot.username: str | None` is set from `get_me()` at start.
- `create_app(..., telegram_api: TelegramAPI | None = None)`. If omitted and `settings.telegram_token` is set, a real `TelegramAPI` is created. The lifespan starts and cancels `run()`.
- `Settings.telegram_token: str | None` (env `JAM_TELEGRAM_TOKEN`).

- [ ] Tests:
  - `test_offset_advances` (fake API serves two batches; the second call's offset is the last `update_id` + 1)
  - `test_slow_add_does_not_block_next_update`
  - `test_bad_token_stops_polling` (401 → `run()` returns and is called no more)
  - `test_network_error_backs_off` (patched sleep records 5, 10, …)
  - API: `test_join_includes_telegram_url_when_bot_running`, `test_telegram_link_is_queued_and_broadcast` (fake API feeds one update and the room gets the song)
  - Settings env test extended
- [ ] Run (FAIL), implement, run (PASS), commit `feat: run the Telegram bot inside the jam server`.

### Task 4: Invite dialog link + docs

**Files:** `frontend/src/api.ts` (`getJoinUrl` returns `{url, telegram_url?}`), `frontend/src/components/InviteDialog.tsx`, a test, `README.md`, `.env.example`

- [ ] Tests:
  - `InviteDialog` shows an **Add on Telegram** link with the `telegram_url` when present, and none otherwise (`getJoinUrl` mocked).
- [ ] README "Telegram bot" section:
  1. @BotFather → `/newbot` → put the token in `.env` as `JAM_TELEGRAM_TOKEN`, then `docker compose up -d`.
  2. Friends open **Add on Telegram** from the Invite dialog, or send the bot the invite link.
  3. In groups, use `/add <link>`, or turn off privacy mode in @BotFather (`/setprivacy`).
  4. Reset link also signs out Telegram users.
- [ ] Commit `feat(frontend): Add on Telegram link in the invite dialog; docs`.

### Task 5: Live check (needs the user's bot token)

- [ ] With a real token:
  - pair via the deep link;
  - send a YouTube link and a Spotify link and confirm both are queued and named in the reply;
  - Reset link → the next message gets the "invite first" reply.
- [ ] This can't run without the user's token. If it isn't available, ledger it as not done and hand the checklist to the user.
