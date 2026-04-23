"""
Seed the database with synthetic call, conference, and recording events for demo purposes.

Usage (from project root, with venv active):
    python scripts/seed_demo_data.py

This script bypasses Twilio signature validation and inserts data directly
into the database. Never run against a production database.

Generates:
  - 200 call events spread across 3 fake subaccounts over the last 30 days
  - 50 conference events across the same subaccounts
  - 40 recording events linked to completed calls
  - All events are written to raw_event_log (processed=True) and to the
    normalized domain tables (call_logs, conference_logs, recording_logs).
"""

import os
import sys
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Allow running from repo root or scripts/ directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

os.environ.setdefault("FLASK_ENV", "development")
os.environ.setdefault("SKIP_SIGNATURE_VALIDATION", "true")

from app import create_app
from app.extensions import db
from app.models import CallLog, ConferenceLog, RawEventLog, RecordingLog

# ---------------------------------------------------------------------------
# Fake subaccount SIDs (resembling real Twilio SIDs for demo realism)
# ---------------------------------------------------------------------------
SUBACCOUNTS = [
    "ACaaaabbbbcccc00001111222233334444",
    "ACaaaabbbbcccc00001111222233335555",
    "ACaaaabbbbcccc00001111222233336666",
]

STATUSES = ["completed", "completed", "completed", "failed", "busy", "no-answer"]
DIRECTIONS = ["inbound", "outbound-api"]
PHONE_NUMBERS = [
    "+15005550001", "+15005550002", "+15005550003",
    "+15005550004", "+15005550005", "+15005550006",
]
CONF_NAMES = [
    "Weekly Standup", "Sales Call", "Support Bridge",
    "Executive Briefing", "Team Sync", "Incident Bridge",
]


def random_dt(days_ago_max=30):
    delta = timedelta(
        days=random.randint(0, days_ago_max),
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59),
    )
    return datetime.now(timezone.utc) - delta


def seed_calls(n=200):
    print(f"Seeding {n} call records…")
    for i in range(n):
        account_sid = random.choice(SUBACCOUNTS)
        call_sid = f"CA{i:032d}"
        status = random.choice(STATUSES)
        direction = random.choice(DIRECTIONS)
        started = random_dt()
        duration = random.randint(5, 600) if status == "completed" else 0
        ended = started + timedelta(seconds=duration)
        error_code = "30007" if status == "failed" else None

        payload = {
            "type": "voice.insights.call-summary.complete",
            "AccountSid": account_sid,
            "CallSid": call_sid,
            "CallStatus": status,
            "Direction": direction,
            "From": random.choice(PHONE_NUMBERS),
            "To": random.choice(PHONE_NUMBERS),
            "Duration": str(duration),
            "StartTime": started.isoformat(),
            "EndTime": ended.isoformat(),
            "ErrorCode": error_code,
        }

        raw = RawEventLog(
            event_id=f"EVseed{i:016d}",
            event_type=payload["type"],
            account_sid=account_sid,
            payload=payload,
            processed=True,
            received_at=started,
        )
        db.session.add(raw)

        call = CallLog(
            account_sid=account_sid,
            call_sid=call_sid,
            status=status,
            direction=direction,
            from_number=payload["From"],
            to_number=payload["To"],
            duration_seconds=duration,
            started_at=started,
            ended_at=ended,
            error_code=error_code,
            raw_payload=payload,
            received_at=started,
        )
        db.session.add(call)

    db.session.commit()
    print("  Done.")


def seed_conferences(n=50):
    print(f"Seeding {n} conference records…")
    for i in range(n):
        account_sid = random.choice(SUBACCOUNTS)
        conf_sid = f"CF{i:032d}"
        started = random_dt()
        duration = random.randint(60, 3600)
        ended = started + timedelta(seconds=duration)
        participants = random.randint(2, 8)

        payload = {
            "type": "insights.conference.summary",
            "AccountSid": account_sid,
            "ConferenceSid": conf_sid,
            "FriendlyName": random.choice(CONF_NAMES),
            "Status": "completed",
            "MaxParticipants": str(participants),
            "Duration": str(duration),
            "DateCreated": started.isoformat(),
            "DateUpdated": ended.isoformat(),
        }

        raw = RawEventLog(
            event_id=f"EVseedconf{i:012d}",
            event_type=payload["type"],
            account_sid=account_sid,
            payload=payload,
            processed=True,
            received_at=started,
        )
        db.session.add(raw)

        conf = ConferenceLog(
            account_sid=account_sid,
            conference_sid=conf_sid,
            friendly_name=payload["FriendlyName"],
            status="completed",
            participant_count=participants,
            duration_seconds=duration,
            started_at=started,
            ended_at=ended,
            raw_payload=payload,
            received_at=started,
        )
        db.session.add(conf)

    db.session.commit()
    print("  Done.")


def seed_recordings(n=40):
    """Seed n fake recording rows linked to existing completed calls."""
    print(f"Seeding {n} recording records…")
    completed_calls = CallLog.query.filter_by(status="completed").limit(n).all()
    for i, call in enumerate(completed_calls):
        rec_sid = f"RE{i:032d}"
        duration = random.randint(5, call.duration_seconds or 30)
        channels = random.choice([1, 1, 1, 2])  # mostly mono

        payload = {
            "type": "com.twilio.voice.status-callback.recording.processed",
            "AccountSid": call.account_sid,
            "RecordingSid": rec_sid,
            "CallSid": call.call_sid,
            "RecordingStatus": "completed",
            "RecordingDuration": str(duration),
            "RecordingChannels": str(channels),
            # Fake Twilio URL (won't play in demo — no real auth)
            "RecordingUrl": f"https://api.twilio.com/2010-04-01/Accounts/{call.account_sid}/Recordings/{rec_sid}.mp3",
            "RecordingStartTime": call.started_at.isoformat() if call.started_at else None,
        }

        raw = RawEventLog(
            event_id=f"EVsedrec{i:013d}",
            event_type=payload["type"],
            account_sid=call.account_sid,
            payload=payload,
            processed=True,
            received_at=call.started_at,
        )
        db.session.add(raw)

        rec = RecordingLog(
            account_sid=call.account_sid,
            recording_sid=rec_sid,
            call_sid=call.call_sid,
            status="completed",
            duration_seconds=duration,
            channels=channels,
            source="twilio",
            twilio_url=payload["RecordingUrl"],
            recorded_at=call.started_at,
            raw_payload=payload,
            received_at=call.started_at,
        )
        db.session.add(rec)

    db.session.commit()
    print("  Done.")


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        seed_calls(200)
        seed_conferences(50)
        seed_recordings(40)
    print("\nSeeding complete. Run `flask run` and visit http://localhost:5000")
