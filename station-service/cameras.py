from __future__ import annotations

import asyncio
import platform
import threading
from collections.abc import AsyncIterator, Callable
from typing import Any

import cv2
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask


_camera_locks: dict[int, threading.Lock] = {}
_camera_locks_guard = threading.Lock()


def _camera_lock(index: int) -> threading.Lock:
    with _camera_locks_guard:
        if index not in _camera_locks:
            _camera_locks[index] = threading.Lock()
        return _camera_locks[index]


def _camera_backend() -> int:
    if platform.system() == "Windows":
        return cv2.CAP_DSHOW
    return cv2.CAP_ANY


def _open_camera(index: int) -> cv2.VideoCapture | None:
    camera = None
    try:
        camera = cv2.VideoCapture(index, _camera_backend())
        if camera.isOpened():
            return camera
    except cv2.error:
        if camera is not None:
            camera.release()
        return None

    camera.release()
    if platform.system() == "Windows":
        camera = None
        try:
            camera = cv2.VideoCapture(index)
            if camera.isOpened():
                return camera
            camera.release()
        except cv2.error:
            if camera is not None:
                camera.release()
            return None
    return None


def detect_camera(index: int, name: str) -> dict[str, Any] | None:
    lock = _camera_lock(index)
    if not lock.acquire(timeout=10):
        return None

    camera = None
    try:
        camera = _open_camera(index)
        if camera is None:
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
                "name": name,
                "connected": True,
                "width": width or None,
                "height": height or None,
                "fps": fps_value,
            }
        except cv2.error:
            return None
    finally:
        try:
            if camera is not None:
                camera.release()
        finally:
            lock.release()


def detect_cameras() -> list[dict[str, Any]]:
    if platform.system() == "Windows":
        from pygrabber.dshow_graph import FilterGraph

        device_names = FilterGraph().get_input_devices()
        indexed_names = list(enumerate(device_names[:9]))
    else:
        indexed_names = [(index, f"Camera {index}") for index in range(9)]

    cameras: list[dict[str, Any]] = []
    for index, name in indexed_names:
        detected = detect_camera(index, str(name))
        if detected is not None:
            cameras.append(detected)
    return cameras


async def _preview_frames(
    camera: cv2.VideoCapture,
    request: Request,
    first_frame: Any,
    release_camera: Callable[[], None],
) -> AsyncIterator[bytes]:
    frame = first_frame
    try:
        while True:
            if await request.is_disconnected():
                break

            height, width = frame.shape[:2]
            scale = min(640 / width, 360 / height, 1)
            if scale < 1:
                frame = cv2.resize(
                    frame,
                    (max(1, round(width * scale)), max(1, round(height * scale))),
                )

            encoded_ok, encoded = cv2.imencode(
                ".jpg",
                frame,
                [cv2.IMWRITE_JPEG_QUALITY, 75],
            )
            if not encoded_ok:
                break

            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + encoded.tobytes() + b"\r\n"
            await asyncio.sleep(1 / 15)

            ok, frame = camera.read()
            if not ok or frame is None:
                break
    finally:
        release_camera()


async def stream_camera_preview(camera_id: int, request: Request) -> StreamingResponse:
    if camera_id < 0 or camera_id > 8:
        raise HTTPException(status_code=404, detail="Camera ID must be between 0 and 8.")

    lock = _camera_lock(camera_id)
    acquired = await asyncio.to_thread(lock.acquire, True, 5)
    if not acquired:
        raise HTTPException(status_code=503, detail="This camera is already in use.")

    camera = None
    try:
        camera = _open_camera(camera_id)
        if camera is None:
            raise HTTPException(status_code=404, detail="Camera is unavailable.")

        # camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640) this was causing an error with cameras that don't support this resolution
        # camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 360)
        ok, first_frame = camera.read()
        if not ok or first_frame is None:
            raise HTTPException(status_code=503, detail="Camera opened but could not provide a frame.")

        cleanup_guard = threading.Lock()
        released = False

        def release_camera() -> None:
            nonlocal released
            with cleanup_guard:
                if released:
                    return
                released = True
            try:
                camera.release()
            finally:
                lock.release()

        return StreamingResponse(
            _preview_frames(camera, request, first_frame, release_camera),
            media_type="multipart/x-mixed-replace; boundary=frame",
            headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
            background=BackgroundTask(release_camera),
        )
    except BaseException:
        try:
            if camera is not None:
                camera.release()
        finally:
            lock.release()
        raise
