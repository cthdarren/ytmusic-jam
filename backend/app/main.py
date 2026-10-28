from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.hub import Hub
from app.links import parse_video_id
from app.models import RoomState, Track
from app.room import Room
from app.ytm import UpstreamError, YTMClient

DEFAULT_STATIC_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"
_DEFAULT = object()


class AddRequest(BaseModel):
    input: str
    added_by: str | None = None


class MoveRequest(BaseModel):
    to_index: int


class NextRequest(BaseModel):
    expected_item_id: str | None = None


class PlayingRequest(BaseModel):
    playing: bool


def create_app(ytm: YTMClient | None = None, static_dir: Path | None | object = _DEFAULT) -> FastAPI:
    """Build the app. Run in production with `uvicorn --factory app.main:create_app`."""
    if static_dir is _DEFAULT:
        static_dir = DEFAULT_STATIC_DIR if DEFAULT_STATIC_DIR.is_dir() else None
    ytm = ytm if ytm is not None else YTMClient()
    room = Room()
    hub = Hub()
    app = FastAPI(title="YT Music Jam")

    async def changed() -> RoomState:
        state = room.snapshot()
        await hub.broadcast(state)
        return state

    @app.get("/api/search")
    async def search(q: str, kind: Literal["songs", "videos"] = "songs") -> list[Track]:
        if not q.strip():
            raise HTTPException(400, "Search query is empty")
        try:
            return await run_in_threadpool(ytm.search, q.strip(), kind)
        except UpstreamError as e:
            raise HTTPException(502, f"YouTube Music search failed: {e}")

    @app.get("/api/state")
    async def get_state() -> RoomState:
        return room.snapshot()

    @app.post("/api/queue")
    async def add_to_queue(body: AddRequest) -> RoomState:
        video_id = parse_video_id(body.input)
        if video_id is None:
            raise HTTPException(400, "Not a YouTube link or video id")
        try:
            track = await run_in_threadpool(ytm.get_track, video_id)
        except LookupError:
            raise HTTPException(404, "That video doesn't exist or isn't available")
        except UpstreamError as e:
            raise HTTPException(502, f"YouTube Music lookup failed: {e}")
        added_by = (body.added_by or "").strip()[:40] or None
        room.add(track, added_by)
        return await changed()

    @app.delete("/api/queue/{item_id}")
    async def remove_from_queue(item_id: str) -> RoomState:
        try:
            room.remove(item_id)
        except KeyError:
            raise HTTPException(404, "That song is no longer in the queue")
        return await changed()

    @app.post("/api/queue/{item_id}/move")
    async def move_in_queue(item_id: str, body: MoveRequest) -> RoomState:
        try:
            room.move(item_id, body.to_index)
        except KeyError:
            raise HTTPException(404, "That song is no longer in the queue")
        return await changed()

    @app.post("/api/player/next")
    async def next_song(body: NextRequest) -> RoomState:
        if room.advance(body.expected_item_id):
            return await changed()
        return room.snapshot()

    @app.post("/api/player/playing")
    async def set_playing(body: PlayingRequest) -> RoomState:
        before = room.version
        room.set_playing(body.playing)
        if room.version != before:
            return await changed()
        return room.snapshot()

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        hub.connect(ws, "owner")
        try:
            await hub.send_state(ws, room.snapshot())
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
            if path.startswith(("api/", "ws", "join/")):
                raise HTTPException(404)
            candidate = (static_root / path).resolve()
            if path and candidate.is_file() and candidate.is_relative_to(static_root):
                return FileResponse(candidate)
            return FileResponse(index)

    return app
