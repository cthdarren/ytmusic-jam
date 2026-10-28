# YT Music Jam Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A self-hosted "jam" web app run with Docker Compose on a home server. The owner logs in with an app password. Friends join through a share link or QR code. Everyone can search YouTube Music, paste links, and add, remove or reorder songs in a shared live queue, which plays on one host device through the YouTube IFrame player.

**Architecture:** A FastAPI backend holds a single in-memory `Room` (now playing, queue, play/pause). Changes go through REST endpoints and are broadcast as full state snapshots over a WebSocket. Every request needs a signed session cookie: an owner cookie (from username and password) or a guest cookie (from a join link the owner can reset). Search and lookups use `ytmusicapi` with no login. A React/Vite frontend has a login screen, a guest/owner control view at `/`, and the player view at `/host`. Ad-free playback comes from the host browser being signed into a Premium YouTube account. The app does no Google OAuth.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, ytmusicapi, itsdangerous, pydantic v2, pytest + httpx (backend); Node 22, React 18 + TypeScript, Vite, @dnd-kit/core + @dnd-kit/sortable, qrcode, vitest + @testing-library/react (frontend); Docker Compose (deploy).

**Spec:** No separate spec doc exists. Requirements come from the conversation:
- Search YouTube / YouTube Music and add songs to the queue. Paste a YouTube or YouTube Music link to add it directly.
- A button to view the queue, with remove and drag-to-reorder.
- Shared queue, one speaker: friends on the home Wi-Fi open the app on their phones. Only the host device plays audio.
- Opening the web app shows a login for the owner's account (an app username and password set in the compose env). Friends join through a share link or QR code the owner shows. The owner can reset it to kick everyone.
- Premium (no ads) comes from the host browser's YouTube sign-in. No Google OAuth.
- Hosted at home with `docker compose`. Reached at `http://192.168.66.66:8000` on the LAN, and also over Tailscale. Plain HTTP, with no domain or TLS.

## Global Constraints

- Backend Python 3.12 with `uv` (`pyproject.toml` and `uv.lock` committed). Frontend Node 22 with `npm` (`package-lock.json` committed). Use the latest stable versions at install time.
- uvicorn runs with **exactly 1 worker** (in-memory room). A restart clears the queue, which is acceptable. Owner sessions and the join token survive restarts.
- Required config comes from env (via the compose `.env`): `JAM_USERNAME`, `JAM_PASSWORD`, `JAM_SECRET` (cookie signing key). Optional: `JAM_COOKIE_SECURE` (default `false`) and `JAM_DATA_DIR` (default `/data`). The app refuses to start if a required var is missing.
- **The site is plain HTTP on a LAN IP.** Cookies must not be `Secure` by default. The frontend must not depend on secure-context-only APIs (`navigator.clipboard`, `crypto.randomUUID`) without a fallback.
- Session cookie `jam_session`: `HttpOnly`, `SameSite=Lax`, max age 30 days, signed with `itsdangerous.URLSafeTimedSerializer(JAM_SECRET)`.
- Guests can do everything except view or reset the join link. `/host` playback works for any session, but the UI only offers it to the owner.
- Metadata comes only from `ytmusicapi.YTMusic()` without auth. No audio is downloaded or proxied. Playback is only through the official IFrame API.
- Blocking ytmusicapi calls go through `starlette.concurrency.run_in_threadpool`. Room changes happen only on the event loop.
- The API uses snake_case JSON, mirrored exactly by the TS types. The backend serves `frontend/dist` on the same origin in production. In dev, Vite proxies `/api`, `/join` and `/ws` to `localhost:8000`.

## Review Focus

