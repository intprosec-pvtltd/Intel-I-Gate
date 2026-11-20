# Deployment, security and operations

## Windows development

Use the README setup and migration commands. Keep one Uvicorn worker. API binds to
127.0.0.1 and Vite proxies same-origin API/media/WebSocket requests. The Windows scripts
check native command exit codes, preserve an existing .env and never overwrite passwords.
They must still be executed on the target Windows installation before being considered verified.

## Linux Docker Compose

Docker is optional. Install models on the host first. Create backend/.env using
scripts/configure.py. Create a separate root `.env` with a strong URL-safe password:

```dotenv
POSTGRES_PASSWORD=YOUR_LONG_RANDOM_URL_SAFE_PASSWORD
```

Use a URL-safe generated password for this Compose template, because it is interpolated
into a PostgreSQL URL. Then:

```bash
docker compose up --build -d
docker compose exec backend python /srv/scripts/create_admin.py
```

Open http://localhost:8080. Compose runs PostgreSQL 16, migrates before API startup,
persists the database and media in named volumes, and mounts model assets read-only.
The provided Docker image is CPU-only. GPU Docker requires NVIDIA Container Toolkit,
a compatible CUDA PyTorch build and tested GPU configuration; no GPU deployment is claimed.

For remote deployment, terminate HTTPS, set COOKIE_SECURE=true and exact ALLOWED_ORIGINS,
and update the frontend proxy/origin configuration. Do not expose development servers or
unauthenticated RTSP/media ports publicly. Restrict OS access to database, storage and keys.
FFmpeg may expose process arguments to the local OS account; restrict that account's access.

## Network controls

Camera targets are literal allowlisted IPs and approved RTSP ports. Loopback, link-local,
multicast, reserved addresses, hostnames and arbitrary URL schemes are rejected. FFmpeg's
protocol list is restricted. A pilot deployment should also enforce egress firewall rules
to the exact cameras: an RTSP server can redirect or advertise other network targets.
Validate redirect/network behavior on the actual camera models before pilot acceptance.

## Retention and deletion

RETENTION_DAYS controls approved snapshot/upload media (default 30 days).
TEMPORARY_HOURS controls unsaved candidate media (default 24 hours). Profiles have their
own explicit expiry. Cleanup runs at startup and hourly, tombstones records before unlinking,
and sweeps orphaned files after a 24-hour grace period. Event metadata and audits remain;
choose and implement an appropriate metadata-retention policy before deployment.
DELETE snapshot/profile APIs require admin; profile deletion is exposed in Settings.

Biometric matching is disabled by default. Confirm authorization/privacy requirements
before enabling processing with real people. Permanent enrollment is separate from
ordinary visit saving. Define who can review footage, retention, deletion requests and
resident verification procedures before the controlled pilot.

## Backup and restore

Back up PostgreSQL with pg_dump, the storage directory/volume, backend/.env and its
encryption key, and docs/model-lock.json. Keep keys in a separate protected backup.
Loss of the encryption key prevents recovery of camera URLs and biometric embeddings.
Test restore into a separate database and storage copy. Stop monitoring before maintenance.

Review Ultralytics' AGPL/commercial licensing and model/dependency licenses before
commercial distribution. Sources: https://www.ultralytics.com/license and
https://github.com/opencv/opencv_zoo and https://huggingface.co/IDEA-Research/grounding-dino-tiny.

The implementation is a development PoC. Real CCTV, PostgreSQL concurrency/restart,
Windows execution, Docker startup and T400 load tests are required acceptance gates.
