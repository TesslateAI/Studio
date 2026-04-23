// Rust-side cloud token store.
//
// The paired cloud credential (`tsk_*`) flows through this module:
//
//   1. Tauri deep-link (`tesslate://auth/callback?token=...`) calls
//      `store_cloud_token()` after the cloud issues a bearer.
//   2. The Python sidecar reads it from `TESSLATE_CLOUD_TOKEN` env var
//      (highest priority in `token_store.py`) OR from the on-disk cache file
//      (`$OPENSAIL_HOME/cache/cloud_token.json`).
//
// This module mirrors the Python `token_store.py` contract:
//   - Writes are atomic (tmp-file + rename).
//   - The file is chmod'd 0600 on POSIX so other processes can't read it.
//   - On first load, if a legacy `cloud_token.json` exists it is kept in place
//     (the Python sidecar keeps reading it — no migration needed here).
//
// Future: replace the file with OS Stronghold / SecretService once
// `tauri-plugin-stronghold` v2 stabilises its Rust-side API surface.

use std::io::Write as _;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Resolve `$OPENSAIL_HOME/cache/cloud_token.json`.
/// Falls back to `{local_app_data}/Tesslate/Studio/cache/cloud_token.json`.
fn token_path() -> PathBuf {
    if let Ok(home) = std::env::var("OPENSAIL_HOME") {
        return PathBuf::from(home).join("cache").join("cloud_token.json");
    }

    // Mirrors `orchestrator/app/services/desktop_paths.py`.
    #[cfg(target_os = "macos")]
    let base = dirs_next::home_dir()
        .map(|h| h.join("Library").join("Application Support").join("Tesslate").join("Studio"))
        .unwrap_or_else(|| PathBuf::from("/tmp"));

    #[cfg(target_os = "windows")]
    let base = dirs_next::data_local_dir()
        .map(|d| d.join("Tesslate").join("Studio"))
        .unwrap_or_else(|| PathBuf::from(r"C:\Temp"));

    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    let base = dirs_next::home_dir()
        .map(|h| h.join(".local").join("share").join("tesslate-studio"))
        .unwrap_or_else(|| PathBuf::from("/tmp"));

    base.join("cache").join("cloud_token.json")
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/// Persist `token` to the cache file (atomic write, 0600 on POSIX).
/// Called after the deep-link OAuth callback delivers a `tsk_*` bearer.
pub fn store_cloud_token(token: &str) -> Result<()> {
    if token.is_empty() {
        anyhow::bail!("token must not be empty");
    }

    let path = token_path();
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)
            .with_context(|| format!("create dir {}", parent.display()))?;
    }

    write_atomic(&path, token).with_context(|| format!("write token to {}", path.display()))
}

/// Return the cloud bearer token, or `None` if not paired.
///
/// Reads `TESSLATE_CLOUD_TOKEN` env var first (Tauri can inject it on spawn),
/// then falls back to the on-disk cache file.
pub fn load_cloud_token() -> Option<String> {
    if let Ok(v) = std::env::var("TESSLATE_CLOUD_TOKEN") {
        let v = v.trim().to_string();
        if !v.is_empty() {
            return Some(v);
        }
    }

    let path = token_path();
    read_token_file(&path).ok().flatten()
}

/// Remove the on-disk token file.  No-op if it doesn't exist.
pub fn clear_cloud_token() -> Result<()> {
    let path = token_path();
    match std::fs::remove_file(&path) {
        Ok(()) => Ok(()),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(e) => Err(e).with_context(|| format!("clear token at {}", path.display())),
    }
}

/// True iff a cloud token is available.
pub fn is_paired() -> bool {
    load_cloud_token().is_some()
}

// ---------------------------------------------------------------------------
// File I/O helpers
// ---------------------------------------------------------------------------

/// Atomically write `{"token":"<value>"}` to `path` using a temp-file + rename.
/// Sets permissions to 0600 on POSIX.
fn write_atomic(path: &Path, token: &str) -> Result<()> {
    let payload = format!("{{\"token\":{}}}", serde_json::to_string(token)?);

    let parent = path.parent().unwrap_or(Path::new("."));
    let mut tmp = tempfile::NamedTempFile::new_in(parent)?;
    tmp.write_all(payload.as_bytes())?;
    tmp.flush()?;

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt as _;
        std::fs::set_permissions(tmp.path(), std::fs::Permissions::from_mode(0o600))?;
    }

    tmp.persist(path)?;
    Ok(())
}

/// Read and parse `{"token": "..."}` from a JSON file.
fn read_token_file(path: &Path) -> Result<Option<String>> {
    if !path.exists() {
        return Ok(None);
    }
    let bytes = std::fs::read(path)?;
    let value: serde_json::Value = serde_json::from_slice(&bytes)?;
    let token = value
        .get("token")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .map(String::from);
    Ok(token)
}
