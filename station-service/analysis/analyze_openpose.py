from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

if __package__:
    from .openpose_io import DEFAULT_MIN_CONFIDENCE, load_openpose_json_dir, torso_confidence_summary
    from .posture_metrics import DEFAULT_NEUTRAL_SECONDS, DEFAULT_THRESHOLDS, UPRIGHT_TOLERANCE_DEG, classify_frames, compute_metrics
else:
    from openpose_io import DEFAULT_MIN_CONFIDENCE, load_openpose_json_dir, torso_confidence_summary
    from posture_metrics import DEFAULT_NEUTRAL_SECONDS, DEFAULT_THRESHOLDS, UPRIGHT_TOLERANCE_DEG, classify_frames, compute_metrics


DEFAULT_FPS = 30.0


def _metric_stats(
    series: pd.Series,
    *,
    threshold: float,
    absolute: bool,
) -> dict[str, float | int | None]:
    values = pd.to_numeric(series, errors="coerce")
    valid = values.dropna()

    if valid.empty:
        return {
            "valid_frames": 0,
            "mean": None,
            "median": None,
            "minimum": None,
            "maximum": None,
            "std": None,
            "frames_over_threshold": 0,
            "pct_valid_frames_over_threshold": None,
        }

    comparison = valid.abs() if absolute else valid
    over = comparison >= threshold

    return {
        "valid_frames": int(valid.size),
        "mean": float(valid.mean()),
        "median": float(valid.median()),
        "minimum": float(valid.min()),
        "maximum": float(valid.max()),
        "std": float(valid.std()) if valid.size > 1 else 0.0,
        "frames_over_threshold": int(over.sum()),
        "pct_valid_frames_over_threshold": float(over.mean() * 100),
    }


def build_summary(
    df: pd.DataFrame,
    *,
    view: str,
    baselines: dict,
    thresholds: dict[str, float],
    neutral_seconds: float,
    total_session_seconds: float | None = None,
) -> dict:
    summary: dict = {
        "view": view,
        "total_json_frames": int(len(df)),
        "neutral_seconds": neutral_seconds,
        "baselines": baselines,
        "thresholds": thresholds,
        "categorization_tolerances": {
            "trunk_rula_upright_degrees": {
                "value": UPRIGHT_TOLERANCE_DEG,
                "description": (
                    "Project-specific automation tolerance around zero; "
                    "not a RULA-defined angular boundary."
                ),
            },
        },
        "metrics": {},
    }

    specs = [
        (
            "Trunk_Flexion_Extension",
            thresholds["Trunk_Flexion_Extension"],
            True,
        ),
        (
            "Trunk_Lean",
            thresholds["Trunk_Leaning"],
            True,
        ),
        (
            "Neck_Flexion_Extension",
            thresholds["Neck_Flexion_Extension"],
            True,
        ),
        (
            "Right_Shoulder_Hiking_Dist",
            thresholds["Shoulder_Hiking"],
            False,
        ),
        (
            "Left_Shoulder_Hiking_Dist",
            thresholds["Shoulder_Hiking"],
            False,
        ),
    ]

    for column, threshold, absolute in specs:
        if column in df:
            metric_threshold = threshold / 100.0 if column in {
                "Right_Shoulder_Hiking_Dist",
                "Left_Shoulder_Hiking_Dist",
            } else threshold
            summary["metrics"][column] = _metric_stats(
                df[column],
                threshold=metric_threshold,
                absolute=absolute,
            )

    category_specs = [
        ("neck", "Neck_RULA_Category", "neck_rula_category"),
        ("forward_trunk", "Trunk_RULA_Category", "trunk_rula_category"),
        ("lateral_trunk", "Trunk_Sidebend_Adjustment_Present", "lateral_adjustment"),
        ("shoulder", "Shoulder_Hiking_Class", "shoulder_class"),
    ]
    category_scores = {
        "flexion_0_10": 1,
        "flexion_10_20": 2,
        "flexion_over_20": 3,
        "extension": 4,
        "upright": 1,
        "flexion_0_20": 2,
        "flexion_20_60": 3,
        "flexion_over_60": 4,
    }
    category_labels = {
        "flexion_0_10": "0-10 degrees flexion",
        "flexion_10_20": "10-20 degrees flexion",
        "flexion_over_20": "Over 20 degrees flexion",
        "extension": "Extension",
        "upright": "Approximately upright",
        "flexion_0_20": "0-20 degrees flexion",
        "flexion_20_60": "20-60 degrees flexion",
        "flexion_over_60": "Over 60 degrees flexion",
        "True": "Trunk side-bending adjustment present",
        "False": "No trunk side-bending adjustment",
    }
    summary["category_distributions"] = {}
    for metric_name, category_column, _kind in category_specs:
        if category_column not in df:
            continue
        times = pd.to_numeric(df["Time_seconds"], errors="coerce")
        intervals = times.shift(-1) - times
        positive_intervals = intervals[intervals.gt(0)]
        cadence = (
            float(positive_intervals.median())
            if not positive_intervals.empty
            else 1.0 / DEFAULT_FPS
        )
        if total_session_seconds is not None and len(times):
            final_interval = max(
                0.0, total_session_seconds - float(times.iloc[-1])
            )
        else:
            final_interval = cadence
        intervals = intervals.fillna(final_interval)
        intervals = intervals.where(intervals.gt(0), cadence)
        if total_session_seconds is not None:
            intervals = pd.Series(
                [
                    min(float(interval), max(0.0, total_session_seconds - float(time)))
                    if pd.notna(time)
                    else 0.0
                    for time, interval in zip(times, intervals)
                ],
                index=df.index,
            )

        seconds_by_category: dict[str, float] = {}
        for category, interval in zip(df[category_column], intervals):
            if pd.isna(category):
                continue
            key = str(category)
            if key.lower() in {"", "nan", "none", "unknown"}:
                continue
            seconds_by_category[key] = seconds_by_category.get(key, 0.0) + float(max(0.0, interval))

        valid_seconds = sum(seconds_by_category.values())
        total_seconds = (
            total_session_seconds
            if total_session_seconds is not None and total_session_seconds > 0
            else float(intervals.clip(lower=0).sum())
        )
        summary["category_distributions"][metric_name] = {
            "valid_tracking_seconds": round(valid_seconds, 3),
            "valid_tracking_percent": (
                round(min(100.0, valid_seconds / total_seconds * 100.0), 2)
                if total_seconds > 0
                else None
            ),
            "categories": [
                {
                    "key": key,
                    "label": category_labels.get(key, key),
                    "rula_score": category_scores.get(key),
                    "seconds": round(seconds, 3),
                    "percent_of_valid_time": (
                        round(seconds / valid_seconds * 100.0, 2)
                        if valid_seconds > 0
                        else None
                    ),
                }
                for key, seconds in sorted(seconds_by_category.items())
            ],
        }

    if "Posture_Classification" in df:
        counts = df["Posture_Classification"].value_counts(dropna=False)
        summary["posture_classification_counts"] = {
            str(name): int(count)
            for name, count in counts.items()
        }

    return summary


