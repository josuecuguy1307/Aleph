// Aleph · Casa 2 · Fase 4 · 4.4.0 — el shell Tauri (envoltorio, no conversión).
//
// Modelo: el backend Python CONGELADO (PyInstaller, `aleph_sidecar`) es el SIDECAR y
// sirve TODO (serving=C: Home + Capa 0 + /v1) en 127.0.0.1:<port>. Este shell:
//   1. elige el puerto ESTABLE (rango determinístico — ver PORT_RANGE; el origen WebKit
//      debe repetirse entre launches o el storage/sesión se pierde en cada arranque),
//   2. limpia best-effort las particiones WebKit huérfanas de puertos viejos,
//   3. spawnea el sidecar en ese puerto,
//   4. muestra un splash mientras el backend arranca,
//   5. navega la webview a http://127.0.0.1:<port>/ cuando el puerto responde,
//   6. mata el sidecar al salir (sin huérfanos).
//
// El binario del sidecar se resuelve por env ALEPH_SIDECAR_BIN (contrato de dev/4.4.0).
// El empaquetado como externalBin dentro del .app (resource path) es 4.4.2.

use std::fs::{copy, create_dir_all, metadata, rename, File, OpenOptions};
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::os::fd::AsRawFd;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::sync::atomic::{AtomicU16, Ordering};
use std::time::{Duration, Instant};

use tauri::Manager;

#[tauri::command]
fn choose_cli_executable(window: tauri::WebviewWindow) -> Result<Option<String>, String> {
    if window.label() != "main" {
        return Err("invalid window".into());
    }
    #[cfg(target_os = "macos")]
    {
        let output = Command::new("/usr/bin/osascript")
            .args(["-e", "POSIX path of (choose file with prompt \"Choose a CLI executable\")"])
            .output()
            .map_err(|_| "file chooser unavailable".to_string())?;
        if !output.status.success() {
            return Ok(None);
        }
        let selected = String::from_utf8(output.stdout)
            .map_err(|_| "invalid selected path".to_string())?
            .trim()
            .to_string();
        return if selected.is_empty() { Ok(None) } else { Ok(Some(selected)) };
    }
    #[cfg(not(target_os = "macos"))]
    {
        Err("file chooser unavailable on this platform".into())
    }
}

// Read the existing UI preference, never create a native locale preference.
// Only the main sidecar origin is eligible: no iframe, auth or foreign storage.
static UI_PORT: AtomicU16 = AtomicU16::new(8330);

fn decode_ui_lang_hex(value: &str) -> Option<&'static str> {
    match value.trim() {
        "65006E00" | "656E" => Some("en"),
        "65007300" | "6573" => Some("es"),
        _ => None,
    }
}

fn read_ui_lang(default_dir: &Path, port: u16) -> &'static str {
    let Ok(parts) = std::fs::read_dir(default_dir) else { return "es"; };
    for part in parts.flatten() {
        let Ok(subs) = std::fs::read_dir(part.path()) else { continue; };
        for sub in subs.flatten() {
            let root = sub.path();
            let Ok(origin) = std::fs::read(root.join("origin")) else { continue; };
            let ports = loopback_ports(&origin);
            if !origin.starts_with(b"\x04\0\0\0\x01http") || ports.len() != 2 || !ports.iter().all(|p| *p == Some(port)) {
                continue;
            }
            let db = root.join("LocalStorage/localstorage.sqlite3");
            if !db.is_file() { continue; }
            // Exact key only; read-only SQLite with a bounded lock timeout.
            let result = Command::new("/usr/bin/sqlite3")
                .arg("-readonly").arg("-cmd").arg(".timeout 500").arg(db)
                .arg("SELECT hex(value) FROM ItemTable WHERE key = 'aleph-lang';")
                .output();
            if let Ok(output) = result {
                if output.status.success() {
                    if let Some(lang) = decode_ui_lang_hex(&String::from_utf8_lossy(&output.stdout)) {
                        return lang;
                    }
                }
            }
        }
    }
    "es" // same default as AlephI18n, not the OS locale or a model instruction
}

fn native_ui_lang(port: u16) -> &'static str {
    if !cfg!(target_os = "macos") { return "es"; }
    let Ok(app_home) = std::env::var("HOME") else { return "es"; };
    read_ui_lang(&Path::new(&app_home).join("Library/WebKit/app.aleph.desktop/WebsiteData/Default"), port)
}

fn ui_copy(es: &str, en: &str) -> String {
    if native_ui_lang(UI_PORT.load(Ordering::Relaxed)) == "en" { en.into() } else { es.into() }
}

fn splash_script(lang: &str, launch_cap: &str, sidecar_port: u16) -> String {
    let (lang, title, detail) = if lang == "en" {
        ("en", "Starting Aleph…", "Starting the local backend")
    } else {
        ("es", "Iniciando Aleph…", "Iniciando el backend local")
    };
    let cap = serde_json::to_string(launch_cap).unwrap_or_else(|_| "\"\"".into());
    format!("(()=>{{const own=location.protocol==='http:'&&location.hostname==='127.0.0.1'&&location.port==='{sidecar_port}';if(own)Object.defineProperty(window,'__ALEPH_LAUNCH_CAP__',{{value:{cap},writable:false,configurable:false}});const apply=()=>{{if(location.protocol!=='tauri:')return;document.documentElement.lang='{lang}';const t=document.getElementById('startup-title');if(t)t.textContent='{title}';const d=document.getElementById('startup-detail');if(d)d.textContent='{detail}';}};if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',apply,{{once:true}});else apply();}})();")
}

#[cfg(test)]
mod linguistic_tests {
    use super::*;

    #[test]
    fn preference_accepts_only_existing_es_en_values() {
        assert_eq!(decode_ui_lang_hex("65006E00\n"), Some("en"));
        assert_eq!(decode_ui_lang_hex("65007300"), Some("es"));
        assert_eq!(decode_ui_lang_hex("656E"), Some("en"));
        assert_eq!(decode_ui_lang_hex("6573"), Some("es"));
        assert_eq!(decode_ui_lang_hex("00"), None);
    }

