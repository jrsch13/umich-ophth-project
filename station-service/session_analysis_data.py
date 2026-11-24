"""Read-only posture summaries, time series, and saved-frame access."""

from __future__ import annotations

import csv
import json
import logging
import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2

from analysis.analyze_openpose import DEFAULT_FPS
from analysis.posture_metrics import DEFAULT_THRESHOLDS, UPRIGHT_TOLERANCE_DEG


logger = logging.getLogger(__name__)
MAX_TIME_SERIES_POINTS = 2000
VIEWS = ("side", "rear")


@dataclass(frozen=True)
class ReferenceZoneRule:
    category: str
    label: str
    rule_type: str
    explanation: str


@dataclass(frozen=True)
class MetricSpec:
    key: str
    label: str
    view: str
    threshold_key: str
    columns: tuple[str, ...]
    unit: str
    category_column: str
    categories: dict[str, tuple[str, int | None]]
    reference_zone: ReferenceZoneRule
    absolute_threshold: bool = True
    posture_angle_column: str | None = None
    posture_angle_absolute: bool = False


METRIC_SPECS = {
    "neck_flexion_extension": MetricSpec(
        key="neck_flexion_extension",
        label="Neck flexion / extension",
        view="side",
        threshold_key="Neck_Flexion_Extension",
        columns=("Neck_Flexion_Extension",),
        unit="degrees",
        category_column="Neck_RULA_Category",
        categories={
            "flexion_0_10": ("0–10° flexion", 1),
            "flexion_10_20": ("10–20° flexion", 2),
            "flexion_over_20": (">20° flexion", 3),
            "extension": ("Extension", 4),
        },
        reference_zone=ReferenceZoneRule(
            category="flexion_0_10",
            label="0–10° neck flexion",
            rule_type="rula_reference_category",
            explanation=(
                "0–10° neck flexion (RULA neck posture score 1). "
                "Greater flexion and any detected extension fall outside the reference zone."
            ),
        ),
        posture_angle_column="Neck_Angle_Deg",
    ),
    "shoulder_hiking": MetricSpec(
        key="shoulder_hiking",
        label="Shoulder hiking",
        view="rear",
        threshold_key="Shoulder_Hiking",
        columns=(
            "R_Shoulder_Hiking_Pct_Hip_Width",
            "L_Shoulder_Hiking_Pct_Hip_Width",
        ),
        unit="% of hip width",
        category_column="Shoulder_Hiking_Class",
        categories={
            "Neutral": ("Neutral", None),
            "Unilateral Right Hiking": ("Unilateral Right Hiking", None),
            "Unilateral Left Hiking": ("Unilateral Left Hiking", None),
            "Bilateral Hiking": ("Bilateral Hiking", None),
        },
        reference_zone=ReferenceZoneRule(
            category="Neutral",
            label="Neutral",
            rule_type="project_specific_rula_adjustment_detection",
            explanation=(
                "Neutral. RULA adjusts the upper-arm posture score when a shoulder is raised. "
                "The prototype uses a project-specific research threshold of "
                f'{DEFAULT_THRESHOLDS["Shoulder_Hiking"]:g}% of hip width or more to detect elevation.'
            ),
        ),
        absolute_threshold=False,
    ),
    "forward_trunk_lean": MetricSpec(
        key="forward_trunk_lean",
        label="Forward trunk lean",
        view="side",
        threshold_key="Trunk_Flexion_Extension",
        columns=("Trunk_Flexion_Extension",),
        unit="degrees",
        category_column="Trunk_RULA_Category",
        categories={
            "upright": ("Approximately upright", 1),
            "flexion_0_20": ("0–20° flexion", 2),
            "flexion_20_60": ("20–60° flexion", 3),
            "flexion_over_60": (">60° flexion", 4),
        },
        reference_zone=ReferenceZoneRule(
            category="upright",
            label="Approximately upright",
            rule_type="project_specific_automation_tolerance",
            explanation=(
                "Approximately upright. The prototype uses a "
                f"±{UPRIGHT_TOLERANCE_DEG:g}° project-specific computer-vision tolerance "
                "to identify upright posture."
            ),
        ),
        posture_angle_column="Trunk_Angle_Deg",
        posture_angle_absolute=True,
    ),
    "lateral_trunk_lean": MetricSpec(
        key="lateral_trunk_lean",
        label="Lateral trunk lean",
        view="rear",
        threshold_key="Trunk_Leaning",
        columns=("Trunk_Lean",),
        unit="degrees",
        category_column="Trunk_Sidebend_Adjustment_Present",
        categories={
            "False": ("No side-bending adjustment", None),
            "True": ("Side-bending adjustment present", None),
        },
        reference_zone=ReferenceZoneRule(
            category="False",
            label="No trunk side-bending adjustment",
            rule_type="project_specific_rula_adjustment_detection",
            explanation=(
                "No side-bending adjustment. RULA uses a single +1 adjustment for trunk "
                "side-bending. The prototype applies it at an absolute lateral tilt of "
                f'{DEFAULT_THRESHOLDS["Trunk_Leaning"]:g}° or more using a project-specific detection tolerance.'
            ),
        ),
        posture_angle_column="Lateral_Lean_Deg",
    ),
}


