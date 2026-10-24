from typing import List, Optional

from sqlalchemy import func, select

from app import config, payments, pricing
from app.models import (
    STATUS_DISPATCHED,
    STATUS_LINK_SENT,
    STATUS_NEW,
    STATUS_PAID,
    STATUS_WEIGHED,
    AgentLog,
    Order,
    OrderItem,
    Product,
    Store,
    utcnow,
)


class OrderError(Exception):
    pass


def log(db, actor: str, action: str, detail: str = None, order_id: str = None) -> AgentLog:
    entry = AgentLog(actor=actor, action=action, detail=detail, order_id=order_id)
    db.add(entry)
    return entry


# --- stores -----------------------------------------------------------------


def localities(db) -> List[str]:
    rows = db.execute(
        select(Store.locality, func.count(Store.id))
        .where(Store.is_active.is_(True), Store.locality != "")
        .group_by(Store.locality)
        .order_by(func.count(Store.id).desc(), Store.locality)
    ).all()
    return [row[0] for row in rows]


def default_locality(db) -> str:
    found = localities(db)
    return found[0] if found else config.DEFAULT_LOCALITY


def stores_in(db, locality: str = None, search: str = None) -> List[Store]:
    stmt = select(Store).where(Store.is_active.is_(True))
    if locality:
        stmt = stmt.where(Store.locality == locality)
    if search:
        like = "%{}%".format(search.strip().lower())
        # Match the shop by name, or by anything on its shelf.
        matching_stores = select(Product.store_id).where(
            Product.is_active.is_(True), func.lower(Product.name).like(like)
        )
        stmt = stmt.where(
            func.lower(Store.name).like(like) | Store.id.in_(matching_stores)
        )
    # Open shops first - a closed butcher is not a result anyone wants on top.
    return list(db.scalars(stmt.order_by(Store.is_open.desc(), Store.distance_km, Store.name)))


def get_store(db, store_id: int) -> Optional[Store]:
    store = db.get(Store, store_id)
    return store if store and store.is_active else None


def active_store(db) -> Optional[Store]:
    """Fallback store for the agent tools, which are not locality-aware."""
    return db.scalars(
        select(Store)
        .where(Store.is_active.is_(True))
        .order_by(Store.is_open.desc(), Store.id)
    ).first()


# --- catalogue --------------------------------------------------------------


def price_list(db, store_id: int, category: str = None) -> List[Product]:
    stmt = select(Product).where(Product.store_id == store_id, Product.is_active.is_(True))
    if category:
        stmt = stmt.where(Product.category == category)
    return list(db.scalars(stmt.order_by(Product.category, Product.name)))


def products_by_category(db, store_id: int) -> dict:
    grouped = {}
    for product in price_list(db, store_id):
        grouped.setdefault(product.category, []).append(product)
    return grouped


def get_product(db, product_id: int) -> Optional[Product]:
    product = db.get(Product, product_id)
    return product if product and product.is_active else None


def category_counts(db, locality: str = None) -> dict:
    stmt = (
        select(Product.category, func.count(Product.id))
        .join(Store, Store.id == Product.store_id)
        .where(Product.is_active.is_(True), Store.is_active.is_(True))
    )
    if locality:
        stmt = stmt.where(Store.locality == locality)
    return {row[0]: row[1] for row in db.execute(stmt.group_by(Product.category)).all()}


def estimate(db, store_id: int, order_text: str) -> dict:
    return pricing.parse_order(order_text, price_list(db, store_id))


# --- orders -----------------------------------------------------------------


def get_order(db, order_id: str) -> Optional[Order]:
    return db.get(Order, (order_id or "").strip().upper())


def _order_item(product: Product, qty: int, line_no: int) -> OrderItem:
    """Freeze a catalogue line onto the order. Prices are copied, not referenced."""
    return OrderItem(
        product_id=product.id,
        line_no=line_no,
        name=product.name,
        unit=product.unit,
        qty=qty,
        unit_price_paisa=product.price_paisa,
        weight_g=product.weight_for(qty),
        amount_paisa=product.price_for(qty),
    )


