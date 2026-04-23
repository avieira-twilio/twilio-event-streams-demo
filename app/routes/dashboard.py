from flask import Blueprint, render_template
from app.routes.auth import require_auth

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.get("/")
@require_auth
def index():
    return render_template("dashboard.html")
