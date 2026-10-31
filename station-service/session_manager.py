from __future__ import annotations

import csv
import json
import math
import re
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2

from camera_config import load_config
from cameras import camera_lock, open_camera
from recording import CameraRecorder

SESSIONS_DIR = Path(__file__).resolve().parent / "sessions"


class SessionError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    temporary_path.replace(path)


def _session_folder_name(resident_id: str) -> str:
    safe_id = re.sub(r"[^A-Za-z0-9_-]+", "_", resident_id).strip("_") or "session"
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    return f"{safe_id}_{timestamp}"


class SessionManager:
    def __init__(self) -> None:
        self._guard = threading.RLock()
        self._active_session: dict[str, Any] | None = None

    def current(self) -> dict[str, Any]:
        with self._guard:
            session = self._active_session
            if session is None:
                return {"status": "idle"}

            elapsed = (time.perf_counter_ns() - session["started_perf_ns"]) / 1_000_000_000
            errors = {
                recorder.role: recorder.error
                for recorder in session["recorders"]
                if recorder.error is not None
            }
            return {
                "status": "recording",
                "session_id": session["session_id"],
                "elapsed_seconds": round(elapsed, 1),
                "selected_cameras": session["selected_cameras"],
                "camera_errors": errors,
            }

    def start(self, resident_id: str, session_label: str) -> dict[str, Any]:
        with self._guard:
            if self._active_session is not None:
                raise SessionError(409, "A session is already recording. Stop it before starting another.")

            config = load_config()
            selected_cameras = {
                "side": config.get("side_camera_id"),
                "rear": config.get("rear_camera_id"),
            }
            configured = [
                (role, camera_id)
                for role, camera_id in selected_cameras.items()
                if camera_id is not None
            ]
            if not configured:
                raise SessionError(400, "No cameras are configured. Assign at least one camera on the Cameras page.")

            ids: set[int] = set()
            for role, camera_id in configured:
                if isinstance(camera_id, bool) or not isinstance(camera_id, int) or not 0 <= camera_id <= 8:
                    raise SessionError(400, f"The saved {role.title()} camera assignment is invalid. Reassign it on the Cameras page.")
                if camera_id in ids:
                    raise SessionError(400, "Side and Rear cannot be assigned to the same camera.")
                ids.add(camera_id)

            resources: list[dict[str, Any]] = []
            recorders: list[CameraRecorder] = []
            session_dir: Path | None = None
            session_dir_created = False

            try:
                for role, camera_id in configured:
                    lock = camera_lock(camera_id)
                    if not lock.acquire(blocking=False):
                        raise SessionError(
                            409,
                            f"The {role.title()} camera is busy. Leave the Cameras page and try again after its preview closes.",
                        )

                    resource = {
                        "role": role,
                        "camera_id": camera_id,
                        "lock": lock,
                        "camera": None,
                        "writer": None,
                        "timestamp_file": None,
                        "recorder": None,
                    }
                    resources.append(resource)

                    camera = open_camera(camera_id)
                    if camera is None:
                        raise SessionError(
                            503,
                            f"The configured {role.title()} camera is unavailable. Reconnect it and rescan cameras.",
                        )
                    resource["camera"] = camera

                    try:
                        ok, first_frame = camera.read()
                    except cv2.error as error:
                        raise SessionError(503, f"Could not read the configured {role.title()} camera.") from error
                    if not ok or first_frame is None:
                        raise SessionError(
                            503,
                            f"The configured {role.title()} camera did not provide a frame. Reconnect it and try again.",
                        )

                    height, width = first_frame.shape[:2]
                    reported_fps = float(camera.get(cv2.CAP_PROP_FPS) or 0)
                    recording_fps = reported_fps if math.isfinite(reported_fps) and reported_fps > 0 else 30.0
                    resource.update({
                        "first_frame": first_frame,
                        "width": int(width),
                        "height": int(height),
                        "reported_fps": (
                            reported_fps
                            if math.isfinite(reported_fps) and reported_fps > 0
                            else None
                        ),
                        "recording_fps": recording_fps,
                    })

                try:
                    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
                    folder_name = _session_folder_name(resident_id)
                    session_dir = SESSIONS_DIR / folder_name
                    suffix = 1
                    while session_dir.exists():
                        session_dir = SESSIONS_DIR / f"{folder_name}_{suffix}"
                        suffix += 1
                    session_dir.mkdir()
                    session_dir_created = True
                    (session_dir / "raw").mkdir()
                except OSError as error:
                    raise SessionError(500, "Could not create the session folder.") from error

                for resource in resources:
                    role = resource["role"]
                    raw_dir = session_dir / "raw"
                    writer = cv2.VideoWriter(
                        str(raw_dir / f"{role}.mp4"),
                        cv2.VideoWriter_fourcc(*"mp4v"),
                        resource["recording_fps"],
                        (resource["width"], resource["height"]),
                    )
                    resource["writer"] = writer
                    if not writer.isOpened():
                        raise SessionError(
                            500,
                            f"Could not open the {role.title()} MP4 writer. Check the camera format and storage permissions.",
                        )

                    timestamp_file = (raw_dir / f"{role}_timestamps.csv").open(
                        "w",
                        newline="",
                        encoding="utf-8",
                    )
                    resource["timestamp_file"] = timestamp_file
                    timestamp_writer = csv.writer(timestamp_file)
                    timestamp_writer.writerow(
                        ("frame_index", "seconds_from_session_start", "wall_time_local")
                    )

                    recorder = CameraRecorder(
                        role=role,
                        camera_id=resource["camera_id"],
                        camera=resource["camera"],
                        lock=resource["lock"],
                        writer=writer,
                        timestamp_file=timestamp_file,
                        timestamp_writer=timestamp_writer,
                        first_frame=resource["first_frame"],
                        session_start_ns=0,
                        width=resource["width"],
                        height=resource["height"],
                    )
                    resource["recorder"] = recorder
                    recorders.append(recorder)

                started_at = datetime.now().astimezone()
                started_perf_ns = time.perf_counter_ns()
                for recorder in recorders:
                    recorder.session_start_ns = started_perf_ns

                session_id = session_dir.name
                metadata = {
                    "session_id": session_id,
                    "resident_or_study_id": resident_id,
                    "session_label": session_label,
                    "status": "recording",
                    "started_at": started_at.isoformat(timespec="milliseconds"),
                    "selected_cameras": selected_cameras,
                }
                try:
                    _write_json(session_dir / "metadata.json", metadata)
                except OSError as error:
                    raise SessionError(500, "Could not write session metadata.") from error

                started_recorders: list[CameraRecorder] = []
                try:
                    for recorder in recorders:
                        recorder.start()
                        started_recorders.append(recorder)
                except RuntimeError as error:
                    for recorder in started_recorders:
                        recorder.stop()
                    for recorder in started_recorders:
                        recorder.join()
                    raise SessionError(500, "Could not start all configured camera recorders.") from error

                self._active_session = {
                    "session_id": session_id,
                    "session_dir": session_dir,
                    "metadata": metadata,
                    "started_perf_ns": started_perf_ns,
                    "recorders": recorders,
                    "selected_cameras": selected_cameras,
                    "camera_details": {
                        item["role"]: {
                            "resolution": f"{item['width']}x{item['height']}",
                            "reported_fps": item["reported_fps"],
                            "recording_fps": item["recording_fps"],
                        }
                        for item in resources
                    },
                }
                return {"status": "recording", "session_id": session_id}
            except SessionError:
                self._cleanup_resources(resources)
                if session_dir is not None and session_dir_created:
                    self._remove_failed_session(session_dir)
                raise
            except (OSError, cv2.error) as error:
                self._cleanup_resources(resources)
                if session_dir is not None and session_dir_created:
                    self._remove_failed_session(session_dir)
                raise SessionError(500, "Could not start recording. Check camera access and session storage.") from error
            except Exception:
                self._cleanup_resources(resources)
                if session_dir is not None and session_dir_created:
                    self._remove_failed_session(session_dir)
                raise

    def stop(self) -> dict[str, Any]:
        with self._guard:
            session = self._active_session
            if session is None:
                raise SessionError(409, "There is no active recording to stop.")

            recorders: list[CameraRecorder] = session["recorders"]
            for recorder in recorders:
                recorder.stop()
            for recorder in recorders:
                recorder.join()

            ended_at = datetime.now().astimezone()
            ended_perf_ns = time.perf_counter_ns()
            duration_seconds = (ended_perf_ns - session["started_perf_ns"]) / 1_000_000_000
            errors = {
                recorder.role: recorder.error
                for recorder in recorders
                if recorder.error is not None
            }
            metadata = dict(session["metadata"])
            metadata.update({
                "status": "completed_with_errors" if errors else "completed",
                "ended_at": ended_at.isoformat(timespec="milliseconds"),
                "duration_seconds": round(duration_seconds, 3),
                "frame_counts": {
                    recorder.role: recorder.frame_count for recorder in recorders
                },
                "camera_details": session["camera_details"],
                "camera_errors": errors,
            })

            save_error: OSError | None = None
            try:
                _write_json(session["session_dir"] / "metadata.json", metadata)
                _write_json(
                    session["session_dir"] / "analysis_status.json",
                    {"status": "pending"},
                )
            except OSError as error:
                save_error = error
            finally:
                self._active_session = None

            if save_error is not None:
                raise SessionError(
                    500,
                    "Recording stopped, but session metadata could not be saved.",
                ) from save_error

            return {
                "status": "saved",
                "session_id": session["session_id"],
                "session_path": str(session["session_dir"]),
                "metadata": metadata,
            }

    def shutdown(self) -> None:
        with self._guard:
            if self._active_session is not None:
                self.stop()

    @staticmethod
    def _cleanup_resources(resources: list[dict[str, Any]]) -> None:
        cleanup_errors: list[Exception] = []
        for resource in reversed(resources):
            try:
                recorder = resource["recorder"]
                if recorder is not None:
                    recorder.stop()
                    recorder.join()
                    recorder.cleanup_unstarted()
                    continue

                try:
                    writer = resource["writer"]
                    if writer is not None:
                        writer.release()
                finally:
                    try:
                        timestamp_file = resource["timestamp_file"]
                        if timestamp_file is not None:
                            timestamp_file.close()
                    finally:
                        try:
                            camera = resource["camera"]
                            if camera is not None:
                                camera.release()
                        finally:
                            resource["lock"].release()
            except (OSError, cv2.error, RuntimeError) as error:
                cleanup_errors.append(error)

        if cleanup_errors:
            raise SessionError(500, "A camera resource could not be released after startup failed.") from cleanup_errors[0]

    @staticmethod
    def _remove_failed_session(session_dir: Path) -> None:
        try:
            shutil.rmtree(session_dir)
        except OSError as error:
            raise SessionError(500, "Incomplete session files could not be removed.") from error


session_manager = SessionManager()
