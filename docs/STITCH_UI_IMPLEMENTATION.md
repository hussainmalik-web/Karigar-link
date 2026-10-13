# Stitch UI implementation

The supplied Stitch package informed the original V2.3 frontend. The current makeover follows the later handicraft-focused handloom reference across the dashboard, customer storefront and operations console.

Current design direction:
- Handloom hero imagery and a compact pill-navigation feel
- Natural cloth, indigo teal, terracotta and turmeric accents
- Rounded white surfaces, generous spacing and subtle shadows
- Clean sans-serif type for both editorial copy and business data
- Responsive desktop/tablet/mobile layout with scroll-triggered reveals and reduced-motion support

The implementation intentionally keeps the existing vanilla frontend runtime because the V2.3 backend already exposes the complete application API surface. This avoids replacing working V2.3 business logic with a static design-only build.

The supplied React/TypeScript Stitch source is retained outside the runtime package; this package contains the integrated production frontend served by FastAPI.
