"""Official PM US retail SDK, exact decimal JSON and trading-only surface.

Construction does no network I/O. Credentials come only from .env. Order POSTs
are never retried, and no funding/key-management endpoint is exposed.
"""

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Protocol

from dotenv import dotenv_values
import httpx
from polymarket_us import PolymarketUS
from polymarket_us.websocket import PrivateWebSocket


def exact_json(value) -> str:
    """Decimal JSON numbers without passing exchange quantities through float."""
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Nonfinite JSON amount")
        return format(value, "f")
    if value is None or isinstance(value, (str, bool, int)):
        return json.dumps(value)
    if isinstance(value, dict) and all(isinstance(k, str) for k in value):
        return "{" + ",".join(json.dumps(k) + ":" + exact_json(v) for k, v in value.items()) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(exact_json(v) for v in value) + "]"
    raise TypeError("Use exact JSON values; float amounts are not supported")


class _ExactClient(httpx.Client):
    def request(self, method, url, **kwargs):
        payload = kwargs.pop("json", None)
        if payload is not None:
            kwargs["content"] = exact_json(payload).encode()
        response = super().request(method, url, **kwargs)
        # Official SDK consumes response.json(); preserve numeric balances and
        # fractional order quantities there as well as string-valued Amounts.
        response.json = lambda **options: json.loads(response.content, parse_float=Decimal, **options)
        return response


@dataclass(frozen=True)
class TradingKeyPolicy:
    """Recorded verification for this key, not a claim inferred from a 200 GET.

    evidence identifies an owner/venue verification that the key may trade and
    cannot withdraw. No permissions are created or changed by this object.
    """
    key_fingerprint: str
    evidence: str
    trading_allowed: bool
    withdrawals_allowed: bool

    def verify(self, fingerprint):
        if (self.key_fingerprint != fingerprint or not self.evidence.strip()
                or self.trading_allowed is not True or self.withdrawals_allowed is not False):
            raise ValueError("Verify trading-only, no-withdrawal permissions for this key first (PRD §6)")


class USAPI(Protocol):
    key_fingerprint: str

    def verify_trading_key(self) -> str: ...
    def balances(self) -> dict: ...
    def market(self, slug: str) -> dict: ...
    def bbo(self, slug: str) -> dict: ...
    def create(self, payload: dict) -> dict: ...
    def order(self, order_id: str) -> dict: ...
    def cancel(self, order_id: str, slug: str) -> None: ...


class PolymarketUSAPI:
    def __init__(self, key_id: str, secret: str, *, key_policy: TradingKeyPolicy | None = None):
        if not key_id or not secret:
            raise ValueError("Existing PM US credentials are required")
        self.key_fingerprint = sha256(key_id.encode()).hexdigest()
        self.key_policy = key_policy
        self._sdk = PolymarketUS(key_id=key_id, secret_key=secret, max_retries=0, timeout=20)
        self._sdk._http.close()
        self._sdk._http = _ExactClient(timeout=httpx.Timeout(20, connect=5))

    @classmethod
    def from_env(cls, path: str | Path = ".env", *, key_policy=None):
        values = dotenv_values(path)
        return cls(values.get("POLYMARKET_US_KEY_ID"), values.get("POLYMARKET_US_SECRET"), key_policy=key_policy)

    @staticmethod
    def _identifier(value):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,255}", value):
            raise ValueError("Invalid PM US resource identifier")
        return value

    def verify_trading_key(self) -> str:
        if self.key_policy is None:
            raise ValueError("Trading-only key permissions have not been verified (PRD §6)")
        self.key_policy.verify(self.key_fingerprint)
        return self.key_policy.evidence

    def balances(self):
        return self._sdk.account.balances()

    def market(self, slug):
        return self._sdk.markets.retrieve_by_slug(self._identifier(slug))

    def bbo(self, slug):
        return self._sdk.markets.bbo(self._identifier(slug))

    def create(self, payload):
        self.verify_trading_key()
        return self._sdk.orders.create(payload)

    def order(self, order_id):
        return self._sdk.orders.retrieve(self._identifier(order_id))

    def cancel(self, order_id, slug):
        self.verify_trading_key()
        return self._sdk.orders.cancel(self._identifier(order_id), {"marketSlug": self._identifier(slug)})

    def private_socket(self, raw_handler):
        """Explicitly constructed, disconnected socket; retain exact JSON numbers.

        The caller connects/subscribes/closes it and handles disconnect incidents.
        SDK authentication/connection handling is reused; its float JSON decoder
        is bypassed so fractional execution quantities remain exact.
        """
        return _RawPrivateSocket(key_id=self._sdk.key_id, secret_key=self._sdk.secret_key,
                                 raw_handler=raw_handler)

    def close(self):
        self._sdk.close()


class _RawPrivateSocket(PrivateWebSocket):
    def __init__(self, *, raw_handler, **kwargs):
        super().__init__(**kwargs)
        self.raw_handler = raw_handler

    def _handle_message(self, data):
        self.raw_handler(data)
