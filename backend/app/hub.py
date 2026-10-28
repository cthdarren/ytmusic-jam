from fastapi import WebSocket

from app.models import RoomState


class Hub:
    """Tracks open WebSockets (with the session role behind each) and fans out state."""

    def __init__(self) -> None:
        self.sockets: dict[WebSocket, str] = {}

    def connect(self, ws: WebSocket, role: str) -> None:
        self.sockets[ws] = role

    def disconnect(self, ws: WebSocket) -> None:
        self.sockets.pop(ws, None)

    async def send_state(self, ws: WebSocket, state: RoomState) -> None:
        await ws.send_json({"type": "state", "state": state.model_dump()})

    async def broadcast(self, state: RoomState) -> None:
        for ws in list(self.sockets):
            try:
                await self.send_state(ws, state)
            except Exception:
                self.disconnect(ws)

    async def close_role(self, role: str, code: int) -> None:
        for ws, ws_role in list(self.sockets.items()):
            if ws_role == role:
                self.disconnect(ws)
                try:
                    await ws.close(code=code)
                except Exception:
                    pass
