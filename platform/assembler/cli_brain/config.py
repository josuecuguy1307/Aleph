"""Device-local executable choices for CLI brains. No credentials live here."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from .registry import spec_by_id


class ConfigError(ValueError):
    """A saved or proposed CLI executable configuration is unusable."""


def config_path() -> Path:
    import aleph_paths
    return Path(aleph_paths.user_data_dir()) / "modelos" / "cli-executables.json"


def _read_all() -> dict:
    path = config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"no pude leer la configuración CLI ({type(exc).__name__})") from exc
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("providers"), dict):
        raise ConfigError("el formato de la configuración CLI es inválido")
    return data["providers"]


def get(provider_id: str) -> dict:
    if spec_by_id(provider_id) is None:
        raise ConfigError("proveedor CLI desconocido")
    item = _read_all().get(provider_id, {})
    if not isinstance(item, dict):
        raise ConfigError("la configuración del proveedor es inválida")
    mode = item.get("mode", "auto")
    if mode not in ("auto", "manual"):
        raise ConfigError("el modo de detección es inválido")
    path = item.get("path", "") if mode == "manual" else ""
    if mode == "manual" and (not isinstance(path, str) or not path or not os.path.isabs(path)):
        raise ConfigError("la ruta manual debe ser absoluta")
    return {"mode": mode, "path": path}


def verify_executable(provider_id: str, path: str) -> dict:
    spec = spec_by_id(provider_id)
    if spec is None:
        raise ConfigError("proveedor CLI desconocido")
    if not isinstance(path, str) or not os.path.isabs(path):
        raise ConfigError("selecciona una ruta absoluta")
    p = Path(path).expanduser()
    if not p.is_file() or not os.access(p, os.X_OK):
        raise ConfigError("la ruta no apunta a un archivo ejecutable")
    # A user-selected executable is run only for this explicit verification. Never
    # forward API keys, OAuth tokens, or the complete backend environment.
    from .base import sanitized_env
    try:
        r = subprocess.run([str(p), "--version"], capture_output=True, text=True,
                           timeout=8, env=sanitized_env(str(p)), check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ConfigError(f"no pude verificar el ejecutable ({type(exc).__name__})") from exc
    output = ((r.stdout or "") + " " + (r.stderr or "")).strip().lower()
    if r.returncode != 0 or spec.binary.lower() not in output:
        raise ConfigError(f"el ejecutable no se identifica como {spec.display_name}")
    return {"provider": provider_id, "binary_found": True, "identity_verified": True,
            "path": str(p)}


def save(provider_id: str, mode: str, path: str = "") -> dict:
    if spec_by_id(provider_id) is None:
        raise ConfigError("proveedor CLI desconocido")
    if mode not in ("auto", "manual"):
        raise ConfigError("elige detección automática o manual")
    if mode == "manual":
        verify_executable(provider_id, path)
    providers = dict(_read_all())
    providers[provider_id] = {"mode": mode, "path": path if mode == "manual" else ""}
    dest = config_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".cli-executables-", dir=dest.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"version": 1, "providers": providers}, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, dest)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return get(provider_id)
