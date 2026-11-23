from __future__ import annotations

import csv
import logging
import queue
import threading
import time
from datetime import datetime
from typing import Any

import cv2

from station_cameras import FrameSubscription

logger = logging.getLogger(__name__)


class CameraRecorder:
    def __init__(
        self,
        *,
        role: str,
        camera_id: str,
        display_name: str,
        backend_index: int,
        subscription: FrameSubscription,
        writer: cv2.VideoWriter,
        timestamp_file: Any,
        timestamp_writer: csv.writer,
        session_start_ns: int,
        width: int,
        height: int,
    ) -> None:
        self.role = role
        self.camera_id = camera_id
        self.display_name = display_name
        self.backend_index = backend_index
        self.subscription = subscription
        self.writer = writer
        self.timestamp_file = timestamp_file
        self.timestamp_writer = timestamp_writer
        self.session_start_ns = session_start_ns
        self.width = width
        self.height = height
        self.frame_count = 0
        self.error: str | None = None
        self._stop_event = threading.Event()
        self._cleanup_guard = threading.Lock()
        self._cleaned = False
        self._thread = threading.Thread(
            target=self._record,
            name=f"camera-recorder-{role}",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def join(self) -> None:
        if self._thread.ident is not None:
            self._thread.join()

    def cleanup_unstarted(self) -> None:
        if self._thread.ident is None:
            self._release_resources()

    def _record(self) -> None:
        logger.info(
            "event=record_thread_started operation=record camera_id=%s display_name=%r backend_index=%s role=%s thread=%s",
            self.camera_id,
            self.display_name,
            self.backend_index,
            self.role,
            threading.current_thread().name,
        )
        try:
            while not self._stop_event.is_set():
                try:
                    frame = self.subscription.frames.get(timeout=0.25)
                except queue.Empty:
                    if self.subscription.stream.status in {"disconnected", "unavailable", "stopped"}:
                        if not self._stop_event.is_set():
                            self.error = f"{self.role.title()} camera stopped providing frames."
                        break
                    continue

                image = frame.image
                if image.shape[1] != self.width or image.shape[0] != self.height:
                    image = cv2.resize(image, (self.width, self.height))

                self.writer.write(image)
                frame_time_ns = time.perf_counter_ns()
                wall_time = datetime.now().astimezone().isoformat(timespec="milliseconds")
                self.timestamp_writer.writerow(
                    (
                        self.frame_count,
                        f"{(frame_time_ns - self.session_start_ns) / 1_000_000_000:.6f}",
                        wall_time,
                    )
                )
                self.frame_count += 1
        except cv2.error:
            self.error = f"{self.role.title()} camera recording failed."
        except OSError:
            self.error = f"Could not write {self.role} camera recording files."
        finally:
            try:
                self._release_resources()
            except Exception:
                if self.error is None:
                    self.error = f"Could not finalize {self.role} camera recording files."

    def _release_resources(self) -> None:
        with self._cleanup_guard:
            if self._cleaned:
                return
            self._cleaned = True

        release_started = time.perf_counter()
        try:
            self.writer.release()
        finally:
            try:
                self.timestamp_file.close()
            finally:
                self.subscription.close()
                logger.info(
                    "event=recorder_resources_released camera_id=%s display_name=%r backend_index=%s role=%s release_ms=%.1f",
                    self.camera_id,
                    self.display_name,
                    self.backend_index,
                    self.role,
                    (time.perf_counter() - release_started) * 1000,
                )
