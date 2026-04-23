"""
JSON API endpoints consumed by the dashboard frontend via fetch().

All endpoints require an authenticated session (set by /login).
All list endpoints share a common filter helper for account_sid, status,
and date range.
"""

from datetime import datetime, timezone
from flask import Blueprint, jsonify, request, Response, current_app
from sqlalchemy import func, case
import requests as http_requests

from app.extensions import db
from app.models import CallLog, ConferenceLog, RawEventLog, RecordingLog
from app.routes.auth import require_auth

api_bp = Blueprint("api", __name__, url_prefix="/api")

PAGE_SIZE = 50


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _apply_call_filters(query, args):
    """Apply common query filters to a CallLog query."""
    if args.get("account_sid"):
        query = query.filter(CallLog.account_sid == args["account_sid"])
    if args.get("status"):
        query = query.filter(CallLog.status == args["status"])
    if from_dt := _parse_date(args.get("from")):
        query = query.filter(CallLog.started_at >= from_dt)
    if to_dt := _parse_date(args.get("to")):
        query = query.filter(CallLog.started_at <= to_dt)
    return query


def _apply_conf_filters(query, args):
    if args.get("account_sid"):
        query = query.filter(ConferenceLog.account_sid == args["account_sid"])
    if args.get("status"):
        query = query.filter(ConferenceLog.status == args["status"])
    if from_dt := _parse_date(args.get("from")):
        query = query.filter(ConferenceLog.started_at >= from_dt)
    if to_dt := _parse_date(args.get("to")):
        query = query.filter(ConferenceLog.started_at <= to_dt)
    return query


# ---------------------------------------------------------------------------
# Subaccounts
# ---------------------------------------------------------------------------

@api_bp.get("/subaccounts")
@require_auth
def list_subaccounts():
    """Return distinct account SIDs seen across call and conference logs."""
    call_sids = db.session.query(CallLog.account_sid).distinct()
    conf_sids = db.session.query(ConferenceLog.account_sid).distinct()
    all_sids = sorted({r[0] for r in call_sids.union(conf_sids).all()})
    return jsonify(all_sids)


# ---------------------------------------------------------------------------
# Call logs
# ---------------------------------------------------------------------------

@api_bp.get("/calls")
@require_auth
def list_calls():
    page = max(1, int(request.args.get("page", 1)))
    query = _apply_call_filters(
        CallLog.query.order_by(CallLog.started_at.desc()), request.args
    )
    total = query.count()
    rows = query.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()
    return jsonify({
        "total": total,
        "page": page,
        "pages": max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE),
        "items": [r.to_dict() for r in rows],
    })


# ---------------------------------------------------------------------------
# Conference logs
# ---------------------------------------------------------------------------

@api_bp.get("/conferences")
@require_auth
def list_conferences():
    page = max(1, int(request.args.get("page", 1)))
    query = _apply_conf_filters(
        ConferenceLog.query.order_by(ConferenceLog.started_at.desc()), request.args
    )
    total = query.count()
    rows = query.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()
    return jsonify({
        "total": total,
        "page": page,
        "pages": max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE),
        "items": [r.to_dict() for r in rows],
    })


# ---------------------------------------------------------------------------
# Chart data
# ---------------------------------------------------------------------------

@api_bp.get("/charts/call-volume")
@require_auth
def chart_call_volume():
    """Daily call counts grouped by account_sid."""
    query = _apply_call_filters(
        db.session.query(
            func.date(CallLog.started_at).label("date"),
            CallLog.account_sid,
            func.count(CallLog.id).label("count"),
        ).group_by(func.date(CallLog.started_at), CallLog.account_sid)
         .order_by(func.date(CallLog.started_at)),
        request.args,
    )
    rows = query.all()
    return jsonify([
        {"date": str(r.date), "account_sid": r.account_sid, "count": r.count}
        for r in rows
    ])


@api_bp.get("/charts/call-duration")
@require_auth
def chart_call_duration():
    """Average call duration per account_sid."""
    query = _apply_call_filters(
        db.session.query(
            CallLog.account_sid,
            func.avg(CallLog.duration_seconds).label("avg_duration"),
            func.max(CallLog.duration_seconds).label("max_duration"),
        ).filter(CallLog.duration_seconds.isnot(None))
         .group_by(CallLog.account_sid),
        request.args,
    )
    rows = query.all()
    return jsonify([
        {
            "account_sid": r.account_sid,
            "avg_duration": round(r.avg_duration or 0, 1),
            "max_duration": r.max_duration or 0,
        }
        for r in rows
    ])


