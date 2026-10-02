"""
crypto.py — cifrado del storage_state, REUSANDO el vault Fernet del org.

El guard de la fase exige que el storage state (cookies/localStorage tras el
login que hace el PROPIO humano) se guarde ENCRIPTADO. No inventamos cripto:
cargamos `platform/gates/vault.py` por ruta (mismo patrón que main.py) y usamos
su CredentialVault (PBKDF2-HMAC-SHA256 → Fernet). El secreto maestro sale del
MISMO env que el runtime: PUPPET_VAULT_MASTER (fallback dev por host).

El password CRUDO nunca toca esto: el humano lo tipea en su navegador; nosotros
sólo persistimos el storage_state resultante, y cifrado.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from typing import Any, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]   # platform/inspection/crypto.py → puppet-ai/
_VAULT_PY = _REPO_ROOT / "platform" / "gates" / "vault.py"


def runtime_master_secret() -> str:
    """Mismo contrato que product/backend/app/main.py::get_vault()."""
    try:
        _node = os.uname().nodename                # POSIX (control/prod byte-idéntico)
    except AttributeError:                          # [Fase 3 · B1] Windows: os.uname no existe
        import platform
        _node = platform.node() or "aleph-client"
    return os.environ.get("PUPPET_VAULT_MASTER") or f"puppet-dev-{_node}"


def _load_vault_module():
    spec = importlib.util.spec_from_file_location("puppet_vault_inspection", _VAULT_PY)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar el vault en {_VAULT_PY}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SessionStateStore:
    """
    Almacén cifrado de storage_states de Playwright, keyed por host/etiqueta.
    Reusa CredentialVault: guarda el storage_state (dict) como JSON string cifrado.
    Archivo aislado del vault de credenciales del producto.
    """

    def __init__(self, store_path: str | os.PathLike, master_secret: Optional[str] = None):
        mod = _load_vault_module()
        Path(store_path).parent.mkdir(parents=True, exist_ok=True)
        self._vault = mod.CredentialVault(
            str(store_path), master_secret=master_secret or runtime_master_secret()
        )

    def save(self, key: str, storage_state: dict[str, Any]) -> None:
        self._vault.put(key, json.dumps(storage_state))

    def load(self, key: str) -> Optional[dict[str, Any]]:
        if not self._vault.has(key):
            return None
        # inject_env es el único getter público de valor del vault.
        raw = self._vault.inject_env({}, [key]).get(key)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    def has(self, key: str) -> bool:
        return self._vault.has(key)

    def forget(self, key: str) -> None:
        self._vault.delete(key)
