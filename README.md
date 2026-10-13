# Karigar Link — Artisan Business OS

A free-first local artisan business intelligence and market-linkage application.

## Preserved V2.3 capabilities

- Overview / business health
- Products and craft catalogue
- Demand & Forecasting
- Pricing Intelligence
- Market Intelligence
- Market & Buyer Match
- Digital Marketplace
- Smart Catalogue
- Market Ready Studio
- Buyer Enquiries
- Historical Sales Data
- Business Insights & Impact

## Added live sections

- Market News
- Government Schemes
- Business Opportunities

These sections use official-source routes and show source/verification information. They fail safely when an external source cannot be reached and do not invent private contacts, orders, bids, prices or deadlines.

## UI

The refreshed frontend uses a handicraft-first, contemporary craft direction:

- An artisan-led handloom hero, with compact navigation and natural, tactile surfaces
- Natural cloth, deep craft teal, terracotta and turmeric accents across dashboard, storefront and admin
- Calm, spacious cards with rounded corners, subtle woven cues and scroll-triggered reveals
- Clear data hierarchy and responsive desktop/tablet/mobile layouts
- Existing business modules, APIs and customer flows remain integrated

The visual redesign is implemented in the existing FastAPI frontend without removing the original V2.3 backend APIs or business logic.

## Run on Windows PowerShell

From the project root:

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8765
```

Open:

`http://127.0.0.1:8765`

Keep the PowerShell window running while using the application.

If port 8765 is already in use:

```powershell
python -m uvicorn app.main:app --reload --port 8777
```

Then open `http://127.0.0.1:8777`.

## Important

Do not start a separate frontend server. The FastAPI application serves the complete frontend from `/app` and the root route.

If the browser displays an older cached interface, press:

`Ctrl + Shift + R`

## Karigar AI Assistant

The assistant is now a data-aware conversational layer. It remembers the recent conversation on the device, resolves products from earlier messages, answers questions from the application's stored data, and can execute navigation actions such as opening Smart Catalogue, Demand & Forecasting, Pricing Intelligence, Market Intelligence, Historical Data, Government Schemes, Market News and Business Opportunities.

For richer open-ended natural-language answers, Karigar Link can use a local Ollama model. This is optional and does not require a paid API:

```env
KARIGAR_ASSISTANT_OLLAMA=1
OLLAMA_URL=http://127.0.0.1:11434/api/generate
OLLAMA_MODEL=llama3.2:3b
```

If Ollama is unavailable, the assistant falls back to the built-in data-aware task engine and does not invent business figures.


## Integrated local AI assistant (free)

The existing Karigar Link assistant panel now uses the Personal AI Assistant's local Ollama model (`llama3.2:1b`) for open-ended conversation. The chat remains inside the Karigar Link website; no separate assistant website is needed. Existing product-aware answers and navigation actions are preserved. The model receives relevant recorded product, buyer, sales-summary, page and recent-conversation context, and is instructed not to invent missing business data.

Before launching Karigar Link, ensure Ollama is running and the model is installed. In PowerShell, run `ollama list`; if `llama3.2:1b` is missing, run `ollama pull llama3.2:1b`. The assistant's status appears in the embedded chat panel. This integration is local to the same computer; it is not automatically available to visitors on a public website unless a secure hosted backend/model is configured.


## Open-ended AI chat fix

The embedded assistant now sends ordinary questions to the local Ollama model even when they mention topics such as pricing, demand, buyers, catalogues, schemes or sales. It navigates to a module only when the user explicitly asks to open or switch to one. General questions can be answered without matching a saved database record; claims about the user's actual business still use recorded data only.


## New in Karigar Link Commerce MVP

### Separate customer storefront

- Open `http://127.0.0.1:8765/app/store.html` while the backend is running.
- Product search and price sorting, product cards, basket/cart, guest checkout and order confirmation.
- Seller order list is available in the artisan dashboard under `Customer Orders`.
- COD demo orders; stock is validated and decremented atomically when an order is placed.
- Free shipping for order subtotals of ₹999 or more; otherwise ₹59 shipping in this demo.
- Order tracking by order number + checkout email; cancellation is available while an order is `placed` or `confirmed`.
- Customer account registration/sign-in, guest checkout, basic wishlist capture by email and product reviews (reviews/wishlist are demo features and are not yet tied to verified purchases).
- Only products that are published, in stock, priced and owned by an artisan with an active ₹199 plan appear publicly.

### Subscription plans

- **₹99 / 30 days — Artisan Business OS:** existing artisan dashboard, product management, embedded Karigar AI assistant and intelligence modules; no public customer listings.
- **₹199 / 30 days — Business OS + Marketplace:** all of the above plus public listings, stock sync and customer order flow.
- No marketplace sales commission is implemented in this model.
- `Plans & Store Sync` is in the artisan sidebar. Subscription activation is **DEMO ONLY** and records a local demo reference; it does not take money.

### Admin console

- Open `http://127.0.0.1:8765/app/admin.html`.
- Review artisan/subscription counts, listings and orders; update order status and cancel eligible orders.
- Local development key is `dev-admin-change-me` unless `KARIGAR_ADMIN_KEY` is set. Set a long random value in your environment before exposing any deployment. This MVP admin key is not production-grade authentication.

### Data / payment / deployment limitations

This is a functional local prototype, not yet a production marketplace. A real payment gateway (for subscription billing and prepaid customer orders), refund/payment reconciliation, courier/shipping integration, purchase-verified customer reviews, seller verification, secure role-based admin access, email/SMS notifications, tax invoices, privacy/terms/returns policy and deployment hardening still need to be implemented before launch. Do not collect real money or expose the local admin console publicly yet.

The new SQLite tables are created automatically and older databases are migrated in place. Keep a backup of `backend/karigar_link.db` before upgrades.

## Commerce publishing troubleshooting (local demo)

1. Start Karigar Link using `RUN_KARIGAR_LINK.bat` and keep the backend terminal open.
2. Open the artisan dashboard at `http://127.0.0.1:8765/` and choose **Commerce & Storefront → Plans & Store Sync**.
3. Activate **Business OS + Marketplace (₹199)** in demo mode. Demo activation does not charge money.
4. Set product stock to at least `1`, then click **Publish / Sync**. The page now shows a visible success or error message instead of relying on a browser alert.
5. Open **Customer Storefront** from the new sidebar group and refresh. Only products with a valid positive price, stock greater than zero, published status, and an active ₹199 plan are shown.
6. If the message says the plan is missing, activate the ₹199 demo plan. If it reports stock or price, update the product and retry.

Commerce navigation is grouped separately from Core Operations under **Commerce & Storefront**, with Plans & Store Sync, Customer Orders, and Customer Storefront together.
