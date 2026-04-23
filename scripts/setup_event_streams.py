"""
One-time Twilio Event Streams setup script.

Creates a Sink (webhook) and a Subscription (Voice Insights + Conference
Insights event types) for one Twilio account/subaccount.

Usage:
    python scripts/setup_event_streams.py \
        --account-sid ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx \
        --auth-token  your_auth_token \
        --webhook-url https://your-domain.com/webhook/events

Run once per subaccount that should feed data into the dashboard.

To use with ngrok for local testing:
    ngrok http 5000
    # Copy the HTTPS forwarding URL, then:
    python scripts/setup_event_streams.py \
        --account-sid AC... --auth-token ... \
        --webhook-url https://abc123.ngrok.io/webhook/events
"""

import argparse
from twilio.rest import Client


EVENT_TYPES = [
    {"type": "voice.insights.call-summary.complete"},
    {"type": "voice.insights.call-summary.error"},
    {"type": "insights.conference.summary"},
    {"type": "insights.conference.participant-summary"},
]


def setup(account_sid: str, auth_token: str, webhook_url: str):
    client = Client(account_sid, auth_token)

    print(f"Creating Sink → {webhook_url}")
    sink = client.events.sinks.create(
        description="Twilio Event Streams Demo Dashboard",
        sink_configuration={
            "destination": webhook_url,
            "method": "POST",
            "batch_events": False,
        },
        sink_type="webhook",
    )
    print(f"  Sink SID: {sink.sid}  Status: {sink.status}")

    print("Creating Subscription…")
    subscription = client.events.subscriptions.create(
        description="Call and Conference Logs — Demo Dashboard",
        sink_sid=sink.sid,
        types=EVENT_TYPES,
    )
    print(f"  Subscription SID: {subscription.sid}")
    print("\nDone. Events will start flowing after the next call/conference on this account.")
    print("To verify, check the raw_event_log table or GET /api/health.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Set up Twilio Event Streams for the demo dashboard.")
    parser.add_argument("--account-sid", required=True, help="Twilio Account or Subaccount SID")
    parser.add_argument("--auth-token", required=True, help="Auth Token for the account")
    parser.add_argument("--webhook-url", required=True, help="Public HTTPS URL of /webhook/events")
    args = parser.parse_args()

    setup(args.account_sid, args.auth_token, args.webhook_url)
