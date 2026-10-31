# Station Service

Local camera discovery and camera assignment service for the ophthalmology ergonomic training station.

## Start the API

```powershell
cd station-service
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

## Endpoints

- `GET /health` returns `{ "status": "ok" }`
- `GET /cameras` enumerates DirectShow devices and reports each as available, busy, or unavailable
- `GET /cameras/{camera_id}/preview` streams the selected camera as MJPEG
- `GET /camera-config` returns the current saved station configuration
- `PUT /camera-config` saves the Side and Rear camera assignments
- `POST /sessions/start` starts recording the configured cameras
- `POST /sessions/stop` stops recording and finalizes session files
- `GET /sessions/current` returns active recording state for page recovery

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
