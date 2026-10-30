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
- `GET /camera-config` returns the current saved station configuration
- `PUT /camera-config` saves the Side and Rear camera assignments

The runtime config is stored in `station-service/camera_config.json`. An example config is provided in `camera_config.example.json`.