def place_order(
    db,
    store: Store,
    customer_name: str,
    phone: str,
    address: str,
    lines: List[dict],
    actor: str,
    notes: str = None,
    delivery_fee_paisa: int = 0,
    payment_method: str = None,
    order_text: str = None,
) -> Order:
    """Create the order at catalogue prices and immediately raise a payment link.

    Prices are fixed, so there is nothing to approve: the buyer pays, then the
    butcher cuts. `lines` is a list of {"product": Product, "qty": int}.
    """
    if not lines:
        raise OrderError("Your cart is empty.")

    items = [
        _order_item(line["product"], line["qty"], index)
        for index, line in enumerate(lines)
    ]
    items_paisa = sum(item.amount_paisa for item in items)
    if items_paisa <= 0:
        raise OrderError("We could not price this order.")

    order = Order(
        store_id=store.id,
        customer_name=(customer_name or "").strip(),
        phone=(phone or "").strip(),
        address=(address or "").strip(),
        order_text=order_text or ", ".join(
            "{} {}".format(item.qty_label(), item.name) for item in items
        ),
        notes=(notes or "").strip() or None,
        items=items,
        expected_weight_g=sum(item.weight_g for item in items),
        items_paisa=items_paisa,
        delivery_fee_paisa=delivery_fee_paisa,
        amount_paisa=items_paisa + delivery_fee_paisa,
        payment_method=payment_method,
        status=STATUS_NEW,
    )
    db.add(order)
    db.flush()

    log(
        db,
        actor,
        "order_created",
        "{} | {} | {}".format(
            store.name,
            pricing.rupees(order.amount_paisa),
            ", ".join(item.name for item in items),
        ),
        order.id,
    )
    db.commit()

    try:
        start_payment(db, order, actor=actor)
    except OrderError:
        # The order stands; the buyer can retry the link from the tracking page.
        pass
    return order


def create_order_from_text(
    db, store: Store, customer_name: str, phone: str, address: str, order_text: str, actor: str
) -> Order:
    """Free-text entry point used by the agent tools and kasai.ai."""
    parsed = estimate(db, store.id, order_text)
    if not parsed["items"]:
        raise OrderError(
            "We could not match anything on the price list. Try e.g. '1kg mutton curry cut'."
        )

    lines = []
    for item in parsed["items"]:
        product = get_product(db, item["product_id"])
        if product is None:
            continue
        if product.unit == "kg":
            qty = item["weight_g"]
        else:
            # Counted goods can only ship whole units, and round() sends anything
            # under half to zero - which dropped the line from the basket without
            # ever telling the buyer. Someone who asks for a piece gets at least one.
            qty = max(1, int(round(item["qty"])))
        if qty > 0:
            lines.append({"product": product, "qty": qty})

    if not lines:
        raise OrderError("Those items are no longer on the price list.")

    return place_order(
        db,
        store,
        customer_name,
        phone,
        address,
        lines,
        actor=actor,
        order_text=order_text.strip(),
        delivery_fee_paisa=delivery_fee_for(sum(line_amount(line) for line in lines)),
    )


def line_amount(line: dict) -> int:
    return line["product"].price_for(line["qty"])


def delivery_fee_for(items_paisa: int) -> int:
    if items_paisa <= 0 or items_paisa >= config.FREE_DELIVERY_ABOVE_PAISA:
        return 0
    return config.DELIVERY_FEE_PAISA


