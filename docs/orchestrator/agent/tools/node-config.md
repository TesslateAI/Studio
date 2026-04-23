# Node Config Tools (`node_config/`)

Two tools that let the agent build or configure Container nodes on the Architecture canvas and safely run commands with encrypted secrets.

## Tools

| Tool | File | Purpose |
|------|------|---------|
| `request_node_config` | `request_node_config.py` | Create (or edit) a Container node, open its config tab in the dock, and park the agent until the user submits. |
| `run_with_secrets` | `run_with_secrets.py` | Run a shell command with a named subset of the project's encrypted secrets injected as environment variables. Output is scrubbed before returning to the agent. |

## `request_node_config` Flow

1. Agent calls with `node_name` + `preset` (plus optional overrides).
2. Tool creates (or loads in edit mode) a `Container` row.
3. Publishes `architecture_node_added` for live canvas update.
4. Publishes `user_input_required` with the form schema. Secret fields never ship their values; edit-mode `initial_values` mark already-populated secrets with the sentinel `"__SET__"`.
5. Awaits user `submit` or `cancel` on `tesslate:pending_input`.
6. On submit, `apply_node_config` merges + encrypts via `services.deployment_encryption`, writes an `AuditLog` row, and emits `node_config_resumed` / `node_config_cancelled` / `secret_rotated` events.
7. Returns to the agent with **key names only**: no secret values.
8. Emits a heartbeat every 30s while awaiting input so the UI can show liveness.

## `run_with_secrets` Flow

1. Loads encrypted secrets for the container (`Container.encrypted_secrets`).
2. Decrypts via `services.deployment_encryption.get_deployment_encryption_service()`.
3. Runs the command with the decrypted values injected as env vars.
4. Captures stdout/stderr and passes them through `_secret_scrubber.scrub_text` before returning.

## Registration

`register_all_node_config_tools(registry)` calls `register_node_config_tool` and `register_run_with_secrets_tool`.

## Related

- `tools/approval.md`: pending-input flow shared with tool approvals.
- `services/deployment_encryption.py`: encrypt/decrypt secrets.
- `_secret_scrubber.py`: output scrubbing.
