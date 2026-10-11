"""Local browser flow for refreshing the daily Kite access token."""

from __future__ import annotations

import logging
import time
from html import escape

from flask import Blueprint, Response, jsonify, redirect, request, session, url_for
from flask.typing import ResponseReturnValue
from kiteconnect.exceptions import KiteException  # type: ignore[import-untyped]

from src.domains.execution import KiteAuthService
from src.platform_kernel import DomainValidationError

_SESSION_STARTED_AT = "kite_authorization_started_at"
_SESSION_TTL_SECONDS = 10 * 60
_LOGGER = logging.getLogger(__name__)


def create_kite_auth_blueprint(
    market_data_service: KiteAuthService | None,
    portfolio_service: KiteAuthService | None = None,
    portfolio_accounts=None,
) -> Blueprint:
    """Build isolated local browser flows for market and portfolio profiles."""
    blueprint = Blueprint("kite_auth", __name__)

    @blueprint.get("/")
    def home() -> ResponseReturnValue:
        if market_data_service is not None and not market_data_service.token_exists:
            return redirect(url_for("kite_auth.authorization_page"))
        return redirect(url_for("dashboard.home"))

    @blueprint.get("/integrations/kite")
    def authorization_page() -> Response:
        if request.args.get("auto") == "1" and market_data_service is not None:
            session.pop("portfolio_broker_authorization", None)
            session[f"{_SESSION_STARTED_AT}:market-data"] = time.time()
            return redirect(market_data_service.login_url())
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
            "Set MARKET_DATA_KITE_API_KEY and MARKET_DATA_KITE_API_SECRET, or configure local_secrets.py."
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
            "Broker-confirmed Kite activity and manually recorded transactions are both reflected in the portfolio.</p>"
            if profile == "portfolio"
            else "<p>This shared profile is used only by market-data jobs.</p>"
        )
        return Response(
            f"""<!doctype html><title>{escape(profile_label)} Kite authorization</title>
<main><h1>{escape(profile_label)} Kite authorization</h1><p>{escape(message)}</p>
<p>Saved token: <strong>{token_status}</strong></p>
{portfolio_note}
<p><a href="/">Return to the screener</a></p>
<button id=authorize {disabled}>Authorize Kite for today</button><p id=status></p></main>
<script>
document.getElementById('authorize').addEventListener('click', async () => {{
  const response = await fetch('/api/integrations/kite/{profile}/authorize', {{
    method: 'POST'
  }});
  if (!response.ok) {{ document.getElementById('status').textContent = 'Authorization could not start.'; return; }}
  window.location.assign((await response.json()).authorization_url);
}});
</script>""",
            mimetype="text/html",
        )

    @blueprint.post("/api/integrations/kite/<profile>/authorize")
    def start_authorization(profile: str) -> ResponseReturnValue:
        service = _service_for(profile)
        return _start_authorization(service, profile)

    @blueprint.get("/api/integrations/kite/<profile>/status")
    def profile_status(profile: str) -> ResponseReturnValue:
        service = _service_for(profile)
        if service is None:
            return jsonify({"configured": False, "status": "NOT_CONFIGURED", "login_required": False})
        pending = session.get("portfolio_broker_authorization")
        started = pending.get("started_at") if isinstance(pending, dict) else None
        shared_started = session.get(f"{_SESSION_STARTED_AT}:market-data")
        login_in_progress = any(
            isinstance(value, (int, float)) and 0 <= time.time() - value <= _SESSION_TTL_SECONDS
            for value in (started, shared_started)
        )
        return jsonify({**service.session_status(), "login_in_progress": login_in_progress})

    def _start_authorization(service: KiteAuthService | None, profile: str) -> ResponseReturnValue:
        if service is None:
            return jsonify({"error": f"Kite {profile} credentials are not configured"}), 503
        session.pop("portfolio_broker_authorization", None)
        session[f"{_SESSION_STARTED_AT}:{profile}"] = time.time()
        return jsonify({"authorization_url": service.login_url()})

    @blueprint.get("/integrations/kite/callback")
    def market_data_callback() -> Response:
        """Route the registered callback to the login started in this browser."""
        if "portfolio_broker_authorization" in session:
            return profile_callback("portfolio")
        return _callback("market-data", market_data_service)

    @blueprint.get("/integrations/kite/<profile>/callback")
    def profile_callback(profile: str) -> Response:
        if profile == "market-data" and "portfolio_broker_authorization" in session:
            return profile_callback("portfolio")
        if profile == "portfolio" and "portfolio_broker_authorization" in session:
            pending = session.pop("portfolio_broker_authorization")
            if (
                portfolio_accounts is None
                or not isinstance(pending, dict)
                or not isinstance(pending.get("started_at"), (int, float))
                or not 0 <= time.time() - pending["started_at"] <= _SESSION_TTL_SECONDS
            ):
                return Response("Start portfolio Kite login again from the app.", status=400)
            if request.args.get("status") != "success":
                return Response("Portfolio Kite login was not completed. Start again from the app.", status=400)
            try:
                portfolio_accounts.authenticate(
                    pending["broker_account_id"], request.args.get("request_token", "")
                )
            except (KeyError, DomainValidationError):
                return Response("Portfolio Kite login failed. Start again from the app.", status=400)
            response = redirect(url_for("dashboard.home"))
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
            return response
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
        if (
            not isinstance(started_at, float) or time.time() - started_at > _SESSION_TTL_SECONDS
        ):
            return Response("Start Kite authorization from this app, then try again.", status=400)
        if request.args.get("status") != "success":
            return Response("Kite authorization was not completed.", status=400)
        try:
            service.exchange_request_token(request.args.get("request_token", ""))
        except (KiteException, OSError, RuntimeError, ValueError) as exc:
            _LOGGER.warning("Kite token exchange failed (%s): %s", type(exc).__name__, str(exc))
            detail = " ".join(str(exc).split()) or "no diagnostic message"
            network_denied = "forbidden by its access permissions" in detail.lower()
            guidance = (
                "Outbound HTTPS from the Python application is blocked. Allow Python to connect to "
                "api.kite.trade:443, then start authorization again."
                if network_denied
                else "Start authorization again."
            )
            return Response(
                f"Kite token refresh failed ({type(exc).__name__}): {escape(detail)} "
                f"{escape(guidance)}",
                status=502,
            )
        return redirect(url_for("dashboard.home"))

    return blueprint
