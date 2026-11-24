"""Create or remove the local Session Analysis demo recording."""

import argparse
import csv
import json
import math
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np


SESSION_ID = "demo-rula-ui-test"
MARKER = ".session-analysis-demo"
VIEWS = ("side", "rear")
FPS = 5
DURATION_SECONDS = 20
FRAME_COUNT = FPS * DURATION_SECONDS


def hold(*segments):
    """Expand (seconds, measurement, category) segments to one entry per second."""
    return [(value, category) for seconds, value, category in segments for _ in range(seconds)]


NECK = hold(
    (5, 4, "flexion_0_10"), (3, 14, "flexion_10_20"), (4, 7, "flexion_0_10"),
    (2, -5, "extension"), (4, 3, "flexion_0_10"), (2, 26, "flexion_over_20"),
)
FORWARD = hold(
    (7, 3, "upright"), (3, 13, "flexion_0_20"), (4, 2, "upright"),
    (2, 32, "flexion_20_60"), (1, 64, "flexion_over_60"), (3, 4, "upright"),
)
LATERAL = hold(
    (8, 1.5, False), (2, 7, True), (5, -1.5, False), (1, -7, True), (4, 2, False),
)
SHOULDERS = hold(
    (6, (5, 3), "Neutral"), (2, (22, 4), "Unilateral Right Hiking"),
    (5, (4, 5), "Neutral"), (1, (3, 23), "Unilateral Left Hiking"),
    (5, (6, 5), "Neutral"), (1, (23, 22), "Bilateral Hiking"),
)


def posture_rows(view):
    for frame in range(FRAME_COUNT):
        seconds = frame / FPS
        block = frame // FPS
        wave = round(0.7 * math.sin(seconds * 3), 2)
        values = {"frame": frame, "Time_seconds": seconds}
        if view == "side":
            neck, neck_category = NECK[block]
            trunk, trunk_category = FORWARD[block]
            values.update({
                "Neck_Flexion_Extension": neck + wave,
                "Neck_Angle_Deg": neck + wave,
                "Neck_RULA_Category": neck_category,
                "Trunk_Flexion_Extension": trunk - wave,
                "Trunk_Angle_Deg": trunk - wave,
                "Trunk_RULA_Category": trunk_category,
            })
        else:
            lateral, sidebend = LATERAL[block]
            (right, left), hiking = SHOULDERS[block]
            values.update({
                "Trunk_Lean": lateral + wave,
                "Lateral_Lean_Deg": abs(lateral + wave),
                "Trunk_Sidebend_Adjustment_Present": sidebend,
                "R_Shoulder_Hiking_Pct_Hip_Width": right + wave,
                "L_Shoulder_Hiking_Pct_Hip_Width": left - wave,
                "Shoulder_Hiking_Class": hiking,
            })
        yield values


def write_csv(path, rows):
    rows = iter(rows)
    first_row = next(rows)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(first_row))
        writer.writeheader()
        writer.writerow(first_row)
        writer.writerows(rows)


def write_demo_video(path, view):
    size = (480, 270)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, size)
    try:
        if not writer.isOpened():
            raise OSError(f"Could not create demo video {path}")
        background = (62, 48, 25) if view == "side" else (62, 36, 48)
        for frame in range(FRAME_COUNT):
            image = np.full((size[1], size[0], 3), background, dtype=np.uint8)
            for label, y, scale in (
                ("DEMO FRAME", 85, 1.5),
                (f"{view.upper()} VIEW  /  SYNTHETIC", 135, 0.7),
                (f"FRAME {frame:03d}  /  {frame / FPS:04.1f} S", 187, 0.8),
            ):
                cv2.putText(image, label, (32, y), cv2.FONT_HERSHEY_SIMPLEX,
                            scale, (245, 245, 245), 2, cv2.LINE_AA)
            writer.write(image)
    finally:
        writer.release()


def create_demo(session):
    session.parent.mkdir(parents=True, exist_ok=True)
    session.mkdir()
    try:
        raw = session / "raw"
        raw.mkdir()
        for view in VIEWS:
            analysis = session / "analysis" / view
            analysis.mkdir(parents=True)
            write_csv(analysis / "posture_metrics.csv", posture_rows(view))
            write_csv(raw / f"{view}_timestamps.csv", (
                {"frame_index": frame, "seconds_from_session_start": frame / FPS}
                for frame in range(FRAME_COUNT)
            ))
            write_demo_video(raw / f"{view}.mp4", view)

        ended_at = datetime.now().astimezone()
        metadata = {
            "session_id": SESSION_ID,
            "session_label": "DEMO — RULA UI Test",
            "started_at": (ended_at - timedelta(seconds=DURATION_SECONDS)).isoformat(),
            "ended_at": ended_at.isoformat(),
            "duration_seconds": DURATION_SECONDS,
            "frame_counts": dict.fromkeys(VIEWS, FRAME_COUNT),
        }
        stage = {"status": "complete", "openpose_status": "complete", "posture_status": "complete"}
        status = {
            "status": "complete",
            "stage": "complete",
            "completed_at": ended_at.isoformat(),
            "views": dict.fromkeys(VIEWS, stage),
        }
        (session / "analysis_status.json").write_text(json.dumps(status), encoding="utf-8")
        (session / MARKER).touch()
        # Publish metadata last so the session list only sees the completed fixture.
        draft_metadata = session / "metadata.json.tmp"
        draft_metadata.write_text(json.dumps(metadata), encoding="utf-8")
        draft_metadata.rename(session / "metadata.json")
    except BaseException:
        if session.resolve() == session:
            shutil.rmtree(session)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create", "remove"))
    args = parser.parse_args()
    sessions = Path(__file__).resolve().parent / "sessions"
    session = sessions / SESSION_ID
    if session.resolve() != session:
        parser.error(f"Demo path is redirected: {session}")
    marker = session / MARKER
    if session.exists() and (marker.is_symlink() or not marker.is_file()):
        parser.error(f"The demo path is occupied by a different session: {session}")
    if args.action == "create":
        if not session.exists():
            create_demo(session)
        print(f"Demo session is available at {session}")
    elif session.exists():
        shutil.rmtree(session)
        print(f"Removed demo session at {session}")
    else:
        print("Demo session is already absent.")


if __name__ == "__main__":
    main()
