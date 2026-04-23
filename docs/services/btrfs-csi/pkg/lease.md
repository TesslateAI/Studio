# pkg/lease

Shared lease types. Kept in its own package solely to break an import cycle between `pkg/sync` and `pkg/volumehub` (both need `BatchReq`, `Lease`, `Renewal`).

## File

`types.go`:

| Type | Purpose |
|------|---------|
| `BatchReq` | One entry in a batch-acquire call: `{VolumeID, Holder, TTL}`. |
| `Lease` | Active lease: `{VolumeID, Holder, ExpiresAt}`. |
| `Renewal` | Lease renewal request: `{VolumeID, Holder, TTL}`. |

## Semantics

A lease is held by a node to signal "I currently own this volume". The Hub hands out leases and tracks the owning node in its registry. The sync daemon uses leases to gate which volumes it is allowed to sync on a given node (avoids double-sync after peer transfer).