def save_line_plot(
    df: pd.DataFrame,
    *,
    x: str,
    ys: list[tuple[str, str]],
    title: str,
    ylabel: str,
    output: Path,
    thresholds: list[float] | None = None,
) -> None:
    fig, ax = plt.subplots(figsize=(16, 6))

    for column, label in ys:
        ax.plot(df[x], df[column], linewidth=1.2, label=label)

    ax.axhline(0, linestyle="--", linewidth=1.2, label="Neutral")

    for threshold in thresholds or []:
        ax.axhline(threshold, linestyle=":", linewidth=1)
        if threshold != 0:
            ax.axhline(-threshold, linestyle=":", linewidth=1)

    ax.set_title(title)
    ax.set_xlabel("Time (seconds)")
    ax.set_ylabel(ylabel)
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output, dpi=150)
    plt.close(fig)


def save_confidence_plot(
    df: pd.DataFrame,
    output: Path,
) -> None:
    joints = [
        "Nose",
        "Neck",
        "RShoulder",
        "LShoulder",
        "MidHip",
        "RHip",
        "LHip",
    ]

    values = []
    labels = []
    for joint in joints:
        column = f"{joint}_confidence"
        if column not in df:
            continue
        clean = pd.to_numeric(df[column], errors="coerce").dropna()
        if clean.empty:
            continue
        values.append(clean.to_numpy())
        labels.append(joint)

    if not values:
        return

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.boxplot(values, tick_labels=labels)
    ax.set_title("OpenPose Confidence Scores for Torso Joints")
    ax.set_xlabel("Torso Joint")
    ax.set_ylabel("Confidence Score")
    ax.set_ylim(0, 1)
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    fig.savefig(output, dpi=150)
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze BODY_25 OpenPose JSON using the notebook-derived "
            "ophthalmology posture heuristics."
        )
    )
    parser.add_argument("--json-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--view",
        required=True,
        choices=["side", "rear", "all"],
        help=(
            "side = trunk flex/ext + neck flex/ext; "
            "rear = lateral lean + shoulder hiking; "
            "all = reproduce all notebook metrics."
        ),
    )
    parser.add_argument("--fps", type=float, default=DEFAULT_FPS)
    parser.add_argument("--neutral-seconds", type=float, default=DEFAULT_NEUTRAL_SECONDS)
    parser.add_argument("--timestamps-csv")
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=DEFAULT_MIN_CONFIDENCE,
        help=(
            "Mask x/y coordinates when OpenPose confidence is at or below "
            "this value. Default 0 only masks missing keypoints."
        ),
    )
    parser.add_argument(
        "--shoulder-threshold",
        type=float,
        default=DEFAULT_THRESHOLDS["Shoulder_Hiking"],
    )
    parser.add_argument(
        "--neck-threshold",
        type=float,
        default=DEFAULT_THRESHOLDS["Neck_Flexion_Extension"],
    )
    parser.add_argument(
        "--trunk-lean-threshold",
        type=float,
        default=DEFAULT_THRESHOLDS["Trunk_Leaning"],
    )
    parser.add_argument(
        "--trunk-flex-threshold",
        type=float,
        default=DEFAULT_THRESHOLDS["Trunk_Flexion_Extension"],
    )
    return parser.parse_args()


