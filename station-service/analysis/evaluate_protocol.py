from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


DEFAULT_CONDITIONS = [
    "Neutral",
    "Trunk_Flexion_Extension",
    "Trunk_Leaning",
    "Neck_Flexion_Extension",
    "Shoulder_Hiking",
    "Trunk_Flexion_Extension + Trunk_Leaning",
    "Trunk_Flexion_Extension + Neck_Flexion_Extension",
    "Trunk_Leaning + Shoulder_Hiking",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate the notebook's fixed 10-second experimental posture "
            "protocol against Posture_Classification in posture_metrics.csv. "
            "This is a validation tool, not production resident scoring."
        )
    )
    parser.add_argument("--metrics-csv", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--seconds-per-condition", type=float, default=10.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(args.metrics_csv)
    if "frame" not in df or "Posture_Classification" not in df:
        raise ValueError(
            "metrics CSV must contain frame and Posture_Classification."
        )

    frames_per_condition = int(round(args.fps * args.seconds_per_condition))
    if frames_per_condition <= 0:
        raise ValueError("seconds-per-condition must produce at least one frame.")

    def actual(frame: int) -> str:
        index = int(frame) // frames_per_condition
        if index < len(DEFAULT_CONDITIONS):
            return DEFAULT_CONDITIONS[index]
        return "Outside_Protocol"

    df["Actual_Classification"] = df["frame"].apply(actual)
    comparison = df[
        df["Actual_Classification"].isin(DEFAULT_CONDITIONS)
    ].copy()

    comparison["Predicted_Classification"] = comparison[
        "Posture_Classification"
    ].apply(
        lambda value: (
            value if value in DEFAULT_CONDITIONS else "Other"
        )
    )

    labels = DEFAULT_CONDITIONS + ["Other"]
    matrix = pd.crosstab(
        comparison["Actual_Classification"],
        comparison["Predicted_Classification"],
        dropna=False,
    ).reindex(index=labels, columns=labels, fill_value=0)

    matrix.to_csv(output / "confusion_matrix.csv")

    total = int(matrix.to_numpy().sum())
    correct = int(np.trace(matrix.to_numpy()))
    accuracy = (correct / total * 100) if total else None

    with (output / "protocol_summary.json").open(
        "w", encoding="utf-8"
    ) as handle:
        json.dump(
            {
                "overall_accuracy_pct": accuracy,
                "evaluated_frames": total,
                "seconds_per_condition": args.seconds_per_condition,
                "conditions": DEFAULT_CONDITIONS,
            },
            handle,
            indent=2,
        )
        handle.write("\n")

    fig, ax = plt.subplots(figsize=(14, 12))
    image = ax.imshow(matrix.to_numpy(), aspect="auto")
    fig.colorbar(image, ax=ax)

    ax.set_xticks(range(len(labels)), labels, rotation=45, ha="left")
    ax.set_yticks(range(len(labels)), labels)
    ax.xaxis.tick_top()
    ax.xaxis.set_label_position("top")
    ax.set_xlabel("Predicted Classification")
    ax.set_ylabel("Actual Classification")
    ax.set_title("OpenPose Posture Classification Confusion Matrix", pad=40)

    for row in range(len(labels)):
        for col in range(len(labels)):
            ax.text(
                col,
                row,
                str(int(matrix.iloc[row, col])),
                ha="center",
                va="center",
            )

    fig.tight_layout()
    fig.savefig(output / "confusion_matrix.png", dpi=150)
    plt.close(fig)

    print(f"Evaluated frames: {total}")
    if accuracy is not None:
        print(f"Overall classification accuracy: {accuracy:.2f}%")
    print(f"Outputs: {output}")


if __name__ == "__main__":
    main()
