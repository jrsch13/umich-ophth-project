"""Authorize access to station-local session records and media."""

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException

from auth.security import Authenticated, Identity
from openpose_runner import OpenPoseRunnerError, openpose_runner
from session_catalog import session_metadata


@dataclass(frozen=True)
class SessionAccess:
    session_id: str
    directory: Path
    identity: Identity


def require_session_access(session_id: str, identity: Authenticated) -> SessionAccess:
    try:
        directory = openpose_runner._session_dir(session_id)
    except (OpenPoseRunnerError, OSError, ValueError, RuntimeError) as error:
        raise HTTPException(status_code=404, detail="Session not found.") from error

    owner = session_metadata(directory).get("owner_user_id")
    if not directory.is_dir() or (identity.user.role != "admin" and owner != identity.user.id):
        raise HTTPException(status_code=404, detail="Session not found.")
    return SessionAccess(session_id, directory, identity)


AccessibleSession = Annotated[SessionAccess, Depends(require_session_access)]
