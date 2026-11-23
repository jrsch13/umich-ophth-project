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