    #[test]
    fn splash_changes_only_tauri_origin_without_another_preference() {
        assert!(splash_script("en", "cap-test", 8080).contains("Starting the local backend"));
        assert!(splash_script("es", "cap-test", 8080).contains("Iniciando el backend local"));
        assert!(splash_script("unsupported", "cap-test", 8080).contains("lang='es'"));
        assert!(splash_script("en", "cap-test", 8080).contains("location.protocol!=='tauri:'"));
        assert!(splash_script("en", "cap-test", 8080).contains("location.port==='8080'"));
        assert!(splash_script("en", "cap-test", 8080).contains("if(own)Object.defineProperty"));
        assert!(splash_script("en", "cap-test", 8080).contains("__ALEPH_LAUNCH_CAP__"));
        assert!(!splash_script("en", "cap-test", 8080).contains("localStorage.setItem"));
    }

    #[test]
    fn readonly_ui_key_uses_exact_main_origin_not_iframe_or_foreign_scheme() {
        let serial = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos();
        let fixture = std::env::temp_dir().join(format!("aleph-ui-lang-test-{}-{serial}", std::process::id()));
        let root = fixture.join("part/part");
        std::fs::create_dir_all(root.join("LocalStorage")).unwrap();
        fn record(scheme: &[u8], port: u16) -> Vec<u8> {
            let mut bytes = Vec::new();
            bytes.extend_from_slice(&(scheme.len() as u32).to_le_bytes());
            bytes.push(1); bytes.extend_from_slice(scheme);
            bytes.extend_from_slice(&9u32.to_le_bytes()); bytes.push(1);
            bytes.extend_from_slice(b"127.0.0.1"); bytes.push(1);
            bytes.extend_from_slice(&port.to_le_bytes()); bytes
        }
        let main = record(b"http",8330);
        let origin = [main.clone(),main.clone()].concat();
        std::fs::write(root.join("origin"), &origin).unwrap();
        let db = root.join("LocalStorage/localstorage.sqlite3");
        assert!(Command::new("/usr/bin/sqlite3").arg(&db).arg("CREATE TABLE ItemTable(key TEXT, value BLOB); INSERT INTO ItemTable VALUES('aleph-lang', X'65006E00');").status().unwrap().success());
        let before = std::fs::read(&db).unwrap();
        assert_eq!(read_ui_lang(&fixture,8330),"en");
        assert_eq!(std::fs::read(&db).unwrap(),before,"preference is read-only");
        assert_eq!(read_ui_lang(&fixture,8331),"es");
        std::fs::write(root.join("origin"),[main,record(b"http",4096)].concat()).unwrap();
        assert_eq!(read_ui_lang(&fixture,8330),"es");
        let foreign = record(b"https",8330);
        std::fs::write(root.join("origin"),[foreign.clone(),foreign].concat()).unwrap();
        assert_eq!(read_ui_lang(&fixture,8330),"es");
        std::fs::remove_dir_all(fixture).unwrap();
    }
}

/// Directorio de artefactos que Aleph está autorizado a exponer al sistema.
/// Nunca aceptamos paths arbitrarios desde el contenido web cargado en la webview.
fn artifact_root() -> Result<PathBuf, String> {
    let home = std::env::var_os("HOME").ok_or_else(|| ui_copy("No se encontró el directorio de usuario", "User directory not found"))?;
    Ok(PathBuf::from(home).join("Library/Application Support/Aleph/workspaces"))
}

fn checked_artifact(path: &str) -> Result<PathBuf, String> {
    let root = artifact_root()?.canonicalize().map_err(|_| ui_copy("No se encontró el directorio de artefactos de Aleph", "Aleph artifact directory not found"))?;
    let candidate = Path::new(path).canonicalize().map_err(|_| ui_copy("El archivo ya no existe", "The file no longer exists"))?;
    if !candidate.starts_with(&root) || !candidate.is_file() {
        return Err(ui_copy("Aleph sólo puede abrir archivos de sus espacios de trabajo", "Aleph can only open files from its workspaces"));
    }
    Ok(candidate)
}

fn downloads_copy(source: &Path) -> Result<PathBuf, String> {
    let home = std::env::var_os("HOME").ok_or_else(|| ui_copy("No se encontró el directorio de usuario", "User directory not found"))?;
    let downloads = PathBuf::from(home).join("Downloads");
    create_dir_all(&downloads).map_err(|e| format!("{}: {e}", ui_copy("No se pudo preparar Descargas", "Could not prepare Downloads")))?;
    let name = source.file_name().and_then(|v| v.to_str()).ok_or_else(|| ui_copy("Nombre de archivo inválido", "Invalid filename"))?;
    let destination = available_download_path(&downloads, name);
    copy(source, &destination).map_err(|e| format!("{}: {e}", ui_copy("No se pudo copiar el archivo a Descargas", "Could not copy the file to Downloads")))?;
    Ok(destination)
}

/// No sobrescribir una descarga anterior del usuario; Finder/Chrome aplican la misma
/// convención de sufijo numérico cuando el nombre ya existe.
fn available_download_path(downloads: &Path, filename: &str) -> PathBuf {
    let original = Path::new(filename);
    let stem = original.file_stem().and_then(|v| v.to_str()).unwrap_or("archivo");
    let extension = original.extension().and_then(|v| v.to_str()).map(|v| format!(".{v}")).unwrap_or_default();
    let mut candidate = downloads.join(filename);
    let mut index = 1usize;
    while candidate.exists() {
        candidate = downloads.join(format!("{stem} ({index}){extension}"));
        index += 1;
    }
    candidate
}

