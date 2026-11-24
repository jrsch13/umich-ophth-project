import hashlib
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import LOOPBACK_HOSTS, allow_local_http, allowed_web_origins
from .db import Database
from .models import AuthSession, User, utcnow


MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128
TOKEN_LENGTH = 43  # Unpadded URL-safe encoding of 32 random bytes.
BROWSER_SECONDS = 8 * 60 * 60
NATIVE_SECONDS = 60 * 60
password_hasher = PasswordHash.recommended()
_dummy_password_hash = password_hasher.hash(secrets.token_urlsafe(32))
_login_lock = threading.Lock()
_login_attempts: dict[str, int] = {}
_login_window_end = 0.0


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def authenticate_password(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == normalize_email(email)))
    stored_hash = user.password_hash if user is not None else _dummy_password_hash
    verified = password_hasher.verify(password, stored_hash)
    if not verified or user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    return user


def rate_limit_login(request: Request) -> None:
    """Bound password attempts per client for this single-worker station."""
    global _login_window_end
    address = request.client.host if request.client else "unknown"
    with _login_lock:
        now = time.monotonic()
        if now >= _login_window_end:
            _login_attempts.clear()
            _login_window_end = now + 60
        attempts = _login_attempts.get(address, 0)
        if attempts >= 12 or (not attempts and len(_login_attempts) >= 2048):
            raise HTTPException(
                status_code=429,
                detail="Too many attempts. Try again shortly.",
                headers={"Retry-After": str(max(1, int(_login_window_end - now)))},
            )
        _login_attempts[address] = attempts + 1


def require_secure_transport(request: Request) -> None:
    if request.url.scheme == "https":
        return
    if (
        allow_local_http()
        and request.url.scheme == "http"
        and request.url.hostname in LOOPBACK_HOSTS
        and request.client is not None
        and request.client.host in LOOPBACK_HOSTS
    ):
        return
    raise HTTPException(status_code=400, detail="Authentication requires HTTPS.")


def require_browser_origin(request: Request) -> None:
    if request.headers.get("origin") not in allowed_web_origins():
        raise HTTPException(status_code=403, detail="Request origin is not allowed.")


def cookie_name(request: Request) -> str:
    return "__Host-station_session" if request.url.scheme == "https" else "station_session"


@dataclass(frozen=True)
class Identity:
    user: User
    kind: str
    token_hash: str


def require_authenticated(request: Request, db: Database) -> Identity:
    authorization = request.headers.get("authorization")
    if authorization is not None:
        scheme, _, token = authorization.partition(" ")
        valid_scheme = scheme.lower() == "bearer"
        kind = "native"
    else:
        token = request.cookies.get(cookie_name(request), "")
        valid_scheme = True
        kind = "browser"

    unauthorized = HTTPException(
        status_code=401, detail="Authentication required.", headers={"WWW-Authenticate": "Bearer"},
    )
    if not valid_scheme or len(token) != TOKEN_LENGTH:
        raise unauthorized
    require_secure_transport(request)
    if kind == "browser" and request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_browser_origin(request)

    hashed = token_hash(token)
    user = db.scalar(
        select(User).join(AuthSession, AuthSession.user_id == User.id).where(
            AuthSession.token_hash == hashed,
            AuthSession.kind == kind,
            AuthSession.expires_at > utcnow(),
            User.is_active.is_(True),
        )
    )
    if user is None:
        raise unauthorized
    # Long-lived camera streams must not retain a database connection.
    db.expunge(user)
    db.rollback()
    return Identity(user=user, kind=kind, token_hash=hashed)


Authenticated = Annotated[Identity, Depends(require_authenticated)]


def require_station(identity: Authenticated) -> Identity:
    if identity.kind != "browser":
        raise HTTPException(status_code=403, detail="This operation is available in the station interface.")
    return identity


StationUser = Annotated[Identity, Depends(require_station)]


def require_admin(identity: Authenticated) -> Identity:
    if identity.user.role != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required.")
    return identity


AdminUser = Annotated[Identity, Depends(require_admin)]