class AnalysisDataError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _frame_number(value: Any) -> int | None:
    number = _number(value)
    if number is None or number < 0 or not number.is_integer():
        return None
    return int(number)


def _read_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                return []
            return list(reader)
    except (OSError, UnicodeError, csv.Error) as error:
        raise AnalysisDataError(500, "Could not read the saved posture metrics.") from error


def _read_recorded_times(session_dir: Path, view: str) -> dict[int, float]:
    path = session_dir / "raw" / f"{view}_timestamps.csv"
    if not path.is_file():
        return {}
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            required = {"frame_index", "seconds_from_session_start"}
            if not reader.fieldnames or not required.issubset(reader.fieldnames):
                raise AnalysisDataError(500, f"The {view} timestamp file has an invalid format.")
            times: dict[int, float] = {}
            for row in reader:
                frame = _frame_number(row.get("frame_index"))
                seconds = _number(row.get("seconds_from_session_start"))
                if frame is not None and seconds is not None and seconds >= 0:
                    times[frame] = seconds
            return times
    except (OSError, UnicodeError, csv.Error) as error:
        raise AnalysisDataError(500, f"Could not read {view} recording timestamps.") from error


def _positive_cadence(times: dict[int, float]) -> float | None:
    intervals = [
        times[frame + 1] - seconds
        for frame, seconds in times.items()
        if frame + 1 in times and times[frame + 1] > seconds
    ]
    return statistics.median(intervals) if intervals else None


