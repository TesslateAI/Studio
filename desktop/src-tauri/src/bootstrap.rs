// First-run bootstrap.
//
// Intentionally a no-op: the Python sidecar calls `ensure_opensail_home`
// itself (see `orchestrator/app/services/desktop_paths.py`), so the Rust
// host has nothing to do here until we bundle additional host-side assets.
