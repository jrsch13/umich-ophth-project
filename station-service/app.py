from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, field_validator

from camera_config import load_config, save_config
from cameras import detect_cameras, stream_camera_preview
from openpose_runner import OpenPoseRunnerError, openpose_runner
from session_catalog import list_sessions, plot_path, session_detail
from session_manager import SessionError, session_manager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await asyncio.to_thread(session_manager.shutdown)


app = FastAPI(title="Station Service", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/openpose/status")
def get_openpose_status() -> dict[str, Any]:
    return openpose_runner.backend_status()


@app.get("/cameras")
def get_cameras() -> dict[str, list[dict[str, Any]]]:
    return {"cameras": detect_cameras()}


@app.get("/cameras/{camera_id}/preview")
async def get_camera_preview(camera_id: int, request: Request):
    return await stream_camera_preview(camera_id, request)


@app.get("/camera-config")
def get_camera_config() -> dict[str, Any]:
    return load_config()


class SessionStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resident_id: str
    session_label: str

    @field_validator("resident_id", "session_label")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("This field cannot be empty.")
        return normalized


@app.post("/sessions/start")
def start_session(request: SessionStartRequest) -> dict[str, Any]:
    try:
        return session_manager.start(request.resident_id, request.session_label)
    except SessionError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


@app.post("/sessions/stop")
def stop_session() -> dict[str, Any]:
    try:
        result = session_manager.stop()
    except SessionError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    try:
        result["analysis_status"] = openpose_runner.start(result["session_id"])
    except OpenPoseRunnerError as error:
        logger.exception("Could not launch analysis for saved session=%s", result["session_id"])
        result["analysis_status"] = openpose_runner.mark_start_failed(
            result["session_id"],
            "Analysis could not be started. Check the station service log.",
        )
    return result


@app.get("/sessions/current")
def get_current_session() -> dict[str, Any]:
    return session_manager.current()


@app.get("/sessions")
def get_sessions() -> dict[str, Any]:
    return {"sessions": list_sessions()}


@app.get("/sessions/{session_id}")
def get_session(session_id: str) -> dict[str, Any]:
    try:
        return session_detail(session_id)
    except OpenPoseRunnerError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


@app.get("/sessions/{session_id}/analysis/{view}/plots/{filename}")
def get_analysis_plot(session_id: str, view: str, filename: str) -> FileResponse:
    try:
        path = plot_path(session_id, view, filename)
    except OpenPoseRunnerError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    return FileResponse(path, media_type="image/png")


@app.post("/sessions/{session_id}/analysis/{view}/retry")
def retry_posture_analysis(session_id: str, view: str) -> dict[str, Any]:
    try:
        return openpose_runner.retry_posture(session_id, view)
    except OpenPoseRunnerError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


@app.get("/sessions/{session_id}/analysis-status")
def get_analysis_status(session_id: str) -> dict[str, Any]:
    try:
        return openpose_runner.get_status(session_id)
    except OpenPoseRunnerError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


@app.post("/sessions/{session_id}/analyze")
def analyze_session(session_id: str) -> dict[str, Any]:
    try:
        return openpose_runner.start(session_id)
    except OpenPoseRunnerError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


class CameraConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    side_camera_id: int | None = None
    rear_camera_id: int | None = None

    @field_validator("side_camera_id", "rear_camera_id")
    @classmethod
    def validate_camera_id(cls, value: int | None) -> int | None:
        if value is None:
            return value
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("Camera IDs must be integers or null.")
        if value < 0:
            raise ValueError("Camera IDs must be zero or higher.")
        return value


@app.put("/camera-config")
def save_camera_config(config: CameraConfigUpdate) -> dict[str, Any]:
    side_camera_id = config.side_camera_id
    rear_camera_id = config.rear_camera_id

    if side_camera_id is not None and rear_camera_id is not None and side_camera_id == rear_camera_id:
        raise HTTPException(status_code=400, detail="Side and Rear cameras must be different.")

    saved = save_config({
        "side_camera_id": side_camera_id,
        "rear_camera_id": rear_camera_id,
    })
    return saved
