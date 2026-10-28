import hmac
import secrets
import time
from collections import defaultdict, deque
from typing import Literal

from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.settings import Settings

Role = Literal["owner", "guest"]

COOKIE_NAME = "jam_session"
SESSION_MAX_AGE = 30 * 24 * 3600
MAX_LOGIN_FAILURES = 5
FAILURE_WINDOW_SECONDS = 60


class Auth:
    """Signed session cookies, the resettable guest join token and a login rate limit.

    A guest cookie embeds the join token it was issued under, so rotating the
    token invalidates every existing guest session at once.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.serializer = URLSafeTimedSerializer(settings.secret, salt="jam-session")
        self.token_path = settings.data_dir / "join_token"
        self.join_token = self._load_or_create_token()
        self.failures: dict[str, deque[float]] = defaultdict(deque)

    def check_password(self, username: str, password: str) -> bool:
        user_ok = hmac.compare_digest(username.encode(), self.settings.username.encode())
        pass_ok = hmac.compare_digest(password.encode(), self.settings.password.encode())
        return user_ok and pass_ok

    def make_cookie(self, role: Role) -> str:
        payload = {"r": role}
        if role == "guest":
            payload["t"] = self.join_token
        return self.serializer.dumps(payload)

    def read_cookie(self, value: str | None) -> Role | None:
        if not value:
            return None
        try:
            payload = self.serializer.loads(value, max_age=SESSION_MAX_AGE)
        except BadSignature:
            return None
        role = payload.get("r") if isinstance(payload, dict) else None
        if role == "owner":
            return "owner"
        if role == "guest" and hmac.compare_digest(str(payload.get("t", "")), self.join_token):
            return "guest"
        return None

    def is_join_token(self, token: str) -> bool:
        return hmac.compare_digest(token, self.join_token)

    def reset_join_token(self) -> str:
        self.join_token = secrets.token_urlsafe(16)
        self._save_token()
        return self.join_token

    def login_allowed(self, ip: str) -> bool:
        window = self.failures[ip]
        cutoff = time.monotonic() - FAILURE_WINDOW_SECONDS
        while window and window[0] < cutoff:
            window.popleft()
        return len(window) < MAX_LOGIN_FAILURES

    def record_failure(self, ip: str) -> None:
        self.failures[ip].append(time.monotonic())

    def _load_or_create_token(self) -> str:
        if self.token_path.is_file():
            token = self.token_path.read_text().strip()
            if token:
                return token
        self.join_token = secrets.token_urlsafe(16)
        self._save_token()
        return self.join_token

    def _save_token(self) -> None:
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(self.join_token)
