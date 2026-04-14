// Tesslate Studio desktop — Tauri host entry point.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod bootstrap;
mod commands;
mod deep_link;
mod sidecar;
mod tokens;
mod tray;
mod updater;

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_deep_link::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .invoke_handler(tauri::generate_handler![
            commands::get_api_url,
            commands::get_bearer,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
