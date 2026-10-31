from __future__ import annotations

import asyncio
import logging
import platform
import threading
import time
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

import cv2
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask


logger = logging.getLogger(__name__)
_camera_locks: dict[int, threading.Lock] = {}
_camera_locks_guard = threading.Lock()
_camera_names: dict[int, str] = {}


def camera_lock(index: int) -> threading.Lock:
    with _camera_locks_guard:
        if index not in _camera_locks:
            _camera_locks[index] = threading.Lock()
        return _camera_locks[index]


def camera_name(index: int) -> str:
    with _camera_locks_guard:
        return _camera_names.get(index, f"Camera {index}")


def _camera_backend() -> int:
    if platform.system() == "Windows":
        return cv2.CAP_DSHOW
    return cv2.CAP_ANY


def open_camera(index: int, operation: str = "camera", retries: int = 0) -> cv2.VideoCapture | None:
    attempts = retries + 1
    for attempt in range(attempts):
        camera = None
        try:
            camera = cv2.VideoCapture(index, _camera_backend())
            if camera.isOpened():
                logger.info(
                    "event=camera_open operation=%s camera_id=%s name=%r thread=%s attempt=%s backend=%s",
                    operation,
                    index,
                    camera_name(index),
                    threading.current_thread().name,
                    attempt + 1,
                    camera.getBackendName(),
                )
                return camera
        except cv2.error:
            if camera is not None:
                camera.release()
            logger.exception(
                "event=camera_open_error operation=%s camera_id=%s name=%r thread=%s attempt=%s",
                operation,
                index,
                camera_name(index),
                threading.current_thread().name,
                attempt + 1,
            )

        if camera is not None:
            camera.release()

        if platform.system() == "Windows":
            camera = None
            try:
                camera = cv2.VideoCapture(index)
                if camera.isOpened():
                    logger.info(
                        "event=camera_open operation=%s camera_id=%s name=%r thread=%s attempt=%s backend=%s",
                        operation,
                        index,
                        camera_name(index),
                        threading.current_thread().name,
                        attempt + 1,
                        camera.getBackendName(),
                    )
                    return camera
            except cv2.error:
                if camera is not None:
                    camera.release()
                logger.exception(
                    "event=camera_open_error operation=%s camera_id=%s name=%r thread=%s attempt=%s backend=default",
                    operation,
                    index,
                    camera_name(index),
                    threading.current_thread().name,
                    attempt + 1,
                )

            if camera is not None:
                camera.release()

        if attempt + 1 < attempts:
            time.sleep(0.1 * (attempt + 1))

    logger.warning(
        "event=camera_open_failed operation=%s camera_id=%s name=%r thread=%s attempts=%s",
        operation,
        index,
        camera_name(index),
        threading.current_thread().name,
        attempts,
    )
    return None


def _release_camera(camera: cv2.VideoCapture, index: int, operation: str) -> None:
    started = time.perf_counter()
    try:
        camera.release()
    finally:
        logger.info(
            "event=camera_release operation=%s camera_id=%s name=%r thread=%s release_ms=%.1f",
            operation,
            index,
            camera_name(index),
            threading.current_thread().name,
            (time.perf_counter() - started) * 1000,
        )


