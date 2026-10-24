import json
from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import payments, services
from app.db import get_db
from app.models import Order

router = APIRouter(prefix="/webhooks")

ACTOR = "pinelabs_webhook"

_LINK_ID_KEYS = ("payment_link_id", "paymentLinkId")
_REFERENCE_KEYS = (
    "merchant_payment_link_reference",
    "merchantPaymentLinkReference",
    "merchant_order_reference",
    "merchantOrderReference",
)
_SUCCESS_VALUES = {"PROCESSED", "PARTIAL_PROCESSED", "SUCCESS", "CAPTURED", "PAID", "COMPLETED"}


def _find(payload, keys) -> Optional[str]:
    """Pine Labs nests the interesting fields differently per event type."""
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        for value in payload.values():
            found = _find(value, keys)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _find(item, keys)
            if found:
                return found
    return None


def _locate_order(db: Session, link_id: Optional[str], reference: Optional[str]):
    if link_id:
        # A link id should be unique, but if one is ever reused the newest order
        # still awaiting payment is the only safe match - crediting an order that
        # has already been paid and dispatched would be unrecoverable.
        matches = db.scalars(
            select(Order)
            .where(Order.payment_link_id == link_id)
            .order_by(Order.created_at.desc())
        ).all()
        for order in matches:
            if not order.is_paid:
                return order
        if matches:
            return matches[0]
    if reference:
        return services.get_order(db, reference)
    return None


@router.post("/pinelabs")
async def pinelabs_webhook(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        services.log(db, ACTOR, "webhook_unparseable", raw[:500].decode("utf-8", "replace"))
        db.commit()
        return {"received": True, "handled": False, "reason": "unparseable body"}

    link_id = _find(payload, _LINK_ID_KEYS)
    reference = _find(payload, _REFERENCE_KEYS)
    order = _locate_order(db, link_id, reference)

    services.log(
        db,
        ACTOR,
        "webhook_received",
        json.dumps(payload)[:1000],
        order.id if order else None,
    )
    db.commit()

    if order is None:
        return {"received": True, "handled": False, "reason": "no matching order"}

    # The payload itself is not authenticated, so confirm the state with Pine Labs
    # before moving money-bearing status.
    if not payments.is_configured():
        services.log(db, ACTOR, "webhook_unverified", "payments not configured", order.id)
        db.commit()
        return {"received": True, "handled": False, "reason": "payments not configured"}

    try:
        link = payments.fetch_payment_link(order)
    except Exception as exc:
        services.log(db, ACTOR, "webhook_verify_failed", str(exc), order.id)
        db.commit()
        return {"received": True, "handled": False, "reason": "verification failed"}

    if link.status not in _SUCCESS_VALUES:
        services.log(db, ACTOR, "webhook_ignored", "link status {}".format(link.status), order.id)
        db.commit()
        return {"received": True, "handled": False, "status": order.status}

    try:
        services.mark_paid(
            db, order, ACTOR, link_id or order.payment_link_id, "verified {}".format(link.status)
        )
    except services.OrderError as exc:
        services.log(db, ACTOR, "webhook_skipped", str(exc), order.id)
        db.commit()

    return {"received": True, "handled": True, "order_id": order.id, "status": order.status}
