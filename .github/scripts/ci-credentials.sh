#!/usr/bin/env bash
set -euo pipefail

postgres_password=${POSTGRES_PASSWORD:-}
session_signing_key=${SESSION_SIGNING_KEY:-}
if [[ -z "$postgres_password" ]]; then
  postgres_password=$(openssl rand -hex 32)
fi
if [[ -z "$session_signing_key" ]]; then
  session_signing_key=$(openssl rand -hex 32)
fi
if [[ ! "$postgres_password" =~ ^[0-9a-fA-F]{64}$ || ! "$session_signing_key" =~ ^[0-9a-fA-F]{64}$ || "$postgres_password" == "$session_signing_key" ]]; then
  printf '%s\n' 'Use separate 64-character hex values for the CI credentials.' >&2
  exit 1
fi
printf '::add-mask::%s\n' "$postgres_password" "$session_signing_key"
printf 'POSTGRES_PASSWORD=%s\nSESSION_SIGNING_KEY=%s\n' "$postgres_password" "$session_signing_key" >> "$GITHUB_ENV"

if [[ "${1:-}" == integration ]]; then
  database_url=$(printf 'postgresql+asyncpg://%s:%s@%s/%s' postgres "$postgres_password" 127.0.0.1:5432 grocergenie_test)
  printf '::add-mask::%s\n' "$database_url"
  printf 'DATABASE_URL=%s\nTEST_DATABASE_URL=%s\n' "$database_url" "$database_url" >> "$GITHUB_ENV"
fi
