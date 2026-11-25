# Dependency changes

Versions below compare the audited branch point with the recovery locks. The lockfiles are authoritative for other transitive changes.

## Backend

| Package | Previous | Recovery | Reason |
|---|---:|---:|---|
| aiosqlite | 0.22.1 | — | Removed from the direct runtime graph with the retired services and tooling. |
| authlib | 1.7.2 | 1.9.10 | Security advisory remediation. |
| certifi | 2026.6.17 | 2026.11.20 | Security advisory remediation. |
| cryptography | 49.0.0 | 50.0.2 | Security advisory remediation. |
| filelock | 3.29.7 | 4.3.1 | Security advisory remediation. |
| granian | 2.7.9 | — | Removed from the direct runtime graph with the retired services and tooling. |
| joserfc | 1.7.3 | 1.8.0 | Security advisory remediation. |
| mcp | 1.28.1 | — | Removed from the direct runtime graph with the retired services and tooling. |
| msgpack | 1.2.1 | 1.2.4 | Security advisory remediation. |
| neo4j | 6.2.0 | — | Removed from the direct runtime graph with the retired services and tooling. |
| nvidia-ml-py3 | 7.352.0 | — | Removed from the direct runtime graph with the retired services and tooling. |
| onnxruntime | 1.24.4 | 1.32.0 | CPU-native engine for local ASR and Piper. |
| onnxruntime-directml | 1.24.4 | — | Removed from the direct runtime graph with the retired services and tooling. |
| onnxruntime-gpu | 1.27.0 | — | Removed from the direct runtime graph with the retired services and tooling. |
| openai | 2.45.0 | — | Removed from the direct runtime graph with the retired services and tooling. |
| pillow | 12.3.0 | 13.0.0 | Validate and re-encode uploaded catalog images. Now a direct dependency. |
| pip | 26.1.2 | 26.3 | Security advisory remediation. |
| pipecat-ai | 1.5.0 | — | Removed from the direct runtime graph with the retired services and tooling. |
| pydub | 0.25.1 | — | Removed from the direct runtime graph with the retired services and tooling. |
| pyjwt | 2.13.0 | — | Removed from the direct runtime graph with the retired services and tooling. |
| pytest-cov | — | 7.1.0 | Required application coverage gate. |
| python-json-logger | 4.1.0 | — | Removed from the direct runtime graph with the retired services and tooling. |
| python-multipart | 0.0.32 | 0.0.32 | Direct multipart form parser for image uploads. |
| qdrant-client | 1.18.0 | — | Removed from the direct runtime graph with the retired services and tooling. |
| redis | 8.0.1 | — | Removed from the direct runtime graph with the retired services and tooling. |
| sentence-transformers | 5.6.0 | — | Removed from the direct runtime graph with the retired services and tooling. |
| slowapi | 0.1.10 | — | Removed from the direct runtime graph with the retired services and tooling. |
| sounddevice | 0.5.5 | — | Removed from the direct runtime graph with the retired services and tooling. |
| soundfile | 0.14.0 | — | Removed from the direct runtime graph with the retired services and tooling. |
| torch | 2.13.0 | — | Removed from the direct runtime graph with the retired services and tooling. |
| urllib3 | 2.7.0 | 2.8.0 | Security advisory remediation. |

The ASR adapter stays on onnx-asr 0.11.0 and Piper on 1.4.2. The runtime ships one ONNX CPU provider. Named speech weights are separate downloads and are absent from the images.

## Frontend

| Package | Previous | Recovery |
|---|---:|---:|
| axios | 1.18.1 | 1.21.1 |
| follow-redirects | 1.16.0 | 1.16.3 |
| react-router | 7.18.1 | 7.18.7 |
| react-router-dom | 7.18.1 | 7.18.7 |
| vite | 8.1.2 | 8.3.8 |
| @typescript-eslint/eslint-plugin | 8.62.1 | 8.74.0 |
| @typescript-eslint/parser | 8.62.1 | 8.74.0 |
| postcss | 8.5.16 | 8.5.33 |
| browserslist | 4.28.4 | 4.29.6 |
| js-yaml | 4.3.0 | 4.3.2 |
| nanoid | 3.3.15 | 3.3.20 |
| zod | 4.4.3 | 4.6.7 |

The lockfile refresh applies compatible npm advisory fixes. Node 22.23.5 satisfies Vite 8’s runtime requirement. The distribution build now produces minified assets and runs nginx as an unprivileged user. [Vite 8 runtime requirements](https://v8.vite.dev/guide/) [Unprivileged nginx image](https://github.com/nginx/docker-nginx-unprivileged)

## Container versions

- PostgreSQL stays on major 16 and is pinned to 16.16 for the supported minor security fixes. [PostgreSQL 16.16 release notes](https://www.postgresql.org/docs/release/16.16/)
- Python 3.12.16 and Node 22.23.5 supply the locked build/runtime. The old unbounded Torch/CUDA image install path is retired. The CPU backend uses ONNX Runtime 1.32.0 for both local speech engines.
- Trivy 0.76.2 is pinned for image vulnerability checks. [Trivy release](https://github.com/aquasecurity/trivy/releases/tag/v0.76.2)

- The packaged backend uses a digest-pinned Wolfi glibc base with Python 3.12.16-r3 and libstdc++ 16.2.0-r5. The Debian image variants reported release-blocking operating-system advisories. The Wolfi image passed the same scan and loaded the actual Canary and Piper assets as the application user. [Wolfi Python recipe](https://github.com/wolfi-dev/os/blob/main/python-3.12.yaml)
- The frontend moved from the unprivileged nginx image that pinned 1.30.6-r1 to Alpine 3.24.3 with nginx 1.30.7-r0. This applied the six outstanding nginx fixes. nginx still runs unprivileged on port 8080.
