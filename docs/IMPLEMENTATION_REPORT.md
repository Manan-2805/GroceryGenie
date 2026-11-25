# GroceryGenie recovery report

## Architecture and completed workflows

FastAPI, PostgreSQL, React/Vite and nginx now ship as one CPU Compose application. The API and assistant use shared domain operations. PostgreSQL holds the transaction boundary for stock, orders, seller ownership and confirmation receipts. The frontend and the voice WebSocket share the owned assistant conversation. This removed the Redis, Qdrant, Neo4j, MCP, Torch and duplicate orchestration paths. [Dependency changes](DEPENDENCY_CHANGES.md)

- Public catalog with indexed lexical search and structured food, price, package, rating and stock fields. Missing allergen values stay unknown.
- Google OIDC integration, revocable sessions and deliberate customer/seller mode switching. Carts, addresses, catalog changes, reports, fulfillment and conversation access are scoped to the signed-in account.
- Exact INR cart and quote totals, simulated payment and atomic multi-seller checkout. Stock, immutable line snapshots and seller-specific fulfillment records commit together. Retry keys replay the receipt.
- Seller storefront operations, stock increases, delivery status updates, revenue, profit, repeat-customer aggregates, low-stock views, weekly forecast, CSV and one reply per purchased-product review.
- Typed, bounded assistant plans and server-owned confirmation previews. Budgeted product selection and private address entry retain supplied fields through follow-ups. Explicit preferences are stored only after confirmation and can be edited or deleted.
- Dedicated Text and Voice modes, with local speech, AudioWorklet capture, playback-driven listening, manual interruption and cleanup. Committed assistant changes remain in the conversation after an interrupted response.
- Non-destructive, repeatable seed with 10,000 product keys and 192 synthetic orders. Docker startup uses a dedicated migration job. The release workflow gates GHCR publication on local-equivalent checks and container scans.

## Verification

| Check | Observed result |
|---|---|
| Fresh PostgreSQL migrations and Alembic schema comparison | Applied through 42045bef3db3. Alembic reported no new upgrade operations. |
| Backend, typing and formatting | 22 tests passed with 81.42% application coverage. Checks included Ruff, strict Mypy and TypeScript, formatting and the production build. |
| Chromium 149 with real local speech enabled | Four scenarios passed. Public catalog and Google-only entry, authenticated text confirmation, multi-seller simulated checkout and the hands-free browser workflow using a synthetic microphone and the real local speech engines. |
| Dependency and static checks | The initial Python and npm scans reported 30 and 21 findings respectively. Both registries reported zero known vulnerabilities after the package updates. Bandit found zero issues. Authlib still emits a deprecation notice about its HTTP transport. |
| Container security | Trivy 0.76.2 found zero high or critical findings in the Wolfi Python backend and Alpine nginx 1.30.7 frontend runtime images after replacing the vulnerable base layers. |
| Frontend production build | Approximately 474 kB main JavaScript, 139 kB gzip. Public source maps were disabled. |
| Seed replay | Exactly 10,000 synthetic products and 192 historical orders. Re-seeding preserved a stock edit. |
| Docker | Both final non-root CPU runtimes built. The clean PostgreSQL 16.16 Compose deployment provisioned speech weights without host Python, migrated, seeded 10,000 products and 192 orders, and returned healthy database and speech flags. |

The Chromium and API suites use disposable accounts and exercise the normal session cookie path. The callback exchange is mocked. Live Google authorization and paid cloud planning remain unverified because the workspace has neither credential configured. The controlled LLM smoke script is limited to one read-only planning request and uses provider rates supplied by the operator. No cloud credits have been consumed.

## Audit dispositions

| Finding group | Recovery evidence |
|---|---|
| GG-001, GG-014–GG-017, GG-034, GG-052, GG-053 | Tracked ORM, clean migration, real PostgreSQL cart, checkout, seller fulfillment, reporting and review tests. |
| GG-002–GG-010, GG-012, GG-026 | Revocable account sessions, owner-scoped access and server-issued confirmations. The signed-in application and mocked callback were exercised. Live OAuth and cloud routing are release checks. |
| GG-027–GG-029, GG-043, GG-046, GG-048 | Indexed catalog and explicit seed paths replace the old vector, graph, startup probes and cache dependencies. Search timings were measured against the full synthetic catalog. |
| GG-030–GG-032, GG-055–GG-057 | Bounded CPU speech, playback-driven listening, explicit reconnect and manual cancellation. Docker and Chromium used actual speech assets. GPU and cloud-side cancellation remain unverified. |
| GG-033, GG-038–GG-045, GG-054 | Local quality, dependency and image verification is recorded above. CI and GHCR still require a remote run. |

The plan retains the complete finding-to-task matrix, including exclusions and acceptance criteria.

## Performance

The local environment reported AMD Ryzen 7 7840HS, 7,944 MiB WSL2 RAM, and Linux x86-64. NVIDIA NVML initialization failed, so all measurements used CPU.

| Workload | Result |
|---|---|
| 100 catalog clients, 1,000 filtered product requests | 0 failures. p50 282 ms, p95 368 ms, 334 requests/s. |
| 150 catalog clients, 600 filtered product requests | 0 failures. p50 453 ms, p95 553 ms, 329 requests/s. |
| Parakeet/Piper, four synthetic English utterances | ASR loaded in 5.80 s, then p50 190 ms. TTS p50 was 95 ms. One ASR token edit converted “fifty” to “50.” |
| Canary/Piper, same four utterances | ASR loaded in 0.50 s, then p50 194 ms. TTS p50 was 80 ms. One ASR token edit converted “as” to “is.” |
| Five authenticated Parakeet/Piper sessions | Five correct responses. Median cold time to first reply PCM 7.38 s. |
| Five authenticated Canary/Piper sessions with speech-boundary buffering | Five correct responses in both runs. First reply PCM reached clients in a median 2.02 s cold and 0.78 s warm. Maximum 2.20 s cold and 0.95 s warm. |
| Backend after both Canary runs | 694,488 KiB resident memory and 162% cumulative CPU as reported by the operating system. |

Catalog performance reflects filtered reads against the seeded application. Voice timing ends at the first WebSocket PCM frame. Speaker onset, microphone diversity, room noise and cloud-provider latency remain separate measurements. Canary is the CPU default because of the cold-start result.

## Limitations and release status

- Voice uses English and explicit reconnection. Manual interruption stops playback and cancels the server wait. A running native inference holds its capacity until completion. Natural barge-in and wake words are deferred. Cloud-side cancellation and billing require provider evidence.
- Indexed lexical and structured search supports the catalog scope. Product recommendations remain limited by label data. The application cannot certify allergen safety.
- Local image scanning passed. GitHub Actions and GHCR publication remain pending, alongside live Google and Moonshot verification. Opening the single PR to main requires a separate approval.

[Recovery tasks and GG-001–GG-057 traceability](FINAL_IMPLEMENTATION_PLAN.md) [Historical audit](PROJECT_AUDIT.md) [Setup and demonstration](../README.md)
