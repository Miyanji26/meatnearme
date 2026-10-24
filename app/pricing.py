import re
from typing import List, Optional

KG_UNITS = {"kg", "kgs", "kilo", "kilos", "kilogram", "kilograms"}
GRAM_UNITS = {"g", "gm", "gms", "gram", "grams"}
PIECE_UNITS = {"pc", "pcs", "piece", "pieces", "no", "nos", "packet", "packets", "pkt"}

WORD_QTY = {
    "half": 0.5,
    "aadha": 0.5,
    "adha": 0.5,
    "quarter": 0.25,
    "pav": 0.25,
    "one": 1.0,
    "two": 2.0,
    "three": 3.0,
    "four": 4.0,
    "five": 5.0,
    "½": 0.5,
    "¼": 0.25,
}

_UNIT_WORDS = "|".join(sorted(KG_UNITS | GRAM_UNITS | PIECE_UNITS, key=len, reverse=True))
_QTY_WORDS = "|".join(sorted(WORD_QTY, key=len, reverse=True))

# "dozen" is a multiplier, not a quantity: "2 dozen eggs" is 24, not 2. The count
# in front of it is spelled out as often as it is written ("half dozen", "two
# dozen"), and leaving those words uncaptured stranded them next to the expanded
# "12 pcs" - the parser then read the stray word and threw the 12 away.
_DOZEN_RE = re.compile(
    r"(?<!\w)(?:(?P<n>\d+(?:\.\d+)?|" + _QTY_WORDS + r")\s*)?(?:dozens?|doz)(?!\w)",
    re.IGNORECASE,
)

_QTY_RE = re.compile(
    r"(?P<num>\d+\s*/\s*\d+|\d+(?:\.\d+)?|" + _QTY_WORDS + r")"
    r"\s*(?P<unit>" + _UNIT_WORDS + r")?\b",
    re.IGNORECASE,
)

_SPLIT_RE = re.compile(r"[,\n;+]|\band\b|\baur\b", re.IGNORECASE)


def rupees(paisa: Optional[int]) -> str:
    if paisa is None:
        return "-"
    return "₹{:,.2f}".format(paisa / 100.0)


def rupees_short(paisa: Optional[int]) -> str:
    """Headline form: drops the paise when there are none."""
    if paisa is None:
        return "-"
    if paisa % 100 == 0:
        return "₹{:,.0f}".format(paisa / 100.0)
    return rupees(paisa)


def grams_to_kg_str(grams: Optional[int]) -> str:
    if grams is None:
        return "-"
    if grams < 1000:
        return "{} g".format(grams)
    return "{:.2f} kg".format(grams / 1000.0).replace(".00 kg", " kg")


def _expand_dozens(chunk: str) -> str:
    def replace(match):
        count = _parse_number(match.group("n")) if match.group("n") else 1.0
        return " {:g} pcs ".format(count * 12)

    return _DOZEN_RE.sub(replace, chunk)


def _parse_number(raw: str) -> float:
    raw = raw.strip().lower()
    if "/" in raw:
        num, den = raw.split("/", 1)
        return float(num.strip()) / float(den.strip())
    if raw in WORD_QTY:
        return WORD_QTY[raw]
    return float(raw)


def _match_product(chunk: str, products: list):
    """Longest alias wins so "chicken boneless" beats a bare "chicken" entry."""
    best = None
    best_len = 0
    for product in products:
        for alias in product.alias_list():
            if alias and alias in chunk and len(alias) > best_len:
                best, best_len = product, len(alias)
    return best


def _quantity_for(chunk: str, product):
    match = _QTY_RE.search(_expand_dozens(chunk))
    if not match:
        return (1.0, product.unit)

    value = _parse_number(match.group("num"))
    unit = (match.group("unit") or "").lower()

    if unit in GRAM_UNITS:
        return (value / 1000.0, "kg")
    if unit in KG_UNITS:
        return (value, "kg")
    if unit in PIECE_UNITS:
        return (value, "piece")
    return (value, product.unit)


def parse_order(text: str, products: list) -> dict:
    """Turn free-text ("1kg mutton curry cut, 2 chicken breast") into priced lines."""
    items: List[dict] = []
    unmatched: List[str] = []

    for raw_chunk in _SPLIT_RE.split(text or ""):
        chunk = raw_chunk.strip().lower()
        if not chunk:
            continue

        product = _match_product(chunk, products)
        if product is None:
            unmatched.append(raw_chunk.strip())
            continue

        qty, qty_unit = _quantity_for(chunk, product)
        if qty <= 0:
            unmatched.append(raw_chunk.strip())
            continue

        if qty_unit == "kg":
            weight_g = int(round(qty * 1000))
            if product.unit == "kg":
                amount = int(round(product.price_paisa * qty))
            else:
                pieces = qty * 1000 / (product.typical_weight_g or 1000)
                amount = int(round(product.price_paisa * pieces))
        else:
            per_piece_g = product.typical_weight_g or 1000
            weight_g = int(round(qty * per_piece_g))
            if product.unit == "piece":
                amount = int(round(product.price_paisa * qty))
            else:
                amount = int(round(product.price_paisa * weight_g / 1000.0))

        items.append(
            {
                "product_id": product.id,
                "name": product.name,
                "qty": round(qty, 3),
                "qty_unit": qty_unit,
                "weight_g": weight_g,
                "amount_paisa": amount,
                "source": raw_chunk.strip(),
            }
        )

    return {
        "items": items,
        "unmatched": unmatched,
        "total_weight_g": sum(i["weight_g"] for i in items),
        "total_paisa": sum(i["amount_paisa"] for i in items),
    }


def value_at_weight(items_paisa: int, expected_weight_g: int, actual_weight_g: int) -> int:
    """What the cut that actually went in the bag was worth, at the blended rate the
    basket implies. The buyer already paid a fixed price - this is the transparency
    number ops compares against, not a new charge."""
    if not expected_weight_g or not items_paisa:
        return items_paisa
    return int(round(items_paisa * actual_weight_g / float(expected_weight_g)))
