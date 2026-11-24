from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, StrictStr, field_validator
from sqlalchemy import select

from auth.config import allowed_web_origins
from auth.db import Database
from auth.models import User
from auth.routes import router as auth_router
from auth.security import Authenticated, StationUser, require_station
from cameras import camera_inventory, stream_camera_preview
from openpose_runner import OpenPoseRunnerError, openpose_runner
from session_access import AccessibleSession
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
app.include_router(auth_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_web_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def prevent_shared_response_caching(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, error: RequestValidationError):
    if request.url.path.startswith(("/auth/", "/admin/invitations")):
        return JSONResponse(status_code=422, content={"detail": "Check the required fields and try again."})
    return await request_validation_exception_handler(request, error)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/openpose/status")
def get_openpose_status(_identity: StationUser) -> dict[str, Any]:
    return openpose_runner.backend_status()


@app.get("/cameras")
def get_cameras(_identity: StationUser) -> dict[str, list[dict[str, Any]]]:
    return {"cameras": camera_inventory()}


@app.get("/cameras/{camera_id}/preview")
async def get_camera_preview(camera_id: str, request: Request, _identity: StationUser):
    return await stream_camera_preview(camera_id, request)


@app.post("/cameras/rescan")
def rescan_cameras(_identity: StationUser) -> dict[str, list[dict[str, Any]]]:
    return {"cameras": station_camera_manager.rescan(reason="explicit")}


@app.get("/camera-config")
def get_camera_config(_identity: StationUser) -> dict[str, Any]:
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

    session_label: str

    @field_validator("session_label")
    @classmethod
    def strip_session_label(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("This field cannot be empty.")
        return normalized


@app.post("/sessions/start")
def start_session(request: SessionStartRequest, identity: StationUser) -> dict[str, Any]:
    try:
        return session_manager.start(identity.user.id, request.session_label)
    except SessionError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


@app.post("/sessions/stop")
def stop_session(identity: StationUser) -> dict[str, Any]:
    try:
        owner = None if identity.user.role == "admin" else identity.user.id
        result = session_manager.stop(owner_user_id=owner)
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
def get_current_session(identity: StationUser) -> dict[str, Any]:
    owner = None if identity.user.role == "admin" else identity.user.id
    return session_manager.current(owner_user_id=owner)


@app.get("/sessions")
def get_sessions(identity: Authenticated, db: Database) -> dict[str, Any]:
    admin = identity.user.role == "admin"
    sessions = list_sessions(owner_user_id=None if admin else identity.user.id)
    if admin:
        owners = {entry["owner_user_id"] for entry in sessions if entry["owner_user_id"]}
        emails = dict(db.execute(select(User.id, User.email).where(User.id.in_(owners))).all()) if owners else {}
        for entry in sessions:
            entry["owner_email"] = emails.get(entry["owner_user_id"])
    return {"sessions": sessions}


@app.get("/sessions/{session_id}")
def get_session(session: AccessibleSession) -> dict[str, Any]:
    try:
        detail = session_detail(session.session_id)
    except OpenPoseRunnerError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    detail["review_media_available"] = session.identity.kind == "browser" and any(
        (session.directory / "raw" / f"{view}.mp4").is_file() for view in detail["available_views"]
    )
    return detail


@app.get("/sessions/{session_id}/analysis/{view}/plots/{filename}")
def get_analysis_plot(session: AccessibleSession, view: str, filename: str) -> FileResponse:
    require_station(session.identity)
    try:
        path = plot_path(session.session_id, view, filename)
    except OpenPoseRunnerError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    return FileResponse(path, media_type="image/png")


@app.get("/sessions/{session_id}/analysis/metrics/{metric}")
def get_session_metric_time_series(session: AccessibleSession, metric: str) -> dict[str, Any]:
    try:
        return metric_time_series(session.directory, metric)
    except AnalysisDataError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


@app.get("/sessions/{session_id}/analysis/frame")
def get_session_analysis_frame(
    session: AccessibleSession,
    view: str,
    frame: int = Query(ge=0),
) -> Response:
    require_station(session.identity)
    try:
        image = saved_video_frame(session.directory, view, frame)
        return Response(content=image, media_type="image/jpeg")
    except AnalysisDataError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


@app.post("/sessions/{session_id}/analysis/{view}/retry")
def retry_posture_analysis(session: AccessibleSession, view: str) -> dict[str, Any]:
    require_station(session.identity)
    try:
        return openpose_runner.retry_posture(session.session_id, view)
    except OpenPoseRunnerError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


@app.get("/sessions/{session_id}/analysis-status")
def get_analysis_status(session: AccessibleSession) -> dict[str, Any]:
    try:
        return openpose_runner.get_status(session.session_id)
    except OpenPoseRunnerError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


@app.post("/sessions/{session_id}/analyze")
def analyze_session(session: AccessibleSession) -> dict[str, Any]:
    require_station(session.identity)
    try:
        return openpose_runner.start(session.session_id)
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
def save_camera_config(config: CameraConfigUpdate, _identity: StationUser) -> dict[str, Any]:
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
