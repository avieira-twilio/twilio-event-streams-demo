import os
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix
from app.config import config_map
from app.extensions import db, migrate


def create_app():
    app = Flask(__name__)

    env = os.environ.get("FLASK_ENV", "development")
    app.config.from_object(config_map.get(env, config_map["development"]))

    # Required when running behind a reverse proxy (ngrok, nginx, load balancer)
    # so that request.url matches the URL Twilio signed.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    db.init_app(app)
    migrate.init_app(app, db)

    from app.routes.auth import auth_bp
    from app.routes.webhook import webhook_bp
    from app.routes.api import api_bp
    from app.routes.dashboard import dashboard_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(webhook_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(dashboard_bp)

    return app
