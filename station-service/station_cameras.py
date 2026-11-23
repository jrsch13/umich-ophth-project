from __future__ import annotations

import ctypes
import hashlib
import logging
import platform
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

import comtypes
import cv2

from camera_config import load_config, save_config

logger = logging.getLogger(__name__)
RECORDER_QUEUE_SIZE = 8
FRAME_WAIT_SECONDS = 5


@dataclass(frozen=True)
class CameraDevice:
    id: str
    display_name: str
    backend_index: int


@dataclass(frozen=True)
class CameraFrame:
    sequence: int
    captured_ns: int
    image: Any


class FrameSubscription:
    def __init__(self, stream: CaptureStream, role: str) -> None:
        self.stream = stream
        self.role = role
        self.frames: queue.Queue[CameraFrame] = queue.Queue(maxsize=RECORDER_QUEUE_SIZE)
        self._closed = False
        self._guard = threading.Lock()

    def close(self) -> None:
        with self._guard:
            if self._closed:
                return
            self._closed = True
        self.stream.detach_recorder(self)


def _moniker_display_name(moniker: Any) -> str:
    from ctypes import c_void_p

    from comtypes import COMMETHOD, HRESULT, POINTER
    from pygrabber.moniker import IBindCtx, IMoniker

    class DirectShowMoniker(IMoniker):
        _iid_ = IMoniker._iid_
        _methods_ = [
            COMMETHOD([], HRESULT, "Reduce"),
            COMMETHOD([], HRESULT, "ComposeWith"),
            COMMETHOD([], HRESULT, "Enum"),
            COMMETHOD([], HRESULT, "IsEqual"),
            COMMETHOD([], HRESULT, "Hash"),
            COMMETHOD([], HRESULT, "IsRunning"),
            COMMETHOD([], HRESULT, "GetTimeOfLastChange"),
            COMMETHOD([], HRESULT, "Inverse"),
            COMMETHOD([], HRESULT, "CommonPrefixWith"),
            COMMETHOD([], HRESULT, "RelativePathTo"),
            COMMETHOD(
                [],
                HRESULT,
                "GetDisplayName",
                (["in"], POINTER(IBindCtx), "pbc"),
                (["in"], POINTER(IMoniker), "pmkToLeft"),
                (["out", "retval"], POINTER(c_void_p), "ppszDisplayName"),
            ),
        ]

    display_name_pointer = moniker.QueryInterface(DirectShowMoniker).GetDisplayName(None, None)
    if not display_name_pointer:
        raise RuntimeError("DirectShow returned an empty moniker display name.")

    display_name = ctypes.wstring_at(display_name_pointer)
    ctypes.windll.ole32.CoTaskMemFree(ctypes.c_void_p(display_name_pointer))
    return display_name


def _stable_device_id(device_path: str) -> str:
    digest = hashlib.sha256(device_path.casefold().encode("utf-8")).hexdigest()
    return f"dshow:{digest}"


def _enumerate_directshow_devices() -> list[CameraDevice]:
    from comtypes import COMError, GUID, client
    from comtypes.persist import IPropertyBag
    from pygrabber.dshow_core import ICreateDevEnum
    from pygrabber.dshow_ids import DeviceCategories, clsids

    system_device_enum = client.CreateObject(
        clsids.CLSID_SystemDeviceEnum,
        interface=ICreateDevEnum,
    )
    monikers = system_device_enum.CreateClassEnumerator(
        GUID(DeviceCategories.VideoInputDevice),
        dwFlags=0,
    )
    if monikers is None:
        return []

    devices: list[CameraDevice] = []
    seen_ids: set[str] = set()
    try:
        moniker, count = monikers.Next(1)
    except ValueError:
        return []
    while count:
        property_bag = moniker.BindToStorage(
            None,
            None,
            IPropertyBag._iid_,
        ).QueryInterface(IPropertyBag)
        display_name = str(property_bag.Read("FriendlyName", pErrorLog=None))
        try:
            device_path = property_bag.Read("DevicePath", pErrorLog=None)
        except COMError:
            device_path = None
        stable_path = str(device_path).strip() if device_path else ""
        if not stable_path:
            stable_path = _moniker_display_name(moniker).strip()
        if not stable_path:
            raise RuntimeError(
                f"DirectShow did not provide a stable identifier for {display_name!r}."
            )

        stable_id = _stable_device_id(stable_path)
        if stable_id in seen_ids:
            raise RuntimeError(
                f"DirectShow returned a duplicate stable identifier for {display_name!r}."
            )
        seen_ids.add(stable_id)
        devices.append(CameraDevice(stable_id, display_name, len(devices)))
        logger.info(
            "event=camera_device_enumerated camera_id=%s display_name=%r backend_index=%s",
            stable_id,
            display_name,
            len(devices) - 1,
        )
        moniker, count = monikers.Next(1)

    return devices


