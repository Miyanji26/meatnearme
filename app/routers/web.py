from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import cart as cart_lib
from app import config, payments, pricing, security, services
from app.db import get_db
from app.models import (
    CATEGORIES,
    CATEGORY_LABELS,
    STATUS_DISPATCHED,
    STATUS_LINK_SENT,
    STATUS_NEW,
    STATUS_PAID,
    STATUS_WEIGHED,
)
from app.templating import templates

router = APIRouter()

# Pine Labs carries every online method; the choice is passed through as a hint.
PAYMENT_METHODS = [
    ("UPI", "UPI", "Google Pay, PhonePe, Paytm"),
    ("CARD", "Credit / Debit card", "Visa, Mastercard, RuPay"),
    ("NETBANKING", "Net banking", "All major banks"),
    ("WALLET", "Wallet", "Paytm, Mobikwik, Amazon Pay"),
]
PAYMENT_CODES = {code for code, _, _ in PAYMENT_METHODS}

CATEGORY_PHOTOS = {
    "chicken": "https://images.unsplash.com/photo-1587593810167-a84920ea0781?auto=format&fit=crop&w=600&q=70",
    "mutton": "https://images.unsplash.com/photo-1603048297172-c92544798d5a?auto=format&fit=crop&w=600&q=70",
    "fish": "https://images.unsplash.com/photo-1498654200943-1088dd4438ae?auto=format&fit=crop&w=600&q=70",
    "eggs": "https://images.unsplash.com/photo-1582722872445-44dc5f7e3c8f?auto=format&fit=crop&w=600&q=70",
}


def _render(request: Request, name: str, ctx: dict, status_code: int = 200) -> HTMLResponse:
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


def _back(path: str, **params) -> RedirectResponse:
    query = urlencode({k: v for k, v in params.items() if v})
    return RedirectResponse("{}?{}".format(path, query) if query else path, status_code=303)


def _chrome(request: Request, db: Session, locality: str = None) -> dict:
    """Everything the shared header needs: where you are and what's in your basket."""
    known = services.localities(db)
    chosen = locality or request.cookies.get("mnm_locality") or ""
    if chosen not in known:
        chosen = known[0] if known else config.DEFAULT_LOCALITY

    basket = cart_lib.load(request)
    totals = cart_lib.summary(db, basket) if basket["lines"] else None
    return {
        "locality": chosen,
        "localities": known,
        "city": config.DEFAULT_CITY,
        "cart_count": cart_lib.count(basket),
        "cart_store_id": basket.get("store_id"),
        "cart_total_paisa": totals["total_paisa"] if totals else 0,
    }


# --- buyer flow -------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
def landing(request: Request, db: Session = Depends(get_db), locality: str = None):
    chrome = _chrome(request, db, locality)
    stores = services.stores_in(db, chrome["locality"])
    if not stores:
        stores = services.stores_in(db)

    counts = services.category_counts(db, chrome["locality"])
    response = _render(
        request,
        "landing.html",
        dict(
            chrome,
            stores=stores,
            categories=[
                {
                    "slug": slug,
                    "label": label,
                    "count": counts.get(slug, 0),
                    "photo": CATEGORY_PHOTOS[slug],
                }
                for slug, label in CATEGORIES
            ],
        ),
    )
    if locality:
        response.set_cookie("mnm_locality", locality, max_age=90 * 24 * 3600, samesite="lax")
    return response


@router.get("/shops", response_class=HTMLResponse)
def shops(
    request: Request,
    db: Session = Depends(get_db),
    locality: str = None,
    q: str = None,
    category: str = None,
):
    chrome = _chrome(request, db, locality)
    stores = services.stores_in(db, chrome["locality"], search=q)

    if category:
        counts = {
            store.id: sum(1 for p in store.products if p.is_active and p.category == category)
            for store in stores
        }
        stores = [store for store in stores if counts.get(store.id)]

    return _render(
        request,
        "shops.html",
        dict(
            chrome,
            stores=stores,
            q=q or "",
            category=category,
            category_label=CATEGORY_LABELS.get(category),
            categories=CATEGORIES,
        ),
    )


