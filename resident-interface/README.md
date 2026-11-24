# Resident Interface

The resident-facing React/Vite app provides these pages:

| Page | Purpose |
| --- | --- |
| Home | Entry page for the station. |
| New Session | Start and monitor a recording session. |
| Session Analysis | Browse saved sessions, metrics, and plots. |
| Cameras | Preview cameras and configure Side/Rear assignments. |

## Source guide

| Path | Responsibility |
| --- | --- |
| `src/App.jsx` | Page routes. |
| `src/components/` | Shared application shell and small display components. |
| `src/pages/` | Home, New Session, Session Analysis, and Cameras pages. |
| `src/stationApi.js` | Station-service request helper and base URL (`http://127.0.0.1:8000`). |
| `src/styles.css` | Application styles. |
| `package.json` | Vite scripts and React dependencies. |

## Run and build

Start the FastAPI station-service separately, then run:

```powershell
npm install
npm run dev
```

Vite normally serves the app at `http://localhost:5173`. Create a production bundle with:

```powershell
npm run build
```

The station-service owns physical cameras and recording. The UI reads session results from backend APIs; posture calculations run in Python, not React.

## Develop with a demo Session Analysis recording

With the station-service virtual environment and React dependencies installed, run these commands from the repository root in one PowerShell terminal:

```powershell
cd station-service
.\.venv\Scripts\python.exe demo_session.py create
.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000 --lifespan off
```

If the backend from this checkout is already running on port 8000, run `demo_session.py create` and refresh the session list.

In a second PowerShell terminal at the repository root, start React:

```powershell
cd resident-interface
npm.cmd run dev -- --host 127.0.0.1
```

Open [Session Analysis](http://127.0.0.1:5173/history) and select **DEMO — RULA UI Test**. Select each posture card and click points on its time series to see the corresponding labeled demo frames.

The script creates an ignored local session with prewritten posture CSVs and synthetic video clips. It requires neither OpenPose nor a GPU. The `--lifespan off` launch option skips camera startup for this Session Analysis preview.

When finished, run this from `station-service/` and refresh Session Analysis:

```powershell
.\.venv\Scripts\python.exe demo_session.py remove
```
