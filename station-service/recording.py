from __future__ import annotations

import csv
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2

from cameras import camera_name


logger = logging.getLogger(__name__)


class CameraRecorder:
    def __init__(
        self,
        *,
        role: str,
        camera_id: int,
        camera: cv2.VideoCapture,
        lock: threading.Lock,
        writer: cv2.VideoWriter,
        timestamp_file: Any,
        timestamp_writer: csv.writer,
        first_frame: Any,
        session_start_ns: int,
        width: int,
        height: int,
    ) -> None:
        self.role = role
        self.camera_id = camera_id
        self.camera = camera
        self.lock = lock
        self.writer = writer
        self.timestamp_file = timestamp_file
        self.timestamp_writer = timestamp_writer
        self.first_frame = first_frame
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
        frame = self.first_frame
        logger.info(
            "event=record_thread_started operation=record camera_id=%s name=%r role=%s thread=%s",
            self.camera_id,
            camera_name(self.camera_id),
            self.role,
            threading.current_thread().name,
        )
        try:
            while not self._stop_event.is_set():
                if frame is None:
                    ok, frame = self.camera.read()
                    if not ok or frame is None:
                        if not self._stop_event.is_set():
                            self.error = f"{self.role.title()} camera stopped providing frames."
                        break

                if frame.shape[1] != self.width or frame.shape[0] != self.height:
                    frame = cv2.resize(frame, (self.width, self.height))

                self.writer.write(frame)
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
                frame = None
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
                try:
                    self.camera.release()
                finally:
                    self.lock.release()
                    logger.info(
                        "event=camera_release operation=record-close camera_id=%s name=%r role=%s thread=%s release_ms=%.1f",
                        self.camera_id,
                        camera_name(self.camera_id),
                        self.role,
                        threading.current_thread().name,
                        (time.perf_counter() - release_started) * 1000,
                    )
                    logger.info(
                        "event=camera_lock_released operation=record-close camera_id=%s name=%r role=%s thread=%s",
                        self.camera_id,
                        camera_name(self.camera_id),
                        self.role,
                        threading.current_thread().name,
                    )