1. **Plain-HTTP LAN access.** Logging in at `http://192.168.66.66:8000` must actually keep you logged in (no `Secure` cookie), and "Copy link" must work where `navigator.clipboard` is undefined (Task 5 `test_login_cookie_not_secure_by_default`, Task 6 `copyText` fallback test).
2. **Double "next".** Two host tabs both fire `ended`, or two people tap Skip, and only one song is skipped (Task 2 `test_advance_ignores_stale_expected_id`, Task 4 `test_next_twice_with_same_expected_id_skips_once`).
3. **Kicking guests.** After "Reset link", old guest cookies stop working on every endpoint *and* their open WebSockets are closed. The owner stays logged in (Task 5 `test_reset_invalidates_guest_cookie`, `test_reset_closes_guest_websockets`).
4. **Link variants.** `music.youtube.com/watch?v=…&list=…`, `youtu.be/ID?si=…`, `/shorts/`, `/embed/`, `m.youtube.com` and a bare id all work. Playlist-only links or junk get a readable 400 (Task 1, Task 4 `test_add_invalid_link_returns_400`).
5. **Unplayable videos.** Embed-blocked videos (IFrame errors 2/5/100/101/150) are skipped automatically and don't stall the jam (Task 7 `onPlayerEvent` tests).

---

## File Structure

```
backend/
  pyproject.toml
  app/
    links.py      # parse_video_id
    models.py     # Track, QueueItem, RoomState
    room.py       # Room queue state machine
    ytm.py        # YTMClient over ytmusicapi
    settings.py   # Settings.from_env()
    auth.py       # Auth: sessions, join token, login rate limit
    hub.py        # Hub: websockets + broadcast
    main.py       # create_app(...)
  tests/  test_links.py test_room.py test_ytm.py test_api.py test_auth.py conftest.py
frontend/
  src/ main.tsx App.tsx types.ts api.ts useRoom.ts copyText.ts hostPlayerLogic.ts
       components/ LoginScreen.tsx InviteDialog.tsx SearchBar.tsx SearchResults.tsx
                   NowPlaying.tsx QueueDrawer.tsx HostPlayer.tsx
Dockerfile  docker-compose.yml  .env.example  .dockerignore  README.md
```

---

### Task 1: Backend scaffold + link parsing

**Files:** Create `backend/pyproject.toml`, `backend/app/__init__.py`, `backend/app/links.py`, `backend/tests/test_links.py`, `.gitignore`, `docs/superpowers/plans/2026-10-28-ytmusic-jam.md` (copy of this plan)

**Interfaces:**
- Produces: `parse_video_id(text: str) -> str | None`. Returns the 11-char id matching `[A-Za-z0-9_-]{11}`.

- [ ] **Step 1: Scaffold.** `uv init --app backend --python 3.12`, then `uv add fastapi "uvicorn[standard]" ytmusicapi itsdangerous` and `uv add --dev pytest httpx`. `.gitignore`: `.venv/ node_modules/ dist/ __pycache__/ data/ .env`. Copy this plan into `docs/superpowers/plans/`.
- [ ] **Step 2: Write the failing tests** in `backend/tests/test_links.py`

```python
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
```

- [ ] **Step 3: Run** `cd backend && uv run pytest tests/test_links.py -v`. Expected: FAIL (import error).
- [ ] **Step 4: Implement.** Strip the input. A bare id must fully match the regex. Otherwise add `https://` if there's no scheme, then `urllib.parse.urlparse`. Allowed hosts: `youtube.com`, `www.youtube.com`, `m.youtube.com`, `music.youtube.com`, `youtu.be`. Take the id from `v=` (for `/watch`), the first path segment (for `youtu.be`), or the second segment (for `/shorts/` and `/embed/`), then regex-validate it.
- [ ] **Step 5: Run.** Expected: PASS. **Step 6: Commit** `feat(backend): scaffold and youtube link parsing`.

---

### Task 2: Room queue model

**Files:** Create `backend/app/models.py`, `backend/app/room.py`, `backend/tests/test_room.py`

