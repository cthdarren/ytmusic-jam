import os
from dataclasses import dataclass
from pathlib import Path

REQUIRED_VARS = ("JAM_USERNAME", "JAM_PASSWORD", "JAM_SECRET")


@dataclass
class Settings:
    username: str
    password: str
    secret: str
    cookie_secure: bool = False
    data_dir: Path = Path("/data")
    # YouTube cookies (Netscape cookies.txt) so yt-dlp plays as the owner's Premium account.
    # None means data_dir / "cookies.txt". Used only if the file exists.
    cookies_file: Path | None = None
    audio_cache_mb: int = 500
    # Upcoming songs kept downloaded ahead of time (on top of the one playing).
    preload_songs: int = 20
    # How many songs download at the same time while preloading.
    preload_workers: int = 4
    # Telegram bot token from @BotFather; no token, no bot.
    telegram_token: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        missing = [name for name in REQUIRED_VARS if not os.environ.get(name)]
        if missing:
            raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
        data_dir = Path(os.environ.get("JAM_DATA_DIR", "/data"))
        return cls(
            username=os.environ["JAM_USERNAME"],
            password=os.environ["JAM_PASSWORD"],
            secret=os.environ["JAM_SECRET"],
            cookie_secure=os.environ.get("JAM_COOKIE_SECURE", "").lower() in ("1", "true", "yes"),
            data_dir=data_dir,
            cookies_file=Path(os.environ.get("JAM_COOKIES_FILE") or data_dir / "cookies.txt"),
            audio_cache_mb=int(os.environ.get("JAM_AUDIO_CACHE_MB") or 500),
            preload_songs=int(os.environ.get("JAM_PRELOAD_SONGS") or 20),
            preload_workers=int(os.environ.get("JAM_PRELOAD_WORKERS") or 4),
            telegram_token=(os.environ.get("JAM_TELEGRAM_TOKEN") or "").strip() or None,
        )
