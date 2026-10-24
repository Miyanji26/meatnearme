import datetime as dt
import threading
import time
import uuid
from typing import Optional

from pinelabs import Amount, PinelabsApi
from pinelabs.types import PaymentLinkCustomer

from app import config

_lock = threading.Lock()
_token_cache: Optional[dict] = None

PAID_LINK_STATUSES = {"PROCESSED", "PARTIAL_PROCESSED"}


class PaymentsNotConfigured(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(config.PINELABS_CLIENT_ID and config.PINELABS_CLIENT_SECRET)


def _expiry_epoch(response) -> float:
    expires_at = getattr(response, "expires_at", None)
    if isinstance(expires_at, dt.datetime):
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=dt.timezone.utc)
        return expires_at.timestamp()
    return time.time() + 3000


def _access_token() -> str:
    global _token_cache
    with _lock:
        if _token_cache and time.time() < _token_cache["expires_at"] - 30:
            return _token_cache["value"]

        # The /token endpoint authenticates via the request body, so this bootstrap
        # client is created with an empty token.
        bootstrap = PinelabsApi(base_url=config.PINELABS_BASE_URL, token="")
        response = bootstrap.authentication.generate_token(
            grant_type="client_credentials",
            client_id=config.PINELABS_CLIENT_ID,
            client_secret=config.PINELABS_CLIENT_SECRET,
        )
        _token_cache = {
            "value": response.access_token,
            "expires_at": _expiry_epoch(response),
        }
        return _token_cache["value"]


def _client() -> PinelabsApi:
    if not is_configured():
        raise PaymentsNotConfigured(
            "PINELABS_CLIENT_ID / PINELABS_CLIENT_SECRET are not set"
        )
    return PinelabsApi(
        base_url=config.PINELABS_BASE_URL,
        token=_access_token(),
        request_id=str(uuid.uuid4()),
        request_timestamp=dt.datetime.now(dt.timezone.utc),
    )


def _split_name(full_name: str):
    parts = (full_name or "").strip().split()
    if not parts:
        return ("Customer", "")
    return (parts[0], " ".join(parts[1:]))


ALL_METHODS = ["UPI", "CARD", "NETBANKING", "WALLET"]


def _methods_for(preferred: Optional[str]) -> list:
    """Lead with what the buyer picked at checkout, but never lock out the rest -
    a declined card should not mean starting the order again."""
    if preferred in ALL_METHODS:
        return [preferred] + [m for m in ALL_METHODS if m != preferred]
    return list(ALL_METHODS)


def create_payment_link(order, amount_paisa: int, reference: str = None):
    # merchant_payment_link_reference is Pine Labs' idempotency key, so a genuine
    # re-issue has to pass a fresh one or the original link comes back.
    first_name, last_name = _split_name(order.customer_name)
    response = _client().payment_links.create_payment_link(
        amount=Amount(value=amount_paisa, currency="INR"),
        merchant_payment_link_reference=reference or order.id,
        description="{} order {} - {}".format(config.APP_NAME, order.id, order.store.name),
        expire_by=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=24),
        allowed_payment_methods=_methods_for(order.payment_method),
        customer=PaymentLinkCustomer(
            first_name=first_name,
            last_name=last_name or None,
            mobile_number=order.phone,
            country_code="+91",
        ),
        callback_url="{}/order/{}".format(config.PUBLIC_BASE_URL, order.id),
    )
    return response


def fetch_payment_link(order):
    if order.payment_link_id:
        return _client().payment_links.get_payment_link_by_id(order.payment_link_id)
    return _client().payment_links.get_payment_link_by_merchant_reference(order.id)
