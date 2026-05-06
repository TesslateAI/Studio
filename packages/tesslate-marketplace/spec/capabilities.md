# Federated Marketplace Capability Matrix

Every capability listed here is implemented end-to-end in this build (no
stubs). The matrix exists so that a hub can advertise *which* capabilities it
implements via `/v1/manifest.capabilities[]`. When a capability is disabled
via the `DISABLED_CAPABILITIES` env var, the corresponding endpoint returns
`501 unsupported_capability` with the typed JSON envelope.

| Capability | Endpoint(s) | Status (default) |
|---|---|---|
| `catalog.read` | `GET /v1/items`, `GET /v1/items/{kind}/{slug}`, `…/versions`, `…/versions/{version}` | ON |
| `catalog.search` | `GET /v1/items?q=` | ON (server-side substring filter) |
| `catalog.changes` | `GET /v1/changes?since=` | ON |
| `catalog.categories` | `GET /v1/categories` | ON |
| `catalog.featured` | `GET /v1/featured` | ON |
| `bundles.signed_url` | `GET /v1/items/{kind}/{slug}/versions/{version}/bundle` | ON |
| `bundles.signed_manifests` | bundle envelope `attestation` block | ON (ed25519) |
| `publish` | `POST /v1/publish/{kind}`, `POST /v1/publish/{kind}/{slug}/versions/{version}` | ON |
| `submissions` | `GET /v1/submissions/{id}`, `POST /v1/submissions/{id}/withdraw` | ON |
| `submissions.staged` | per-stage check arrays in submission detail | ON |
| `yanks` | `POST /v1/yanks`, `GET /v1/yanks/{id}` | ON |
| `yanks.feed` | `GET /v1/yanks?since=` | ON |
| `yanks.appeals` | `POST /v1/yanks/{id}/appeal` | ON |
| `reviews.read` | `GET /v1/items/{kind}/{slug}/reviews` | ON |
| `reviews.write` | `POST /v1/items/{kind}/{slug}/reviews` | ON |
| `reviews.aggregates` | `GET /v1/items/{kind}/{slug}/reviews/aggregate` | ON |
| `pricing.read` | `GET /v1/items/{kind}/{slug}/pricing` | ON |
| `pricing.checkout` | `POST /v1/items/{kind}/{slug}/checkout` | ON (Stripe live or dev simulator) |
| `attestations` | `GET /v1/items/{kind}/{slug}/versions/{version}/attestation` | ON |
| `telemetry.opt_in` | `POST /v1/telemetry/install`, `POST /v1/telemetry/usage` | ON |
| `cross_source_ranking` | hub-supplied relevance scores | ON (no-op weights — extension hook) |

## Disable a capability

```bash
DISABLED_CAPABILITIES=pricing.checkout,telemetry.opt_in \
  uvicorn app.main:app
```

Hitting `POST /v1/items/{kind}/{slug}/checkout` will then return:

```json
HTTP/1.1 501 Not Implemented
{
  "error": "unsupported_capability",
  "capability": "pricing.checkout",
  "hub_id": "...",
  "details": "This hub does not implement pricing.checkout."
}
```

## Per-kind bundle policies

Surfaced under `/v1/manifest.policies.max_bundle_size_bytes`:

| Kind | Max bundle | Format | Required root file |
|---|---|---|---|
| `app` | 500 MB | tar.zst | `app.manifest.json` |
| `agent` | 50 MB | tar.zst | — |
| `skill`, `theme`, `workflow_template` | 10 MB | tar.zst | — |
| `mcp_server` | 1 MB | tar.zst | manifest only |
| `base` | 1 MB | tar.zst | reference manifest |
