"""Create a fresh Kite access token without exposing local credentials in logs.

Run ``--open-login``, complete the Kite login in the browser, then run this
script with the short-lived request token returned to the configured redirect
URL. The generated access token is atomically written to ``access_token.txt``.
"""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from pathlib import Path
from tempfile import NamedTemporaryFile

from kiteconnect import KiteConnect  # type: ignore[import-untyped]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOKEN_PATH = PROJECT_ROOT / "access_token.txt"


def _kite_client() -> tuple[KiteConnect, str]:
    try:
        from local_secrets import KITE_API_KEY, KITE_API_SECRET
    except ImportError as exc:
        raise RuntimeError("local_secrets.py with Kite credentials is required") from exc
    return KiteConnect(api_key=KITE_API_KEY), KITE_API_SECRET


def _write_token(access_token: str) -> None:
    with NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=PROJECT_ROOT, delete=False, prefix=".access-token-"
    ) as temporary_file:
        temporary_file.write(f"{access_token}\n")
        temporary_path = Path(temporary_file.name)
    try:
        os.replace(temporary_path, TOKEN_PATH)
    finally:
        temporary_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--open-login", action="store_true", help="Open the Kite login page.")
    mode.add_argument("--request-token", help="Exchange a request token for a new access token.")
    arguments = parser.parse_args()

    try:
        client, api_secret = _kite_client()
        if arguments.open_login:
            if not webbrowser.open(client.login_url(), new=1):
                raise RuntimeError("could not open the default browser")
            print("Kite login opened in the default browser.")
            return 0

        session = client.generate_session(arguments.request_token, api_secret=api_secret)
        _write_token(str(session["access_token"]))
        print("Kite access token refreshed in access_token.txt.")
        return 0
    except Exception as exc:  # noqa: BLE001 - do not leak credentials or server details
        print(f"Kite token initialization failed: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
