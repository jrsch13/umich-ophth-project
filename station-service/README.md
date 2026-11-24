# Station Service

The local FastAPI backend handles camera discovery and assignment, persistent camera streams, session recording and metadata, OpenPose orchestration, posture analysis, and session APIs. It does not expose cameras directly to React; the service owns camera access.

## Setup and start

Run from PowerShell in `station-service/`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:OPENPOSE_BACKEND = "cpu" # Or "wsl" on an NVIDIA/WSL workstation.
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

The backend defaults to `cpu` when `OPENPOSE_BACKEND` is unset. Set `$env:OPENPOSE_BACKEND = "wsl"` for NVIDIA/WSL; it does not fall back between backends. Check `GET /openpose/status` for readiness. See [OpenPose setup](../openpose-pipeline/README.md) for installing either runtime.

The React interface runs separately from `resident-interface/` with `npm run dev`.

## Important files

| Path | Responsibility |
| --- | --- |
| `app.py` | FastAPI routes and service lifecycle. |
| `cameras.py`, `station_cameras.py` | Camera preview and the shared physical capture streams. |
| `camera_config.py` | Persisted Side and Rear camera assignments. |
| `session_manager.py`, `recording.py` | Recording lifecycle, video files, timestamps, and metadata. |
| `openpose_runner.py` | Starts CPU/WSL inference, tracks per-view stages, and supports posture-only retries. |
| `posture_analysis_runner.py` | Runs posture analysis from existing OpenPose JSON and checks expected outputs. |
| `analysis_status_store.py` | Reads and synchronizes atomic per-session status-file updates. |
| `session_catalog.py`, `session_analysis_data.py` | Session listing/details and analysis data served to the UI. |
| `analysis/` | BODY_25 JSON loading, posture metrics, and CSV/summary/plot generation. |
| `sessions/` | Runtime session data; ignored by Git. |
| `requirements.txt` | FastAPI, Uvicorn, OpenCV, and backend dependencies. |
| `test_*.py` | Backend regression and unit tests. |

## Session files

```text
sessions/<session_id>/
├── metadata.json
├── analysis_status.json
├── raw/                  # side.mp4/rear.mp4 and per-frame timestamp CSVs
├── openpose/<view>/json/ # BODY_25 *_keypoints.json
├── labeled-videos/       # <view>_labeled.avi
├── analysis/<view>/      # metrics CSV, summary JSON, plots/
└── logs/                 # per-view OpenPose logs
```

The pipeline is `raw video → OpenPose JSON → posture metrics and summary → Session Analysis API`. Analysis uses the recording's timestamp CSV when available; otherwise it falls back to 30 FPS.

## Posture measures

| View | Measure | Plain-language ergonomic definition |
| --- | --- | --- |
| Side | Neck flexion/extension | Forward or backward cervical bending away from neutral alignment. |
| Side | Forward trunk lean | Forward bending of the torso away from an upright posture. |
| Rear/rear-oblique | Lateral trunk lean | Side-bending of the torso away from neutral vertical alignment. |
| Rear/rear-oblique | Shoulder hiking | Elevation of one or both shoulders from a relaxed position. |

These are ergonomic descriptions, not clinical diagnoses. See AAO's [Ergonomics Simplified](https://www.aao.org/young-ophthalmologists/yo-info/article/ergonomics-simplified) and NIOSH's [About Ergonomics and Work-Related Musculoskeletal Disorders](https://www.cdc.gov/niosh/ergonomics/about/index.html) for background on neutral posture and awkward postures.

Session Analysis exposes RULA-aligned posture categories for neck flexion/extension and forward trunk posture, plus project-detected side-bending and raised-shoulder adjustments. The API returns `category_distribution` and `reference_zone_exposure` for each posture. The reference zone is neck flexion in RULA posture score 1, approximately upright trunk posture, no side-bending adjustment, or the Neutral shoulder class, respectively. Forward trunk uses a project-specific ±5° tolerance around zero for the upright category. The project applies the side-bending adjustment at 5° of absolute lateral tilt or more and detects a raised shoulder at an elevation increase of 18% of hip width or more.

Category and reference-zone percentages use valid tracked time. The API reports valid tracking as a separate percentage of session time. Exposure percentages are `null` when tracking is unavailable. Legacy binary threshold exposure fields remain for backward compatibility and are deprecated. The prototype automates selected RULA components and does not calculate the complete RULA grand score.

## API workflow

- `GET /cameras` reads the cached camera inventory; `POST /cameras/rescan` refreshes it. `GET`/`PUT /camera-config` reads or saves assignments.
- `POST /sessions/start` and `/sessions/stop` record a session; stop starts analysis in the background.
- `GET /sessions` and `/sessions/{session_id}` provide saved session history and details.
- `GET /sessions/{session_id}/analysis-status` reports progress.
- `POST /sessions/{session_id}/analyze` starts the full OpenPose pipeline. `POST /sessions/{session_id}/analysis/{view}/retry` reruns posture analysis from existing JSON without rerunning OpenPose.

## Tests

From `station-service/`:

```powershell
python -m unittest discover
```

The API `TestClient` tests also require `httpx`, which is not included in the runtime requirements: install it in the development environment with `python -m pip install httpx`.
