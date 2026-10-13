# Karigar Link V2.1 — Stability Release

## Why V2.1 exists
V2 had the correct feature set but its two-server local setup could easily be started from the wrong directory. V2.1 makes the normal experience one-server: FastAPI serves both the API and the complete frontend.

## V2 intelligence modules
### Demand & Forecasting
- 3-month product demand estimate
- recent-sales baseline
- calendar-month seasonality
- expected revenue
- capacity / production gap
- peak-demand indication
- confidence level
- “What Should I Make Next?”

### Market Intelligence
- product-to-market opportunity ranking
- demand / competition / price-fit signals
- seasonal signal
- market comparison
- best expansion opportunity
- explainable local scoring

### Digital Marketplace
- artisan storefront
- product listings
- buyer request board
- buyer requirement posting
- buyer-request → product matching
- bulk enquiry flow
- opportunity score on listings

## V1 preserved
Historical data management, products, pricing intelligence, market & buyer match, market-ready studio, buyer enquiries, smart catalogue, impact dashboard, SQLite database, demo seed data and free local processing remain included.

## Stability changes
- One-server startup at port 8765
- FastAPI serves `/` and `/app/*`
- Frontend API base automatically uses same origin on port 8765
- Optional compatibility with port 5500/5501 remains
- Added buyer request matching endpoint
- Added one-click Windows launcher
- Added startup instructions
