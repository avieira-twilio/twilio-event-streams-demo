from datetime import datetime, timezone
from app.extensions import db


def _now():
    return datetime.now(timezone.utc)


class CallLog(db.Model):
    __tablename__ = "call_logs"

    id = db.Column(db.Integer, primary_key=True)
    account_sid = db.Column(db.String(34), nullable=False, index=True)
    call_sid = db.Column(db.String(34), unique=True, nullable=False)
    status = db.Column(db.String(20))          # completed, failed, busy, no-answer, canceled
    direction = db.Column(db.String(10))        # inbound, outbound-api, outbound-dial
    from_number = db.Column(db.String(20))
    to_number = db.Column(db.String(20))
    duration_seconds = db.Column(db.Integer)
    started_at = db.Column(db.DateTime, index=True)
    ended_at = db.Column(db.DateTime)
    error_code = db.Column(db.String(10))       # Nullable; present on error events
    raw_payload = db.Column(db.JSON)            # Full original event for schema resilience
    received_at = db.Column(db.DateTime, default=_now)

    def to_dict(self):
        return {
            "id": self.id,
            "account_sid": self.account_sid,
            "call_sid": self.call_sid,
            "status": self.status,
            "direction": self.direction,
            "from_number": self.from_number,
            "to_number": self.to_number,
            "duration_seconds": self.duration_seconds,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "error_code": self.error_code,
            "received_at": self.received_at.isoformat() if self.received_at else None,
        }


class ConferenceLog(db.Model):
    __tablename__ = "conference_logs"

    id = db.Column(db.Integer, primary_key=True)
    account_sid = db.Column(db.String(34), nullable=False, index=True)
    conference_sid = db.Column(db.String(34), unique=True, nullable=False)
    friendly_name = db.Column(db.String(255))
    status = db.Column(db.String(20))
    participant_count = db.Column(db.Integer)
    duration_seconds = db.Column(db.Integer)
    started_at = db.Column(db.DateTime, index=True)
    ended_at = db.Column(db.DateTime)
    raw_payload = db.Column(db.JSON)
    received_at = db.Column(db.DateTime, default=_now)

    participants = db.relationship(
        "ConferenceParticipantLog",
        backref="conference",
        lazy="dynamic",
        foreign_keys="ConferenceParticipantLog.conference_sid",
        primaryjoin="ConferenceLog.conference_sid == ConferenceParticipantLog.conference_sid",
    )

    def to_dict(self):
        return {
            "id": self.id,
            "account_sid": self.account_sid,
            "conference_sid": self.conference_sid,
            "friendly_name": self.friendly_name,
            "status": self.status,
            "participant_count": self.participant_count,
            "duration_seconds": self.duration_seconds,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "received_at": self.received_at.isoformat() if self.received_at else None,
        }


class ConferenceParticipantLog(db.Model):
    __tablename__ = "conference_participant_logs"

    id = db.Column(db.Integer, primary_key=True)
    conference_sid = db.Column(db.String(34), nullable=False, index=True)
    account_sid = db.Column(db.String(34), nullable=False, index=True)
    call_sid = db.Column(db.String(34))
    duration_seconds = db.Column(db.Integer)
    coaching = db.Column(db.Boolean, default=False)
    raw_payload = db.Column(db.JSON)
    received_at = db.Column(db.DateTime, default=_now)

    def to_dict(self):
        return {
            "id": self.id,
            "conference_sid": self.conference_sid,
            "account_sid": self.account_sid,
            "call_sid": self.call_sid,
            "duration_seconds": self.duration_seconds,
            "coaching": self.coaching,
            "received_at": self.received_at.isoformat() if self.received_at else None,
        }


class RecordingLog(db.Model):
    """Audio recording metadata, supporting both Twilio and S3 storage."""
    __tablename__ = "recording_logs"

    id = db.Column(db.Integer, primary_key=True)
    account_sid = db.Column(db.String(34), nullable=False, index=True)
    recording_sid = db.Column(db.String(34), unique=True, nullable=False)
    call_sid = db.Column(db.String(34), index=True)  # links back to call_logs
    status = db.Column(db.String(20))                # completed, failed, absent
    duration_seconds = db.Column(db.Integer)
    channels = db.Column(db.Integer, default=1)      # 1=mono, 2=dual-channel
    source = db.Column(db.String(20))                # twilio, s3
    twilio_url = db.Column(db.String(512))           # Twilio media URL (always stored)
    s3_url = db.Column(db.String(512))               # S3 object URL (if uploaded)
    s3_key = db.Column(db.String(512))               # S3 object key
    recorded_at = db.Column(db.DateTime, index=True)
    raw_payload = db.Column(db.JSON)
    received_at = db.Column(db.DateTime, default=_now)

    def to_dict(self):
        return {
            "id": self.id,
            "account_sid": self.account_sid,
            "recording_sid": self.recording_sid,
            "call_sid": self.call_sid,
            "status": self.status,
            "duration_seconds": self.duration_seconds,
            "channels": self.channels,
            "source": self.source,
            "twilio_url": self.twilio_url,
            "s3_url": self.s3_url,
            "recorded_at": self.recorded_at.isoformat() if self.recorded_at else None,
            "received_at": self.received_at.isoformat() if self.received_at else None,
        }


class RawEventLog(db.Model):
    """Dead-letter queue and audit log for every received event."""
    __tablename__ = "raw_event_log"

    id = db.Column(db.Integer, primary_key=True)
    # X-Twilio-Event-Id header — gaps in sequence indicate dropped events
    event_id = db.Column(db.String(64), index=True)
    event_type = db.Column(db.String(100))
    account_sid = db.Column(db.String(34), index=True)
    payload = db.Column(db.JSON)
    processed = db.Column(db.Boolean, default=False, nullable=False)
    received_at = db.Column(db.DateTime, default=_now, index=True)
