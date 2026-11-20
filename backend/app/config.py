from pathlib import Path
from typing import Literal
from pydantic import SecretStr
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
ROOT = Path(__file__).resolve().parents[1]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT/'.env', extra='ignore')
    database_url: str = 'postgresql+psycopg://intel_mini:CHANGE_ME@localhost:5432/intel_mini'
    secret_key: str = Field(min_length=32)
    encryption_key: str
    allowed_origins: str = 'http://localhost:5173,http://127.0.0.1:5173'
    cookie_secure: bool = False
    session_hours: int = Field(default=8, ge=1, le=24)
    camera_allow_cidrs: str = ''
    camera_ports: str = '554,8554'
    storage_dir: Path = ROOT/'storage'
    model_dir: Path = ROOT/'ai_models'
    ai_enabled: bool = True
    device: str = 'cpu'
    dino_device: str = 'cpu'
    inference_fps: float = Field(default=5, ge=.2, le=10)
    preview_fps: int = Field(default=25, ge=1, le=30)
    max_sources: int = Field(default=4, ge=1, le=16)
    dino_interval: float = Field(default=3, ge=1)
    delivery_min_span: float = Field(default=2, ge=1, le=30)
    delivery_window: float = Field(default=15, ge=3, le=120)
    delivery_result_ttl: float = Field(default=15, ge=1, le=60)
    overlay_ttl: float = Field(default=1, ge=.2, le=3)
    max_preview_peers: int = Field(default=4, ge=1, le=8)
    delivery_threshold: float = Field(default=.5, ge=.05, le=1)
    delivery_hits: int = Field(default=3, ge=3, le=10)
    delivery_prompts: str = 'delivery backpack. food delivery bag. insulated delivery bag. courier bag. parcel. cardboard delivery box. courier package. delivery uniform. person holding a delivery package. person carrying a delivery backpack.'
    face_min_size: int = Field(default=40, ge=20)
    biometric_enabled: bool = False
    face_match_threshold: float = Field(default=.55, ge=0, le=1)
    resident_recognition_enabled: bool = True
    resident_match_threshold: float = Field(default=0.85,ge=0.5,le=1.0)
    resident_match_margin: float = Field(default=0.20,ge=0.05,le=1.0)
    public_app_url: str = ''
    visit_response_hours: int = Field(default=24,ge=1,le=72)
    maintenance_interval_seconds: int = Field(default=30,ge=10,le=300)
    orphan_grace_minutes: int = Field(default=10,ge=5,le=1440)
    calendar_cleanup_enabled: bool = True
    auto_exit_fast_enabled: bool = True
    auto_exit_fast_threshold: float = Field(default=.85,ge=.8,le=1)
    auto_exit_fast_margin: float = Field(default=.20,ge=.15,le=.8)
    auto_exit_enabled: bool = False
    auto_test_exit_enabled: bool = False
    auto_exit_threshold: float = Field(default=.65,ge=.5,le=1)
    auto_exit_margin: float = Field(default=.10,ge=.05,le=.5)
    auto_exit_confirmations: int = Field(default=3,ge=3,le=10)
    auto_exit_min_span: float = Field(default=1,ge=.5,le=10)
    auto_exit_window: float = Field(default=10,ge=2,le=60)
    auto_exit_min_entry_seconds: float = Field(default=15,ge=1,le=300)
    auto_exit_max_frame_age: float = Field(default=3,ge=.5,le=10)
    max_upload_mb: int = Field(default=1024, ge=1)
    retention_days: int = Field(default=30, ge=1)
    temporary_hours: int = Field(default=24, ge=1)
    timezone: str = 'Asia/Kolkata'
    sms_provider: Literal['disabled','twilio'] = 'disabled'
    twilio_account_sid: str = ''
    twilio_auth_token: SecretStr = SecretStr('')
    twilio_from_number: str = ''
    twilio_messaging_service_sid: str = ''
    otp_expiry_seconds: int = Field(default=300,ge=60,le=600)
    otp_resend_seconds: int = Field(default=60,ge=30,le=300)
    otp_max_attempts: int = Field(default=5,ge=3,le=10)
    otp_recipient_hourly_limit: int = Field(default=5,ge=1,le=20)
    otp_guard_hourly_limit: int = Field(default=30,ge=1,le=100)
    ffmpeg: str = 'ffmpeg' 
    ffprobe: str = 'ffprobe'

    @model_validator(mode='after')
    def validate_configuration(self):
        from cryptography.fernet import Fernet
        from zoneinfo import ZoneInfo
        Fernet(self.encryption_key.encode())
        ZoneInfo(self.timezone)
        if (self.auto_exit_enabled or self.auto_test_exit_enabled) and not self.biometric_enabled:
            raise ValueError('Automatic face exits require BIOMETRIC_ENABLED=true')
        if self.auto_exit_min_span>self.auto_exit_window:
            raise ValueError('Automatic exit evidence span must fit inside its window')
        if self.delivery_min_span > self.delivery_window:
            raise ValueError('Delivery evidence span must fit inside its window')
        if not self.database_url.startswith('postgresql'):
            raise ValueError('Production requires PostgreSQL; tests inject an isolated engine')
        if self.public_app_url:
            from urllib.parse import urlsplit
            u=urlsplit(self.public_app_url)
            if u.scheme!='https' or not u.hostname or u.username or u.password or u.query or u.fragment or u.path not in ('','/'):
                raise ValueError('PUBLIC_APP_URL must be an HTTPS origin without credentials, path, query or fragment')
        return self

    @property
    def origins(self):
        return [x.strip() for x in self.allowed_origins.split(',') if x.strip()]