@router.get("/store/{store_id}", response_class=HTMLResponse)
def store_page(
    store_id: int,
    request: Request,
    db: Session = Depends(get_db),
    category: str = None,
    msg: str = None,
):
    store = services.get_store(db, store_id)
    if store is None:
        return _render(request, "not_found.html", {}, status_code=404)

    grouped = services.products_by_category(db, store.id)
    if category and category not in grouped:
        category = None

    chrome = _chrome(request, db, store.locality)
    return _render(
        request,
        "store.html",
        dict(
            chrome,
            store=store,
            grouped=grouped,
            category=category,
            category_labels=CATEGORY_LABELS,
            tabs=[(slug, CATEGORY_LABELS[slug]) for slug, _ in CATEGORIES if slug in grouped],
            qty_options=cart_lib.qty_options,
            default_qty=lambda product: 500 if product.unit == "kg" else 6,
            msg=msg,
        ),
    )


@router.post("/store/{store_id}/add")
def add_to_cart(
    store_id: int,
    request: Request,
    product_id: int = Form(...),
    qty: int = Form(...),
    db: Session = Depends(get_db),
):
    product = services.get_product(db, product_id)
    if product is None or product.store_id != store_id:
        return _back("/store/{}".format(store_id), msg="That item is no longer available.")

    current = cart_lib.load(request)
    switched = current.get("store_id") not in (None, store_id)
    updated = cart_lib.add(current, product, qty)

    note = "{} {} added.".format(cart_lib.qty_label(product, qty), product.name)
    if switched:
        note = "Started a new basket at {}. {}".format(product.store.name, note)

    response = _back("/store/{}".format(store_id), msg=note, category=product.category)
    cart_lib.save(response, updated)
    return response


@router.get("/cart", response_class=HTMLResponse)
def cart_page(request: Request, db: Session = Depends(get_db), error: str = None):
    basket = cart_lib.load(request)
    summary = cart_lib.summary(db, basket)
    chrome = _chrome(request, db, summary["store"].locality if summary["store"] else None)

    return _render(
        request,
        "cart.html",
        dict(
            chrome,
            summary=summary,
            qty_label=cart_lib.qty_label,
            qty_options=cart_lib.qty_options,
            methods=PAYMENT_METHODS,
            payments_ready=payments.is_configured(),
            free_above=config.FREE_DELIVERY_ABOVE_PAISA,
            error=error,
            form={},
        ),
    )


@router.post("/cart/update")
def cart_update(
    request: Request,
    product_id: int = Form(...),
    qty: int = Form(...),
    db: Session = Depends(get_db),
):
    updated = cart_lib.set_qty(cart_lib.load(request), product_id, qty)
    response = RedirectResponse("/cart", status_code=303)
    cart_lib.save(response, updated)
    return response


@router.post("/checkout")
def checkout(
    request: Request,
    customer_name: str = Form(...),
    phone: str = Form(...),
    address: str = Form(...),
    notes: str = Form(""),
    payment_method: str = Form("UPI"),
    db: Session = Depends(get_db),
):
    basket = cart_lib.load(request)
    summary = cart_lib.summary(db, basket)
    if not summary["lines"]:
        return _back("/cart", error="Your cart is empty.")

    store = summary["store"]
    if not store.is_open:
        return _back("/cart", error="{} has closed for the day.".format(store.name))

    try:
        order = services.place_order(
            db,
            store,
            customer_name,
            phone,
            address,
            [{"product": line["product"], "qty": line["qty"]} for line in summary["lines"]],
            actor="customer",
            notes=notes,
            delivery_fee_paisa=summary["delivery_fee_paisa"],
            payment_method=payment_method if payment_method in PAYMENT_CODES else None,
        )
    except services.OrderError as exc:
        return _back("/cart", error=str(exc))

    response = RedirectResponse("/order/{}".format(order.id), status_code=303)
    cart_lib.clear(response)
    return response