**Interfaces:**
- Produces (pydantic):
  - `Track(video_id: str, title: str, artist: str, duration_seconds: int | None, thumbnail_url: str | None)`
  - `QueueItem(id: str, track: Track, added_by: str | None)`. `id = uuid4().hex`.
  - `RoomState(now_playing: QueueItem | None, queue: list[QueueItem], is_playing: bool, version: int)`
- Produces, `class Room`:
  - `add(track, added_by) -> QueueItem`. If nothing is playing, the item becomes `now_playing` with `is_playing=True`. Otherwise it's appended to the queue.
  - `remove(item_id) -> None`. Raises `KeyError`.
  - `move(item_id, to_index) -> None`. Clamps the index to `[0, len-1]`. Raises `KeyError`.
  - `advance(expected_item_id: str | None) -> bool`. A no-op returning False if it doesn't match the current `now_playing.id`. Otherwise pops queue[0] into `now_playing` (an empty queue gives None and `is_playing=False`).
  - `set_playing(playing: bool) -> None`. A no-op when nothing is playing.
  - `snapshot() -> RoomState`
  - `version` increments only on a successful change.

- [ ] **Step 1: Write the failing tests** using a helper `t(n)` that builds a Track:
  - `test_first_add_starts_playing`
  - `test_later_adds_queue_in_order`
  - `test_same_song_twice_gets_distinct_ids`
  - `test_remove`, `test_remove_unknown_raises`
  - `test_move` (a,b,c; move c→0 gives c,a,b)
  - `test_move_clamps_index` (a→99 is last; c→-5 is first)
  - `test_advance_pops_next`
  - `test_advance_ignores_stale_expected_id` (the second call with the same id returns False, and only one item is consumed)
  - `test_advance_on_empty_queue_stops`
  - `test_version_increments_only_on_change`
- [ ] **Step 2: Run.** Expected FAIL. **Step 3: Implement.** **Step 4: Run.** Expected PASS. **Step 5: Commit** `feat(backend): in-memory room queue model`.

---

### Task 3: YouTube Music client

**Files:** Create `backend/app/ytm.py`, `backend/tests/test_ytm.py`

**Interfaces:**
- Produces: `class UpstreamError(Exception)`, and `class YTMClient(yt: YTMusic | None = None)` with:
  - `search(query, kind: Literal["songs","videos"]="songs", limit=20) -> list[Track]`. Calls `yt.search(query, filter=kind, limit=limit)` and skips rows without a `videoId`.
  - `get_track(video_id) -> Track`. Reads `yt.get_song(video_id)["videoDetails"]`. Raises `LookupError` if it's missing.
  - Any other ytmusicapi exception is re-raised as `UpstreamError`.
- Mapping:
  - Search: `artist = ", ".join(a["name"] for a in r.get("artists") or [])`, `duration_seconds = r.get("duration_seconds")`, thumbnail = the last `thumbnails[].url`.
  - get_song: `title`, `author`, `int(lengthSeconds)`, `thumbnail.thumbnails[-1].url`.

- [ ] **Step 1: Write the failing tests** with a `FakeYT` returning canned dicts in exactly those shapes:
  - `test_search_maps_fields` (two artists give `"A, B"`; the largest thumbnail is used)
  - `test_search_skips_results_without_video_id`
  - `test_get_track_maps_fields` (`"215"` gives `215`)
  - `test_get_track_missing_details_raises_lookup`
  - `test_upstream_exception_wrapped`
- [ ] **Step 2–4:** Run (FAIL), implement, run (PASS).
- [ ] **Step 5: Network smoke check.** `uv run python -c "from app.ytm import YTMClient; print(YTMClient().search('daft punk')[:2])"`. Expected: real titles. If the keys have drifted, fix both the mapping and the fake.
- [ ] **Step 6: Commit** `feat(backend): ytmusicapi client wrapper`.

---

### Task 4: HTTP API + WebSocket broadcast (no auth yet)

