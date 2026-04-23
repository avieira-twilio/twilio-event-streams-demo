# Production Deployment Guide
## Twilio Event Streams — Call & Conference Dashboard

**Audience:** Engineering teams deploying this solution for production use  
**Purpose:** Guidelines for hardening, scaling, and operating the dashboard beyond the proof-of-concept stage

---

## Architecture overview

```
                    ┌─────────────────────────────────────────┐
                    │           Twilio Platform               │
                    │                                         │
                    │  Master Account + Subaccounts           │
                    │  Event Streams Subscription             │
                    │  Recording Status Callbacks             │
                    └────────────────┬────────────────────────┘
                                     │ HTTPS POST (signed)
                                     ▼
                    ┌─────────────────────────────────────────┐
                    │        Load Balancer / Reverse Proxy    │
                    │        (nginx, AWS ALB, Cloudflare)     │
                    └────────────────┬────────────────────────┘
                                     │
                    ┌────────────────▼────────────────────────┐
                    │         Application Servers             │
                    │         Flask + Gunicorn                │
                    │         (2+ instances, auto-scale)      │
                    └────┬───────────────────────┬────────────┘
                         │                       │
           ┌─────────────▼──────┐   ┌────────────▼────────────┐
           │   PostgreSQL       │   │   AWS S3                │
           │   (primary +       │   │   (recording storage)   │
           │    read replica)   │   └─────────────────────────┘
           └────────────────────┘
```

---

## 1. Infrastructure

### Hosting

| Component | Recommended options |
|---|---|
| Application | AWS ECS, Fly.io, Heroku, Render, Google Cloud Run |
| Database | AWS RDS PostgreSQL, Supabase, Neon, Google Cloud SQL |
| Recording storage | AWS S3 or S3-compatible (Cloudflare R2, Backblaze B2) |
| Reverse proxy | nginx, AWS ALB, Cloudflare |

The application is stateless — all state lives in the database and S3. This means horizontal scaling is straightforward.

### Minimum production sizing

| Tier | Requests/day | App | Database |
|---|---|---|---|
| Small (< 10k calls/day) | ~50k | 1 instance, 512MB RAM | 1 vCPU, 2GB RAM |
| Medium (10k–100k calls/day) | ~500k | 2–4 instances, 1GB RAM | 2 vCPU, 8GB RAM |
| Large (> 100k calls/day) | > 1M | Auto-scale group | Multi-AZ, read replica |

---

## 2. Environment variables

Copy `.env.example` to your secret manager (AWS Secrets Manager, HashiCorp Vault, Doppler) and populate all values. Never commit secrets to source control.

```bash
# ── Flask ─────────────────────────────────────────────────────────────────────
FLASK_ENV=production
FLASK_SECRET_KEY=<64-character random string>   # python -c "import secrets; print(secrets.token_hex(32))"

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL=postgresql://user:password@host:5432/twilio_dashboard

# ── Twilio ────────────────────────────────────────────────────────────────────
TWILIO_AUTH_TOKEN=<master account auth token>   # Auth Token of subscription owner

# ── Dashboard access ──────────────────────────────────────────────────────────
# Replace with your own authentication system for production (see Section 5)
DASHBOARD_TOKEN=<strong random token>

# ── Signature validation ──────────────────────────────────────────────────────
SKIP_SIGNATURE_VALIDATION=false                 # NEVER set to true in production

# ── AWS S3 (optional — omit to serve recordings from Twilio) ──────────────────
AWS_ACCESS_KEY_ID=<key id>
AWS_SECRET_ACCESS_KEY=<secret key>
AWS_REGION=us-east-1
AWS_S3_BUCKET=<your bucket name>
```

---

## 3. Database

### Switch from SQLite to PostgreSQL

Change `DATABASE_URL` to a PostgreSQL connection string and run migrations:

```bash
flask --app wsgi:app db upgrade
```

SQLAlchemy handles the dialect difference automatically. No code changes required.

### Recommended PostgreSQL settings

```sql
-- Increase connection pool if using many app instances
ALTER SYSTEM SET max_connections = 200;

-- Enable pg_stat_statements for query monitoring
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
```

### Indexes already created by migrations

| Table | Index |
|---|---|
| `call_logs` | `account_sid`, `started_at` |
| `conference_logs` | `account_sid`, `started_at` |
| `recording_logs` | `account_sid`, `call_sid`, `recorded_at` |
| `raw_event_log` | `event_id`, `account_sid`, `received_at` |

For large deployments (> 1M rows), also add a composite index:

