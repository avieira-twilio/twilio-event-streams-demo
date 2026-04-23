"""
Parse raw Twilio Event Streams payloads into database model instances.

All field access uses .get() with safe fallbacks so that Twilio schema
additions or renames do not crash ingestion — the raw_payload column
always preserves the original event for replay.
"""

from datetime import datetime, timezone
from flask import current_app
from app.extensions import db
from app.models import CallLog, ConferenceLog, ConferenceParticipantLog, RecordingLog


def _parse_dt(value):
    """Parse an ISO 8601 string to a UTC-aware datetime, or return None."""
    if not value:
        return None
    try:
        # Handle both Z-suffix and +00:00 forms
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_event(payload: dict, event_type: str):
    """Dispatch to the appropriate parser based on event_type."""
    handlers = {
        # Call summary events
        "com.twilio.voice.insights.call-summary.complete": _parse_call_summary,
        "com.twilio.voice.insights.call-summary.partial": _parse_call_summary,
        "com.twilio.voice.insights.call-summary.predicted-complete": _parse_call_summary,
        # Conference events
        "com.twilio.voice.insights.conference-summary.complete": _parse_conference_summary,
        "com.twilio.voice.insights.conference-summary.partial": _parse_conference_summary,
        "com.twilio.voice.insights.conference-participant-summary.complete": _parse_conference_participant,
        # Recording events
        "com.twilio.voice.status-callback.recording.processed": _parse_recording,
        # Legacy short names (seed data / older subscriptions)
        "voice.insights.call-summary.complete": _parse_call_summary,
        "voice.insights.call-summary.error": _parse_call_summary,
        "insights.conference.summary": _parse_conference_summary,
        "insights.conference.participant-summary": _parse_conference_participant,
    }
    handler = handlers.get(event_type)
    if handler:
        handler(payload)


def _parse_call_summary(payload: dict):
    """Upsert a CallLog from a voice.insights.call-summary.* event."""
    # Twilio nests the actual call data under a "payload" sub-key in some versions.
    # Support both flat and nested structures.
    data = payload.get("payload") or payload

    call_sid = data.get("CallSid") or data.get("call_sid")
    if not call_sid:
        return

    account_sid = (
        data.get("AccountSid")
        or data.get("account_sid")
        or payload.get("AccountSid", "unknown")
    )

    existing = CallLog.query.filter_by(call_sid=call_sid).first()
    if existing is None:
        existing = CallLog(call_sid=call_sid)
        db.session.add(existing)

    existing.account_sid = account_sid
    existing.status = data.get("CallStatus") or data.get("call_status")
    existing.direction = data.get("Direction") or data.get("direction")
    existing.from_number = data.get("From") or data.get("from")
    existing.to_number = data.get("To") or data.get("to")
    existing.duration_seconds = _parse_int(
        data.get("Duration") or data.get("duration")
    )
    existing.started_at = _parse_dt(
        data.get("StartTime") or data.get("start_time")
    )
    existing.ended_at = _parse_dt(
        data.get("EndTime") or data.get("end_time")
    )
    existing.error_code = str(data.get("ErrorCode") or data.get("error_code") or "")
    existing.raw_payload = payload


def _parse_conference_summary(payload: dict):
    """Upsert a ConferenceLog from an insights.conference.summary event."""
    data = payload.get("payload") or payload

    conference_sid = data.get("ConferenceSid") or data.get("conference_sid")
    if not conference_sid:
        return

    account_sid = (
        data.get("AccountSid")
        or data.get("account_sid")
        or payload.get("AccountSid", "unknown")
    )

    existing = ConferenceLog.query.filter_by(conference_sid=conference_sid).first()
    if existing is None:
        existing = ConferenceLog(conference_sid=conference_sid)
        db.session.add(existing)

    existing.account_sid = account_sid
    existing.friendly_name = data.get("FriendlyName") or data.get("friendly_name")
    existing.status = data.get("Status") or data.get("status")
    existing.participant_count = _parse_int(
        data.get("MaxParticipants") or data.get("max_participants")
    )
    existing.duration_seconds = _parse_int(
        data.get("Duration") or data.get("duration")
    )
    existing.started_at = _parse_dt(
        data.get("DateCreated") or data.get("date_created")
    )
    existing.ended_at = _parse_dt(
        data.get("DateUpdated") or data.get("date_updated")
    )
    existing.raw_payload = payload