def enumerate_directshow_devices() -> list[CameraDevice]:
    if platform.system() != "Windows":
        raise RuntimeError("Stable camera discovery currently requires Windows DirectShow.")

    comtypes.CoInitialize()
    try:
        return _enumerate_directshow_devices()
    finally:
        comtypes.CoUninitialize()


def open_device(device: CameraDevice) -> cv2.VideoCapture:
    capture = cv2.VideoCapture(device.backend_index, cv2.CAP_DSHOW)
    if capture.isOpened():
        logger.info(
            "event=camera_physical_open camera_id=%s display_name=%r backend_index=%s backend=%s",
            device.id,
            device.display_name,
            device.backend_index,
            capture.getBackendName(),
        )
    else:
        logger.warning(
            "event=camera_physical_open_failed camera_id=%s display_name=%r backend_index=%s",
            device.id,
            device.display_name,
            device.backend_index,
        )
    return capture


class CaptureStream:
    def __init__(
        self,
        device: CameraDevice,
        capture_factory: Callable[[CameraDevice], Any] = open_device,
        on_idle: Callable[[CaptureStream], None] | None = None,
    ) -> None:
        self.device = device
        self._capture_factory = capture_factory
        self._on_idle = on_idle
        self._condition = threading.Condition()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._latest_frame: CameraFrame | None = None
        self._frame_sequence = 0
        self._status = "starting"
        self._width: int | None = None
        self._height: int | None = None
        self._fps: int | None = None
        self._preview_subscribers = 0
        self._recorders: set[FrameSubscription] = set()
        self._dropped_recorder_frames = 0

    @property
    def status(self) -> str:
        with self._condition:
            return self._status

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def has_preview_subscribers(self) -> bool:
        with self._condition:
            return self._preview_subscribers > 0

    @property
    def has_recorders(self) -> bool:
        with self._condition:
            return bool(self._recorders)

    @property
    def dimensions(self) -> tuple[int | None, int | None, int | None]:
        with self._condition:
            return self._width, self._height, self._fps

    @property
    def latest_frame(self) -> CameraFrame | None:
        with self._condition:
            return self._latest_frame

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._capture_loop,
            name=f"camera-capture-{self.device.id[-8:]}",
            daemon=True,
        )
        self._thread.start()

    def _set_status(self, status: str) -> None:
        with self._condition:
            self._status = status
            self._condition.notify_all()

    def _capture_loop(self) -> None:
        capture = None
        opened = False
        try:
            capture = self._capture_factory(self.device)
            if not capture.isOpened():
                self._set_status("unavailable")
                return
            opened = True
            reported_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            reported_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            reported_fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
            self._set_status("available")

            while not self._stop_event.is_set():
                ok, image = capture.read()
                if not ok or image is None:
                    if not self._stop_event.is_set():
                        self._set_status("disconnected")
                        logger.warning(
                            "event=camera_physical_disconnect camera_id=%s display_name=%r backend_index=%s",
                            self.device.id,
                            self.device.display_name,
                            self.device.backend_index,
                        )
                    break

                captured_ns = time.perf_counter_ns()
                height, width = image.shape[:2]
                with self._condition:
                    self._frame_sequence += 1
                    frame = CameraFrame(self._frame_sequence, captured_ns, image)
                    self._latest_frame = frame
                    self._width = reported_width or int(width)
                    self._height = reported_height or int(height)
                    self._fps = int(reported_fps) if reported_fps > 0 else None
                    recorder_subscriptions = tuple(self._recorders)
                    self._condition.notify_all()

                for subscription in recorder_subscriptions:
                    try:
                        subscription.frames.put_nowait(frame)
                    except queue.Full:
                        try:
                            subscription.frames.get_nowait()
                            subscription.frames.put_nowait(frame)
                            self._dropped_recorder_frames += 1
                            if self._dropped_recorder_frames % 100 == 1:
                                logger.warning(
                                    "event=recorder_frame_queue_overflow camera_id=%s display_name=%r dropped_frames=%s",
                                    self.device.id,
                                    self.device.display_name,
                                    self._dropped_recorder_frames,
                                )
                        except queue.Empty:
                            pass
        except cv2.error:
            self._set_status("unavailable" if not opened else "disconnected")
            logger.exception(
                "event=camera_capture_error camera_id=%s display_name=%r backend_index=%s",
                self.device.id,
                self.device.display_name,
                self.device.backend_index,
            )
        finally:
            if capture is not None:
                try:
                    capture.release()
                finally:
                    if opened:
                        logger.info(
                            "event=camera_physical_release camera_id=%s display_name=%r backend_index=%s",
                            self.device.id,
                            self.device.display_name,
                            self.device.backend_index,
                        )
            if self._stop_event.is_set():
                self._set_status("stopped")

    def wait_for_frame(self, after_sequence: int = 0, timeout: float = FRAME_WAIT_SECONDS) -> CameraFrame | None:
        with self._condition:
            self._condition.wait_for(
                lambda: (
                    self._frame_sequence > after_sequence
                    or self._status in {"unavailable", "disconnected", "stopped"}
                ),
                timeout=timeout,
            )
            if self._frame_sequence > after_sequence:
                return self._latest_frame
            return None

    def add_preview_subscriber(self) -> None:
        with self._condition:
            self._preview_subscribers += 1
        logger.info(
            "event=preview_subscriber_attach camera_id=%s display_name=%r subscribers=%s",
            self.device.id,
            self.device.display_name,
            self._preview_subscribers,
        )

    def remove_preview_subscriber(self) -> int:
        with self._condition:
            self._preview_subscribers = max(0, self._preview_subscribers - 1)
            remaining = self._preview_subscribers
        logger.info(
            "event=preview_subscriber_detach camera_id=%s display_name=%r subscribers=%s",
            self.device.id,
            self.device.display_name,
            remaining,
        )
        return remaining

    def add_recorder(self, role: str) -> FrameSubscription:
        subscription = FrameSubscription(self, role)
        with self._condition:
            self._recorders.add(subscription)
        logger.info(
            "event=recorder_subscriber_attach camera_id=%s display_name=%r backend_index=%s role=%s subscribers=%s",
            self.device.id,
            self.device.display_name,
            self.device.backend_index,
            role,
            len(self._recorders),
        )
        return subscription

    def detach_recorder(self, subscription: FrameSubscription) -> None:
        with self._condition:
            self._recorders.discard(subscription)
            count = len(self._recorders)
        logger.info(
            "event=recorder_subscriber_detach camera_id=%s display_name=%r role=%s subscribers=%s",
            self.device.id,
            self.device.display_name,
            subscription.role,
            count,
        )
        if self._on_idle is not None:
            self._on_idle(self)

    def stop(self) -> None:
        self._stop_event.set()
        with self._condition:
            self._condition.notify_all()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=10)
            if thread.is_alive():
                logger.error(
                    "event=camera_capture_stop_timeout camera_id=%s display_name=%r backend_index=%s",
                    self.device.id,
                    self.device.display_name,
                    self.device.backend_index,
                )


