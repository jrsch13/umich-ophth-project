from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, field_validator

from camera_config import load_config, save_config
from cameras import detect_cameras

app = FastAPI(title="Station Service", version="0.1.0")
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


@app.get("/cameras")
def get_cameras() -> dict[str, list[dict[str, Any]]]:
    return {"cameras": detect_cameras()}


@app.get("/camera-config")
def get_camera_config() -> dict[str, Any]:
    return load_config()


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
