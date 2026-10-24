"""Cart kept in a signed cookie.

No server-side cart table: the basket is small, anonymous and short-lived, and a
signed cookie keeps the app stateless across Render's ephemeral instances. The
signature stops a buyer from editing quantities or prices - and prices are never
stored in the cookie anyway, they are re-read from the catalogue on every render.
"""

from typing import Optional

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select

from app import config
from app.models import Product

_serializer = URLSafeTimedSerializer(config.SECRET_KEY, salt="mnm-cart")

MAX_LINES = 20
MAX_QTY = 20000  # 20 kg or 20 pieces - a sanity ceiling, not a business rule


def empty() -> dict:
    return {"store_id": None, "lines": {}}


def load(request) -> dict:
    raw = request.cookies.get(config.CART_COOKIE)
    if not raw:
        return empty()
    try:
        data = _serializer.loads(raw, max_age=config.CART_MAX_AGE)
    except (BadSignature, SignatureExpired, ValueError):
        return empty()
    if not isinstance(data, dict):
        return empty()

    lines = {}
    for key, value in (data.get("lines") or {}).items():
        try:
            product_id, qty = int(key), int(value)
        except (TypeError, ValueError):
            continue
        if 0 < qty <= MAX_QTY:
            lines[product_id] = qty

    store_id = data.get("store_id")
    return {"store_id": int(store_id) if store_id else None, "lines": lines}


def save(response, cart: dict) -> None:
    if not cart.get("lines"):
        clear(response)
        return
    payload = {
        "store_id": cart.get("store_id"),
        "lines": {str(k): int(v) for k, v in cart["lines"].items()},
    }
    response.set_cookie(
        config.CART_COOKIE,
        _serializer.dumps(payload),
        max_age=config.CART_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=config.PUBLIC_BASE_URL.startswith("https://"),
    )


def clear(response) -> None:
    response.delete_cookie(config.CART_COOKIE)


def add(cart: dict, product: Product, qty: int) -> dict:
    """Switching stores starts a fresh basket - one butcher cuts one order."""
    if cart.get("store_id") != product.store_id:
        cart = {"store_id": product.store_id, "lines": {}}

    lines = dict(cart["lines"])
    current = lines.get(product.id, 0)
    new_qty = min(current + max(qty, 0), MAX_QTY)
    if new_qty > 0:
        lines[product.id] = new_qty
    if len(lines) > MAX_LINES:
        lines.pop(product.id, None)
    return {"store_id": product.store_id, "lines": lines}


def set_qty(cart: dict, product_id: int, qty: int) -> dict:
    lines = dict(cart["lines"])
    if qty <= 0:
        lines.pop(product_id, None)
    else:
        lines[product_id] = min(qty, MAX_QTY)
    return {"store_id": cart.get("store_id") if lines else None, "lines": lines}


def count(cart: dict) -> int:
    return len(cart.get("lines") or {})


def _delivery_fee(items_paisa: int) -> int:
    if items_paisa <= 0:
        return 0
    if items_paisa >= config.FREE_DELIVERY_ABOVE_PAISA:
        return 0
    return config.DELIVERY_FEE_PAISA


def summary(db, cart: dict) -> dict:
    """Re-price the basket against the live catalogue."""
    ids = list((cart.get("lines") or {}).keys())
    if not ids:
        return {
            "store": None,
            "lines": [],
            "items_paisa": 0,
            "weight_g": 0,
            "delivery_fee_paisa": 0,
            "total_paisa": 0,
            "free_delivery_gap_paisa": config.FREE_DELIVERY_ABOVE_PAISA,
        }

    products = {
        p.id: p
        for p in db.scalars(
            select(Product).where(Product.id.in_(ids), Product.is_active.is_(True))
        )
    }

    lines = []
    for product_id, qty in cart["lines"].items():
        product = products.get(product_id)
        if product is None:  # delisted since it was added
            continue
        lines.append(
            {
                "product": product,
                "qty": qty,
                "weight_g": product.weight_for(qty),
                "amount_paisa": product.price_for(qty),
            }
        )
    lines.sort(key=lambda line: line["product"].name)

    items_paisa = sum(line["amount_paisa"] for line in lines)
    delivery = _delivery_fee(items_paisa)
    store = lines[0]["product"].store if lines else None

    return {
        "store": store,
        "lines": lines,
        "items_paisa": items_paisa,
        "weight_g": sum(line["weight_g"] for line in lines),
        "delivery_fee_paisa": delivery,
        "total_paisa": items_paisa + delivery,
        "free_delivery_gap_paisa": max(
            config.FREE_DELIVERY_ABOVE_PAISA - items_paisa, 0
        ),
    }


KG_STEPS = [250, 500, 750, 1000, 1500, 2000, 3000, 5000]
PIECE_STEPS = [1, 2, 4, 6, 12, 18, 30]


def qty_options(product: Product, current: int = None) -> list:
    """Quantity choices for a line, always including whatever is already selected."""
    steps = list(KG_STEPS if product.unit == "kg" else PIECE_STEPS)
    if current and current not in steps:
        steps.append(current)
    steps.sort()
    return [
        {
            "qty": qty,
            "label": qty_label(product, qty),
            "amount": product.price_for(qty),
            "selected": qty == current,
        }
        for qty in steps
    ]


def qty_label(product: Product, qty: int) -> str:
    if product.unit == "kg":
        if qty < 1000:
            return "{} g".format(qty)
        return "{:.2f} kg".format(qty / 1000.0).replace(".00 kg", " kg")
    return "{} pc".format(qty) if qty == 1 else "{} pcs".format(qty)


def from_parsed_items(items: list, products_by_id: dict) -> Optional[dict]:
    """Turn kasai.ai's parsed basket into a cart the buyer can confirm."""
    cart = empty()
    for item in items:
        product = products_by_id.get(item.get("product_id"))
        if product is None:
            continue
        if product.unit == "kg":
            qty = int(item.get("weight_g") or 0)
        else:
            qty = int(round(float(item.get("qty") or 0)))
        if qty > 0:
            cart = add(cart, product, qty)
    return cart if cart["lines"] else None
