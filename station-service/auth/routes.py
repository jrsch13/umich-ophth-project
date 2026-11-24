from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import web_origin
from .db import Database
from .models import AuthSession, Invitation, User, utcnow
from .security import (
    AdminUser, Authenticated, BROWSER_SECONDS, MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH,
    NATIVE_SECONDS, TOKEN_LENGTH, authenticate_password, cookie_name, new_token,
    normalize_email, password_hasher, rate_limit_login, require_browser_origin,
    require_secure_transport, token_hash,
)


router = APIRouter()
INVITE_LIFETIME = timedelta(hours=24)


class AuthInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class Credentials(AuthInput):
    email: Annotated[str, Field(min_length=1, max_length=320)]
    password: Annotated[str, Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)]


class IdentityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    role: Literal["resident", "admin"]


class NativeSessionResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class InvitationRequest(AuthInput):
    email: EmailStr


class InvitationToken(AuthInput):
    token: Annotated[str, Field(min_length=TOKEN_LENGTH, max_length=TOKEN_LENGTH, pattern=r"^[A-Za-z0-9_-]+$")]


class InvitationAcceptance(InvitationToken):
    email: EmailStr
    password: Annotated[str, Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)]


def _start_auth_session(db: Session, user: User, kind: str, lifetime: int) -> str:
    token = new_token()
    now = utcnow()
    db.execute(delete(AuthSession).where(AuthSession.expires_at <= now))
    db.add(AuthSession(
        token_hash=token_hash(token), user_id=user.id, kind=kind,
        created_at=now, expires_at=now + timedelta(seconds=lifetime),
    ))
    db.commit()
    return token


@router.post(
    "/auth/login", status_code=204,
    dependencies=[Depends(require_secure_transport), Depends(require_browser_origin), Depends(rate_limit_login)],
)
def login(credentials: Credentials, request: Request, db: Database) -> Response:
    user = authenticate_password(db, credentials.email, credentials.password)
    name = cookie_name(request)
    previous = request.cookies.get(name)
    if previous and len(previous) == TOKEN_LENGTH:
        db.execute(delete(AuthSession).where(
            AuthSession.token_hash == token_hash(previous), AuthSession.kind == "browser",
        ))
    token = _start_auth_session(db, user, "browser", BROWSER_SECONDS)
    response = Response(status_code=204)
    response.set_cookie(
        name, token, max_age=BROWSER_SECONDS, path="/", httponly=True,
        secure=request.url.scheme == "https", samesite="strict",
    )
    return response


@router.post("/auth/token", dependencies=[Depends(require_secure_transport)])
def native_token(credentials: Credentials, request: Request, db: Database) -> NativeSessionResponse:
    if "origin" in request.headers or "sec-fetch-site" in request.headers:
        raise HTTPException(status_code=403, detail="Use the browser login endpoint.")
    rate_limit_login(request)
    user = authenticate_password(db, credentials.email, credentials.password)
    token = _start_auth_session(db, user, "native", NATIVE_SECONDS)
    return NativeSessionResponse(access_token=token, expires_in=NATIVE_SECONDS)


@router.get("/auth/me")
def me(identity: Authenticated) -> IdentityResponse:
    return IdentityResponse.model_validate(identity.user)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, identity: Authenticated, db: Database) -> Response:
    db.execute(delete(AuthSession).where(AuthSession.token_hash == identity.token_hash))
    db.commit()
    response = Response(status_code=204)
    if identity.kind == "browser":
        response.delete_cookie(
            cookie_name(request), path="/", secure=request.url.scheme == "https", httponly=True, samesite="strict",
        )
    return response


class InvitationCreated(BaseModel):
    email: str
    invitation_url: str
    expires_at: datetime


def _duplicate_account(user: User | None) -> bool:
    return user is not None and (user.is_active or user.role != "resident")


@router.post("/admin/invitations", status_code=201)
def create_invitation(payload: InvitationRequest, identity: AdminUser, db: Database) -> InvitationCreated:
    email = normalize_email(payload.email)
    user = db.scalar(select(User).where(User.email == email))
    if _duplicate_account(user):
        raise HTTPException(status_code=409, detail="An account already exists for this email.")

    now = utcnow()
    token = new_token()
    expiration = now + INVITE_LIFETIME
    fields = {
        "token_hash": token_hash(token), "invited_by_user_id": identity.user.id,
        "expires_at": expiration, "accepted_at": None, "created_at": now,
    }
    existing_invitation = db.scalar(select(Invitation).where(Invitation.email == email))
    if existing_invitation is None:
        db.add(Invitation(email=email, **fields))
    else:
        changed = db.execute(update(Invitation).where(
            Invitation.id == existing_invitation.id,
            Invitation.token_hash == existing_invitation.token_hash,
            or_(Invitation.accepted_at.is_not(None), Invitation.expires_at <= now),
            ~select(User.id).where(
                User.email == email, or_(User.is_active.is_(True), User.role != "resident"),
            ).exists(),
        ).values(**fields).execution_options(synchronize_session=False))
        if changed.rowcount != 1:
            raise HTTPException(status_code=409, detail="An account or pending invitation already exists for this email.")
    try:
        db.commit()
    except IntegrityError as error:
        raise HTTPException(status_code=409, detail="An invitation already exists for this email.") from error
    return InvitationCreated(
        email=email, invitation_url=f"{web_origin()}/accept-invitation#token={token}", expires_at=expiration,
    )


def _pending_invitation(hashed: str, now: datetime):
    return (
        Invitation.token_hash == hashed, Invitation.accepted_at.is_(None), Invitation.expires_at > now,
    )


def _invalid_invitation() -> HTTPException:
    return HTTPException(status_code=400, detail="This invitation is invalid, expired, or already used.")


@router.post(
    "/auth/invitations/preview",
    dependencies=[Depends(require_secure_transport), Depends(require_browser_origin)],
)
def preview_invitation(payload: InvitationToken, db: Database) -> InvitationRequest:
    email = db.scalar(select(Invitation.email).where(*_pending_invitation(token_hash(payload.token), utcnow())))
    if email is None:
        raise _invalid_invitation()
    return InvitationRequest(email=email)


@router.post(
    "/auth/invitations/accept", status_code=201,
    dependencies=[Depends(require_secure_transport), Depends(require_browser_origin), Depends(rate_limit_login)],
)
def accept_invitation(payload: InvitationAcceptance, db: Database) -> IdentityResponse:
    hashed = token_hash(payload.token)
    email = normalize_email(payload.email)
    eligible = db.scalar(select(Invitation.id).where(
        *_pending_invitation(hashed, utcnow()), Invitation.email == email,
    ))
    if eligible is None:
        raise _invalid_invitation()
    db.rollback()  # Finish the read before hashing and opening the write transaction.
    password_hash = password_hasher.hash(payload.password)

    now = utcnow()
    claimed = db.execute(update(Invitation).where(
        *_pending_invitation(hashed, now), Invitation.email == email,
    ).values(accepted_at=now))
    if claimed.rowcount != 1:
        raise _invalid_invitation()

    user = db.scalar(select(User).where(User.email == email))
    if _duplicate_account(user):
        raise HTTPException(status_code=409, detail="An account already exists for this email.")
    if user is None:
        user = User(email=email, password_hash=password_hash, role="resident")
        db.add(user)
    else:
        user.password_hash = password_hash
        user.is_active = True
        db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    try:
        db.commit()
    except IntegrityError as error:
        raise HTTPException(status_code=409, detail="An account already exists for this email.") from error
    return IdentityResponse.model_validate(user)
