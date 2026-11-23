from __future__ import annotations

import threading
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

import station_cameras
from station_cameras import CameraDevice, StationCameraManager, _stable_device_id
import session_manager as session_manager_module
from session_manager import SessionManager


class FakeCapture:
    def __init__(self, *, reads: bool = True) -> None:
        self.reads = reads
        self.released = threading.Event()

    def isOpened(self) -> bool:
        return True

    def get(self, _: int) -> float:
        return 30

    def read(self) -> tuple[bool, np.ndarray | None]:
        time.sleep(0.005)
        return (self.reads, np.zeros((2, 3, 3), dtype=np.uint8) if self.reads else None)

    def release(self) -> None:
        self.released.set()


class FakeWriter:
    def __init__(self) -> None:
        self.released = False
        self.frame_count = 0

    def isOpened(self) -> bool:
        return True

    def write(self, _: np.ndarray) -> None:
        self.frame_count += 1

    def release(self) -> None:
        self.released = True


class StationCameraManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.first = CameraDevice(_stable_device_id("device-path-1"), "GoPro Camera", 0)
        self.second = CameraDevice(_stable_device_id("device-path-2"), "GoPro Camera", 1)
        self.devices = [self.first, self.second]
        self.captures: list[FakeCapture] = []

        def capture_factory(_: CameraDevice) -> FakeCapture:
            capture = FakeCapture()
            self.captures.append(capture)
            return capture

        self.config_patches = (
            patch("station_cameras.load_config", return_value={
                "side_camera_id": None,
                "rear_camera_id": None,
            }),
            patch("station_cameras.save_config", side_effect=lambda config: dict(config)),
        )
        for config_patch in self.config_patches:
            config_patch.start()
            self.addCleanup(config_patch.stop)

        self.enumeration_count = 0

        def enumerate_devices() -> list[CameraDevice]:
            self.enumeration_count += 1
            return list(self.devices)

        self.manager = StationCameraManager(
            enumerate_devices=enumerate_devices,
            capture_factory=capture_factory,
        )
        self.addCleanup(self.manager.shutdown)
        self.manager.start()

    def test_identical_friendly_names_have_distinct_stable_ids(self) -> None:
        self.assertEqual(self.first.display_name, self.second.display_name)
        self.assertNotEqual(self.first.id, self.second.id)

    def test_directshow_enumeration_initializes_and_cleans_up_com(self) -> None:
        with patch.object(station_cameras.platform, "system", return_value="Windows"), \
             patch.object(station_cameras.comtypes, "CoInitialize") as initialize, \
             patch.object(station_cameras.comtypes, "CoUninitialize") as uninitialize, \
             patch.object(station_cameras, "_enumerate_directshow_devices", return_value=[self.first]):
            self.assertEqual(station_cameras.enumerate_directshow_devices(), [self.first])

        initialize.assert_called_once_with()
        uninitialize.assert_called_once_with()

        with patch.object(station_cameras.platform, "system", return_value="Windows"), \
             patch.object(station_cameras.comtypes, "CoInitialize"), \
             patch.object(station_cameras.comtypes, "CoUninitialize") as uninitialize, \
             patch.object(station_cameras, "_enumerate_directshow_devices", side_effect=RuntimeError("enumeration failed")):
            with self.assertRaisesRegex(RuntimeError, "enumeration failed"):
                station_cameras.enumerate_directshow_devices()

        uninitialize.assert_called_once_with()

    def test_side_and_rear_assignments_keep_distinct_devices(self) -> None:
        self.manager.set_assignments(self.first.id, self.second.id)

        self.assertEqual(self.manager.get_camera_config(), {
            "side_camera_id": self.first.id,
            "rear_camera_id": self.second.id,
        })
        self.assertEqual(self.manager.stream_for(self.first.id).device.id, self.first.id)
        self.assertEqual(self.manager.stream_for(self.second.id).device.id, self.second.id)

    def test_cached_inventory_does_not_rescan_and_explicit_rescan_does(self) -> None:
        self.manager.set_assignments(self.first.id, None)
        stream = self.manager.stream_for(self.first.id)
        self.assertIsNotNone(stream.wait_for_frame(timeout=1))
        capture = self.captures[0]
        initial_count = self.enumeration_count
        self.manager.get_cameras()
        self.assertEqual(self.enumeration_count, initial_count)

        self.manager.rescan(reason="explicit")
        self.assertEqual(self.enumeration_count, initial_count + 1)
        self.assertIs(self.manager.stream_for(self.first.id), stream)
        self.assertFalse(capture.released.is_set())

    def test_preview_detach_does_not_release_configured_camera(self) -> None:
        self.manager.set_assignments(self.first.id, None)
        stream = self.manager.stream_for(self.first.id)
        self.assertIsNotNone(stream.wait_for_frame(timeout=1))
        capture = self.captures[0]

        attached = self.manager.attach_preview(self.first.id)
        self.manager.detach_preview(self.first.id, attached)

        self.assertIs(self.manager.stream_for(self.first.id), stream)
        self.assertFalse(capture.released.is_set())

    def test_recorder_attaches_to_the_exact_configured_camera(self) -> None:
        self.manager.set_assignments(self.first.id, self.second.id)
        self.assertIsNotNone(self.manager.stream_for(self.second.id).wait_for_frame(timeout=1))

        subscription = self.manager.attach_recorder(self.second.id, "rear")
        self.assertEqual(subscription.stream.device.id, self.second.id)
        subscription.close()

    def test_session_recording_reuses_station_capture_handles(self) -> None:
        self.manager.set_assignments(self.first.id, self.second.id)
        first_stream = self.manager.stream_for(self.first.id)
        second_stream = self.manager.stream_for(self.second.id)
        self.assertIsNotNone(first_stream.wait_for_frame(timeout=1))
        self.assertIsNotNone(second_stream.wait_for_frame(timeout=1))
        physical_handle_count = len(self.captures)
        writers: list[FakeWriter] = []

        def create_writer(*_: object) -> FakeWriter:
            writer = FakeWriter()
            writers.append(writer)
            return writer

        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(session_manager_module, "station_camera_manager", self.manager), \
                 patch.object(session_manager_module, "SESSIONS_DIR", Path(temporary)), \
                 patch.object(session_manager_module.cv2, "VideoWriter", side_effect=create_writer):
                session = SessionManager()
                started = session.start("TEST001", "camera ownership test")
                time.sleep(0.03)
                stopped = session.stop()

        self.assertEqual(started["status"], "recording")
        self.assertEqual(stopped["metadata"]["selected_cameras"], {
            "side": self.first.id,
            "rear": self.second.id,
        })
        self.assertEqual(len(self.captures), physical_handle_count)
        self.assertEqual(len(writers), 2)
        self.assertTrue(all(writer.frame_count > 0 for writer in writers))
        self.assertIs(self.manager.stream_for(self.first.id), first_stream)
        self.assertIs(self.manager.stream_for(self.second.id), second_stream)

    def test_legacy_numeric_config_is_not_bound_to_current_indices(self) -> None:
        with patch("station_cameras.load_config", return_value={
            "side_camera_id": 0,
            "rear_camera_id": 1,
        }):
            legacy_manager = StationCameraManager(
                enumerate_devices=lambda: list(self.devices),
                capture_factory=lambda _: FakeCapture(),
            )
        self.addCleanup(legacy_manager.shutdown)
        legacy_manager.start()

        self.assertEqual(legacy_manager.get_camera_config(), {
            "side_camera_id": 0,
            "rear_camera_id": 1,
        })
        self.assertIsNone(legacy_manager.stream_for(self.first.id))
        self.assertIsNone(legacy_manager.stream_for(self.second.id))

    def test_disconnected_camera_is_not_substituted_by_same_named_device(self) -> None:
        def capture_factory(device: CameraDevice) -> FakeCapture:
            capture = FakeCapture(reads=device.id != self.first.id)
            self.captures.append(capture)
            return capture

        self.manager._capture_factory = capture_factory
        self.manager.set_assignments(self.first.id, self.second.id)
        first_stream = self.manager.stream_for(self.first.id)
        second_stream = self.manager.stream_for(self.second.id)

        deadline = time.monotonic() + 1
        while first_stream.status != "disconnected" and time.monotonic() < deadline:
            time.sleep(0.01)

        cameras = {camera["id"]: camera for camera in self.manager.get_cameras()}
        self.assertEqual(first_stream.status, "disconnected")
        self.assertFalse(cameras[self.first.id]["connected"])
        self.assertEqual(self.manager.stream_for(self.first.id).device.id, self.first.id)
        self.assertEqual(self.manager.stream_for(self.second.id).device.id, self.second.id)
        self.assertTrue(cameras[self.second.id]["connected"])


if __name__ == "__main__":
    unittest.main()
