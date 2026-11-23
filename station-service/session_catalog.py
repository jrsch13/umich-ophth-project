"""Read-only session descriptions for the station API."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from openpose_runner import OpenPoseRunnerError, SESSIONS_DIR, VIEWS, openpose_runner
from session_analysis_data import posture_summaries


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
        if isinstance(value, dict):
            return value
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _recorded_at(metadata: dict[str, Any], path: Path) -> str:
    for key in ("started_at", "ended_at", "created_at"):
        value = metadata.get(key)
        if isinstance(value, str):
            try:
                datetime.fromisoformat(value)
                return value
            except ValueError:
                pass
    return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat()


def session_detail(
    session_id: str,
    *,
    include_posture_summaries: bool = True,
) -> dict[str, Any]:
    session_dir = openpose_runner._session_dir(session_id)
    if not session_dir.is_dir():
        raise OpenPoseRunnerError(404, "Session not found.")
    metadata = _read_json(session_dir / "metadata.json")
    status = openpose_runner.get_status(session_id)
    views: dict[str, Any] = {}
    for view in VIEWS:
        raw = session_dir / "raw" / f"{view}.mp4"
        json_dir = session_dir / "openpose" / view / "json"
        analysis_dir = session_dir / "analysis" / view
        labeled = session_dir / "labeled-videos" / f"{view}_labeled.avi"
        if not (raw.is_file() or json_dir.is_dir() or analysis_dir.is_dir() or view in status.get("views", {})):
            continue
        plots_dir = analysis_dir / "plots"
        plots = [
            {"name": path.name, "url": f"/sessions/{quote(session_id)}/analysis/{view}/plots/{quote(path.name)}"}
            for path in sorted(plots_dir.glob("*.png"))
            if path.is_file() and path.stat().st_size > 0
        ] if plots_dir.is_dir() else []
        views[view] = {
            "analysis_status": status.get("views", {}).get(view, {}),
            "plots": plots,
            "summary": _read_json(analysis_dir / "summary.json") if (analysis_dir / "summary.json").is_file() else None,
            "labeled_video_available": labeled.is_file() and labeled.stat().st_size > 0,
        }
    detail = {
        "session_id": session_id,
        "metadata": metadata,
        "analysis_status": status,
        "available_views": list(views),
        "views": views,
    }
    if include_posture_summaries:
        detail["posture_summaries"] = posture_summaries(session_dir, metadata)
    return detail


def list_sessions() -> list[dict[str, Any]]:
    if not SESSIONS_DIR.is_dir():
        return []
    sessions = []
    for path in SESSIONS_DIR.iterdir():
        if not path.is_dir() or path.is_symlink():
            continue
        metadata = _read_json(path / "metadata.json")
        if not metadata:
            continue
        detail = session_detail(path.name, include_posture_summaries=False)
        sessions.append({
            "session_id": path.name,
            "resident_or_study_id": metadata.get("resident_or_study_id"),
            "session_label": metadata.get("session_label"),
            "recorded_at": _recorded_at(metadata, path),
            "analysis_status": detail["analysis_status"]["status"],
            "available_views": detail["available_views"],
            "plots_available": any(item["plots"] for item in detail["views"].values()),
        })
    sessions.sort(key=lambda item: datetime.fromisoformat(item["recorded_at"]).timestamp(), reverse=True)
    return sessions


def plot_path(session_id: str, view: str, filename: str) -> Path:
    if view not in VIEWS:
        raise OpenPoseRunnerError(404, "Plot not found.")
    session_dir = openpose_runner._session_dir(session_id)
    if not session_dir.is_dir() or filename != Path(filename).name or not filename.endswith(".png"):
        raise OpenPoseRunnerError(404, "Plot not found.")
    plots_dir = session_dir / "analysis" / view / "plots"
    path = (plots_dir / filename).resolve()
    if not path.is_relative_to(session_dir.resolve()) or path.parent != plots_dir.resolve() or not path.is_file():
        raise OpenPoseRunnerError(404, "Plot not found.")
    return path
