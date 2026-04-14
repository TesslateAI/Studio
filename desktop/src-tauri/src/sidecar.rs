// Sidecar supervision.
//
// Spawns the orchestrator binary via tauri-plugin-shell externalBin,
// parses `TESSLATE_READY {port} {bearer}` from stdout, health-checks
// `/health`, and restarts on crash with backoff.

pub struct SidecarHandle {
    pub port: u16,
    pub bearer: String,
}

impl SidecarHandle {
    pub fn api_url(&self) -> String {
        format!("http://127.0.0.1:{}", self.port)
    }
}
