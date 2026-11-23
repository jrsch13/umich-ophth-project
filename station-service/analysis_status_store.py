"""Synchronized, atomic persistence for per-session analysis status."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable


logger = logging.getLogger(__name__)
VIEWS = ("side", "rear")
_REPLACE_ATTEMPTS = 8
_REPLACE_DELAYS = (0.025, 0.05, 0.1, 0.2, 0.2, 0.2, 0.2)
_READ_ATTEMPTS = 3
_READ_DELAYS = (0.02, 0.04)
_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.RLock] = {}


class InvalidAnalysisStatusError(ValueError):
    """Raised when a persistent status file is malformed or has an invalid shape."""


def _lock_for(path: Path) -> threading.RLock:
    key = os.path.normcase(os.path.abspath(os.fspath(path)))
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[key] = lock
        return lock


def _default_status(session_dir: Path, views: tuple[str, ...]) -> dict[str, Any]:
    return {
        "status": "pending",
        "started_at": None,
        "completed_at": None,
        "error": None,
        "views": {
            view: {
                "status": "pending",
                "openpose_status": "pending",
                "posture_status": "pending",
            }
            for view in views
            if (session_dir / "raw" / f"{view}.mp4").is_file()
        },
    }


def _read_locked(path: Path, views: tuple[str, ...]) -> dict[str, Any]:
    if not path.is_file():
        return _default_status(path.parent, views)

    last_error: OSError | json.JSONDecodeError | None = None
    for attempt in range(_READ_ATTEMPTS):
        try:
            with path.open(encoding="utf-8") as handle:
                status = json.load(handle)
            break
        except (OSError, json.JSONDecodeError) as error:
            last_error = error
            if attempt + 1 < _READ_ATTEMPTS:
                time.sleep(_READ_DELAYS[attempt])
    else:
        assert last_error is not None
        raise last_error

    if not isinstance(status, dict) or status.get("status") not in {
        "pending",
        "processing",
        "complete",
        "failed",
    }:
        raise InvalidAnalysisStatusError("The session analysis status file is invalid.")
    if "views" not in status:
        status["views"] = {}
    if not isinstance(status["views"], dict):
        raise InvalidAnalysisStatusError("The session analysis status file is invalid.")

    if status["status"] == "pending":
        for view in views:
            if (path.parent / "raw" / f"{view}.mp4").is_file():
                status["views"].setdefault(view, {"status": "pending"})

    for view_status in status["views"].values():
        if not isinstance(view_status, dict):
            raise InvalidAnalysisStatusError("The session analysis status file is invalid.")
        if "openpose_status" not in view_status:
            view_status["openpose_status"] = view_status.get("status", "pending")
        if "posture_status" not in view_status:
            view_status["posture_status"] = (
                "complete" if view_status.get("analysis_dir") else "pending"
            )
        if view_status["openpose_status"] == "complete" and view_status["posture_status"] == "pending":
            view_status["status"] = "pending"
    if status["status"] == "complete" and any(
        item["posture_status"] != "complete" for item in status["views"].values()
    ):
        status["status"] = "pending"
        status["stage"] = "posture_analysis"
    return status


def read_status(path: Path, *, views: tuple[str, ...] = VIEWS) -> dict[str, Any]:
    """Read and normalize a status file while excluding in-process replacements."""
    with _lock_for(path):
        return _read_locked(path, views)


def _atomic_write_locked(path: Path, payload: dict[str, Any]) -> None:
    temporary_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary_path.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        for attempt in range(_REPLACE_ATTEMPTS):
            try:
                os.replace(temporary_path, path)
                return
            except PermissionError:
                if attempt + 1 >= _REPLACE_ATTEMPTS:
                    raise
                logger.warning(
                    "Transient lock replacing analysis_status.json for session=%s; retry %d/%d",
                    path.parent.name,
                    attempt + 2,
                    _REPLACE_ATTEMPTS,
                )
                time.sleep(_REPLACE_DELAYS[attempt])
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def write_status(path: Path, payload: dict[str, Any]) -> None:
    """Replace the complete status document atomically."""
    with _lock_for(path):
        _atomic_write_locked(path, payload)


def update_status(
    path: Path,
    updater: Callable[[dict[str, Any]], None],
    *,
    views: tuple[str, ...] = VIEWS,
) -> dict[str, Any]:
    """Apply a read-modify-write callback under the status file's session lock."""
    with _lock_for(path):
        status = _read_locked(path, views)
        updater(status)
        _atomic_write_locked(path, status)
        return status
