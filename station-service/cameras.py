from __future__ import annotations

import platform
from typing import Any

import cv2


def _camera_backend() -> int:
    if platform.system() == "Windows":
        return cv2.CAP_DSHOW
    return cv2.CAP_ANY


def detect_camera(index: int) -> dict[str, Any] | None:
    backend = _camera_backend()
    camera = cv2.VideoCapture(index, backend)
    if not camera.isOpened():
        camera = cv2.VideoCapture(index)
        if not camera.isOpened():
            return None

    try:
        ok, frame = camera.read()
        if not ok or frame is None:
            return None

        width = int(camera.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(camera.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        fps = camera.get(cv2.CAP_PROP_FPS)
        fps_value = int(fps) if fps and fps > 0 else None

        return {
            "id": index,
            "connected": True,
            "width": width or None,
            "height": height or None,
            "fps": fps_value,
        }
    finally:
        camera.release()


def detect_cameras() -> list[dict[str, Any]]:
    cameras: list[dict[str, Any]] = []
    for index in range(9):
        detected = detect_camera(index)
        if detected is not None:
            cameras.append(detected)
    return cameras
