"""Local Kite authentication and short-lived access-token persistence."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Protocol

from kiteconnect import KiteConnect  # type: ignore[import-untyped]


class KiteClient(Protocol):
    def login_url(self) -> str: ...

    def generate_session(self, request_token: str, api_secret: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class KiteCredentials:
    api_key: str
    api_secret: str


def load_kite_credentials(
    config: dict[str, object], *, profile: str = "market_data"
) -> KiteCredentials | None:
    """Load one isolated Kite profile without ever mixing profile credentials.

    ``market_data`` accepts the retired KITE_* variables and local_secrets.py
    solely as a compatibility migration path.  ``portfolio`` intentionally has
    no fallback: a shared read-only profile must never become an order profile.
    """
    profiles = {
        "market_data": ("MARKET_DATA_KITE", True),
        "portfolio": ("PORTFOLIO_KITE", False),
    }
    try:
        prefix, allow_legacy_fallback = profiles[profile]
    except KeyError as error:
        raise ValueError(f"unknown Kite credential profile: {profile}") from error
    api_key = config.get(f"{prefix}_API_KEY")
    api_secret = config.get(f"{prefix}_API_SECRET")
    if allow_legacy_fallback and api_key is None and api_secret is None:
        api_key = config.get("KITE_API_KEY")
        api_secret = config.get("KITE_API_SECRET")
    if api_key is None and api_secret is None:
        if not allow_legacy_fallback:
            return None
        try:
            from local_secrets import KITE_API_KEY, KITE_API_SECRET
        except ImportError:
            return None
        api_key, api_secret = KITE_API_KEY, KITE_API_SECRET
    if (
        not isinstance(api_key, str)
        or not api_key
        or not isinstance(api_secret, str)
        or not api_secret
    ):
        raise RuntimeError(f"both {prefix}_API_KEY and {prefix}_API_SECRET must be configured")
    return KiteCredentials(api_key=api_key, api_secret=api_secret)


class KiteAuthService:
    """Create Kite login URLs and atomically replace the local access token."""

    def __init__(
        self,
        credentials: KiteCredentials,
        access_token_path: str | Path,
        client_factory: Callable[..., KiteClient] = KiteConnect,
    ) -> None:
        self._credentials = credentials
        self._access_token_path = Path(access_token_path)
        self._client_factory = client_factory

    @property
    def token_exists(self) -> bool:
        return self._access_token_path.is_file() and bool(
            self._access_token_path.read_text(encoding="utf-8").strip()
        )

    def login_url(self) -> str:
        return self._client_factory(api_key=self._credentials.api_key).login_url()

    def exchange_request_token(self, request_token: str) -> None:
        if not isinstance(request_token, str) or not request_token.strip():
            raise ValueError("Kite did not return a request token")
        session = self._client_factory(api_key=self._credentials.api_key).generate_session(
            request_token.strip(), api_secret=self._credentials.api_secret
        )
        access_token = session.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise RuntimeError("Kite did not return an access token")
        self._write_access_token(access_token)

    def _write_access_token(self, access_token: str) -> None:
        self._access_token_path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self._access_token_path.parent,
            delete=False,
            prefix=".kite-access-token-",
        ) as temporary_file:
            temporary_file.write(f"{access_token}\n")
            temporary_path = Path(temporary_file.name)
        try:
            os.replace(temporary_path, self._access_token_path)
        finally:
            temporary_path.unlink(missing_ok=True)
