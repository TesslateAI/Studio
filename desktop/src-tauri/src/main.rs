// Tesslate Studio desktop — Tauri host entry point.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod bootstrap;
mod commands;
mod deep_link;
mod sidecar;
mod tokens;
mod tray;
mod updater;

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
                &sidecar_handle.bearer.chars().take(8).collect::<String>()
            );
            app.manage(sidecar_handle);

            deep_link::register(handle);

            if let Err(e) = tray::install(handle) {
                eprintln!("[host] tray install failed: {e}");
            }

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::get_api_url,
            commands::get_bearer,
            commands::open_in_ide,
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
