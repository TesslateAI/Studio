// Tauri `invoke` commands exposed to the frontend.

use std::time::Duration;

use tauri::{AppHandle, State};
use tauri_plugin_shell::ShellExt;

use crate::sidecar::SidecarHandle;

#[tauri::command]
pub fn get_api_url(state: State<'_, SidecarHandle>) -> String {
    state.api_url()
}

#[tauri::command]
pub fn get_bearer(state: State<'_, SidecarHandle>) -> String {
    state.bearer()
}

/// Read the persisted cloud pairing token (if any).
///
/// Returns `None` when the desktop sidecar is not paired with a cloud account.
#[tauri::command]
pub fn get_cloud_token() -> Option<String> {
    crate::tokens::load_cloud_token()
}

/// Remove the persisted cloud pairing token (desktop unpair).
#[tauri::command]
pub fn clear_cloud_token() -> Result<(), String> {
    crate::tokens::clear_cloud_token().map_err(|e| e.to_string())
}

/// Return whether the desktop sidecar is currently paired with a cloud account.
#[tauri::command]
pub fn is_cloud_paired() -> bool {
    crate::tokens::is_paired()
}

/// Fetch a long-lived session JWT for the local desktop user.
///
/// Calls `GET /api/desktop/local-auth` on the sidecar using the
/// per-launch bearer so the frontend can auto-authenticate without a
/// registration / login flow.
#[tauri::command]
pub async fn get_user_token(state: State<'_, SidecarHandle>) -> Result<String, String> {
    let api_url = state.api_url();
    let bearer = state.bearer();

    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(15))
        .build()
        .map_err(|e| format!("client build: {e}"))?;

    let resp = client
        .get(format!("{api_url}/api/desktop/local-auth"))
        .bearer_auth(&bearer)
        .send()
        .await
        .map_err(|e| format!("request failed: {e}"))?;

    if !resp.status().is_success() {
        return Err(format!("sidecar returned {}", resp.status()));
    }

    let body: serde_json::Value = resp
        .json()
        .await
        .map_err(|e| format!("json parse: {e}"))?;

    body.get("token")
        .and_then(|v| v.as_str())
        .map(String::from)
        .ok_or_else(|| "missing token in response".to_string())
}

/// Start window drag from a mousedown event in the renderer titlebar.
#[tauri::command]
pub fn start_dragging(window: tauri::WebviewWindow) -> Result<(), String> {
    window.start_dragging().map_err(|e| e.to_string())
}

/// Minimize the main window.
#[tauri::command]
pub fn minimize_window(window: tauri::WebviewWindow) -> Result<(), String> {
    window.minimize().map_err(|e| e.to_string())
}

/// Toggle between maximized and restored state.
#[tauri::command]
pub fn toggle_maximize_window(window: tauri::WebviewWindow) -> Result<(), String> {
    if window.is_maximized().map_err(|e: tauri::Error| e.to_string())? {
        window.unmaximize().map_err(|e: tauri::Error| e.to_string())
    } else {
        window.maximize().map_err(|e: tauri::Error| e.to_string())
    }
}

/// Close the main window (hides to tray; tray.rs handles ExitRequested).
#[tauri::command]
pub fn close_window(window: tauri::WebviewWindow) -> Result<(), String> {
    window.close().map_err(|e| e.to_string())
}

/// Open a filesystem path in a user's preferred IDE.
///
/// `ide` accepts the CLI entrypoint for VS Code (`code`), Cursor (`cursor`),
/// or Zed (`zed`). When omitted or unrecognised we fall back to the
/// per-platform OS handler via `xdg-open` / `open` / `start.exe`.
#[tauri::command]
pub async fn open_in_ide(
    app: AppHandle,
    path: String,
    ide: Option<String>,
) -> Result<(), String> {
    let shell = app.shell();
    let program = match ide.as_deref() {
        Some("code") => "code",
        Some("cursor") => "cursor",
        Some("zed") => "zed",
        _ => {
            let opener = if cfg!(target_os = "macos") {
                "open"
            } else if cfg!(target_os = "windows") {
                "explorer"
            } else {
                "xdg-open"
            };
            shell
                .command(opener)
                .args([&path])
                .spawn()
                .map_err(|e| format!("spawn {opener} failed: {e}"))?;
            return Ok(());
        }
    };

    shell
        .command(program)
        .args([path])
        .spawn()
        .map_err(|e| format!("spawn {program} failed: {e}"))?;
    Ok(())
}
