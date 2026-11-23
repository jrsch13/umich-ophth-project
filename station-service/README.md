# Station Service

Local camera discovery and camera assignment service for the ophthalmology ergonomic training station.

## Start the API

Choose the OpenPose backend for the station before starting FastAPI. The default is `cpu` if `OPENPOSE_BACKEND` is unset. The variable applies only to the current PowerShell session unless you configure it permanently.

### CPU workstation

The CPU backend uses the native Windows portable OpenPose build and does not require NVIDIA or WSL. Inference is much slower than the WSL/CUDA backend.

```powershell
cd station-service
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:OPENPOSE_BACKEND="cpu"
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

### NVIDIA / WSL workstation

The WSL backend uses the source-built CUDA OpenPose installation in WSL2 and is intended for NVIDIA GPU inference. It is expected to be much faster than CPU inference.

```powershell
cd station-service
.\.venv\Scripts\Activate.ps1
$env:OPENPOSE_BACKEND="wsl"
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

The backend is fixed for that FastAPI process; residents do not select it. The service does not fall back between backends. Check `GET /openpose/status` to see the configured backend and readiness. Supported values are `cpu` and `wsl`; any other value is reported as invalid and prevents analysis from starting.

## Endpoints

- `GET /health` returns `{ "status": "ok" }`
- `GET /openpose/status` reports the configured OpenPose backend and readiness
- `GET /cameras` returns the cached DirectShow inventory and current capture status
- `POST /cameras/rescan` explicitly refreshes the DirectShow inventory
- `GET /cameras/{camera_id}/preview` streams the selected camera as MJPEG
- `GET /camera-config` returns the current saved station configuration
- `PUT /camera-config` saves the Side and Rear camera assignments
- `POST /sessions/start` starts recording the configured cameras
- `POST /sessions/stop` stops recording, finalizes session files, and starts OpenPose in the background
- `GET /sessions/current` returns active recording state for page recovery
- `GET /sessions/{session_id}/analysis-status` returns per-view OpenPose and posture progress
- `POST /sessions/{session_id}/analyze` starts or retries the full OpenPose pipeline for a completed session
- `POST /sessions/{session_id}/analysis/{view}/retry` runs posture analysis from existing JSON without rerunning OpenPose
- `GET /sessions` lists saved sessions newest-first with analysis and plot availability
- `GET /sessions/{session_id}` returns metadata, stage status, per-view summaries and plot URLs
- `GET /sessions/{session_id}/analysis/{view}/plots/{filename}` serves a session plot PNG

Start a session with JSON such as:

```json
{
  "resident_id": "TEST001",
  "session_label": "Slit lamp practice"
}
```

On Windows, a camera ID is a SHA-256 identifier derived from its DirectShow device path (or moniker display name when the property bag omits the path). The DirectShow enumeration index is exposed separately as `backend_index` and is used only to open that device through OpenCV's DirectShow backend. Friendly names are display-only and can be duplicated.

The runtime config is stored in `station-service/camera_config.json`. `side_camera_id` and `rear_camera_id` store stable IDs. Existing integer/index-only assignments are returned as needing attention and are not automatically rebound; choose the physical camera again on the Cameras page and save. An example config is provided in `camera_config.example.json`.

A process-level station camera manager enumerates once at service startup and thereafter only on `POST /cameras/rescan`. Cameras-page and New Session mounts and status polls read the cached inventory and do not enumerate hardware. The manager owns one capture thread and `VideoCapture` handle per configured physical camera; preview uses its latest-frame buffer and recording subscribes to frames from that same stream. A preview client disconnect does not release a configured camera. An unassigned camera opened only for an ad-hoc preview is released after its last preview subscriber disconnects.

If a configured physical camera stops providing frames, that exact ID is marked disconnected and is not substituted with another same-named device. Its saved assignment is retained; use Rescan Cameras after reconnecting it. Logs include stable ID, display name, backend index, physical open/release, preview and recorder subscribers, rescan, and disconnect/reconnect events.

Recording sessions are stored under `station-service/sessions/`. Each session contains metadata, an `analysis_status.json` marker created on stop, and one MP4 plus per-frame timestamp CSV for each configured camera. Camera timestamps use one shared monotonic session start reference; this is software synchronization, not hardware synchronization. Stopping recording detaches the recorders but leaves configured station camera streams open.

The station camera manager owns physical capture streams; recording attaches to the configured streams without opening another camera handle. Stopping the service first finalizes an active recording and then releases the manager-owned streams.

After recording stops, the service invokes the configured CPU or WSL wrapper once for each available raw view. The runner does not use or reopen cameras. Both backends write BODY_25 JSON under `openpose/<view>/json/`, labeled AVI files under `labeled-videos/`, and per-view PowerShell/OpenPose output under `logs/`. Once a view's OpenPose output passes artifact checks, posture analysis writes CSV, summary JSON, and PNG plots under `analysis/<view>/`. The selected backend and each stage's status are recorded in `analysis_status.json`. The API returns without waiting for inference; use the analysis-status endpoint to poll. If posture analysis fails, its error is recorded and the raw video, OpenPose JSON, and labeled AVI remain available. Retry only that stage through the posture retry endpoint.

For an existing JSON fixture such as `sessions/dummy_side_test`, start the service and call `POST /sessions/dummy_side_test/analysis/side/retry`. Poll `GET /sessions/dummy_side_test/analysis-status` until complete or failed. This retry uses `raw/side_timestamps.csv` when present and otherwise uses the 30 FPS fallback. It uses the first 10 seconds as the neutral baseline.

The CPU wrapper expects the portable Windows OpenPose executable and BODY_25 models under `openpose-pipeline/openpose/`. The WSL wrapper expects the OpenPose build and BODY_25 model at `~/openpose` inside WSL, with GPU support configured as described in `openpose-pipeline/README.MD`.
