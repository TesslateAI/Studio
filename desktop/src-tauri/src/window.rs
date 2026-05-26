// Window lifecycle.
//
// Close-to-tray: closing the window hides it instead of exiting the app, so the
// sidecar (and any running agents / projects) keeps working. The tray "Quit"
// item, cmd+Q on macOS, or alt+F4 routed to a real exit are the only paths
// that actually shut the host down.

use tauri::{AppHandle, Manager, WebviewUrl, WebviewWindowBuilder, WindowEvent};

const MAIN_LABEL: &str = "main";

/// Programmatically create the main window so we can attach an
/// `initialization_script` that injects `window._env_.API_URL` BEFORE the
/// bundled React app runs `config.ts`.
///
/// Without this, the frontend tries to load `/config.js` (which exists only in
/// the nginx-rendered cloud build), fails, and falls back to `http://localhost:8000`
/// — but the desktop sidecar binds to an ephemeral 127.0.0.1 port, so every
/// API request would go to nothing and the user lands on the cloud login page.
pub fn create_main_window(app: &AppHandle, sidecar_api_url: &str) -> tauri::Result<()> {
    // Escape the URL for safe embedding in a single-quoted JS string literal.
    // The sidecar emits a `http://127.0.0.1:<port>` URL, so no real special
    // characters are expected, but we defensively escape backslashes + quotes.
    let escaped_url = sidecar_api_url.replace('\\', "\\\\").replace('\'', "\\'");
    let init_script = format!(
        "window._env_ = {{ \
            API_URL: '{escaped_url}', \
            POSTHOG_KEY: '', \
            POSTHOG_HOST: '' \
        }};"
    );

    let mut builder = WebviewWindowBuilder::new(app, MAIN_LABEL, WebviewUrl::App("index.html".into()))
        .title("OpenSail")
        .inner_size(1440.0, 900.0)
        .min_inner_size(960.0, 600.0)
        .initialization_script(&init_script);

    // macOS-only title-bar tweaks (overlay style + custom traffic-light position
    // + hidden native title) — match the previous tauri.conf.json values.
    #[cfg(target_os = "macos")]
    {
        use tauri::{utils::TitleBarStyle, LogicalPosition};
        builder = builder
            .title_bar_style(TitleBarStyle::Overlay)
            .hidden_title(true)
            .traffic_light_position(LogicalPosition::new(20.0, 20.0));
    }

    let window = builder.build()?;

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

    Ok(())
}

pub fn show_main(app: &AppHandle) {
    if let Some(window) = app.get_webview_window(MAIN_LABEL) {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}
