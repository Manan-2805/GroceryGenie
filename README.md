# GroceryGenie

GroceryGenie is a grocery marketplace portfolio project with a web storefront, seller tools, and a shared text and hands-free voice assistant. Checkout and seeded data are simulated. Prices are in INR.

## Start the application

Docker Compose v2 gives you the same Linux CPU runtime across supported hosts. Copy `.env.example` to `.env`, set a URL-safe database password and a random session signing key, then run:

```sh
docker compose up --build -d --wait
docker compose exec backend python -m app.db.seed
```

Open `http://localhost:8080/items` to browse the catalog. Migration runs in a dedicated Compose job. The explicit showcase seed inserts 10,000 distinct listings across eight shops and 192 synthetic historical orders. Run it again without overwriting existing records. Use `--as-of YYYY-MM-DD` to reproduce the synthetic sales dates on a fresh database.

Register `http://localhost:8080/api/v1/auth/google/callback` as an authorized Google OAuth redirect and supply the client ID and secret in your local configuration. Keep the redirect, browser origin and backend configuration consistent. Catalog browsing works with Google and the assistant unconfigured. For a remote installation, terminate HTTPS at your ingress and configure `ENV_MODE=production`, HTTPS frontend/origin/redirect values and a stable secret.

## Assistant

Open **AI Assistant** after signing in. Select Text Mode or Voice Mode. Confirm proposed writes after reviewing the exact values. Text and voice use the same account, conversations and action receipts. Examples:

- “Find cheap milk under ₹50.”
- “Show my orders.”
- “Add address.” Answer the requested fields, then check the full preview.
- “Remember that I prefer vegetarian products.”
- In seller mode, “Show inventory” or “Show my pending orders.”

Simple commands and local address entry work without cloud keys. Broader planning uses a configured OpenAI-compatible cloud endpoint. Supply a JSON array in `LLM_PROVIDERS` with `name`, `base_url` ending in the provider’s API version path, `model`, and `api_key`. For Moonshot, start with the Kimi K3 example in [.env.example](.env.example). The example selects low reasoning effort and the provider's completion-token limit to bound planning latency and output. An optional fallback is the second entry. The optional `json_object` switch controls whether the request asks for a JSON response format. Local schema validation applies regardless of the provider setting. Keep the credentials in runtime configuration. Saved address fields stay out of provider requests during the local address flow.

To verify one live Moonshot planning request after configuring the key and current rates, execute the checked-in smoke script inside the backend container:

```sh
docker compose exec -T backend python - --live < scripts/smoke_llm.py
```

This sends a single synthetic read-only request and checks the returned intent. [Kimi K3 API parameters](https://platform.kimi.ai/docs/guide/kimi-k3-quickstart) [Kimi K3 pricing](https://www.kimi.com/en/blog/kimi-k3)

### Enable hands-free voice

Once the CPU image is built or pulled, download speech assets into a dedicated volume using that image:

```sh
docker compose -f compose.yaml -f compose.voice.yaml run --rm speech-assets
docker compose -f compose.yaml -f compose.voice.yaml up -d --wait
```

The backend mounts the populated volume read-only. Canary int8 is the CPU default for its measured cold-start advantage. The portable download script also accepts `--with-parakeet` for local model comparisons. Select Parakeet with `ASR_MODEL=nemo-parakeet-tdt-0.6b-v2` and `ASR_SUBDIR=asr` when both assets are present. Check the upstream cards for terms and attribution. [Canary ONNX export](https://huggingface.co/istupakov/canary-180m-flash-onnx) [Parakeet ONNX export](https://huggingface.co/istupakov/parakeet-tdt-0.6b-v2-onnx) [Piper Lessac model card](https://huggingface.co/rhasspy/piper-voices/tree/b145f2ac26522d6a2ccde0164b7b0e48b1e3199c/en/en_US/lessac/medium)

Use desktop Chromium with microphone permission on localhost or HTTPS. Start Voice Mode explicitly. The mic opens after the greeting finishes and reopens after each response. **Interrupt** stops the current playback and asks the server to abandon unfinished work. A committed action remains in the conversation. Native speech inference still occupies its worker slot until it finishes. Five sessions can connect per API process, with one inference job active at a time. Voice is English-only. Text Mode remains available when local speech fails. Automatic wake word and speech-during-playback interruption are outside the current implementation.

## Development and verification

Run `make install` with Python 3.12, uv and Node 22.23.5 available. Set `DATABASE_URL` to a local application database and use a separate migrated, disposable `TEST_DATABASE_URL` for test data. Migrate with `make migrate`. The Vite proxy defaults to `http://127.0.0.1:8000` and accepts `GROCERY_VITE_PROXY` for an alternate local backend.

| Command | Purpose |
|---|---|
| `make check` | Ruff, strict Mypy/TypeScript, formatting, backend tests and a production frontend build |
| `make coverage` | Application coverage with an 80% minimum |
| `make security` | Bandit and Python/npm package advisory checks |
| `make test-e2e` | Chromium against a running isolated fixture stack |
| `docker compose config --quiet` | Resolve Compose structure without printing runtime settings |

The Chromium suite uses synthetic accounts in a disposable database, through the regular authenticated cookie path. Install the browser with `uv run --locked playwright install chromium` from `backend/`. Set `E2E_BASE_URL` if Vite uses a different origin. Use `git config core.hooksPath scripts` to enable the local pre-commit hook.

Use `scripts/benchmark_catalog.py` with a loopback URL for the seeded catalog workload. Run `scripts/benchmark_voice.py` and `scripts/benchmark_voice_session.py` with the locked backend interpreter and `PYTHONPATH=backend` to measure models and the authenticated server path. The local scripts use synthetic or existing opt-in assets and consume zero cloud API credits.

## Demonstration sequence

1. Browse and compare packages from two shops, add them to a cart, choose an address and place a simulated order.
2. Switch to a seller account that owns one of the products. Advance only that seller’s fulfillment and view its revenue, low stock and CSV report.
3. Return to the buyer account. Track each fulfillment and review an item once its shipment is delivered.
4. Open the assistant. Search by budget, confirm a saved preference or address, switch to Voice Mode and check an order hands-free.
5. Interrupt a voice response and end the session. Review the conversation and the committed action outcome in Text Mode.

The backend is a FastAPI monolith. PostgreSQL holds transactional commerce, indexed catalog search, sessions and accepted assistant receipts. The React browser and voice WebSocket use the same shared business operations. [Audit](docs/PROJECT_AUDIT.md) [Implementation plan](docs/FINAL_IMPLEMENTATION_PLAN.md) [Dependency changes](docs/DEPENDENCY_CHANGES.md)
