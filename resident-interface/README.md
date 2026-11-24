# Resident Interface

The resident-facing React/Vite app provides these pages:

| Page | Purpose |
| --- | --- |
| Log In | Sign in with an invited resident account or a bootstrapped admin account. |
| Home | View the latest authorized session. Administrators can create invitation links. |
| New Session | Start and monitor a recording session. |
| Session Analysis | Browse saved sessions, metrics, and plots. |
| Cameras | Preview cameras and configure Side/Rear assignments. |

## Source guide

| Path | Responsibility |
| --- | --- |
| `src/App.jsx` | Page routes. |
| `src/components/` | Shared application shell and small display components. |
| `src/pages/` | Home, New Session, Session Analysis, and Cameras pages. |
| `src/auth.jsx`, `src/stationApi.js` | Identity from `/auth/me`, browser credentials, and the configurable API URL. |
| `src/styles.css` | Application styles. |
| `package.json` | Vite scripts and React dependencies. |

## Run and build

Set up the database and first administrator using the [station service instructions](../station-service/README.md). Start FastAPI separately, then run:

```powershell
npm.cmd ci
npm.cmd run dev -- --host 127.0.0.1
```

Open [the local station interface](http://127.0.0.1:5173). By default the browser calls the same host on port 8000. Set `VITE_STATION_API_URL` before starting Vite or building to override it. For a same-origin HTTPS deployment, one option is `VITE_STATION_API_URL=/api` with a reverse proxy forwarding `/api/*` to FastAPI without the prefix.

If port 5173 is in use, stop the other Vite instance or start Vite on a different port and set `AUTH_WEB_ORIGIN` to the matching address before restarting FastAPI. For local HTTP, use the same hostname in the browser and the API URL so the browser can send the session cookie.

Create a production bundle with:

```powershell
npm.cmd run build
```

The station-service owns physical cameras and recording. The UI reads session results from backend APIs; posture calculations run in Python, not React.

## Invite a resident for testing

1. Log in as the admin and open **Invite Users** on Home.
2. Enter a new test resident email and select **Create Invitation**, then **Copy Link**.
3. Open the link in a separate browser profile, confirm the invited email, set a password, and select **Create Account**. Log in with the new credentials.
4. Repeat with a second email to test data isolation. Each resident sees only their own saved sessions, and the admin table identifies the resident who owns each session.

## Develop with a demo Session Analysis recording

With the station-service virtual environment and React dependencies installed, run these commands from the repository root in one PowerShell terminal:

```powershell
cd station-service
.\.venv\Scripts\python.exe demo_session.py create
$env:AUTH_ALLOW_INSECURE_LOCAL_HTTP = "1"
.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000 --lifespan off
```

If the backend from this checkout is already running on port 8000, run `demo_session.py create` and refresh the session list.

In a second PowerShell terminal at the repository root, start React:

```powershell
cd resident-interface
npm.cmd run dev -- --host 127.0.0.1
```

Log in as an administrator, open [Session Analysis](http://127.0.0.1:5173/history), and select **DEMO — RULA UI Test**. Existing fixtures have no owner and appear only in the admin history. Select each posture card and click points on its time series to see the corresponding labeled demo frames.

The script creates an ignored local session with prewritten posture CSVs and synthetic video clips. It requires neither OpenPose nor a GPU. The `--lifespan off` launch option skips camera startup for this Session Analysis preview.

When finished, run this from `station-service/` and refresh Session Analysis:

```powershell
.\.venv\Scripts\python.exe demo_session.py remove
```
