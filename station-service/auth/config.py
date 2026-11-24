import os
from pathlib import Path
from urllib.parse import urlsplit


LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


def database_url() -> str:
    local_db = Path(__file__).resolve().parents[1] / "auth.sqlite3"
    return os.environ.get("AUTH_DATABASE_URL", f"sqlite:///{local_db.as_posix()}")


def web_origin() -> str:
    origin = os.environ.get("AUTH_WEB_ORIGIN", "http://127.0.0.1:5173").rstrip("/")
    parsed = urlsplit(origin)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.path or parsed.query or parsed.fragment
    ):
        raise ValueError("AUTH_WEB_ORIGIN must be a single HTTP(S) origin without a path.")
    return origin


def allow_local_http() -> bool:
    return os.environ.get("AUTH_ALLOW_INSECURE_LOCAL_HTTP") == "1"


def allowed_web_origins() -> list[str]:
    origin = web_origin()
    parsed = urlsplit(origin)
    if not allow_local_http() or parsed.scheme != "http" or parsed.hostname not in LOOPBACK_HOSTS:
        return [origin]

    port = f":{parsed.port}" if parsed.port is not None else ""
    return [origin, *(
        f"http://{host}{port}" for host in ("127.0.0.1", "localhost", "[::1]")
        if f"http://{host}{port}" != origin
    )]
