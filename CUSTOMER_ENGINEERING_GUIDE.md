# Subaccount-Level Call & Conference Log Access
## Using Twilio Event Streams — Customer Engineering Guide

**Audience:** Twilio Customer Engineering  
**Use case:** Customers who need read-only, subaccount-scoped visibility into call logs, conference logs, and audio recordings

---

## The Problem

Twilio Console does not support granting read-only access to call or conference logs at the subaccount level.

This is a common and real customer ask. Typical scenarios:

- A customer runs one subaccount per client. A client wants to log in and see their own call history — but handing them Console access also gives them the ability to modify numbers, settings, and billing.
- An internal analyst needs to audit call volume and error rates across subaccounts without admin rights.
- A compliance team needs an audit trail of all calls and recordings, scoped to a specific business unit's subaccount.
- A manager needs a read-only dashboard for their team without any configuration access.

**There is no native Twilio Console permission that solves this today.** Console access is all-or-nothing at the account level.

---

## The Recommended Solution: Event Streams

Twilio's recommended approach is to use **Twilio Event Streams** to export call and conference data in real time to a webhook, store it in a custom database, and build a read-only visualization layer on top.

This is not a workaround — Event Streams is a first-party Twilio product designed for exactly this type of data export use case.

### How it works

```
Twilio Account / Subaccounts
        │
        │  After each call/conference/recording completes:
        │  Voice Insights fires a CloudEvents 1.0 payload
        │  to your registered webhook URL
        ▼
Event Streams Subscription (one, on master account)
        │
        │  HTTP POST — JSON array, signed with Auth Token
        ▼
Your Webhook  →  Database  →  Read-only Dashboard
                                (filtered by account_sid)
```

Every event payload includes the `account_sid` field identifying which subaccount the activity originated from. This is the key that enables subaccount-level filtering without any changes to Twilio configuration.

---

## Key Concepts

### 1. Relevant event types

| Event Type | Fires When |
|---|---|
| `com.twilio.voice.insights.call-summary.complete` | A call completes and Voice Insights finishes processing (~60s after hang-up) |
| `com.twilio.voice.insights.call-summary.partial` | A partial summary is available (~30s after hang-up, less complete) |
| `com.twilio.voice.insights.conference-summary.complete` | A conference ends |
| `com.twilio.voice.insights.conference-participant-summary.complete` | A conference participant disconnects |
| `com.twilio.voice.status-callback.recording.processed` | A call recording has been transcoded and is ready |

### 2. Event payload structure (CloudEvents 1.0)

