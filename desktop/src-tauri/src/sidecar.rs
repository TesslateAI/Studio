// Sidecar supervision.
//
// Spawns the PyInstaller-frozen orchestrator binary via
// `tauri-plugin-shell`'s `externalBin` machinery, reads stdout until the
// `TESSLATE_READY {port} {bearer}` handshake line appears, and returns a
// `SidecarHandle` the rest of the host uses to talk to the loopback API.
//
// Restart-on-crash:
//   A background supervisor task watches the event stream.  When the process
//   exits unexpectedly it waits with exponential back-off (1 s → 2 s → 4 s →
//   8 s → 16 s, max 5 attempts) and re-spawns the binary with a new ephemeral
//   port + bearer.  On each successful restart it updates the shared
//   `SidecarLive` state (wrapped in `Arc<RwLock<…>>`) and emits a
//   `sidecar-restarted` Tauri event so the frontend can re-fetch
//   `get_api_url` / `get_bearer` without a full window reload.

use std::sync::{Arc, Mutex, RwLock};
use std::time::Duration;

use anyhow::{anyhow, Context, Result};
use tauri::async_runtime::Receiver;
use tauri::{AppHandle, Emitter};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;
use tokio::sync::oneshot;
use tokio::time::timeout;

/// Name of the sidecar binary as declared in `tauri.conf.json` → `externalBin`.
const SIDECAR_BIN: &str = "tesslate-studio-orchestrator";

/// stdout prefix emitted by `desktop/sidecar/entrypoint.py` once uvicorn is ready.
const READY_PREFIX: &str = "TESSLATE_READY ";

/// How long to wait for the initial handshake (covers PyInstaller self-extraction +
/// alembic upgrade-head on a cold DB).
const HANDSHAKE_TIMEOUT: Duration = Duration::from_secs(90);

/// Restart back-off delays indexed by `attempt - 1` (capped at last element).
const RESTART_DELAYS: [Duration; 5] = [
    Duration::from_secs(1),
    Duration::from_secs(2),
    Duration::from_secs(4),
    Duration::from_secs(8),
    Duration::from_secs(16),
];

/// Maximum consecutive restart attempts before giving up.
const MAX_RESTARTS: u32 = 5;

// ---------------------------------------------------------------------------
// Internal live state (mutated on each restart)
// ---------------------------------------------------------------------------

struct SidecarLive {
    port: u16,
    bearer: String,
}

// ---------------------------------------------------------------------------
// Public handle
// ---------------------------------------------------------------------------

/// Shared handle to the running sidecar.  Clone is cheap (Arc inside).
#[derive(Clone)]
pub struct SidecarHandle {
    live: Arc<RwLock<SidecarLive>>,
    /// Owning handle; `kill_on_exit` uses it at shutdown to avoid orphan PIDs.
    pub child: Arc<Mutex<Option<CommandChild>>>,
}

impl std::fmt::Debug for SidecarHandle {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let live = self.live.read().unwrap();
        let bp: String = live.bearer.chars().take(8).collect();
        f.debug_struct("SidecarHandle")
            .field("port", &live.port)
            .field("bearer", &format!("{bp}…"))
            .finish()
    }
}

impl SidecarHandle {
    pub fn api_url(&self) -> String {
        format!("http://127.0.0.1:{}", self.live.read().unwrap().port)
    }

    pub fn bearer(&self) -> String {
        self.live.read().unwrap().bearer.clone()
    }
}

// ---------------------------------------------------------------------------
// Spawn + supervise
// ---------------------------------------------------------------------------

/// Spawn the orchestrator sidecar and block until the `TESSLATE_READY` line
/// arrives or the handshake timeout fires.
///
/// A supervisor task runs in the background that restarts the sidecar if it
/// exits unexpectedly.
pub fn spawn(app: &AppHandle) -> Result<SidecarHandle> {
    let (mut rx, child) = raw_spawn(app)?;

    let live: Arc<RwLock<SidecarLive>> = Arc::new(RwLock::new(SidecarLive {
        port: 0,
        bearer: String::new(),
    }));
    let child_arc: Arc<Mutex<Option<CommandChild>>> = Arc::new(Mutex::new(Some(child)));

    let (ready_tx, ready_rx) = oneshot::channel::<Result<(u16, String)>>();
    let mut ready_tx_opt: Option<oneshot::Sender<Result<(u16, String)>>> = Some(ready_tx);

    let live_sup = Arc::clone(&live);
    let child_sup = Arc::clone(&child_arc);
    let app_sup = app.clone();

    tauri::async_runtime::spawn(async move {
        // --- Phase 1: drain initial process run + send handshake signal ---
        let should_restart = drain_until_exit(&mut rx, &mut ready_tx_opt, &child_sup).await;
        if !should_restart {
            return;
        }

        // --- Phase 2: restart loop ---
        let mut attempts: u32 = 0;
        loop {
            attempts += 1;
            if attempts > MAX_RESTARTS {
                eprintln!("[sidecar supervisor] gave up after {MAX_RESTARTS} restart attempts");
                break;
            }

            let delay =
                RESTART_DELAYS[((attempts - 1) as usize).min(RESTART_DELAYS.len() - 1)];
            eprintln!("[sidecar supervisor] restart #{attempts} in {delay:?}");
            tokio::time::sleep(delay).await;

            let (port, bearer, new_child, mut new_rx) = match respawn_wait_ready(&app_sup).await
            {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("[sidecar supervisor] restart #{attempts} failed: {e}");
                    continue;
                }
            };

            // Atomically update live state.
            {
                let mut g = live_sup.write().unwrap();
                g.port = port;
                g.bearer = bearer.clone();
            }
            {
                let mut g = child_sup.lock().unwrap();
                *g = Some(new_child);
            }

            let _ = app_sup.emit("sidecar-restarted", serde_json::json!({ "port": port }));
            eprintln!("[sidecar supervisor] restarted on port {port}");
            attempts = 0;

            // Drain the new process until it exits.
            let mut no_tx: Option<oneshot::Sender<Result<(u16, String)>>> = None;
            if !drain_until_exit(&mut new_rx, &mut no_tx, &child_sup).await {
                break; // Normal shutdown.
            }
            // Abnormal exit → loop back for another restart.
        }
    });

    // Block until the first handshake or timeout.
    let (port, bearer) = tauri::async_runtime::block_on(async move {
        match timeout(HANDSHAKE_TIMEOUT, ready_rx).await {
            Ok(Ok(Ok(pair))) => Ok(pair),
            Ok(Ok(Err(e))) => Err(e),
            Ok(Err(_)) => Err(anyhow!("ready channel closed without signal")),
            Err(_) => Err(anyhow!(
                "sidecar did not emit TESSLATE_READY within {}s",
                HANDSHAKE_TIMEOUT.as_secs()
            )),
        }
    })?;

    // Populate live state with the real port + bearer from the handshake.
    {
        let mut g = live.write().unwrap();
        g.port = port;
        g.bearer = bearer;
    }

    Ok(SidecarHandle { live, child: child_arc })
}

