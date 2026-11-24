# Ergonomic Training Station for Ophthalmology

This project records ophthalmology training sessions from configured Side and Rear/rear-oblique cameras, runs OpenPose BODY_25, and derives posture measures for training feedback. Residents can review completed sessions and ergonomic exposure in the React interface. The measures are research heuristics, not a validated clinical injury-risk score.

## Pipeline

```text
Resident session → camera recording → OpenPose BODY_25
                 → posture analysis → Session Analysis
```

The current measures are neck flexion/extension, forward trunk lean, lateral trunk lean, and shoulder hiking. The Side view supplies the first two; the Rear view supplies the latter two.

## Quick start

Start the backend in one PowerShell window:

```powershell
cd station-service
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m alembic upgrade head
python -m auth.create_admin # Run once, then use Invite Users to register residents.
$env:AUTH_ALLOW_INSECURE_LOCAL_HTTP = "1"
$env:OPENPOSE_BACKEND = "wsl" # Use "cpu" for the Windows CPU backend.
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

For the Windows CPU fallback, use `$env:OPENPOSE_BACKEND = "cpu"` instead.

OpenPose must be installed separately. See [OpenPose setup](./openpose-pipeline/README.md).

Start the interface in another window:

```powershell
cd resident-interface
npm.cmd ci
npm.cmd run dev -- --host 127.0.0.1
```

Open [the station interface](http://127.0.0.1:5173) and log in. Residents register with an invitation from an administrator. The backend saves the signed-in owner's ID on new recordings. Administrators can see legacy recordings under **Unassigned**. See the [station setup and mobile API notes](./station-service/README.md) for database and HTTPS configuration.

## Interface

| Page | Use |
| --- | --- |
| Home | View the latest authorized session summary. Administrators can invite residents. |
| New Session | Select the session label and record using the configured cameras. |
| Session Analysis | Browse saved sessions, posture metrics, plots, and analysis status. |
| Cameras | Preview cameras and configure or rescan Side and Rear assignments. |

## Repository map

| Path | Contents |
| --- | --- |
| `station-service/` | Local FastAPI service for cameras, recording, OpenPose orchestration, posture analysis, and session APIs. |
| `resident-interface/` | React/Vite resident-facing interface. |
| `openpose-pipeline/` | Windows CPU and WSL/NVIDIA wrappers and installation instructions. |
| `anipose-pipeline-v1/`–`anipose-pipeline-v3/` | Earlier DeepLabCut/Anipose experiments and outputs; not part of the current station workflow. |
| `data/` | Local source research videos; see [data/README.md](./data/README.md). |
| `models/` | Local DeepLabCut baseline project and model files; ignored by Git. |
| `requirements.txt` | Root-level dependencies for the earlier Anipose/DeepLabCut experiments. |
| `setup_baseline_model.py` | Earlier DeepLabCut baseline setup helper with workstation-specific paths. |
| `testing.ipynb` | Small OpenCV check that opens a sample `.MOV` video and reports its frame properties. |
| `.gitignore` | Excludes local videos, models, OpenPose assets, and generated outputs. |

## Remaining Work

### Resident mobile application

Build the React Native app on the authenticated identity, session list, and analysis endpoints. A shared deployment will need HTTPS and a central session catalog. Review media stays on the recording station until a separate upload workflow exists.
