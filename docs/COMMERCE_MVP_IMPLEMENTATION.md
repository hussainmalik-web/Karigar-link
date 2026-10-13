# Karigar Link Commerce MVP — Implementation Notes

## Product decision

Karigar Link retains its original Artisan Business OS. Commerce is added as an adjacent customer-facing storefront backed by the same FastAPI service and SQLite product records.

## Plans

| Plan | Price | Access |
|---|---:|---|
| Artisan Business OS | ₹99 / 30 days | Existing business tools; no public listing |
| Business OS + Marketplace | ₹199 / 30 days | Existing tools + customer storefront listing, stock and orders |

No sales commission is included in the current concept. Local plan activation is simulated and is not a payment gateway.

## Data flow

1. Artisan selects a plan in `Plans & Store Sync`.
2. An active ₹199 plan permits publication of priced products with stock greater than zero.
3. `/api/store/products` returns published, in-stock products from eligible sellers.
4. Customer checkout revalidates stock and seller subscription on the server, creates an order + item rows and decrements stock.
5. The admin console reviews orders and updates fulfilment status. Cancellation of an eligible order returns the quantity to stock.

## Main routes

- `GET /api/subscriptions/plans`
- `GET /api/subscriptions/status`
- `POST /api/subscriptions/activate` (demo/manual only)
- `POST /api/products/{id}/marketplace-listing`
- `GET /api/store/products`
- `GET /api/store/products/{id}`
- `POST /api/store/orders`
- `GET /api/store/orders/track`
- `POST /api/store/orders/cancel`
- `POST /api/store/reviews`
- `POST /api/store/wishlist`
- `GET /api/admin/overview`
- `PATCH /api/admin/orders/{id}`

## Production checklist still required

- Payment gateway integration and verified webhook processing for subscription renewals and prepaid checkout.
- Customer accounts, secure authorization, verified reviews and wishlist ownership.
- Secure admin authentication/roles; rate limiting, CSRF protections where relevant, audit logs and secrets management.
- Seller onboarding/verification, returns/refunds policy, shipping provider, tax/invoice support and email/SMS notifications.
- Automated tests, backups, monitoring, privacy/terms disclosures and production hosting.
