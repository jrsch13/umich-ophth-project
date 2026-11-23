from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd


DEFAULT_MIN_CONFIDENCE = 0.0

BODY25_NAMES = [
    "Nose",
    "Neck",
    "RShoulder",
    "RElbow",
    "RWrist",
    "LShoulder",
    "LElbow",
    "LWrist",
    "MidHip",
    "RHip",
    "RKnee",
    "RAnkle",
    "LHip",
    "LKnee",
    "LAnkle",
    "REye",
    "LEye",
    "REar",
    "LEar",
    "LBigToe",
    "LSmallToe",
    "LHeel",
    "RBigToe",
    "RSmallToe",
    "RHeel",
]

TORSO_JOINTS = [
    "Nose",
    "Neck",
    "RShoulder",
    "LShoulder",
    "MidHip",
    "RHip",
    "LHip",
]

_FRAME_PATTERN = re.compile(r"_(\d+)_keypoints\.json$", re.IGNORECASE)


def _frame_number(path: Path, fallback: int) -> int:
    match = _FRAME_PATTERN.search(path.name)
    if match:
        return int(match.group(1))
    return fallback


def _load_timestamp_map(timestamp_csv: str | Path | None) -> dict[int, float]:
    if timestamp_csv is None:
        return {}

    path = Path(timestamp_csv)
    if not path.is_file():
        raise FileNotFoundError(f"Timestamp CSV not found: {path}")

    timestamps = pd.read_csv(path)
    required = {"frame_index", "seconds_from_session_start"}
    missing = required - set(timestamps.columns)
    if missing:
        raise ValueError(
            f"Timestamp CSV is missing required columns: {sorted(missing)}"
        )

    clean = timestamps.dropna(
        subset=["frame_index", "seconds_from_session_start"]
    ).copy()
    return {
        int(frame): float(seconds)
        for frame, seconds in zip(
            clean["frame_index"], clean["seconds_from_session_start"]
        )
    }


def load_openpose_json_dir(
    json_dir: str | Path,
    *,
    fps: float = 30.0,
    timestamps_csv: str | Path | None = None,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> pd.DataFrame:
    """Load BODY_25 OpenPose JSON files into one wide per-frame dataframe.

    Missing-person frames are retained as rows containing NaN coordinates.
    Coordinates whose confidence is <= ``min_confidence`` are masked to NaN,
    while the original confidence value is preserved.
    """
    if fps <= 0:
        raise ValueError("fps must be greater than zero.")
    if not 0 <= min_confidence <= 1:
        raise ValueError("min_confidence must be between 0 and 1.")

    folder = Path(json_dir)
    if not folder.is_dir():
        raise FileNotFoundError(f"OpenPose JSON directory not found: {folder}")

    files = sorted(folder.glob("*_keypoints.json"))
    if not files:
        raise FileNotFoundError(
            f"No *_keypoints.json files found in: {folder}"
        )

    timestamp_map = _load_timestamp_map(timestamps_csv)

    rows: list[dict[str, float | int]] = []

    for fallback_frame, path in enumerate(files):
        frame = _frame_number(path, fallback_frame)
        row: dict[str, float | int] = {"frame": frame}

        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        people = payload.get("people", [])
        person = people[0] if people else None
        keypoints = (
            person.get("pose_keypoints_2d", [])
            if isinstance(person, dict)
            else []
        )

        for joint_index, joint_name in enumerate(BODY25_NAMES):
            base = joint_index * 3

            if len(keypoints) >= base + 3:
                x = float(keypoints[base])
                y = float(keypoints[base + 1])
                confidence = float(keypoints[base + 2])
            else:
                x = np.nan
                y = np.nan
                confidence = np.nan

            if (
                not np.isfinite(confidence)
                or confidence <= min_confidence
                or (x == 0 and y == 0)
            ):
                x = np.nan
                y = np.nan

            row[f"{joint_name}_x"] = x
            row[f"{joint_name}_y"] = y
            row[f"{joint_name}_confidence"] = confidence

        row["Time_seconds"] = timestamp_map.get(frame, frame / fps)
        rows.append(row)

    dataframe = pd.DataFrame(rows).sort_values("frame").reset_index(drop=True)
    return dataframe


def torso_confidence_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Return notebook-equivalent confidence summary for torso joints."""
    rows = []
    for joint in TORSO_JOINTS:
        column = f"{joint}_confidence"
        if column not in df:
            continue

        values = pd.to_numeric(df[column], errors="coerce")
        rows.append(
            {
                "joint": joint,
                "mean": values.mean(),
                "median": values.median(),
                "std": values.std(),
                "minimum": values.min(),
                "maximum": values.max(),
                "pct_below_0_5": (values < 0.5).mean() * 100,
                "pct_missing": values.isna().mean() * 100,
            }
        )

    return pd.DataFrame(rows)
