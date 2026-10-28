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

    @classmethod
    def from_env(cls) -> "Settings":
        missing = [name for name in REQUIRED_VARS if not os.environ.get(name)]
        if missing:
            raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
        return cls(
            username=os.environ["JAM_USERNAME"],
            password=os.environ["JAM_PASSWORD"],
            secret=os.environ["JAM_SECRET"],
            cookie_secure=os.environ.get("JAM_COOKIE_SECURE", "").lower() in ("1", "true", "yes"),
            data_dir=Path(os.environ.get("JAM_DATA_DIR", "/data")),
        )