**Files:** Create `backend/app/hub.py`, `backend/app/main.py`, `backend/tests/test_api.py`, `backend/tests/conftest.py`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces:
  - `create_app(ytm: YTMClient | None = None, static_dir: Path | None = None) -> FastAPI`. Each call creates a fresh `Room` and `Hub`. Task 5 adds a `settings` parameter.
  - `Hub`: `connect(ws, role: str)`, `disconnect(ws)`, `async broadcast(state)`, which sends `{"type":"state","state":…}` and drops dead sockets, and `async close_role(role: str, code: int)`, used by Task 5.
  - `conftest.py`: a `FakeYTM` and a `client` fixture.

| Method/Path | Body | Success | Errors |
|---|---|---|---|
| `GET /api/search?q=&kind=songs` | | `list[Track]` | 400 blank q, 502 Upstream |
| `GET /api/state` | | `RoomState` | |
| `POST /api/queue` | `{"input": str, "added_by": str\|null}` | `RoomState` | 400 `"Not a YouTube link or video id"`, 404 Lookup, 502 Upstream |
| `DELETE /api/queue/{item_id}` | | `RoomState` | 404 |
| `POST /api/queue/{item_id}/move` | `{"to_index": int}` | `RoomState` | 404 |
| `POST /api/player/next` | `{"expected_item_id": str\|null}` | `RoomState` | |
| `POST /api/player/playing` | `{"playing": bool}` | `RoomState` | |
| `WS /ws` | | state on connect, then on every change | |

  Changing routes broadcast after they succeed. If `static_dir` is set, serve it with an SPA fallback: any non-`/api`, non-`/ws`, non-`/join` GET that isn't a file returns `index.html`.

- [ ] **Step 1: Write the failing tests:**
  - `test_search_returns_tracks`, `test_search_empty_query_returns_400`, `test_search_upstream_error_returns_502`
  - `test_add_by_link_starts_playing`, `test_add_invalid_link_returns_400`
  - `test_remove_unknown_returns_404`, `test_move_reorders`
  - `test_next_twice_with_same_expected_id_skips_once`
  - `test_ws_receives_state_on_connect_and_on_change`
- [ ] **Step 2–4:** Run (FAIL), implement, `uv run pytest -v` (PASS).
- [ ] **Step 5: Commit** `feat(backend): REST API and websocket state broadcast`.

---

### Task 5: Owner login + guest join links

**Files:** Create `backend/app/settings.py`, `backend/app/auth.py`, `backend/tests/test_auth.py`. Modify `backend/app/main.py` and `backend/tests/conftest.py` (the `client` fixture becomes an owner-logged-in client; add `anon_client` and `guest_client` fixtures).

**Interfaces:**
- Produces:
  - `Settings(username: str, password: str, secret: str, cookie_secure: bool = False, data_dir: Path = Path("/data"))`
  - `Settings.from_env() -> Settings`. Raises `RuntimeError` naming every missing var among `JAM_USERNAME`, `JAM_PASSWORD` and `JAM_SECRET`.
  - `class Auth(settings)`:
    - `check_password(username, password) -> bool` (`hmac.compare_digest` on both).
    - `make_cookie(role: Literal["owner","guest"]) -> str`. A guest payload embeds the current join token.
    - `read_cookie(value: str | None) -> Literal["owner","guest"] | None`. Returns None if the signature is bad, the cookie is older than 30 days, or it's a guest cookie whose token isn't current.
    - `join_token: str`. Persisted in `data_dir/join_token`, created with `secrets.token_urlsafe(16)` the first time.
    - `reset_join_token() -> str`.
    - `login_allowed(ip: str) -> bool` and `record_failure(ip)`. At most 5 failures per IP per 60 s, in memory.
  - `create_app(ytm=None, static_dir=None, settings: Settings | None = None)`. Settings default to `Settings.from_env()`.
