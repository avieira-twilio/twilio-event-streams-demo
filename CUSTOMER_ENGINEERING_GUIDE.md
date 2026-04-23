# Subaccount-Level Call & Conference Log Access
## Using Twilio Event Streams as a Workaround

**Audience:** Customer Engineering  
**Use case:** Customers who need read-only visibility into call/conference logs at the subaccount level

---

## The Problem

Twilio Console does not support granting read-only access to call or conference logs at the subaccount level.

This is a real and common ask. Typical scenarios:

- A customer runs one subaccount per client. A client wants to log in and see their own call history — but the customer cannot give them Console access without also giving them the ability to modify settings, buy numbers, and change configurations.
- An internal analyst needs to audit call volume and error rates across subaccounts without having admin rights.
- A manager needs a read-only view scoped to their team's subaccount.

**There is no native Twilio Console permission that solves this today.** Console access is all-or-nothing at the account level.

---

## The Recommended Workaround: Event Streams

Twilio Support's recommendation is to use **Twilio Event Streams** to export call and conference data in real time to a custom webhook, then build a read-only visualization layer on top.

### How it works

```
Twilio Account / Subaccounts
        │
        │  Voice Insights events fire after each call/conference completes
        │  (com.twilio.voice.insights.call-summary.complete, etc.)
        ▼
Event Streams Subscription
        │
        │  HTTP POST  (CloudEvents 1.0 format, JSON array)
        ▼
Your Webhook  →  Database  →  Read-only Dashboard
```

Every event payload includes an `account_sid` field identifying which subaccount the call or conference originated from. This is the key that enables subaccount-level filtering.

---

## Key Concepts to Explain to the Customer

### 1. What is Event Streams?

Event Streams is a Twilio product that lets you subscribe to real-time events from your account and push them to a destination (webhook, Kinesis, Segment, etc.). It supports 100+ event types across Voice, Messaging, Video, TaskRouter, and more.

For this use case, the relevant event types are:

| Event Type | Fires When |
|---|---|
| `com.twilio.voice.insights.call-summary.complete` | A call completes and Voice Insights finishes processing |
| `com.twilio.voice.insights.call-summary.partial` | A partial summary is available (faster, less complete) |
| `com.twilio.voice.insights.conference-summary.complete` | A conference ends |
| `com.twilio.voice.insights.conference-participant-summary.complete` | A conference participant disconnects |

### 2. Event payload structure (CloudEvents 1.0)

Twilio Event Streams uses the CloudEvents spec. Each POST is a JSON array of event objects:

```json
[
  {
    "specversion": "1.0",
    "type": "com.twilio.voice.insights.call-summary.complete",
    "source": "/v1/Voice/CAxxxxx/Summary",
    "id": "EZxxxxx",
    "time": "2026-04-23T02:08:35.000Z",
    "data": {
      "call_sid": "CAxxxxx",
      "account_sid": "ACxxxxx",
      "call_state": "completed",
      "duration": 45,
      "start_time": "2026-04-23T02:07:50Z",
      "end_time": "2026-04-23T02:08:35Z",
      "properties": {
        "direction": "outbound_api"
      },
      "from": { "caller": "+15551234567" },
      "to":   { "callee":  "+15559876543" }
    }
  }
]
```

Important fields:
- `data.account_sid` — identifies the subaccount
- `data.call_sid` — the Call SID for cross-referencing with the REST API
- `data.call_state` — final status of the call
- `data.duration` — call duration in seconds

### 3. Subscription scope: master account vs. subaccount

**Option A — Master account subscription (recommended for this use case)**

Create one subscription on the master account. It receives events from the master account and all its subaccounts. The `account_sid` in each event tells you which subaccount it came from.

This is the simplest setup: one subscription, one webhook, all data in one place.

**Option B — Per-subaccount subscriptions**

Create a separate subscription on each subaccount using that subaccount's credentials. More granular control, but more operational overhead.

For the read-only access use case, Option A is almost always the right choice.

### 4. Signature validation

Twilio signs every webhook request with an HMAC-SHA1 signature using the account's Auth Token. Always validate this on your webhook receiver. The signature is in the `X-Twilio-Signature` header.

Use the Auth Token of the account that owns the subscription (master account for Option A).

---

## Implementation Overview

### Step 1: Create a Sink (the destination)

```python
from twilio.rest import Client

client = Client(MASTER_ACCOUNT_SID, MASTER_AUTH_TOKEN)

sink = client.events.v1.sinks.create(
    description="Call & Conference Log Dashboard",
    sink_configuration={
        "destination": "https://your-app.com/webhook/events",
        "method": "POST",
        "batch_events": False,
    },
    sink_type="webhook",
)
print(sink.sid)  # DGxxxxx — save this
```

