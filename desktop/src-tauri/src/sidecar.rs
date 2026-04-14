// Sidecar supervision.
//
// Spawns the PyInstaller-frozen orchestrator binary via
// `tauri-plugin-shell`'s `externalBin` machinery, reads stdout until the
// `TESSLATE_READY {port} {bearer}` handshake line appears, and returns a
// `SidecarHandle` the rest of the host uses to talk to the loopback API.
//
// Restart-on-crash is deferred: the SidecarHandle ref ships to the frontend
// via invoke commands and a transparent port/bearer change requires either
// a Mutex<Arc<...>> wrap on the managed state plus a frontend re-fetch, or
// a hard window reload. We log exits for now; the user relaunches the app.

use std::sync::{Arc, Mutex};
use std::time::Duration;

use anyhow::{anyhow, Context, Result};
use tauri::AppHandle;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;
use tokio::sync::oneshot;
use tokio::time::timeout;

/// Name of the sidecar binary as declared in `tauri.conf.json` -> `externalBin`.
/// Tauri appends the target triple suffix automatically.
const SIDECAR_BIN: &str = "tesslate-studio-orchestrator";

/// stdout prefix printed by `desktop/sidecar/entrypoint.py` once uvicorn is
/// ready to serve requests.
const READY_PREFIX: &str = "TESSLATE_READY ";

/// Upper bound on how long we'll wait for the handshake before giving up.
/// The frozen PyInstaller --onefile bundle self-extracts on first run and
/// Python takes ~5-15s to import litellm + sqlalchemy + the orchestrator
/// package; 90s covers cold boot plus alembic upgrade head on a fresh DB.
const HANDSHAKE_TIMEOUT: Duration = Duration::from_secs(90);

#[derive(Clone)]
pub struct SidecarHandle {
    pub port: u16,
    pub bearer: String,
    /// Owning handle on the child process; `kill_on_exit()` uses it at
    /// app shutdown so we never orphan the sidecar when the host panics
    /// or the user force-quits.
    pub child: Arc<Mutex<Option<CommandChild>>>,
}

impl std::fmt::Debug for SidecarHandle {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("SidecarHandle")
            .field("port", &self.port)
            .field("bearer", &"<redacted>")
            .finish()
    }
}

impl SidecarHandle {
    pub fn api_url(&self) -> String {
        format!("http://127.0.0.1:{}", self.port)
    }
}

/// Spawn the orchestrator sidecar and block (on the current tokio runtime)
/// until its ready line arrives or the handshake timeout fires.
pub fn spawn(app: &AppHandle) -> Result<SidecarHandle> {
    let shell = app.shell();
    let command = shell
        .sidecar(SIDECAR_BIN)
        .with_context(|| format!("resolve sidecar '{SIDECAR_BIN}' from externalBin"))?;

    let (mut rx, child) = command
        .spawn()
        .with_context(|| format!("spawn sidecar '{SIDECAR_BIN}'"))?;

    let child_arc: Arc<Mutex<Option<CommandChild>>> = Arc::new(Mutex::new(Some(child)));
    let child_for_clear = Arc::clone(&child_arc);
    let (ready_tx, ready_rx) = oneshot::channel::<Result<(u16, String)>>();
    let mut ready_tx = Some(ready_tx);

    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) => {
                    let text = String::from_utf8_lossy(&line).to_string();
                    if let Some((port, bearer)) = parse_ready(&text) {
                        if let Some(tx) = ready_tx.take() {
                            let _ = tx.send(Ok((port, bearer)));
                        }
                    } else {
                        // Forward sidecar stdout so users can see boot logs.
                        eprintln!("[sidecar stdout] {}", text.trim_end());
                    }
                }
                CommandEvent::Stderr(line) => {
                    let text = String::from_utf8_lossy(&line);
                    eprintln!("[sidecar stderr] {}", text.trim_end());
                }
                CommandEvent::Error(err) => {
                    eprintln!("[sidecar error] {err}");
                    if let Some(tx) = ready_tx.take() {
                        let _ = tx.send(Err(anyhow!("sidecar error before ready: {err}")));
                    }
                }
                CommandEvent::Terminated(payload) => {
                    eprintln!(
                        "[sidecar exited] code={:?} signal={:?}",
                        payload.code, payload.signal
                    );
                    // Child is already dead; drop our handle so we don't
                    // try to kill() a stale PID at host shutdown.
                    if let Ok(mut slot) = child_for_clear.lock() {
                        slot.take();
                    }
                    if let Some(tx) = ready_tx.take() {
                        let _ = tx.send(Err(anyhow!(
                            "sidecar exited before ready (code={:?}, signal={:?})",
                            payload.code,
                            payload.signal
                        )));
                    }
                    break;
                }
                _ => {}
            }
        }
    });

    // Block the caller's runtime until the handshake lands or times out.
    let (port, bearer) = tauri::async_runtime::block_on(async move {
        match timeout(HANDSHAKE_TIMEOUT, ready_rx).await {
            Ok(Ok(Ok(pair))) => Ok(pair),
            Ok(Ok(Err(e))) => Err(e),
            Ok(Err(_)) => Err(anyhow!("sidecar ready channel closed without signal")),
            Err(_) => Err(anyhow!(
                "sidecar did not emit TESSLATE_READY within {}s",
                HANDSHAKE_TIMEOUT.as_secs()
            )),
        }
    })?;

    Ok(SidecarHandle {
        port,
        bearer,
        child: child_arc,
    })
}

/// Kill the sidecar child process. Called from the Tauri host's `RunEvent::Exit`
/// handler so the child never outlives the parent on a normal quit.
/// A no-op if the child already terminated on its own.
pub fn kill_on_exit(handle: &SidecarHandle) {
    if let Ok(mut slot) = handle.child.lock() {
        if let Some(child) = slot.take() {
            let _ = child.kill();
        }
    }
}

/// Extract the `(port, bearer)` pair from a candidate stdout line.
///
/// Returns `None` if the line is anything other than a well-formed handshake
/// so ordinary log output is ignored.
fn parse_ready(line: &str) -> Option<(u16, String)> {
    for candidate in line.lines() {
        let trimmed = candidate.trim();
        if let Some(rest) = trimmed.strip_prefix(READY_PREFIX) {
            let mut parts = rest.split_whitespace();
            let port = parts.next()?.parse::<u16>().ok()?;
            let bearer = parts.next()?.to_string();
            if bearer.is_empty() {
                return None;
            }
            return Some((port, bearer));
        }
    }
    None
}
