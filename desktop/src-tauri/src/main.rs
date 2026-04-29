// OpenSail desktop — Tauri host entry point.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod bootstrap;
mod commands;
mod deep_link;
mod sidecar;
mod tokens;
mod tray;
mod updater;
mod window;

use std::time::Duration;

use tauri::Manager;

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_deep_link::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
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
            updater::check_in_background(handle.clone());

            if let Err(e) = tray::install(handle) {
                eprintln!("[host] tray install failed: {e}");
            }

            window::register_main_window(handle);

            // Inject the local user's JWT into the WebView so the frontend
            // can auto-authenticate without a registration / login flow.
            // Runs async so it doesn't block the setup callback.
            let app_handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                // The sidecar emits TESSLATE_READY before `import uvicorn`
                // even runs (entrypoint.py:182), so on a cold start uvicorn
                // won't actually bind for another 10-30 s while alembic /
                // SQLAlchemy / app.main warm up. Budget enough retries to
                // cover that worst case (~120 s) so auto-login is reliable.
                const ATTEMPTS: u32 = 240;
                const POLL_INTERVAL_MS: u64 = 500;

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
        .run(|app_handle, event| match &event {
            // Kill the sidecar when the host exits (any reason) so we
            // never leave an orphan holding the loopback port + SQLite
            // file. Without this, force-quit or crash leaves the child
            // parented to init(1) and the next launch fails with
            // "address already in use".
            tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit => {
                if let Some(handle) = app_handle.try_state::<sidecar::SidecarHandle>() {
                    sidecar::kill_on_exit(&handle);
                }
            }
            // macOS dock-icon click while no window is visible (close-to-tray
            // hid the window). Without this, the dock click does nothing and
            // the only re-open path is the menu-bar tray.
            #[cfg(target_os = "macos")]
            tauri::RunEvent::Reopen { has_visible_windows, .. } if !has_visible_windows => {
                window::show_main(app_handle);
            }
            _ => {}
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