/// Kill the child process at host exit so we never leave an orphan.
pub fn kill_on_exit(handle: &SidecarHandle) {
    if let Ok(mut slot) = handle.child.lock() {
        if let Some(child) = slot.take() {
            let _ = child.kill();
        }
    }
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

fn raw_spawn(app: &AppHandle) -> Result<(Receiver<CommandEvent>, CommandChild)> {
    let shell = app.shell();
    let command = shell
        .sidecar(SIDECAR_BIN)
        .with_context(|| format!("resolve sidecar '{SIDECAR_BIN}'"))?;
    let (rx, child) = command
        .spawn()
        .with_context(|| format!("spawn sidecar '{SIDECAR_BIN}'"))?;
    Ok((rx, child))
}

/// Spawn a fresh sidecar and wait for its `TESSLATE_READY` handshake.
async fn respawn_wait_ready(
    app: &AppHandle,
) -> Result<(u16, String, CommandChild, Receiver<CommandEvent>)> {
    let (mut rx, child) = raw_spawn(app)?;

    let pair = timeout(HANDSHAKE_TIMEOUT, async {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) => {
                    let text = String::from_utf8_lossy(&line).to_string();
                    if let Some(pair) = parse_ready(&text) {
                        return Ok::<(u16, String), anyhow::Error>(pair);
                    }
                    eprintln!("[sidecar stdout] {}", text.trim_end());
                }
                CommandEvent::Stderr(line) => {
                    eprintln!("[sidecar stderr] {}", String::from_utf8_lossy(&line).trim_end());
                }
                CommandEvent::Error(e) => {
                    return Err(anyhow!("sidecar error before ready: {e}"));
                }
                CommandEvent::Terminated(p) => {
                    return Err(anyhow!("sidecar exited before ready (code={:?})", p.code));
                }
                _ => {}
            }
        }
        Err(anyhow!("event channel closed before TESSLATE_READY"))
    })
    .await
    .context("handshake timeout")?;

    let (port, bearer) = pair?;
    Ok((port, bearer, child, rx))
}

/// Drain events until the process terminates or the channel closes.
///
/// `ready_tx_opt`:
///   - `Some(tx)` → initial boot: fires the handshake signal on TESSLATE_READY.
///   - `None`     → restart path: no signal needed.
///
/// Returns `true` if the exit was abnormal (supervisor should restart),
/// `false` if the process was killed intentionally or the channel just closed.
async fn drain_until_exit(
    rx: &mut Receiver<CommandEvent>,
    ready_tx_opt: &mut Option<oneshot::Sender<Result<(u16, String)>>>,
    child_arc: &Arc<Mutex<Option<CommandChild>>>,
) -> bool {
    while let Some(event) = rx.recv().await {
        match event {
            CommandEvent::Stdout(line) => {
                let text = String::from_utf8_lossy(&line).to_string();
                if let Some(pair) = parse_ready(&text) {
                    if let Some(tx) = ready_tx_opt.take() {
                        let _ = tx.send(Ok(pair));
                    }
                } else {
                    eprintln!("[sidecar stdout] {}", text.trim_end());
                }
            }
            CommandEvent::Stderr(line) => {
                eprintln!("[sidecar stderr] {}", String::from_utf8_lossy(&line).trim_end());
            }
            CommandEvent::Error(e) => {
                eprintln!("[sidecar error] {e}");
                if let Some(tx) = ready_tx_opt.take() {
                    let _ = tx.send(Err(anyhow!("error: {e}")));
                }
            }
            CommandEvent::Terminated(p) => {
                eprintln!("[sidecar exited] code={:?} signal={:?}", p.code, p.signal);
                if let Ok(mut slot) = child_arc.lock() {
                    slot.take();
                }
                if let Some(tx) = ready_tx_opt.take() {
                    // Process died before the very first handshake — propagate the
                    // error to the caller and do NOT restart (boot failure).
                    let _ = tx.send(Err(anyhow!(
                        "exited before ready (code={:?})",
                        p.code
                    )));
                    return false;
                }
                let is_abnormal = p.code.map_or(true, |c| c != 0);
                return is_abnormal;
            }
            _ => {}
        }
    }
    false // Channel closed → normal shutdown.
}

/// Extract `(port, bearer)` from a candidate stdout line.
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
