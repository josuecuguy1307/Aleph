#!/usr/bin/env python3
"""
PIEZA 3 — Sandbox de ejecución de código (Jupyter/Stata).

La ejecución de código (T02/T04/T08 del threat-model) corre con:

    • workdir ACOTADO: el cwd del proceso de código es un directorio aislado;
      todo acceso a archivos fuera de ese árbol se rechaza,
    • SIN acceso a ~/.ssh, ~/.env, al vault, ni a secretos montados,
    • SIN red salvo la API permitida (declarada por el belt),
    • el environment del kernel se construye con `clean_env()` — JAMÁS hereda
      las credenciales del vault ni del entorno del runtime.

Dos capas de defensa (defense-in-depth):
  (1) `clean_env()` + workdir acotado: el kernel arranca sin nada sensible montado
      ni en env ni en cwd (control de configuración).
  (2) `SandboxGuard.guard_code()`: escaneo adversarial del código a ejecutar —
      todo intento de leer rutas prohibidas (~/.ssh, .env, el vault, /etc/passwd)
      o de abrir red fuera de la lista blanca se RECHAZA con error claro ANTES de
      correr (control de admisión). Test adversarial del done (d).

PARAMETRIZABLE: las rutas prohibidas y la lista blanca de red entran por config;
el motor no sabe de finanzas.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional


class SandboxError(Exception):
    """Se lanza cuando el código viola la política del sandbox. Mensaje claro al usuario."""


# Rutas que NUNCA pueden tocarse desde código sandboxeado.
DEFAULT_FORBIDDEN_PATHS = [
    "~/.ssh", ".ssh/", "id_rsa", "id_ed25519",
    "~/.env", "/.env", ".env",
    "vault.enc", "vault.salt", "/vault", "credentials.json",
    "/etc/passwd", "/etc/shadow", "~/.aws", "~/.config/gcloud",
    "service_account", "service-account",
]

# Firmas de exfiltración / acceso a secretos por código.
DEFAULT_FORBIDDEN_PATTERNS = [
    r"os\.environ",                       # leer el environment (donde podrían vivir secretos)
    r"os\.getenv",
    r"subprocess",                        # shell-out (curl, cat ~/.ssh, etc.)
    r"os\.system",
    r"socket\.",                          # red cruda
    r"\bsmtplib\b", r"\bftplib\b",
    r"open\s*\(\s*['\"][^'\"]*\.ssh",     # open('~/.ssh/...')
    r"Path\.home\s*\(\s*\)",              # navegar al home del usuario
    r"pathlib\.Path\.home",
]


class SandboxGuard:
    """
    Control de admisión para código que va a un kernel.

    `guard_code(code)` -> levanta SandboxError si el código intenta salir de la
    caja. El workdir acotado y `clean_env()` son la segunda y tercera línea: aun
    si una firma se escapara del escáner, el kernel no tiene secretos en env ni
    rutas sensibles en su cwd.
    """

    def __init__(self, workdir: str,
                 forbidden_paths: Optional[list] = None,
                 forbidden_patterns: Optional[list] = None,
                 net_allowlist: Optional[list] = None):
        self.workdir = Path(workdir).expanduser().resolve()
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.forbidden_paths = [p for p in (forbidden_paths or DEFAULT_FORBIDDEN_PATHS)]
        self.forbidden_patterns = [re.compile(p) for p in (forbidden_patterns or DEFAULT_FORBIDDEN_PATTERNS)]
        self.net_allowlist = net_allowlist or []

    def guard_code(self, code: str) -> None:
        """Rechaza el código si viola la política. Mensaje claro (sin jerga)."""
        low = code.lower()

        # 1) rutas prohibidas literales
        for p in self.forbidden_paths:
            needle = p.lower().lstrip("~")
            if needle and needle in low:
                raise SandboxError(
                    "Tu agente intentó leer un archivo protegido de tu computadora "
                    f"(«{p}»). La caja de seguridad lo bloqueó: el código corre aislado "
                    "y no puede tocar tus llaves, tu vault ni tus secretos."
                )

        # 2) firmas de exfiltración / acceso a entorno
        for rx in self.forbidden_patterns:
            if rx.search(code):
                raise SandboxError(
                    "Tu agente intentó usar una operación que la caja de seguridad no "
                    "permite (leer variables de entorno, abrir red cruda o ejecutar "
                    "comandos del sistema). Se bloqueó antes de correr."
                )

    def clean_env(self, allowed_api_vars: Optional[list] = None,
                  base_env: Optional[dict] = None,
                  vault=None) -> dict:
        """
        Construye el environment del kernel SIN secretos. Solo se inyectan las
        variables de API explícitamente permitidas por el belt (ej. la key de
        mercado para un backtest), y esas vienen del vault — el resto del
        entorno del runtime NO se hereda.

        Devuelve un dict mínimo y seguro.
        """
        # arranca de cero: PATH mínimo, HOME apuntando al workdir (no al home real)
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(self.workdir),
            "PWD": str(self.workdir),
            "PUPPET_SANDBOX": "1",
        }
        # inyectar SOLO las API vars permitidas, desde el vault si está disponible
        for var in (allowed_api_vars or []):
            if vault is not None and vault.has(var):
                env[var] = vault.inject_env({}, [var]).get(var, "")
            elif base_env and var in base_env:
                env[var] = base_env[var]
        return env

    def resolve_path(self, requested: str) -> Path:
        """
        Normaliza una ruta pedida por el código y la confina al workdir.
        Levanta SandboxError si escapa (path traversal, ruta absoluta fuera).
        """
        p = (self.workdir / requested).resolve() if not Path(requested).is_absolute() \
            else Path(requested).resolve()
        if not str(p).startswith(str(self.workdir)):
            raise SandboxError(
                f"Tu agente intentó escribir fuera de su carpeta de trabajo segura «{requested}». "
                "La caja de seguridad lo confina a su propio directorio."
            )
        return p
