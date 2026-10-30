import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.audio import AudioCache, AudioPaused, AudioUnavailable, Preloader, ytdlp_download
from app.auth import COOKIE_NAME, SESSION_MAX_AGE, Auth, Role
from app.hub import Hub
from app.links import VIDEO_ID_RE, parse_video_id
from app.lyrics import LyricsFinder, fetch_lrclib
from app.models import Lyrics, RoomState, Track
from app.room import Room
from app.settings import Settings
from app.spotify import SpotifyNotATrack, best_match, fetch_spotify_track, parse_spotify
from app.telegram import Pairings, TelegramAPI, TelegramBot
from app.ytm import UpstreamError, YTMClient

log = logging.getLogger(__name__)

AUDIO_MEDIA_TYPES = {".webm": "audio/webm", ".opus": "audio/ogg", ".ogg": "audio/ogg",
                     ".m4a": "audio/mp4", ".mp4": "audio/mp4", ".mp3": "audio/mpeg"}

DEFAULT_STATIC_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"
_DEFAULT = object()


class AddRequest(BaseModel):
    input: str
    added_by: str | None = None


class MoveRequest(BaseModel):
    to_index: int


class NextRequest(BaseModel):
    expected_item_id: str | None = None
    # True when someone pressed Skip (not when a song simply ended): downloads refocus on
    # the new playing/next songs.
    manual: bool = False


class PlayingRequest(BaseModel):
    playing: bool


class LoginRequest(BaseModel):
    username: str
    password: str


