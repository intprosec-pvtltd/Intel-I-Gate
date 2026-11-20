# Verification report — 22 October 2026

This report covers the source package produced in this run. The earlier temporary
workspace was reset; current results below were executed against the rebuilt source.

## Executed checks

| Check | Actual result | Scope |
|---|---|---|
| Clean dependency installation | PASS | CPython 3.11.17, Linux; CPU PyTorch 2.6.0 |
| Dependency compatibility | PASS | `uv pip check`: all installed packages compatible |
| Python syntax/imports | PASS | Backend and scripts compile; all 12 ORM entities import |
| Backend API/service tests | 32 passed | Isolated SQLite fixtures, not PostgreSQL integration |
| Frontend component tests | 2 passed | Camera form and explicit guard-save behavior |
| React production build | PASS | Vite build of real JSX source |
| Frontend dependency audit | 0 known vulnerabilities returned | npm audit at execution time |
| Browser workflow | 1 passed | Real Chromium, FastAPI and Vite, isolated test database |
| Official model downloads | PASS | YuNet, SFace, YOLOv8m, Grounding DINO Tiny; SHA256 manifest |
| Five-component smoke inference | PASS | Actual weights; blank-image inference and ByteTrack update |
| Managed video AI integration | PASS | Public sample image encoded into a one-second static-video fixture |
| Positive face capture | PASS | Public OpenCV sample image; one usable face, JPEG and 128-value embedding |
| Desktop UI inspection | PASS | Security overview rendered at 1440×1000 |

The browser test covers login → manual candidate → delivery/destination verification →
explicit Save Event → visit history → page reload → guard exit confirmation → logout.
It confirms the connected guard workflow, not automatic detection accuracy or camera hardware.

The managed video test used the official Ultralytics bus.jpg repeated as a static video.
Actual models detected four person tracks and created four pending events. The selected
event was saved in an isolated database with idempotency verified. No face met the quality
criteria in that small/distant-person sample; the system preserved the missing-face state.
The test database was discarded. These are test observations, not apartment visit statistics.

A separate OpenCV sample-image test exercised actual positive face selection, encoded a
real face crop and generated a 128-dimensional SFace feature. It does not validate identity
matching, recognition thresholds, demographics, live camera quality, or enrollment authorization.

See `local-model-test.json`, `integrated-model-test.json` and `face-capture-test.json`
for the actual recorded outputs. CPU sample measurements were approximately 310 ms mean
YOLO, 34 ms YuNet/SFace branch, 4.16 s DINO, and 1.79 GB RSS in the two-frame video test.
The one-second fixture completed in 8.63 seconds including model initialization. These are
small CPU smoke measurements, not production throughput or a T400 benchmark.

Backend tests cover session access/revocation, guard/admin roles, CSRF origin checks,
camera IP/port restrictions, credential encryption/redaction, duplicate streams, invalid
uploads, path traversal, destination validation, terminal states, idempotent save,
transaction rollback, snapshot ownership, retention, historical occupancy and exit rules.

## Remaining acceptance gates

1. PostgreSQL 16 migration execution, actual row-lock concurrency, database failure,
   application restart and restore tests. This runtime has no available PostgreSQL service.
   Offline DDL generation is a syntax check only.
2. Execute the supplied PowerShell scripts on Windows 10/11, with actual PostgreSQL/FFmpeg
   paths and driver verification. Linux execution does not verify Windows commands.
3. Add an authorized real RTSP camera, verify genuine preview, timeouts, reconnects,
   stop/restart/deletion and behavior during network loss.
4. Use labeled apartment footage including couriers, ordinary residents, parcels,
   backpacks, helmets, multiple people and occlusions. Measure false candidates, missed
   deliveries, snapshot quality, ownership correctness and guard review workload.
5. Calibrate DINO prompts/thresholds and SFace match thresholds. Model scores are not
   calibrated probabilities of delivery purpose or identity correctness.
6. Benchmark NVIDIA T400 4 GB: driver/CUDA compatibility, VRAM/RAM, sustained inference,
   queueing, multi-camera throughput, long uploads and preview responsiveness.
7. Validate real entry/exit lines and authorized face suggestions. Lost tracks and uncertain
   matches must remain reviewable. No automatic identity-based exit closure is enabled.
8. Test Docker Compose, disk-full behavior, interruption/cancellation during inference,
   malformed media, retention recovery, backups, HTTPS and camera egress restrictions.
9. Complete deployment-specific privacy, biometric authorization and licensing review.

The complete end-to-end real-CCTV acceptance sequence is **not yet verified**. This source
package is an integrated development build for local verification, not a pilot-ready release.

## Phase status

| Prompt phase | Delivered implementation | Verification boundary |
|---|---|---|
| 1 Initialization | Project, JSX, Axios, dependencies, configuration | Frontend/API test servers start |
| 2 Database/auth | 12 entities, migration, auth, roles, health | SQLite service/API tests; PostgreSQL pending |
| 3 Camera management | Real RTSP test, CRUD, controls, MJPEG, zones | API controls tested; physical camera pending |
| 4 Models | Downloader, revision/hash manifest, real weights | Five-component smoke inference passed |
| 5 Detection/tracking | YOLOv8m and per-source ByteTrack | Actual public sample-video inference passed |
| 6 Delivery clues | Selected-frame DINO, association, candidate accumulation | Executes; site accuracy/calibration pending |
| 7 Face snapshot | YuNet quality selection, protected crop, missing-face handling | Positive real-image capture passed |
| 8 Guard workflow | Verify, explicit save, history, atomic promotion | API/browser and rollback tests passed |
| 9 Uploads | FFprobe validation, bounded decode/job/cancel/results | Actual managed video job passed |
| 10 Identity/exits | Opt-in profiles, suggestions, lines, guard completion | Service rules tested; real cross-camera tests pending |
| 11 Performance | Sampling, queues, serialized models, measurements | Small CPU tests only; T400 pending |
| 12 Deployment | Tests, Windows scripts, Docker, documentation | Linux tests passed; Windows/Docker/site gates pending |

## Reproduce

Use README commands. Run tests in a dedicated test installation. Do not create automated
test visitors in an occupied building's operational database. Model checks intentionally
report what they measured; they do not fabricate detections when a model or input is missing.
