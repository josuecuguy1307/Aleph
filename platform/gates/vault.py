#!/usr/bin/env python3
"""
PIEZA 2 — Vault de credenciales.

Las keys del usuario (API keys gratis AV/FRED, OAuth Google, etc.) viven
CIFRADAS con Fernet (se recicla la experiencia Fernet del org). El valor de la
key se inyecta SOLO al proceso del MCP server — vía el environment del
subprocess — y JAMÁS:

    • entra al contexto del modelo (el LLM nunca ve el valor; llama tools por
      nombre y la tool usa la key server-side),
    • aparece en logs (los registros guardan SOLO el NOMBRE de la variable,
      nunca el valor — el helper `redacted_env_log` lo garantiza).

Diseño confirmado por P010 §B1: "env vars por nombre, jamás por valor".

Test del done (c): grep de la key en TODOS los mensajes al modelo + logs = 0.

PARAMETRIZABLE: el vault no sabe de finanzas; guarda pares (nombre→valor) para
cualquier nicho. Qué keys necesita cada belt lo dice el belt, no este archivo.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


# ── Derivación de la clave de cifrado del vault ───────────────────────────────

def _derive_fernet_key(master_secret: str, salt: bytes) -> bytes:
    """
    Deriva una clave Fernet (32 bytes url-safe b64) del secreto maestro del
    runtime. El secreto maestro vive en el entorno del runtime (NUNCA en código,
    NUNCA en el contexto del modelo). PBKDF2-HMAC-SHA256, 200k iteraciones.
    """
    dk = hashlib.pbkdf2_hmac("sha256", master_secret.encode("utf-8"), salt, 200_000, dklen=32)
    return base64.urlsafe_b64encode(dk)


# ── El vault ──────────────────────────────────────────────────────────────────

class CredentialVault:
    """
    Almacén cifrado de credenciales del usuario.

    Las credenciales se guardan cifradas en disco (vault.enc) bajo una clave
    Fernet derivada del secreto maestro del runtime. En memoria se mantiene el
    plaintext SOLO el tiempo necesario para construir el env del subprocess MCP;
    nunca se serializa a un mensaje ni a un log.
    """

    def __init__(self, store_path: str, master_secret: str):
        if not master_secret:
            raise ValueError("El vault requiere un secreto maestro del runtime (env), no vacío.")
        self._store_path = Path(store_path)
        self._salt_path = self._store_path.with_suffix(".salt")
        self._salt = self._load_or_create_salt()
        self._fernet = Fernet(_derive_fernet_key(master_secret, self._salt))
        self._cache: dict[str, str] = self._load()

    # ── escritura ──

    def put(self, name: str, value: str) -> None:
        """Guarda/actualiza una credencial. El valor se cifra antes de tocar disco."""
        self._cache[name] = value
        self._persist()

    def delete(self, name: str) -> None:
        self._cache.pop(name, None)
        self._persist()

    # ── lectura (SOLO para inyección al proceso MCP) ──

    def names(self) -> list[str]:
        """Los NOMBRES de las credenciales guardadas — seguro de loguear."""
        return sorted(self._cache.keys())

    def has(self, name: str) -> bool:
        return name in self._cache

    def inject_env(self, base_env: dict, wanted: list[str]) -> dict:
        """
        Construye el environment para un subprocess MCP, inyectando SOLO las
        credenciales pedidas (`wanted`). Devuelve un dict NUEVO; no muta base_env.

        Este es el ÚNICO camino por el que un valor de credencial sale del vault,
        y va directo al `env` del subprocess — nunca a un string que pueda llegar
        al modelo o a un log.
        """
        env = dict(base_env)
        for name in wanted:
            if name in self._cache:
                env[name] = self._cache[name]
        return env

    def resolve_env_template(self, env_template: dict) -> dict:
        """
        Resuelve un dict de env con placeholders ${NAME}: si NAME está en el
        vault, lo sustituye por el valor; si no, deja la cadena tal cual (el
        belt declara ${ALPHA_VANTAGE_API_KEY} y el vault lo llena).
        Devuelve dict NUEVO con valores reales SOLO para inyección al subprocess.
        """
        out = {}
        for k, raw in env_template.items():
            if isinstance(raw, str) and raw.startswith("${") and raw.endswith("}"):
                name = raw[2:-1]
                out[k] = self._cache.get(name, os.environ.get(name, raw))
            else:
                out[k] = raw
        return out

    # ── internos ──

    def _load_or_create_salt(self) -> bytes:
        if self._salt_path.exists():
            return self._salt_path.read_bytes()
        salt = os.urandom(16)
        self._salt_path.parent.mkdir(parents=True, exist_ok=True)
        self._salt_path.write_bytes(salt)
        try:
            os.chmod(self._salt_path, 0o600)
        except OSError:
            pass
        return salt

    def _load(self) -> dict[str, str]:
        if not self._store_path.exists():
            return {}
        try:
            blob = self._store_path.read_bytes()
            plaintext = self._fernet.decrypt(blob)
            return json.loads(plaintext.decode("utf-8"))
        except (InvalidToken, json.JSONDecodeError, OSError):
            return {}

    def _persist(self) -> None:
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        plaintext = json.dumps(self._cache).encode("utf-8")
        blob = self._fernet.encrypt(plaintext)
        self._store_path.write_bytes(blob)
        try:
            os.chmod(self._store_path, 0o600)
        except OSError:
            pass


# ── Helper de logging seguro ──────────────────────────────────────────────────

def redacted_env_log(env: dict, secret_names: list[str]) -> str:
    """
    Render de un env para LOG: las variables que son credenciales se muestran
    SOLO por nombre, con su valor enmascarado. Garantiza el contrato 'jamás por
    valor'. Usalo en cualquier punto que loguee el env de un MCP server.
    """
    parts = []
    secret_set = set(secret_names)
    for k in sorted(env.keys()):
        if k in secret_set:
            parts.append(f"{k}=<oculto:vault>")
        else:
            v = env[k]
            # heurística: nunca loguear algo con pinta de secreto aunque no esté listado
            parts.append(f"{k}={'<oculto>' if _looks_secret(str(v)) else v}")
    return " ".join(parts)


def _looks_secret(value: str) -> bool:
    v = value.strip()
    if len(v) < 16:
        return False
    # tokens largos sin espacios y mayormente alfanuméricos = sospechoso
    if " " in v:
        return False
    alnum = sum(c.isalnum() or c in "-_" for c in v)
    return alnum / max(1, len(v)) > 0.9