def create_app(
    ytm: YTMClient | None = None,
    static_dir: Path | None | object = _DEFAULT,
    settings: Settings | None = None,
    audio: AudioCache | None = None,
    telegram_api: TelegramAPI | None = None,
) -> FastAPI:
    """Build the app. Run in production with `uvicorn --factory app.main:create_app`."""
    if static_dir is _DEFAULT:
        static_dir = DEFAULT_STATIC_DIR if DEFAULT_STATIC_DIR.is_dir() else None
    settings = settings if settings is not None else Settings.from_env()
    ytm = ytm if ytm is not None else YTMClient()
    auth = Auth(settings)
    room = Room(settings.data_dir / "room.json")
    if audio is None:
        audio = AudioCache(
            settings.data_dir / "audio-cache",
            settings.cookies_file or settings.data_dir / "cookies.txt",
            settings.audio_cache_mb * 1024 * 1024,
            downloader=ytdlp_download,
        )
    preloader = Preloader(audio, concurrency=settings.preload_workers)
    lyrics = LyricsFinder(ytm, lrclib=fetch_lrclib)
    if telegram_api is None and settings.telegram_token:
        telegram_api = TelegramAPI(settings.telegram_token)
    bot = (
        TelegramBot(
            telegram_api,
            Pairings(settings.data_dir / "telegram_users.json"),
            lambda: auth.join_token,  # Reset link signs Telegram users out too
            lambda text, added_by: add_link(text, added_by),
        )
        if telegram_api is not None
        else None
    )
    hub = Hub()

    # Tell everyone which songs are downloaded (start instantly) whenever that changes.
    last_ready: set[str] = audio.ready_ids()
    background: set[asyncio.Task] = set()

    def ready_message(ids: set[str]) -> dict:
        return {"type": "ready", "video_ids": sorted(ids)}

    def on_audio_change() -> None:
        nonlocal last_ready
        ids = audio.ready_ids()
        if ids == last_ready:
            return
        last_ready = ids
        task = asyncio.get_running_loop().create_task(hub.broadcast_message(ready_message(ids)))
        background.add(task)
        task.add_done_callback(background.discard)

    audio.on_change = on_audio_change

    def preload(state: RoomState) -> None:
        """Keep the song playing and the next few downloaded, nearest first."""
        upcoming = ([state.now_playing] if state.now_playing else []) + state.queue[: settings.preload_songs]
        preloader.update([item.track.video_id for item in upcoming])

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        preload(room.snapshot())  # a restored night is preloaded, and stale downloads pruned, right away
        bot_task = asyncio.create_task(bot.run()) if bot is not None else None
        yield
        if bot_task is not None:
            bot_task.cancel()
            await asyncio.gather(bot_task, return_exceptions=True)
        await preloader.close()

    app = FastAPI(title="YT Music Jam", lifespan=lifespan)

    def session_role(request: Request) -> Role:
        role = auth.read_cookie(request.cookies.get(COOKIE_NAME))
        if role is None:
            raise HTTPException(401, "Not logged in")
        return role

    def require_owner(role: Role = Depends(session_role)) -> None:
        if role != "owner":
            raise HTTPException(403, "Only the host can do that")

    def set_session(response: Response, role: Role) -> None:
        response.set_cookie(
            COOKIE_NAME, auth.make_cookie(role), max_age=SESSION_MAX_AGE,
            httponly=True, samesite="lax", secure=settings.cookie_secure,
        )

    def join_url(request: Request) -> dict[str, str]:
        urls = {"url": f"{request.base_url}join/{auth.join_token}"}
        if bot is not None and bot.username:
            urls["telegram_url"] = f"https://t.me/{bot.username}?start={auth.join_token}"
        return urls

    api = APIRouter(dependencies=[Depends(session_role)])

    async def changed() -> RoomState:
        # Saving is best-effort: memory is the source of truth, and a full or read-only
        # disk must not stop the broadcast (the host would never hear about the next song).
        try:
            room.save()
        except OSError:
            log.exception("Couldn't save the room; carrying on with it in memory")
        state = room.snapshot()
        await hub.broadcast(state)
        preload(state)
        return state

    @app.post("/api/auth/login")
    async def login(body: LoginRequest, request: Request, response: Response) -> dict[str, str]:
        ip = request.client.host if request.client else "unknown"
        if not auth.login_allowed(ip):
            raise HTTPException(429, "Too many failed attempts, try again in a minute")
        if not auth.check_password(body.username, body.password):
            auth.record_failure(ip)
            raise HTTPException(401, "Wrong username or password")
        set_session(response, "owner")
        return {"role": "owner"}

    @app.post("/api/auth/logout", status_code=204)
    async def logout(response: Response) -> None:
        response.delete_cookie(COOKIE_NAME, httponly=True, samesite="lax", secure=settings.cookie_secure)

    @app.get("/api/auth/me")
    async def me(role: Role = Depends(session_role)) -> dict[str, str]:
        return {"role": role}

    @app.get("/api/join", dependencies=[Depends(require_owner)])
    async def get_join_url(request: Request) -> dict[str, str]:
        return join_url(request)

    @app.post("/api/join/reset", dependencies=[Depends(require_owner)])
    async def reset_join_url(request: Request) -> dict[str, str]:
        auth.reset_join_token()
        await hub.close_role("guest", 4401)
        return join_url(request)

    @app.get("/join/{token}", include_in_schema=False)
    async def join(token: str, request: Request) -> RedirectResponse:
        if not auth.is_join_token(token):
            return RedirectResponse("/?join=invalid", status_code=303)
        response = RedirectResponse("/", status_code=303)
        if auth.read_cookie(request.cookies.get(COOKIE_NAME)) != "owner":
            set_session(response, "guest")
        return response

    @api.get("/api/search")
    async def search(q: str, kind: Literal["songs", "videos"] = "songs") -> list[Track]:
        if not q.strip():
            raise HTTPException(400, "Search query is empty")
        try:
            return await run_in_threadpool(ytm.search, q.strip(), kind)
        except UpstreamError as e:
            raise HTTPException(502, f"YouTube Music search failed: {e}")

    @api.get("/api/audio/{video_id}")
    async def audio_file(video_id: str) -> FileResponse:
        if not VIDEO_ID_RE.fullmatch(video_id):
            raise HTTPException(400, "Not a video id")
        try:
            path = await audio.ensure(video_id)
        except AudioUnavailable:
            raise HTTPException(404, "YouTube won't give us this song")
        except AudioPaused:
            # Only songs that are no longer playing or next get paused, so the host has moved on.
            raise HTTPException(503, "That song's download was paused for a more urgent one")
        return FileResponse(path, media_type=AUDIO_MEDIA_TYPES.get(path.suffix, "application/octet-stream"))

    @api.get("/api/lyrics/{video_id}")
    async def get_lyrics(video_id: str) -> Lyrics:
        if not VIDEO_ID_RE.fullmatch(video_id):
            raise HTTPException(400, "Not a video id")
        state = room.snapshot()
        night = [*state.played, *([state.now_playing] if state.now_playing else []), *state.queue]
        track = next((item.track for item in night if item.track.video_id == video_id), None)
        if track is None:
            raise HTTPException(404, "That song isn't in the jam")
        if not settings.lyrics:
            return Lyrics(lines=[])
        lines = await run_in_threadpool(lyrics.find, track)
        offset = settings.lyrics_offset_ms
        return Lyrics(lines=[line.model_copy(update={"start_ms": max(0, line.start_ms - offset)}) for line in lines])

    @api.get("/api/state")
    async def get_state() -> RoomState:
        return room.snapshot()

    def spotify_to_youtube(track_id: str) -> Track:
        """Find the YouTube Music song matching a Spotify track. Blocking."""
        try:
            spotify = fetch_spotify_track(track_id)
        except LookupError:
            raise HTTPException(404, "That Spotify song doesn't exist")
        except UpstreamError:
            raise HTTPException(502, "Couldn't read that Spotify link")
        query = " ".join([spotify.name, *spotify.artists[:1]])
        try:
            candidates = ytm.search(query, "songs", 10)
        except UpstreamError as e:
            raise HTTPException(502, f"YouTube Music search failed: {e}")
        match = best_match(spotify, candidates)
        if match is None:
            raise HTTPException(404, "Couldn't find that song on YouTube Music")
        return match

    async def add_link(text: str, added_by: str | None) -> RoomState:
        """Queue the song behind a YouTube or Spotify link (web search box and Telegram bot)."""
        try:
            spotify_id = parse_spotify(text)
        except SpotifyNotATrack:
            raise HTTPException(400, "Only Spotify song links are supported (not albums or playlists)")
        if spotify_id is not None:
            track = await run_in_threadpool(spotify_to_youtube, spotify_id)
        else:
            video_id = parse_video_id(text)
            if video_id is None:
                raise HTTPException(400, "Not a YouTube or Spotify link")
            try:
                track = await run_in_threadpool(ytm.get_track, video_id)
            except LookupError:
                raise HTTPException(404, "That video doesn't exist or isn't available")
            except UpstreamError as e:
                raise HTTPException(502, f"YouTube Music lookup failed: {e}")
        room.add(track, (added_by or "").strip()[:40] or None)
        return await changed()

    @api.post("/api/queue")
    async def add_to_queue(body: AddRequest) -> RoomState:
        return await add_link(body.input, body.added_by)

    # Declared before the /api/queue/{item_id}/... routes so "clear" is never read as an item id.
    @api.post("/api/queue/clear", dependencies=[Depends(require_owner)])
    async def clear_queue() -> RoomState:
        room.clear()
        state = await changed()
        preloader.reset()
        audio.clear()  # downloads are short-term: a new night starts with an empty cache
        return state

    @api.post("/api/queue/{item_id}/play")
    async def play_item(item_id: str) -> RoomState:
        try:
            jumped = room.jump(item_id)
        except KeyError:
            raise HTTPException(404, "That song is no longer in the queue")
        if not jumped:
            return room.snapshot()
        state = await changed()
        preloader.refocus()  # a tap is a manual song change: get the new next song ready first
        return state

    @api.delete("/api/queue/{item_id}")
    async def remove_from_queue(item_id: str) -> RoomState:
        try:
            room.remove(item_id)
        except ValueError:
            raise HTTPException(409, "Skip the song that's playing instead of removing it")
        except KeyError:
            raise HTTPException(404, "That song is no longer in the queue")
        return await changed()

    @api.post("/api/queue/{item_id}/move")
    async def move_in_queue(item_id: str, body: MoveRequest) -> RoomState:
        try:
            room.move(item_id, body.to_index)
        except KeyError:
            raise HTTPException(404, "That song is no longer in the queue")
        return await changed()

    @api.post("/api/player/next")
    async def next_song(body: NextRequest) -> RoomState:
        if not room.advance(body.expected_item_id):
            return room.snapshot()
        state = await changed()
        if body.manual:
            preloader.refocus()
        return state

    @api.post("/api/player/playing")
    async def set_playing(body: PlayingRequest) -> RoomState:
        before = room.version
        room.set_playing(body.playing)
        if room.version != before:
            return await changed()
        return room.snapshot()

    app.include_router(api)

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        role = auth.read_cookie(ws.cookies.get(COOKIE_NAME))
        if role is None:
            # Accept-then-close so browsers see code 4401 instead of a bare handshake failure.
            await ws.close(code=4401)
            return
        hub.connect(ws, role)
        try:
            await hub.send_state(ws, room.snapshot())
            await hub.send_message(ws, ready_message(audio.ready_ids()))
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            hub.disconnect(ws)

    if static_dir is not None:
        static_root = Path(static_dir).resolve()
        index = static_root / "index.html"

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str) -> FileResponse:
            if path == "ws" or path.startswith(("api/", "join/")):
                raise HTTPException(404)
            candidate = (static_root / path).resolve()
            if path and candidate.is_file() and candidate.is_relative_to(static_root):
                return FileResponse(candidate)
            # A missing file (e.g. an old hashed asset after a redeploy) must 404, not get HTML back.
            if path.startswith("assets/") or "." in path.rsplit("/", 1)[-1]:
                raise HTTPException(404)
            # Never cache index.html, so phones pick up new asset hashes after an update.
            return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app
