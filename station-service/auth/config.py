import os
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy.engine import make_url


LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
DATABASE_URL_ENV = "AUTH_DATABASE_URL"
SERVICE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SQLITE_PATH = SERVICE_DIR / "auth.sqlite3"


def database_url() -> str:
    """The one identity database URL used by the API, CLIs, migrations, and tests.

    Unset: the Git-ignored, machine-local `station-service/auth.sqlite3`. A relative SQLite
    path in the variable resolves against `station-service/`, never the working directory.
    """
    configured = os.environ.get(DATABASE_URL_ENV, "").strip()
    if not configured:
        return f"sqlite:///{DEFAULT_SQLITE_PATH.as_posix()}"
    url = make_url(configured)
    database = url.database or ""
    if url.get_backend_name() != "sqlite" or database in {"", ":memory:"} or database.startswith("file:"):
        return configured
    if Path(database).is_absolute():
        return configured
    return url.set(database=(SERVICE_DIR / database).as_posix()).render_as_string(hide_password=False)


def sqlite_path() -> Path | None:
    url = make_url(database_url())
    if url.get_backend_name() != "sqlite" or url.database in {None, "", ":memory:"} or url.database.startswith("file:"):
        return None
    return Path(url.database)


def database_description() -> str:
    """The configured database with any password masked, safe to print."""
    return make_url(database_url()).render_as_string(hide_password=True)


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
