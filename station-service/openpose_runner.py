from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from posture_analysis_runner import run_posture_analysis


logger = logging.getLogger(__name__)
STATION_DIR = Path(__file__).resolve().parent
REPO_ROOT = STATION_DIR.parent
SESSIONS_DIR = STATION_DIR / "sessions"
OPENPOSE_SCRIPTS = {
    "cpu": REPO_ROOT / "openpose-pipeline" / "run_openpose_cpu.ps1",
    "wsl": REPO_ROOT / "openpose-pipeline" / "run_openpose_wsl.ps1",
}
VIEWS = ("side", "rear")


class OpenPoseRunnerError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    temporary_path.replace(path)


class OpenPoseRunner:
    def __init__(self) -> None:
        self._guard = threading.RLock()
        self._jobs: set[str] = set()

    def backend_status(self) -> dict[str, Any]:
        configured_backend = os.environ.get("OPENPOSE_BACKEND", "cpu").strip().lower()
        if configured_backend not in OPENPOSE_SCRIPTS:
            return {
                "backend": configured_backend,
                "wrapper_exists": False,
                "ready": False,
                "error": "OPENPOSE_BACKEND must be either 'cpu' or 'wsl'.",
            }

        script = OPENPOSE_SCRIPTS[configured_backend]
        wrapper_exists = script.is_file()
        result: dict[str, Any] = {
            "backend": configured_backend,
            "wrapper_exists": wrapper_exists,
            "ready": wrapper_exists,
        }
        if not wrapper_exists:
            result["error"] = "The configured OpenPose wrapper is missing."
            return result

        if configured_backend == "wsl":
            try:
                wsl_check = subprocess.run(
                    ["wsl.exe", "bash", "-lc", "true"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=10,
                    check=False,
                )
                wsl_available = wsl_check.returncode == 0
            except (OSError, subprocess.SubprocessError):
                wsl_available = False
            result["wsl_available"] = wsl_available
            result["ready"] = wrapper_exists and wsl_available
            if not wsl_available:
                result["error"] = "WSL is unavailable or could not start its configured distribution."
        return result

    def get_status(self, session_id: str) -> dict[str, Any]:
        with self._guard:
            session_dir = self._session_dir(session_id)
            status_path = session_dir / "analysis_status.json"
            if not session_dir.is_dir():
                raise OpenPoseRunnerError(404, "Session not found.")
            if not status_path.is_file():
                return {
                    "status": "pending",
                    "started_at": None,
                    "completed_at": None,
                    "error": None,
                    "views": {
                        view: {"status": "pending", "openpose_status": "pending", "posture_status": "pending"}
                        for view in VIEWS if (session_dir / "raw" / f"{view}.mp4").is_file()
                    },
                }
            try:
                with status_path.open(encoding="utf-8") as handle:
                    status = json.load(handle)
            except (OSError, json.JSONDecodeError) as error:
                raise OpenPoseRunnerError(500, "Could not read the session analysis status.") from error
            if not isinstance(status, dict) or status.get("status") not in {
                "pending",
                "processing",
                "complete",
                "failed",
            }:
                raise OpenPoseRunnerError(500, "The session analysis status file is invalid.")
            if "views" not in status:
                status["views"] = {}
            if not isinstance(status.get("views"), dict):
                raise OpenPoseRunnerError(500, "The session analysis status file is invalid.")
            if status["status"] == "pending":
                for view in VIEWS:
                    if (session_dir / "raw" / f"{view}.mp4").is_file():
                        status["views"].setdefault(view, {"status": "pending"})
            for view_status in status.get("views", {}).values():
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

    def start(self, session_id: str) -> dict[str, Any]:
        backend_status = self.backend_status()
        backend = backend_status["backend"]
        if not backend_status["ready"]:
            detail = backend_status.get("error", "The configured OpenPose backend is not ready.")
            raise OpenPoseRunnerError(503, detail)

        session_dir = self._session_dir(session_id)
        if not session_dir.is_dir():
            raise OpenPoseRunnerError(404, "Session not found.")

        metadata_path = session_dir / "metadata.json"
        try:
            with metadata_path.open(encoding="utf-8") as handle:
                metadata = json.load(handle)
        except (OSError, json.JSONDecodeError) as error:
            raise OpenPoseRunnerError(500, "Could not read the saved session metadata.") from error
        if metadata.get("status") not in {"completed", "completed_with_errors"}:
            raise OpenPoseRunnerError(409, "Analysis can start only after recording has completed.")

        with self._guard:
            status = self.get_status(session_id)
            if session_id in self._jobs:
                raise OpenPoseRunnerError(409, "Analysis is already processing for this session.")
            if status["status"] == "processing":
                status.update({
                    "status": "failed",
                    "completed_at": _timestamp(),
                    "error": "The previous analysis worker did not finish. A retry was requested.",
                })
                self._save_status(session_dir, status)
            if status["status"] == "complete":
                raise OpenPoseRunnerError(409, "Analysis is already complete for this session.")

            existing_views = {
                view: {"status": "pending", "openpose_status": "pending", "posture_status": "pending"}
                for view in VIEWS
                if (session_dir / "raw" / f"{view}.mp4").is_file()
            }
            started_status: dict[str, Any] = {
                "status": "processing",
                "stage": "openpose",
                "backend": backend,
                "started_at": _timestamp(),
                "completed_at": None,
                "error": None,
                "views": existing_views,
            }
            self._save_status(session_dir, started_status)
            self._jobs.add(session_id)
            worker = threading.Thread(
                target=self._run,
                args=(session_id, session_dir, started_status, OPENPOSE_SCRIPTS[backend]),
                name=f"openpose-{session_id}",
                daemon=True,
            )
            try:
                worker.start()
            except RuntimeError as error:
                self._jobs.discard(session_id)
                started_status.update({
                    "status": "failed",
                    "stage": None,
                    "completed_at": _timestamp(),
                    "error": "Could not start the analysis worker. See the session logs.",
                })
                self._save_status(session_dir, started_status)
                raise OpenPoseRunnerError(500, "Could not start session analysis.") from error
            return started_status

    def _run(
        self,
        session_id: str,
        session_dir: Path,
        status: dict[str, Any],
        wrapper_path: Path,
    ) -> None:
        logs_dir = session_dir / "logs"
        failures: list[str] = []
        try:
            logs_dir.mkdir(parents=True, exist_ok=True)
            for view in status["views"]:
                log_relative = f"logs/openpose_{view}.log"
                status["views"][view]["log"] = log_relative
                status["views"][view]["status"] = "processing"
                status["views"][view]["openpose_status"] = "processing"
                status["stage"] = "openpose"
                self._save_status(session_dir, status)
                try:
                    result = self._run_view(
                        session_dir,
                        view,
                        logs_dir / f"openpose_{view}.log",
                        status["backend"],
                        wrapper_path,
                    )
                    status["views"][view].update(result)
                    status["views"][view]["openpose_status"] = "complete"
                    status["views"][view]["posture_status"] = "processing"
                    status["stage"] = "posture_analysis"
                    self._save_status(session_dir, status)
                    try:
                        status["views"][view].update(run_posture_analysis(session_dir, view))
                        status["views"][view]["posture_status"] = "complete"
                        status["views"][view]["status"] = "complete"
                    except Exception as error:
                        summary = f"{view.title()} posture analysis failed: {error}"
                        logger.exception("Posture analysis failed for session=%s view=%s", session_id, view)
                        status["views"][view].update({
                            "status": "failed", "posture_status": "failed", "error": summary,
                        })
                        failures.append(summary)
                except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                    summary = f"{view.title()} analysis failed. See {log_relative}."
                    logger.exception("OpenPose failed for session=%s view=%s", session_id, view)
                    status["views"][view].update({"status": "failed", "openpose_status": "failed", "error": summary, "log": log_relative})
                    failures.append(summary)
                except Exception:
                    summary = f"{view.title()} analysis failed. See {log_relative}."
                    logger.exception("Unexpected OpenPose failure for session=%s view=%s", session_id, view)
                    status["views"][view].update({"status": "failed", "openpose_status": "failed", "error": summary, "log": log_relative})
                    failures.append(summary)
                self._save_status(session_dir, status)

            if not status["views"]:
                failures.append("No raw Side or Rear video was found.")
            status.update({
                "status": "failed" if failures else "complete",
                "stage": None,
                "completed_at": _timestamp(),
                "error": "; ".join(failures) if failures else None,
            })
            with self._guard:
                self._save_status(session_dir, status)
                self._jobs.discard(session_id)
        except Exception:
            logger.exception("Could not finalize OpenPose status for session=%s", session_id)
            status.update({
                "status": "failed",
                "stage": None,
                "completed_at": _timestamp(),
                "error": "Analysis could not be finalized. Check the station service log.",
            })
            try:
                with self._guard:
                    self._save_status(session_dir, status)
                    self._jobs.discard(session_id)
            except OSError:
                logger.exception("Could not save failed OpenPose status for session=%s", session_id)
        finally:
            with self._guard:
                self._jobs.discard(session_id)

    def _run_view(
        self,
        session_dir: Path,
        view: str,
        log_path: Path,
        backend: str,
        wrapper_path: Path,
    ) -> dict[str, Any]:
        video_path = session_dir / "raw" / f"{view}.mp4"
        output_dir = session_dir / "openpose" / view
        json_dir = output_dir / "json"
        labeled_path = session_dir / "labeled-videos" / f"{view}_labeled.avi"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(wrapper_path),
            "-Video",
            str(video_path),
            "-OutputDir",
            str(output_dir),
            "-LabeledVideoPath",
            str(labeled_path),
        ]
        with log_path.open("w", encoding="utf-8") as log_file:
            log_file.write(
                f"Started: {_timestamp()}\n"
                f"OpenPose backend: {backend}\n"
                f"Wrapper: {wrapper_path.name}\n"
                f"Input view: {view}\n"
                f"Command: {subprocess.list2cmdline(command)}\n\n"
            )
            log_file.flush()
            try:
                if not video_path.is_file():
                    raise RuntimeError(f"Input video is missing: {video_path}")
                if not wrapper_path.is_file():
                    raise RuntimeError(f"OpenPose wrapper not found: {wrapper_path}")
                json_dir.mkdir(parents=True, exist_ok=True)
                labeled_path.parent.mkdir(parents=True, exist_ok=True)
                completed = subprocess.run(
                    command,
                    cwd=REPO_ROOT,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    text=True,
                    check=False,
                )
            except (OSError, RuntimeError) as error:
                log_file.write(f"\nERROR: {error}\n")
                raise
            log_file.write(f"\nFinished: {_timestamp()}\nExit code: {completed.returncode}\n")
        if completed.returncode != 0:
            raise RuntimeError(f"OpenPose exited with code {completed.returncode}.")

        json_frame_count = sum(1 for _ in json_dir.glob("*_keypoints.json"))
        if json_frame_count == 0:
            raise RuntimeError("OpenPose completed without producing BODY_25 JSON frames.")
        if not labeled_path.is_file() or labeled_path.stat().st_size == 0:
            raise RuntimeError("OpenPose completed without producing the labeled video.")
        return {
            "json_frame_count": json_frame_count,
            "labeled_video": str(labeled_path.relative_to(session_dir)).replace("\\", "/"),
        }

    def mark_start_failed(self, session_id: str, summary: str) -> dict[str, Any]:
        try:
            session_dir = self._session_dir(session_id)
            status = self.get_status(session_id)
            status.update({
                "status": "failed",
                "stage": None,
                "backend": os.environ.get("OPENPOSE_BACKEND", "cpu").strip().lower(),
                "completed_at": _timestamp(),
                "error": summary,
            })
            self._save_status(session_dir, status)
            return status
        except (OSError, OpenPoseRunnerError):
            logger.exception("Could not persist analysis launch failure for session=%s", session_id)
            return {
                "status": "failed",
                "started_at": None,
                "completed_at": _timestamp(),
                "error": summary,
                "views": {},
            }

    def retry_posture(self, session_id: str, view: str) -> dict[str, Any]:
        if view not in VIEWS:
            raise OpenPoseRunnerError(404, "View not found.")
        session_dir = self._session_dir(session_id)
        if not session_dir.is_dir():
            raise OpenPoseRunnerError(404, "Session not found.")
        json_dir = session_dir / "openpose" / view / "json"
        if not json_dir.is_dir() or not any(json_dir.glob("*_keypoints.json")):
            raise OpenPoseRunnerError(409, f"No OpenPose BODY_25 JSON frames found for {view}.")
        with self._guard:
            if session_id in self._jobs:
                raise OpenPoseRunnerError(409, "Analysis is already processing for this session.")
            status = self.get_status(session_id)
            view_status = status.setdefault("views", {}).setdefault(view, {})
            for key in ("analysis_dir", "summary", "plots"):
                view_status.pop(key, None)
            view_status.update({
                "status": "processing", "openpose_status": "complete",
                "posture_status": "processing", "json_frame_count": sum(1 for _ in json_dir.glob("*_keypoints.json")),
                "error": None,
            })
            labeled = session_dir / "labeled-videos" / f"{view}_labeled.avi"
            if labeled.is_file() and labeled.stat().st_size:
                view_status["labeled_video"] = f"labeled-videos/{view}_labeled.avi"
            status.update({"status": "processing", "stage": "posture_analysis", "completed_at": None, "error": None})
            self._save_status(session_dir, status)
            self._jobs.add(session_id)
            worker = threading.Thread(
                target=self._retry_posture_worker,
                args=(session_id, session_dir, view, status),
                name=f"posture-{session_id}-{view}",
                daemon=True,
            )
            try:
                worker.start()
            except RuntimeError as error:
                self._jobs.discard(session_id)
                view_status.update({"status": "failed", "posture_status": "failed", "error": str(error)})
                status.update({"status": "failed", "stage": None, "error": str(error)})
                self._save_status(session_dir, status)
                raise OpenPoseRunnerError(500, "Could not start posture analysis worker.") from error
            return status

    def _retry_posture_worker(
        self, session_id: str, session_dir: Path, view: str, status: dict[str, Any]
    ) -> None:
        try:
            result = run_posture_analysis(session_dir, view)
            status["views"][view].update(result)
            status["views"][view].update({"status": "complete", "posture_status": "complete", "error": None})
        except Exception as error:
            logger.exception("Posture retry failed for session=%s view=%s", session_id, view)
            status["views"][view].update({
                "status": "failed", "posture_status": "failed", "error": f"{view.title()} posture analysis failed: {error}",
            })
        finally:
            with self._guard:
                views = status["views"].values()
                failed = [item.get("error") for item in views if item.get("status") == "failed"]
                complete = bool(status["views"]) and all(item.get("status") == "complete" for item in views)
                status.update({
                    "status": "complete" if complete else "failed" if failed else "pending",
                    "stage": None,
                    "completed_at": _timestamp(),
                    "error": "; ".join(item for item in failed if item) or None,
                })
                try:
                    self._save_status(session_dir, status)
                finally:
                    self._jobs.discard(session_id)

    def _save_status(self, session_dir: Path, status: dict[str, Any]) -> None:
        with self._guard:
            _write_json(session_dir / "analysis_status.json", status)

    @staticmethod
    def _session_dir(session_id: str) -> Path:
        if not session_id or Path(session_id).name != session_id or session_id in {".", ".."}:
            raise OpenPoseRunnerError(400, "Invalid session ID.")
        session_dir = (SESSIONS_DIR / session_id).resolve()
        if session_dir.parent != SESSIONS_DIR.resolve():
            raise OpenPoseRunnerError(400, "Invalid session ID.")
        return session_dir


openpose_runner = OpenPoseRunner()