/// ── LA DESCARGA DEL WEBVIEW, ATENDIDA ─────────────────────────────────────────────────
///
/// EL DEFECTO QUE ESTO CIERRA, medido el 2026-08-28 en los seis espacios. Cinco de los seis
/// stacks descargan con el patrón estándar de la web —`URL.createObjectURL` + un `<a
/// download>` al que se le hace `click()`—: Ciencia en 9 archivos, Educación en 6, Finanzas
/// en 2, Legal en 3. Adentro de un WKWebView eso NO baja nada si la app no atiende el
/// evento, y esta cáscara no lo atendía: el usuario tocaba «descargar» y no pasaba nada, sin
/// un solo error. Por eso Oficina había tenido que rodearlo a mano con `download_artifact`
/// (`ee1a540e`) — no era un capricho, era la única salida que había.
///
/// POR QUÉ ACÁ Y NO EN CADA STACK: es UN lugar contra CINCO integraciones en cinco códigos
/// ajenos, que además habría que rehacer en cada actualización de cada uno. Y cubre al que
/// venga después sin tocarlo.
///
/// QUÉ HACE: deja el nombre que propuso el webview y sólo cambia el DESTINO a `~/Descargas`,
/// con el mismo sufijo numérico que ya usa `download_artifact` para no pisar una descarga
/// anterior. Devolver `true` es lo que autoriza la bajada; devolver `false` la cancela.
/// ¿Esta URL es de la casa —y entonces se navega adentro— o es de afuera?
///
/// El criterio es el ORIGEN, no el esquema: el sidecar vive en 127.0.0.1, cada pack en su
/// puerto local, y `tauri://`/`about:`/`blob:`/`data:` son de la propia webview. Todo lo
/// demás es internet y va al navegador del sistema.
fn es_de_la_casa(url: &tauri::Url) -> bool {
    // Lo que es de la propia webview, sin host que mirar.
    if matches!(url.scheme(), "tauri" | "about" | "blob" | "data") {
        return true;
    }
    // ⚠️ TODO LO DEMÁS QUE NO SEA WEB ES DE AFUERA. Esta línea la puso una prueba que
    // falló: `mailto:` no tiene host, y una guarda de «host vacío ⇒ es la casa» lo daba
    // por local. El resultado habría sido navegar la ventana de Aleph a un `mailto:` en
    // vez de abrir el cliente de correo.
    if !matches!(url.scheme(), "http" | "https") {
        return false;
    }
    // Y acá el host se compara ENTERO: `127.0.0.1.evil.com` empieza igual y no es la casa.
    let host = url.host_str().unwrap_or("");
    host == "127.0.0.1" || host == "localhost" || host == "::1" || host == "[::1]"
}

#[cfg(test)]
mod pruebas_links {
    use super::es_de_la_casa;

    fn u(s: &str) -> tauri::Url {
        tauri::Url::parse(s).expect("url de prueba")
    }

    #[test]
    fn lo_local_se_navega_adentro() {
        // El sidecar y los packs: la casa.
        assert!(es_de_la_casa(&u("http://127.0.0.1:8330/workspaces/ciencia.html")));
        assert!(es_de_la_casa(&u("http://127.0.0.1:58568/global/health")));
        assert!(es_de_la_casa(&u("http://localhost:4096/")));
        // Y lo que es de la propia webview.
        assert!(es_de_la_casa(&u("about:blank")));
        assert!(es_de_la_casa(&u("data:text/html,<p>hola")));
    }

    #[test]
    fn internet_se_va_al_navegador() {
        // El caso que lo destapó: Ciencia devolvió papers de openalex y no se abría ninguno.
        assert!(!es_de_la_casa(&u("https://openalex.org/W2903401602")));
        assert!(!es_de_la_casa(&u("https://arxiv.org/abs/2401.00001")));
        assert!(!es_de_la_casa(&u("http://example.com/")));
        assert!(!es_de_la_casa(&u("mailto:alguien@ejemplo.com")));
    }

    #[test]
    fn un_host_que_EMPIEZA_igual_no_es_la_casa() {
        // `127.0.0.1.evil.com` y `localhost.attacker.net` contienen el nombre de la casa
        // pero NO son la casa: se compara el host entero, no un prefijo.
        assert!(!es_de_la_casa(&u("http://127.0.0.1.evil.com/")));
        assert!(!es_de_la_casa(&u("https://localhost.attacker.net/")));
    }
}

fn destino_en_descargas(sugerido: &Path) -> Option<PathBuf> {
    let home = std::env::var_os("HOME")?;
    let downloads = PathBuf::from(home).join("Downloads");
    create_dir_all(&downloads).ok()?;
    // El nombre sale del sugerido; si el webview no propuso ninguno —pasa con `blob:` sin
    // `download`— se usa uno neutro en vez de abandonar la descarga.
    let nombre = sugerido
        .file_name()
        .and_then(|v| v.to_str())
        .filter(|v| !v.is_empty())
        .unwrap_or("descarga");
    Some(available_download_path(&downloads, nombre))
}

#[tauri::command]
fn open_artifact(path: String) -> Result<(), String> {
    let source = checked_artifact(&path)?;
    let downloaded = downloads_copy(&source)?;
    Command::new("open").arg(&downloaded).spawn().map_err(|e| format!("{}: {e}", ui_copy("No se pudo abrir el archivo", "Could not open the file")))?;
    Ok(())
}

#[tauri::command]
fn reveal_artifact(path: String) -> Result<(), String> {
    let source = checked_artifact(&path)?;
    Command::new("open").arg("-R").arg(source).spawn().map_err(|e| format!("{}: {e}", ui_copy("No se pudo mostrar el archivo", "Could not reveal the file")))?;
    Ok(())
}

#[tauri::command]
fn download_artifact(name: String, contents_base64: String) -> Result<String, String> {
    use base64::Engine;
    let filename = Path::new(&name).file_name().and_then(|v| v.to_str()).filter(|v| !v.is_empty()).ok_or_else(|| ui_copy("Nombre de archivo inválido", "Invalid filename"))?;
    let bytes = base64::engine::general_purpose::STANDARD.decode(contents_base64).map_err(|_| ui_copy("La descarga recibió datos inválidos", "Download data is invalid"))?;
    let home = std::env::var_os("HOME").ok_or_else(|| ui_copy("No se encontró el directorio de usuario", "User directory not found"))?;
    let downloads = PathBuf::from(home).join("Downloads");
    create_dir_all(&downloads).map_err(|e| format!("{}: {e}", ui_copy("No se pudo preparar Descargas", "Could not prepare Downloads")))?;
    let destination = available_download_path(&downloads, filename);
    std::fs::write(&destination, bytes).map_err(|e| format!("{}: {e}", ui_copy("No se pudo guardar en Descargas", "Could not save to Downloads")))?;
    Ok(destination.display().to_string())
}

