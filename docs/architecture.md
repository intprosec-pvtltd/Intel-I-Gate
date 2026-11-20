# Architecture and invariants

FastAPI serves the API. One managed inference thread owns a single instance of each AI
model. Separate source-reader threads own killable FFmpeg processes. Each source has a
frame queue of capacity one. Live queues replace stale frames; video queues apply backpressure.
The inference thread cycles across sources. This is a single-process PoC, not distributed
worker orchestration. Do not increase Uvicorn process count to scale camera capacity.

YOLOv8m person detections feed a source-specific ByteTrack instance. Ultralytics' global
ID allocator is swapped with a source-local counter only inside the serialized inference
thread. References include source and session; reconnects use new camera epochs. Uploaded
video replay uses deterministic epochs. A camera-local track is never a permanent identity.

YuNet runs before selected-frame DINO inference. It detects actual faces independently of
delivery clues. Faces with ambiguous ownership among overlapping person boxes are rejected.
Size, sharpness, exposure, clipping, eye tilt, landmark symmetry and detection confidence
support best-so-far selection. Tilt/symmetry are pose proxies; no separate occlusion model
is claimed. Only real captured pixels become evidence. The image is not synthesized.

DINO uses configurable DELIVERY_PROMPTS. Object overlap must identify a unique owner.
Consecutive selected-frame hits can mark POSSIBLE_DELIVERY. Clothing, bags and parcels do
not establish occupation or purpose. Every observed person remains reviewable; the guard
can create a manual candidate when needed. A DINO inference failure preserves face results
and is exposed in worker metrics. Model-loading failure fails the AI worker explicitly.

Default DINO runs on CPU and GPU operations are serialized. INFERENCE_FPS is a sampling
target, not measured throughput. A slow DINO pass can reduce effective analysis speed while
the independent live decoder continues updating preview frames.

## Persistence

Twelve PostgreSQL entities separate users, cameras, residents, uploads, jobs, detections,
pending events, visits, snapshots, profiles, exit observations and audit logs.

Save Event locks the candidate row (`SELECT FOR UPDATE` on PostgreSQL), validates guard,
state and destination, creates a unique visit, approves the snapshot and records an audit
entry in one transaction. Duplicate requests return that visit. Verification alone never
creates a confirmed visit. Later AI frames cannot modify a confirmed candidate's snapshot.

Snapshot files are immutable and staged durably before their database reference is stored.
Approval changes a database flag instead of renaming a file during commit. Database failure
therefore cannot move a referenced file to an unexpected path. Unreferenced files receive
a cleanup grace period. Media is accessible only through authenticated endpoints.

The business transitions are:

```text
PENDING_VERIFICATION / NEEDS_REVIEW -> CONFIRMED (verify only)
PENDING_VERIFICATION / NEEDS_REVIEW / CONFIRMED -> ENTRY_RECORDED (Save Event)
PENDING_VERIFICATION / NEEDS_REVIEW / CONFIRMED -> NOT_DELIVERY / CANCELLED
ENTRY_RECORDED -> COMPLETED (guard confirms exit)
```

DETECTED and EXIT_DETECTED are represented by detection and exit-observation records.
These observations do not authorize entry or complete a visit automatically.

## Time, exits and identity

Wall-clock timestamps are UTC. Live captured_at means server receive/observation time;
this implementation does not extract camera capture clocks. Uploaded video times are
sampled relative seconds. Original dates are unknown. Manual reports have no fabricated
arrival timestamp. Saving/processing and observation timestamps remain distinct.
The UI displays configured timezone; date-range controls use browser-local time explicitly.

Crossing lines use normalized coordinates of the 960×540 letterboxed preview. A finite
line triggers negative-to-positive travel; reversing endpoints reverses direction. Track
disappearance never means exit. Same-session tracks and authorized SFace comparisons can
suggest associations. Every exit completion still requires a guard's confirmation.

BIOMETRIC_ENABLED defaults false. Enabling it is a deployment-level authorization choice
that allows transient encrypted embeddings. Permanent profile creation is a separate
admin action requiring authorization text and 1–90 day expiry. Saving an ordinary visit
never silently enrolls a profile. Uncertain matches remain unknown; thresholds require
calibration and the suggested identity is explicitly reviewable.

## Failure recovery and limits

FFmpeg reads have watchdog termination; reconnect delay is capped at 30 seconds. Stale
previews are unavailable after five seconds. The UI hides feeds when camera-update
WebSockets disconnect. Session expiry and logout revoke long-lived media access.
Startup marks unfinished jobs INTERRUPTED and clears old camera monitoring flags.
Operators restart the affected source after checking the cause.

No claim is made of reliable re-identification through long occlusions. A reacquired
person may form another pending candidate. Guard review is required for duplicates.
Metadata is retained separately from media; media retention does not erase audit history.
