# Twilio Event Streams Demo Dashboard

## Why this exists

**The limitation:** Twilio Console does not provide a way to grant read-only
access to call or conference logs at the subaccount level. If a customer wants
to give a client or analyst view-only visibility into a subaccount's call
activity, there is no native Console permission to do that today.

**Twilio Support's recommendation:** Use [Event Streams](https://www.twilio.com/docs/events)
to export Voice Insights and Conference Insights events in real-time to a
webhook. Build a custom data store and visualization layer on top of that data.

**What this repo is:** A working demo of that exact pattern. It is intended for
educational and demonstration purposes only, not for production use.

```
Twilio (subaccount calls/conferences)
        │
        │  Voice Insights events (call-summary.complete, etc.)
        │  Conference Insights events (conference.summary, etc.)
        ▼
POST /webhook/events   ← this app
        │
        ▼
SQLite / PostgreSQL  →  Flask JSON API  →  Dashboard (Chart.js)
```

---

## Tech stack

| Layer | Tool |
|---|---|
| Backend | Python 3.12 + Flask 3 |
| ORM / migrations | SQLAlchemy + Flask-Migrate |
| Database | SQLite (dev, zero-setup) → PostgreSQL (Docker / prod) |
| Frontend | Jinja2 templates + Chart.js 4 (CDN) |
| Auth | Token-based session (demo-grade) |
| Local tunnel | ngrok (free tier) |
| Container | Docker + docker-compose (optional) |

---

## Quick start (local, SQLite)

```bash
# 1. Clone and enter the project
cd event-streams

# 2. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure
cp .env.example .env
# Edit .env — at minimum set FLASK_SECRET_KEY and DASHBOARD_TOKEN

# 5. Initialize the database
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
- A Twilio account (free trial works) with at least one subaccount
- Voice Insights enabled (available on all accounts)
- ngrok installed (`brew install ngrok` or download from ngrok.com)

### Steps

```bash
# Terminal 1 — run the app
flask --app wsgi:app run

# Terminal 2 — expose it publicly
ngrok http 5000
# Copy the HTTPS URL, e.g. https://abc123.ngrok.io

# Terminal 3 — create the Event Streams subscription on your subaccount
python scripts/setup_event_streams.py \
    --account-sid ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx \
    --auth-token  your_subaccount_auth_token \
    --webhook-url https://abc123.ngrok.io/webhook/events
```

Then place a call through that subaccount. Within ~60 seconds of call
completion, a Voice Insights event arrives at the webhook. Refresh the
dashboard to see it.

Run `setup_event_streams.py` once per subaccount you want to monitor.

**Auth Token note:** The `TWILIO_AUTH_TOKEN` in `.env` must match the account
that owns the Event Streams subscription — master account token for
master-account subscriptions, subaccount token for subaccount subscriptions.

---

## Docker (PostgreSQL)

```bash
cp .env.example .env   # fill in values (DATABASE_URL is overridden by docker-compose)
docker compose -f docker/docker-compose.yml up --build

# In a second terminal, run migrations and seed:
docker compose -f docker/docker-compose.yml exec web flask --app wsgi:app db upgrade
docker compose -f docker/docker-compose.yml exec web python scripts/seed_demo_data.py
```

---

## Migrating from SQLite to PostgreSQL

```bash
# Export from SQLite, import into PostgreSQL:
export PG_DATABASE_URL=postgresql://user:pass@host:5432/twilio_dashboard
python scripts/migrate_sqlite_to_pg.py   # (DIY — see plan for outline)
```

Or simply re-seed against PostgreSQL from scratch and let real events repopulate.

---

## API reference

All endpoints (except `/webhook/events` and `/api/health`) require authentication.

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/subaccounts` | Distinct account SIDs in the DB |
| `GET` | `/api/calls` | Paginated call logs. Filters: `account_sid`, `status`, `from`, `to`, `page` |
| `GET` | `/api/conferences` | Paginated conference logs. Same filters. |
| `GET` | `/api/charts/call-volume` | Daily call counts by subaccount |
| `GET` | `/api/charts/call-duration` | Avg + max duration by subaccount |
| `GET` | `/api/charts/error-rate` | Daily error % by subaccount |
| `GET` | `/api/charts/call-status` | Status breakdown by subaccount |
| `GET` | `/api/health` | Latest event timestamp + unprocessed count |
| `POST` | `/webhook/events` | Twilio Event Streams webhook receiver |