/// ── Puerto ESTABLE (GAP-DEV-DESKTOP §Tauri-c) ─────────────────────────────────────────
/// WebKit particiona TODO el storage web (localStorage, IndexedDB, cookies) por ORIGEN =
/// scheme+host+puerto. El `free_port()` histórico (bind :0) estrenaba un puerto efímero
/// en cada launch → cada arranque era OTRO origen → la sesión/login/cerebro guardados en
/// el launch anterior quedaban en una partición inalcanzable (38 particiones huérfanas
/// medidas en ~/Library/WebKit). El puerto ahora es FIJO con fallback DETERMINÍSTICO:
///
///   8330 — primario de la app instalada; lejos de los puertos del repo
///   (:8080-:8151 dev, :8923-:8926 shims/CLI) y bajo el rango efímero
///   de macOS (49152+), sin servicio IANA conocido.
///
/// Manejo de colisión (en orden):
///   1. El primario se reintenta ~1s (4×250ms): un sidecar predecesor moribundo lo suelta
///      al morir (watchdog --parent-pid) → el relaunch inmediato recupera el MISMO origen.
///   2. Ocupado de verdad (otra app, o segunda instancia de Aleph): se avanza EN ORDEN por
///      el rango corto 8331-8333 — como el orden es fijo, se re-aterriza en el mismo
///      origen que cualquier launch anterior que haya caído ahí (4 orígenes acotados, no
///      infinitos; la limpieza de abajo jamás toca estos 4).
///   3. Rango entero ocupado (≥4 squatters — patológico): último recurso efímero para que
///      la app ABRA igual (disponibilidad > persistencia), con warning fuerte: la sesión
///      de ESE launch no va a persistir.
///
/// `ALEPH_SIDECAR_PORT` pinnea un puerto exacto (dev/diagnóstico; sin fallback).
/// El shell retiene el listener y entrega un duplicado al sidecar: ningún proceso puede
/// ocupar el puerto entre el probe y el arranque, ni tras un crash del sidecar.
const PORT_RANGE: [u16; 4] = [8330, 8331, 8332, 8333];

/// ¿Se puede bindear el puerto en loopback ahora mismo? (bind y soltar).
fn port_is_free(port: u16) -> bool {
    TcpListener::bind(("127.0.0.1", port)).is_ok()
}

/// Elige el puerto del sidecar según el contrato de arriba.
fn stable_port() -> u16 {
    if let Ok(v) = std::env::var("ALEPH_SIDECAR_PORT") {
        if let Ok(p) = v.parse::<u16>() {
            eprintln!("[shell] puerto pinneado por ALEPH_SIDECAR_PORT: {}", p);
            return p;
        }
    }
    stable_port_in(&PORT_RANGE)
}

fn stable_port_in(range: &[u16]) -> u16 {
    let Some(&primary) = range.first() else { return free_port() };
    for intento in 0..4 {
        if port_is_free(primary) {
            return primary;
        }
        if intento < 3 {
            std::thread::sleep(Duration::from_millis(250));
        }
    }
    for &p in &range[1..] {
        if port_is_free(p) {
            eprintln!("[shell] :{} ocupado — fallback determinístico a :{}", primary, p);
            return p;
        }
    }
    let p = free_port();
    eprintln!(
        "[shell] ⚠ rango estable {:?} entero ocupado — puerto efímero :{} (la sesión de ESTE launch no va a persistir)",
        range, p
    );
    p
}

/// Un puerto TCP libre en loopback (bind a :0, leer el asignado, soltar).
/// SOLO último recurso de `stable_port()` — un puerto efímero estrena origen WebKit y la
/// sesión no persiste (la razón de todo el bloque de arriba).
fn free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .and_then(|l| l.local_addr())
        .map(|a| a.port())
        .unwrap_or(8080)
}

/// ── Limpieza BEST-EFFORT de particiones WebKit huérfanas (GAP §Tauri-c) ──────────────
/// Los launches históricos con puerto aleatorio dejaron ~38 orígenes 127.0.0.1:<efímero>
/// bajo ~/Library/WebKit/app.aleph.desktop/WebsiteData/Default/<hash>/<hash>/{origin,…}.
/// Cada `origin` serializa (formato WebKit observado) strings length-prefixed:
///   u32len "http" 0x01 … u32len 0x01 "127.0.0.1" 0x01 <u16 puerto LE>  (top + frame)
/// Se borra la partición (el dir <hash> de primer nivel) SOLO si tiene ≥1 archivo
/// `origin`, TODOS mencionan 127.0.0.1, TODOS los puertos decodifican y TODOS caen fuera
/// del set a conservar (rango estable + puerto elegido). Cualquier duda —parse raro,
/// host no-loopback (p.ej. tauri://localhost del splash), error de IO— se DEJA.
/// Nunca fatal: la app arranca igual si esto falla entero.

/// Todos los puertos que siguen a una ocurrencia de "127.0.0.1" en el blob; `None` por
/// ocurrencia que no decodifica (flag 0x01 ausente o bytes cortos).
fn loopback_ports(bytes: &[u8]) -> Vec<Option<u16>> {
    const HOST: &[u8] = b"127.0.0.1";
    let mut out = Vec::new();
    let mut i = 0;
    while i + HOST.len() <= bytes.len() {
        if &bytes[i..i + HOST.len()] == HOST {
            let rest = &bytes[i + HOST.len()..];
            if rest.len() >= 3 && rest[0] == 0x01 {
                out.push(Some(u16::from_le_bytes([rest[1], rest[2]])));
            } else {
                out.push(None);
            }
            i += HOST.len();
        } else {
            i += 1;
        }
    }
    out
}

