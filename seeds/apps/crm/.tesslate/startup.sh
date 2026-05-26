#!/bin/sh
set -e

cd /app
mkdir -p data
test -d node_modules || npm install

# Resolve the Prisma engine version hash at runtime so the downloads stay
# correct across Prisma upgrades without changing this script.
EV=$(node -e "
  const v = require('@prisma/engines-version');
  console.log(v.enginesVersion || (v.default || {}).engineVersion);
" 2>/dev/null)

ENGINES=/app/node_modules/@prisma/engines
SCHEMA_ENG=${ENGINES}/schema-engine-linux-musl-openssl-3.0.x
QUERY_ENG=${ENGINES}/libquery_engine-linux-musl-openssl-3.0.x.so.node

# Alpine 3.20+ ships OpenSSL 3 only; the default Prisma engines are compiled
# against OpenSSL 1.1 and will fail with "libssl.so.1.1 not found".
# Download the openssl-3.0.x variants from the Prisma CDN if not cached.
if [ -n "$EV" ] && [ ! -f "$SCHEMA_ENG" ]; then
  wget -qO- "https://binaries.prisma.sh/all_commits/${EV}/linux-musl-openssl-3.0.x/schema-engine.gz" \
    | gunzip > "$SCHEMA_ENG"
  chmod +x "$SCHEMA_ENG"
fi

if [ -n "$EV" ] && [ ! -f "$QUERY_ENG" ]; then
  wget -qO- "https://binaries.prisma.sh/all_commits/${EV}/linux-musl-openssl-3.0.x/libquery_engine.so.node.gz" \
    | gunzip > "$QUERY_ENG"
fi

export PRISMA_SCHEMA_ENGINE_BINARY=$SCHEMA_ENG
export PRISMA_QUERY_ENGINE_LIBRARY=$QUERY_ENG
export PRISMA_ENGINES_CHECKSUM_IGNORE_MISSING=1

npx prisma db push --skip-generate --accept-data-loss
npm run dev
