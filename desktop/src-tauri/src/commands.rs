// Tauri `invoke` commands exposed to the frontend.

#[tauri::command]
pub fn get_api_url() -> String {
    // Reads from the SidecarHandle state once the supervisor is wired.
    "http://127.0.0.1:0".to_string()
}

#[tauri::command]
pub fn get_bearer() -> String {
    // Reads the per-launch bearer from SidecarHandle once wired.
    "".to_string()
}
