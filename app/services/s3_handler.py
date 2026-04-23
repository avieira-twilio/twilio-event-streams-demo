"""
S3 handler — downloads a Twilio recording and uploads it to S3.

Only runs when AWS_S3_BUCKET is set in the environment.
If not configured, recordings are stored as Twilio-only (source="twilio").
"""

import os
import requests
from flask import current_app


def _s3_client():
    try:
        import boto3, certifi
        return boto3.client(
            "s3",
            aws_access_key_id=current_app.config.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=current_app.config.get("AWS_SECRET_ACCESS_KEY"),
            region_name=current_app.config.get("AWS_REGION", "us-east-1"),
            verify=certifi.where(),
        )
    except ImportError:
        return None


def s3_enabled():
    return bool(current_app.config.get("AWS_S3_BUCKET"))


def upload_recording(recording_sid: str, twilio_url: str, account_sid: str, auth_token: str):
    """
    Download recording from Twilio and upload to S3.
    Returns (s3_url, s3_key) on success, (None, None) on failure or if S3 not configured.
    """
    if not s3_enabled():
        return None, None

    bucket = current_app.config["AWS_S3_BUCKET"]
    s3_key = f"recordings/{account_sid}/{recording_sid}.mp3"

    try:
        # Download from Twilio (requires auth)
        response = requests.get(
            twilio_url,
            auth=(account_sid, auth_token),
            timeout=30,
            stream=True,
        )
        response.raise_for_status()

        # Upload to S3
        s3 = _s3_client()
        if s3 is None:
            current_app.logger.error("boto3 not installed — cannot upload to S3")
            return None, None

        s3.upload_fileobj(
            response.raw,
            bucket,
            s3_key,
            ExtraArgs={"ContentType": "audio/mpeg"},
        )

        region = current_app.config.get("AWS_REGION", "us-east-1")
        s3_url = f"https://{bucket}.s3.{region}.amazonaws.com/{s3_key}"
        current_app.logger.info("Uploaded recording %s to S3: %s", recording_sid, s3_key)
        return s3_url, s3_key

    except Exception as e:
        current_app.logger.error("S3 upload failed for %s: %s", recording_sid, e)
        return None, None


def generate_presigned_url(s3_key: str, expires_in: int = 3600):
    """Generate a presigned S3 URL for in-browser playback (valid for 1 hour by default)."""
    if not s3_enabled():
        return None
    try:
        s3 = _s3_client()
        if s3 is None:
            return None
        return s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": current_app.config["AWS_S3_BUCKET"], "Key": s3_key},
            ExpiresIn=expires_in,
        )
    except Exception as e:
        current_app.logger.error("Presigned URL generation failed for %s: %s", s3_key, e)
        return None