```sql
CREATE INDEX idx_call_logs_account_started
    ON call_logs (account_sid, started_at DESC);
```

### Backup

Enable automated backups on your managed PostgreSQL provider. Minimum recommended retention: 7 days. For compliance use cases, consider 90-day retention with point-in-time recovery.

---

## 4. Running with Gunicorn

Replace `flask run` with Gunicorn for production:

```bash
gunicorn wsgi:app \
    --workers 4 \
    --worker-class sync \
    --bind 0.0.0.0:8000 \
    --timeout 60 \
    --access-logfile - \
    --error-logfile -
```

**Workers:** Set to `(2 × CPU cores) + 1`. For a 2-core server, use 5 workers.

**Docker:**
```bash
docker compose -f docker/docker-compose.yml up --build
```

The provided `docker-compose.yml` runs Gunicorn behind a PostgreSQL instance with a health check dependency.

---

## 5. Authentication

The demo uses a single shared token for simplicity. **For production, replace this with a proper authentication system.**

### Recommended options

**Option A — OAuth 2.0 / SSO (recommended)**  
Integrate with your existing identity provider (Okta, Auth0, Google Workspace, Azure AD) using a library like [Authlib](https://authlib.org/) or [Flask-Login](https://flask-login.readthedocs.io/) with an OAuth backend.

**Option B — Per-subaccount user accounts**  
Create a `users` table with `account_sid` scope. Each user can only query their own subaccount's data. Use bcrypt for password hashing (`pip install flask-bcrypt`).

**Option C — API key per subaccount**  
For machine-to-machine access, issue API keys scoped to an `account_sid`. Validate in a middleware decorator similar to the existing `@require_auth`.

In all cases, ensure:
- Sessions are signed and expire (the existing `FLASK_SECRET_KEY` covers this for cookie-based sessions)
- HTTPS is enforced — never run without TLS in production
- Failed login attempts are rate-limited

---

## 6. HTTPS and reverse proxy

The application includes `ProxyFix` middleware which reads `X-Forwarded-Proto` and `X-Forwarded-Host` headers from your reverse proxy. This is required for Twilio signature validation to work correctly.

### nginx configuration (example)

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate     /etc/ssl/certs/your-domain.crt;
    ssl_certificate_key /etc/ssl/private/your-domain.key;

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Forwarded-For   $remote_addr;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_set_header   X-Forwarded-Host  $host;
        proxy_read_timeout 60s;
    }
}
```

### Important: Twilio signature validation and URL matching

Twilio signs requests using the full URL it posts to. If your app reconstructs the URL incorrectly (wrong scheme, extra port), signature validation will fail with 403.

Checklist:
- `SKIP_SIGNATURE_VALIDATION=false` in `.env`
- `ProxyFix` middleware is applied in `app/__init__.py` ✓
- nginx forwards `X-Forwarded-Proto: https` ✓
- Your Event Streams Sink URL uses `https://` ✓
- No port number in the Sink URL (use 443, which is implicit in HTTPS) ✓

---

## 7. AWS S3 for recording storage

### IAM user setup

