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

## Shared assistant and local speech

- Replaced the two transport-specific orchestration paths with one typed, bounded planner and PostgreSQL conversation state. The planner uses allowlisted operations, scoped records, and at most two cloud requests per turn. Confirmed operations commit with their receipt and duplicate confirmations replay the persisted result.
- Keep address slot-filling local and save durable preferences only after an explicit request and confirmation. Added owner-scoped conversation history, deletion, and preference editing.
- Replaced the voice endpoint and assistant page with a shared conversation and a bounded PCM protocol. Browser playback completion enables listening. Manual interrupt cancels the awaiting task and drops pending playback. Local native inference keeps its worker slot until it stops. Cloud-side cancellation and billing effects require provider verification.
- Removed the retired Redis, graph, vector, and tool paths. PostgreSQL now handles catalog filtering, scoped data, and explicit conversation state.

## Demo and distribution

- Added per-user replay receipts for additive stock and cart requests. The dashboard and CSV render seller-scoped SQL metrics using exact purchase-time amounts. Added storefront label details, seller review replies, deterministic 10,000-product data, and 12 synthetic sales weeks.
- Rebuilt CPU images using the locked dependency graph and unprivileged app processes. Compose initializes a fresh database through a dedicated migration job. Added local benchmarks, a Chromium suite, and gating workflows for coverage, dependencies, scanning, and GHCR publication.
