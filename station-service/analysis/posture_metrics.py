from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd


DEFAULT_THRESHOLDS = {
    "Shoulder_Hiking": 18.0,             # project detection tolerance: percent of hip width
    "Neck_Flexion_Extension": 5.0,       # degrees
    "Trunk_Leaning": 5.0,                # project side-bending detection tolerance
    "Trunk_Flexion_Extension": 5.0,      # degrees
}
DEFAULT_NEUTRAL_SECONDS = 10.0
DEFAULT_MIN_CONFIDENCE = 0.0
UPRIGHT_TOLERANCE_DEG = 5.0

# RULA posture bands. Neck extension is score 4. These boundaries are
# inclusive at the lower endpoint and exclusive at the upper endpoint except
# where a band is the terminal score.
def neck_rula_category(angle_deg: float | None) -> dict[str, object] | None:
    if angle_deg is None or not np.isfinite(angle_deg):
        return None
    if angle_deg < 0:
        return {"key": "extension", "label": "Extension", "rula_score": 4}
    if angle_deg <= 10:
        return {"key": "flexion_0_10", "label": "0-10 degrees flexion", "rula_score": 1}
    if angle_deg <= 20:
        return {"key": "flexion_10_20", "label": "10-20 degrees flexion", "rula_score": 2}
    return {"key": "flexion_over_20", "label": "Over 20 degrees flexion", "rula_score": 3}


def trunk_rula_category(angle_deg: float | None) -> dict[str, object] | None:
    if angle_deg is None or not np.isfinite(angle_deg):
        return None
    magnitude = abs(float(angle_deg))
    if magnitude <= UPRIGHT_TOLERANCE_DEG:
        return {"key": "upright", "label": "Approximately upright", "rula_score": 1}
    if magnitude < 20:
        return {"key": "flexion_0_20", "label": "0-20 degrees flexion", "rula_score": 2}
    if magnitude <= 60:
        return {"key": "flexion_20_60", "label": "20-60 degrees flexion", "rula_score": 3}
    return {"key": "flexion_over_60", "label": "Over 60 degrees flexion", "rula_score": 4}


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


