# Demo Startup Guide

## What you have

| Environment | URL | Purpose |
|---|---|---|
| Demo | http://localhost:5000 | Pre-populated with 200 synthetic calls across 3 fake subaccounts |
| Live | http://localhost:5001 | Real Twilio events from your master account |

Login tokens:
- Demo: `demo-access-token`
- Live: `live-access-token`

---

## Every time you start

You need **3 terminals** open simultaneously.

---

### Terminal 1 — Demo app (port 5000)

```bash
cd /Users/avieira/Claude/event-streams
source venv/bin/activate
flask --app wsgi:app run --port 5000
```

---

### Terminal 2 — Live app (port 5001)

```bash
cd /Users/avieira/Claude/event-streams-live
source venv/bin/activate
flask --app wsgi:app run --port 5001
```

---

### Terminal 3 — ngrok (exposes live app to Twilio)

```bash
ngrok http 5001
```

ngrok will print your public HTTPS URL, e.g.:
```
https://your-subdomain.ngrok-free.dev
```

---

## Verify everything is working

1. Open http://localhost:5000 → sign in with `demo-access-token` → charts and call logs should be populated
2. Open http://localhost:5001 → sign in with `live-access-token` → shows real calls
3. Open http://127.0.0.1:4040 → ngrok inspector, shows incoming Twilio events

---

## Make a real test call (optional, to show live data arriving)

Open a 4th terminal and run:

```bash
python3 -c "
from twilio.rest import Client
c = Client('YOUR_ACCOUNT_SID', 'YOUR_AUTH_TOKEN')
call = c.calls.create(from_='YOUR_TWILIO_NUMBER', to='YOUR_VERIFIED_NUMBER', url='http://demo.twilio.com/docs/voice.xml')
print('Call SID:', call.sid, 'Status:', call.status)
"
```

Wait ~60 seconds, then refresh http://localhost:5001 — the new call will appear.

---

## Make a real test conference (to populate Conference Logs)

You only need your one mobile number. This creates a named conference room and
calls your mobile twice — both legs join the same room, simulating a 2-participant
conference.

Open a 4th terminal and run:

```bash
python3 -c "
from twilio.rest import Client

c = Client('YOUR_ACCOUNT_SID', 'YOUR_AUTH_TOKEN')

twiml = '<Response><Dial><Conference>DemoRoom</Conference></Dial></Response>'

call1 = c.calls.create(from_='YOUR_TWILIO_NUMBER', to='YOUR_VERIFIED_NUMBER', twiml=twiml)
print('Leg 1:', call1.sid)

call2 = c.calls.create(from_='YOUR_TWILIO_NUMBER', to='YOUR_VERIFIED_NUMBER', twiml=twiml)
print('Leg 2:', call2.sid)
"
```

What happens:
1. Your mobile rings — answer it, you are now in the conference room
2. Your mobile rings a second time — answer it (or let it go to voicemail, it still counts as a participant)
3. Talk for a few seconds, then hang up both calls
4. A `conference-summary.complete` event fires ~60 seconds after the conference ends

Refresh http://localhost:5001 and the conference will appear in the Conference Logs tab.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Port 5000 already in use | `lsof -ti :5000 \| xargs kill` |
| Port 5001 already in use | `lsof -ti :5001 \| xargs kill` |
| ngrok error: endpoint already online | `pkill ngrok` then re-run `ngrok http 5001` |
| Live dashboard empty after calls | Check http://127.0.0.1:4040 — if events show 500, Flask wasn't running; click Replay on each |
| Signed out unexpectedly | Browser cleared session cookie — just sign in again |
