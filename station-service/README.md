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
- `GET /cameras` enumerates DirectShow devices and reports each as available, busy, or unavailable
- `GET /cameras/{camera_id}/preview` streams the selected camera as MJPEG
- `GET /camera-config` returns the current saved station configuration
- `PUT /camera-config` saves the Side and Rear camera assignments
- `POST /sessions/start` starts recording the configured cameras
- `POST /sessions/stop` stops recording, finalizes session files, and starts OpenPose in the background
- `GET /sessions/current` returns active recording state for page recovery
- `GET /sessions/{session_id}/analysis-status` returns per-view OpenPose progress
- `POST /sessions/{session_id}/analyze` starts or retries analysis for a completed session

Start a session with JSON such as:

```json
{
  "resident_id": "TEST001",
  "session_label": "Slit lamp practice"
}
```

The runtime config is stored in `station-service/camera_config.json`. An example config is provided in `camera_config.example.json`.

The preview endpoint holds a per-camera lock for the lifetime of the stream, preventing discovery or another preview from opening the same camera concurrently. The camera handle is released when the stream ends or its client disconnects. Previews are reduced to at most 640x360 and approximately 15 FPS to limit CPU usage.

Discovery does not remove a DirectShow-enumerated device when its capture lock is busy or OpenCV cannot currently open it. Responses include `connected` and `availability` (`available`, `busy`, or `unavailable`). The backend logs camera open/release, lock ownership, preview disconnect, and recording lifecycle events with camera IDs/names and request/thread context.

Recording sessions are stored under `station-service/sessions/`. Each session contains metadata, an `analysis_status.json` marker created on stop, and one MP4 plus per-frame timestamp CSV for each configured camera. Camera timestamps use one shared monotonic session start reference; this is software synchronization, not hardware synchronization.

The service takes exclusive per-camera locks while recording. Stopping the service also stops and finalizes an active session.

After recording stops, the service invokes the configured CPU or WSL wrapper once for each available raw view. The runner does not use or reopen cameras. Both backends write BODY_25 JSON under `openpose/<view>/json/`, labeled AVI files under `labeled-videos/`, and per-view PowerShell/OpenPose output under `logs/`. The selected backend is recorded in `analysis_status.json` and each view log. The API returns without waiting for inference; use the analysis-status endpoint to poll. A failed analysis preserves the raw video and can be retried with the analyze endpoint.

The CPU wrapper expects the portable Windows OpenPose executable and BODY_25 models under `openpose-pipeline/openpose/`. The WSL wrapper expects the OpenPose build and BODY_25 model at `~/openpose` inside WSL, with GPU support configured as described in `openpose-pipeline/README.MD`.