def start_payment(db, order: Order, actor: str, force: bool = False) -> Order:
    """Raise the Pine Labs link for an unpaid order.

    An existing live link is reused unless `force` - re-issuing on every page view
    would litter the merchant account with abandoned links.
    """
    if order.is_paid:
        return order
    if order.payment_link and not force:
        return order
    if not payments.is_configured():
        log(db, actor, "payment_link_skipped", "Pine Labs credentials not configured", order.id)
        db.commit()
        raise OrderError("Online payment is not configured yet.")

    reference = order.id
    if force:
        attempts = sum(
            1 for entry in order_logs(db, order.id) if entry.action == "payment_link_created"
        )
        reference = "{}-R{}".format(order.id, attempts + 1)

    try:
        response = payments.create_payment_link(order, order.amount_paisa, reference=reference)
    except Exception as exc:
        log(db, actor, "payment_link_failed", "{}: {}".format(type(exc).__name__, exc), order.id)
        db.commit()
        raise OrderError("The payment link could not be created: {}".format(exc))

    order.payment_link = response.payment_link
    order.payment_link_id = response.payment_link_id
    order.status = STATUS_LINK_SENT
    log(
        db,
        actor,
        "payment_link_created",
        "{} | {}".format(response.payment_link_id, pricing.rupees(order.amount_paisa)),
        order.id,
    )
    db.commit()
    return order


def mark_paid(db, order: Order, actor: str, reference: str = None, detail: str = None) -> Order:
    if order.status in (STATUS_PAID, STATUS_WEIGHED, STATUS_DISPATCHED):
        return order

    order.status = STATUS_PAID
    order.paid_at = utcnow()
    order.payment_reference = reference or order.payment_reference
    log(db, actor, "order_paid", detail or (reference or ""), order.id)
    db.commit()
    return order


def set_weight(db, order: Order, actual_weight_g: int, actor: str, note: str = None) -> Order:
    """Record what the butcher actually cut. This happens after payment and never
    changes the amount charged - it is the receipt, not the bill."""
    if not order.is_paid:
        raise OrderError("Order {} has not been paid yet.".format(order.id))
    if order.status == STATUS_DISPATCHED:
        raise OrderError("Order {} is already out for delivery.".format(order.id))
    if actual_weight_g <= 0:
        raise OrderError("Weight must be greater than zero.")

    order.actual_weight_g = actual_weight_g
    order.actual_value_paisa = pricing.value_at_weight(
        order.items_paisa, order.expected_weight_g, actual_weight_g
    )
    order.vendor_note = (note or "").strip() or None
    order.status = STATUS_WEIGHED

    log(
        db,
        actor,
        "order_weighed",
        "cut {} (paid for {}) -> worth {}".format(
            pricing.grams_to_kg_str(actual_weight_g),
            pricing.grams_to_kg_str(order.expected_weight_g),
            pricing.rupees(order.actual_value_paisa),
        ),
        order.id,
    )
    db.commit()
    return order


def dispatch(db, order: Order, actor: str) -> Order:
    if order.status not in (STATUS_PAID, STATUS_WEIGHED):
        raise OrderError("Only paid orders can be dispatched (order is {}).".format(order.status))

    order.status = STATUS_DISPATCHED
    log(db, actor, "order_dispatched", None, order.id)
    db.commit()
    return order


def sync_payment_status(db, order: Order, actor: str) -> Order:
    """Poll Pine Labs for link state - used by the agent's check_payment tool."""
    if order.is_paid or not order.payment_link_id:
        return order

    response = payments.fetch_payment_link(order)
    if response.status in payments.PAID_LINK_STATUSES:
        mark_paid(db, order, actor, order.payment_link_id, "polled: {}".format(response.status))
    return order


def orders_by_status(db, statuses: list) -> List[Order]:
    return list(
        db.scalars(
            select(Order).where(Order.status.in_(statuses)).order_by(Order.created_at.desc())
        )
    )


def recent_orders(db, limit: int = 50) -> List[Order]:
    return list(db.scalars(select(Order).order_by(Order.created_at.desc()).limit(limit)))


def order_logs(db, order_id: str) -> List[AgentLog]:
    return list(
        db.scalars(
            select(AgentLog).where(AgentLog.order_id == order_id).order_by(AgentLog.timestamp)
        )
    )
