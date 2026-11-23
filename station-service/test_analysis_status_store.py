from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import analysis_status_store as status_store


class AnalysisStatusStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def _status_path(self, session_id: str = "session") -> Path:
        session_dir = self.root / session_id
        session_dir.mkdir(exist_ok=True)
        return session_dir / "analysis_status.json"

    @staticmethod
    def _payload(value: int) -> dict[str, object]:
        return {"status": "pending", "value": value, "views": {}}

    def test_normal_atomic_write_persists_complete_json(self) -> None:
        path = self._status_path()
        payload = self._payload(42)

        status_store.write_status(path, payload)

        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), payload)

    def test_transient_replace_permission_error_retries_then_succeeds(self) -> None:
        path = self._status_path()
        replace = status_store.os.replace
        attempts = 0

        def fail_once(source: Path, destination: Path) -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise PermissionError("temporarily locked")
            replace(source, destination)

        with patch.object(status_store.os, "replace", side_effect=fail_once):
            status_store.write_status(path, self._payload(1))

        self.assertEqual(attempts, 2)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["value"], 1)

    def test_persistent_replace_permission_error_raises_and_preserves_good_file(self) -> None:
        path = self._status_path()
        existing = self._payload(7)
        path.write_text(json.dumps(existing), encoding="utf-8")

        with patch.object(status_store.os, "replace", side_effect=PermissionError("locked")) as replace:
            with self.assertRaises(PermissionError):
                status_store.write_status(path, self._payload(8))

        self.assertEqual(replace.call_count, status_store._REPLACE_ATTEMPTS)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), existing)
        self.assertEqual(list(path.parent.glob("analysis_status.json.*.tmp")), [])

    def test_each_write_uses_a_unique_temporary_filename(self) -> None:
        path = self._status_path()
        replace = status_store.os.replace
        temporary_names: list[str] = []

        def record_replace(source: Path, destination: Path) -> None:
            temporary_names.append(source.name)
            replace(source, destination)

        with patch.object(status_store.os, "replace", side_effect=record_replace):
            status_store.write_status(path, self._payload(1))
            status_store.write_status(path, self._payload(2))

        self.assertEqual(len(temporary_names), 2)
        self.assertNotEqual(temporary_names[0], temporary_names[1])
        self.assertTrue(all(name.startswith("analysis_status.json.") and name.endswith(".tmp")
                            for name in temporary_names))

    def test_same_session_updates_are_serialized(self) -> None:
        path = self._status_path()
        status_store.write_status(path, {"status": "pending", "counter": 0, "views": {}})
        errors: list[BaseException] = []

        def increment() -> None:
            try:
                for _ in range(25):
                    def apply(status: dict[str, object]) -> None:
                        status["counter"] = int(status["counter"]) + 1

                    status_store.update_status(path, apply)
            except BaseException as error:
                errors.append(error)

        workers = [threading.Thread(target=increment) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=5)

        self.assertFalse(any(worker.is_alive() for worker in workers))
        self.assertEqual(errors, [])
        self.assertEqual(status_store.read_status(path)["counter"], 50)

    def test_different_sessions_can_write_independently(self) -> None:
        first_path = self._status_path("first")
        second_path = self._status_path("second")
        first_entered_replace = threading.Event()
        release_first_replace = threading.Event()
        second_finished = threading.Event()
        replace = status_store.os.replace
        errors: list[BaseException] = []

        def block_first(source: Path, destination: Path) -> None:
            if source.parent.name == "first":
                first_entered_replace.set()
                if not release_first_replace.wait(timeout=3):
                    raise TimeoutError("test did not release first writer")
            replace(source, destination)

        def write(path: Path, finished: threading.Event | None = None) -> None:
            try:
                status_store.write_status(path, self._payload(1))
            except BaseException as error:
                errors.append(error)
            finally:
                if finished is not None:
                    finished.set()

        with patch.object(status_store.os, "replace", side_effect=block_first):
            first = threading.Thread(target=write, args=(first_path,))
            first.start()
            self.assertTrue(first_entered_replace.wait(timeout=2))

            second = threading.Thread(target=write, args=(second_path, second_finished))
            second.start()
            self.assertTrue(second_finished.wait(timeout=2))
            release_first_replace.set()
            first.join(timeout=3)
            second.join(timeout=3)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(first_path.is_file())
        self.assertTrue(second_path.is_file())

    def test_concurrent_view_updates_do_not_lose_each_others_fields(self) -> None:
        path = self._status_path()
        status_store.write_status(path, {
            "status": "processing",
            "views": {"side": {"openpose_status": "processing"}, "rear": {"openpose_status": "pending"}},
        })
        barrier = threading.Barrier(2)
        errors: list[BaseException] = []

        def update_view(view: str, field: str) -> None:
            try:
                barrier.wait(timeout=2)

                def apply(status: dict[str, object]) -> None:
                    views = status["views"]
                    assert isinstance(views, dict)
                    views[view][field] = "complete"

                status_store.update_status(path, apply)
            except BaseException as error:
                errors.append(error)

        workers = [
            threading.Thread(target=update_view, args=("side", "posture_status")),
            threading.Thread(target=update_view, args=("rear", "json_frame_count")),
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=5)

        self.assertEqual(errors, [])
        saved = status_store.read_status(path)
        self.assertEqual(saved["views"]["side"]["posture_status"], "complete")
        self.assertEqual(saved["views"]["rear"]["json_frame_count"], "complete")
        self.assertEqual(saved["views"]["side"]["openpose_status"], "processing")
        self.assertEqual(saved["views"]["rear"]["openpose_status"], "pending")

    def test_temporary_file_is_cleaned_after_success(self) -> None:
        path = self._status_path()

        status_store.write_status(path, self._payload(1))

        self.assertEqual(list(path.parent.glob("analysis_status.json.*.tmp")), [])

    def test_temporary_file_is_cleaned_after_persistent_failure(self) -> None:
        path = self._status_path()

        with patch.object(status_store.os, "replace", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                status_store.write_status(path, self._payload(1))

        self.assertEqual(list(path.parent.glob("analysis_status.json.*.tmp")), [])

    def test_reader_succeeds_while_atomic_replacements_are_running(self) -> None:
        path = self._status_path()
        status_store.write_status(path, self._payload(0))
        finished = threading.Event()
        errors: list[BaseException] = []

        def writer() -> None:
            try:
                for value in range(1, 60):
                    status_store.write_status(path, self._payload(value))
            except BaseException as error:
                errors.append(error)
            finally:
                finished.set()

        worker = threading.Thread(target=writer)
        worker.start()
        while not finished.is_set():
            try:
                status = status_store.read_status(path)
                self.assertEqual(status["status"], "pending")
                self.assertIsInstance(status["value"], int)
            except BaseException as error:
                errors.append(error)
                break
        worker.join(timeout=5)

        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])

    def test_legacy_status_normalization_is_preserved(self) -> None:
        session_dir = self.root / "legacy"
        raw_dir = session_dir / "raw"
        raw_dir.mkdir(parents=True)
        (raw_dir / "side.mp4").write_bytes(b"video")
        path = session_dir / "analysis_status.json"
        path.write_text(json.dumps({
            "status": "complete",
            "views": {"side": {"status": "complete", "json_frame_count": 3}},
        }), encoding="utf-8")

        status = status_store.read_status(path)

        self.assertEqual(status["status"], "pending")
        self.assertEqual(status["stage"], "posture_analysis")
        self.assertEqual(status["views"]["side"]["openpose_status"], "complete")
        self.assertEqual(status["views"]["side"]["posture_status"], "pending")

    def test_persistent_malformed_json_read_is_bounded(self) -> None:
        path = self._status_path()
        path.write_text("{", encoding="utf-8")

        with patch.object(status_store.time, "sleep") as sleep:
            with self.assertRaises(json.JSONDecodeError):
                status_store.read_status(path)

        self.assertEqual(sleep.call_count, status_store._READ_ATTEMPTS - 1)


if __name__ == "__main__":
    unittest.main()
