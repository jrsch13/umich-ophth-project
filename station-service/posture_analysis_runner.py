"""Session-specific adapter for the reusable BODY_25 posture analysis."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from analysis.analyze_openpose import DEFAULT_FPS, DEFAULT_NEUTRAL_SECONDS, analyze_openpose


EXPECTED_PLOTS = {
    "side": ("torso_confidence.png", "trunk_flexion_extension.png", "neck_flexion_extension.png"),
    "rear": ("torso_confidence.png", "trunk_lateral_lean.png", "shoulder_hiking.png"),
}


def run_posture_analysis(session_dir: Path, view: str) -> dict[str, Any]:
    if view not in EXPECTED_PLOTS:
        raise ValueError("View must be side or rear.")

    json_dir = session_dir / "openpose" / view / "json"
    if not json_dir.is_dir() or not any(json_dir.glob("*_keypoints.json")):
        raise FileNotFoundError(f"No OpenPose BODY_25 JSON frames found for {view}: {json_dir}")

    timestamp_path = session_dir / "raw" / f"{view}_timestamps.csv"
    output_dir = session_dir / "analysis" / view
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = session_dir / "metadata.json"
    total_session_seconds = None
    if metadata_path.is_file():
        with metadata_path.open(encoding="utf-8") as handle:
            metadata = json.load(handle)
        if isinstance(metadata, dict):
            try:
                duration = float(metadata.get("duration_seconds"))
            except (TypeError, ValueError):
                duration = math.nan
            if math.isfinite(duration) and duration > 0:
                total_session_seconds = duration

    analyze_openpose(
        json_dir,
        output_dir,
        view=view,
        fps=DEFAULT_FPS,
        neutral_seconds=DEFAULT_NEUTRAL_SECONDS,
        timestamps_csv=timestamp_path if timestamp_path.is_file() else None,
        total_session_seconds=total_session_seconds,
    )

    required = [
        output_dir / "posture_metrics.csv",
        output_dir / "confidence_summary.csv",
        output_dir / "summary.json",
        *(output_dir / "plots" / name for name in EXPECTED_PLOTS[view]),
    ]
    missing = [path.name for path in required if not path.is_file() or path.stat().st_size == 0]
    if missing:
        raise RuntimeError(f"Posture analysis did not produce expected artifacts: {', '.join(missing)}")
    return {
        "analysis_dir": f"analysis/{view}",
        "summary": f"analysis/{view}/summary.json",
        "plots": list(EXPECTED_PLOTS[view]),
    }
