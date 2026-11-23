from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

import cv2
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from station_cameras import CaptureStream, station_camera_manager

logger = logging.getLogger(__name__)


async def _preview_frames(
    camera_id: str,
    stream: CaptureStream,
    request_id: str,
    request: Request,
    release_subscriber: Callable[[], None],
) -> AsyncIterator[bytes]:
    sequence = 0
    try:
        while True:
            if await request.is_disconnected():
                logger.info(
                    "event=preview_client_disconnected camera_id=%s display_name=%r request_id=%s",
                    camera_id,
                    stream.device.display_name,
                    request_id,
                )
                break

            frame = await asyncio.to_thread(stream.wait_for_frame, sequence, 1)
            if frame is None:
                if stream.status != "available":
                    break
                continue
            sequence = frame.sequence

            height, width = frame.image.shape[:2]
            scale = min(640 / width, 360 / height, 1)
            preview_frame = frame.image
            if scale < 1:
                preview_frame = cv2.resize(
                    frame.image,
                    (max(1, round(width * scale)), max(1, round(height * scale))),
                )

            encoded_ok, encoded = cv2.imencode(
                ".jpg",
                preview_frame,
                [cv2.IMWRITE_JPEG_QUALITY, 75],
            )
            if not encoded_ok:
                logger.warning(
                    "event=preview_encode_failed camera_id=%s display_name=%r request_id=%s",
                    camera_id,
                    stream.device.display_name,
                    request_id,
                )
                break

            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + encoded.tobytes() + b"\r\n"
            await asyncio.sleep(1 / 15)
    finally:
        logger.info(
            "event=preview_stream_closed camera_id=%s display_name=%r request_id=%s thread=%s",
            camera_id,
            stream.device.display_name,
            request_id,
            threading.current_thread().name,
        )
        release_subscriber()


async def stream_camera_preview(camera_id: str, request: Request) -> StreamingResponse:
    request_id = uuid.uuid4().hex[:8]
    try:
        stream = await asyncio.to_thread(station_camera_manager.attach_preview, camera_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Camera is not in the current inventory. Rescan cameras.") from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    cleanup_guard = threading.Lock()
    released = False

    def release_subscriber() -> None:
        nonlocal released
        with cleanup_guard:
            if released:
                return
            released = True
        station_camera_manager.detach_preview(camera_id, stream)

    return StreamingResponse(
        _preview_frames(camera_id, stream, request_id, request, release_subscriber),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
        background=BackgroundTask(release_subscriber),
    )


def camera_inventory() -> list[dict[str, Any]]:
    return station_camera_manager.get_cameras()
