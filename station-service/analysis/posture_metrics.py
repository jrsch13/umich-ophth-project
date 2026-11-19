from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd


DEFAULT_THRESHOLDS = {
    "Shoulder_Hiking": 0.01,             # normalized trunk-length ratio
    "Neck_Flexion_Extension": 5.0,       # degrees
    "Trunk_Leaning": 5.0,                # degrees
    "Trunk_Flexion_Extension": 5.0,      # degrees
}


@dataclass
class Baselines:
    trunk_angle: float | None = None
    lateral_angle: float | None = None
    neck_angle: float | None = None
    right_shoulder_ratio: float | None = None
    left_shoulder_ratio: float | None = None

    def to_dict(self) -> dict[str, float | None]:
        return asdict(self)


def calc_angle_from_vertical(
    origin_x: pd.Series,
    origin_y: pd.Series,
    target_x: pd.Series,
    target_y: pd.Series,
) -> pd.Series:
    """Notebook formula: angle of origin->target relative to image vertical."""
    dx = target_x - origin_x
    dy = origin_y - target_y
    return pd.Series(
        np.degrees(np.arctan2(dx, dy)),
        index=origin_x.index,
        dtype=float,
    )


def _baseline_mean(
    values: pd.Series,
    time_seconds: pd.Series,
    neutral_seconds: float,
) -> float:
    if neutral_seconds <= 0:
        raise ValueError("neutral_seconds must be greater than zero.")

    baseline = pd.to_numeric(
        values[time_seconds < neutral_seconds], errors="coerce"
    ).dropna()

    if baseline.empty:
        raise ValueError(
            "No valid keypoints were available during the neutral baseline."
        )

    return float(baseline.mean())


def add_trunk_flexion_extension(
    df: pd.DataFrame,
    *,
    neutral_seconds: float,
) -> float:
    absolute = calc_angle_from_vertical(
        df["MidHip_x"],
        df["MidHip_y"],
        df["Neck_x"],
        df["Neck_y"],
    )
    df["Absolute_Trunk_Angle"] = absolute
    baseline = _baseline_mean(
        absolute, df["Time_seconds"], neutral_seconds
    )
    df["Trunk_Flexion_Extension"] = absolute - baseline
    return baseline


def add_trunk_lateral_lean(
    df: pd.DataFrame,
    *,
    neutral_seconds: float,
) -> float:
    # This is intentionally the same geometric formula as trunk F/E.
    # Its interpretation changes with camera plane: rear/front vs side.
    absolute = calc_angle_from_vertical(
        df["MidHip_x"],
        df["MidHip_y"],
        df["Neck_x"],
        df["Neck_y"],
    )
    df["Absolute_Lateral_Angle"] = absolute
    baseline = _baseline_mean(
        absolute, df["Time_seconds"], neutral_seconds
    )
    df["Trunk_Lean"] = absolute - baseline
    return baseline


def add_neck_flexion_extension(
    df: pd.DataFrame,
    *,
    neutral_seconds: float,
) -> float:
    head = calc_angle_from_vertical(
        df["Neck_x"],
        df["Neck_y"],
        df["Nose_x"],
        df["Nose_y"],
    )
    trunk = calc_angle_from_vertical(
        df["MidHip_x"],
        df["MidHip_y"],
        df["Neck_x"],
        df["Neck_y"],
    )

    df["Absolute_Head_Angle"] = head
    if "Absolute_Trunk_Angle" not in df:
        df["Absolute_Trunk_Angle"] = trunk

    relative = head - trunk
    df["Relative_Neck_Angle"] = relative

    baseline = _baseline_mean(
        relative, df["Time_seconds"], neutral_seconds
    )
    df["Neck_Flexion_Extension"] = relative - baseline
    return baseline