/// ¿La partición es huérfana? (ver contrato del bloque de limpieza).
fn origin_is_stale(origin_bytes: &[u8], keep: &[u16]) -> bool {
    let ports = loopback_ports(origin_bytes);
    !ports.is_empty()
        && ports
            .iter()
            .all(|p| matches!(p, Some(port) if !keep.contains(port)))
}

/// Barre `default_dir` (WebsiteData/Default) y borra particiones huérfanas.
/// Devuelve (borradas, saltadas). Todo error de IO = saltar, jamás propagar.
fn clean_stale_webkit_storage(default_dir: &Path, keep: &[u16]) -> (usize, usize) {
    let (mut borradas, mut saltadas) = (0usize, 0usize);
    let entries = match std::fs::read_dir(default_dir) {
        Ok(e) => e,
        Err(_) => return (0, 0),
    };
    for entry in entries.flatten() {
        let part = entry.path();
        if !part.is_dir() {
            continue;
        }
        // origins de la partición: <part>/<hash>/origin
        let mut origins = Vec::new();
        if let Ok(subs) = std::fs::read_dir(&part) {
            for sub in subs.flatten() {
                let of = sub.path().join("origin");
                if of.is_file() {
                    origins.push(of);
                }
            }
        }
        let stale = !origins.is_empty()
            && origins.iter().all(|of| match std::fs::read(of) {
                Ok(bytes) => origin_is_stale(&bytes, keep),
                Err(_) => false,
            });
        if stale && std::fs::remove_dir_all(&part).is_ok() {
            borradas += 1;
        } else {
            saltadas += 1;
        }
    }
    (borradas, saltadas)
}

/// Resuelve el dir WebsiteData/Default del bundle y corre la limpieza. macOS-only (la
/// ruta es de WebKit.framework); se ejecuta ANTES de crear la webview (nadie tiene esos
/// sqlite abiertos todavía). El identifier va en sync con tauri.conf.json.
fn clean_stale_webkit_storage_for_bundle(keep: &[u16]) {
    if !cfg!(target_os = "macos") {
        return;
    }
    let home = match std::env::var("HOME") {
        Ok(h) if !h.is_empty() => h,
        _ => return,
    };
    let default_dir = Path::new(&home)
        .join("Library/WebKit/app.aleph.desktop/WebsiteData/Default");
    if !default_dir.is_dir() {
        return;
    }
    let (borradas, saltadas) = clean_stale_webkit_storage(&default_dir, keep);
    if borradas > 0 || saltadas > 0 {
        eprintln!(
            "[shell] storage WebKit: {} partición(es) huérfana(s) de puertos viejos borradas, {} conservadas",
            borradas, saltadas
        );
    }
}

/// Bloquea hasta que el backend responda HTTP, no sólo hasta que el socket acepte TCP.
/// El shell retiene el listener: otro proceso no puede falsificar esta respuesta.
fn wait_ready(port: u16, timeout: Duration) -> bool {
    let start = Instant::now();
    while start.elapsed() < timeout {
        let address = std::net::SocketAddr::from(([127, 0, 0, 1], port));
        if let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(250)) {
            let _ = stream.set_read_timeout(Some(Duration::from_millis(250)));
            let request = format!("GET /health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n");
            if stream.write_all(request.as_bytes()).is_ok() {
                // TCP may split headers and body. Inspect a bounded complete response,
                // not only the first packet (the frozen sidecar exposes this race).
                let mut response = Vec::with_capacity(1024);
                let mut chunk = [0u8; 1024];
                while response.len() < 8192 {
                    match stream.read(&mut chunk) {
                        Ok(0) | Err(_) => break,
                        Ok(size) => {
                            response.extend_from_slice(&chunk[..size]);
                            let body = String::from_utf8_lossy(&response);
                            if body.starts_with("HTTP/1.1 200 ") && body.contains("puppet-ai-core") {
                                return true;
                            }
                        }
                    }
                }
            }
        }
        std::thread::sleep(Duration::from_millis(150));
    }
    false
}

/// Resuelve el binario del sidecar. En el BUNDLE (.app) el externalBin de Tauri queda
/// JUNTO al ejecutable principal (`Contents/MacOS/aleph_sidecar`) → cero env vars.
/// `ALEPH_SIDECAR_BIN` queda SOLO como fallback de DEV (`cargo run`/`tauri dev`, donde no
/// hay bundle). Esto satisface "externalBin dentro del bundle, no por env var".
fn resolve_sidecar() -> Option<std::path::PathBuf> {
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            let p = dir.join("aleph_sidecar");
            if p.exists() {
                return Some(p);
            }
        }
    }
    match std::env::var("ALEPH_SIDECAR_BIN") {
        Ok(p) if !p.is_empty() && std::path::Path::new(&p).exists() => {
            Some(std::path::PathBuf::from(p))
        }
        _ => None,
    }
}

/// Archivo durable del diagnóstico del motor. En una .app lanzada desde Finder no hay
/// terminal: heredar stdout/stderr equivale a perderlos y deja `Aleph.log` en 0 bytes.
fn sidecar_log_file() -> Option<File> {
    // An explicit isolated data root also isolates diagnostics during private
    // packaged QA. Normal Finder launches keep the established Library/Logs path.
    let dir = if let Some(root) = std::env::var_os("ALEPH_DATA_DIR").filter(|v| !v.is_empty()) {
        std::path::PathBuf::from(root).join("logs")
    } else {
        let user_home = std::env::var_os("HOME")?;
        std::path::PathBuf::from(user_home).join("Library/Logs/app.aleph.desktop")
    };
    if create_dir_all(&dir).is_err() {
        return None;
    }
    let path = dir.join("Aleph.log");
    // Un único histórico alcanza para diagnóstico y evita que stdout/stderr crezcan sin
    // límite. La rotación ocurre antes del spawn, cuando ningún sidecar hijo escribe aún.
    if metadata(&path).map(|m| m.len() >= 5 * 1024 * 1024).unwrap_or(false) {
        let _ = rename(&path, dir.join("Aleph.log.1"));
    }
    OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .ok()
}

