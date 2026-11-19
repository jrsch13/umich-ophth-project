from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from openpose_io import load_openpose_json_dir, torso_confidence_summary
from posture_metrics import (
    DEFAULT_THRESHOLDS,
    classify_frames,
    compute_metrics,
)


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
) -> dict:
    summary: dict = {
        "view": view,
        "total_json_frames": int(len(df)),
        "neutral_seconds": neutral_seconds,
        "baselines": baselines,
        "thresholds": thresholds,
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
            summary["metrics"][column] = _metric_stats(
                df[column],
                threshold=threshold,
                absolute=absolute,
            )

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
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--neutral-seconds", type=float, default=10.0)
    parser.add_argument("--timestamps-csv")
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.0,
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


def main() -> None:
    args = parse_args()
    output = Path(args.output_dir)
    plots = output / "plots"
    output.mkdir(parents=True, exist_ok=True)
    plots.mkdir(parents=True, exist_ok=True)

    thresholds = {
        "Shoulder_Hiking": args.shoulder_threshold,
        "Neck_Flexion_Extension": args.neck_threshold,
        "Trunk_Leaning": args.trunk_lean_threshold,
        "Trunk_Flexion_Extension": args.trunk_flex_threshold,
    }

    df = load_openpose_json_dir(
        args.json_dir,
        fps=args.fps,
        timestamps_csv=args.timestamps_csv,
        min_confidence=args.min_confidence,
    )

    metrics, baselines = compute_metrics(
        df,
        view=args.view,
        neutral_seconds=args.neutral_seconds,
    )
    metrics = classify_frames(metrics, thresholds=thresholds)

    metrics.to_csv(output / "posture_metrics.csv", index=False)

    confidence = torso_confidence_summary(metrics)
    confidence.to_csv(output / "confidence_summary.csv", index=False)

    summary = build_summary(
        metrics,
        view=args.view,
        baselines=baselines.to_dict(),
        thresholds=thresholds,
        neutral_seconds=args.neutral_seconds,
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

    print(f"Analysis complete: {output}")
    print(f"Metrics CSV: {output / 'posture_metrics.csv'}")
    print(f"Summary JSON: {output / 'summary.json'}")
    print(f"Plots: {plots}")


if __name__ == "__main__":
    main()
