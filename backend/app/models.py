from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import String, Text, DateTime, JSON, Float, Integer, Boolean, ForeignKey, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

def now(): return datetime.now(timezone.utc)
def uid(): return str(uuid4())
class Base(DeclarativeBase): pass
class Record:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

class User(Record, Base):
    __tablename__='users'
    apartment_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    email: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__=(CheckConstraint("role in ('admin','guard')"),)

class Camera(Record, Base):
    __tablename__='cameras'
    name: Mapped[str] = mapped_column(String(100), unique=True)
    location: Mapped[str] = mapped_column(String(160))
    purpose: Mapped[str] = mapped_column(String(30))
    rtsp_encrypted: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(40), default='STOPPED')
    error: Mapped[str | None] = mapped_column(String(200))
    zones: Mapped[dict] = mapped_column(JSON, default=dict)

class Resident(Record, Base):
    __tablename__='residents'
    name: Mapped[str] = mapped_column(String(120))
    flat: Mapped[str] = mapped_column(String(40), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    phone_encrypted: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default='0')
    __table_args__=(UniqueConstraint('name','flat'),)

class Video(Record, Base):
    __tablename__='video_uploads'
    test_role: Mapped[str | None] = mapped_column(String(10), nullable=True)
    __table_args__=(CheckConstraint("test_role IS NULL OR test_role IN ('entry','exit')",name='ck_video_test_role'),)
    filename: Mapped[str] = mapped_column(String(250))
    path: Mapped[str] = mapped_column(String(100), unique=True)
    size: Mapped[int] = mapped_column(Integer)
    duration: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(40), default='UPLOADED')

class Job(Record, Base):
    __tablename__='analysis_jobs'
    video_id: Mapped[str] = mapped_column(ForeignKey('video_uploads.id'), unique=True)
    status: Mapped[str] = mapped_column(String(40), default='QUEUED')
    progress: Mapped[float] = mapped_column(Float, default=0)
    error: Mapped[str | None] = mapped_column(String(200))

class Snapshot(Record, Base):
    __tablename__='snapshots'
    path: Mapped[str] = mapped_column(String(100), unique=True)
    quality: Mapped[float] = mapped_column(Float)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    embedding_encrypted: Mapped[str | None] = mapped_column(Text)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)

class Event(Record, Base):
    __tablename__='pending_events'
    camera_id: Mapped[str | None] = mapped_column(ForeignKey('cameras.id',ondelete='SET NULL'))
    video_id: Mapped[str | None] = mapped_column(ForeignKey('video_uploads.id',ondelete='SET NULL'))
    track_ref: Mapped[str] = mapped_column(String(160),unique=True)
    state: Mapped[str] = mapped_column(String(40), default='PENDING_VERIFICATION',index=True)
    candidate_status: Mapped[str] = mapped_column(String(40),default='NEEDS_REVIEW')
    evidence: Mapped[dict] = mapped_column(JSON,default=dict)
    snapshot_id: Mapped[str | None] = mapped_column(ForeignKey('snapshots.id',ondelete='SET NULL'))
    frame_seconds: Mapped[float | None] = mapped_column(Float)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification: Mapped[dict | None] = mapped_column(JSON)
    verified_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'))

class Visit(Record, Base):
    __tablename__='visits'
    event_id: Mapped[str] = mapped_column(ForeignKey('pending_events.id'),unique=True)
    resident_id: Mapped[str | None] = mapped_column(ForeignKey('residents.id',ondelete='SET NULL'))
    resident_name: Mapped[str] = mapped_column(String(120))
    flat: Mapped[str] = mapped_column(String(40),index=True)
    guard_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    company: Mapped[str] = mapped_column(String(120),default='')
    notes: Mapped[str] = mapped_column(Text,default='')
    entry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    historical: Mapped[bool] = mapped_column(Boolean,default=False)
    expected_exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40),default='ENTRY_RECORDED',index=True)