def analyze_openpose(
    json_dir: str | Path,
    output_dir: str | Path,
    *,
    view: str,
    fps: float = DEFAULT_FPS,
    neutral_seconds: float = DEFAULT_NEUTRAL_SECONDS,
    timestamps_csv: str | Path | None = None,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    thresholds: dict[str, float] | None = None,
    total_session_seconds: float | None = None,
) -> dict:
    """Analyze existing BODY_25 frames and write CSV, summary, and plots."""
    output = Path(output_dir)
    plots = output / "plots"
    output.mkdir(parents=True, exist_ok=True)
    plots.mkdir(parents=True, exist_ok=True)

    thresholds = dict(DEFAULT_THRESHOLDS) if thresholds is None else dict(thresholds)

    df = load_openpose_json_dir(
        json_dir,
        fps=fps,
        timestamps_csv=timestamps_csv,
        min_confidence=min_confidence,
    )

    metrics, baselines = compute_metrics(
        df,
        view=view,
        neutral_seconds=neutral_seconds,
    )
    metrics = classify_frames(metrics, thresholds=thresholds)

    metrics.to_csv(output / "posture_metrics.csv", index=False)

    confidence = torso_confidence_summary(metrics)
    confidence.to_csv(output / "confidence_summary.csv", index=False)

    summary = build_summary(
        metrics,
        view=view,
        baselines=baselines.to_dict(),
        thresholds=thresholds,
        neutral_seconds=neutral_seconds,
        total_session_seconds=total_session_seconds,
    )
    with (output / "summary.json").open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, allow_nan=False)
        handle.write("\n")

    save_confidence_plot(
        metrics,
        plots / "torso_confidence.png",
    )

    if "Trunk_Flexion_Extension" in metrics:
        save_line_plot(
            metrics,
            x="Time_seconds",
            ys=[
                (
                    "Trunk_Flexion_Extension",
                    "Trunk Flexion/Extension",
                )
            ],
            title="Trunk Flexion / Extension Throughout Video",
            ylabel="Trunk Angle Deviation (degrees)",
            output=plots / "trunk_flexion_extension.png",
            thresholds=[thresholds["Trunk_Flexion_Extension"]],
        )

    if "Neck_Flexion_Extension" in metrics:
        save_line_plot(
            metrics,
            x="Time_seconds",
            ys=[
                (
                    "Neck_Flexion_Extension",
                    "Neck Flexion/Extension",
                )
            ],
            title="Neck Flexion / Extension Throughout Video",
            ylabel="Neck Angle Deviation (degrees)",
            output=plots / "neck_flexion_extension.png",
            thresholds=[thresholds["Neck_Flexion_Extension"]],
        )

    if "Trunk_Lean" in metrics:
        save_line_plot(
            metrics,
            x="Time_seconds",
            ys=[("Trunk_Lean", "Trunk Lateral Lean")],
            title="Trunk Lateral Lean Throughout Video",
            ylabel="Lateral Lean Angle (degrees)",
            output=plots / "trunk_lateral_lean.png",
            thresholds=[thresholds["Trunk_Leaning"]],
        )

    if {
        "Right_Shoulder_Hiking_Dist",
        "Left_Shoulder_Hiking_Dist",
    }.issubset(metrics.columns):
        shoulder_plot = metrics.copy()
        shoulder_plot["Right_Shoulder_Hiking_Pct"] = (
            shoulder_plot["Right_Shoulder_Hiking_Dist"] * 100
        )
        shoulder_plot["Left_Shoulder_Hiking_Pct"] = (
            shoulder_plot["Left_Shoulder_Hiking_Dist"] * 100
        )
        save_line_plot(
            shoulder_plot,
            x="Time_seconds",
            ys=[
                ("Right_Shoulder_Hiking_Pct", "Right Shoulder"),
                ("Left_Shoulder_Hiking_Pct", "Left Shoulder"),
            ],
            title="Shoulder Hiking Throughout Video",
            ylabel="Shoulder Elevation (% of Trunk Length)",
            output=plots / "shoulder_hiking.png",
            thresholds=[thresholds["Shoulder_Hiking"] * 100],
        )

    return summary


def main() -> None:
    args = parse_args()
    output = Path(args.output_dir)
    analyze_openpose(
        args.json_dir,
        output,
        view=args.view,
        fps=args.fps,
        neutral_seconds=args.neutral_seconds,
        timestamps_csv=args.timestamps_csv,
        min_confidence=args.min_confidence,
        thresholds={
            "Shoulder_Hiking": args.shoulder_threshold,
            "Neck_Flexion_Extension": args.neck_threshold,
            "Trunk_Leaning": args.trunk_lean_threshold,
            "Trunk_Flexion_Extension": args.trunk_flex_threshold,
        },
    )
    plots = output / "plots"
    print(f"Analysis complete: {output}")
    print(f"Metrics CSV: {output / 'posture_metrics.csv'}")
    print(f"Summary JSON: {output / 'summary.json'}")
    print(f"Plots: {plots}")


if __name__ == "__main__":
    main()
