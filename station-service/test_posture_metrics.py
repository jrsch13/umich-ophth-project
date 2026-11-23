from __future__ import annotations

import unittest
import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.posture_metrics import (
    UPRIGHT_TOLERANCE_DEG,
    add_shoulder_hiking,
    add_trunk_lateral_lean,
    neck_rula_category,
    trunk_rula_category,
)
from analysis.openpose_io import load_openpose_json_dir


class RulaPostureMetricTests(unittest.TestCase):
    def test_neck_category_boundaries(self) -> None:
        cases = [
            (0.0, "flexion_0_10", 1),
            (9.999, "flexion_0_10", 1),
            (10.0, "flexion_0_10", 1),
            (10.001, "flexion_10_20", 2),
            (19.999, "flexion_10_20", 2),
            (20.0, "flexion_10_20", 2),
            (20.001, "flexion_over_20", 3),
            (-0.001, "extension", 4),
        ]
        for angle, key, score in cases:
            with self.subTest(angle=angle):
                category = neck_rula_category(angle)
                self.assertEqual(category["key"], key)
                self.assertEqual(category["rula_score"], score)

    def test_trunk_category_boundaries(self) -> None:
        cases = [
            (0.0, "upright", 1),
            (UPRIGHT_TOLERANCE_DEG, "upright", 1),
            (UPRIGHT_TOLERANCE_DEG + 0.001, "flexion_0_20", 2),
            (19.999, "flexion_0_20", 2),
            (20.0, "flexion_20_60", 3),
            (59.999, "flexion_20_60", 3),
            (60.0, "flexion_20_60", 3),
            (60.001, "flexion_over_60", 4),
        ]
        for angle, key, score in cases:
            with self.subTest(angle=angle):
                category = trunk_rula_category(angle)
                self.assertEqual(category["key"], key)
                self.assertEqual(category["rula_score"], score)

    def test_upright_tolerance_is_project_specific_and_documented(self) -> None:
        self.assertEqual(UPRIGHT_TOLERANCE_DEG, 5.0)
        category = trunk_rula_category(UPRIGHT_TOLERANCE_DEG)
        self.assertEqual(category["key"], "upright")
        self.assertEqual(category["rula_score"], 1)

    def test_lateral_and_shoulder_project_thresholds(self) -> None:
        df = pd.DataFrame({
            "Time_seconds": [0.0, 1.0, 2.0, 3.0],
            "RHip_x": [50.0] * 4,
            "RHip_y": [100.0] * 4,
            "RHip_confidence": [0.9] * 4,
            "LHip_x": [150.0] * 4,
            "LHip_y": [100.0] * 4,
            "LHip_confidence": [0.9] * 4,
            "RShoulder_x": [45.0] * 4,
            "RShoulder_y": [20.0, 20.0, 0.0, 20.0],
            "RShoulder_confidence": [0.9] * 4,
            "LShoulder_x": [155.0] * 4,
            "LShoulder_y": [20.0, 20.0, 20.0, 0.0],
            "LShoulder_confidence": [0.9] * 4,
        })
        add_shoulder_hiking(df, neutral_seconds=2.0)

        self.assertGreater(
            df.loc[2, "R_Shoulder_Hiking_Pct_Hip_Width"],
            18.0,
        )
        self.assertEqual(
            df.loc[2, "Shoulder_Hiking_Class"],
            "Unilateral Right Hiking",
        )
        self.assertGreater(
            df.loc[3, "L_Shoulder_Hiking_Pct_Hip_Width"],
            18.0,
        )
        self.assertEqual(
            df.loc[3, "Shoulder_Hiking_Class"],
            "Unilateral Left Hiking",
        )
        self.assertFalse(
            df.loc[0, "Shoulder_Raised_Adjustment_Present"]
        )

    def test_bilateral_shoulder_hiking_class(self) -> None:
        df = pd.DataFrame({
            "Time_seconds": [0.0, 1.0],
            "RHip_x": [50.0] * 2,
            "RHip_y": [100.0] * 2,
            "RHip_confidence": [0.9] * 2,
            "LHip_x": [150.0] * 2,
            "LHip_y": [100.0] * 2,
            "LHip_confidence": [0.9] * 2,
            "RShoulder_x": [45.0] * 2,
            "RShoulder_y": [20.0, 0.0],
            "RShoulder_confidence": [0.9] * 2,
            "LShoulder_x": [155.0] * 2,
            "LShoulder_y": [20.0, 0.0],
            "LShoulder_confidence": [0.9] * 2,
        })
        add_shoulder_hiking(df, neutral_seconds=1.0)
        self.assertEqual(df.loc[1, "Shoulder_Hiking_Class"], "Bilateral Hiking")

    def test_lateral_adjustment_uses_project_tolerance(self) -> None:
        df = pd.DataFrame({
            "Time_seconds": [0.0, 1.0],
            "MidHip_x": [100.0, 100.0],
            "MidHip_y": [200.0, 200.0],
            "Neck_x": [105.0, 110.0],
            "Neck_y": [100.0, 100.0],
        })
        add_trunk_lateral_lean(df, neutral_seconds=1.0)
        self.assertFalse(df.loc[0, "Trunk_Sidebend_Adjustment_Present"])
        self.assertTrue(df.loc[1, "Trunk_Sidebend_Adjustment_Present"])

    def test_configurable_low_confidence_masks_coordinates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            json_dir = Path(temporary)
            keypoints = [0.0] * 75
            keypoints[0:3] = [100.0, 100.0, 0.05]
            (json_dir / "frame_000000000000_keypoints.json").write_text(
                json.dumps({"people": [{"pose_keypoints_2d": keypoints}]}),
                encoding="utf-8",
            )
            df = load_openpose_json_dir(json_dir, min_confidence=0.10)
        self.assertTrue(pd.isna(df.loc[0, "Nose_x"]))

    def test_missing_shoulder_keypoints_stay_unknown(self) -> None:
        df = pd.DataFrame({
            "Time_seconds": [0.0, 1.0],
            "RHip_x": [50.0, np.nan],
            "RHip_y": [100.0, np.nan],
            "RHip_confidence": [0.9, np.nan],
            "LHip_x": [150.0, np.nan],
            "LHip_y": [100.0, np.nan],
            "LHip_confidence": [0.9, np.nan],
            "RShoulder_x": [45.0, np.nan],
            "RShoulder_y": [20.0, np.nan],
            "RShoulder_confidence": [0.9, np.nan],
            "LShoulder_x": [155.0, np.nan],
            "LShoulder_y": [20.0, np.nan],
            "LShoulder_confidence": [0.9, np.nan],
        })
        add_shoulder_hiking(df, neutral_seconds=1.0)
        self.assertTrue(pd.isna(df.loc[1, "R_Shoulder_Hiking_Pct_Hip_Width"]))
        self.assertEqual(df.loc[1, "Shoulder_Hiking_Class"], "Unknown")


if __name__ == "__main__":
    unittest.main()
