fn main() {
  tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
    tauri_build::AppManifest::new().commands(&["open_artifact", "reveal_artifact", "download_artifact"]),
  )).expect("failed to build application permissions")
}