def _parse_conference_participant(payload: dict):
    """Insert a ConferenceParticipantLog from an insights.conference.participant-summary event."""
    data = payload.get("payload") or payload

    conference_sid = data.get("ConferenceSid") or data.get("conference_sid")
    call_sid = data.get("CallSid") or data.get("call_sid")
    if not conference_sid:
        return

    account_sid = (
        data.get("AccountSid")
        or data.get("account_sid")
        or payload.get("AccountSid", "unknown")
    )

    # Avoid duplicating participant rows on replay
    existing = ConferenceParticipantLog.query.filter_by(
        conference_sid=conference_sid, call_sid=call_sid
    ).first()
    if existing is None:
        existing = ConferenceParticipantLog(
            conference_sid=conference_sid, call_sid=call_sid
        )
        db.session.add(existing)

    existing.account_sid = account_sid
    existing.duration_seconds = _parse_int(
        data.get("Duration") or data.get("duration")
    )
    existing.coaching = bool(data.get("Coaching") or data.get("coaching"))
    existing.raw_payload = payload


def _parse_recording(payload: dict):
    """
    Upsert a RecordingLog from a com.twilio.voice.status-callback.recording.processed event.
    If S3 is configured, copies the audio file to S3 and stores both URLs.
    """
    data = payload.get("data") or payload.get("payload") or payload

    recording_sid = data.get("RecordingSid") or data.get("recording_sid")
    if not recording_sid:
        return

    account_sid = (
        data.get("AccountSid")
        or data.get("account_sid")
        or payload.get("AccountSid", "unknown")
    )
    call_sid = data.get("CallSid") or data.get("call_sid")

    # Twilio recording URL — append .mp3 for direct audio streaming
    twilio_url = data.get("RecordingUrl") or data.get("recording_url") or ""
    if twilio_url and not twilio_url.endswith(".mp3"):
        twilio_url = twilio_url + ".mp3"

    existing = RecordingLog.query.filter_by(recording_sid=recording_sid).first()
    if existing is None:
        existing = RecordingLog(recording_sid=recording_sid)
        db.session.add(existing)

    existing.account_sid = account_sid
    existing.call_sid = call_sid
    existing.status = data.get("RecordingStatus") or data.get("recording_status") or "completed"
    existing.duration_seconds = _parse_int(
        data.get("RecordingDuration") or data.get("recording_duration")
    )
    existing.channels = _parse_int(
        data.get("RecordingChannels") or data.get("recording_channels")
    ) or 1
    existing.twilio_url = twilio_url
    existing.recorded_at = _parse_dt(
        data.get("RecordingStartTime") or data.get("recording_start_time")
        or data.get("DateCreated") or data.get("date_created")
    )
    existing.raw_payload = payload

    # Attempt S3 upload if configured
    try:
        from app.services.s3_handler import upload_recording, s3_enabled
        if s3_enabled() and twilio_url:
            auth_token = current_app.config.get("TWILIO_AUTH_TOKEN", "")
            s3_url, s3_key = upload_recording(recording_sid, twilio_url, account_sid, auth_token)
            if s3_url:
                existing.s3_url = s3_url
                existing.s3_key = s3_key
                existing.source = "s3"
            else:
                existing.source = "twilio"
        else:
            existing.source = "twilio"
    except Exception as e:
        current_app.logger.error("S3 upload failed for recording %s: %s", recording_sid, e)
        existing.source = "twilio"
