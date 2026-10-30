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
- `GET /cameras` scans camera indexes 0-8 using OpenCV and reports valid devices
- `GET /cameras/{camera_id}/preview` streams the selected camera as MJPEG
- `GET /camera-config` returns the current saved station configuration
- `PUT /camera-config` saves the Side and Rear camera assignments

The runtime config is stored in `station-service/camera_config.json`. An example config is provided in `camera_config.example.json`.

The preview endpoint holds a per-camera lock for the lifetime of the stream, preventing discovery or another preview from opening the same camera concurrently. The camera handle is released when the stream ends or its client disconnects. Previews are reduced to at most 640x360 and approximately 15 FPS to limit CPU usage.
