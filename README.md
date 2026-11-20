# INTEL-I Mini

An independent apartment delivery-monitoring application built from scratch using
React + JavaScript JSX, Axios, FastAPI, PostgreSQL 16, YOLOv8m, Grounding DINO Tiny,
ByteTrack, YuNet and SFace.

**Development build. Real-site acceptance and NVIDIA T400 benchmarks remain required.**
The application contains no seeded operational detections, cameras, visitor records,
face snapshots, or default production credentials. See `docs/testing.md` for actual results.

## Included workflow

Live CCTV / uploaded video → person detection + tracking → delivery clues and independent
automatic face selection → pending event → guard confirms delivery purpose and destination
→ explicit Save Event → persistent visit history → reviewable exit observation / guard exit confirmation.

The frontend includes login, dashboard, live cameras, camera management, video analysis,
delivery verification, visit history and administrator settings. Settings includes resident
and user creation, user disabling, profile deletion, and actual model/worker status.

## Windows installation

Install Python **3.11**, Node.js **22.12+**, PostgreSQL **16**, Git, and FFmpeg including
FFprobe. Add `py`, `node`, `npm`, `psql`, `git`, `ffmpeg`, and `ffprobe` to PATH.
Extract the project folder to a new location, for example:

```text
C:\Users\selva\OneDrive\Desktop\INTEL-I-Mini
```

Open PowerShell in that project folder:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\scripts\setup_windows.ps1 -TorchBuild cpu
```

For the NVIDIA T400, inspect the installed driver first:

```powershell
nvidia-smi
.\scripts\setup_windows.ps1 -TorchBuild cu124
```

The CUDA installation checks `torch.cuda.is_available()` and prints the actual GPU.
The script creates a fresh `.venv`, installs pinned direct dependencies, builds React,
creates local secrets and downloads the official model assets. Model binaries are
downloaded on your PC; they are excluded from the source ZIP. Expect roughly 0.8 GB
of checkpoint downloads plus Python/Node dependencies. No empty checkpoint files are supplied.

## PostgreSQL setup

```powershell
psql -U postgres
```

At the database prompt:

```sql
CREATE ROLE intel_mini LOGIN;
\password intel_mini
CREATE DATABASE intel_mini OWNER intel_mini;
\q
```

Choose your own database password. Edit the generated environment:

```powershell
notepad .\backend\.env
```

Set your actual connection details and camera allowlist:

```dotenv
DATABASE_URL=postgresql+psycopg://intel_mini:YOUR_URL_ENCODED_PASSWORD@localhost:5432/intel_mini
CAMERA_ALLOW_CIDRS=192.168.1.50/32,192.168.1.51/32
DEVICE=cpu
DINO_DEVICE=cpu
```

Percent-encode special characters in database passwords used in URLs (`@` → `%40`).
Replace the example camera IPs with your camera IPs. Empty `CAMERA_ALLOW_CIDRS` denies
all camera targets. Literal private LAN IPs work when explicitly allowlisted; hostnames
and arbitrary protocols are rejected. Add an approved RTSP port to `CAMERA_PORTS` if required.

After CUDA verification, you can set `DEVICE=cuda:0`. Start with `DINO_DEVICE=cpu`
on the T400's 4 GB VRAM, then measure your footage. This conservative configuration
does not guarantee real-time inference. Keep inference and preview FPS separate.

Create the schema and your admin account:

```powershell
Push-Location .\backend
& ..\.venv\Scripts\python.exe -m alembic upgrade head
Pop-Location
& .\.venv\Scripts\python.exe .\scripts\verify_postgres.py
& .\.venv\Scripts\python.exe .\scripts\create_admin.py
```

Expected database verification: `PASS PostgreSQL 16... schema revision 0001 tables 12`.
The admin command prompts locally for credentials. No password is supplied in the project.

## Start

First PowerShell window:

```powershell
.\scripts\start_backend.ps1
```

Second PowerShell window:

```powershell
.\scripts\start_frontend.ps1
```

Open **http://localhost:5173**. API schema: **http://127.0.0.1:8000/docs**.
Use **one backend worker**. The local managed AI worker and camera ownership are
in-process; multiple Uvicorn workers would duplicate them.

The Vite proxy makes API, WebSocket and MJPEG access same-origin with the frontend.
JavaScript HTTP calls use Axios exclusively. Native `<img>` MJPEG rendering is
authenticated browser media access. Do not pass an RTSP URL to a browser video element.

## First real workflow

1. Sign in as admin. Add guards and residents in Settings if needed.
2. Add a camera with Camera Name, Location/Purpose and RTSP URL. No separate camera
   username or password fields are used. Credential-bearing RTSP input is protected;
   saved URLs are encrypted and never returned by APIs.
3. Test Connection, Save Camera, then Start Monitoring. Confirm actual live frames and
   model status. If AI fails, the status must report the error.
4. Review an observed person in Delivery Verification. The best adequate face is captured
   automatically. If no face qualifies, the UI explicitly requires guard review.
5. Confirm delivery purpose and destination flat/resident. Confirm Delivery validates the
   review; **Save Event** creates the visit. Repeated saves return the same visit.
6. Check Visit History, reload, and restart the application to verify PostgreSQL persistence.
7. Stop the camera to configure normalized entry/exit lines. Restart monitoring.
8. Review exit observations and confirm the correct visitor's exit. Lost tracks and face
   similarity alone never close a visit.

Use Manual candidate when a delivery visitor is missed. No face or capture time is invented.
Use Video Analysis for recorded footage, then Start Analysis after validation. Historical
footage shows relative seconds and does not inflate live occupancy. Without a trustworthy
original date, the application blocks completing historical visits using today's exit time.

## Tests and model checks

```powershell
& .\.venv\Scripts\python.exe -m pip check
& .\.venv\Scripts\python.exe -m pytest .\backend\tests -q
.\scripts\test_models.ps1
.\scripts\test_models.ps1 -Video 'C:\path\to\authorized-test-video.mp4'
Push-Location .\frontend
npm test
npm run build
npm audit
npx playwright install chromium
Pop-Location
```

For a browser integration test, stop normal development servers first:

```powershell
& .\.venv\Scripts\python.exe .\scripts\run_browser_tests.py
```

The helper uses an explicitly isolated SQLite test fixture. The production configuration
always requires PostgreSQL. The test creates a temporary account/database, launches both
servers, verifies a manual guard workflow, then removes the temporary database. For testing
against a dedicated PostgreSQL test installation, set `E2E_USERNAME`, `E2E_PASSWORD` and
`E2E_BASE_URL` and run `npm run test:e2e` against that installation.

## Documentation

- `docs/architecture.md`: inference, state transitions, persistence and time handling.
- `docs/api.md`: endpoints, permissions, pagination and client authentication.
- `docs/testing.md`: executed checks, limitations and remaining acceptance tests.
- `docs/deployment.md`: Docker, privacy controls, retention and backups.
- `docs/model-lock.json`: immutable model revisions and SHA256 checksums.

Model confidence thresholds require site-specific calibration. Review Ultralytics and
other dependency/model licensing before proprietary commercial distribution.