def add_shoulder_hiking(
    df: pd.DataFrame,
    *,
    neutral_seconds: float,
) -> tuple[float, float]:
    trunk_length = np.sqrt(
        (df["Neck_x"] - df["MidHip_x"]) ** 2
        + (df["Neck_y"] - df["MidHip_y"]) ** 2
    )
    trunk_length = trunk_length.where(trunk_length > 0)

    df["Trunk_Length"] = trunk_length
    df["RShoulder_Y_Dist"] = (
        df["RShoulder_y"] - df["Neck_y"]
    )
    df["LShoulder_Y_Dist"] = (
        df["LShoulder_y"] - df["Neck_y"]
    )

    df["Norm_RShoulder_Y"] = (
        df["RShoulder_Y_Dist"] / trunk_length
    )
    df["Norm_LShoulder_Y"] = (
        df["LShoulder_Y_Dist"] / trunk_length
    )

    baseline_r = _baseline_mean(
        df["Norm_RShoulder_Y"],
        df["Time_seconds"],
        neutral_seconds,
    )
    baseline_l = _baseline_mean(
        df["Norm_LShoulder_Y"],
        df["Time_seconds"],
        neutral_seconds,
    )

    # Notebook convention:
    # baseline (larger Y distance) - current (smaller distance)
    # => positive values when the shoulder moves upward.
    df["Right_Shoulder_Hiking_Dist"] = (
        baseline_r - df["Norm_RShoulder_Y"]
    )
    df["Left_Shoulder_Hiking_Dist"] = (
        baseline_l - df["Norm_LShoulder_Y"]
    )

    return baseline_r, baseline_l


def compute_metrics(
    df: pd.DataFrame,
    *,
    view: str,
    neutral_seconds: float = 10.0,
) -> tuple[pd.DataFrame, Baselines]:
    """Compute notebook-derived posture metrics.

    view='side':
        trunk flexion/extension + neck flexion/extension

    view='rear':
        trunk lateral lean + shoulder hiking

    view='all':
        all four metrics, useful for reproducing notebook experiments.
    """
    normalized_view = view.strip().lower()
    if normalized_view not in {"side", "rear", "all"}:
        raise ValueError("view must be one of: side, rear, all")

    result = df.copy()
    baselines = Baselines()

    if normalized_view in {"side", "all"}:
        baselines.trunk_angle = add_trunk_flexion_extension(
            result, neutral_seconds=neutral_seconds
        )
        baselines.neck_angle = add_neck_flexion_extension(
            result, neutral_seconds=neutral_seconds
        )

    if normalized_view in {"rear", "all"}:
        baselines.lateral_angle = add_trunk_lateral_lean(
            result, neutral_seconds=neutral_seconds
        )
        (
            baselines.right_shoulder_ratio,
            baselines.left_shoulder_ratio,
        ) = add_shoulder_hiking(
            result, neutral_seconds=neutral_seconds
        )

    return result, baselines


def classify_frames(
    df: pd.DataFrame,
    *,
    thresholds: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Apply the notebook's initial threshold classifications."""
    limits = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        limits.update(thresholds)

    result = df.copy()
    available_flags: list[str] = []

    if "Trunk_Flexion_Extension" in result:
        name = "Trunk_Flexion_Extension_Flag"
        result[name] = (
            result["Trunk_Flexion_Extension"].abs()
            >= limits["Trunk_Flexion_Extension"]
        ).astype("Int64")
        available_flags.append(name)

    if "Trunk_Lean" in result:
        name = "Trunk_Leaning_Flag"
        result[name] = (
            result["Trunk_Lean"].abs()
            >= limits["Trunk_Leaning"]
        ).astype("Int64")
        available_flags.append(name)

    if "Neck_Flexion_Extension" in result:
        name = "Neck_Flexion_Extension_Flag"
        result[name] = (
            result["Neck_Flexion_Extension"].abs()
            >= limits["Neck_Flexion_Extension"]
        ).astype("Int64")
        available_flags.append(name)

    if {
        "Right_Shoulder_Hiking_Dist",
        "Left_Shoulder_Hiking_Dist",
    }.issubset(result.columns):
        name = "Shoulder_Hiking_Flag"
        result[name] = (
            (
                result["Right_Shoulder_Hiking_Dist"]
                >= limits["Shoulder_Hiking"]
            )
            | (
                result["Left_Shoulder_Hiking_Dist"]
                >= limits["Shoulder_Hiking"]
            )
        ).astype("Int64")
        available_flags.append(name)

    labels = {
        "Trunk_Flexion_Extension_Flag": "Trunk_Flexion_Extension",
        "Trunk_Leaning_Flag": "Trunk_Leaning",
        "Neck_Flexion_Extension_Flag": "Neck_Flexion_Extension",
        "Shoulder_Hiking_Flag": "Shoulder_Hiking",
    }

    def classify_row(row: pd.Series) -> str:
        active = [
            labels[column]
            for column in available_flags
            if pd.notna(row[column]) and int(row[column]) == 1
        ]
        return " + ".join(active) if active else "Neutral"

    result["Posture_Classification"] = result.apply(
        classify_row, axis=1
    )
    return result
