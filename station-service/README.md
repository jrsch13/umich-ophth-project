# Station Service

The local FastAPI backend handles camera discovery and assignment, persistent camera streams, session recording and metadata, OpenPose orchestration, posture analysis, and session APIs. It does not expose cameras directly to React; the service owns camera access.

## Setup and start

Run from PowerShell in `station-service/`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m alembic upgrade head
python -m auth.create_admin
$env:AUTH_ALLOW_INSECURE_LOCAL_HTTP = "1"
$env:OPENPOSE_BACKEND = "cpu" # Or "wsl" on an NVIDIA/WSL workstation.
python -m uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

Run `python -m auth.create_admin` once after migrating. It prompts for an email and a password of 12–128 characters with echo disabled. It refuses, without changing anything, if the database already has an administrator or an account for that email. Later account creation uses invitations. Apply `python -m alembic upgrade head` when upgrading the database schema.

Run `python -m auth.list_users` to see which identity database this machine uses and the accounts it holds (email, role, active/inactive, creation time). It never prints password hashes or tokens.

## Development databases

- Uvicorn, `auth.create_admin`, `auth.list_users`, invitations, Alembic, and tests all read one setting from `auth/config.py`. With `AUTH_DATABASE_URL` unset, that is `station-service/auth.sqlite3`, resolved from the code location, so the working directory does not matter. A relative SQLite path in `AUTH_DATABASE_URL` also resolves against `station-service/`.
- Local SQLite accounts are machine-specific. Creating an admin on Computer A does not create that user on Computer B. Login on B returns the generic `401 Invalid email or password.`
- Each development machine needs its own bootstrap admin: `python -m alembic upgrade head`, then `python -m auth.create_admin`. Reusing the same email is fine; it is a separate record with its own password hash.
- Never synchronize or commit credential databases through Git, OneDrive, or a network share. `auth.sqlite3*` is Git-ignored.
- Production, multiple stations, and the mobile app need one centralized API backed by one server database (for example, PostgreSQL through `AUTH_DATABASE_URL`) so every client authenticates against the same accounts.

The backend defaults to `cpu` when `OPENPOSE_BACKEND` is unset. Set `$env:OPENPOSE_BACKEND = "wsl"` for NVIDIA/WSL. The authenticated station interface can check readiness at `GET /openpose/status`. See [OpenPose setup](../openpose-pipeline/README.md) for installing either runtime.

The React interface runs separately from `resident-interface/` with `npm.cmd run dev -- --host 127.0.0.1`. Use `http://127.0.0.1:5173` for the default browser origin.

## Identity configuration

| Variable | Purpose |
| --- | --- |
| `AUTH_DATABASE_URL` | SQLAlchemy database URL for all identity data. Omit it to use the Git-ignored `station-service/auth.sqlite3`. For PostgreSQL install `psycopg[binary]`, set a `postgresql+psycopg://` URL in the environment, and run the same Alembic migrations. Keep database credentials out of Git and preserve user IDs when migrating data. |
| `AUTH_WEB_ORIGIN` | Trusted web origin for credentialed CORS, browser writes, and generated invitation links. Defaults to `http://127.0.0.1:5173`. Set it to the actual HTTPS frontend origin for a deployed station, or include the new port if you change the local Vite port. |
| `AUTH_ALLOW_INSECURE_LOCAL_HTTP` | Use `1` for local HTTP development on loopback. The backend accepts `127.0.0.1`, `localhost`, and `[::1]` on the configured frontend port in this mode. Leave it unset for deployment. |

Deploy the web app and API over HTTPS on the same site. Browser login sets a host-only, HttpOnly, SameSite=Strict cookie that expires after eight hours. HTTPS cookies have the `Secure` flag and a `__Host-` prefix. Browser mutations require the configured origin. The database stores hashes of random authentication and invitation tokens, so there is no application signing secret. Passwords use Argon2id. Login attempts are limited in memory per source IP, and a multi-worker deployment should use a shared limit at its gateway.

## Accounts and session ownership

- Log in with email and password. `GET /auth/me` returns ID, email, and role. Logging out revokes the current credential on the server.
- As an administrator, open **Invite Users** on Home, enter the resident's email, and copy the generated link to share privately. The link expires in 24 hours. The resident opens it, confirms the supplied email, sets a password, and logs in. There is no public signup form. An active account or a pending invitation for the same address returns a conflict.
- Start a New Session while logged in to create an owned recording. The recorder writes the logged-in user's ID to `owner_user_id` in `metadata.json`. Residents can list, open, and review only their own sessions. Administrators see all sessions and the owner's email when available. A legacy directory without an owner appears as **Unassigned** for administrators.
- To verify isolation, create two residents, record and save one session as each, and copy Resident B's Session Analysis URL while logged in as B. Log in as A in a separate browser profile. The list contains A's session and the direct URL for B's session returns `404` from the API. An administrator can open both.

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
| `session_access.py`, `session_catalog.py`, `session_analysis_data.py` | Ownership checks, session listing and details, and analysis data served to clients. |
| `auth/`, `migrations/` | Database-backed identity, invitations, and authentication sessions. |
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

- `POST /auth/login` accepts JSON with `email` and `password` and sets the browser cookie. It is the browser counterpart of the native `POST /auth/token`; both verify passwords with the same function against the same database and return the same generic 401. `POST /auth/logout` revokes the current browser or native credential.
- `POST /admin/invitations` creates a single-use resident invitation. The browser posts the token in JSON to `/auth/invitations/preview` and `/auth/invitations/accept`. Invitation links put the token in the URL fragment so it stays out of normal HTTP request URLs.
- `GET /cameras` reads the cached camera inventory; `POST /cameras/rescan` refreshes it. `GET`/`PUT /camera-config` reads or saves assignments.
- `POST /sessions/start` and `/sessions/stop` record a session; stop starts analysis in the background.
- `GET /sessions` and `/sessions/{session_id}` provide saved session history and details.
- `GET /sessions/{session_id}/analysis-status` reports progress.
- `POST /sessions/{session_id}/analyze` starts the full OpenPose pipeline. `POST /sessions/{session_id}/analysis/{view}/retry` reruns posture analysis from existing JSON without rerunning OpenPose.

## Native API and review media

An Expo client uses its configured HTTPS API URL and sends `POST /auth/token` with JSON `email` and `password`. It uses the returned `access_token` as `Authorization: Bearer <token>` for `GET /auth/me`, `GET /sessions`, session detail, analysis status, and metric time series. Tokens expire after one hour. Reauthenticate on expiry. Keep the token in memory or use platform-backed secure storage if persistence is needed. Call `POST /auth/logout` to revoke the token.

Native clients do not perform station camera or recording operations. Session detail returns `review_media_available: false` for native clients today. The workstation interface can still fetch selected frames and plots for authorized sessions while the local files are present. Raw and labeled video stay on the recording station. A shared service can centralize identities, ownership, summaries, and time series, then add optional compressed review uploads. The mobile UI should only show selected-frame controls when the API advertises accessible review media.

## Tests

From `station-service/`:

```powershell
python -m unittest discover
```

The API `TestClient` tests also require `httpx`, which is not included in the runtime requirements: install it in the development environment with `python -m pip install httpx`.
