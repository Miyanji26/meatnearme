"""Put one real shop and its price list into the catalogue.

    python -m scripts.onboard shops/example.json

Separate from scripts.seed on purpose. The seed owns the three demo shops and
rewrites them on every run; a real butcher's prices must not be in a file that
anything resets. This script only ever touches the shop named in the JSON.

Re-running is safe and is the intended way to change prices: the shop is matched
on name, each product on (shop, name), so an edited file updates in place rather
than creating a second listing. Products you remove from the file are retired
rather than deleted, because an order line points at a product id and a hard
delete would blank it out of the order history.

Prices are written in rupees in the JSON and stored in paisa, so there is one
obvious place to get the units wrong and it is checked rather than assumed.
"""

import json
import sys
from pathlib import Path

from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.models import Product, Store

STORE_FIELDS = {
    "name", "photo_url", "tagline", "phone", "address", "locality", "city",
    "distance_km", "rating", "rating_count", "services", "opens_at",
    "closes_at", "is_open",
}
PRODUCT_FIELDS = {
    "name", "aliases", "category", "description", "photo_url", "unit",
    "price_rupees", "typical_weight_g",
}


def _fail(message: str):
    raise SystemExit("onboard: {}".format(message))


def _to_paisa(value, label: str) -> int:
    """Rupees in the file, paisa in the table.

    round() rather than int(): 169.95 lands on 16995, where truncation would
    quietly shave a paisa off every sale of that cut.
    """
    try:
        paisa = int(round(float(value) * 100))
    except (TypeError, ValueError):
        _fail("{}: price_rupees must be a number, got {!r}".format(label, value))
    if paisa <= 0:
        _fail("{}: price_rupees must be greater than zero".format(label))
    return paisa


def _check_keys(payload: dict, allowed: set, label: str):
    """A typo in a key would otherwise be silently ignored, and the shop would
    go live missing its phone number or its rating."""
    unknown = set(payload) - allowed
    if unknown:
        _fail("{}: unknown field(s) {}".format(label, ", ".join(sorted(unknown))))


def load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        _fail("no such file: {}".format(path))
    except json.JSONDecodeError as exc:
        _fail("{} is not valid JSON: {}".format(path, exc))

    store = data.get("store")
    products = data.get("products")
    if not isinstance(store, dict) or not store.get("name"):
        _fail("the file needs a \"store\" object with a \"name\"")
    if not isinstance(products, list) or not products:
        _fail("the file needs a non-empty \"products\" list")

    _check_keys(store, STORE_FIELDS, "store")
    seen = set()
    for item in products:
        label = "product {!r}".format(item.get("name", "<unnamed>"))
        if not item.get("name"):
            _fail("every product needs a name")
        _check_keys(item, PRODUCT_FIELDS, label)
        if item.get("unit", "kg") not in ("kg", "piece"):
            _fail("{}: unit must be \"kg\" or \"piece\"".format(label))
        # Two products with the same name would fight over the same row, and
        # whichever came last would win without saying so.
        if item["name"].lower() in seen:
            _fail("{} appears twice".format(label))
        seen.add(item["name"].lower())
    return data


def apply(data: dict) -> None:
    init_db()
    db = SessionLocal()
    try:
        fields = dict(data["store"])
        store = db.scalars(select(Store).where(Store.name == fields["name"])).first()
        verb = "updated"
        if store is None:
            store = Store(**fields)
            db.add(store)
            db.flush()
            verb = "created"
        else:
            for key, value in fields.items():
                setattr(store, key, value)
        store.is_active = True

        kept = set()
        for item in data["products"]:
            product = db.scalars(
                select(Product).where(
                    Product.store_id == store.id, Product.name == item["name"]
                )
            ).first()
            if product is None:
                product = Product(store_id=store.id, name=item["name"])
                db.add(product)
            product.aliases = item.get("aliases")
            product.category = item.get("category", "chicken")
            product.description = item.get("description")
            product.photo_url = item.get("photo_url")
            product.unit = item.get("unit", "kg")
            product.price_paisa = _to_paisa(item["price_rupees"], item["name"])
            product.typical_weight_g = item.get("typical_weight_g")
            product.is_active = True
            kept.add(item["name"])
            print("  {:<28} Rs {:>8.2f} / {}".format(
                item["name"], product.price_paisa / 100.0, product.unit))

        # Anything dropped from the file stops being sellable but stays in the
        # table, so past orders still resolve the product they were cut from.
        retired = 0
        for product in store.products:
            if product.name not in kept and product.is_active:
                product.is_active = False
                retired += 1

        db.commit()
        print("\n{} {} (id {}) with {} product(s){}".format(
            verb, store.name, store.id, len(kept),
            ", {} retired".format(retired) if retired else ""))
        print("live at /store/{}".format(store.id))
    finally:
        db.close()


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    apply(load(Path(sys.argv[1])))


if __name__ == "__main__":
    main()
