"""Cascada de remedios instalables para conectores locales.

Orden sellado:

1. catálogo local/write-back;
2. derivación determinista desde paquete+transporte, con URL verificada;
3. búsqueda con el cerebro sólo para huecos;
4. ausencia declarada con la fuente que sí conocemos.

El módulo nunca ejecuta. Devuelve una propuesta registrada por ``remedio_id``; el endpoint
de instalación resuelve ese id del lado servidor y exige ``confirmado:true`` antes de
correr. Así el cliente no puede cambiar el comando entre lo mostrado y lo ejecutado.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import threading
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

try:
    import aleph_paths
except ImportError:  # pragma: no cover - sólo imports directos fuera del backend
    import sys
    _PLATFORM = Path(__file__).resolve().parents[4] / "platform"
    if str(_PLATFORM) not in sys.path:
        sys.path.insert(0, str(_PLATFORM))
    import aleph_paths

_LOCK = threading.Lock()
_PROPUESTAS: dict[str, dict] = {}
_BUSCADOR_IA: Optional[Callable[[dict, Optional[str]], Optional[dict]]] = None
_BUSQUEDAS_IA = 0
_URL_TIMEOUT = float(os.environ.get("ALEPH_REMEDIO_URL_TIMEOUT", "8"))

_GESTORES = frozenset({"uvx", "npx", "pip", "pip3", "python", "python3"})


def _catalog_path() -> Path:
    override = (os.environ.get("ALEPH_REMEDIOS_CATALOGO_PATH") or "").strip()
    if override:
        return Path(override)
    return aleph_paths.data_root() / "catalog" / "remedios.json"


def _read_catalog() -> dict:
    try:
        value = json.loads(_catalog_path().read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}


def _write_catalog(data: dict) -> None:
    path = _catalog_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _source_from_recommended(catalog_id: str) -> Optional[str]:
    """Sólo lee el catálogo; no extiende la ingesta de 5a."""
    try:
        root = aleph_paths.resource_root()
        data = json.loads((root / "catalog" / "recomendados.json").read_text(encoding="utf-8"))
    except Exception:
        return None
    needle = str(catalog_id or "").split("#")[-1].lower()
    for rows in data.values() if isinstance(data, dict) else []:
        for row in rows if isinstance(rows, list) else []:
            rid = str((row or {}).get("id") or "").lower()
            if rid == needle or rid.removesuffix("-mcp") == needle.removesuffix("-mcp"):
                value = str((row or {}).get("fuente") or "").strip()
                return value or None
    return None


def verificar_url(url: str, *, timeout: Optional[float] = None) -> dict:
    """Afirma una URL sólo después de una respuesta HTTP real."""
    u = str(url or "").strip()
    # Knob de vara negativa, nunca una opción de producto: simula el bug «afirmar sin
    # consultar» para comprobar que la calibración de URL se pone roja.
    if os.environ.get("ALEPH_REMEDIO_ROMPER_VERIFICACION", "").strip() == "1":
        return {"ok": True, "url": u, "status": "knob_sin_request"}
    if not u.startswith("https://"):
        return {"ok": False, "url": u, "status": None, "error": "la URL no es https"}
    req = urllib.request.Request(
        u, method="HEAD",
        headers={"User-Agent": "Aleph-remedio/1.0", "Accept": "text/html,application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout or _URL_TIMEOUT) as resp:
            return {"ok": 200 <= int(resp.status) < 400, "url": u, "status": int(resp.status)}
    except urllib.error.HTTPError as exc:
        # Algunos registries niegan HEAD. Un GET acotado decide sin descargar la página.
        if exc.code not in (400, 403, 405):
            return {"ok": False, "url": u, "status": exc.code, "error": str(exc)}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "url": u, "status": None, "error": str(exc)}
    try:
        req = urllib.request.Request(
            u, method="GET",
            headers={"User-Agent": "Aleph-remedio/1.0", "Range": "bytes=0-1023"},
        )
        with urllib.request.urlopen(req, timeout=timeout or _URL_TIMEOUT) as resp:
            resp.read(1024)
            return {"ok": 200 <= int(resp.status) < 400, "url": u, "status": int(resp.status)}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "url": u, "status": exc.code, "error": str(exc)}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "url": u, "status": None, "error": str(exc)}


def _npm_name(value: str) -> str:
    v = value.strip()
    if v.startswith("@"):
        # @scope/pkg@1.2 → @scope/pkg
        slash = v.find("/")
        at = v.find("@", slash + 1)
        return v[:at] if at > slash else v
    return v.split("@", 1)[0]


def _package_from_spec(spec: dict) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """(registry, package, command) o (None,None,None)."""
    cmd = Path(str(spec.get("command") or "")).name
    args = [str(a) for a in (spec.get("args") or [])]
    explicit = str(spec.get("package") or spec.get("paquete") or "").strip()
    if cmd == "npx":
        package = explicit or next((a for a in args if a and not a.startswith("-")), "")
        if not package:
            return None, None, None
        package = _npm_name(package)
        return "npm", package, f"npx -y {shlex.quote(package)}"
    if cmd == "uvx":
        package = explicit
        if not package and "--from" in args:
            i = args.index("--from")
            package = args[i + 1] if i + 1 < len(args) else ""
        if not package:
            package = next((a for a in args if a and not a.startswith("-")), "")
        if not package:
            return None, None, None
        package = package.split("==", 1)[0]
        return "pypi", package, f"uvx {shlex.quote(package)}"
    if cmd in {"pip", "pip3"} and explicit:
        package = explicit.split("==", 1)[0]
        return "pypi", package, f"pip install {shlex.quote(package)}"
    if cmd in {"python", "python3"} and explicit:
        package = explicit.split("==", 1)[0]
        return "pypi", package, f"pip install {shlex.quote(package)}"
    return None, None, None


def _spec_from_runtime(runtime: dict) -> dict:
    """Elige una alternativa declarada por el registro y la vuelve probeable.

    Preferimos remoto: no instala nada. Si sólo hay paquete, producimos el launcher
    estándar del registry; los argumentos extra siguen siendo los declarados.
    """
    remotes = runtime.get("remotes") if isinstance(runtime.get("remotes"), list) else []
    for remote in remotes:
        if not isinstance(remote, dict) or not str(remote.get("url") or "").startswith("https://"):
            continue
        headers = remote.get("headers") if isinstance(remote.get("headers"), list) else []
        required = [h for h in headers if isinstance(h, dict) and h.get("required")]
        first = required[0] if required else None
        return {
            "transport": "http",
            "url": remote["url"],
            "needs_auth": bool(required),
            "header_name": first.get("name") if first else None,
            "header_template": first.get("template") if first else None,
            "fuente": runtime.get("source"),
        }
    packages = runtime.get("packages") if isinstance(runtime.get("packages"), list) else []
    for package in packages:
        if not isinstance(package, dict):
            continue
        registry = str(package.get("registry") or "").lower()
        identifier = str(package.get("identifier") or "").strip()
        if not identifier:
            continue
        if registry == "npm":
            command, args = "npx", ["-y", identifier]
        elif registry == "pypi":
            command, args = "uvx", [identifier]
        elif registry in {"oci", "docker"}:
            command, args = "docker", ["run", "--rm", "-i", identifier]
        else:
            continue
        env = package.get("environment") if isinstance(package.get("environment"), list) else []
        required = [v for v in env if isinstance(v, dict) and v.get("required")]
        return {
            "transport": "stdio",
            "command": command,
            "args": [*args, *[str(v) for v in (package.get("args") or [])]],
            "package": identifier,
            "registry": registry,
            "needs_auth": bool(required),
            "package_env_var": required[0].get("name") if required else None,
            "fuente": runtime.get("source"),
        }
    return {}


def _runtime_for(catalog_id: str) -> dict:
    try:
        from app.phase1 import catalog_ingest_router
        value = catalog_ingest_router.runtime_spec(catalog_id)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _remedio_id(catalog_id: str, comando: str, fuente: str) -> str:
    raw = "\x1f".join((catalog_id, comando, fuente)).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def _registrar(row: dict) -> dict:
    item = dict(row)
    rid = item.get("remedio_id") or _remedio_id(
        str(item.get("catalog_id") or ""),
        str(item.get("como") or ""),
        str(item.get("fuente") or item.get("url") or ""),
    )
    item["remedio_id"] = rid
    _PROPUESTAS[rid] = item
    return item


def obtener(remedio_id: str) -> Optional[dict]:
    row = _PROPUESTAS.get(str(remedio_id or ""))
    if row:
        return dict(row)
    # Reiniciar el sidecar no borra lo que ya fue confirmado: también se busca en write-back.
    entries = (_read_catalog().get("entradas") or {})
    for item in entries.values() if isinstance(entries, dict) else []:
        if isinstance(item, dict) and item.get("remedio_id") == remedio_id:
            return dict(item)
    return None


def _writeback(item: dict) -> dict:
    catalog_id = str(item.get("catalog_id") or "").strip()
    if not catalog_id:
        return item
    with _LOCK:
        data = _read_catalog()
        entries = data.get("entradas") if isinstance(data.get("entradas"), dict) else {}
        clean = {
            k: item.get(k) for k in (
                "catalog_id", "como", "url", "fuente", "origen", "paquete",
                "transporte", "url_verificada", "remedio_id",
            ) if item.get(k) is not None
        }
        clean["confirmado"] = True
        entries[catalog_id] = clean
        data = {"version": 1, "entradas": entries}
        _write_catalog(data)
    return {**item, "write_back": True, "confirmado": True}


def confirmar(remedio_id: str) -> Optional[dict]:
    item = obtener(remedio_id)
    if not item:
        return None
    saved = _writeback(item)
    _PROPUESTAS[remedio_id] = saved
    return saved


def _desde_catalogo(catalog_id: str) -> Optional[dict]:
    entry = ((_read_catalog().get("entradas") or {}).get(catalog_id) or {})
    if not isinstance(entry, dict) or not entry.get("como"):
        return None
    return _registrar({
        **entry,
        "catalog_id": catalog_id,
        "estado": "listo",
        "origen": "catalogo",
        "confirmacion_requerida": True,
        "ejecutable": True,
        "write_back": True,
    })


def _derivar(spec: dict, catalog_id: str, fuente: Optional[str],
             *, url_checker: Callable[[str], dict] = verificar_url) -> Optional[dict]:
    registry, package, command = _package_from_spec(spec)
    if not registry or not package or not command:
        return None
    if registry == "npm":
        url = f"https://www.npmjs.com/package/{package}"
    else:
        url = f"https://pypi.org/project/{package}"
    checked = url_checker(url)
    item = _registrar({
        "catalog_id": catalog_id,
        "estado": "listo",
        "origen": "derivacion",
        "como": command,
        "url": url if checked.get("ok") else None,
        "url_candidata": url,
        "url_verificada": bool(checked.get("ok")),
        "url_status": checked.get("status"),
        "fuente": url if checked.get("ok") else fuente,
        "paquete": package,
        "transporte": spec.get("transport") or "stdio",
        "confirmacion_requerida": True,
        "ejecutable": True,
    })
    # La derivación sólo se afirma y recuerda como dato del catálogo cuando el link que la
    # sostiene respondió. Sin red, el comando sigue visible pero el URL no se inventa.
    return _writeback(item) if checked.get("ok") else item


def _comando_ia_seguro(command: str) -> bool:
    """Propuestas de IA: sólo un argv simple de gestor; nunca shell/metacaracteres."""
    if not command or any(x in command for x in (";", "&&", "||", "|", "`", "$(", "\n")):
        return False
    try:
        argv = shlex.split(command)
    except ValueError:
        return False
    if not argv or Path(argv[0]).name not in _GESTORES:
        return False
    if Path(argv[0]).name in {"python", "python3"}:
        return argv[1:4] == ["-m", "pip", "install"]
    return True


def _buscar_con_cerebro(spec: dict, fuente: Optional[str]) -> Optional[dict]:
    """Búsqueda acotada: la fuente conocida queda a la vista y la salida debe ser JSON."""
    if not fuente:
        return None
    try:
        from app.phase1 import method_brain
        prompt = (
            "Busca únicamente en la fuente indicada cómo preparar este servidor local. "
            "Devuelve JSON estricto con command, url y source. command debe ser UN comando "
            "sin shell usando uvx, npx -y o pip install. Si el setup necesita varios pasos, "
            "venv, archivos de configuración o no estás seguro, devuelve "
            '{"found":false}. No ejecutes nada.\n'
            f"FUENTE: {fuente}\nMANIFEST: "
            + json.dumps({
                "command": spec.get("command"),
                "args": spec.get("args") or [],
                "transport": spec.get("transport") or "stdio",
            }, ensure_ascii=False)
        )
        text, _model = method_brain._call_brain(  # type: ignore[attr-defined]
            [{"role": "user", "content": prompt}], max_tokens=450
        )
        match = re.search(r"\{[\s\S]*\}", text or "")
        obj = json.loads(match.group(0)) if match else {}
    except Exception:
        return None
    if obj.get("found") is False:
        return None
    command = str(obj.get("command") or "").strip()
    url = str(obj.get("url") or fuente or "").strip()
    source = str(obj.get("source") or fuente or "").strip()
    if not _comando_ia_seguro(command):
        return None
    checked = verificar_url(source)
    if not checked.get("ok"):
        return None
    link = url if url.startswith("https://") else source
    if link != source and not verificar_url(link).get("ok"):
        return None
    return {"como": command, "url": link,
            "fuente": source}


def _buscar_ia(spec: dict, fuente: Optional[str]) -> Optional[dict]:
    global _BUSQUEDAS_IA
    _BUSQUEDAS_IA += 1
    fn = _BUSCADOR_IA or _buscar_con_cerebro
    return fn(spec, fuente)


def resolver(spec: dict, *, catalog_id: str, fuente: Optional[str] = None,
             buscar_ia: bool = True, forzar_busqueda: bool = False,
             url_checker: Callable[[str], dict] = verificar_url) -> dict:
    """Resuelve el remedio en cascada. Nunca ejecuta."""
    catalog_id = str(catalog_id or "").strip() or "mcp-local"
    runtime = _runtime_for(catalog_id)
    normalized = _spec_from_runtime(runtime)
    # Un spec explícito/curado gana; el runtime público completa solamente sus huecos.
    spec = {**normalized, **dict(spec or {})}
    source = fuente or spec.get("fuente") or runtime.get("source") \
        or _source_from_recommended(catalog_id)

    if not forzar_busqueda:
        cached = _desde_catalogo(catalog_id)
        if cached:
            return cached

    # Campos curados que ya vinieron en el manifest: ganan sin re-derivar.
    instalacion = spec.get("instalacion") if isinstance(spec.get("instalacion"), dict) else {}
    curated_how = spec.get("como") or instalacion.get("como")
    install_url = spec.get("url_instalacion") or instalacion.get("url")
    if curated_how and install_url:
        item = _registrar({
            "catalog_id": catalog_id, "estado": "listo", "origen": "catalogo",
            "como": str(curated_how), "url": str(install_url),
            "fuente": str(spec.get("fuente") or install_url),
            "paquete": spec.get("package") or spec.get("paquete"),
            "transporte": spec.get("transport") or "stdio",
            "confirmacion_requerida": True, "ejecutable": True,
        })
        return _writeback(item)

    derived = _derivar(spec, catalog_id, source, url_checker=url_checker)
    if derived:
        return derived

    if buscar_ia:
        proposed = _buscar_ia(spec, source)
        if proposed:
            return _registrar({
                **proposed,
                "catalog_id": catalog_id,
                "estado": "propuesto",
                "origen": "busqueda_ia",
                "transporte": spec.get("transport") or "stdio",
                "confirmacion_requerida": True,
                "ejecutable": True,
                "write_back": False,
            })

    # Si la preparación no cabe en un botón seguro, el resultado sigue teniendo una mano:
    # abrir la fuente oficial. No se ofrece un comando inventado ni un callejón sin salida.
    if source and str(source).startswith("https://"):
        return {
            "catalog_id": catalog_id,
            "estado": "guia",
            "origen": "fuente_oficial",
            "mensaje": "Este conector necesita una preparación guiada.",
            "fuente": source,
            "url": source,
            "accion": {"tipo": "abrir_guia", "url": source},
            "ejecutable": True,
        }
    return {
        "catalog_id": catalog_id,
        "estado": "no_encontre",
        "origen": "busqueda_ia" if buscar_ia else "sin_busqueda",
        "mensaje": "No encontré cómo instalarlo.",
        "fuente": source,
        "repo": source,
        "accion": {
            "tipo": "buscar_de_nuevo",
            "endpoint": "/v1/motor/remedio/buscar",
            "method": "POST",
        },
        "ejecutable": False,
    }


def camino_de(remedio: dict) -> dict:
    if remedio.get("ejecutable") and remedio.get("como"):
        return {
            "estado": "ejecutable",
            "accion": "instalar",
            "label": "Instalarlo",
            "comando": remedio["como"],
            "url": remedio.get("url"),
            "fuente": remedio.get("fuente"),
            "endpoint": "/v1/motor/instalar",
            "method": "POST",
            "remedio_id": remedio.get("remedio_id"),
            "confirmacion_requerida": True,
        }
    if remedio.get("ejecutable") and remedio.get("url"):
        return {
            "estado": "ejecutable",
            "accion": "abrir_guia",
            "label": "Abrir guía oficial",
            "url": remedio["url"],
            "fuente": remedio.get("fuente"),
        }
    return {
        "estado": "ausente_declarado",
        "motivo": remedio.get("mensaje") or "No encontré cómo instalarlo.",
        "fuente": remedio.get("fuente") or remedio.get("repo"),
        "accion": remedio.get("accion"),
    }


def reset_pruebas() -> None:
    """Sólo para varas unitarias deterministas."""
    global _BUSQUEDAS_IA
    _PROPUESTAS.clear()
    _BUSQUEDAS_IA = 0


__all__ = [
    "verificar_url", "resolver", "camino_de", "obtener", "confirmar",
    "reset_pruebas", "_BUSQUEDAS_IA",
]