- New routes. All other `/api/*` routes now need a valid session (401 otherwise), and `/ws` closes with code `4401` if there's no session.

| Method/Path | Who | Behaviour |
|---|---|---|
| `POST /api/auth/login` `{"username","password"}` | anyone | 200 `{"role":"owner"}` and sets the cookie. 401 `"Wrong username or password"`. 429 when rate-limited. |
| `POST /api/auth/logout` | anyone | Clears the cookie. 204. |
| `GET /api/auth/me` | session | `{"role": "owner"\|"guest"}`, or 401. |
| `GET /api/join` | owner | `{"url": f"{request.base_url}join/{token}"}` (403 for guests). |
| `POST /api/join/reset` | owner | Rotates the token, runs `hub.close_role("guest", 4401)`, returns the new `{"url"}`. |
| `GET /join/{token}` | anyone | Valid: sets a guest cookie (unless an owner cookie is already present) and 303 to `/`. Invalid: 303 to `/?join=invalid`. |

- [ ] **Step 1: Write the failing tests** in `test_auth.py`. Use `Settings(username="me", password="pw", secret="s"*32, data_dir=tmp_path)`.
  - `test_api_requires_session`: anon `GET /api/state` returns 401.
  - `test_ws_rejects_anon`: connecting raises `WebSocketDisconnect` with code 4401.
  - `test_login_success_sets_cookie_and_me_is_owner`, `test_login_wrong_password_401`
  - `test_login_cookie_not_secure_by_default`: the `Set-Cookie` header has no `Secure` and does have `HttpOnly`.
  - `test_login_rate_limited_after_5_failures`: the 6th attempt returns 429 even with the right password.
  - `test_join_link_gives_guest_session`: owner `GET /api/join` → anon follows `/join/{token}` → `me` is guest → `GET /api/state` is 200.
  - `test_guest_cannot_view_or_reset_join`: 403.
  - `test_bad_join_token_redirects_invalid`: `Location` is `/?join=invalid`.
  - `test_reset_invalidates_guest_cookie`: the guest gets 401 afterwards, and the owner still gets 200.
  - `test_reset_closes_guest_websockets`
  - `test_join_token_persists_across_app_instances`: two `create_app` calls with the same `data_dir` give the same token.
  - `test_missing_env_raises`: `monkeypatch.delenv` → `RuntimeError` whose message names `JAM_PASSWORD`.
- [ ] **Step 2: Run** `uv run pytest -v`. Expected: the new tests FAIL. Task 4 tests still pass once the fixture is updated.
- [ ] **Step 3: Implement** `settings.py` and `auth.py`, plus a `require_session` dependency on the protected routes in `main.py`. Read the WS cookie from `websocket.cookies`, then `hub.connect(ws, role)`.
- [ ] **Step 4: Run.** Expected: all PASS. **Step 5: Commit** `feat(backend): owner login and resettable guest join links`.

---

### Task 6: Frontend: login, invite and jam UI

**Files:**
- Create the `frontend/` scaffold (`npm create vite@latest frontend -- --template react-ts`) and `src/{types,api,useRoom,copyText}.ts`.
- Create `src/components/{LoginScreen,InviteDialog,SearchBar,SearchResults,NowPlaying,QueueDrawer}.tsx` and `src/App.tsx`.
- Create tests `src/api.test.ts`, `src/copyText.test.ts`, `src/components/QueueDrawer.test.tsx`.
- Modify `vite.config.ts`: proxy `/api`, `/join` and `/ws` (with `ws: true`) to `localhost:8000`. Set vitest to `jsdom`.

