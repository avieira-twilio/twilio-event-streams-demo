from functools import wraps
from flask import (
    Blueprint, request, session, redirect, url_for,
    render_template, current_app, jsonify,
)

auth_bp = Blueprint("auth", __name__)


def require_auth(f):
    """Decorator: redirect to login for HTML routes, 401 for API routes."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Unauthorized"}), 401
            return redirect(url_for("auth.login", next=request.path))
        return f(*args, **kwargs)
    return decorated


@auth_bp.get("/login")
def login():
    return render_template("login.html")


@auth_bp.post("/login")
def login_post():
    token = request.form.get("token", "").strip()
    if token == current_app.config["DASHBOARD_TOKEN"]:
        session["authenticated"] = True
        next_url = request.args.get("next") or url_for("dashboard.index")
        return redirect(next_url)
    return render_template("login.html", error="Invalid access token.")


@auth_bp.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
