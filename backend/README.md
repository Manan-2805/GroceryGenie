# Backend

See the [project README](../README.md) for setup, test commands and deployment.

`app/api` exposes web and assistant transports. `app/commerce` coordinates cart, quote, checkout and replay rules. `app/catalog` holds validated product operations and search. `app/assistant` validates and executes plans against those operations. `app/services/voice` wraps local CPU speech inference. Schema revisions live in `app/db/migrations`.

Production startup expects a migrated PostgreSQL database. The application process can serve without model assets or cloud keys. Run `python -m app.db.seed` explicitly for the showcase data.
