# tesslate-marketplace

Reference implementation of the **Tesslate Federated Marketplace `/v1` protocol** —
a self-hosted FastAPI service that any OpenSail orchestrator can federate with.

## What it serves

- `/v1/manifest` — hub identity, advertised capabilities, per-kind policies
- `/v1/items` — list / detail / versions / bundle / attestation
- `/v1/categories`, `/v1/featured`
- `/v1/changes`, `/v1/yanks` — incremental sync feed with tombstones
- `/v1/items/.../reviews`, `.../reviews/aggregate`
- `/v1/items/.../pricing`, `.../checkout` (Stripe Connect compatible)
- `/v1/publish/{kind}` and submission lifecycle (`stage0..stage3`)
- `/v1/yanks` + `/v1/yanks/{id}/appeal`
- `/v1/telemetry/install`, `/v1/telemetry/usage`

Every response carries `X-Tesslate-Hub-Id` and `X-Tesslate-Hub-Api-Version: v1`.
The capability matrix is advertised at `/v1/manifest.capabilities[]`; an endpoint
whose capability is disabled returns `501 unsupported_capability`.

## Run locally

```bash
cd packages/tesslate-marketplace
uv venv
source .venv/bin/activate
uv pip install -e .[dev]

# Initialize DB + load seeds + build bundles + emit changes events
DATABASE_URL="postgresql+asyncpg://tesslate_test:testpass@localhost:5433/marketplace_test" \
  python scripts/init_db.py

# Boot
DATABASE_URL="postgresql+asyncpg://tesslate_test:testpass@localhost:5433/marketplace_test" \
  uvicorn app.main:app --host 0.0.0.0 --port 8800
```

```bash
curl -s http://localhost:8800/v1/manifest | jq
curl -s 'http://localhost:8800/v1/items?kind=agent' | jq '.items | length'
curl -s 'http://localhost:8800/v1/changes?since=' | jq '.events | length'
```

## Tests

```bash
pytest -q
```

The test suite uses SQLite (`aiosqlite`) by default, so no Postgres is required for
unit tests. Set `DATABASE_URL` to override.

## Deploy

```bash
docker build -t tesslate/marketplace:latest .
docker compose up
```

The supplied `docker-compose.yml` brings up Postgres + the service on port 8800.
For local OpenSail dev, the root `docker-compose.yml` exposes a `marketplace-dev`
profile that wires this service alongside the orchestrator: `docker compose --profile marketplace-dev up`.

## Configuration

| Env var | Default | What it does |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./marketplace.db` | SQLAlchemy async URL |
| `BUNDLE_STORAGE_DIR` | `./app/bundles` | Where the local-FS CAS adapter stores bundles |
| `BUNDLE_STORAGE_BACKEND` | `local` | One of `local`, `s3`, `volume_hub` |
| `S3_BUCKET` | _unset_ | Required when `BUNDLE_STORAGE_BACKEND=s3` |
| `VOLUME_HUB_URL` | _unset_ | Required when `BUNDLE_STORAGE_BACKEND=volume_hub` |
| `BUNDLE_BASE_URL` | `http://localhost:8800` | Public URL the local-FS adapter signs into |
| `BUNDLE_URL_SECRET` | _auto-generated_ | HMAC secret for signed bundle URLs |
| `HUB_ID` | _auto-generated and persisted_ | Stable hub identity UUID |
| `HUB_ID_FILE` | `./.hub_id` | Where to persist the auto-generated `HUB_ID` |
| `HUB_DISPLAY_NAME` | `Tesslate Official` | Friendly hub name surfaced via `/v1/manifest` |
| `HUB_API_VERSION` | `v1` | Wire protocol version |
| `BUILD_REVISION` | `dev` | Surfaced via `/v1/manifest` |
| `ATTESTATION_KEY_PATH` | `./.attestation_key` | Ed25519 PEM private key (auto-generated on boot) |
| `STATIC_TOKENS` | _unset_ | `token1:scope1:scope2,token2:scope3` for local dev |
| `STRIPE_API_KEY` | _unset_ | Live Stripe key. When unset, returns dev-mode fake checkout URL |
| `STRIPE_CONNECT_ACCOUNT_ID` | _unset_ | Optional Stripe Connect account for marketplace-mode checkouts |
| `DISABLED_CAPABILITIES` | _unset_ | Comma-list of capability names to flip OFF (returns 501) |
| `OPENSAIL_ENV` | `dev` | One of `dev`, `test`, `staging`, `production` |

## Capability matrix

See [`spec/capabilities.md`](spec/capabilities.md). Every capability defaults to ON.
Disable a capability by listing it in `DISABLED_CAPABILITIES`; the corresponding
endpoints will return `501 unsupported_capability` with the typed JSON envelope.

## Promotion to a separate repo

This package currently lives inside the OpenSail monorepo at
`packages/tesslate-marketplace/`. Once the protocol stabilises and the schema
stops churning, it should be promoted to a dedicated GitHub repository
(`TesslateAI/tesslate-marketplace`) and re-vendored here as a git submodule —
mirroring the existing `packages/tesslate-agent` layout. **Do not** add a
`.gitmodules` entry until the upstream repo exists; doing so locally would break
clones for every other developer on the monorepo.

When the upstream repo is created:

```bash
git submodule add https://github.com/TesslateAI/tesslate-marketplace.git \
  packages/tesslate-marketplace
git commit -am "chore: vendor tesslate-marketplace as a submodule"
```