@api_bp.get("/charts/error-rate")
@require_auth
def chart_error_rate():
    """Daily error counts vs. total calls, per account_sid."""
    query = _apply_call_filters(
        db.session.query(
            func.date(CallLog.started_at).label("date"),
            CallLog.account_sid,
            func.count(CallLog.id).label("total"),
            func.sum(
                case((CallLog.status.in_(["failed", "busy", "no-answer"]), 1), else_=0)
            ).label("errors"),
        ).group_by(func.date(CallLog.started_at), CallLog.account_sid)
         .order_by(func.date(CallLog.started_at)),
        request.args,
    )
    rows = query.all()
    return jsonify([
        {
            "date": str(r.date),
            "account_sid": r.account_sid,
            "total": r.total,
            "errors": int(r.errors or 0),
        }
        for r in rows
    ])


@api_bp.get("/charts/call-status")
@require_auth
def chart_call_status():
    """Call status breakdown (all time or filtered) per account_sid."""
    query = _apply_call_filters(
        db.session.query(
            CallLog.account_sid,
            CallLog.status,
            func.count(CallLog.id).label("count"),
        ).group_by(CallLog.account_sid, CallLog.status),
        request.args,
    )
    rows = query.all()
    return jsonify([
        {"account_sid": r.account_sid, "status": r.status, "count": r.count}
        for r in rows
    ])


# ---------------------------------------------------------------------------
# Recording logs
# ---------------------------------------------------------------------------

def _apply_recording_filters(query, args):
    if args.get("account_sid"):
        query = query.filter(RecordingLog.account_sid == args["account_sid"])
    if args.get("status"):
        query = query.filter(RecordingLog.status == args["status"])
    if from_dt := _parse_date(args.get("from")):
        query = query.filter(RecordingLog.recorded_at >= from_dt)
    if to_dt := _parse_date(args.get("to")):
        query = query.filter(RecordingLog.recorded_at <= to_dt)
    return query


@api_bp.get("/recordings")
@require_auth
def list_recordings():
    page = max(1, int(request.args.get("page", 1)))
    query = _apply_recording_filters(
        RecordingLog.query.order_by(RecordingLog.recorded_at.desc()), request.args
    )
    total = query.count()
    rows = query.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()
    return jsonify({
        "total": total,
        "page": page,
        "pages": max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE),
        "items": [r.to_dict() for r in rows],
    })


@api_bp.get("/recordings/proxy/<recording_sid>")
@require_auth
def proxy_recording(recording_sid):
    """Stream a Twilio-hosted recording to the browser (avoids CORS + auth headers)."""
    rec = RecordingLog.query.filter_by(recording_sid=recording_sid).first()
    if rec is None:
        return jsonify({"error": "not found"}), 404
    if not rec.twilio_url:
        return jsonify({"error": "no twilio url"}), 404

    auth_token = current_app.config.get("TWILIO_AUTH_TOKEN", "")
    try:
        resp = http_requests.get(
            rec.twilio_url,
            auth=(rec.account_sid, auth_token),
            stream=True,
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        current_app.logger.error("Recording proxy failed for %s: %s", recording_sid, e)
        return jsonify({"error": "upstream fetch failed"}), 502

    return Response(
        resp.iter_content(chunk_size=8192),
        content_type=resp.headers.get("Content-Type", "audio/mpeg"),
        headers={"Content-Disposition": f'inline; filename="{recording_sid}.mp3"'},
    )


@api_bp.get("/recordings/presign/<recording_sid>")
@require_auth
def presign_recording(recording_sid):
    """Return a short-lived S3 presigned URL for browser playback."""
    rec = RecordingLog.query.filter_by(recording_sid=recording_sid).first()
    if rec is None:
        return jsonify({"error": "not found"}), 404
    if not rec.s3_key:
        return jsonify({"error": "not in s3"}), 404

    from app.services.s3_handler import generate_presigned_url
    url = generate_presigned_url(rec.s3_key)
    if url is None:
        return jsonify({"error": "presign failed"}), 500
    return jsonify({"url": url})


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@api_bp.get("/health")
def health():
    """Public health endpoint: latest event time + unprocessed count."""
    latest = RawEventLog.query.order_by(RawEventLog.received_at.desc()).first()
    unprocessed = RawEventLog.query.filter_by(processed=False).count()
    return jsonify({
        "status": "ok",
        "latest_event_at": latest.received_at.isoformat() if latest else None,
        "unprocessed_count": unprocessed,
    })
