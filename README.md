# Twilio Event Streams — Call & Conference Dashboard

A production-ready reference implementation showing how to use Twilio Event Streams to build a real-time, subaccount-aware call and conference log dashboard with audio recording support.

## Why this exists

Twilio Console does not support granting read-only access to call or conference logs at the subaccount level. Customers who need to give clients or analysts view-only visibility have no native Console option today.

**Twilio's recommended solution:** Use [Event Streams](https://www.twilio.com/docs/events) to stream Voice Insights and Conference Insights events in real time to a webhook, then build a custom data and visualization layer on top.

This repository is a complete, working implementation of that pattern — suitable both as a demo and as a foundation for a production deployment.

```
Twilio Account / Subaccounts
        │
        │  Voice Insights events  (call-summary.complete, conference-summary.complete, …)
        │  Recording status callbacks  (recording.processed)
        ▼
POST /webhook/events  ←  this app
        │
        ├─► raw_event_log   (every event stored verbatim — dead-letter queue + replay)
        │
        ├─► call_logs / conference_logs / recording_logs  (normalized, indexed)
        │
        └─► Flask JSON API  →  Chart.js Dashboard  (filtered by subaccount)
```

---

## Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Backend | Python 3.11+ / Flask 3 | App factory pattern, Blueprints |
| ORM / Migrations | SQLAlchemy + Flask-Migrate | Schema-versioned, Alembic under the hood |
| Database | SQLite (dev) → PostgreSQL (prod) | Zero-config locally; swap `DATABASE_URL` for prod |
| Frontend | Jinja2 + Chart.js 4 (CDN) | No build step required |
| Auth | Token-based session | Demo-grade; replace with SSO/OAuth for production |
| Recording storage | Twilio (default) or AWS S3 | S3 upload triggered automatically when `AWS_S3_BUCKET` is set |
| Container | Docker + docker-compose | Includes PostgreSQL service |

---

## Quick start (local demo, SQLite)

```bash
# 1. Clone
git clone https://github.com/avieira-twilio/twilio-event-streams-demo.git
cd twilio-event-streams-demo

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env — set FLASK_SECRET_KEY and DASHBOARD_TOKEN at minimum

# 5. Initialize database
flask --app wsgi:app db upgrade

# 6. Seed with synthetic demo data (no Twilio account needed)
python scripts/seed_demo_data.py

# 7. Run
flask --app wsgi:app run

# 8. Open http://localhost:5000 and sign in with your DASHBOARD_TOKEN
```

---

## Connecting to real Twilio Event Streams

### Prerequisites
- A Twilio account with at least one subaccount
- Voice Insights enabled (available on all paid accounts)
- A publicly reachable HTTPS endpoint (ngrok for local dev, or a deployed URL)

### Steps

```bash
# Terminal 1 — run the app
flask --app wsgi:app run

# Terminal 2 — expose publicly for local testing
ngrok http 5000

# Terminal 3 — create the Event Streams Sink and Subscription
python scripts/setup_event_streams.py \
    --account-sid ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx \
    --auth-token  your_master_account_auth_token \
    --webhook-url https://your-subdomain.ngrok-free.app/webhook/events
```

Place a call through any subaccount. Within ~60 seconds of call completion, a Voice Insights event arrives and appears in the dashboard.

> **Auth Token note:** `TWILIO_AUTH_TOKEN` in `.env` must match the account that owns the subscription. Use the master account token for master-level subscriptions.

---

## Audio recordings

Set the following environment variables to automatically upload recordings to S3:

```
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_REGION=us-east-1
AWS_S3_BUCKET=your-bucket-name
```

When `AWS_S3_BUCKET` is set, recordings are downloaded from Twilio and uploaded to `s3://your-bucket/recordings/{account_sid}/{recording_sid}.mp3` immediately on receipt. The dashboard shows a blue **S3** badge and serves audio via presigned URLs. Without S3 configured, recordings are proxied directly from Twilio.

For the recording status callback to fire, pass `recordingStatusCallback` when creating calls:

```python
client.calls.create(
    to=to_number,
    from_=from_number,
    url="...",
    record=True,
    recording_status_callback="https://your-app.com/webhook/recording-status",
    recording_status_callback_method="POST",
)
```

---

## Docker (PostgreSQL)