### Step 2: Create a Subscription

```python
subscription = client.events.v1.subscriptions.create(
    description="Voice Insights — Subaccount Dashboard",
    sink_sid=sink.sid,
    types=[
        {"type": "com.twilio.voice.insights.call-summary.complete"},
        {"type": "com.twilio.voice.insights.call-summary.partial"},
        {"type": "com.twilio.voice.insights.conference-summary.complete"},
        {"type": "com.twilio.voice.insights.conference-participant-summary.complete"},
    ],
)
print(subscription.sid)  # DFxxxxx
```

### Step 3: Webhook receiver (Python/Flask example)

```python
from flask import request, jsonify
from twilio.request_validator import RequestValidator

@app.post("/webhook/events")
def receive_event():
    # Validate signature
    validator = RequestValidator(MASTER_AUTH_TOKEN)
    if not validator.validate(request.url, request.get_data(as_text=True),
                              request.headers.get("X-Twilio-Signature", "")):
        return jsonify({"error": "Forbidden"}), 403

    # Parse CloudEvents array
    for event in request.get_json(force=True) or []:
        event_type = event.get("type")
        data = event.get("data", {})
        account_sid = data.get("account_sid")   # which subaccount
        call_sid    = data.get("call_sid")
        status      = data.get("call_state")
        duration    = data.get("duration")
        # ... store in database

    return jsonify({"status": "ok"}), 200
```

### Step 4: Store with subaccount granularity

Minimum recommended schema:

```sql
CREATE TABLE call_logs (
    call_sid        VARCHAR(34) PRIMARY KEY,
    account_sid     VARCHAR(34) NOT NULL,   -- subaccount identifier
    status          VARCHAR(20),
    direction       VARCHAR(20),
    from_number     VARCHAR(20),
    to_number       VARCHAR(20),
    duration_seconds INTEGER,
    started_at      TIMESTAMP,
    raw_payload     JSONB                   -- store full event for replay
);

CREATE INDEX idx_call_logs_account_sid ON call_logs (account_sid);
CREATE INDEX idx_call_logs_started_at  ON call_logs (started_at);
```

The `raw_payload` column is important — storing the full original event means you can re-parse it if your schema changes, without losing any data.

### Step 5: Read-only dashboard

The dashboard queries the database filtered by `account_sid`. Because this is your own application layer, you control access completely:

- Give each client a login scoped to their `account_sid`
- They can only see their own data
- They have zero ability to modify Twilio settings

---

## What to Show the Customer

### The core message

> "Because Twilio Console doesn't have a native read-only subaccount view, we use Twilio's own Event Streams product to stream your call and conference data into a lightweight app. Everything is tagged by subaccount. You control exactly who sees what, and they can never touch your Twilio configuration."

### Key points to hit

1. **Event Streams is a first-party Twilio product** — this is not a workaround that could break; it's the supported integration path.
2. **Data arrives in real time** — within ~60 seconds of a call completing, Voice Insights fires the event.
3. **The `account_sid` field is the key** — every event includes it, so subaccount-level filtering is trivial.
4. **You own the access layer** — role-based access, SSO, audit logs — all possible because it's your app.
5. **Full event history is preserved** — the raw payload is stored, so even if Twilio adds new fields later, you don't lose old data.

---

## Common Customer Questions

**"How long does it take for events to arrive?"**
Voice Insights `partial` events arrive within ~30 seconds of call completion. `complete` events follow within a few minutes once full quality metrics are processed.

**"What if my webhook is down and I miss events?"**
Twilio retries failed webhook deliveries. Additionally, storing the raw `X-Twilio-Event-Id` header allows you to detect gaps in the event sequence. For critical use cases, cross-reference periodically against the Twilio REST API (`client.calls.list()`).

**"Does this work for inbound calls too?"**
Yes. The `direction` field in the event payload distinguishes `inbound`, `outbound_api`, and `outbound_dial`.

**"Can I filter by date, status, or duration?"**
Yes — those fields are all in the `data` object of every event. Store them as indexed columns and filter at query time.

**"Does Event Streams cost extra?"**
Event Streams itself is free to set up. Voice Insights Advanced features have associated costs — check the current pricing page. For basic call summaries, costs are minimal.

**"Can I use this for conferences too?"**
Yes — `com.twilio.voice.insights.conference-summary.complete` and `conference-participant-summary.complete` provide the same coverage for conference calls.

---

## Resources

- Event Streams overview: https://www.twilio.com/docs/events
- Voice Insights event types: https://www.twilio.com/docs/voice/insights/api/call-summary-resource
- CloudEvents spec: https://cloudevents.io
- Twilio error 20409 (event type not found): https://www.twilio.com/docs/errors/20409
