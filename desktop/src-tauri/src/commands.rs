// Tauri `invoke` commands exposed to the frontend.

use tauri::{AppHandle, State};
use tauri_plugin_shell::ShellExt;

use crate::sidecar::SidecarHandle;

#[tauri::command]
pub fn get_api_url(state: State<'_, SidecarHandle>) -> String {
    state.api_url()
}

#[tauri::command]
pub fn get_bearer(state: State<'_, SidecarHandle>) -> String {
    state.bearer.clone()
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