```bash
cp .env.example .env   # fill in values
docker compose -f docker/docker-compose.yml up --build

# Run migrations (first time only)
docker compose -f docker/docker-compose.yml exec web flask --app wsgi:app db upgrade

# Optionally seed demo data
docker compose -f docker/docker-compose.yml exec web python scripts/seed_demo_data.py
```

---

## API reference

All endpoints except `/webhook/events`, `/webhook/recording-status`, and `/api/health` require authentication.

| Method | Path | Description |
|---|---|---|
| `POST` | `/webhook/events` | Twilio Event Streams receiver (CloudEvents 1.0 array) |
| `POST` | `/webhook/recording-status` | Direct recording status callback |
| `GET` | `/api/health` | Latest event timestamp + unprocessed count |
| `GET` | `/api/subaccounts` | Distinct account SIDs in the database |
| `GET` | `/api/calls` | Paginated call logs. Filters: `account_sid`, `status`, `from`, `to`, `page` |
| `GET` | `/api/conferences` | Paginated conference logs. Same filters. |
| `GET` | `/api/recordings` | Paginated recording logs. Filters: `account_sid`, `status`, `from`, `to`, `page` |
| `GET` | `/api/recordings/proxy/<sid>` | Stream Twilio audio to browser (server-side proxy) |
| `GET` | `/api/recordings/presign/<sid>` | Return S3 presigned URL for browser playback |
| `GET` | `/api/charts/call-volume` | Daily call counts by subaccount |
| `GET` | `/api/charts/call-duration` | Avg + max duration by subaccount |
| `GET` | `/api/charts/error-rate` | Daily error percentage by subaccount |
| `GET` | `/api/charts/call-status` | Status breakdown by subaccount |

---

## Project structure

```
event-streams/
├── app/
│   ├── __init__.py            Flask app factory + ProxyFix middleware
│   ├── config.py              Dev / Prod config classes
│   ├── extensions.py          db, migrate singletons
│   ├── models.py              CallLog, ConferenceLog, ConferenceParticipantLog,
│   │                          RecordingLog, RawEventLog
│   ├── routes/
│   │   ├── auth.py            /login, /logout, @require_auth decorator
│   │   ├── webhook.py         POST /webhook/events and /webhook/recording-status
│   │   ├── api.py             JSON API endpoints
│   │   └── dashboard.py       HTML dashboard route
│   ├── services/
│   │   ├── event_parser.py    Raw payload → domain models (CloudEvents + legacy)
│   │   └── s3_handler.py      S3 upload + presigned URL generation
│   ├── templates/
│   │   ├── base.html
│   │   ├── login.html
│   │   └── dashboard.html
│   └── static/js/charts.js   Chart.js rendering + table pagination
├── scripts/
│   ├── seed_demo_data.py      Synthetic data (200 calls, 50 conferences, 40 recordings)
│   ├── setup_event_streams.py Create Twilio Sink + Subscription
│   └── make_recorded_call.py  Place a test call with recording + status callback
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
├── wsgi.py
├── requirements.txt
├── .env.example
├── README.md
├── PRODUCTION_GUIDE.md        ← Production deployment guidelines for customers
└── STARTUP_GUIDE.md           ← Local demo startup instructions
```

---

## Best practices

### Schema resilience
Every event is stored verbatim in the `raw_payload` JSON column. If Twilio changes field names or adds new fields, historical data is preserved and re-parseable by replaying from `raw_event_log`. The parser uses `.get()` everywhere with safe fallbacks.

### Dropped event detection
- `raw_event_log` rows with `processed=False` act as a dead-letter queue. Alert on any row older than 1 hour.
- The `event_id` column stores `X-Twilio-Event-Id`. Gaps in sequential IDs indicate dropped deliveries.
- `GET /api/health` returns the latest event timestamp and unprocessed count. Wire this into your monitoring system.
- Periodically reconcile against the Twilio REST API: `client.calls.list()` per subaccount vs. `call_logs` row counts.

### Signature validation
Validation is on by default. Never disable it in production. The `ProxyFix` middleware in `app/__init__.py` ensures `request.url` matches the URL Twilio signed when running behind a reverse proxy. After rotating an Auth Token, update `.env` and restart — plan for a brief 403 window or implement dual-token validation during rotation.

---

*See `PRODUCTION_GUIDE.md` for guidelines on deploying this to a production environment.*