class StationCameraManager:
    def __init__(
        self,
        *,
        enumerate_devices: Callable[[], list[CameraDevice]] = enumerate_directshow_devices,
        capture_factory: Callable[[CameraDevice], Any] = open_device,
    ) -> None:
        self._enumerate_devices = enumerate_devices
        self._capture_factory = capture_factory
        self._guard = threading.RLock()
        self._inventory: dict[str, CameraDevice] = {}
        self._known_devices: dict[str, CameraDevice] = {}
        self._streams: dict[str, CaptureStream] = {}
        self._unavailable_ids: set[str] = set()
        self._config = load_config()
        self._started = False

    @staticmethod
    def _configured_ids(config: dict[str, Any]) -> set[str]:
        return {
            camera_id
            for camera_id in (config.get("side_camera_id"), config.get("rear_camera_id"))
            if isinstance(camera_id, str)
        }

    def start(self) -> None:
        with self._guard:
            if self._started:
                return
            self._started = True
        self.rescan(reason="service_start")

    def _start_stream_locked(self, device: CameraDevice) -> CaptureStream:
        stream = CaptureStream(device, self._capture_factory, self._prune_unowned_stream)
        self._streams[device.id] = stream
        stream.start()
        return stream

    def _prune_unowned_stream(self, stream: CaptureStream) -> None:
        with self._guard:
            camera_id = stream.device.id
            if (
                camera_id in self._configured_ids(self._config)
                or stream.has_preview_subscribers
                or stream.has_recorders
                or self._streams.get(camera_id) is not stream
            ):
                return
            self._streams.pop(camera_id, None)
            stream.stop()

    def rescan(self, reason: str = "explicit") -> list[dict[str, Any]]:
        logger.info("event=camera_rescan reason=%s", reason)
        devices = self._enumerate_devices()
        refreshed = {device.id: device for device in devices}
        if len(refreshed) != len(devices):
            raise RuntimeError("Camera discovery returned duplicate stable device IDs.")

        streams_to_stop: list[CaptureStream] = []
        with self._guard:
            self._known_devices.update(self._inventory)
            self._known_devices.update(refreshed)
            self._inventory = refreshed
            configured_ids = self._configured_ids(self._config)
            self._unavailable_ids.update(configured_ids - set(refreshed))

            for camera_id, stream in tuple(self._streams.items()):
                device = refreshed.get(camera_id)
                if (
                    camera_id not in configured_ids
                    and not stream.has_preview_subscribers
                    and not stream.has_recorders
                ):
                    self._streams.pop(camera_id, None)
                    streams_to_stop.append(stream)
                elif (
                    device is None
                    or device.backend_index != stream.device.backend_index
                    or not stream.is_running
                    or stream.status in {"disconnected", "unavailable", "stopped"}
                ):
                    self._streams.pop(camera_id, None)
                    streams_to_stop.append(stream)

            for stream in streams_to_stop:
                stream.stop()
            for camera_id in self._configured_ids(self._config):
                device = self._inventory.get(camera_id)
                if device is not None and camera_id not in self._streams:
                    old_stream = next((old for old in streams_to_stop if old.device.id == camera_id), None)
                    was_unavailable = camera_id in self._unavailable_ids or (
                        old_stream is not None and old_stream.status in {"disconnected", "unavailable"}
                    )
                    if was_unavailable:
                        logger.info(
                            "event=camera_physical_reconnect camera_id=%s display_name=%r backend_index=%s",
                            device.id,
                            device.display_name,
                            device.backend_index,
                        )
                        self._unavailable_ids.discard(camera_id)
                    self._start_stream_locked(device)
        return self.get_cameras()

    def get_cameras(self) -> list[dict[str, Any]]:
        with self._guard:
            devices = dict(self._inventory)
            for camera_id in self._configured_ids(self._config):
                if camera_id not in devices:
                    previous = self._known_devices.get(camera_id)
                    if previous is not None:
                        devices[camera_id] = previous

            result: list[dict[str, Any]] = []
            for camera_id, device in devices.items():
                stream = self._streams.get(camera_id)
                width, height, fps = stream.dimensions if stream is not None else (None, None, None)
                if camera_id not in self._inventory:
                    connected = False
                    availability = "disconnected"
                elif stream is None:
                    connected = True
                    availability = "detected"
                else:
                    availability = stream.status
                    connected = availability in {"starting", "available"}
                result.append({
                    "id": device.id,
                    "display_name": device.display_name,
                    "backend_index": device.backend_index if camera_id in self._inventory else None,
                    "width": width,
                    "height": height,
                    "fps": fps,
                    "connected": connected,
                    "availability": availability,
                })
            return result

    def get_camera_config(self) -> dict[str, Any]:
        with self._guard:
            return dict(self._config)

    def set_assignments(self, side_camera_id: str | None, rear_camera_id: str | None) -> dict[str, Any]:
        if side_camera_id is not None and side_camera_id == rear_camera_id:
            raise ValueError("Side and Rear cameras must be different.")

        with self._guard:
            old_ids = self._configured_ids(self._config)
            new_ids = {camera_id for camera_id in (side_camera_id, rear_camera_id) if camera_id is not None}
            for camera_id in new_ids:
                if camera_id not in self._inventory and camera_id not in old_ids:
                    raise KeyError(camera_id)

            saved = save_config({
                "side_camera_id": side_camera_id,
                "rear_camera_id": rear_camera_id,
            })
            self._config = saved
            for camera_id in old_ids - new_ids:
                stream = self._streams.get(camera_id)
                if stream is not None:
                    if not stream.has_preview_subscribers and not stream.has_recorders:
                        self._streams.pop(camera_id, None)
                        stream.stop()

            for camera_id in new_ids:
                device = self._inventory.get(camera_id)
                if device is not None and camera_id not in self._streams:
                    self._start_stream_locked(device)

            logger.info(
                "event=camera_assignments_saved side_camera_id=%s rear_camera_id=%s",
                side_camera_id,
                rear_camera_id,
            )
        return dict(saved)

    def attach_preview(self, camera_id: str) -> CaptureStream:
        with self._guard:
            device = self._inventory.get(camera_id)
            if device is None:
                raise KeyError(camera_id)
            stream = self._streams.get(camera_id)
            if stream is None:
                stream = self._start_stream_locked(device)
            if not stream.is_running:
                raise RuntimeError("Camera is unavailable. Use Rescan Cameras to retry it.")
            stream.add_preview_subscriber()

        frame = stream.wait_for_frame()
        if frame is None:
            self.detach_preview(camera_id, stream)
            raise RuntimeError("Camera is unavailable or did not provide a frame.")
        return stream

    def detach_preview(self, camera_id: str, stream: CaptureStream) -> None:
        remaining = stream.remove_preview_subscriber()
        with self._guard:
            configured = camera_id in self._configured_ids(self._config)
            has_recorders = stream.has_recorders
            if not configured and remaining == 0 and not has_recorders and self._streams.get(camera_id) is stream:
                self._streams.pop(camera_id, None)
                stream.stop()

    def attach_recorder(self, camera_id: str, role: str) -> FrameSubscription:
        with self._guard:
            if camera_id not in self._configured_ids(self._config):
                raise KeyError(camera_id)
            stream = self._streams.get(camera_id)
            if stream is None or stream.status != "available" or stream.latest_frame is None:
                raise RuntimeError(f"The configured {role.title()} camera is unavailable. Rescan or reassign it.")
            return stream.add_recorder(role)

    def stream_for(self, camera_id: str) -> CaptureStream | None:
        with self._guard:
            return self._streams.get(camera_id)

    def shutdown(self) -> None:
        with self._guard:
            streams = list(self._streams.values())
            self._streams.clear()
            self._started = False
            for stream in streams:
                stream.stop()


station_camera_manager = StationCameraManager()