/// Spawnea el sidecar frozen. `None` si no se encuentra el binario o falla el spawn.
fn spawn_sidecar(port: u16, launch_cap: &str, listener: &TcpListener) -> Option<Child> {
    let bin = match resolve_sidecar() {
        Some(p) => p,
        None => {
            eprintln!("[shell] sidecar no encontrado (ni junto al .app ni ALEPH_SIDECAR_BIN) — splash queda");
            return None;
        }
    };
    // --parent-pid: el sidecar vigila NUESTRO pid y se autotermina si morimos (anti-huérfano,
    // robusto ante el doble-proceso del onefile de PyInstaller y ante SIGKILL/crash del shell).
    let ppid = std::process::id().to_string();
    eprintln!("[shell] spawneando sidecar: {} --port {} --parent-pid {}", bin.display(), port, ppid);
    let mut cmd = Command::new(&bin);
    // Rust sockets are CLOEXEC. Duplicate only for this child; keep the original
    // bound in the shell for its entire lifetime so a crashed sidecar cannot be replaced.
    let child_socket = listener.try_clone().ok()?;
    let listen_fd = child_socket.as_raw_fd();
    let fd_flags = unsafe { libc::fcntl(listen_fd, libc::F_GETFD) };
    if fd_flags < 0 || unsafe { libc::fcntl(listen_fd, libc::F_SETFD,
                                             fd_flags & !libc::FD_CLOEXEC) } < 0 {
        eprintln!("[shell] no se pudo entregar el listener al sidecar");
        return None;
    }
    cmd.arg("--port").arg(port.to_string())
        .arg("--listen-fd").arg(listen_fd.to_string())
        .arg("--parent-pid").arg(&ppid)
        .arg("--launch-cap-stdin=1")
        .stdin(Stdio::piped());
    if let Some(mut log_file) = sidecar_log_file() {
        let _ = writeln!(
            log_file,
            "[shell] iniciando sidecar en :{} (pid padre {})",
            port, ppid
        );
        if let Ok(stdout_file) = log_file.try_clone() {
            cmd.stdout(Stdio::from(stdout_file))
                .stderr(Stdio::from(log_file));
        }
    }
    let result = cmd.spawn();
    drop(child_socket);
    match result {
        Ok(mut child) => {
            let delivered = child.stdin.take().map(|mut input| {
                writeln!(input, "{launch_cap}").is_ok()
            }).unwrap_or(false);
            if !delivered {
                let _ = child.kill();
                eprintln!("[shell] no se pudo entregar la capability al sidecar por el pipe privado");
                return None;
            }
            Some(child)
        }
        Err(e) => {
            eprintln!("[shell] no se pudo spawnear el sidecar '{}': {}", bin.display(), e);
            None
        }
    }
}

#[cfg(test)]
mod oauth_frozen_component_tests {
    use super::*;

