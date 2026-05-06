// Window lifecycle.
//
// Close-to-tray: closing the window hides it instead of exiting the app, so the
// sidecar (and any running agents / projects) keeps working. The tray "Quit"
// item, cmd+Q on macOS, or alt+F4 routed to a real exit are the only paths
// that actually shut the host down.

use tauri::{AppHandle, Manager, WindowEvent};

const MAIN_LABEL: &str = "main";

pub fn register_main_window(app: &AppHandle) {
    let Some(window) = app.get_webview_window(MAIN_LABEL) else {
        eprintln!("[host] window::register_main_window: main window not found");
        return;
    };

    // macOS keeps native decorations so the title-bar overlay style draws
    // real traffic lights. Windows/Linux turn them off — the React TitleBar
    // renders its own chrome to keep a consistent in-app look.
    #[cfg(not(target_os = "macos"))]
    if let Err(e) = window.set_decorations(false) {
        eprintln!("[host] disable native decorations failed: {e}");
    }

    let window_for_close = window.clone();
    window.on_window_event(move |event| {
        if let WindowEvent::CloseRequested { api, .. } = event {
            api.prevent_close();
            let _ = window_for_close.hide();
        }
    });
}

pub fn show_main(app: &AppHandle) {
    if let Some(window) = app.get_webview_window(MAIN_LABEL) {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}
