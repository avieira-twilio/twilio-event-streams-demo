# Demo Startup Guide

## What you have

| Environment | Port | Purpose |
|---|---|---|
| **Demo** | 5000 | Pre-populated with 200 synthetic calls, 50 conferences, and 40 recordings across 3 fake subaccounts. No Twilio account needed. |
| **Live** | 5001 | Receives real Twilio events from your master account via ngrok. |

Login tokens:
- Demo: `demo-access-token`
- Live: `live-access-token`

---

## Every time you start

You need **3 terminals** open simultaneously.

### Terminal 1 — Demo app (port 5000)

```bash
cd /Users/avieira/Claude/event-streams
source venv/bin/activate
flask --app wsgi:app run --port 5000
```

### Terminal 2 — Live app (port 5001)

```bash
cd /Users/avieira/Claude/event-streams-live
source venv/bin/activate
flask --app wsgi:app run --port 5001
```

### Terminal 3 — ngrok (exposes live app to Twilio)

```bash
ngrok http 5001 --domain=interfactional-unprohibitively-waltraud.ngrok-free.dev
```

---

## Verify everything is working

1. Open http://localhost:5000 → sign in with `demo-access-token` → charts and all three log tabs should be populated
2. Open http://localhost:5001 → sign in with `live-access-token` → shows real calls
3. Open http://127.0.0.1:4040 → ngrok inspector, shows incoming Twilio events in real time

---

## Make a test call (shows live data arriving)

Open a 4th terminal:

```bash
cd /Users/avieira/Claude/event-streams-live && source venv/bin/activate && python -c "
from twilio.rest import Client
from dotenv import load_dotenv
import os
load_dotenv('.env')
c = Client('YOUR_ACCOUNT_SID', os.getenv('TWILIO_AUTH_TOKEN'))
c.calls.create(to='+YOUR_MOBILE', from_='+YOUR_TWILIO_NUMBER', url='http://demo.twilio.com/docs/voice.xml')
print('Call placed.')
"
```

Wait ~60 seconds, refresh http://localhost:5001 — the call appears in the Call Logs tab.

---

## Make a test call with recording (shows Recording Logs + S3)

```bash
cd /Users/avieira/Claude/event-streams-live && source venv/bin/activate && python scripts/make_recorded_call.py
```

Answer your phone, wait for the call to end. Within 1–2 minutes, a recording entry appears in the Recording Logs tab with a blue **S3** badge. Click **▶ Play** to stream audio directly from S3.

---

## Make a test conference call

This creates a named conference room and calls your mobile twice — both legs join the same room, simulating a 2-participant conference.

```bash
cd /Users/avieira/Claude/event-streams-live && source venv/bin/activate && python -c "
from twilio.rest import Client
from dotenv import load_dotenv
import os
load_dotenv('.env')
c = Client('YOUR_ACCOUNT_SID', os.getenv('TWILIO_AUTH_TOKEN'))
twiml = '<Response><Dial><Conference>DemoRoom</Conference></Dial></Response>'
c.calls.create(to='+YOUR_MOBILE', from_='+YOUR_TWILIO_NUMBER', twiml=twiml)
c.calls.create(to='+YOUR_MOBILE', from_='+YOUR_TWILIO_NUMBER', twiml=twiml)
print('Both legs placed.')
"
```

Answer both calls, talk briefly, hang up. A `conference-summary.complete` event fires ~60 seconds after. Refresh the Conference Logs tab.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Port 5000 already in use | `lsof -ti :5000 \| xargs kill -9` |
| Port 5001 already in use | `lsof -ti :5001 \| xargs kill -9` |
| ngrok error: endpoint already online | `pkill ngrok` then re-run |
| Live dashboard empty after calls | Check http://127.0.0.1:4040 — if events show 403, the ProxyFix header is missing; if 500, check Flask logs. Click Replay after fixing. |
| Recordings not appearing | Confirm `AWS_S3_BUCKET` is set in `.env`; check Flask logs for S3 errors |
| "Invalid signature" on webhook | Ensure `TWILIO_AUTH_TOKEN` in `.env` matches the account that owns the Event Streams subscription |
| Browser shows wrong dashboard | Demo and live share `localhost` cookie domain — use a regular window for one and an incognito window for the other |
