"""
evaluate_pipeline_v1.py

Quality-check an Anipose / DeepLabCut 2D pipeline and evaluate simple
2D heuristic proxies for:
  1) shoulder hiking
  2) neck extension

The heuristic calculations deliberately use the RAW DLC detections plus
confidence-based masking and short-gap linear interpolation. This avoids
blindly trusting an Anipose filtered file if spline interpolation produces
implausible coordinates.

Run from anipose-pipeline-v1 in powershell:
python .\scripts\evaluate_pipeline_v1.py `
    --video ".\sample01\videos-raw\side_profile_test.MOV" `
    --raw ".\sample01\pose-2d\side_profile_test.h5" `
    --filtered ".\sample01\pose-2d-filtered\side_profile_test.h5" `
    --baseline-start 45 `
    --baseline-end 50 `
    --shoulder shoulder1 `
    --hip hip1 `
    --chin chin

Choose a baseline interval in which the subject is genuinely in a neutral
reference posture. If neck-extension direction is reversed relative to the
video, rerun with --neck-sign -1.

These are research heuristics/proxies, not validated clinical measurements.
"""

from __future__ import annotations
import argparse
from pathlib import Path
import sys
import cv2
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="QC a 2D Anipose/DLC pipeline and test ergonomic heuristics."
    )
    p.add_argument("--video", required=True, help="Original video file")
    p.add_argument("--raw", required=True, help="Raw DLC/Anipose pose-2d .h5")
    p.add_argument(
        "--filtered",
        default=None,
        help="Optional Anipose pose-2d-filtered .h5 for QC comparison",
    )
    p.add_argument("--shoulder", default="shoulder1")
    p.add_argument("--hip", default="hip1")
    p.add_argument("--chin", default="chin")
    p.add_argument(
        "--confidence",
        type=float,
        default=0.80,
        help="Likelihood threshold for heuristic input (default 0.80)",
    )
    p.add_argument(
        "--max-gap",
        type=int,
        default=5,
        help="Maximum missing run (frames) to linearly interpolate (default 5)",
    )
    p.add_argument(
        "--baseline-start",
        type=float,
        required=True,
        help="Neutral/reference interval start time in seconds",
    )
    p.add_argument(
        "--baseline-end",
        type=float,
        required=True,
        help="Neutral/reference interval end time in seconds",
    )
    p.add_argument(
        "--action-start",
        type=float,
        default=None,
        help="Optional known action interval start time in seconds",
    )
    p.add_argument(
        "--action-end",
        type=float,
        default=None,
        help="Optional known action interval end time in seconds",
    )
    p.add_argument(
        "--neck-sign",
        type=float,
        choices=[-1.0, 1.0],
        default=1.0,
        help="Flip sign if positive values correspond to flexion, not extension",
    )
    p.add_argument(
        "--outdir",
        default="pipeline_test_results",
        help="Output directory (default pipeline_test_results)",
    )
    return p.parse_args()


def read_pose(path: Path) -> pd.DataFrame:
    df = pd.read_hdf(path)
    if not isinstance(df.columns, pd.MultiIndex):
        raise ValueError(f"{path} does not have DLC-style MultiIndex columns.")
    required_levels = {"scorer", "bodyparts", "coords"}
    if not required_levels.issubset(set(df.columns.names)):
        raise ValueError(
            f"{path} column levels are {df.columns.names}; expected "
            "scorer/bodyparts/coords."
        )
    return df

def bodyparts(df: pd.DataFrame) -> list[str]:
    return list(pd.Index(df.columns.get_level_values("bodyparts")).unique())

def scorer_name(df: pd.DataFrame) -> str:
    scorers = list(pd.Index(df.columns.get_level_values("scorer")).unique())
    if len(scorers) != 1:
        raise ValueError(f"Expected one scorer; found {scorers}")
    return scorers[0]

