from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, StrictStr, field_validator

from cameras import camera_inventory, stream_camera_preview
from openpose_runner import OpenPoseRunnerError, openpose_runner
from session_catalog import list_sessions, plot_path, session_detail
from session_analysis_data import AnalysisDataError, metric_time_series, saved_video_frame
from session_manager import SessionError, session_manager
from station_cameras import station_camera_manager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await asyncio.to_thread(station_camera_manager.start)
    try:
        yield
    finally:
        await asyncio.to_thread(session_manager.shutdown)
        await asyncio.to_thread(station_camera_manager.shutdown)


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
    return {"cameras": camera_inventory()}


@app.get("/cameras/{camera_id}/preview")
async def get_camera_preview(camera_id: str, request: Request):
    return await stream_camera_preview(camera_id, request)


@app.post("/cameras/rescan")
def rescan_cameras() -> dict[str, list[dict[str, Any]]]:
    return {"cameras": station_camera_manager.rescan(reason="explicit")}


@app.get("/camera-config")
def get_camera_config() -> dict[str, Any]:
    config = station_camera_manager.get_camera_config()
    side_camera_id = config.get("side_camera_id")
    rear_camera_id = config.get("rear_camera_id")
    duplicate_assignment = side_camera_id is not None and side_camera_id == rear_camera_id
    config["needs_attention"] = {
        "side": (
            side_camera_id is not None
            and (not isinstance(side_camera_id, str) or not side_camera_id.startswith("dshow:"))
        ) or duplicate_assignment,
        "rear": (
            rear_camera_id is not None
            and (not isinstance(rear_camera_id, str) or not rear_camera_id.startswith("dshow:"))
        ) or duplicate_assignment,
    }
    return config


class SessionStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resident_id: str = ""
    session_label: str

    @field_validator("resident_id")
    @classmethod
    def strip_resident_id(cls, value: str) -> str:
        return value.strip()

    @field_validator("session_label")
    @classmethod
    def strip_session_label(cls, value: str) -> str:
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


@app.get("/sessions/{session_id}/analysis/metrics/{metric}")
def get_session_metric_time_series(session_id: str, metric: str) -> dict[str, Any]:
    try:
        session_dir = openpose_runner._session_dir(session_id)
        if not session_dir.is_dir():
            raise OpenPoseRunnerError(404, "Session not found.")
        return metric_time_series(session_dir, metric)
    except OpenPoseRunnerError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    except AnalysisDataError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


@app.get("/sessions/{session_id}/analysis/frame")
def get_session_analysis_frame(
    session_id: str,
    view: str,
    frame: int = Query(ge=0),
) -> Response:
    try:
        session_dir = openpose_runner._session_dir(session_id)
        if not session_dir.is_dir():
            raise OpenPoseRunnerError(404, "Session not found.")
        image = saved_video_frame(session_dir, view, frame)
        return Response(content=image, media_type="image/jpeg")
    except OpenPoseRunnerError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    except AnalysisDataError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


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

    side_camera_id: StrictStr | None = None
    rear_camera_id: StrictStr | None = None

    @field_validator("side_camera_id", "rear_camera_id")
    @classmethod
    def validate_camera_id(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Camera IDs must be non-empty stable device IDs or null.")
        return value


@app.put("/camera-config")
def save_camera_config(config: CameraConfigUpdate) -> dict[str, Any]:
    side_camera_id = config.side_camera_id
    rear_camera_id = config.rear_camera_id

    if side_camera_id is not None and rear_camera_id is not None and side_camera_id == rear_camera_id:
        raise HTTPException(status_code=400, detail="Side and Rear cameras must be different.")

    try:
        saved = station_camera_manager.set_assignments(side_camera_id, rear_camera_id)
    except KeyError as error:
        raise HTTPException(
            status_code=409,
            detail="The selected physical camera is not in the current inventory. Rescan and reassign it.",
        ) from error
    return saved
