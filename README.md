# Meet Near Me

Quick commerce made groceries instant, but fresh meat got left out. The freshest, most
trusted and lowest-priced supply sits with local butchers who can't take remote orders,
fulfil them, or collect payment — so buyers trade either convenience for price, or
freshness for trust. Meet Near Me puts the butchers in your locality online.

Catalogue prices are **final**. The buyer pays at checkout and the butcher cuts
afterwards, so there is no estimate to argue with and nothing to approve before money
moves. Weighing still happens — it records what actually went in the bag rather than
deciding what to charge.

## Order flow

```
new ──► link_sent ──► paid ──► weighed ──► dispatched
 │          │           │         │            │
buyer   payment link  webhook   vendor        ops
/cart   raised at     /webhooks  /vendor      /ops
        checkout      /pinelabs
```

- **new** — order written at catalogue prices, one `order_items` row per line.
- **link_sent** — a Pine Labs payment link is raised immediately for the cart total.
- **paid** — set by the Pine Labs webhook, or by the agent polling `check_payment`.
- **weighed** — the butcher logs what they actually cut. The price does not change; this
  is the receipt, not the bill. Ops watches the drift via `PRICE_GAP_THRESHOLD` (10%).
- **dispatched** — ops marks it out for delivery.

## Pages

| Route | Who | What |
| --- | --- | --- |
| `/` | buyer | Locality header, category tiles, nearby shops carousel, kasai.ai |
| `/shops` | buyer | Every shop in the locality — rating, services, distance, starting price |
| `/store/{id}` | buyer | The shop's cuts by category, with add-to-cart |
| `/cart` | buyer | Lines, bill summary, delivery address, payment options |
| `/order/{id}` | buyer | Status timeline and pay CTA, refreshes every 15s |
| `/vendor` | butcher | Paid orders to cut, log actual weight |
| `/ops` | ops | Password gated. Paid/weighed queue with gap %, dispatch, re-issue link |
| `/proof` | public | Every order — first initial only, timestamps, status |

Order ids are random codes (`MNM4K2P9Q`) rather than sequential integers, so `/order/{id}`
can be shared without exposing the order book or being walkable by a stranger.

The cart lives in a signed cookie, not a table: it survives across Render instances with
no session store, and prices are never kept client-side — every render re-reads them from
the catalogue, so a stale cookie cannot pin an old price.

## kasai.ai

The bubble on the landing page takes free text ("1kg chicken curry cut and half dozen
eggs"), runs it through the same parser the agent API uses, prices it against the live
catalogue and offers to drop the basket straight into the cart.

## Agent tool APIs

Every call needs `X-Agent-Key: $AGENT_API_KEY`.

| Endpoint | Purpose |
| --- | --- |
| `GET /tools/stores` | Shops with locality, rating, hours and starting price |
| `GET /tools/price_list` | Priced products in paisa with the aliases the parser knows. `?store_id=` to narrow |
| `POST /tools/create_order` | `{store_id, customer_name, phone, address, order_text}` → order + priced lines + payment link |
| `GET /tools/order/{id}` | Full order state |
| `GET /tools/check_payment/{id}` | Polls Pine Labs and promotes the order to `paid` when the link is settled |

```bash
curl -H "X-Agent-Key: $AGENT_API_KEY" localhost:8000/tools/price_list

curl -X POST localhost:8000/tools/create_order \
  -H "X-Agent-Key: $AGENT_API_KEY" -H 'Content-Type: application/json' \
  -d '{"store_id":1,"customer_name":"Asha","phone":"9876543210","address":"4 Market Rd","order_text":"1kg chicken curry cut and half dozen eggs"}'
```

## Data model

`stores` → `products`, and `orders` → `order_items`. Each order line stores its own name,
unit and price rather than pointing at the live product: a catalogue edit next year must
not rewrite what someone was charged. `product_id` is kept for tracing and goes null if
the product is deleted.

Money is in **paisa** and weights in **grams**, both integers, so nothing rounds in
storage. `qty` means grams for `unit="kg"` products and piece count for `unit="piece"`.

## Payments

Pine Labs Plural via the `pinelabs-python` SDK, authenticated either way round:

- `PINELABS_API_KEY` is sent as the bearer token as-is — nothing to exchange, nothing to
  expire.
- `PINELABS_CLIENT_ID` + `PINELABS_CLIENT_SECRET` are exchanged for an OAuth2
  client-credentials token, fetched once and cached until `expires_at`.

The key wins if both are set. With neither, the app still runs — checkout just reports
that payments are not switched on instead of failing at the gateway.

Checkout calls `create_payment_link` with the
amount **in paisa** and the order id as `merchant_payment_link_reference` — that field is
the idempotency key, so a retried checkout returns the existing link rather than a second
one. Re-issuing deliberately passes a fresh reference.

`POST /webhooks/pinelabs` is unauthenticated by design (Pine Labs calls it), so it never
trusts the payload. It uses the body only to identify the order, then re-reads the link
state from Pine Labs and marks the order paid only if the API agrees. Without that, anyone
who guessed the URL could mark orders paid.

## Audit trail

Every state change writes to `agent_logs` (`actor`, `action`, `detail`, `timestamp`,
`order_id`). Actors seen in practice: `customer`, `agent`, `vendor`, `ops`,
`pinelabs_webhook`.

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then export the vars you need
python -m scripts.seed        # creates tables + three Shivajinagar shops
uvicorn app.main:app --reload
```

Without `DATABASE_URL` it uses local SQLite (`freshcut.db`), so you can run the whole flow
except the live Pine Labs calls with no Postgres installed.

## Deploy to Render

`render.yaml` is a Blueprint: it provisions the web service and a Postgres instance
together. `DATABASE_URL`, `SECRET_KEY` and `AGENT_API_KEY` are wired automatically; set
`OPS_PASSWORD`, `PINELABS_CLIENT_ID` and `PINELABS_CLIENT_SECRET` when prompted.

- `PUBLIC_BASE_URL` can stay unset — it falls back to Render's `RENDER_EXTERNAL_URL`. It
  is handed to Pine Labs as the post-payment return URL, so a wrong value strands paying
  customers. Set it only for a custom domain.
- `SEED_ON_START=true` loads the demo shops on first deploy. **Turn it off afterwards** —
  the seed updates prices for the shops it owns and would undo a butcher's edits on every
  deploy.
- Point the Pine Labs webhook at `https://<your-app>/webhooks/pinelabs`, and switch
  `PINELABS_BASE_URL` from UAT to production when you go live.

On Render's free tier the web service sleeps when idle, so the first webhook after a quiet
spell may hit a cold start, and free Postgres instances expire — check both before putting
real orders through.

## Photos

Product and storefront images are stock placeholders chosen to be raw rather than cooked;
a couple still do not match their label (there was no genuine raw-drumstick shot, so
"Chicken Leg Pieces" shows fillet). Swap in each shop's own photos before launch.