Create a dedicated IAM user (`twilio-recordings`) with the following policy. Replace `YOUR_BUCKET_NAME`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "RecordingsBucketAccess",
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::YOUR_BUCKET_NAME/recordings/*"
    },
    {
      "Sid": "ListBucketForPresign",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::YOUR_BUCKET_NAME"
    }
  ]
}
```

Generate programmatic access keys (not console access) and store them in your secret manager, then set `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, and `AWS_S3_BUCKET` in your environment.

### Bucket configuration recommendations

```
Versioning:         Enabled (allows recovery from accidental deletes)
Server-side encryption: AES-256 or KMS
Block public access: All four settings ON
Lifecycle rule:     Transition to S3 Intelligent-Tiering after 30 days
                    Expire after [your retention policy] days
```

### Recording flow

```
Call ends
    │
    ├─► Twilio fires recording.processed to /webhook/recording-status
    │
    ├─► App downloads .mp3 from Twilio (authenticated with Auth Token)
    │
    ├─► App uploads to s3://{bucket}/recordings/{account_sid}/{recording_sid}.mp3
    │
    └─► Dashboard serves audio via presigned URL (1-hour expiry, configurable)
```

Presigned URL expiry is set in `app/services/s3_handler.py` (`generate_presigned_url(expires_in=3600)`). Adjust to match your security requirements.

---

## 8. Event Streams subscription setup

Run once per environment (staging, production):

```bash
python scripts/setup_event_streams.py \
    --account-sid ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx \
    --auth-token  your_master_auth_token \
    --webhook-url https://your-domain.com/webhook/events
```

This creates a Sink (webhook destination) and a Subscription covering:
- `com.twilio.voice.insights.call-summary.complete`
- `com.twilio.voice.insights.call-summary.partial`
- `com.twilio.voice.insights.conference-summary.complete`
- `com.twilio.voice.insights.conference-participant-summary.complete`
- `com.twilio.voice.status-callback.recording.processed`

Save the Subscription SID (`DFxxx`) — you will need it if you ever need to update the event types or change the destination URL.

### Updating the webhook URL (e.g. after a domain change)

```python
from twilio.rest import Client

client = Client(MASTER_ACCOUNT_SID, MASTER_AUTH_TOKEN)

# Update the Sink destination
client.events.v1.sinks("DGxxxxx").update(
    sink_configuration={
        "destination": "https://new-domain.com/webhook/events",
        "method": "POST",
        "batch_events": False,
    }
)
```

---

## 9. Monitoring and alerting

### Health endpoint

`GET /api/health` returns:

```json
{
  "status": "ok",
  "latest_event_at": "2026-04-23T21:14:34.000Z",
  "unprocessed_count": 0
}
```

Wire this into your uptime monitoring (UptimeRobot, Datadog, Pingdom). Alert on:
- `unprocessed_count > 0` for more than 15 minutes → parser failure
- `latest_event_at` older than 30 minutes during business hours → possible event delivery gap
- HTTP status not 200 → app is down

### Dead-letter queue

```sql
-- Events that failed to parse — investigate and replay
SELECT id, event_type, account_sid, received_at, payload
FROM raw_event_log
WHERE processed = FALSE
ORDER BY received_at DESC;
```

To replay a failed event after fixing the parser:

```python
from app import create_app
from app.extensions import db
from app.models import RawEventLog
from app.services.event_parser import parse_event

app = create_app()
with app.app_context():
    failed = RawEventLog.query.filter_by(processed=False).all()
    for row in failed:
        try:
            parse_event(row.payload, row.event_type)
            row.processed = True
        except Exception as e:
            print(f"Still failing: {row.id} — {e}")
    db.session.commit()
```

### Sequence gap detection

```sql
-- Find gaps in event sequence (potential dropped deliveries)
SELECT
    event_id,
    received_at,
    LAG(received_at) OVER (ORDER BY received_at) AS prev_received_at,
    received_at - LAG(received_at) OVER (ORDER BY received_at) AS gap
FROM raw_event_log
ORDER BY received_at DESC
LIMIT 100;
```

### Recommended metrics to track

| Metric | How |
|---|---|
| Events received per minute | Count `raw_event_log` inserts |
| Parse failure rate | `processed=False` / total |
| Webhook p95 response time | Application logs / APM |
| Database query time | `pg_stat_statements` |
| S3 upload success rate | Application logs |
| Recording processing lag | `received_at` − `recorded_at` on `recording_logs` |

---

## 10. Security checklist

Before going to production, verify each item:

- [ ] `SKIP_SIGNATURE_VALIDATION=false` in all production environments
- [ ] `FLASK_SECRET_KEY` is a 64-character random string, not the default
- [ ] `DASHBOARD_TOKEN` has been replaced with a proper auth system (Section 5)
- [ ] `DATABASE_URL` uses a dedicated database user with least-privilege access (not superuser)
- [ ] Application runs over HTTPS only — HTTP redirects to HTTPS at the load balancer
- [ ] S3 bucket has public access blocked; recordings are served only via presigned URLs
- [ ] IAM user has only the permissions listed in Section 7 (no `s3:*` wildcard)
- [ ] AWS credentials are stored in a secret manager, not in `.env` files on disk
- [ ] Auth Token rotation procedure is documented and tested
- [ ] `raw_event_log` payload column is excluded from any external logging (contains PII — phone numbers)
- [ ] Database backups are configured and tested
- [ ] Rate limiting is applied to `/webhook/events` at the load balancer or WAF layer

---

## 11. Auth Token rotation

When rotating the Twilio Auth Token:

1. Generate the new token in Twilio Console (Account → API Keys & Tokens)
2. Update `TWILIO_AUTH_TOKEN` in your secret manager
3. Deploy a new version of the app (or restart to pick up the new secret)
4. Twilio's signature validation will accept the new token immediately after deployment
5. There is a brief window between the token change and the app restart where webhooks may return 403. Schedule the rotation during a low-traffic window or implement dual-token validation

**Dual-token validation (optional, zero-downtime rotation):**

```python
def validate_signature(request):
    """Accept either the current or the previous token during rotation."""
    tokens = [
        current_app.config["TWILIO_AUTH_TOKEN"],
        current_app.config.get("TWILIO_AUTH_TOKEN_PREVIOUS", ""),
    ]
    sig = request.headers.get("X-Twilio-Signature", "")
    body = request.get_data(as_text=True)
    return any(
        RequestValidator(t).validate(request.url, body, sig)
        for t in tokens if t
    )
```

---

## 12. Scaling considerations

### Webhook throughput

A single Gunicorn worker can handle ~50 webhook requests/second (each request is a short database write). For higher throughput:

- Add more Gunicorn workers / instances behind a load balancer
- Consider async workers (`--worker-class gevent`) for I/O-bound workloads
- Add a message queue (SQS, Redis) between the webhook receiver and the parser for burst handling

### Database connections

Each Gunicorn worker holds a SQLAlchemy connection pool. With 4 workers × 4 instances = 16 processes, set the pool to:

```python
# In config.py
SQLALCHEMY_ENGINE_OPTIONS = {
    "pool_size": 5,
    "max_overflow": 10,
    "pool_pre_ping": True,
}
```

Use [PgBouncer](https://www.pgbouncer.org/) in transaction mode for connection pooling at the database level if you run many app instances.

### Data retention

```sql
-- Archive or delete old raw events (keep normalized tables)
DELETE FROM raw_event_log
WHERE received_at < NOW() - INTERVAL '90 days'
  AND processed = TRUE;
```

Run this as a scheduled job (cron, pg_cron, or your task scheduler) to keep the table size manageable.

---

## 13. Grafana integration (optional)

Grafana can connect directly to PostgreSQL to build advanced dashboards with alerting.

```bash
docker run -p 3000:3000 grafana/grafana
```

Add a **PostgreSQL data source** pointing to the same `DATABASE_URL`. Example panels:

```sql
-- Call volume over time (Grafana time series)
SELECT
    date_trunc('hour', started_at) AS time,
    account_sid,
    COUNT(*) AS calls
FROM call_logs
WHERE started_at BETWEEN $__timeFrom() AND $__timeTo()
GROUP BY 1, 2
ORDER BY 1;

-- Error rate by subaccount
SELECT
    account_sid,
    ROUND(
        100.0 * SUM(CASE WHEN status IN ('failed','busy','no-answer') THEN 1 ELSE 0 END)
        / COUNT(*), 2
    ) AS error_pct
FROM call_logs
WHERE started_at > NOW() - INTERVAL '24 hours'
GROUP BY account_sid;
```

Use Grafana template variables for `account_sid` to replicate the subaccount filtering from the built-in dashboard.

---

## 14. Estimated build time and cost

### One-time build effort

| Task | Effort |
|---|---|
| Deploy to cloud (ECS/Fly.io/Render) | 1–2 days |
| Switch to PostgreSQL + run migrations | 2 hours |
| Replace token auth with SSO/OAuth | 2–4 days |
| S3 bucket + IAM setup | 2 hours |
| Monitoring + alerting | 1 day |
| Security hardening (checklist above) | 1 day |
| **Total** | **~1–2 weeks for a small team** |

### Ongoing infrastructure cost (USD/month, estimates)

| Component | Small (<10k calls/day) | Medium (<100k calls/day) |
|---|---|---|
| App hosting (Fly.io / Render) | $7–$25 | $50–$150 |
| PostgreSQL (managed) | $15–$25 | $50–$200 |
| S3 storage (recordings) | $1–$5 | $10–$50 |
| Twilio Event Streams | Free | Free |
| Voice Insights (per call) | See Twilio pricing | See Twilio pricing |
| **Total (excl. Twilio calls)** | **~$25–$55/mo** | **~$110–$400/mo** |

---

## Resources

- [Twilio Event Streams documentation](https://www.twilio.com/docs/events)
- [Voice Insights event types](https://www.twilio.com/docs/voice/insights/api/call-summary-resource)
- [CloudEvents 1.0 specification](https://cloudevents.io)
- [Flask deployment options](https://flask.palletsprojects.com/en/3.0.x/deploying/)
- [SQLAlchemy connection pooling](https://docs.sqlalchemy.org/en/20/core/pooling.html)
- [AWS S3 presigned URLs](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html)
- [Twilio Auth Token rotation](https://help.twilio.com/articles/223136047)