Twilio Event Streams uses the [CloudEvents](https://cloudevents.io) specification. Each POST to your webhook is a JSON array:

```json
[
  {
    "specversion": "1.0",
    "type": "com.twilio.voice.insights.call-summary.complete",
    "id": "EZxxxxx",
    "time": "2026-04-23T02:08:35.000Z",
    "data": {
      "call_sid": "CAxxxxx",
      "account_sid": "ACxxxxx",      ← subaccount identifier
      "call_state": "completed",
      "duration": 45,
      "start_time": "2026-04-23T02:07:50Z",
      "end_time": "2026-04-23T02:08:35Z",
      "from": { "caller": "+15551234567" },
      "to":   { "callee": "+15559876543" },
      "properties": { "direction": "outbound_api" }
    }
  }
]
```

Key fields:
- `data.account_sid` — which subaccount this call belongs to
- `data.call_sid` — cross-reference with the Twilio REST API
- `data.call_state` — final status: `completed`, `failed`, `busy`, `no-answer`
- `data.duration` — seconds

### 3. Subscription scope: master account (recommended)

Create **one subscription on the master account**. It receives events from the master account and all its subaccounts. The `account_sid` in each event identifies the source subaccount.

This is the simplest and most maintainable setup — one subscription, one webhook, all data in one place. Your application handles the per-subaccount access control.

### 4. Signature validation

Every webhook request is signed with HMAC-SHA1 using the account's Auth Token. The signature is in the `X-Twilio-Signature` header.

Always validate this on your webhook receiver. The Twilio Helper Libraries provide a `RequestValidator` class that does this in one line. Use the Auth Token of the account that owns the subscription (the master account for Option A above).

---

## What the Demo Shows

This repository is a complete, runnable implementation of the pattern described above. It demonstrates:

| Feature | How it's implemented |
|---|---|
| Real-time event ingestion | `POST /webhook/events` receives and validates every event |
| Subaccount filtering | Dropdown populated from distinct `account_sid` values in DB |
| Call log visualization | Line chart (volume), bar chart (duration), error rate, status breakdown |
| Conference log table | Paginated, filterable by subaccount, status, date range |
| Audio recording playback | Recordings stored in S3; in-browser playback via presigned URLs |
| Schema resilience | Full raw payload stored in JSON column; re-parseable on replay |
| Dead-letter queue | `raw_event_log.processed=False` rows flag parse failures |
| Health monitoring | `GET /api/health` returns latest event time + failure count |

---

## Positioning for the Customer Conversation

### Core message

> "Because Twilio Console doesn't have a native read-only subaccount view, we use Twilio's own Event Streams product to stream your call and conference data into a lightweight application. Every event is tagged with the originating subaccount. You control who sees what — and they have zero ability to touch your Twilio configuration."

### Key points

1. **Event Streams is a first-party Twilio product.** This is the supported, documented integration path — not a hack or workaround.

2. **Data arrives in near real time.** `partial` events arrive within ~30 seconds of a call ending. `complete` events follow within a few minutes once full quality metrics are processed.

3. **The `account_sid` is the access control key.** Every event includes it. Your application can scope each user's view to exactly their subaccount(s).

4. **You own the access layer.** Role-based access, SSO, audit logs, custom branding — all possible because it's your application. Twilio Console restrictions no longer apply.

5. **No historical data is lost.** The raw event payload is stored verbatim. If Twilio adds new fields or you need to re-process historical data, every event is replayable.

6. **Audio recordings are first-class.** The same pattern extends to recording metadata and audio files — recordings can be stored in your own S3 bucket and streamed securely to authorized users via presigned URLs.

---

## Common Customer Questions

**"How long does it take for events to arrive?"**  
`partial` call summary events arrive within ~30 seconds of call completion. `complete` events follow within 1–3 minutes once Voice Insights finishes processing quality metrics. Conference events arrive within ~60 seconds of the conference ending.

**"What if our webhook is down and we miss events?"**  
Twilio retries failed webhook deliveries with exponential backoff. The `raw_event_log` table also serves as a dead-letter queue — rows with `processed=False` indicate events that arrived but failed to parse. For guaranteed delivery SLAs, consider adding a message queue (SQS, Redis) between the webhook receiver and the processing logic.

**"Does this work for inbound calls too?"**  
Yes. The `data.properties.direction` field distinguishes `inbound`, `outbound_api`, and `outbound_dial`.

**"Can we filter by date, status, duration, or phone number?"**  
Yes — all of these fields are indexed columns in the normalized tables. The demo dashboard already supports date range, status, and subaccount filters out of the box.

**"Does Event Streams cost extra?"**  
Event Streams itself is free. Voice Insights has per-call costs for advanced features — check current Twilio pricing. For basic call summaries, the cost is minimal. Recording storage costs depend on S3 usage.

**"Can this replace our existing reporting tool?"**  
This pattern gives you the raw data and a reference frontend. Most production customers extend the frontend, add their own branding, integrate with BI tools (Grafana, Looker, Metabase), or expose the data via their own API. The database schema is straightforward SQL — any reporting tool that connects to PostgreSQL will work.

**"How do we handle Auth Token rotation?"**  
Update `TWILIO_AUTH_TOKEN` in your secret manager and restart the app. Plan for a brief 403 window, or implement dual-token validation (current + previous token both accepted) for zero-downtime rotation. See `PRODUCTION_GUIDE.md` Section 11 for implementation details.

**"Is this production-ready?"**  
The demo is a proof of concept. See `PRODUCTION_GUIDE.md` for the full production deployment checklist — covering authentication, HTTPS, PostgreSQL, S3, monitoring, and scaling. A small engineering team can production-harden this in approximately 1–2 weeks.

---

## Handoff Artifacts

When handing this solution to a customer's engineering team, provide:

| Document | Contents |
|---|---|
| `README.md` | Tech stack, quick start, API reference, project structure |
| `PRODUCTION_GUIDE.md` | Infrastructure, security hardening, scaling, monitoring, cost estimates |
| `STARTUP_GUIDE.md` | How to run the demo locally (for CE use during the PoC phase) |
| This repository | Complete working code — webhook receiver, event parser, API, dashboard |

The customer's engineering team should treat this as a **reference implementation**, not a copy-paste deployment. They will need to:

1. Replace the demo token auth with their identity provider
2. Deploy to their cloud of choice (see `PRODUCTION_GUIDE.md` Section 1)
3. Integrate S3 (or their preferred object storage) for recordings
4. Add their own branding and any domain-specific features to the dashboard

---

## Resources

- [Twilio Event Streams overview](https://www.twilio.com/docs/events)
- [Voice Insights event types](https://www.twilio.com/docs/voice/insights/api/call-summary-resource)
- [CloudEvents 1.0 specification](https://cloudevents.io)
- [Twilio RequestValidator (signature validation)](https://www.twilio.com/docs/usage/webhooks/webhooks-security)
- [Event Streams pricing](https://www.twilio.com/en-us/voice/insights)