def get_point(df: pd.DataFrame, name: str) -> pd.DataFrame:
    if name not in bodyparts(df):
        raise KeyError(
            f"Bodypart '{name}' not found. Available: {', '.join(bodyparts(df))}"
        )
    scorer = scorer_name(df)
    return pd.DataFrame(
        {
            "x": df[(scorer, name, "x")].astype(float),
            "y": df[(scorer, name, "y")].astype(float),
            "likelihood": df[(scorer, name, "likelihood")].astype(float),
        }
    )

def get_video_info(video_path: Path) -> dict:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"OpenCV could not open video: {video_path}")
    info = {
        "frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        "fps": float(cap.get(cv2.CAP_PROP_FPS)),
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
    }
    cap.release()
    if info["fps"] <= 0:
        raise RuntimeError("Video FPS is zero/invalid.")
    return info

def qc_table(
    df: pd.DataFrame,
    width: int,
    height: int,
    confidence_threshold: float,
    source: str,
) -> pd.DataFrame:
    rows = []
    n = len(df)
    for bp in bodyparts(df):
        pt = get_point(df, bp)
        finite = np.isfinite(pt["x"]) & np.isfinite(pt["y"])
        in_bounds = (
            finite
            & pt["x"].between(0, width - 1)
            & pt["y"].between(0, height - 1)
        )
        rows.append(
            {
                "source": source,
                "bodypart": bp,
                "frames": n,
                "median_likelihood": float(pt["likelihood"].median()),
                "pct_below_conf": 100.0
                * float((pt["likelihood"] < confidence_threshold).mean()),
                "pct_nan_xy": 100.0 * float((~finite).mean()),
                "pct_out_of_bounds_xy": 100.0
                * float((finite & ~in_bounds).mean()),
            }
        )
    return pd.DataFrame(rows)

def interpolate_short_gaps(s: pd.Series, max_gap: int) -> pd.Series:
    """Linearly fill only whole interior NaN runs of length <= max_gap."""
    s = s.astype(float).copy()
    interp = s.interpolate(method="linear", limit_area="inside")
    missing = s.isna()

    if not missing.any():
        return s

    group_id = (missing != missing.shift(fill_value=False)).cumsum()

    for _, idx in missing.groupby(group_id).groups.items():
        idx = list(idx)
        if not missing.loc[idx[0]]:
            continue
        if len(idx) > max_gap:
            continue

        first = idx[0]
        last = idx[-1]
        if first == s.index[0] or last == s.index[-1]:
            continue

        # Require valid data on both sides.
        pos_first = s.index.get_loc(first)
        pos_last = s.index.get_loc(last)
        left_pos = pos_first - 1
        right_pos = pos_last + 1
        if left_pos < 0 or right_pos >= len(s):
            continue
        if pd.isna(s.iloc[left_pos]) or pd.isna(s.iloc[right_pos]):
            continue

        s.loc[idx] = interp.loc[idx]

    return s

def clean_point(
    df: pd.DataFrame,
    name: str,
    width: int,
    height: int,
    confidence_threshold: float,
    max_gap: int,
) -> pd.DataFrame:
    pt = get_point(df, name)
    good = (
        (pt["likelihood"] >= confidence_threshold)
        & pt["x"].between(0, width - 1)
        & pt["y"].between(0, height - 1)
        & np.isfinite(pt["x"])
        & np.isfinite(pt["y"])
    )

    out = pt.copy()
    out.loc[~good, ["x", "y"]] = np.nan
    out["x"] = interpolate_short_gaps(out["x"], max_gap)
    out["y"] = interpolate_short_gaps(out["y"], max_gap)
    out["originally_confident"] = good
    return out

def time_mask(times: np.ndarray, start: float, end: float) -> np.ndarray:
    if end <= start:
        raise ValueError("Interval end must be greater than start.")
    return (times >= start) & (times <= end)