@router.get("/order/{order_id}", response_class=HTMLResponse)
def order_page(order_id: str, request: Request, db: Session = Depends(get_db), error: str = None):
    order = services.get_order(db, order_id)
    if order is None:
        return _render(request, "not_found.html", {}, status_code=404)

    return _render(
        request,
        "order.html",
        dict(
            _chrome(request, db, order.store.locality),
            order=order,
            items=order.items,
            payments_ready=payments.is_configured(),
            error=error,
        ),
    )


@router.post("/order/{order_id}/pay")
def order_retry_payment(order_id: str, db: Session = Depends(get_db)):
    order = services.get_order(db, order_id)
    if order is None:
        return _back("/", error="Order not found.")

    try:
        services.start_payment(db, order, actor="customer")
    except services.OrderError as exc:
        return _back("/order/{}".format(order.id), error=str(exc))
    return RedirectResponse("/order/{}".format(order.id), status_code=303)


# --- kasai.ai ---------------------------------------------------------------


def _kasai_store(db, request: Request):
    """Chat against the shop you are standing in, else the nearest open one."""
    basket = cart_lib.load(request)
    if basket.get("store_id"):
        store = services.get_store(db, basket["store_id"])
        if store:
            return store

    chrome_locality = request.cookies.get("mnm_locality")
    nearby = services.stores_in(db, chrome_locality) or services.stores_in(db)
    return nearby[0] if nearby else None


@router.post("/kasai")
def kasai_chat(payload: dict, request: Request, db: Session = Depends(get_db)):
    message = (payload or {}).get("message", "")
    store = _kasai_store(db, request)
    if store is None:
        return JSONResponse({"reply": "No shops are listed near you yet."}, status_code=503)

    parsed = services.estimate(db, store.id, message)
    if not parsed["items"]:
        return {
            "store": {"id": store.id, "name": store.name},
            "reply": "I could not find that on {}'s list. Try something like "
            "\"1kg chicken curry cut and 2 dozen eggs\".".format(store.name),
            "items": [],
            "can_add": False,
        }

    return {
        "store": {"id": store.id, "name": store.name},
        "reply": "Here's your basket from {}.".format(store.name),
        "items": [
            {
                "name": item["name"],
                "qty": "{:g} {}".format(item["qty"], item["qty_unit"]),
                "amount": pricing.rupees(item["amount_paisa"]),
            }
            for item in parsed["items"]
        ],
        "unmatched": parsed["unmatched"],
        "total": pricing.rupees(parsed["total_paisa"]),
        "can_add": True,
    }


@router.post("/kasai/add")
def kasai_add(request: Request, message: str = Form(...), db: Session = Depends(get_db)):
    store = _kasai_store(db, request)
    if store is None:
        return _back("/", error="No shops are listed near you yet.")

    parsed = services.estimate(db, store.id, message)
    products = {p.id: p for p in services.price_list(db, store.id)}
    basket = cart_lib.from_parsed_items(parsed["items"], products)
    if basket is None:
        return _back("/store/{}".format(store.id), msg="kasai.ai could not price that.")

    response = RedirectResponse("/cart", status_code=303)
    cart_lib.save(response, basket)
    return response


# --- vendor -----------------------------------------------------------------


@router.get("/vendor", response_class=HTMLResponse)
def vendor_page(request: Request, db: Session = Depends(get_db), msg: str = None, error: str = None):
    return _render(
        request,
        "vendor.html",
        {
            "to_cut": services.orders_by_status(db, [STATUS_PAID]),
            "incoming": services.orders_by_status(db, [STATUS_NEW, STATUS_LINK_SENT]),
            "ready": services.orders_by_status(db, [STATUS_WEIGHED]),
            "msg": msg,
            "error": error,
        },
    )


