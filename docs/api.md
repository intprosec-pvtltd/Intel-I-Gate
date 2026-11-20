# API reference

OpenAPI: `/openapi.json`; interactive schema: `/docs`.
The application factory is `app.main:create_app`.

Authentication uses an HttpOnly `intel_session` cookie. Browser mutations, including login,
require an exact ALLOWED_ORIGINS Origin and `X-Intel-Request: 1`. Axios sets the header
and credentials. Native preview media and WebSockets use the same cookie. No tokens are
placed in URLs. An external API client must supply the allowed Origin/header explicitly.

| Group | Routes |
|---|---|
| Auth | POST `/api/auth/login`, `/logout`; GET `/me` |
| Health | GET `/api/health`, `/api/system/status`, `/models`, `/inference` |
| Cameras | GET/POST `/api/cameras`; POST `/test`; GET/PUT/DELETE `/{id}` |
| Controls | POST `/api/cameras/{id}/start`, `/stop`, `/restart`; GET `/status`, `/preview` |
| Zones | PUT `/api/cameras/{id}/zones` |
| Residents | GET/POST `/api/residents` |
| Uploads | GET `/api/videos`; POST `/upload`; POST `/{id}/analyze`, `/cancel`; GET `/status`, `/results` |
| Candidates | GET `/api/events`, `/pending`, `/{id}`; POST `/manual` |
| Guard review | POST `/api/events/{id}/verify`, `/save`, `/reject`, `/review`, `/cancel`, `/complete` |
| Visits | GET `/api/visits?q=&status=&start=&end=&offset=0&limit=50` |
| Exits | GET `/api/exit-observations` |
| Images | GET/DELETE `/api/snapshots/{id}` |
| Enrollment | POST `/api/visits/{id}/enroll`; GET `/api/profiles`; DELETE `/api/profiles/{id}` |
| Users | GET/POST `/api/users`; POST `/api/users/{id}/disable` |
| Dashboard | GET `/api/dashboard/summary`, `/recent-events` |
| Audit | GET `/api/audit?offset=0` |
| WebSockets | `/ws/events`, `/ws/cameras` — authenticated current-state snapshots every 2 s |

Camera, resident and user mutations, profile access, audit access and image deletion require
admin. Guards can review/save visits, upload/analyze video, view authorized streams/history
and confirm exits. Residents can also be entered as verified names/flat numbers in a visit;
a referenced directory resident must match the supplied destination.

Save/verify body:

```json
{"delivery_confirmed":true,"flat":"A-101","resident_name":"Verified resident","resident_id":null,"company":"","notes":""}
```

Completion body:

```json
{"confirmed":true,"reason":"Guard saw visitor leave","observation_id":null}
```

Zones use optional arrays: `{"entry":[0.1,0.5,0.9,0.5],"exit":[0.9,0.5,0.1,0.5]}`.
Camera edit may omit the new RTSP URL to preserve encrypted configuration. Saved URLs,
password hashes, raw embeddings and storage paths are never returned.

Invalid sessions return 401; role failures 403; conflicting state/duplicates 409; invalid
fields 422; unavailable database/storage 503. Validation errors remove rejected input to
avoid echoing passwords or camera credentials. Lists use bounded pages. Video results
return up to 100 events and timeline entries per offset; the UI includes page controls.
