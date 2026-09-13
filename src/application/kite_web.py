"""Local browser flow for refreshing the daily Kite access token."""

from __future__ import annotations

import secrets
import time
from html import escape

from flask import Blueprint, Response, current_app, jsonify, redirect, request, session, url_for
from flask.typing import ResponseReturnValue
from kiteconnect.exceptions import KiteException  # type: ignore[import-untyped]

from src.application.kite_auth import KiteAuthService

_SESSION_STARTED_AT = "kite_authorization_started_at"
_SESSION_TTL_SECONDS = 10 * 60


def create_kite_auth_blueprint(
    market_data_service: KiteAuthService | None,
    portfolio_service: KiteAuthService | None = None,
) -> Blueprint:
    """Build isolated local browser flows for market and portfolio profiles."""
    blueprint = Blueprint("kite_auth", __name__)

    @blueprint.get("/")
    def home() -> ResponseReturnValue:
        if "request_token" in request.args or "status" in request.args:
            return _callback("market-data", market_data_service)
        return redirect(url_for("dashboard_v2.dashboard"))

    @blueprint.get("/integrations/kite")
    def authorization_page() -> Response:
        return _authorization_page("market-data", market_data_service)

    @blueprint.get("/integrations/kite/portfolio")
    def portfolio_authorization_page() -> Response:
        return _authorization_page("portfolio", portfolio_service)

    def _authorization_page(profile: str, service: KiteAuthService | None) -> Response:
        configured = service is not None
        token_status = "present" if service is not None and service.token_exists else "missing"
        disabled = "" if configured else "disabled"
        profile_label = "Shared market-data" if profile == "market-data" else "Portfolio"
        credential_message = (
            "Set MARKET_DATA_KITE_API_KEY and MARKET_DATA_KITE_API_SECRET. "
            "The retired KITE_* variables remain a temporary market-data fallback."
            if profile == "market-data"
            else "Set PORTFOLIO_KITE_API_KEY and PORTFOLIO_KITE_API_SECRET. "
            "This profile never falls back to shared market-data credentials."
        )
        message = (
            f"Kite credentials are not configured. {credential_message}"
            if not configured
            else "A fresh Kite access token is required each trading day."
        )
        portfolio_note = (
            "<p>Portfolio authorization is isolated for a future broker gateway. "
            "V4 currently remains paper-execution only and will not place Kite orders.</p>"
            if profile == "portfolio"
            else "<p>This shared profile is used only by market-data jobs.</p>"
        )
        return Response(
            f"""<!doctype html><title>{escape(profile_label)} Kite authorization</title>
<main><h1>{escape(profile_label)} Kite authorization</h1><p>{escape(message)}</p>
<p>Saved token: <strong>{token_status}</strong></p>
{portfolio_note}
<p><a href="/app">Return to the screener</a></p>
<button id=authorize {disabled}>Authorize Kite for today</button><p id=status></p></main>
<script>
document.getElementById('authorize').addEventListener('click', async () => {{
  const token = window.prompt('Enter the local operator token');
  if (!token) return;
  const response = await fetch('/api/v2/integrations/kite/{profile}/authorize', {{
    method: 'POST', headers: {{'X-Operator-Token': token}}
  }});
  if (!response.ok) {{ document.getElementById('status').textContent = 'Authorization could not start.'; return; }}
  window.location.assign((await response.json()).authorization_url);
}});
</script>""",
            mimetype="text/html",
        )

    @blueprint.post("/api/v2/integrations/kite/authorize")
    def start_market_data_authorization_compatibility() -> ResponseReturnValue:
        return _start_authorization(market_data_service, "market-data")

    @blueprint.post("/api/v2/integrations/kite/<profile>/authorize")
    def start_authorization(profile: str) -> ResponseReturnValue:
        service = _service_for(profile)
        return _start_authorization(service, profile)

    def _start_authorization(service: KiteAuthService | None, profile: str) -> ResponseReturnValue:
        if service is None:
            return jsonify({"error": f"Kite {profile} credentials are not configured"}), 503
        configured_operator_token = current_app.config.get("OPERATOR_TOKEN")
        supplied_operator_token = request.headers.get("X-Operator-Token", "")
        if not isinstance(configured_operator_token, str) or not configured_operator_token:
            return jsonify({"error": "operator token is not configured"}), 503
        if not secrets.compare_digest(supplied_operator_token, configured_operator_token):
            return jsonify({"error": "operator token is required"}), 401
        session[f"{_SESSION_STARTED_AT}:{profile}"] = time.time()
        return jsonify({"authorization_url": service.login_url()})

    @blueprint.get("/integrations/kite/callback")
    def callback() -> Response:
        return _callback("market-data", market_data_service)

    @blueprint.get("/integrations/kite/<profile>/callback")
    def profile_callback(profile: str) -> Response:
        return _callback(profile, _service_for(profile))

    def _service_for(profile: str) -> KiteAuthService | None:
        if profile == "market-data":
            return market_data_service
        if profile == "portfolio":
            return portfolio_service
        return None

    def _callback(profile: str, service: KiteAuthService | None) -> Response:
        if service is None:
            return Response("Kite credentials are not configured.", status=503)
        started_at = session.pop(f"{_SESSION_STARTED_AT}:{profile}", None)
        if not isinstance(started_at, float) or time.time() - started_at > _SESSION_TTL_SECONDS:
            return Response("Start Kite authorization from this app, then try again.", status=400)
        if request.args.get("status") != "success":
            return Response("Kite authorization was not completed.", status=400)
        try:
            service.exchange_request_token(request.args.get("request_token", ""))
        except (KiteException, OSError, RuntimeError, ValueError):
            return Response("Kite token refresh failed. Start authorization again.", status=502)
        return Response(
            "<!doctype html><title>Kite authorized</title><main><h1>Kite authorized</h1>"
            "<p>The local access token has been refreshed. You can close this tab.</p></main>",
            mimetype="text/html",
        )

    return blueprint