@router.post("/vendor/{order_id}/weigh")
def vendor_weigh(
    order_id: str,
    actual_weight_kg: float = Form(...),
    vendor_note: str = Form(""),
    db: Session = Depends(get_db),
):
    order = services.get_order(db, order_id)
    if order is None:
        return _back("/vendor", error="Order not found.")

    try:
        services.set_weight(
            db, order, int(round(actual_weight_kg * 1000)), actor="vendor", note=vendor_note
        )
    except services.OrderError as exc:
        return _back("/vendor", error=str(exc))

    return _back("/vendor", msg="Order {} cut, packed and logged.".format(order.id))


# --- ops --------------------------------------------------------------------


@router.get("/ops", response_class=HTMLResponse)
def ops_page(request: Request, db: Session = Depends(get_db), msg: str = None, error: str = None):
    if not security.is_ops(request):
        return _render(request, "ops_login.html", {"error": None})

    return _render(
        request,
        "ops.html",
        {
            "awaiting_payment": services.orders_by_status(db, [STATUS_NEW, STATUS_LINK_SENT]),
            "to_cut": services.orders_by_status(db, [STATUS_PAID]),
            "to_dispatch": services.orders_by_status(db, [STATUS_WEIGHED]),
            "threshold": config.PRICE_GAP_THRESHOLD,
            "payments_ready": payments.is_configured(),
            "msg": msg,
            "error": error,
        },
    )


@router.post("/ops/login")
def ops_login(request: Request, password: str = Form(...), db: Session = Depends(get_db)):
    if not security.check_ops_password(password):
        services.log(db, "ops", "login_failed", "bad password")
        db.commit()
        return _render(request, "ops_login.html", {"error": "Wrong password."}, status_code=401)

    services.log(db, "ops", "login", None)
    db.commit()

    response = RedirectResponse("/ops", status_code=303)
    response.set_cookie(
        config.OPS_COOKIE,
        security.issue_ops_token(),
        max_age=security.OPS_SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=config.PUBLIC_BASE_URL.startswith("https://"),
    )
    return response


@router.post("/ops/logout")
def ops_logout():
    response = RedirectResponse("/ops", status_code=303)
    response.delete_cookie(config.OPS_COOKIE)
    return response


@router.post("/ops/{order_id}/dispatch")
def ops_dispatch(order_id: str, request: Request, db: Session = Depends(get_db)):
    if not security.is_ops(request):
        return RedirectResponse("/ops", status_code=303)

    order = services.get_order(db, order_id)
    if order is None:
        return _back("/ops", error="Order not found.")

    try:
        services.dispatch(db, order, actor="ops")
    except services.OrderError as exc:
        return _back("/ops", error=str(exc))

    return _back("/ops", msg="Order {} dispatched.".format(order.id))


@router.post("/ops/{order_id}/retry_link")
def ops_retry_link(order_id: str, request: Request, db: Session = Depends(get_db)):
    if not security.is_ops(request):
        return RedirectResponse("/ops", status_code=303)

    order = services.get_order(db, order_id)
    if order is None:
        return _back("/ops", error="Order not found.")

    try:
        services.start_payment(db, order, actor="ops", force=True)
    except services.OrderError as exc:
        return _back("/ops", error=str(exc))

    return _back("/ops", msg="Payment link re-issued for {}.".format(order.id))


# --- proof ------------------------------------------------------------------


@router.get("/proof", response_class=HTMLResponse)
def proof_page(request: Request, db: Session = Depends(get_db)):
    orders = services.recent_orders(db, limit=100)
    return _render(
        request,
        "proof.html",
        dict(
            _chrome(request, db),
            orders=orders,
            paid_count=sum(1 for o in orders if o.is_paid),
            dispatched_count=sum(1 for o in orders if o.status == STATUS_DISPATCHED),
        ),
    )
