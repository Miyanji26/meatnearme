"""Seed the Shivajinagar locality with its three butchers.

Idempotent - re-running updates details and prices rather than duplicating rows.
Product photos are stock placeholders; swap in each shop's own shots before launch.
"""

from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.models import Product, Store

PHOTO = "https://images.unsplash.com/{}?auto=format&fit=crop&w=800&q=70"

# Each key is named for what the picture actually shows, checked by eye rather than
# trusted from the filename. Cooked-dish stock photos were dropped: a raw-meat
# counter that advertises roast chicken and barbecue ribs reads as a restaurant.
SHOT = {
    "raw_whole_chicken": PHOTO.format("photo-1587593810167-a84920ea0781"),
    "raw_chicken_fillet": PHOTO.format("photo-1604503468506-a8da13d82791"),
    "raw_red_slab": PHOTO.format("photo-1613454320437-0c228c8b1723"),
    "raw_red_chops": PHOTO.format("photo-1603048297172-c92544798d5a"),
    "raw_red_ribeye": PHOTO.format("photo-1588347818036-558601350947"),
    "fish_ice": PHOTO.format("photo-1498654200943-1088dd4438ae"),
    "prawns": PHOTO.format("photo-1565680018434-b513d5e5fd47"),
    "eggs_bowl": PHOTO.format("photo-1582722872445-44dc5f7e3c8f"),
    "eggs_carton": PHOTO.format("photo-1598965675045-45c5e72c7d05"),
}

LOCALITY = "Shivajinagar"
CITY = "Bengaluru"

