mod commands;
mod domain;
mod error;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    .plugin(tauri_plugin_dialog::init())
    .invoke_handler(tauri::generate_handler![commands::download::download_extensions])
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
}
