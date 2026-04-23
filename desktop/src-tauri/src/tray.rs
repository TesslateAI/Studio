// System tray.
//
// Menu: "Open Studio" shows + focuses the main window, "Quit" exits.
// Tooltip is refreshed every 5s with live counts pulled from
// `/api/desktop/tray-state` so users can see "Studio · 2 agents · 1 project"
// without opening the window.

use std::time::Duration;

use serde::Deserialize;
use tauri::{
    menu::{MenuBuilder, MenuItemBuilder},
    tray::{TrayIcon, TrayIconBuilder},
    AppHandle, Manager,
};

use crate::sidecar::SidecarHandle;

const MENU_OPEN: &str = "open_studio";
const MENU_QUIT: &str = "quit";
const TRAY_ID: &str = "tesslate-studio";
const POLL_INTERVAL: Duration = Duration::from_secs(5);

pub fn install(app: &AppHandle) -> tauri::Result<()> {
    let open_item = MenuItemBuilder::with_id(MENU_OPEN, "Open Studio").build(app)?;
    let quit_item = MenuItemBuilder::with_id(MENU_QUIT, "Quit").build(app)?;
    let menu = MenuBuilder::new(app)
        .items(&[&open_item, &quit_item])
        .build()?;

    let icon = app.default_window_icon().cloned().ok_or_else(|| {
        tauri::Error::AssetNotFound("default window icon missing from bundle".into())
    })?;

    let _tray = TrayIconBuilder::with_id(TRAY_ID)
        .tooltip("OpenSail")
        .icon(icon)
        .menu(&menu)
        .on_menu_event(|app, event| match event.id().as_ref() {
            MENU_OPEN => {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.show();
                    let _ = window.unminimize();
                    let _ = window.set_focus();
                }
            }
            MENU_QUIT => {
                app.exit(0);
            }
            _ => {}
        })
        .build(app)?;

    spawn_tooltip_poll(app.clone());
    Ok(())
}

#[derive(Deserialize)]
struct TrayState {
    #[serde(default)]
    running_projects: Vec<serde_json::Value>,
    #[serde(default)]
    running_agents: Vec<serde_json::Value>,
}

fn spawn_tooltip_poll(app: AppHandle) {
    tauri::async_runtime::spawn(async move {
        let client = match reqwest::Client::builder()
            .timeout(Duration::from_secs(3))
            .build()
        {
            Ok(c) => c,
            Err(e) => {
                eprintln!("[tray] reqwest client build failed: {e}");
                return;
            }
        };
        loop {
            tokio::time::sleep(POLL_INTERVAL).await;
            let Some(state) = app.try_state::<SidecarHandle>() else {
                continue;
            };
            let url = format!("{}/api/desktop/tray-state", state.api_url());
            let bearer = format!("Bearer {}", state.bearer());
            let resp = client.get(&url).header("Authorization", &bearer).send().await;
            let payload: TrayState = match resp {
                Ok(r) if r.status().is_success() => match r.json().await {
                    Ok(v) => v,
                    Err(_) => continue,
                },
                _ => continue,
            };
            let tooltip = format_tooltip(payload.running_agents.len(), payload.running_projects.len());
            if let Some(tray) = app.tray_by_id(TRAY_ID) {
                let _: tauri::Result<()> = set_tooltip(&tray, &tooltip);
            }
        }
    });
}

fn set_tooltip(tray: &TrayIcon, text: &str) -> tauri::Result<()> {
    tray.set_tooltip(Some(text))?;
    Ok(())
}

fn format_tooltip(agents: usize, projects: usize) -> String {
    match (agents, projects) {
        (0, 0) => "OpenSail".to_string(),
        (a, 0) => format!("OpenSail · {a} agent{}", plural(a)),
        (0, p) => format!("OpenSail · {p} project{}", plural(p)),
        (a, p) => format!(
            "OpenSail · {a} agent{} · {p} project{}",
            plural(a),
            plural(p)
        ),
    }
}

fn plural(n: usize) -> &'static str {
    if n == 1 { "" } else { "s" }
}