# (name, aliases, category, description, photo, unit, price_paisa, typical_weight_g)
STORES = [
    {
        "store": {
            "name": "Rajbhavan Poultry Marketing Agency",
            "tagline": "Fresh-cut poultry since 1982. Birds dressed to order.",
            "photo_url": SHOT["raw_whole_chicken"],
            "phone": "+91 98860 11223",
            "address": "12, Market Road, Shivajinagar, Bengaluru 560001",
            "locality": LOCALITY,
            "city": CITY,
            "distance_km": 0.8,
            "rating": 4.6,
            "rating_count": 812,
            "services": "Halal, Curry cut, Skin removed, Home delivery, Bulk orders",
            "opens_at": "06:30",
            "closes_at": "21:30",
            "is_open": True,
        },
        "products": [
            ("Chicken Curry Cut", "chicken,chicken curry,broiler,curry cut", "chicken",
             "Whole bird, skin off, cut into 12-14 curry pieces.", "raw_whole_chicken",
             "kg", 24000, None),
            ("Chicken Leg Pieces", "leg piece,leg pieces,chicken leg,drumstick,drumsticks", "chicken",
             "Thigh and drumstick, trimmed. The biryani cut.", "raw_chicken_fillet",
             "kg", 26000, None),
            ("Chicken Boneless", "chicken boneless,boneless chicken,boneless", "chicken",
             "Thigh boneless, cubed for curry or tikka.", "raw_chicken_fillet",
             "kg", 34000, None),
            ("Chicken Breast", "breast,chicken breast", "chicken",
             "Skinless breast fillet, fat trimmed.", "raw_chicken_fillet",
             "kg", 36000, None),
            ("Country Chicken", "country chicken,desi chicken,naati koli,naati", "chicken",
             "Free-range naati koli. Firmer meat, deeper stock.", "raw_whole_chicken",
             "kg", 42000, None),
            ("Chicken Liver", "liver,kaleji,chicken liver", "chicken",
             "Cleaned liver and gizzard mix.", "raw_red_slab",
             "kg", 18000, None),
            ("Farm Eggs", "egg,eggs,anda,farm eggs", "eggs",
             "Graded farm eggs, laid this week.", "eggs_carton",
             "piece", 900, 55),
            ("Country Eggs", "country egg,country eggs,naati motte,desi anda", "eggs",
             "Smaller, darker yolk, free-range birds.", "eggs_bowl",
             "piece", 1500, 48),
        ],
    },
    {
        "store": {
            "name": "KGN Meats",
            "tagline": "Mutton cut the way your grandmother asked for it.",
            "photo_url": SHOT["raw_red_slab"],
            "phone": "+91 99452 33881",
            "address": "48, Ebrahim Sahib Street, Shivajinagar, Bengaluru 560051",
            "locality": LOCALITY,
            "city": CITY,
            "distance_km": 1.4,
            "rating": 4.4,
            "rating_count": 503,
            "services": "Halal, Mutton specialist, Keema on order, Home delivery",
            "opens_at": "07:00",
            "closes_at": "22:00",
            "is_open": True,
        },
        "products": [
            ("Mutton Curry Cut", "mutton,goat,bakra,mutton curry,curry cut", "mutton",
             "Shoulder and leg on the bone, cut small for curry.", "raw_red_chops",
             "kg", 84000, None),
            ("Mutton Boneless", "mutton boneless,boneless mutton,boti", "mutton",
             "Leg boneless, cubed. No fat, no bone.", "raw_red_slab",
             "kg", 99000, None),
            ("Mutton Keema", "keema,mutton mince,qeema", "mutton",
             "Minced twice on the day you order.", "raw_red_ribeye",
             "kg", 88000, None),
            ("Mutton Chops", "chops,mutton chops,ribs,champ", "mutton",
             "Rib chops, French-trimmed.", "raw_red_chops",
             "kg", 92000, None),
            ("Chicken Curry Cut", "chicken,chicken curry,broiler", "chicken",
             "Daily broiler, cut to order.", "raw_whole_chicken",
             "kg", 25000, None),
            ("Rohu Fish", "fish,rohu,rohu fish", "fish",
             "Whole rohu, cleaned and steaked.", "fish_ice",
             "kg", 32000, None),
            ("Prawns", "prawn,prawns,jhinga,shrimp", "fish",
             "Medium prawns, deveined on request.", "prawns",
             "kg", 65000, None),
        ],
    },
    {
        "store": {
            "name": "A1 Meats",
            "tagline": "Coastal fish counter and daily mutton under one roof.",
            "photo_url": SHOT["fish_ice"],
            "phone": "+91 97400 55219",
            "address": "7, Commercial Street Cross, Shivajinagar, Bengaluru 560001",
            "locality": LOCALITY,
            "city": CITY,
            "distance_km": 2.1,
            "rating": 4.2,
            "rating_count": 287,
            "services": "Halal, Fish counter, Cleaning included, Home delivery",
            "opens_at": "08:00",
            "closes_at": "20:30",
            "is_open": False,
        },
        "products": [
            ("Mutton Curry Cut", "mutton,goat,bakra,mutton curry", "mutton",
             "On the bone, cut medium.", "raw_red_chops",
             "kg", 82000, None),
            ("Chicken Curry Cut", "chicken,chicken curry,broiler", "chicken",
             "Skin on or off, your call at checkout.", "raw_whole_chicken",
             "kg", 23500, None),
            ("Chicken Leg Pieces", "leg piece,leg pieces,chicken leg,drumstick", "chicken",
             "Whole legs, skin on.", "raw_chicken_fillet",
             "kg", 25500, None),
            ("Seer Fish (Surmai)", "surmai,seer,seer fish,anjal", "fish",
             "Thick steaks, cut from whole fish.", "fish_ice",
             "kg", 78000, None),
            ("Pomfret", "pomfret,paplet,white pomfret", "fish",
             "Whole silver pomfret, gutted and scaled.", "fish_ice",
             "kg", 69000, None),
            ("Farm Eggs", "egg,eggs,anda", "eggs",
             "Tray-fresh table eggs.", "eggs_carton",
             "piece", 850, 55),
        ],
    },
]


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        for entry in STORES:
            fields = entry["store"]
            store = db.scalars(select(Store).where(Store.name == fields["name"])).first()
            if store is None:
                store = Store(**fields)
                db.add(store)
                db.flush()
            else:
                for key, value in fields.items():
                    setattr(store, key, value)
            store.is_active = True

            for name, aliases, category, desc, shot, unit, price, typical in entry["products"]:
                product = db.scalars(
                    select(Product).where(Product.store_id == store.id, Product.name == name)
                ).first()
                if product is None:
                    product = Product(store_id=store.id, name=name)
                    db.add(product)
                product.aliases = aliases
                product.category = category
                product.description = desc
                product.photo_url = SHOT[shot]
                product.unit = unit
                product.price_paisa = price
                product.typical_weight_g = typical
                product.is_active = True

            print("seeded {} ({} products)".format(store.name, len(entry["products"])))

        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