    #[test]
    fn shell_hands_reserved_socket_to_frozen_python_component() {
        let Ok(probe) = std::env::var("ALEPH_OAUTH_FROZEN_PROBE") else {
            return; // The isolated component test supplies its own frozen executable.
        };
        assert!(Path::new(&probe).is_file());
        std::env::set_var("ALEPH_SIDECAR_BIN", &probe);
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let capability = "a".repeat(64);
        let mut child = spawn_sidecar(port, &capability, &listener)
            .expect("shell must spawn frozen component with inherited listener");
        let ready = wait_ready(port, Duration::from_secs(20));
        if ready {
            if let Ok(mut shutdown) = TcpStream::connect(("127.0.0.1", port)) {
                let _ = shutdown.write_all(b"GET /shutdown HTTP/1.1\r\nConnection: close\r\n\r\n");
            }
        } else {
            let _ = child.kill();
        }
        let _ = child.wait();
        assert!(ready, "frozen component must adopt the exact reserved listener");
        let log_path = Path::new(&std::env::var("HOME").unwrap())
            .join("Library/Logs/app.aleph.desktop/Aleph.log");
        let log = std::fs::read_to_string(log_path).unwrap();
        assert!(!log.contains(&capability), "launch capability must not enter shell/sidecar logs");
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let port = stable_port();
    let bound_socket = match TcpListener::bind(("127.0.0.1", port)) {
        Ok(listener) => Arc::new(listener),
        Err(error) => {
            eprintln!("[shell] el puerto :{port} cambió de dueño antes del bind: {error} — arranque cancelado");
            return;
        }
    };
    let mut cap_bytes = [0u8; 32];
    if let Err(e) = getrandom::getrandom(&mut cap_bytes) {
        eprintln!("[shell] no se pudo generar la capability de arranque: {e} — sidecar no se inicia");
        return;
    }
    let launch_cap: String = cap_bytes.iter().map(|b| format!("{b:02x}")).collect();
    UI_PORT.store(port, Ordering::Relaxed);
    // Conservar SIEMPRE los 4 orígenes del rango (un launch anterior pudo caer en un
    // fallback y dejar sesión válida ahí) + el puerto elegido (cubre el pin por env).
    let mut keep: Vec<u16> = PORT_RANGE.to_vec();
    if !keep.contains(&port) {
        keep.push(port);
    }
    clean_stale_webkit_storage_for_bundle(&keep);
    let child = spawn_sidecar(port, &launch_cap, &bound_socket);
    let child_slot: Arc<Mutex<Option<Child>>> = Arc::new(Mutex::new(child));
    let kill_slot = child_slot.clone();
    let port_guard = bound_socket.clone();

    tauri::Builder::default()
        // opener: el botón de OAuth abre la URL en el NAVEGADOR DEL SISTEMA (Google bloquea
        // OAuth en webviews embebidas). El frontend lo llama por window.__TAURI__.opener.
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![open_artifact, reveal_artifact, download_artifact, choose_cli_executable])
        .setup(move |app| {
            // LA VENTANA SE CONSTRUYE ACÁ, no la crea la config (`"create": false`). El
            // enganche de descargas es un método del BUILDER: una ventana ya creada no lo
            // acepta. Todo lo demás —tamaño, título, redimensionable— lo sigue diciendo
            // `tauri.conf.json`; acá sólo se le agrega el manejador.
            let ventana = app
                .config()
                .app
                .windows
                .iter()
                .find(|w| w.label == "main")
                .cloned();
            if let Some(cfg) = ventana {
                // El handle se captura acá: `on_navigation` recibe SÓLO la url.
                let handle_links = app.handle().clone();
                tauri::webview::WebviewWindowBuilder::from_config(app.handle(), &cfg)?
                    // Sólo el frame principal recibe la capability. No se persiste en
                    // storage ni se pasa a `initialization_script_for_all_frames`.
                    .initialization_script(splash_script(native_ui_lang(port), &launch_cap, port))
                    .initialization_script_for_all_frames(include_str!("download-bridge.js"))
                    // ── UN LINK EXTERNO SE ABRE EN EL NAVEGADOR, NO ACÁ ADENTRO ────────
                    //
                    // LO QUE PASABA, VISTO EN PANTALLA. Ciencia devolvió una lista de
                    // papers con sus URLs de openalex.org y NINGUNA se podía abrir: en una
                    // webview un `<a href="https://…">` o no hace nada o —peor— te navega
                    // LA VENTANA DE ALEPH afuera de la app, y el usuario se queda sin
                    // aplicación y sin forma obvia de volver.
                    //
                    // ES DE LA CÁSCARA Y POR ESO ES UNIVERSAL: los seis workspaces y la
                    // Sala viven adentro de esta misma webview, así que arreglarlo acá los
                    // cubre a todos sin tocarle una línea a ningún stack. Arreglarlo stack
                    // por stack habrían sido seis parches y el séptimo esperando.
                    //
                    // El criterio es el ORIGEN, no el esquema: lo local es la casa y se
                    // navega adentro (el sidecar en 127.0.0.1, los packs en su puerto, y
                    // `tauri://`/`about:` que son de la propia webview). Todo lo demás es
                    // afuera: se manda al navegador del sistema y se BLOQUEA la navegación.
                    //
                    // Mismo espíritu que `on_download`: el plugin `opener` ya estaba acá
                    // para el botón de OAuth —Google bloquea OAuth en webviews embebidas—,
                    // sólo que nadie lo había conectado a los links del contenido.
                    .on_navigation(move |url| {
                        if es_de_la_casa(&url) {
                            return true;
                        }
                        // Sólo se delega lo que un navegador entiende. Un esquema raro no se
                        // abre «por las dudas»: se dice y se bloquea igual.
                        if matches!(url.scheme(), "http" | "https" | "mailto") {
                            use tauri_plugin_opener::OpenerExt;
                            if let Err(e) = handle_links
                                .opener()
                                .open_url(url.as_str(), None::<&str>)
                            {
                                eprintln!("[shell] no pude abrir {} en el navegador: {}", url, e);
                            } else {
                                eprintln!("[shell] link externo → navegador: {}", url);
                            }
                        } else {
                            eprintln!("[shell] navegación bloqueada, esquema no soportado: {}", url);
                        }
                        false
                    })
                    .on_download(|_webview, evento| {
                        if let tauri::webview::DownloadEvent::Requested { destination, .. } = evento {
                            if let Some(destino) = destino_en_descargas(destination) {
                                eprintln!("[shell] descarga → {}", destino.display());
                                *destination = destino;
                            }
                        }
                        // Autorizar SIEMPRE. Un `false` acá se ve igual que el bug que esto
                        // arregla: no pasa nada y nadie sabe por qué.
                        true
                    })
                    .build()?;
            }
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            // Espera al backend en un hilo aparte (no bloquea el arranque de la ventana) y,
            // cuando responde, navega la webview 'main' al sidecar EN EL HILO PRINCIPAL
            // (macOS exige que el toque a la webview sea main-thread).
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                let ready = wait_ready(port, Duration::from_secs(45));
                if !ready {
                    eprintln!("[shell] el sidecar no respondió en :{} — se queda el splash", port);
                    return;
                }
                let url = format!("http://127.0.0.1:{}/", port);
                eprintln!("[shell] backend listo — navegando a {}", url);
                let h_nav = handle.clone();
                let nav_url = url.clone();
                let _ = handle.run_on_main_thread(move || {
                    if let Some(win) = h_nav.get_webview_window("main") {
                        match tauri::Url::parse(&nav_url) {
                            Ok(u) => {
                                if let Err(e) = win.navigate(u) {
                                    eprintln!("[shell] navigate falló: {}", e);
                                }
                            }
                            Err(e) => eprintln!("[shell] url inválida: {}", e),
                        }
                    }
                });
                // Verificación post-carga (Rust-side, sin screen-capture): la URL EFECTIVA de
                // la webview. Si siguió el 307 → .../Home.dc.html, cargó Home de verdad.
                std::thread::sleep(Duration::from_secs(6));
                let h_chk = handle.clone();
                let _ = handle.run_on_main_thread(move || {
                    if let Some(win) = h_chk.get_webview_window("main") {
                        match win.url() {
                            Ok(u) => eprintln!("[shell] webview URL efectiva: {}", u),
                            Err(e) => eprintln!("[shell] no pude leer webview URL: {}", e),
                        }
                    }
                });
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(move |_app_handle, event| {
            let _keep_port_reserved = &port_guard;
            // Al salir, matar el sidecar para no dejar uvicorn huérfano.
            if let tauri::RunEvent::Exit = event {
                if let Ok(mut slot) = kill_slot.lock() {
                    if let Some(mut c) = slot.take() {
                        // SIGTERM PRIMERO, SIGKILL DESPUÉS — y la diferencia son 214 MB.
                        //
                        // `Child::kill()` de Rust ES SIGKILL, que no se puede atajar. El
                        // sidecar es un onefile de PyInstaller: su bootloader borra el
                        // `_MEIxxxxxx` de $TMPDIR al salir, y con SIGKILL nunca llega a
                        // hacerlo. MEDIDO 2026-07-31 contra el binario instalado: SIGTERM
                        // deja 0 directorios, SIGKILL deja 1 de 214 MB. O sea que la fuga
                        // no era de los cierres sucios — era de TODOS, incluido el normal.
                        // En esta máquina se juntaron 9 GB y frenaron un build.
                        //
                        // Con TERM el bootloader lo reenvía a su hijo Python, que ya hace
                        // el cierre gracioso que este bloque describía (:8926 + los CLI).
                        // El KILL queda como red: si en 3 s no salió, no va a salir.
                        eprintln!("[shell] cerrando — SIGTERM al sidecar");
                        let pid = c.id() as i32;
                        unsafe { libc::kill(pid, libc::SIGTERM); }
                        let plazo = Instant::now() + Duration::from_secs(3);
                        let mut salio = false;
                        while Instant::now() < plazo {
                            match c.try_wait() {
                                Ok(Some(_)) => { salio = true; break; }
                                Ok(None) => std::thread::sleep(Duration::from_millis(50)),
                                Err(_) => break,
                            }
                        }
                        if !salio {
                            eprintln!("[shell] el sidecar no salió con TERM — SIGKILL");
                            let _ = c.kill();
                        }
                        // wait() igual: evita dejar un zombie inmediato.
                        let _ = c.wait();
                    }
                }
            }
        });
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex as StdMutex;

    /// Los tests de puertos comparten los puertos REALES del rango: serializarlos para
    /// que el probe de uno no le robe el bind al otro (cargo test corre en paralelo).
    static PORT_TESTS: StdMutex<()> = StdMutex::new(());

    #[test]
    fn puerto_estable_es_deterministico_entre_launches() {
        let _lock = PORT_TESTS.lock().unwrap();
        // Dos "launches" consecutivos con el rango libre → el MISMO puerto (mismo origen
        // WebKit → la sesión del launch 1 es visible en el launch 2). Con free_port()
        // viejo esto fallaba siempre.
        let first = TcpListener::bind("127.0.0.1:0").unwrap();
        let second = TcpListener::bind("127.0.0.1:0").unwrap();
        let range = [first.local_addr().unwrap().port(), second.local_addr().unwrap().port()];
        drop((first, second));
        let a = stable_port_in(&range);
        let b = stable_port_in(&range);
        assert_eq!(a, b, "dos launches consecutivos deben aterrizar en el mismo puerto");
        assert_eq!(a, range[0], "sin colisión, el puerto sale del rango estable");
    }

    #[test]
    fn colision_avanza_en_orden_por_el_rango() {
        let _lock = PORT_TESTS.lock().unwrap();
        // Squatter en el primario → fallback determinístico al SIGUIENTE del rango.
        let squat = TcpListener::bind("127.0.0.1:0").unwrap();
        let fallback = TcpListener::bind("127.0.0.1:0").unwrap();
        let range = [squat.local_addr().unwrap().port(), fallback.local_addr().unwrap().port()];
        drop(fallback);
        let p = stable_port_in(&range);
        assert_eq!(p, range[1], "con :{} ocupado, toca :{}", range[0], range[1]);
    }

    /// Blob `origin` REAL capturado en ~/Library/WebKit/app.aleph.desktop (hexdump del
    /// GAP-DEV-DESKTOP): http://127.0.0.1:63678 como top+frame origin.
    fn origin_real(port: u16) -> Vec<u8> {
        let mut rec = Vec::new();
        rec.extend_from_slice(&4u32.to_le_bytes());
        rec.push(0x01);
        rec.extend_from_slice(b"http");
        rec.extend_from_slice(&9u32.to_le_bytes());
        rec.push(0x01);
        rec.extend_from_slice(b"127.0.0.1");
        rec.push(0x01);
        rec.extend_from_slice(&port.to_le_bytes());
        let mut out = rec.clone();
        out.extend_from_slice(&rec); // top origin + frame origin, idénticos
        out
    }

    #[test]
    fn origin_decodifica_y_clasifica() {
        let keep = PORT_RANGE.to_vec();
        // huérfano: puerto efímero viejo (el 63678 del hexdump real)
        assert!(origin_is_stale(&origin_real(63678), &keep));
        // conservar: puerto del rango estable
        assert!(!origin_is_stale(&origin_real(PORT_RANGE[0]), &keep));
        // conservar: host no-loopback (ni una ocurrencia de 127.0.0.1)
        assert!(!origin_is_stale(b"\x04\x00\x00\x00\x01tauri\x09\x00\x00\x00\x01localhost", &keep));
        // conservar: blob corrupto (host presente pero puerto no decodifica)
        assert!(!origin_is_stale(b"127.0.0.1", &keep));
        assert_eq!(loopback_ports(&origin_real(63678)), vec![Some(63678), Some(63678)]);
    }

    #[test]
    fn limpieza_borra_solo_huerfanas_y_es_best_effort() {
        let keep = PORT_RANGE.to_vec();
        let root = std::env::temp_dir().join(format!("aleph-webkit-test-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        let mk = |nombre: &str, bytes: &[u8]| {
            let d = root.join(nombre).join(nombre);
            std::fs::create_dir_all(&d).unwrap();
            std::fs::write(d.join("origin"), bytes).unwrap();
            std::fs::create_dir_all(root.join(nombre).join(nombre).join("LocalStorage")).unwrap();
        };
        mk("stale-a", &origin_real(60374));
        mk("stale-b", &origin_real(55887));
        mk("keep-rango", &origin_real(PORT_RANGE[2]));
        mk("keep-raro", b"blob sin loopback");
        std::fs::create_dir_all(root.join("sin-origin")).unwrap(); // dir vacío → saltar

        let (borradas, saltadas) = clean_stale_webkit_storage(&root, &keep);
        assert_eq!(borradas, 2, "solo las dos particiones de puertos efímeros viejos");
        assert_eq!(saltadas, 3);
        assert!(!root.join("stale-a").exists());
        assert!(!root.join("stale-b").exists());
        assert!(root.join("keep-rango").exists());
        assert!(root.join("keep-raro").exists());

        // best-effort: dir inexistente → (0,0) sin pánico
        assert_eq!(clean_stale_webkit_storage(&root.join("no-existe"), &keep), (0, 0));
        let _ = std::fs::remove_dir_all(&root);
    }
}
