use tauri::AppHandle;
use tauri_plugin_updater::UpdaterExt;

/// Spawn a background task that checks for an update and, if one is available,
/// prompts the user with a native dialog before downloading and installing.
///
/// Non-blocking: errors are logged and silently swallowed so a broken updater
/// endpoint never prevents the app from starting.
pub fn check_in_background(app: AppHandle) {
    tauri::async_runtime::spawn(async move {
        if let Err(e) = check_and_prompt(app).await {
            eprintln!("[updater] check failed (non-fatal): {e}");
        }
    });
}

async fn check_and_prompt(app: AppHandle) -> anyhow::Result<()> {
    let updater = app.updater()?;

    let Some(update) = updater.check().await? else {
        eprintln!("[updater] no update available");
        return Ok(());
    };

    eprintln!(
        "[updater] update available: {} → {}",
        update.current_version,
        update.version
    );

    // Ask the user before downloading.
    let body = update.body.as_deref().unwrap_or("No release notes.");
    let message = format!(
        "OpenSail {} is available.\n\n{}\n\nInstall now? The app will restart automatically.",
        update.version, body
    );

    let confirmed = tauri::async_runtime::spawn_blocking({
        let app = app.clone();
        move || {
            use tauri_plugin_dialog::{DialogExt, MessageDialogButtons};
            app.dialog()
                .message(message)
                .title("Update Available")
                .buttons(MessageDialogButtons::OkCancelCustom(
                    "Install".into(),
                    "Later".into(),
                ))
                .blocking_show()
        }
    })
    .await
    .unwrap_or(false);

    if !confirmed {
        eprintln!("[updater] user deferred update");
        return Ok(());
    }

    eprintln!("[updater] downloading and installing…");
    update
        .download_and_install(
            |downloaded, total| {
                if let Some(total) = total {
                    eprintln!("[updater] progress: {downloaded}/{total} bytes");
                }
            },
            || eprintln!("[updater] download complete, installing"),
        )
        .await?;

    // Tauri will restart automatically after install on supported platforms.
    Ok(())
}
