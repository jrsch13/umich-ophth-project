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
import pandas as pd
from fastapi.testclient import TestClient

import app as station_app
import openpose_runner as runner_module
import session_catalog
from analysis.analyze_openpose import build_summary
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
        self.write_metrics("side", ("Neck_Flexion_Extension", "Neck_RULA_Category"), [
            {"frame": 0, "Time_seconds": 0.0, "Neck_Flexion_Extension": 4.0, "Neck_RULA_Category": "flexion_0_10"},
            {"frame": 1, "Time_seconds": 0.033, "Neck_Flexion_Extension": 6.0, "Neck_RULA_Category": "flexion_0_10"},
            {"frame": 2, "Time_seconds": 0.066, "Neck_Flexion_Extension": 6.0, "Neck_RULA_Category": "flexion_10_20"},
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

    def test_category_duration_uses_timestamps_and_excludes_invalid_tracking(self) -> None:
        self.write_video("side")
        self.write_timestamps("side", [(0, 0.0), (1, 0.1), (2, 0.3)])
        self.write_metrics("side", (
            "Neck_Flexion_Extension",
            "Neck_RULA_Category",
        ), [
            {"frame": 0, "Time_seconds": 0.0, "Neck_Flexion_Extension": 5.0, "Neck_RULA_Category": "flexion_0_10"},
            {"frame": 1, "Time_seconds": 0.1, "Neck_Flexion_Extension": "", "Neck_RULA_Category": ""},
            {"frame": 2, "Time_seconds": 0.3, "Neck_Flexion_Extension": 15.0, "Neck_RULA_Category": "flexion_10_20"},
        ])

        result = next(
            item for item in posture_summaries(self.session_dir, {"duration_seconds": 0.5})
            if item["metric"] == "neck_flexion_extension"
        )
        distribution = {
            item["key"]: item
            for item in result["category_distribution"]
        }
        self.assertEqual(result["valid_tracking_seconds"], 0.3)
        self.assertEqual(distribution["flexion_0_10"]["seconds"], 0.1)
        self.assertEqual(distribution["flexion_10_20"]["seconds"], 0.2)
        self.assertEqual(distribution["flexion_10_20"]["percent_of_valid_time"], 66.67)

    def test_missing_pose_intervals_are_excluded_from_within_threshold(self) -> None:
        self.write_video("side")
        self.write_timestamps("side", [(0, 0.0), (1, 0.1), (2, 0.2)])
        self.write_metrics("side", ("Neck_Flexion_Extension", "Neck_RULA_Category"), [
            {"frame": 0, "Time_seconds": 0.0, "Neck_Flexion_Extension": 1.0, "Neck_RULA_Category": "flexion_0_10"},
            {"frame": 1, "Time_seconds": 0.1, "Neck_Flexion_Extension": "", "Neck_RULA_Category": ""},
            {"frame": 2, "Time_seconds": 0.2, "Neck_Flexion_Extension": 1.0, "Neck_RULA_Category": "flexion_0_10"},
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
        self.assertEqual(METRIC_SPECS["shoulder_hiking"].unit, "% of hip width")
        self.assertEqual(
            METRIC_SPECS["shoulder_hiking"].columns,
            (
                "R_Shoulder_Hiking_Pct_Hip_Width",
                "L_Shoulder_Hiking_Pct_Hip_Width",
            ),
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
            "R_Shoulder_Hiking_Pct_Hip_Width",
            "L_Shoulder_Hiking_Pct_Hip_Width",
            "Shoulder_Hiking_Class",
        ), [
            {"frame": 0, "Time_seconds": 0.0, "R_Shoulder_Hiking_Pct_Hip_Width": 0.0, "L_Shoulder_Hiking_Pct_Hip_Width": 18.0, "Shoulder_Hiking_Class": "Unilateral Left Hiking"},
            {"frame": 1, "Time_seconds": 0.1, "R_Shoulder_Hiking_Pct_Hip_Width": 18.0, "L_Shoulder_Hiking_Pct_Hip_Width": 0.0, "Shoulder_Hiking_Class": "Unilateral Right Hiking"},
            {"frame": 2, "Time_seconds": 0.2, "R_Shoulder_Hiking_Pct_Hip_Width": 0.0, "L_Shoulder_Hiking_Pct_Hip_Width": 0.0, "Shoulder_Hiking_Class": "Neutral"},
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

    def test_forward_trunk_time_series_exposes_absolute_posture_angle(self) -> None:
        (self.session_dir / "raw" / "side.mp4").write_bytes(b"recorded video")
        self.write_metrics("side", (
            "Trunk_Flexion_Extension",
            "Trunk_Angle_Deg",
            "Trunk_RULA_Category",
        ), [
            {
                "frame": 12,
                "Time_seconds": 0.4,
                "Trunk_Flexion_Extension": -4.0,
                "Trunk_Angle_Deg": -24.1,
                "Trunk_RULA_Category": "flexion_20_60",
            },
        ])

        point = metric_time_series(
            self.session_dir, "forward_trunk_lean"
        )["points"][0]

        self.assertEqual(point["frame"], 12)
        self.assertEqual(point["value"], -4.0)
        self.assertEqual(point["posture_angle_deg"], 24.1)
        self.assertEqual(point["category"], "flexion_20_60")

    def test_shoulder_time_series_keeps_both_values(self) -> None:
        (self.session_dir / "raw" / "rear.mp4").write_bytes(b"recorded video")
        self.write_metrics("rear", (
            "R_Shoulder_Hiking_Pct_Hip_Width",
            "L_Shoulder_Hiking_Pct_Hip_Width",
        ), [
            {"frame": 3, "Time_seconds": 0.1, "R_Shoulder_Hiking_Pct_Hip_Width": 2.0, "L_Shoulder_Hiking_Pct_Hip_Width": 0.0},
        ])

        point = metric_time_series(self.session_dir, "shoulder_hiking")["points"][0]

        self.assertEqual(point, {
            "time_seconds": 0.1,
            "frame": 3,
            "right_value": 2.0,
            "left_value": 0.0,
        })

    def test_rula_categories_are_canonical_and_tracking_percent_is_populated(self) -> None:
        self.write_video("side")
        self.write_timestamps("side", [(0, 0.0), (1, 0.1), (2, 0.2)])
        self.write_metrics("side", (
            "Neck_Flexion_Extension",
            "Neck_RULA_Category",
            "Trunk_Flexion_Extension",
            "Trunk_Angle_Deg",
            "Trunk_RULA_Category",
        ), [
            {"frame": 0, "Time_seconds": 0.0, "Neck_Flexion_Extension": 1.0, "Neck_RULA_Category": "flexion_0_10", "Trunk_Flexion_Extension": 0.0, "Trunk_Angle_Deg": 2.0, "Trunk_RULA_Category": "upright"},
            {"frame": 1, "Time_seconds": 0.1, "Neck_Flexion_Extension": 6.0, "Neck_RULA_Category": "flexion_0_10", "Trunk_Flexion_Extension": 50.0, "Trunk_Angle_Deg": 10.0, "Trunk_RULA_Category": "flexion_0_20"},
            {"frame": 2, "Time_seconds": 0.2, "Neck_Flexion_Extension": 25.0, "Neck_RULA_Category": "flexion_10_20", "Trunk_Flexion_Extension": 0.0, "Trunk_Angle_Deg": 10.0, "Trunk_RULA_Category": "flexion_0_20"},
        ])
        view_summary = build_summary(
            pd.DataFrame([
                {"Time_seconds": 0.0, "Neck_RULA_Category": "flexion_0_10", "Trunk_RULA_Category": "upright"},
                {"Time_seconds": 0.1, "Neck_RULA_Category": "flexion_0_10", "Trunk_RULA_Category": "flexion_0_20"},
                {"Time_seconds": 0.2, "Neck_RULA_Category": "flexion_10_20", "Trunk_RULA_Category": "flexion_0_20"},
            ]),
            view="side",
            baselines={},
            thresholds={
                **DEFAULT_THRESHOLDS,
                "Neck_Flexion_Extension": 9999,
                "Trunk_Flexion_Extension": 9999,
            },
            neutral_seconds=10.0,
        )
        (self.session_dir / "analysis" / "side" / "summary.json").write_text(
            json.dumps(view_summary),
            encoding="utf-8",
        )
        (self.session_dir / "metadata.json").write_text(
            json.dumps({"duration_seconds": 0.3}),
            encoding="utf-8",
        )

        with patch.object(runner_module, "SESSIONS_DIR", self.sessions_dir), \
             patch.object(session_catalog, "SESSIONS_DIR", self.sessions_dir):
            response = TestClient(station_app.app).get("/sessions/test_session")

        self.assertEqual(response.status_code, 200)
        detail = response.json()
        summaries = {item["metric"]: item for item in detail["posture_summaries"]}
        forward = summaries["forward_trunk_lean"]
        distribution = {
            item["key"]: item
            for item in forward["category_distribution"]
        }
        self.assertEqual(distribution["upright"]["rula_score"], 1)
        self.assertEqual(distribution["flexion_0_20"]["rula_score"], 2)
        self.assertAlmostEqual(
            sum(item["percent_of_valid_time"] for item in forward["category_distribution"]),
            100.0,
            delta=0.01,
        )
        self.assertEqual(forward["valid_tracking_percent"], 100.0)
        self.assertEqual(forward["category_definition"]["upright_tolerance_degrees"], 5.0)
        self.assertTrue(forward["legacy_binary_threshold_exposure_deprecated"])
        self.assertEqual(
            detail["views"]["side"]["summary"]["categorization_tolerances"]["trunk_rula_upright_degrees"]["value"],
            5.0,
        )
        self.assertEqual(
            detail["views"]["side"]["summary"]["category_distributions"]["forward_trunk"]["valid_tracking_percent"],
            forward["valid_tracking_percent"],
        )

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