def shoulder_hike_proxy(
    shoulder: pd.DataFrame,
    hip: pd.DataFrame,
    baseline_mask: np.ndarray,
) -> tuple[pd.Series, pd.Series]:
    """
    Shoulder-hike proxy:
      project the hip->shoulder vector onto the NEUTRAL torso-up axis.
      Positive change means the shoulder moved farther "up" that baseline axis.

    Returns:
      hike_pixels, hike_percent_of_baseline_torso_length
    """
    valid_baseline = (
        baseline_mask
        & shoulder["x"].notna().to_numpy()
        & shoulder["y"].notna().to_numpy()
        & hip["x"].notna().to_numpy()
        & hip["y"].notna().to_numpy()
    )
    if valid_baseline.sum() < 5:
        raise RuntimeError(
            "Too few valid frames in baseline interval for shoulder heuristic. "
            "Choose a better baseline interval or lower confidence threshold cautiously."
        )

    vx0 = (
        shoulder.loc[valid_baseline, "x"].to_numpy()
        - hip.loc[valid_baseline, "x"].to_numpy()
    )
    # Convert image coordinates to Cartesian-style y-up coordinates.
    vy0 = -(
        shoulder.loc[valid_baseline, "y"].to_numpy()
        - hip.loc[valid_baseline, "y"].to_numpy()
    )

    baseline_vec = np.array([np.nanmedian(vx0), np.nanmedian(vy0)], dtype=float)
    baseline_len = float(np.linalg.norm(baseline_vec))
    if baseline_len <= 1e-9:
        raise RuntimeError("Baseline torso vector has near-zero length.")

    up_axis = baseline_vec / baseline_len

    vx = shoulder["x"] - hip["x"]
    vy = -(shoulder["y"] - hip["y"])

    projected = vx * up_axis[0] + vy * up_axis[1]
    baseline_projected = float(np.nanmedian(projected.to_numpy()[baseline_mask]))

    hike_px = projected - baseline_projected
    hike_pct = 100.0 * hike_px / baseline_len
    return hike_px, hike_pct


def signed_angle_deg(ax, ay, bx, by) -> np.ndarray:
    cross = ax * by - ay * bx
    dot = ax * bx + ay * by
    return np.degrees(np.arctan2(cross, dot))

def neck_extension_proxy(
    shoulder: pd.DataFrame,
    hip: pd.DataFrame,
    chin: pd.DataFrame,
    baseline_mask: np.ndarray,
    neck_sign: float,
) -> pd.Series:
    """
    Neck-extension proxy:
      signed 2D angle between torso vector (hip -> shoulder)
      and neck vector (shoulder -> chin), baseline-subtracted.

    This is a SIDE-VIEW proxy, not a validated anatomical neck angle.
    """
    tx = shoulder["x"] - hip["x"]
    ty = -(shoulder["y"] - hip["y"])

    nx = chin["x"] - shoulder["x"]
    ny = -(chin["y"] - shoulder["y"])

    angle = pd.Series(
        signed_angle_deg(tx.to_numpy(), ty.to_numpy(), nx.to_numpy(), ny.to_numpy()),
        index=shoulder.index,
        dtype=float,
    )

    baseline_vals = angle.to_numpy()[baseline_mask]
    baseline_vals = baseline_vals[np.isfinite(baseline_vals)]
    if len(baseline_vals) < 5:
        raise RuntimeError(
            "Too few valid frames in baseline interval for neck heuristic."
        )

    baseline_angle = float(np.nanmedian(baseline_vals))
    # Circular difference in [-180, 180].
    delta = ((angle - baseline_angle + 180.0) % 360.0) - 180.0
    return neck_sign * delta

def interval_stats(series: pd.Series, mask: np.ndarray, label: str) -> dict:
    vals = series.to_numpy()[mask]
    vals = vals[np.isfinite(vals)]
    if len(vals) == 0:
        return {
            "interval": label,
            "n_valid": 0,
            "median": np.nan,
            "mean": np.nan,
            "p95": np.nan,
            "max": np.nan,
            "min": np.nan,
        }
    return {
        "interval": label,
        "n_valid": len(vals),
        "median": float(np.nanmedian(vals)),
        "mean": float(np.nanmean(vals)),
        "p95": float(np.nanpercentile(vals, 95)),
        "max": float(np.nanmax(vals)),
        "min": float(np.nanmin(vals)),
    }

