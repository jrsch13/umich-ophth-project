"""Focused integration checks for JSON-only posture retries and plot access."""

from __future__ import annotations

import json
import csv
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import openpose_runner as runner_module
import session_catalog
from openpose_runner import OpenPoseRunner, OpenPoseRunnerError


class AnalysisPipelineTests(unittest.TestCase):
    def test_legacy_pending_status_without_views_remains_listable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            sessions_dir = Path(temporary)
            session = sessions_dir / "legacy_session"
            raw_dir = session / "raw"
            raw_dir.mkdir(parents=True)
            (session / "analysis_status.json").write_text(
                json.dumps({"status": "pending"}), encoding="utf-8"
            )
            (session / "metadata.json").write_text(
                json.dumps({"resident_or_study_id": "Test", "session_label": "Legacy"}),
                encoding="utf-8",
            )
            (raw_dir / "side.mp4").write_bytes(b"recorded video")

            with patch.object(runner_module, "SESSIONS_DIR", sessions_dir), \
                 patch.object(session_catalog, "SESSIONS_DIR", sessions_dir):
                sessions = session_catalog.list_sessions()

            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0]["analysis_status"], "pending")
            self.assertEqual(sessions[0]["available_views"], ["side"])

    def test_legacy_openpose_complete_status_is_not_full_analysis_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            sessions_dir = Path(temporary)
            session = sessions_dir / "test_session"
            session.mkdir()
            (session / "analysis_status.json").write_text(json.dumps({
                "status": "complete", "views": {"side": {"status": "complete", "json_frame_count": 3}}
            }), encoding="utf-8")
            with patch.object(runner_module, "SESSIONS_DIR", sessions_dir):
                status = OpenPoseRunner().get_status("test_session")
            self.assertEqual(status["status"], "pending")
            self.assertEqual(status["views"]["side"]["openpose_status"], "complete")
            self.assertEqual(status["views"]["side"]["posture_status"], "pending")

    def test_openpose_success_runs_each_view_and_isolates_posture_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            session = Path(temporary) / "test_session"
            session.mkdir()
            status = {
                "status": "processing", "backend": "cpu", "views": {
                    "side": {"status": "pending", "openpose_status": "pending", "posture_status": "pending"},
                    "rear": {"status": "pending", "openpose_status": "pending", "posture_status": "pending"},
                },
            }

            def posture_result(_: Path, view: str) -> dict[str, str]:
                if view == "side":
                    raise ValueError("neutral baseline unavailable")
                return {"analysis_dir": "analysis/rear", "summary": "analysis/rear/summary.json"}

            runner = OpenPoseRunner()
            with patch.object(runner, "_run_view", return_value={
                "json_frame_count": 3, "labeled_video": "labeled-videos/view_labeled.avi"
            }) as run_openpose, patch.object(runner_module, "run_posture_analysis", side_effect=posture_result) as run_posture, \
                 patch.object(runner, "_save_status"), patch.object(runner_module.logger, "exception"):
                runner._run("test_session", session, status, Path("unused.ps1"))
            self.assertEqual(run_openpose.call_count, 2, status)
            self.assertEqual(run_posture.call_count, 2)
            self.assertEqual(status["views"]["side"]["openpose_status"], "complete")
            self.assertEqual(status["views"]["side"]["posture_status"], "failed")
            self.assertEqual(status["views"]["rear"]["posture_status"], "complete")
            self.assertEqual(status["status"], "failed")

    def test_retry_uses_existing_json_without_openpose(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            sessions_dir = Path(temporary)
            session = sessions_dir / "test_session"
            json_dir = session / "openpose" / "side" / "json"
            json_dir.mkdir(parents=True)
            (session / "raw").mkdir()
            (session / "raw" / "side.mp4").write_bytes(b"existing raw video")
            (session / "metadata.json").write_text(
                json.dumps({"session_id": "test_session", "status": "completed", "session_label": "Test"}),
                encoding="utf-8",
            )
            keypoints = [0.0] * 75
            for joint, x, y in ((0, 100, 50), (1, 100, 100), (2, 120, 110),
                                (5, 80, 110), (8, 100, 200), (9, 110, 200), (12, 90, 200)):
                keypoints[joint * 3:joint * 3 + 3] = [x, y, 0.9]
            for frame in range(3):
                (json_dir / f"frame_{frame:012d}_keypoints.json").write_text(
                    json.dumps({"people": [{"pose_keypoints_2d": keypoints}]}), encoding="utf-8"
                )

            runner = OpenPoseRunner()
            with patch.object(runner_module, "SESSIONS_DIR", sessions_dir), \
                 patch.object(session_catalog, "SESSIONS_DIR", sessions_dir), \
                 patch.object(runner, "_run_view", side_effect=AssertionError("OpenPose reran")):
                started = runner.retry_posture("test_session", "side")
                self.assertEqual(started["views"]["side"]["openpose_status"], "complete")
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    status = runner.get_status("test_session")
                    if status["status"] != "processing":
                        break
                    time.sleep(0.1)
                self.assertEqual(status["status"], "complete", status.get("error"))
                self.assertEqual(status["views"]["side"]["posture_status"], "complete")
                detail = session_catalog.session_detail("test_session")
                self.assertEqual(len(detail["views"]["side"]["plots"]), 3)
                self.assertEqual(detail["views"]["side"]["summary"]["total_json_frames"], 3)
                with (session / "analysis" / "side" / "posture_metrics.csv").open(newline="", encoding="utf-8") as handle:
                    rows = list(csv.DictReader(handle))
                self.assertAlmostEqual(float(rows[1]["Time_seconds"]), 1 / 30)
                self.assertTrue(session_catalog.plot_path("test_session", "side", "torso_confidence.png").is_file())
                with self.assertRaises(OpenPoseRunnerError):
                    session_catalog.plot_path("test_session", "side", "..\\metadata.json")
                with self.assertRaises(OpenPoseRunnerError):
                    session_catalog.plot_path("test_session", "other", "torso_confidence.png")
                with self.assertRaises(OpenPoseRunnerError):
                    runner.retry_posture("test_session", "rear")

                (session / "raw" / "side_timestamps.csv").write_text(
                    "frame_index,seconds_from_session_start\n0,2.0\n1,2.4\n2,2.9\n", encoding="utf-8"
                )
                runner.retry_posture("test_session", "side")
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    status = runner.get_status("test_session")
                    if status["status"] != "processing":
                        break
                    time.sleep(0.1)
                self.assertEqual(status["status"], "complete", status.get("error"))
                with (session / "analysis" / "side" / "posture_metrics.csv").open(newline="", encoding="utf-8") as handle:
                    rows = list(csv.DictReader(handle))
                self.assertEqual(float(rows[1]["Time_seconds"]), 2.4)

                with patch.object(runner_module, "run_posture_analysis", side_effect=ValueError("baseline unavailable")), \
                     patch.object(runner_module.logger, "exception"):
                    runner.retry_posture("test_session", "side")
                    deadline = time.monotonic() + 30
                    while time.monotonic() < deadline:
                        status = runner.get_status("test_session")
                        if status["status"] != "processing":
                            break
                        time.sleep(0.1)
                self.assertEqual(status["views"]["side"]["openpose_status"], "complete")
                self.assertEqual(status["views"]["side"]["posture_status"], "failed")
                self.assertIn("baseline unavailable", status["error"])
                self.assertTrue((session / "raw" / "side.mp4").is_file())
                self.assertEqual(len(list(json_dir.glob("*_keypoints.json"))), 3)


if __name__ == "__main__":
    unittest.main()
