// Deep-link handler for `tesslate://auth/callback?token=...`.
//
// Listens for `tauri-plugin-deep-link` events, extracts the `token` query
// parameter, and forwards it to the sidecar's `POST /api/desktop/auth/token`
// endpoint using the per-launch bearer from `SidecarHandle`. Failures are
// logged but not retried — the user can re-trigger the pairing flow.

use tauri::{AppHandle, Manager};
use tauri_plugin_deep_link::DeepLinkExt;
use url::Url;

use crate::sidecar::SidecarHandle;
use crate::tokens;

/// Register the deep-link listener. Call once after `SidecarHandle` is
/// managed on the app.
pub fn register(app: &AppHandle) {
    let handle = app.clone();
    app.deep_link().on_open_url(move |event| {
        for url in event.urls() {
            if let Some(token) = extract_auth_token(&url) {
                dispatch_token(&handle, token);
            }
        }
    });
}

/// Pull a `?token=...` value off a `tesslate://auth/callback` URL.
fn extract_auth_token(url: &Url) -> Option<String> {
    if url.scheme() != "tesslate" {
        return None;
    }
    // Both `tesslate://auth/callback?token=...` and any nested host/path
    // variant the cloud may choose should work — we only care about the
    // query pair.
    let host = url.host_str().unwrap_or("");
    let path = url.path();
    let is_auth_callback = matches!(
        (host, path),
        ("auth", "/callback") | ("auth", "/callback/") | ("", "/auth/callback")
    ) || path.ends_with("/auth/callback");

    if !is_auth_callback {
        return None;
    }

    url.query_pairs()
        .find(|(k, _)| k == "token")
        .map(|(_, v)| v.to_string())
        .filter(|t| !t.is_empty())
}

fn dispatch_token(app: &AppHandle, token: String) {
    // Persist the cloud token on the Rust side (file-backed cache) so it
    // survives sidecar restarts even before the sidecar processes the POST.
    if let Err(e) = tokens::store_cloud_token(&token) {
        eprintln!("[deep-link] failed to persist cloud token locally: {e}");
    }

    let Some(handle) = app.try_state::<SidecarHandle>() else {
        eprintln!("[deep-link] dropped auth token to sidecar: sidecar not ready yet");
        return;
    };
    let api_url = handle.api_url();
    let bearer = handle.bearer();

    tauri::async_runtime::spawn(async move {
        let client = match reqwest::Client::builder().build() {
            Ok(c) => c,
            Err(e) => {
                eprintln!("[deep-link] reqwest client build failed: {e}");
                return;
            }
        };

        let endpoint = format!("{api_url}/api/desktop/auth/token");
        let result = client
            .post(&endpoint)
            .bearer_auth(&bearer)
            .json(&serde_json::json!({ "token": token }))
            .send()
            .await;

        match result {
            Ok(resp) if resp.status().is_success() => {
                log::info!("deep-link token delivered to sidecar");
            }
            Ok(resp) => {
                eprintln!(
                    "[deep-link] sidecar rejected token: {} {}",
                    resp.status(),
                    resp.text().await.unwrap_or_default()
                );
            }
            Err(err) => {
                eprintln!("[deep-link] failed to POST token: {err}");
            }
        }
    });
}