**Interfaces:**
- Consumes: the Task 4 and Task 5 contracts.
- Produces:
  - `types.ts` mirrors the models, plus `Role = "owner" | "guest"`.
  - `api.ts`: `isLink(text): boolean` (contains `youtube.com/` or `youtu.be/`, or fully matches `^[A-Za-z0-9_-]{11}$`), `me(): Promise<Role | null>` (null on 401), `login(u, p)`, `logout()`, `getJoinUrl()`, `resetJoinUrl()`, `search`, `addToQueue(input, addedBy)`, `removeItem`, `moveItem`, `next(expectedItemId)`, `setPlaying`. Calls throw `Error(detail)` on a non-2xx response. Any 401 from a non-auth call fires a `"jam:unauthorized"` window event, and App drops back to the login screen.
  - `copyText(text): Promise<boolean>`. Uses `navigator.clipboard?.writeText` if it exists. Otherwise it falls back to a hidden textarea + `document.execCommand("copy")`.
  - `useRoom(): { state: RoomState | null; connected: boolean }`. A WebSocket with a 1→10 s backoff reconnect. On close code 4401 it fires `"jam:unauthorized"` and stops reconnecting.
  - `reorder(ids: string[], activeId: string, overId: string): { id: string; toIndex: number }`, exported from `QueueDrawer.tsx`.
- UI:
  - App calls `me()`. If null, show `LoginScreen` (username, password, error text). With `?join=invalid` it says "That invite link has expired — ask the host for a new one."
  - Nickname prompt on first visit, saved in `localStorage` (inside try/catch).
  - Owner header: an "Invite" button opens `InviteDialog` (join URL, QR code via the `qrcode` package to a canvas, Copy, Reset link), plus "Open player" (link to `/host`) and "Log out".
  - SearchBar: a single input. A link adds directly; text runs a search, with a Songs/Videos toggle.
  - NowPlaying bar fixed at the bottom: Skip, Play/Pause and a "Queue (n)" button that opens `QueueDrawer` (dnd-kit sortable with touch support, drag handles, ✕ remove).
  - Errors appear in a toast. Layout is mobile-first.

- [ ] **Step 1: Scaffold + deps.** `npm i @dnd-kit/core @dnd-kit/sortable @dnd-kit/utilities qrcode`, then `npm i -D @types/qrcode vitest jsdom @testing-library/react @testing-library/jest-dom`. Add `"test": "vitest run"`.
- [ ] **Step 2: Write the failing tests:**
  - `isLink` is true for a music.youtube.com URL, `youtu.be/dQw4w9WgXcQ` and `dQw4w9WgXcQ`, and false for `daft punk` and `around the world`.
  - `copyText` with `navigator.clipboard` undefined and `document.execCommand` stubbed to return true → resolves true, and `execCommand` was called with `"copy"`.
  - `reorder(["a","b","c"], "c", "a")` → `{id:"c", toIndex:0}`.
  - QueueDrawer renders 3 titles in order, and ✕ on the 2nd calls `onRemove` with its id.
- [ ] **Step 3–4:** `npm test` (FAIL), implement, `npm test` (PASS).
- [ ] **Step 5: Manual check.** Run `JAM_USERNAME=me JAM_PASSWORD=pw JAM_SECRET=dev JAM_DATA_DIR=./data uv run uvicorn app.main:app --reload --host 0.0.0.0` and `npm run dev -- --host`.
  1. Log in on the laptop, open Invite and scan the QR code with a phone on the same Wi-Fi. The phone joins as a guest without a password.
  2. Add, paste a link, reorder and remove from both devices. Both update live.
  3. Press "Reset link". The phone drops back to the login screen.
- [ ] **Step 6: Commit** `feat(frontend): login, invite links and jam queue UI`.

---

### Task 7: Host player (YouTube IFrame API)

**Files:** Create `frontend/src/components/HostPlayer.tsx`, `frontend/src/hostPlayerLogic.ts`, `frontend/src/hostPlayerLogic.test.ts`. Modify `frontend/src/App.tsx` (on `/host`, render `<HostPlayer/>` above the normal UI).

