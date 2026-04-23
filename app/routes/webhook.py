"""
POST /webhook/events

Receives Twilio Event Streams HTTP POST events. Every event is:
  1. Signature-validated against the configured Auth Token.
  2. Logged to raw_event_log (processed=False).
  3. Parsed into the appropriate domain table (call_logs, conference_logs, etc.).
  4. Marked processed=True on success; left False on parse failure (dead-letter queue).

Auth Token note:
  - If your Event Streams subscription is on the master account, set TWILIO_AUTH_TOKEN
    to the MASTER account's auth token.
  - If each subaccount has its own subscription, you would need to look up the correct
    auth token per AccountSid in the event — for this demo we use one token.
"""

from flask import Blueprint, request, jsonify, current_app
from twilio.request_validator import RequestValidator

from app.extensions import db
from app.models import RawEventLog
from app.services.event_parser import parse_event

webhook_bp = Blueprint("webhook", __name__)


@webhook_bp.post("/webhook/events")
def receive_event():
    # --- Signature validation ---
    skip = current_app.config.get("SKIP_SIGNATURE_VALIDATION", False)
    if not skip:
        validator = RequestValidator(current_app.config["TWILIO_AUTH_TOKEN"])
        sig = request.headers.get("X-Twilio-Signature", "")
        body = request.get_data(as_text=True)
        if not validator.validate(request.url, body, sig):
            current_app.logger.warning(
                "Rejected event: invalid Twilio signature from %s", request.remote_addr
            )
            return jsonify({"error": "Invalid signature"}), 403

    payload = request.get_json(force=True, silent=True) or {}
    event_type = payload.get("type", "unknown")
    account_sid = payload.get("AccountSid", "unknown")
    event_id = request.headers.get("X-Twilio-Event-Id", "")

    raw = RawEventLog(
        event_id=event_id,
        event_type=event_type,
        account_sid=account_sid,
        payload=payload,
        processed=False,
    )
    db.session.add(raw)
    db.session.flush()  # Assign raw.id before parse so FK is available if needed

    try:
        parse_event(payload, event_type)
        raw.processed = True
    except Exception as exc:
        current_app.logger.error(
            "Parse failed for event_id=%s type=%s: %s", event_id, event_type, exc
        )

    db.session.commit()
    return jsonify({"status": "ok"}), 200