def _baseline_median(
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
    return float(baseline.median())


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
    df["Trunk_Angle_Deg"] = absolute
    df["Trunk_Valid"] = absolute.notna()
    df["Trunk_RULA_Category"] = [
        None if item is None else item["key"]
        for item in (trunk_rula_category(value) for value in absolute)
    ]
    df["Trunk_RULA_Posture_Score"] = [
        None if item is None else item["rula_score"]
        for item in (trunk_rula_category(value) for value in absolute)
    ]
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
    df["Lateral_Lean_Deg"] = absolute.abs()
    df["Lateral_Valid"] = absolute.notna()
    df["Trunk_Sidebend_Adjustment_Present"] = (
        df["Lateral_Lean_Deg"] >= DEFAULT_THRESHOLDS["Trunk_Leaning"]
    ).astype("boolean")
    df.loc[~df["Lateral_Valid"], "Trunk_Sidebend_Adjustment_Present"] = pd.NA
    return baseline


def add_neck_flexion_extension(
    df: pd.DataFrame,
    *,
    neutral_seconds: float,
) -> float:
    right_ear_confidence = pd.to_numeric(
        df["REar_confidence"], errors="coerce"
    )
    left_ear_confidence = pd.to_numeric(
        df["LEar_confidence"], errors="coerce"
    )
    facing_side = (
        "R"
        if right_ear_confidence.median() > left_ear_confidence.median()
        else "L"
    )
    ear = f"{facing_side}Ear"
    shoulder = f"{facing_side}Shoulder"

    head = calc_angle_from_vertical(
        df[f"{shoulder}_x"],
        df[f"{shoulder}_y"],
        df[f"{ear}_x"],
        df[f"{ear}_y"],
    )
    trunk = calc_angle_from_vertical(
        df["MidHip_x"],
        df["MidHip_y"],
        df["Neck_x"],
        df["Neck_y"],
    )

    valid = (
        df[f"{ear}_confidence"].ge(DEFAULT_MIN_CONFIDENCE)
        & df[f"{shoulder}_confidence"].ge(DEFAULT_MIN_CONFIDENCE)
        & df["Neck_confidence"].ge(DEFAULT_MIN_CONFIDENCE)
        & df["MidHip_confidence"].ge(DEFAULT_MIN_CONFIDENCE)
    )
    df["Absolute_Head_Angle"] = head
    df["Facing_Side"] = facing_side
    if "Absolute_Trunk_Angle" not in df:
        df["Absolute_Trunk_Angle"] = trunk
    df["Absolute_Neck_Trunk_Angle"] = trunk

    relative = head - trunk
    relative = ((relative + 180) % 360) - 180
    df["Relative_Neck_Angle"] = relative
    df.loc[~valid, "Relative_Neck_Angle"] = np.nan
    df.loc[~valid, "Absolute_Head_Angle"] = np.nan
    df.loc[~valid, "Absolute_Neck_Trunk_Angle"] = np.nan

    baseline = _baseline_median(
        df["Relative_Neck_Angle"], df["Time_seconds"], neutral_seconds
    )
    deviation = df["Relative_Neck_Angle"] - baseline
    deviation = ((deviation + 180) % 360) - 180

    facing = np.sign(
        (
            df["Nose_x"]
            - df[f"{ear}_x"]
        )[df["Time_seconds"] < neutral_seconds].median()
    )
    if not np.isfinite(facing) or facing == 0:
        facing = 1.0

    df["Neck_Flexion_Signed"] = facing * deviation
    df["Neck_Flexion_Extension"] = df["Neck_Flexion_Signed"]
    df["Neck_Angle_Deg"] = df["Neck_Flexion_Signed"]
    df["Neck_Valid"] = df["Neck_Flexion_Signed"].notna()
    df["Neck_RULA_Category"] = [
        None if item is None else item["key"]
        for item in (neck_rula_category(value) for value in df["Neck_Flexion_Signed"])
    ]
    df["Neck_RULA_Posture_Score"] = [
        None if item is None else item["rula_score"]
        for item in (neck_rula_category(value) for value in df["Neck_Flexion_Signed"])
    ]
    return baseline


def add_shoulder_hiking(
    df: pd.DataFrame,
    *,
    neutral_seconds: float,
) -> tuple[float, float]:
    hip_width = np.hypot(
        df["RHip_x"] - df["LHip_x"],
        df["RHip_y"] - df["LHip_y"],
    )
    valid_scale = (
        df["RHip_confidence"].ge(DEFAULT_MIN_CONFIDENCE)
        & df["LHip_confidence"].ge(DEFAULT_MIN_CONFIDENCE)
        & (hip_width > 0)
    )

    baselines: dict[str, float] = {}
    detected_columns: list[str] = []
    for side in ("R", "L"):
        shoulder = f"{side}Shoulder"
        hip = f"{side}Hip"
        valid_side = (
            valid_scale
            & df[f"{shoulder}_confidence"].ge(DEFAULT_MIN_CONFIDENCE)
            & df[f"{hip}_confidence"].ge(DEFAULT_MIN_CONFIDENCE)
        )

        shoulder_hip_distance = np.hypot(
            df[f"{shoulder}_x"] - df[f"{hip}_x"],
            df[f"{shoulder}_y"] - df[f"{hip}_y"],
        )
        elevation_pct = shoulder_hip_distance / hip_width * 100.0
        elevation_pct = elevation_pct.where(valid_side)
        elevation_column = f"{side}_Shoulder_Elevation_Pct_Hip_Width"
        hiking_column = f"{side}_Shoulder_Hiking_Pct_Hip_Width"
        detected_column = f"{side}_Shoulder_Raised_Adjustment_Present"
        df[elevation_column] = elevation_pct

        baseline = _baseline_median(
            elevation_pct, df["Time_seconds"], neutral_seconds
        )
        baselines[side] = baseline
        hiking = elevation_pct - baseline
        df[hiking_column] = hiking
        df[detected_column] = (
            hiking >= DEFAULT_THRESHOLDS["Shoulder_Hiking"]
        ).astype("boolean")
        df.loc[hiking.isna(), detected_column] = pd.NA
        detected_columns.append(detected_column)

    baseline_r = baselines["R"]
    baseline_l = baselines["L"]

    # Preserve existing production column names while exposing the richer
    # percentage-of-hip-width research signal and classes.
    df["Right_Shoulder_Hiking_Dist"] = (
        df["R_Shoulder_Hiking_Pct_Hip_Width"] / 100.0
    )
    df["Left_Shoulder_Hiking_Dist"] = (
        df["L_Shoulder_Hiking_Pct_Hip_Width"] / 100.0
    )
    df["Shoulder_Hiking_Magnitude_Pct_Hip_Width"] = df[
        ["R_Shoulder_Hiking_Pct_Hip_Width", "L_Shoulder_Hiking_Pct_Hip_Width"]
    ].max(axis=1, skipna=True)
    df.loc[
        df[
            ["R_Shoulder_Hiking_Pct_Hip_Width", "L_Shoulder_Hiking_Pct_Hip_Width"]
        ].isna().all(axis=1),
        "Shoulder_Hiking_Magnitude_Pct_Hip_Width",
    ] = np.nan

    right = df["R_Shoulder_Raised_Adjustment_Present"] == True
    left = df["L_Shoulder_Raised_Adjustment_Present"] == True
    right_valid = df["R_Shoulder_Hiking_Pct_Hip_Width"].notna()
    left_valid = df["L_Shoulder_Hiking_Pct_Hip_Width"].notna()
    df["Shoulder_Hiking_Class"] = np.select(
        [
            right_valid & left_valid & right & left,
            right_valid & left_valid & right & ~left,
            right_valid & left_valid & ~right & left,
            right_valid & left_valid & ~right & ~left,
            right_valid & ~left_valid & right,
            right_valid & ~left_valid & ~right,
            ~right_valid & left_valid & left,
            ~right_valid & left_valid & ~left,
        ],
        [
            "Bilateral Hiking",
            "Unilateral Right Hiking",
            "Unilateral Left Hiking",
            "Neutral",
            "Unilateral Right Hiking",
            "Neutral",
            "Unilateral Left Hiking",
            "Neutral",
        ],
        default="Unknown",
    )
    df.loc[
        ~right_valid & ~left_valid,
        "Shoulder_Hiking_Class",
    ] = "Unknown"
    df["Shoulder_Valid"] = right_valid | left_valid
    df["Shoulder_Raised_Adjustment_Present"] = (
        df["R_Shoulder_Raised_Adjustment_Present"].fillna(False)
        | df["L_Shoulder_Raised_Adjustment_Present"].fillna(False)
    )
    df.loc[~df["Shoulder_Valid"], "Shoulder_Raised_Adjustment_Present"] = pd.NA

    return baseline_r, baseline_l


def compute_metrics(
    df: pd.DataFrame,
    *,
    view: str,
    neutral_seconds: float = DEFAULT_NEUTRAL_SECONDS,
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
        result.loc[result["Trunk_Flexion_Extension"].isna(), name] = pd.NA
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
        result.loc[result["Neck_Flexion_Extension"].isna(), name] = pd.NA
        available_flags.append(name)

    if {
        "Right_Shoulder_Hiking_Dist",
        "Left_Shoulder_Hiking_Dist",
    }.issubset(result.columns):
        name = "Shoulder_Hiking_Flag"
        result[name] = (
            (
                result["Right_Shoulder_Hiking_Dist"] * 100.0
                >= limits["Shoulder_Hiking"]
            )
            | (
                result["Left_Shoulder_Hiking_Dist"] * 100.0
                >= limits["Shoulder_Hiking"]
            )
        ).astype("Int64")
        invalid = (
            result["Right_Shoulder_Hiking_Dist"].isna()
            & result["Left_Shoulder_Hiking_Dist"].isna()
        )
        result.loc[invalid, name] = pd.NA
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
