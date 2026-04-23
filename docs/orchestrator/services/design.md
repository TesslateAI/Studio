# Design Services

**Directory**: `orchestrator/app/services/design/`

Design view support: async gRPC client for the standalone `tesslate-ast` service plus a per-process circuit breaker.

The `tesslate-ast` service parses source files into an OID-indexed AST so the frontend design panel can map DOM clicks to source locations and apply code diffs.

## When to load

Load this doc when:
- Debugging design-view "Inspect Element" or code-edit-from-canvas failures.
- Adding a new AST operation (parse, resolve OID, apply patch).
- Tuning AST service circuit-breaker thresholds.

## File map

| File | Purpose |
|------|---------|
| `__init__.py` | Package docstring: "Design view services: AST worker, OID indexing, code-diff application." |
| `ast_client.py` | Async gRPC client for `tesslate-ast`. Uses JSON codec (matching `fileops_client`, `hub_client`). Cluster-internal traffic only. |
| `circuit_breaker.py` | Per-process circuit breaker for `ast_client`. State machine: `CLOSED -> (N failures) -> OPEN -> (T seconds elapsed) -> HALF_OPEN -> success -> CLOSED`. |

## Callers

| Caller | Service(s) used |
|--------|-----------------|
| `routers/design.py` | `ast_client`, `circuit_breaker` |
| Agent design tools (code lens, click-to-edit) | `ast_client` |

## Related

- `services/fileops_client.py` and `services/hub_client.py` use the same JSON-over-gRPC codec convention.
