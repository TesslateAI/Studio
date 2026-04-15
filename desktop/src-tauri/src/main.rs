// Tesslate Studio desktop — Tauri host entry point.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod bootstrap;
mod commands;
mod deep_link;
mod sidecar;
mod tokens;
mod tray;
mod updater;

use std::time::Duration;

use tauri::Manager;

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_deep_link::init())
        // Updater plugin requires a `plugins.updater` config block (release
        // manifest URL + signing pubkey) that we don't ship yet. Wire it
        // back when the release pipeline + signing keys exist.
        .setup(|app| {
            let handle = app.handle();

            let sidecar_handle = match sidecar::spawn(handle) {
                Ok(h) => h,
                Err(e) => {
                    // No sidecar means no API — fail loud rather than ship a
                    // dead window.
                    panic!("failed to start orchestrator sidecar: {e:?}");
                }
            };
            eprintln!(
                "[host] sidecar ready on {} (bearer {}...)",
                sidecar_handle.api_url(),
                &sidecar_handle.bearer().chars().take(8).collect::<String>()
            );
            app.manage(sidecar_handle.clone());

            deep_link::register(handle);

            if let Err(e) = tray::install(handle) {
                eprintln!("[host] tray install failed: {e}");
            }

            // Inject the local user's JWT into the WebView so the frontend
            // can auto-authenticate without a registration / login flow.
            // Runs async so it doesn't block the setup callback.
            let app_handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                // The sidecar emits TESSLATE_READY before uvicorn is fully
                // accepting connections.  Poll at a fixed 300 ms interval
                // until local-auth responds (max ~15 s total).
                const ATTEMPTS: u32 = 50;
                const POLL_INTERVAL_MS: u64 = 300;

                let mut token: Option<String> = None;
                for attempt in 1..=ATTEMPTS {
                    tokio::time::sleep(Duration::from_millis(POLL_INTERVAL_MS)).await;

                    token = fetch_local_user_token(&sidecar_handle).await;
                    if token.is_some() {
                        break;
                    }
                    eprintln!("[host] local-auth attempt {attempt}/{ATTEMPTS} not ready yet, retrying…");
                }

                match token {
                    Some(t) => inject_desktop_token(&app_handle, &t),
                    None => eprintln!(
                        "[host] could not obtain local user token after {ATTEMPTS} attempts — manual login required"
                    ),
                }
            });

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::get_api_url,
            commands::get_bearer,
            commands::get_user_token,
            commands::get_cloud_token,
            commands::clear_cloud_token,
            commands::is_cloud_paired,
            commands::open_in_ide,
            commands::start_dragging,
            commands::minimize_window,
            commands::toggle_maximize_window,
            commands::close_window,
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            // Kill the sidecar when the host exits (any reason) so we
            // never leave an orphan holding the loopback port + SQLite
            // file. Without this, force-quit or crash leaves the child
            // parented to init(1) and the next launch fails with
            // "address already in use".
            if let tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit = event {
                if let Some(handle) = app_handle.try_state::<sidecar::SidecarHandle>() {
                    sidecar::kill_on_exit(&handle);
                }
            }
        });
}

// ---------------------------------------------------------------------------
// Desktop auto-login helpers
// ---------------------------------------------------------------------------

/// Fetch the local user JWT from the sidecar's `/api/desktop/local-auth`.
/// Returns `None` if the server is not yet ready or returns an error.
async fn fetch_local_user_token(handle: &sidecar::SidecarHandle) -> Option<String> {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(5))
        .build()
        .ok()?;

    let url = format!("{}/api/desktop/local-auth", handle.api_url());
    let resp = match client.get(&url).bearer_auth(handle.bearer()).send().await {
        Ok(r) => r,
        Err(e) => {
            // Connection refused — server not ready yet; caller will retry.
            eprintln!("[host] local-auth connect: {e}");
            return None;
        }
    };

    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        eprintln!("[host] local-auth {status}: {body}");
        return None;
    }

    let body: serde_json::Value = match resp.json().await {
        Ok(v) => v,
        Err(e) => {
            eprintln!("[host] local-auth json parse: {e}");
            return None;
        }
    };
    body.get("token")
        .and_then(|v| v.as_str())
        .map(String::from)
}

/// Inject the JWT into the main WebView via JS eval.
///
/// Sets `window.__TESSLATE_DESKTOP_TOKEN__` and dispatches
/// `tesslate-desktop-token-ready` so `AuthContext.tsx` picks it up
/// regardless of whether React mounted before or after this runs.
fn inject_desktop_token(app: &tauri::AppHandle, token: &str) {
    let Some(window) = app.get_webview_window("main") else {
        eprintln!("[host] main window not found — cannot inject desktop token");
        return;
    };
    // Escape the token for safe JS string literal embedding.
    let escaped = token.replace('\\', "\\\\").replace('\'', "\\'");
    let js = format!(
        "window.__TESSLATE_DESKTOP_TOKEN__ = '{escaped}'; \
         window.dispatchEvent(new Event('tesslate-desktop-token-ready'));"
    );
    if let Err(e) = window.eval(&js) {
        eprintln!("[host] failed to inject desktop token: {e}");
    }
}
