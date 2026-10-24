import os

APP_NAME = "Meet Near Me"
APP_TAGLINE = "Your locality's butchers, open online."

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./freshcut.db")

SECRET_KEY = os.getenv("SECRET_KEY", "dev-insecure-secret-change-me")
OPS_PASSWORD = os.getenv("OPS_PASSWORD", "ops123")
AGENT_API_KEY = os.getenv("AGENT_API_KEY", "dev-agent-key")

PINELABS_BASE_URL = os.getenv("PINELABS_BASE_URL", "https://pluraluat.v2.pinepg.in")

# Two ways in, because Pine Labs issues both. An API key is the bearer token
# directly; a client id/secret pair has to be exchanged for a short-lived token
# first. The key wins when both are set - it is the simpler path, and it is what
# a hackathon tenant hands out.
PINELABS_API_KEY = os.getenv("PINELABS_API_KEY", "")
PINELABS_CLIENT_ID = os.getenv("PINELABS_CLIENT_ID", "")
PINELABS_CLIENT_SECRET = os.getenv("PINELABS_CLIENT_SECRET", "")

# Pine Labs sends the buyer back here after paying, so a wrong value strands them
# on localhost. Render injects RENDER_EXTERNAL_URL with the service's own https
# address, which is right more often than anything typed in by hand.
PUBLIC_BASE_URL = (
    os.getenv("PUBLIC_BASE_URL")
    or os.getenv("RENDER_EXTERNAL_URL")
    or "http://localhost:8000"
).rstrip("/")

# Catalogue prices are final, so the cart total is what the buyer pays. Ops still
# watches how far the butcher's actual cut drifted from it.
PRICE_GAP_THRESHOLD = float(os.getenv("PRICE_GAP_THRESHOLD", "0.10"))

DELIVERY_FEE_PAISA = int(os.getenv("DELIVERY_FEE_PAISA", "2900"))
FREE_DELIVERY_ABOVE_PAISA = int(os.getenv("FREE_DELIVERY_ABOVE_PAISA", "50000"))

DEFAULT_LOCALITY = os.getenv("DEFAULT_LOCALITY", "Shivajinagar")
DEFAULT_CITY = os.getenv("DEFAULT_CITY", "Bengaluru")

OPS_COOKIE = "mnm_ops"
CART_COOKIE = "mnm_cart"
CART_MAX_AGE = 7 * 24 * 60 * 60