---

## Best practices

### Handling Twilio event schema changes

- Every event is stored verbatim in the `raw_payload` / `payload` JSON column.
  If Twilio adds, renames, or removes a field, historical data is preserved
  and re-parseable by replaying rows from `raw_event_log`.
- `event_parser.py` uses `.get()` everywhere with safe fallbacks — it never
  assumes a field exists. When Twilio announces schema changes, update the
  parser and replay from `raw_event_log` with `processed=False` rows.

### Monitoring for dropped events

- **Dead-letter queue:** Any `raw_event_log` row with `processed=False` means
  the parser raised an exception. Query these regularly and alert if any are
  older than 1 hour.
- **Sequence gap detection:** The `event_id` column stores the
  `X-Twilio-Event-Id` header. Gaps in sequential event IDs indicate dropped
  deliveries. Twilio will retry failed webhooks, but permanent gaps can be
  cross-checked against the REST API.
- **Health endpoint:** `GET /api/health` returns the timestamp of the most
  recently received event and the unprocessed count. Wire this into your
  monitoring system and alert if the latest event is stale by more than
  30 minutes during business hours.
- **REST API reconciliation:** Periodically fetch call counts from
  `client.calls.list()` per subaccount and compare against `call_logs` row
  counts. A significant delta indicates missed events.

### Twilio signature validation

- Signature validation is on by default. **Never disable it in production.**
- If running behind a reverse proxy (nginx, load balancer, ngrok), the
  `ProxyFix` middleware in `app/__init__.py` ensures `request.url` matches
  what Twilio signed.
- After rotating an Auth Token in the Twilio Console, update `TWILIO_AUTH_TOKEN`
  in `.env` and restart the app. There is a brief window where requests may
  fail with 403; plan for a short outage window or implement dual-token
  validation during rotation.

---

## Optional: Grafana integration

Because all data lives in PostgreSQL, connecting Grafana is straightforward:

1. Run Grafana locally: `docker run -p 3000:3000 grafana/grafana`
2. Add a PostgreSQL data source pointing to the same `DATABASE_URL`.
3. Build panels using direct SQL:

```sql
-- Call volume over time by subaccount
SELECT
  date_trunc('day', started_at) AS time,
  account_sid,
  count(*) AS calls
FROM call_logs
WHERE started_at BETWEEN $__timeFrom() AND $__timeTo()
GROUP BY 1, 2
ORDER BY 1;
```

Use Grafana template variables (`account_sid`) for subaccount filtering.

---

## Project structure

```
event-streams/
├── app/
│   ├── __init__.py            Flask app factory + ProxyFix
│   ├── config.py              Dev / Prod config classes
│   ├── extensions.py          db, migrate singletons
│   ├── models.py              CallLog, ConferenceLog, ConferenceParticipantLog, RawEventLog
│   ├── routes/
│   │   ├── auth.py            /login, /logout, @require_auth decorator
│   │   ├── webhook.py         POST /webhook/events
│   │   ├── api.py             JSON API endpoints
│   │   └── dashboard.py       HTML dashboard route
│   ├── services/
│   │   └── event_parser.py    Raw payload → domain models
│   ├── templates/
│   │   ├── base.html
│   │   ├── login.html
│   │   └── dashboard.html
│   └── static/js/charts.js   Chart.js rendering + table pagination
├── scripts/
│   ├── seed_demo_data.py      Synthetic data (200 calls, 50 conferences)
│   └── setup_event_streams.py Create Twilio Sink + Subscription
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
├── wsgi.py
├── requirements.txt
└── .env.example
```

---

*Demo use only. Not intended for production deployment without additional
security hardening, rate limiting, and proper secret management.*