**Interfaces:**
- Consumes: `RoomState`, `next`, `setPlaying`.
- Produces: `onPlayerEvent(event: {kind:"ended"} | {kind:"error", code:number}, nowPlayingId: string | null): {call:"next", expected:string} | null`.
- Behaviour:
  - Load `https://www.youtube.com/iframe_api` once and create a `YT.Player` with `playerVars: { autoplay: 1, playsinline: 1 }`.
  - When `now_playing.track.video_id` changes, call `loadVideoById`. If it becomes null, call `stopVideo`.
  - Mirror `is_playing` with `playVideo`/`pauseVideo`, and report native play/pause changes through `setPlaying`. Compare with the state first to avoid an echo loop.
  - Send `ended` and `error` through `onPlayerEvent` → `next`.
  - Show a "Start jam" button until the first click, because of the autoplay policy.
  - `npm i -D @types/youtube`.
  - Show a small hint: "For no ads, sign into YouTube Premium in this browser (Chrome recommended)."

- [ ] **Step 1: Write the failing tests:** `ended` → next with the id. Errors 150 and 101 → next. Error 999 → null. A null `nowPlayingId` → null.
- [ ] **Step 2–4:** Run (FAIL), implement, run (PASS).
- [ ] **Step 5: Manual check.** Open `/host` as the owner in Chrome signed into Premium. Add 3 songs from a guest phone. They play in order with no ads. Skip and pause from the phone work. Auto-advance works. With a second `/host` tab open, an ended song skips only once.
- [ ] **Step 6: Commit** `feat(frontend): host IFrame player with auto-advance`.

---

### Task 8: Docker Compose deploy + README

**Files:** Create `Dockerfile`, `docker-compose.yml`, `.env.example`, `.dockerignore`, `README.md`

**Interfaces:**
- Consumes: `app.main:app` (Settings from env, static `frontend/dist`).

- [ ] **Step 1: Dockerfile.**
  - Stage 1: `node:22-slim` runs `npm ci && npm run build` in `frontend/`.
  - Stage 2: `python:3.12-slim` with `COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/`. Run `uv sync --frozen --no-dev` in `/app/backend` and copy `dist` to `/app/frontend/dist`.
  - `CMD ["uv","run","--no-sync","uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--workers","1"]`.
- [ ] **Step 2: `docker-compose.yml`.** Service `jam`: `build: .`, `env_file: .env`, `ports: ["8000:8000"]`, `volumes: ["./data:/data"]`, `restart: unless-stopped`. `.env.example` lists `JAM_USERNAME`, `JAM_PASSWORD`, `JAM_SECRET` (with the comment `# openssl rand -hex 32`) and `JAM_COOKIE_SECURE=false`.
- [ ] **Step 3: README.** Cover:
  - Setup: `cp .env.example .env`, edit it, then `docker compose up -d --build`.
  - Open `http://192.168.66.66:8000` or the server's Tailscale address.
  - `/host` is the speaker device. Sign into YouTube Premium in that browser, preferably Chrome, because browsers that block third-party cookies show ads in the embed.
  - Invite friends from the Invite button, and reset the link to kick them.
  - Dev commands.
- [ ] **Step 4: Verify.**
  1. `docker compose up -d --build`
  2. `curl -s -o /dev/null -w '%{http_code}' localhost:8000/api/state`. Expected `401`.
  3. `curl -s -c /tmp/c -H 'content-type: application/json' -d '{"username":"<u>","password":"<p>"}' localhost:8000/api/auth/login`. Expected `{"role":"owner"}`.
  4. `curl -s -b /tmp/c localhost:8000/api/state`. Expected `{"now_playing":null,"queue":[],"is_playing":false,"version":0}`.
  5. `docker compose restart`, then repeat step 4 with the same cookie. Expected: still 200.
  6. Repeat the Task 6 and Task 7 manual checks against `http://192.168.66.66:8000`.
- [ ] **Step 5: Commit** `chore: docker compose deployment and README`.
