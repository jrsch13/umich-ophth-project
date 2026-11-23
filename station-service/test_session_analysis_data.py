"""Tests for posture exposure, time-series, and saved-frame APIs."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from fastapi.testclient import TestClient

import app as station_app
import openpose_runner as runner_module
import session_catalog
from analysis.posture_metrics import DEFAULT_THRESHOLDS
from session_analysis_data import METRIC_SPECS, metric_time_series, posture_summaries


class SessionAnalysisDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.sessions_dir = Path(self.temporary.name)
        self.session_dir = self.sessions_dir / "test_session"
        (self.session_dir / "raw").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_metrics(
        self,
        view: str,
        columns: tuple[str, ...],
        rows: list[dict[str, object]],
    ) -> None:
        output = self.session_dir / "analysis" / view
        output.mkdir(parents=True, exist_ok=True)
        fieldnames = ["frame", "Time_seconds", *columns]
        with (output / "posture_metrics.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def write_timestamps(self, view: str, values: list[tuple[int, float]]) -> None:
        path = self.session_dir / "raw" / f"{view}_timestamps.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(("frame_index", "seconds_from_session_start"))
            writer.writerows(values)

    def write_video(self, view: str, frame_count: int = 3) -> Path:
        path = self.session_dir / "raw" / f"{view}.mp4"
        writer = cv2.VideoWriter(
            str(path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            10.0,
            (64, 48),
        )
        self.assertTrue(writer.isOpened(), "OpenCV mp4v VideoWriter is unavailable.")
        for index in range(frame_count):
            image = np.zeros((48, 64, 3), dtype=np.uint8)
            image[:, :, index % 3] = 100 + index * 30
            writer.write(image)
        writer.release()
        return path

    def test_exposure_uses_recorded_frame_timestamps(self) -> None:
        self.write_video("side")
        self.write_timestamps("side", [(0, 0.0), (1, 0.1), (2, 0.3)])
        self.write_metrics("side", ("Neck_Flexion_Extension",), [
            {"frame": 0, "Time_seconds": 0.0, "Neck_Flexion_Extension": 4.0},
            {"frame": 1, "Time_seconds": 0.033, "Neck_Flexion_Extension": 6.0},
            {"frame": 2, "Time_seconds": 0.066, "Neck_Flexion_Extension": 6.0},
        ])

        result = next(
            item for item in posture_summaries(self.session_dir, {"duration_seconds": 0.5})
            if item["metric"] == "neck_flexion_extension"
        )

        self.assertEqual(result["threshold"], DEFAULT_THRESHOLDS["Neck_Flexion_Extension"])
        self.assertEqual(result["within_threshold_seconds"], 0.1)
        self.assertEqual(result["above_threshold_seconds"], 0.4)
        self.assertEqual(result["valid_tracking_seconds"], 0.5)
        self.assertEqual(result["within_threshold_percent"], 20.0)
        self.assertEqual(result["above_threshold_percent"], 80.0)

    def test_missing_pose_intervals_are_excluded_from_within_threshold(self) -> None:
        self.write_video("side")
        self.write_timestamps("side", [(0, 0.0), (1, 0.1), (2, 0.2)])
        self.write_metrics("side", ("Neck_Flexion_Extension",), [
            {"frame": 0, "Time_seconds": 0.0, "Neck_Flexion_Extension": 1.0},
            {"frame": 1, "Time_seconds": 0.1, "Neck_Flexion_Extension": ""},
            {"frame": 2, "Time_seconds": 0.2, "Neck_Flexion_Extension": 1.0},
        ])

        result = next(
            item for item in posture_summaries(self.session_dir, {"duration_seconds": 0.3})
            if item["metric"] == "neck_flexion_extension"
        )

        self.assertEqual(result["within_threshold_seconds"], 0.2)
        self.assertEqual(result["above_threshold_seconds"], 0.0)
        self.assertEqual(result["valid_tracking_seconds"], 0.2)
        self.assertEqual(result["valid_tracking_percent"], 66.67)

    def test_posture_metrics_map_to_the_existing_views_and_columns(self) -> None:
        self.assertEqual(METRIC_SPECS["neck_flexion_extension"].view, "side")
        self.assertEqual(METRIC_SPECS["neck_flexion_extension"].columns, ("Neck_Flexion_Extension",))
        self.assertEqual(METRIC_SPECS["forward_trunk_lean"].view, "side")
        self.assertEqual(METRIC_SPECS["forward_trunk_lean"].columns, ("Trunk_Flexion_Extension",))
        self.assertEqual(METRIC_SPECS["lateral_trunk_lean"].view, "rear")
        self.assertEqual(METRIC_SPECS["lateral_trunk_lean"].columns, ("Trunk_Lean",))
        self.assertEqual(METRIC_SPECS["shoulder_hiking"].view, "rear")
        self.assertEqual(
            METRIC_SPECS["shoulder_hiking"].columns,
            ("Right_Shoulder_Hiking_Dist", "Left_Shoulder_Hiking_Dist"),
        )

    def test_unprocessed_recording_is_not_reported_as_unreadable(self) -> None:
        self.write_video("side")

        result = next(
            item for item in posture_summaries(self.session_dir, {"duration_seconds": 0.3})
            if item["metric"] == "neck_flexion_extension"
        )

        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], "analysis_not_available")

    def test_shoulder_exposure_uses_either_side_over_threshold(self) -> None:
        self.write_video("rear")
        self.write_timestamps("rear", [(0, 0.0), (1, 0.1), (2, 0.2)])
        self.write_metrics("rear", (
            "Right_Shoulder_Hiking_Dist", "Left_Shoulder_Hiking_Dist",
        ), [
            {"frame": 0, "Time_seconds": 0.0, "Right_Shoulder_Hiking_Dist": 0.0, "Left_Shoulder_Hiking_Dist": 0.02},
            {"frame": 1, "Time_seconds": 0.1, "Right_Shoulder_Hiking_Dist": 0.02, "Left_Shoulder_Hiking_Dist": 0.0},
            {"frame": 2, "Time_seconds": 0.2, "Right_Shoulder_Hiking_Dist": 0.0, "Left_Shoulder_Hiking_Dist": 0.0},
        ])

        result = next(
            item for item in posture_summaries(self.session_dir, {"duration_seconds": 0.3})
            if item["metric"] == "shoulder_hiking"
        )

        self.assertEqual(result["threshold"], DEFAULT_THRESHOLDS["Shoulder_Hiking"])
        self.assertEqual(result["above_threshold_seconds"], 0.2)
        self.assertEqual(result["within_threshold_seconds"], 0.1)

    def test_time_series_uses_original_source_frame_numbers(self) -> None:
        (self.session_dir / "raw" / "side.mp4").write_bytes(b"recorded video")
        self.write_metrics("side", ("Neck_Flexion_Extension",), [
            {"frame": 10, "Time_seconds": 0.0, "Neck_Flexion_Extension": 1.0},
            {"frame": 12, "Time_seconds": 0.2, "Neck_Flexion_Extension": 6.0},
            {"frame": 15, "Time_seconds": 0.5, "Neck_Flexion_Extension": 2.0},
        ])

        with patch.object(runner_module, "SESSIONS_DIR", self.sessions_dir):
            response = TestClient(station_app.app).get(
                "/sessions/test_session/analysis/metrics/neck_flexion_extension"
            )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual([point["frame"] for point in result["points"]], [10, 12, 15])
        self.assertEqual([point["time_seconds"] for point in result["points"]], [0.0, 0.2, 0.5])
        self.assertEqual(result["points"][1]["value"], 6.0)

    def test_shoulder_time_series_keeps_both_values(self) -> None:
        (self.session_dir / "raw" / "rear.mp4").write_bytes(b"recorded video")
        self.write_metrics("rear", (
            "Right_Shoulder_Hiking_Dist", "Left_Shoulder_Hiking_Dist",
        ), [
            {"frame": 3, "Time_seconds": 0.1, "Right_Shoulder_Hiking_Dist": 0.02, "Left_Shoulder_Hiking_Dist": 0.0},
        ])

        point = metric_time_series(self.session_dir, "shoulder_hiking")["points"][0]

        self.assertEqual(point, {
            "time_seconds": 0.1,
            "frame": 3,
            "right_value": 0.02,
            "left_value": 0.0,
        })

    def test_time_series_downsampling_is_bounded_and_keeps_real_frames(self) -> None:
        (self.session_dir / "raw" / "side.mp4").write_bytes(b"recorded video")
        self.write_metrics("side", ("Neck_Flexion_Extension",), [
            {
                "frame": frame * 2,
                "Time_seconds": frame / 30,
                "Neck_Flexion_Extension": 10.0 if frame == 2500 else (6.0 if frame % 2 else 1.0),
            }
            for frame in range(5000)
        ])

        result = metric_time_series(self.session_dir, "neck_flexion_extension")
        frames = [point["frame"] for point in result["points"]]

        self.assertTrue(result["downsampled"])
        self.assertLessEqual(len(frames), 2000)
        self.assertEqual(len(frames), len(set(frames)))
        self.assertIn(5000, frames)

    def test_session_detail_marks_rear_metrics_unavailable_for_side_only_recording(self) -> None:
        self.write_video("side")
        (self.session_dir / "metadata.json").write_text(json.dumps({
            "session_label": "Side only",
            "duration_seconds": 0.3,
        }), encoding="utf-8")
        (self.session_dir / "analysis_status.json").write_text(json.dumps({
            "status": "pending",
            "views": {"side": {"status": "pending"}},
        }), encoding="utf-8")

        with patch.object(runner_module, "SESSIONS_DIR", self.sessions_dir), \
             patch.object(session_catalog, "SESSIONS_DIR", self.sessions_dir):
            detail = session_catalog.session_detail("test_session")

        summaries = {item["metric"]: item for item in detail["posture_summaries"]}
        self.assertEqual(summaries["shoulder_hiking"]["status"], "unavailable")
        self.assertEqual(summaries["shoulder_hiking"]["reason"], "view_not_recorded")
        self.assertEqual(summaries["lateral_trunk_lean"]["reason"], "view_not_recorded")
        self.assertNotIn("points", detail["posture_summaries"][0])

    def test_frame_endpoint_returns_jpeg_image(self) -> None:
        self.write_video("side")
        with patch.object(runner_module, "SESSIONS_DIR", self.sessions_dir):
            response = TestClient(station_app.app).get(
                "/sessions/test_session/analysis/frame",
                params={"view": "side", "frame": 1},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/jpeg")
        decoded = cv2.imdecode(np.frombuffer(response.content, dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded.shape[:2], (48, 64))

    def test_frame_endpoint_rejects_out_of_range_frame(self) -> None:
        self.write_video("side")
        with patch.object(runner_module, "SESSIONS_DIR", self.sessions_dir):
            response = TestClient(station_app.app).get(
                "/sessions/test_session/analysis/frame",
                params={"view": "side", "frame": 3},
            )
        self.assertEqual(response.status_code, 404)

    def test_frame_endpoint_rejects_invalid_view(self) -> None:
        with patch.object(runner_module, "SESSIONS_DIR", self.sessions_dir):
            response = TestClient(station_app.app).get(
                "/sessions/test_session/analysis/frame",
                params={"view": "front", "frame": 0},
            )
        self.assertEqual(response.status_code, 400)

    def test_frame_endpoint_reports_missing_video(self) -> None:
        with patch.object(runner_module, "SESSIONS_DIR", self.sessions_dir):
            response = TestClient(station_app.app).get(
                "/sessions/test_session/analysis/frame",
                params={"view": "rear", "frame": 0},
            )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