def detect_camera(index: int, name: str, enumerated: bool = False) -> dict[str, Any]:
    lock = camera_lock(index)
    if not lock.acquire(blocking=False):
        logger.info(
            "event=camera_lock_busy operation=discover camera_id=%s name=%r thread=%s",
            index,
            name,
            threading.current_thread().name,
        )
        return {
            "id": index,
            "name": name,
            "width": None,
            "height": None,
            "fps": None,
            "connected": True,
            "availability": "busy",
        }

    camera = None
    try:
        logger.info(
            "event=camera_lock_acquired operation=discover camera_id=%s name=%r thread=%s",
            index,
            name,
            threading.current_thread().name,
        )
        camera = open_camera(index, operation="discover")
        if camera is None:
            return {
                "id": index,
                "name": name,
                "width": None,
                "height": None,
                "fps": None,
                "connected": enumerated,
                "availability": "unavailable",
            }

        try:
            ok, frame = camera.read()
            if not ok or frame is None:
                logger.warning(
                    "event=camera_frame_unavailable operation=discover camera_id=%s name=%r thread=%s",
                    index,
                    name,
                    threading.current_thread().name,
                )
                return {
                    "id": index,
                    "name": name,
                    "width": None,
                    "height": None,
                    "fps": None,
                    "connected": enumerated,
                    "availability": "unavailable",
                }

            width = int(camera.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            height = int(camera.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            fps = camera.get(cv2.CAP_PROP_FPS)
            fps_value = int(fps) if fps and fps > 0 else None
            return {
                "id": index,
                "name": name,
                "connected": True,
                "availability": "available",
                "width": width or int(frame.shape[1]),
                "height": height or int(frame.shape[0]),
                "fps": fps_value,
            }
        except cv2.error:
            logger.exception(
                "event=camera_discover_error camera_id=%s name=%r thread=%s",
                index,
                name,
                threading.current_thread().name,
            )
            return {
                "id": index,
                "name": name,
                "width": None,
                "height": None,
                "fps": None,
                "connected": enumerated,
                "availability": "unavailable",
            }
    finally:
        try:
            if camera is not None:
                _release_camera(camera, index, "discover")
        finally:
            lock.release()
            logger.info(
                "event=camera_lock_released operation=discover camera_id=%s name=%r thread=%s",
                index,
                name,
                threading.current_thread().name,
            )


def detect_cameras() -> list[dict[str, Any]]:
    if platform.system() == "Windows":
        from pygrabber.dshow_graph import FilterGraph

        device_names = FilterGraph().get_input_devices()
        indexed_names = list(enumerate(device_names[:9]))
    else:
        indexed_names = [(index, f"Camera {index}") for index in range(9)]

    cameras: list[dict[str, Any]] = []
    for index, name in indexed_names:
        with _camera_locks_guard:
            _camera_names[index] = str(name)
        detected = detect_camera(
            index,
            str(name),
            enumerated=platform.system() == "Windows",
        )
        if platform.system() == "Windows" or detected["connected"] or detected["availability"] == "busy":
            cameras.append(detected)
        logger.info(
            "event=camera_enumerated camera_id=%s name=%r connected=%s availability=%s",
            index,
            name,
            detected["connected"],
            detected["availability"],
        )
    return cameras


async def _preview_frames(
    camera: cv2.VideoCapture,
    camera_id: int,
    request_id: str,
    request: Request,
    first_frame: Any,
    release_camera: Callable[[], None],
) -> AsyncIterator[bytes]:
    frame = first_frame
    try:
        while True:
            if await request.is_disconnected():
                logger.info(
                    "event=preview_client_disconnected camera_id=%s name=%r request_id=%s",
                    camera_id,
                    camera_name(camera_id),
                    request_id,
                )
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
                logger.warning(
                    "event=preview_frame_unavailable camera_id=%s name=%r request_id=%s",
                    camera_id,
                    camera_name(camera_id),
                    request_id,
                )
                break
    finally:
        logger.info(
            "event=preview_stream_finally camera_id=%s name=%r request_id=%s thread=%s",
            camera_id,
            camera_name(camera_id),
            request_id,
            threading.current_thread().name,
        )
        release_camera()


async def stream_camera_preview(camera_id: int, request: Request) -> StreamingResponse:
    if camera_id < 0 or camera_id > 8:
        raise HTTPException(status_code=404, detail="Camera ID must be between 0 and 8.")

    request_id = uuid.uuid4().hex[:8]
    lock = camera_lock(camera_id)
    acquired = await asyncio.to_thread(lock.acquire, True, 5)
    if not acquired:
        logger.warning(
            "event=camera_lock_timeout operation=preview-open camera_id=%s name=%r request_id=%s",
            camera_id,
            camera_name(camera_id),
            request_id,
        )
        raise HTTPException(status_code=503, detail="This camera is already in use.")

    camera = None
    try:
        logger.info(
            "event=camera_lock_acquired operation=preview-open camera_id=%s name=%r request_id=%s thread=%s",
            camera_id,
            camera_name(camera_id),
            request_id,
            threading.current_thread().name,
        )
        camera = open_camera(camera_id, operation="preview-open", retries=2)
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
                _release_camera(camera, camera_id, "preview-close")
            finally:
                lock.release()
                logger.info(
                    "event=camera_lock_released operation=preview-close camera_id=%s request_id=%s thread=%s",
                    camera_id,
                    request_id,
                    threading.current_thread().name,
                )

        return StreamingResponse(
            _preview_frames(camera, camera_id, request_id, request, first_frame, release_camera),
            media_type="multipart/x-mixed-replace; boundary=frame",
            headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
            background=BackgroundTask(release_camera),
        )
    except BaseException:
        try:
            if camera is not None:
                _release_camera(camera, camera_id, "preview-open-failed")
        finally:
            lock.release()
            logger.info(
                "event=camera_lock_released operation=preview-open-failed camera_id=%s request_id=%s thread=%s",
                camera_id,
                request_id,
                threading.current_thread().name,
            )
        raise