def _session_duration(session_dir: Path, metadata: dict[str, Any]) -> float | None:
    duration = _number(metadata.get("duration_seconds"))
    if duration is not None and duration > 0:
        return duration

    timestamp_ends: list[float] = []
    for view in VIEWS:
        try:
            times = _read_recorded_times(session_dir, view)
        except AnalysisDataError:
            logger.warning("Ignoring invalid %s timestamps for session duration: %s", view, session_dir.name)
            continue
        cadence = _positive_cadence(times)
        if times and cadence is not None:
            timestamp_ends.append(max(times.values()) + cadence)
    if timestamp_ends:
        return max(timestamp_ends)

    video_durations: list[float] = []
    for view in VIEWS:
        video_path = session_dir / "raw" / f"{view}.mp4"
        if not video_path.is_file():
            continue
        capture = cv2.VideoCapture(str(video_path))
        try:
            frame_count = _number(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = _number(capture.get(cv2.CAP_PROP_FPS))
            if capture.isOpened() and frame_count and fps and frame_count > 0 and fps > 0:
                video_durations.append(frame_count / fps)
        finally:
            capture.release()
    return max(video_durations) if video_durations else None


def _metric_times(row: dict[str, str], recorded_times: dict[int, float]) -> tuple[int, float] | None:
    frame = _frame_number(row.get("frame"))
    if frame is None:
        return None
    seconds = recorded_times.get(frame)
    if seconds is None:
        seconds = _number(row.get("Time_seconds"))
    if seconds is None or seconds < 0:
        return None
    return frame, seconds


def _row_intervals(
    rows: list[dict[str, str]],
    recorded_times: dict[int, float],
    total_session_seconds: float | None,
    last_recorded_frame: int | None,
) -> list[float]:
    positions = [_metric_times(row, recorded_times) for row in rows]
    positioned = sorted(
        (position for position in positions if position is not None),
        key=lambda item: item[0],
    )
    source_times = recorded_times or dict(positioned)
    cadence = _positive_cadence(source_times)
    if cadence is None:
        cadence = _positive_cadence(dict(positioned))
    if cadence is None:
        cadence = 1.0 / DEFAULT_FPS

    max_source_frame = last_recorded_frame
    if max_source_frame is None and source_times:
        max_source_frame = max(source_times)
    durations: dict[int, float] = {}
    for frame, seconds in positioned:
        next_seconds = source_times.get(frame + 1)
        if next_seconds is not None and next_seconds > seconds:
            interval = next_seconds - seconds
        elif (
            max_source_frame == frame
            and total_session_seconds is not None
            and recorded_times
            and len(source_times) > 1
        ):
            interval = max(0.0, total_session_seconds - seconds)
        else:
            interval = cadence
        if total_session_seconds is not None:
            interval = min(interval, max(0.0, total_session_seconds - seconds))
        durations[frame] = max(0.0, interval)
    return [
        durations.get(position[0], 0.0) if position is not None else 0.0
        for position in positions
    ]


def _threshold(session_dir: Path, spec: MetricSpec) -> tuple[float, str]:
    summary_path = session_dir / "analysis" / spec.view / "summary.json"
    if summary_path.is_file():
        try:
            with summary_path.open(encoding="utf-8") as handle:
                summary = json.load(handle)
            value = _number(summary.get("thresholds", {}).get(spec.threshold_key))
            if value is not None and value >= 0:
                return value, "analysis_summary"
        except (OSError, json.JSONDecodeError, AttributeError):
            logger.warning("Using posture-analysis default for invalid threshold summary: %s", summary_path)
    return float(DEFAULT_THRESHOLDS[spec.threshold_key]), "posture_analysis_default"


def _base_summary(
    spec: MetricSpec,
    threshold: float,
    threshold_source: str,
    total_session_seconds: float | None,
    *,
    status: str,
    reason: str | None,
) -> dict[str, Any]:
    return {
        "metric": spec.key,
        "label": spec.label,
        "view": spec.view,
        "unit": spec.unit,
        "threshold": threshold,
        "threshold_source": threshold_source,
        "threshold_semantics": "deprecated_legacy_binary_project_heuristic",
        "legacy_binary_threshold_exposure_deprecated": True,
        "category_definition": (
            {
                "upright_tolerance_degrees": UPRIGHT_TOLERANCE_DEG,
                "upright_tolerance_type": "project_specific_automation_tolerance",
            }
            if spec.key == "forward_trunk_lean"
            else None
        ),
        "status": status,
        "available": status == "available",
        "reason": reason,
        "within_threshold_seconds": None,
        "above_threshold_seconds": None,
        "within_threshold_percent": None,
        "above_threshold_percent": None,
        "valid_tracking_seconds": None,
        "valid_tracking_percent": None,
        "reference_zone_exposure": {
            "within_seconds": None,
            "outside_seconds": None,
            "within_percent": None,
            "outside_percent": None,
            "rule_label": spec.reference_zone.label,
            "rule_type": spec.reference_zone.rule_type,
            "rule_explanation": spec.reference_zone.explanation,
        },
        "total_session_seconds": (
            round(total_session_seconds, 3) if total_session_seconds is not None else None
        ),
        "category_distribution": [],
    }


def _is_above(row: dict[str, str], spec: MetricSpec, threshold: float) -> bool | None:
    values = [_number(row.get(column)) for column in spec.columns]
    if spec.key == "shoulder_hiking":
        present = [value for value in values if value is not None]
        if not present:
            return None
        return any(value >= threshold for value in present)
    if any(value is None for value in values):
        return None
    value = values[0]
    if value is None:
        return None
    return (abs(value) if spec.absolute_threshold else value) >= threshold


def _summarize_metric(
    session_dir: Path,
    spec: MetricSpec,
    rows_by_view: dict[str, list[dict[str, str]] | None],
    times_by_view: dict[str, dict[int, float]],
    total_session_seconds: float | None,
    last_recorded_frame: int | None,
) -> dict[str, Any]:
    threshold, threshold_source = _threshold(session_dir, spec)
    raw_video = session_dir / "raw" / f"{spec.view}.mp4"
    if not raw_video.is_file():
        return _base_summary(
            spec, threshold, threshold_source, total_session_seconds,
            status="unavailable", reason="view_not_recorded",
        )

    rows = rows_by_view.get(spec.view)
    if rows is None:
        return _base_summary(
            spec, threshold, threshold_source, total_session_seconds,
            status="unavailable", reason="analysis_not_available",
        )

    summary = _base_summary(
        spec, threshold, threshold_source, total_session_seconds,
        status="insufficient_tracking", reason="metric_columns_missing",
    )
    if not rows:
        return summary

    intervals = _row_intervals(
        rows,
        times_by_view[spec.view],
        total_session_seconds,
        last_recorded_frame,
    )

    legacy_valid_seconds = 0.0
    above_seconds = 0.0
    within_seconds = 0.0
    category_seconds = dict.fromkeys(spec.categories, 0.0)
    for row, interval in zip(rows, intervals):
        if interval <= 0:
            continue

        classification = _is_above(row, spec, threshold)
        if classification is not None:
            legacy_valid_seconds += interval
            if classification:
                above_seconds += interval
            else:
                within_seconds += interval

        category = str(row.get(spec.category_column, "")).strip()
        if category in category_seconds:
            category_seconds[category] += interval

    valid_seconds = sum(category_seconds.values())
    summary.update({
        "valid_tracking_seconds": round(valid_seconds, 3),
        "valid_tracking_percent": (
            round(min(100.0, valid_seconds / total_session_seconds * 100.0), 2)
            if total_session_seconds and total_session_seconds > 0
            else None
        ),
    })
    if valid_seconds <= 0:
        summary["reason"] = (
            "category_data_unavailable"
            if spec.category_column not in rows[0]
            else "no_valid_tracking"
        )
        return summary

    in_zone_seconds = category_seconds[spec.reference_zone.category]
    outside_zone_seconds = sum(
        seconds for category, seconds in category_seconds.items()
        if category != spec.reference_zone.category
    )
    summary["reference_zone_exposure"].update({
        "within_seconds": round(in_zone_seconds, 3),
        "outside_seconds": round(outside_zone_seconds, 3),
        "within_percent": round(in_zone_seconds / valid_seconds * 100.0, 2),
        "outside_percent": round(outside_zone_seconds / valid_seconds * 100.0, 2),
    })
    summary.update({
        "status": "available",
        "available": True,
        "reason": None,
        "category_distribution": [
            {
                "key": category,
                "label": label,
                "rula_score": score,
                "rula_adjustment_present": (
                    category != spec.reference_zone.category
                    if spec.reference_zone.rule_type == "project_specific_rula_adjustment_detection"
                    else None
                ),
                "seconds": round(category_seconds[category], 3),
                "percent_of_valid_time": round(category_seconds[category] / valid_seconds * 100.0, 2),
            }
            for category, (label, score) in spec.categories.items()
        ],
    })
    if legacy_valid_seconds > 0:
        summary.update({
            "within_threshold_seconds": round(within_seconds, 3),
            "above_threshold_seconds": round(above_seconds, 3),
            "within_threshold_percent": round(
                within_seconds / legacy_valid_seconds * 100.0, 2
            ),
            "above_threshold_percent": round(
                above_seconds / legacy_valid_seconds * 100.0, 2
            ),
        })
    return summary


def posture_summaries(
    session_dir: Path,
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    duration = _session_duration(session_dir, metadata)
    rows_by_view: dict[str, list[dict[str, str]] | None] = {}
    times_by_view: dict[str, dict[int, float]] = {}
    unreadable_views: set[str] = set()
    for view in VIEWS:
        csv_path = session_dir / "analysis" / view / "posture_metrics.csv"
        if csv_path.is_file():
            try:
                rows_by_view[view] = _read_rows(csv_path)
            except AnalysisDataError:
                logger.exception("Could not read analysis data for session=%s view=%s", session_dir.name, view)
                rows_by_view[view] = None
                times_by_view[view] = {}
                unreadable_views.add(view)
                continue
            try:
                times_by_view[view] = _read_recorded_times(session_dir, view)
            except AnalysisDataError:
                logger.warning("Using posture CSV timestamps for session=%s view=%s", session_dir.name, view)
                times_by_view[view] = {}
        else:
            rows_by_view[view] = None
            times_by_view[view] = {}
    summaries = []
    for spec in METRIC_SPECS.values():
        frame_counts = metadata.get("frame_counts")
        frame_count = (
            _frame_number(frame_counts.get(spec.view))
            if isinstance(frame_counts, dict)
            else None
        )
        summary = _summarize_metric(
            session_dir,
            spec,
            rows_by_view,
            times_by_view,
            duration,
            frame_count - 1 if frame_count is not None and frame_count > 0 else None,
        )
        if spec.view in unreadable_views:
            summary["reason"] = "analysis_data_unreadable"
        summaries.append(summary)
    return summaries


def _point(row: dict[str, str], spec: MetricSpec, recorded_times: dict[int, float]) -> dict[str, Any] | None:
    position = _metric_times(row, recorded_times)
    if position is None:
        return None
    frame, seconds = position
    values = [_number(row.get(column)) for column in spec.columns]
    if spec.key == "shoulder_hiking":
        if all(value is None for value in values):
            return None
        point = {
            "time_seconds": round(seconds, 6),
            "frame": frame,
            "right_value": round(values[0], 6) if values[0] is not None else None,
            "left_value": round(values[1], 6) if values[1] is not None else None,
        }
        if spec.category_column in row:
            category = row.get(spec.category_column)
            point["category"] = category if category in spec.categories else None
        return point
    value = values[0]
    if value is None:
        return None
    category = row.get(spec.category_column)
    point = {
        "time_seconds": round(seconds, 6),
        "frame": frame,
        "value": round(value, 6),
        "category": category if category in spec.categories else None,
    }
    if spec.posture_angle_column:
        posture_angle = _number(row.get(spec.posture_angle_column))
        if posture_angle is not None:
            if spec.posture_angle_absolute:
                posture_angle = abs(posture_angle)
            point["posture_angle_deg"] = round(posture_angle, 6)
    return point


def _point_value(point: dict[str, Any], channel: str, spec: MetricSpec) -> float | None:
    key = (
        ("right_value" if channel == spec.columns[0] else "left_value")
        if spec.key == "shoulder_hiking"
        else "value"
    )
    return point.get(key)


def _point_is_above(value: float | None, spec: MetricSpec, threshold: float) -> bool | None:
    if value is None:
        return None
    return (abs(value) if spec.absolute_threshold else value) >= threshold


def _downsample_points(
    points: list[dict[str, Any]],
    spec: MetricSpec,
    threshold: float,
) -> list[dict[str, Any]]:
    if len(points) <= MAX_TIME_SERIES_POINTS:
        return points

    channel_count = len(spec.columns)
    candidates_per_bucket = 2 + 6 * channel_count
    bucket_count = max(1, MAX_TIME_SERIES_POINTS // candidates_per_bucket)
    bucket_size = math.ceil(len(points) / bucket_count)
    selected: set[int] = set()

    for start in range(0, len(points), bucket_size):
        end = min(len(points), start + bucket_size)
        selected.update((start, end - 1))
        for column in spec.columns:
            valid = [
                (index, _point_value(points[index], column, spec))
                for index in range(start, end)
            ]
            valid = [(index, value) for index, value in valid if value is not None]
            if not valid:
                continue
            selected.add(min(valid, key=lambda item: item[1])[0])
            selected.add(max(valid, key=lambda item: item[1])[0])
            crossings = []
            for (previous_index, previous), (current_index, current) in zip(valid, valid[1:]):
                previous_state = _point_is_above(previous, spec, threshold)
                current_state = _point_is_above(current, spec, threshold)
                if (
                    current_index == previous_index + 1
                    and previous_state is not None
                    and current_state is not None
                    and previous_state != current_state
                ):
                    crossings.append((previous_index, current_index))
            if crossings:
                for index in (*crossings[0], *crossings[-1]):
                    selected.add(index)

    return [points[index] for index in sorted(selected)]


def metric_time_series(session_dir: Path, metric: str) -> dict[str, Any]:
    spec = METRIC_SPECS.get(metric)
    if spec is None:
        raise AnalysisDataError(404, "Posture metric not found.")
    if not (session_dir / "raw" / f"{spec.view}.mp4").is_file():
        raise AnalysisDataError(404, f"The {spec.view} view was not recorded for this session.")
    csv_path = session_dir / "analysis" / spec.view / "posture_metrics.csv"
    if not csv_path.is_file():
        raise AnalysisDataError(409, f"Posture analysis is not available for the {spec.view} view.")

    rows = _read_rows(csv_path)
    if rows and any(column not in rows[0] for column in spec.columns):
        raise AnalysisDataError(409, "The requested posture metric is not present in the analysis data.")
    recorded_times = _read_recorded_times(session_dir, spec.view)
    points = [
        point
        for row in rows
        if (point := _point(row, spec, recorded_times)) is not None
    ]
    threshold, threshold_source = _threshold(session_dir, spec)
    downsampled = _downsample_points(points, spec, threshold)
    response: dict[str, Any] = {
        "metric": spec.key,
        "label": spec.label,
        "view": spec.view,
        "threshold": threshold,
        "threshold_source": threshold_source,
        "threshold_semantics": "deprecated_legacy_binary_project_heuristic",
        "threshold_deprecated": True,
        "unit": spec.unit,
        "status": "available" if points else "insufficient_tracking",
        "reason": None if points else "no_valid_tracking",
        "source_point_count": len(points),
        "returned_point_count": len(downsampled),
        "downsampled": len(downsampled) < len(points),
        "max_points": MAX_TIME_SERIES_POINTS,
        "points": downsampled,
    }
    return response


def saved_video_frame(session_dir: Path, view: str, frame: int) -> bytes:
    if view not in VIEWS:
        raise AnalysisDataError(400, "View must be 'side' or 'rear'.")
    if isinstance(frame, bool) or frame < 0:
        raise AnalysisDataError(400, "Frame must be a non-negative integer.")

    resolved_session = session_dir.resolve()
    raw_dir = (session_dir / "raw").resolve()
    if not raw_dir.is_relative_to(resolved_session):
        raise AnalysisDataError(404, f"The {view} raw video was not found.")
    video_path = raw_dir / f"{view}.mp4"
    try:
        video_path = video_path.resolve(strict=True)
    except OSError:
        raise AnalysisDataError(404, f"The {view} raw video was not found.") from None
    if video_path.parent != raw_dir or not video_path.is_relative_to(resolved_session):
        raise AnalysisDataError(404, f"The {view} raw video was not found.")

    capture = cv2.VideoCapture(str(video_path))
    try:
        if not capture.isOpened():
            raise AnalysisDataError(404, f"The {view} raw video could not be opened.")
        frame_count = _number(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if frame_count is not None and frame >= frame_count:
            raise AnalysisDataError(404, "The requested frame does not exist.")
        try:
            seek_position = float(frame)
        except OverflowError:
            raise AnalysisDataError(404, "The requested frame does not exist.") from None
        capture.set(cv2.CAP_PROP_POS_FRAMES, seek_position)
        read_ok, image = capture.read()
        if not read_ok or image is None:
            raise AnalysisDataError(404, "The requested frame does not exist.")
        encoded_ok, encoded = cv2.imencode(
            ".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 90]
        )
        if not encoded_ok:
            raise AnalysisDataError(500, "Could not encode the requested video frame.")
        return encoded.tobytes()
    finally:
        capture.release()
