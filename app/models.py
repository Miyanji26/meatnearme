import datetime as dt
import secrets
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# Catalogue prices are fixed, so the buyer pays at checkout and the butcher cuts
# afterwards. Weighing still happens - it just records what was actually cut
# instead of deciding what to charge.
STATUS_NEW = "new"
STATUS_LINK_SENT = "link_sent"
STATUS_PAID = "paid"
STATUS_WEIGHED = "weighed"
STATUS_DISPATCHED = "dispatched"

STATUS_FLOW = [
    STATUS_NEW,
    STATUS_LINK_SENT,
    STATUS_PAID,
    STATUS_WEIGHED,
    STATUS_DISPATCHED,
]

STATUS_LABELS = {
    STATUS_NEW: "Order placed",
    STATUS_LINK_SENT: "Awaiting payment",
    STATUS_PAID: "Paid",
    STATUS_WEIGHED: "Cut & packed",
    STATUS_DISPATCHED: "Out for delivery",
}

CATEGORIES = [
    ("chicken", "Chicken"),
    ("mutton", "Mutton"),
    ("fish", "Fish"),
    ("eggs", "Eggs"),
]
CATEGORY_LABELS = dict(CATEGORIES)

_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_order_code() -> str:
    return "MNM" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(7))


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Store(Base):
    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    photo_url: Mapped[Optional[str]] = mapped_column(String(500))
    tagline: Mapped[Optional[str]] = mapped_column(String(300))
    phone: Mapped[Optional[str]] = mapped_column(String(32))
    address: Mapped[Optional[str]] = mapped_column(Text)

    locality: Mapped[str] = mapped_column(String(120), default="", nullable=False, index=True)
    city: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    distance_km: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    rating: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    rating_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    services: Mapped[Optional[str]] = mapped_column(String(400))
    opens_at: Mapped[Optional[str]] = mapped_column(String(16))
    closes_at: Mapped[Optional[str]] = mapped_column(String(16))
    is_open: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    products: Mapped[list["Product"]] = relationship(back_populates="store")

    def service_list(self) -> list:
        return [s.strip() for s in (self.services or "").split(",") if s.strip()]

    @property
    def starting_price(self):
        """Cheapest headline price as (paisa, unit).

        Per-kg is preferred: a shop whose cheapest line is a ₹9 egg would otherwise
        advertise "from ₹9" against neighbours quoting per kilo.
        """
        by_kg = [p.price_paisa for p in self.products if p.is_active and p.unit == "kg"]
        if by_kg:
            return (min(by_kg), "kg")
        others = [p.price_paisa for p in self.products if p.is_active]
        return (min(others), "pc") if others else None

    @property
    def starting_price_paisa(self) -> Optional[int]:
        cheapest = self.starting_price
        return cheapest[0] if cheapest else None


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    aliases: Mapped[Optional[str]] = mapped_column(String(500))
    category: Mapped[str] = mapped_column(String(32), default="chicken", nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(String(300))
    photo_url: Mapped[Optional[str]] = mapped_column(String(500))
    unit: Mapped[str] = mapped_column(String(16), default="kg", nullable=False)  # kg | piece
    price_paisa: Mapped[int] = mapped_column(Integer, nullable=False)
    typical_weight_g: Mapped[Optional[int]] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    store: Mapped[Store] = relationship(back_populates="products")

    def alias_list(self) -> list:
        raw = [self.name] + (self.aliases or "").split(",")
        return [a.strip().lower() for a in raw if a and a.strip()]

    @property
    def step(self) -> int:
        """Smallest sellable increment: 250g for weighed goods, 1 for counted goods."""
        return 250 if self.unit == "kg" else 1

    def price_for(self, qty: int) -> int:
        """qty is grams for kg products, piece count for piece products."""
        if self.unit == "kg":
            return int(round(self.price_paisa * qty / 1000.0))
        return int(round(self.price_paisa * qty))

    def weight_for(self, qty: int) -> int:
        if self.unit == "kg":
            return qty
        return int(round(qty * (self.typical_weight_g or 0)))


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=new_order_code)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False, index=True)

    customer_name: Mapped[str] = mapped_column(String(160), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    order_text: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    expected_weight_g: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # What the customer was actually charged - fixed at checkout.
    items_paisa: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    delivery_fee_paisa: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    amount_paisa: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # What the butcher actually cut - recorded after payment, for transparency.
    actual_weight_g: Mapped[Optional[int]] = mapped_column(Integer)
    actual_value_paisa: Mapped[Optional[int]] = mapped_column(Integer)
    vendor_note: Mapped[Optional[str]] = mapped_column(Text)

    status: Mapped[str] = mapped_column(String(24), default=STATUS_NEW, nullable=False, index=True)

    payment_method: Mapped[Optional[str]] = mapped_column(String(24))
    payment_link: Mapped[Optional[str]] = mapped_column(String(1000))
    payment_link_id: Mapped[Optional[str]] = mapped_column(String(120), index=True)
    payment_reference: Mapped[Optional[str]] = mapped_column(String(120), index=True)
    paid_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    store: Mapped[Store] = relationship()
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="OrderItem.line_no",
    )

    @property
    def gap_ratio(self) -> float:
        """How far the cut drifted from what was paid for. Ops watches this."""
        if not self.items_paisa or self.actual_value_paisa is None:
            return 0.0
        return (self.actual_value_paisa - self.items_paisa) / self.items_paisa

    @property
    def is_paid(self) -> bool:
        return self.status in (STATUS_PAID, STATUS_WEIGHED, STATUS_DISPATCHED)

    def masked_name(self) -> str:
        name = (self.customer_name or "").strip()
        return (name[0].upper() + ".") if name else "?"


class OrderItem(Base):
    """One priced line of an order.

    The name, unit and price are copied in rather than read back through the
    product: a catalogue edit six months from now must not rewrite what someone
    was charged. product_id is kept only so ops can trace the line, and it goes
    null if the product is ever deleted.
    """

    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[str] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), index=True
    )
    line_no: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    unit: Mapped[str] = mapped_column(String(16), default="kg", nullable=False)
    # Grams for kg products, piece count for piece products - same convention as
    # Product.price_for().
    qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unit_price_paisa: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    weight_g: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    amount_paisa: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    order: Mapped[Order] = relationship(back_populates="items")

    def qty_label(self) -> str:
        if self.unit == "kg":
            grams = self.qty
            if grams < 1000:
                return "{} g".format(grams)
            return "{:.2f} kg".format(grams / 1000.0).replace(".00 kg", " kg")
        return "{} pc{}".format(self.qty, "" if self.qty == 1 else "s")

    def as_dict(self) -> dict:
        return {
            "product_id": self.product_id,
            "name": self.name,
            "unit": self.unit,
            "qty": self.qty,
            "weight_g": self.weight_g,
            "unit_price_paisa": self.unit_price_paisa,
            "amount_paisa": self.amount_paisa,
        }


class AgentLog(Base):
    __tablename__ = "agent_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[Optional[str]] = mapped_column(String(16), index=True)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    detail: Mapped[Optional[str]] = mapped_column(Text)
    timestamp: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
