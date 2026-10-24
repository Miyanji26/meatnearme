from pathlib import Path

from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from app import config, pricing
from app.models import CATEGORY_LABELS, STATUS_FLOW, STATUS_LABELS

TEMPLATE_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


def stars(rating) -> Markup:
    """Five stars with the lit portion clipped to the exact rating.

    Rounding to whole or half stars either flatters or shortchanges the shop, and
    the half-star glyphs are not reliably present in system fonts.
    """
    pct = max(0.0, min(float(rating or 0) / 5.0, 1.0)) * 100
    return Markup(
        '<span class="bar">★★★★★<i style="width:{:.1f}%">★★★★★</i></span>'.format(pct)
    )


def distance(km) -> str:
    value = float(km or 0)
    if value <= 0:
        return "nearby"
    if value < 1:
        return "{:.0f} m".format(value * 1000)
    return "{:.1f} km".format(value)


def _asset_version() -> str:
    """Cache-buster for the stylesheet, keyed on its mtime.

    Without it a deploy ships new CSS that returning phones never fetch, because
    StaticFiles serves it under a URL that has not changed.
    """
    try:
        return str(int((STATIC_DIR / "style.css").stat().st_mtime))
    except OSError:
        return "0"


templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
templates.env.filters["rupees"] = pricing.rupees
templates.env.filters["rupees_short"] = pricing.rupees_short
templates.env.filters["kg"] = pricing.grams_to_kg_str
templates.env.filters["stars"] = stars
templates.env.filters["distance"] = distance
templates.env.globals["STATUS_FLOW"] = STATUS_FLOW
templates.env.globals["STATUS_LABELS"] = STATUS_LABELS
templates.env.globals["CATEGORY_LABELS"] = CATEGORY_LABELS
templates.env.globals["APP_NAME"] = config.APP_NAME
templates.env.globals["APP_TAGLINE"] = config.APP_TAGLINE
templates.env.globals["asset_version"] = _asset_version
