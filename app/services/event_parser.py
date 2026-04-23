"""
Parse raw Twilio Event Streams payloads into database model instances.

All field access uses .get() with safe fallbacks so that Twilio schema
additions or renames do not crash ingestion — the raw_payload column
always preserves the original event for replay.
"""

from datetime import datetime, timezone
from app.extensions import db
from app.models import CallLog, ConferenceLog, ConferenceParticipantLog


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
