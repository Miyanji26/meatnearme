from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import config, pricing, services
from app.db import get_db
from app.models import CATEGORY_LABELS, STATUS_LABELS, Order
from app.security import require_agent_key

router = APIRouter(prefix="/tools", dependencies=[Depends(require_agent_key)])

AGENT = "agent"


class CreateOrderRequest(BaseModel):
    customer_name: str = Field(..., min_length=1, max_length=160)
    phone: str = Field(..., min_length=5, max_length=32)
    address: str = Field(..., min_length=1)
    order_text: str = Field(..., min_length=1)
    store_id: int = Field(None)


def _store_payload(store) -> dict:
    return {
        "id": store.id,
        "name": store.name,
        "locality": store.locality,
        "city": store.city,
        "phone": store.phone,
        "address": store.address,
        "rating": store.rating,
        "rating_count": store.rating_count,
        "distance_km": store.distance_km,
        "services": store.service_list(),
        "is_open": store.is_open,
        "hours": "{}-{}".format(store.opens_at or "?", store.closes_at or "?"),
        "starting_price_paisa": store.starting_price_paisa,
    }


def _order_payload(order: Order) -> dict:
    return {
        "order_id": order.id,
        "status": order.status,
        "status_label": STATUS_LABELS.get(order.status, order.status),
        "store": _store_payload(order.store),
        "customer_name": order.customer_name,
        "phone": order.phone,
        "address": order.address,
        "order_text": order.order_text,
        "items": [item.as_dict() for item in order.items],
        "expected_weight_g": order.expected_weight_g,
        "items_paisa": order.items_paisa,
        "delivery_fee_paisa": order.delivery_fee_paisa,
        "amount_paisa": order.amount_paisa,
        "actual_weight_g": order.actual_weight_g,
        "actual_value_paisa": order.actual_value_paisa,
        "paid": order.is_paid,
        "payment_link": order.payment_link,
        "payment_link_id": order.payment_link_id,
        "track_url": "{}/order/{}".format(config.PUBLIC_BASE_URL, order.id),
        "created_at": order.created_at.isoformat(),
        "updated_at": order.updated_at.isoformat(),
    }


def _require_order(db: Session, order_id: str) -> Order:
    order = services.get_order(db, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order {} not found".format(order_id))
    return order


def _require_store(db: Session, store_id: int = None):
    store = services.get_store(db, store_id) if store_id else services.active_store(db)
    if store is None:
        raise HTTPException(status_code=404 if store_id else 503, detail="No such store")
    return store


@router.get("/stores")
def list_stores(db: Session = Depends(get_db), locality: str = None):
    stores = services.stores_in(db, locality)
    services.log(db, AGENT, "stores_read", "{} stores".format(len(stores)))
    db.commit()
    return {
        "localities": services.localities(db),
        "stores": [_store_payload(store) for store in stores],
    }


@router.get("/price_list")
def price_list(db: Session = Depends(get_db), store_id: int = None):
    store = _require_store(db, store_id)

    products = services.price_list(db, store.id)
    services.log(db, AGENT, "price_list_read", "{} products".format(len(products)))
    db.commit()

    return {
        "store": _store_payload(store),
        "currency": "INR",
        "note": "Catalogue prices are final. The buyer pays at checkout and the butcher "
        "cuts to that order.",
        "products": [
            {
                "id": p.id,
                "name": p.name,
                "category": p.category,
                "category_label": CATEGORY_LABELS.get(p.category, p.category),
                "aliases": [a for a in p.alias_list() if a != p.name.lower()],
                "unit": p.unit,
                "price_paisa": p.price_paisa,
                "price_display": "{} per {}".format(pricing.rupees(p.price_paisa), p.unit),
                "typical_weight_g": p.typical_weight_g,
                "min_step": p.step,
            }
            for p in products
        ],
    }


@router.post("/create_order", status_code=201)
def create_order(payload: CreateOrderRequest, db: Session = Depends(get_db)):
    store = _require_store(db, payload.store_id)

    try:
        order = services.create_order_from_text(
            db,
            store,
            payload.customer_name,
            payload.phone,
            payload.address,
            payload.order_text,
            actor=AGENT,
        )
    except services.OrderError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return _order_payload(order)


@router.get("/order/{order_id}")
def get_order(order_id: str, db: Session = Depends(get_db)):
    order = _require_order(db, order_id)
    services.log(db, AGENT, "order_read", None, order.id)
    db.commit()
    return _order_payload(order)


@router.get("/check_payment/{order_id}")
def check_payment(order_id: str, db: Session = Depends(get_db)):
    order = _require_order(db, order_id)

    try:
        services.sync_payment_status(db, order, actor=AGENT)
    except Exception as exc:
        services.log(db, AGENT, "payment_check_failed", str(exc), order.id)
        db.commit()
        raise HTTPException(status_code=502, detail="Payment lookup failed: {}".format(exc))

    services.log(db, AGENT, "payment_checked", order.status, order.id)
    db.commit()

    return {
        "order_id": order.id,
        "status": order.status,
        "paid": order.is_paid,
        "amount_paisa": order.amount_paisa,
        "payment_link": order.payment_link,
        "payment_link_id": order.payment_link_id,
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
    }