class VisitAlert(Record, Base):
    __tablename__='visit_alerts'
    visit_id: Mapped[str] = mapped_column(ForeignKey('visits.id',ondelete='CASCADE'),unique=True)
    state: Mapped[str] = mapped_column(String(20),default='OPEN')
    sms_state: Mapped[str] = mapped_column(String(30),default='PENDING')
    attempts: Mapped[int] = mapped_column(Integer,default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    token_digest: Mapped[str | None] = mapped_column(String(64),unique=True)
    token_encrypted: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    destination_digest: Mapped[str | None] = mapped_column(String(64))
    response: Mapped[str | None] = mapped_column(String(20))
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(160))

class FileDeletion(Record, Base):
    __tablename__='pending_file_deletions'
    path: Mapped[str] = mapped_column(String(100),unique=True)

class CleanupRun(Record, Base):
    __tablename__='cleanup_runs'
    counts: Mapped[dict] = mapped_column(JSON,default=dict)

class Detection(Record, Base):
    __tablename__='detections'
    source_key: Mapped[str] = mapped_column(String(100),index=True)
    track_ref: Mapped[str] = mapped_column(String(160),index=True)
    frame_seconds: Mapped[float] = mapped_column(Float)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence: Mapped[dict] = mapped_column(JSON)

class FaceProfile(Record, Base):
    __tablename__='visitor_face_profiles'
    visit_id: Mapped[str] = mapped_column(ForeignKey('visits.id'),unique=True)
    embedding_encrypted: Mapped[str] = mapped_column(Text)
    authorization: Mapped[str] = mapped_column(Text)
    authorized_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class ExitObservation(Record, Base):
    __tablename__='exit_observations'
    camera_id: Mapped[str | None] = mapped_column(ForeignKey('cameras.id'), nullable=True)
    video_id: Mapped[str | None] = mapped_column(ForeignKey('video_uploads.id'), nullable=True)
    track_ref: Mapped[str] = mapped_column(String(160),unique=True)
    visit_id: Mapped[str | None] = mapped_column(ForeignKey('visits.id'))
    evidence: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(40),default='NEEDS_REVIEW')

class Audit(Record, Base):
    __tablename__='event_audit_logs'
    actor_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    event_id: Mapped[str | None] = mapped_column(ForeignKey('pending_events.id',ondelete='SET NULL'))
    action: Mapped[str] = mapped_column(String(60))
    details: Mapped[dict] = mapped_column(JSON,default=dict)

class DeliveryOTP(Record, Base):
    __tablename__='delivery_otps'
    event_id: Mapped[str] = mapped_column(ForeignKey('pending_events.id',ondelete='CASCADE'),unique=True)
    resident_id: Mapped[str] = mapped_column(ForeignKey('residents.id'))
    requested_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    destination_digest: Mapped[str] = mapped_column(String(64))
    code_digest: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer,default=0)
    state: Mapped[str] = mapped_column(String(20),default='PENDING')

class OTPSend(Record, Base):
    __tablename__='otp_send_limits'
    recipient_digest: Mapped[str] = mapped_column(String(64),index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey('users.id'),index=True)


class ApartmentMapPoint(Record, Base):
    __tablename__='apartment_map_points'
    flat: Mapped[str] = mapped_column(String(40), unique=True)
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    __table_args__=(CheckConstraint('x >= 0 AND x <= 1', name='ck_map_point_x'), CheckConstraint('y >= 0 AND y <= 1', name='ck_map_point_y'))


class ResidentFace(Record, Base):
    __tablename__='resident_faces'
    resident_id: Mapped[str] = mapped_column(ForeignKey('residents.id',ondelete='CASCADE'),unique=True)
    snapshot_id: Mapped[str | None] = mapped_column(ForeignKey('snapshots.id',ondelete='SET NULL'))
    embedding_encrypted: Mapped[str | None] = mapped_column(Text)
    enrolled_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    active: Mapped[bool] = mapped_column(Boolean,default=True)
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)
