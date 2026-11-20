BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 0001

CREATE TABLE cameras (
    name VARCHAR(100) NOT NULL, 
    location VARCHAR(160) NOT NULL, 
    purpose VARCHAR(30) NOT NULL, 
    rtsp_encrypted TEXT NOT NULL, 
    fingerprint VARCHAR(64) NOT NULL, 
    enabled BOOLEAN NOT NULL, 
    status VARCHAR(40) NOT NULL, 
    error VARCHAR(200), 
    zones JSON NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (fingerprint), 
    UNIQUE (name)
);

CREATE INDEX ix_cameras_created_at ON cameras (created_at);

CREATE TABLE detections (
    source_key VARCHAR(100) NOT NULL, 
    track_ref VARCHAR(160) NOT NULL, 
    frame_seconds FLOAT NOT NULL, 
    captured_at TIMESTAMP WITH TIME ZONE, 
    evidence JSON NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id)
);

CREATE INDEX ix_detections_created_at ON detections (created_at);

CREATE INDEX ix_detections_source_key ON detections (source_key);

CREATE INDEX ix_detections_track_ref ON detections (track_ref);

CREATE TABLE residents (
    name VARCHAR(120) NOT NULL, 
    flat VARCHAR(40) NOT NULL, 
    active BOOLEAN NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (name, flat)
);

CREATE INDEX ix_residents_created_at ON residents (created_at);

CREATE INDEX ix_residents_flat ON residents (flat);

CREATE TABLE snapshots (
    path VARCHAR(100) NOT NULL, 
    quality FLOAT NOT NULL, 
    metrics JSON NOT NULL, 
    embedding_encrypted TEXT, 
    approved BOOLEAN NOT NULL, 
    deleted BOOLEAN NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (path)
);

CREATE INDEX ix_snapshots_created_at ON snapshots (created_at);

CREATE TABLE users (
    username VARCHAR(100) NOT NULL, 
    password_hash TEXT NOT NULL, 
    role VARCHAR(20) NOT NULL, 
    active BOOLEAN NOT NULL, 
    token_version INTEGER NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    CHECK (role in ('admin','guard')), 
    UNIQUE (username)
);

CREATE INDEX ix_users_created_at ON users (created_at);

CREATE TABLE video_uploads (
    filename VARCHAR(250) NOT NULL, 
    path VARCHAR(100) NOT NULL, 
    size INTEGER NOT NULL, 
    duration FLOAT NOT NULL, 
    status VARCHAR(40) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (path)
);

CREATE INDEX ix_video_uploads_created_at ON video_uploads (created_at);

CREATE TABLE analysis_jobs (
    video_id VARCHAR(36) NOT NULL, 
    status VARCHAR(40) NOT NULL, 
    progress FLOAT NOT NULL, 
    error VARCHAR(200), 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(video_id) REFERENCES video_uploads (id), 
    UNIQUE (video_id)
);

CREATE INDEX ix_analysis_jobs_created_at ON analysis_jobs (created_at);

CREATE TABLE pending_events (
    camera_id VARCHAR(36), 
    video_id VARCHAR(36), 
    track_ref VARCHAR(160) NOT NULL, 
    state VARCHAR(40) NOT NULL, 
    candidate_status VARCHAR(40) NOT NULL, 
    evidence JSON NOT NULL, 
    snapshot_id VARCHAR(36), 
    frame_seconds FLOAT, 
    captured_at TIMESTAMP WITH TIME ZONE, 
    verification JSON, 
    verified_by VARCHAR(36), 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(camera_id) REFERENCES cameras (id) ON DELETE SET NULL, 
    FOREIGN KEY(snapshot_id) REFERENCES snapshots (id) ON DELETE SET NULL, 
    FOREIGN KEY(verified_by) REFERENCES users (id), 
    FOREIGN KEY(video_id) REFERENCES video_uploads (id) ON DELETE SET NULL, 
    UNIQUE (track_ref)
);

CREATE INDEX ix_pending_events_created_at ON pending_events (created_at);

CREATE INDEX ix_pending_events_state ON pending_events (state);

CREATE TABLE event_audit_logs (
    actor_id VARCHAR(36), 
    event_id VARCHAR(36), 
    action VARCHAR(60) NOT NULL, 
    details JSON NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(actor_id) REFERENCES users (id), 
    FOREIGN KEY(event_id) REFERENCES pending_events (id) ON DELETE SET NULL
);

CREATE INDEX ix_event_audit_logs_created_at ON event_audit_logs (created_at);

CREATE TABLE visits (
    event_id VARCHAR(36) NOT NULL, 
    resident_id VARCHAR(36), 
    resident_name VARCHAR(120) NOT NULL, 
    flat VARCHAR(40) NOT NULL, 
    guard_id VARCHAR(36) NOT NULL, 
    company VARCHAR(120) NOT NULL, 
    notes TEXT NOT NULL, 
    entry_at TIMESTAMP WITH TIME ZONE, 
    exit_at TIMESTAMP WITH TIME ZONE, 
    historical BOOLEAN NOT NULL, 
    status VARCHAR(40) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(event_id) REFERENCES pending_events (id), 
    FOREIGN KEY(guard_id) REFERENCES users (id), 
    FOREIGN KEY(resident_id) REFERENCES residents (id) ON DELETE SET NULL, 
    UNIQUE (event_id)
);

CREATE INDEX ix_visits_created_at ON visits (created_at);

CREATE INDEX ix_visits_flat ON visits (flat);

CREATE INDEX ix_visits_status ON visits (status);

CREATE TABLE exit_observations (
    camera_id VARCHAR(36) NOT NULL, 
    track_ref VARCHAR(160) NOT NULL, 
    visit_id VARCHAR(36), 
    evidence JSON NOT NULL, 
    state VARCHAR(40) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(camera_id) REFERENCES cameras (id), 
    FOREIGN KEY(visit_id) REFERENCES visits (id), 
    UNIQUE (track_ref)
);

CREATE INDEX ix_exit_observations_created_at ON exit_observations (created_at);

CREATE TABLE visitor_face_profiles (
    visit_id VARCHAR(36) NOT NULL, 
    embedding_encrypted TEXT NOT NULL, 
    "authorization" TEXT NOT NULL, 
    authorized_by VARCHAR(36) NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(authorized_by) REFERENCES users (id), 
    FOREIGN KEY(visit_id) REFERENCES visits (id), 
    UNIQUE (visit_id)
);

CREATE INDEX ix_visitor_face_profiles_created_at ON visitor_face_profiles (created_at);

INSERT INTO alembic_version (version_num) VALUES ('0001') RETURNING alembic_version.version_num;

COMMIT;