def save_plot(
    times: np.ndarray,
    values: pd.Series,
    ylabel: str,
    title: str,
    outpath: Path,
    baseline_start: float,
    baseline_end: float,
    action_start: float | None,
    action_end: float | None,
) -> None:
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(times, values.to_numpy())
    ax.axvspan(baseline_start, baseline_end, alpha=0.15, label="baseline")
    if action_start is not None and action_end is not None:
        ax.axvspan(action_start, action_end, alpha=0.15, label="known action")
    ax.axhline(0, linewidth=1)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend()
    fig.tight_layout()
    fig.savefig(outpath, dpi=150)
    plt.close(fig)

def main() -> int:
    args = parse_args()

    video_path = Path(args.video)
    raw_path = Path(args.raw)
    filtered_path = Path(args.filtered) if args.filtered else None
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    info = get_video_info(video_path)
    raw = read_pose(raw_path)

    print("\n=== VIDEO ===")
    print(
        f"{video_path}\n"
        f"{info['width']}x{info['height']}, {info['fps']:.3f} fps, "
        f"{info['frames']} frames"
    )

    print("\n=== RAW POSE ===")
    print(f"{raw_path}\n{len(raw)} rows, {len(bodyparts(raw))} bodyparts")
    print("Bodyparts:", ", ".join(bodyparts(raw)))

    # Pipeline integrity checks.
    frame_delta = len(raw) - info["frames"]
    print("\n=== PIPELINE INTEGRITY ===")
    print(f"Video frames: {info['frames']}")
    print(f"Raw H5 rows: {len(raw)}")
    print(f"Frame-count difference: {frame_delta:+d}")

    required = [args.shoulder, args.hip, args.chin]
    missing = [bp for bp in required if bp not in bodyparts(raw)]
    if missing:
        raise KeyError(f"Required bodyparts missing from raw pose: {missing}")
    print("Required landmarks present: PASS")

    qc_frames = [
        qc_table(
            raw,
            info["width"],
            info["height"],
            args.confidence,
            source="raw",
        )
    ]

    if filtered_path is not None:
        filtered = read_pose(filtered_path)
        qc_frames.append(
            qc_table(
                filtered,
                info["width"],
                info["height"],
                args.confidence,
                source="filtered",
            )
        )
        print(f"Filtered H5 rows: {len(filtered)}")

    qc = pd.concat(qc_frames, ignore_index=True)
    qc.to_csv(outdir / "pipeline_qc.csv", index=False)

    focus = qc[qc["bodypart"].isin(required)].copy()
    print("\n=== QC FOR HEURISTIC LANDMARKS ===")
    print(
        focus[
            [
                "source",
                "bodypart",
                "median_likelihood",
                "pct_below_conf",
                "pct_nan_xy",
                "pct_out_of_bounds_xy",
            ]
        ].to_string(index=False, float_format=lambda x: f"{x:7.2f}")
    )

    if filtered_path is not None:
        bad_filtered = focus[
            (focus["source"] == "filtered")
            & (focus["pct_out_of_bounds_xy"] > 0)
        ]
        if len(bad_filtered):
            print(
                "\nWARNING: filtered file contains out-of-bounds coordinates for "
                "one or more heuristic landmarks. The heuristics below use RAW "
                "detections plus conservative cleaning instead."
            )

    # Conservative raw-coordinate cleaning.
    shoulder = clean_point(
        raw,
        args.shoulder,
        info["width"],
        info["height"],
        args.confidence,
        args.max_gap,
    )
    hip = clean_point(
        raw,
        args.hip,
        info["width"],
        info["height"],
        args.confidence,
        args.max_gap,
    )
    chin = clean_point(
        raw,
        args.chin,
        info["width"],
        info["height"],
        args.confidence,
        args.max_gap,
    )

    n = len(raw)
    times = np.arange(n, dtype=float) / info["fps"]
    baseline_mask = time_mask(times, args.baseline_start, args.baseline_end)

    shoulder_px, shoulder_pct = shoulder_hike_proxy(
        shoulder, hip, baseline_mask
    )
    neck_deg = neck_extension_proxy(
        shoulder, hip, chin, baseline_mask, args.neck_sign
    )

    all_needed_shoulder = (
        shoulder["x"].notna()
        & shoulder["y"].notna()
        & hip["x"].notna()
        & hip["y"].notna()
    )
    all_needed_neck = (
        all_needed_shoulder
        & chin["x"].notna()
        & chin["y"].notna()
    )

    print("\n=== HEURISTIC COVERAGE ===")
    print(
        f"Shoulder-hike proxy usable frames: "
        f"{100 * all_needed_shoulder.mean():.1f}%"
    )
    print(
        f"Neck-extension proxy usable frames: "
        f"{100 * all_needed_neck.mean():.1f}%"
    )

    out = pd.DataFrame(
        {
            "frame": np.arange(n),
            "time_s": times,
            f"{args.shoulder}_x_clean": shoulder["x"],
            f"{args.shoulder}_y_clean": shoulder["y"],
            f"{args.hip}_x_clean": hip["x"],
            f"{args.hip}_y_clean": hip["y"],
            f"{args.chin}_x_clean": chin["x"],
            f"{args.chin}_y_clean": chin["y"],
            "shoulder_hike_proxy_px": shoulder_px,
            "shoulder_hike_proxy_pct_torso": shoulder_pct,
            "neck_extension_proxy_deg": neck_deg,
        }
    )
    out.to_csv(outdir / "heuristics_timeseries.csv", index=False)

    save_plot(
        times,
        shoulder_pct,
        "Shoulder hike (% of baseline torso length)",
        "2D shoulder-hiking heuristic",
        outdir / "shoulder_hike_proxy.png",
        args.baseline_start,
        args.baseline_end,
        args.action_start,
        args.action_end,
    )
    save_plot(
        times,
        neck_deg,
        "Baseline-relative angle (deg)",
        "2D neck-extension heuristic",
        outdir / "neck_extension_proxy.png",
        args.baseline_start,
        args.baseline_end,
        args.action_start,
        args.action_end,
    )

    stats = []
    stats.append(
        {
            "metric": "shoulder_hike_proxy_pct_torso",
            **interval_stats(shoulder_pct, baseline_mask, "baseline"),
        }
    )
    stats.append(
        {
            "metric": "neck_extension_proxy_deg",
            **interval_stats(neck_deg, baseline_mask, "baseline"),
        }
    )

    if args.action_start is not None or args.action_end is not None:
        if args.action_start is None or args.action_end is None:
            raise ValueError(
                "Provide both --action-start and --action-end, or neither."
            )
        action_mask = time_mask(times, args.action_start, args.action_end)
        stats.append(
            {
                "metric": "shoulder_hike_proxy_pct_torso",
                **interval_stats(shoulder_pct, action_mask, "known_action"),
            }
        )
        stats.append(
            {
                "metric": "neck_extension_proxy_deg",
                **interval_stats(neck_deg, action_mask, "known_action"),
            }
        )

    stats_df = pd.DataFrame(stats)
    stats_df.to_csv(outdir / "interval_stats.csv", index=False)

    print("\n=== INTERVAL STATS ===")
    print(stats_df.to_string(index=False, float_format=lambda x: f"{x:8.3f}"))

    print("\n=== OUTPUTS ===")
    for name in [
        "pipeline_qc.csv",
        "heuristics_timeseries.csv",
        "interval_stats.csv",
        "shoulder_hike_proxy.png",
        "neck_extension_proxy.png",
    ]:
        print(outdir / name)

    print(
        "\nInterpretation rule: a useful heuristic should (1) stay near zero in "
        "the neutral baseline, (2) move consistently during the known action, "
        "(3) agree in sign/timing with the video, and (4) not be driven by "
        "low-confidence or out-of-frame landmarks."
    )
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        raise