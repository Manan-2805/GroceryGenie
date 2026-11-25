# AI implementation changelog

## Schema recovery and safe startup

- Restored SQLAlchemy models described by the tracked revisions, scoped the model-weight ignore rule, and use UTC-aware defaults.
- Removed startup migration, network and destructive seed work. Startup now leaves migration and seed to explicit commands. The reset entry point is retired and the seed uses stable synthetic records without overwriting existing data.
- Replaced Windows-specific Make recipes with portable check and explicit formatting, migration, and seed targets.

## Google sessions and commerce

- Replaced the development and password login paths with Google authorization, revocable opaque sessions, same-origin write checks, and deliberate customer/seller mode switching. Scope chat and WebSocket identity to the authenticated owner.
- Added checkout quotes and idempotent, transactional multi-seller orders. Inventory uses row locks and the order stores immutable item, cost, price, and delivery snapshots. Amounts use fixed-scale decimal INR. The simulated payment status lives on the parent order.
- Share cart and fulfillment rules with other transports, isolate seller fulfillment projections and enforce forward transitions. Customer pages show their combined order with seller fulfillment statuses.
- Added structured grocery fields and PostgreSQL search, scoped product updates, bounded image handling, saved address rules, purchase-backed reviews, seller replies and seller-only sales reports.
