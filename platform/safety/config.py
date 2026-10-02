"""
config.py — parámetros de la capa de safety, TODOS override-ables por env.

Cero constantes mágicas escondidas en la lógica: el operador ajusta el régimen por
env sin tocar código. Defaults conservadores (fail-closed). Mismo criterio del org:
lo seguro auto-avanza, lo dudoso se frena.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Raíz de datos del backend (donde ya viven espacios/, run_outputs/, etc.). La capa de
# safety escribe su propio sub-árbol data/safety/ (audit, kill-switch, rate-state).
_REPO_ROOT = Path(__file__).resolve().parents[2]

# [Casa 2 · Fase 3 · B3] El DÓNDE por rol lo centraliza aleph_paths: cliente → dir de
# datos del usuario (fuera del árbol); control → product/backend/data (histórico). El
# override explícito ALEPH_DATA_ROOT sigue ganando siempre (ambos roles). Fail-safe al
# árbol si aleph_paths no resuelve.
_PLATFORM = str(_REPO_ROOT / "platform")
if _PLATFORM not in sys.path:
    sys.path.insert(0, _PLATFORM)
try:
    import aleph_paths
    _default_data_root = str(aleph_paths.data_root())
except Exception:
    _default_data_root = str(_REPO_ROOT / "product" / "backend" / "data")

DATA_ROOT = Path(os.environ.get("ALEPH_DATA_ROOT", _default_data_root))
SAFETY_DIR = DATA_ROOT / "safety"


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip())
    except (ValueError, AttributeError):
        return default


def _env_list(name: str) -> list[str]:
    raw = os.environ.get(name, "") or ""
    return [x.strip().lower() for x in raw.split(",") if x.strip()]


# ── SSRF / recon ──────────────────────────────────────────────────────────────
# Esquemas que el recon puede navegar. file://, gopher://, data://, ftp:// jamás.
ALLOWED_SCHEMES = ("http", "https")

# "Solo software con derecho a inspeccionar": si esta allowlist está poblada (sufijos
# de host, coma-separados), un target DEBE matchear o se rechaza. Vacía = sin allowlist
# de host (se confía en el resto de la defensa: rangos privados + consentimiento).
INSPECT_HOST_ALLOWLIST = _env_list("ALEPH_INSPECT_ALLOWLIST")

# Override global de dev: permitir targets privados/loopback en TODO el recon. Default
# OFF — en prod jamás. (Los fixtures benignos pasan allow_local_fixture=True explícito.)
ALLOW_PRIVATE_TARGETS = _env_bool("ALEPH_SAFETY_ALLOW_PRIVATE_TARGETS", False)

# IPs de metadata de cloud — SIEMPRE bloqueadas aunque alguien afloje lo demás. Belt-and-
# suspenders sobre el filtro de rangos (169.254.169.254 ya cae en link-local, pero lo
# nombramos explícito por ser el blanco #1 de SSRF).
CLOUD_METADATA_IPS = frozenset({
    "169.254.169.254",      # AWS / GCP / Azure / DigitalOcean IMDS
    "100.100.100.200",      # Alibaba Cloud
    "fd00:ec2::254",        # AWS IMDS IPv6
})

# ── rate-limit del recon (por sujeto: user_id o space_id) ─────────────────────
RECON_RATE_MAX = _env_int("ALEPH_RECON_RATE_MAX", 20)            # nº de recon
RECON_RATE_WINDOW_S = _env_int("ALEPH_RECON_RATE_WINDOW_S", 3600)  # por ventana (1h)

# ── blast-radius de writes del agente ─────────────────────────────────────────
# Cuántos writes EXTERNOS puede disparar un sujeto en la ventana antes de que la capa
# auto-trabe el kill-switch de ese scope ("un write masivo se puede frenar").
WRITE_BLAST_MAX = _env_int("ALEPH_WRITE_BLAST_MAX", 25)
WRITE_BLAST_WINDOW_S = _env_int("ALEPH_WRITE_BLAST_WINDOW_S", 600)  # 10 min

# ── retención / privacidad ────────────────────────────────────────────────────
# Días que se conservan los artefactos de recon efímeros (espacios inspect-*/recon-*)
# y los outputs de runs antes de que el sweep los pueda borrar. 0 = no expira por edad.
RETENTION_SPACES_DAYS = _env_int("ALEPH_RETENTION_SPACES_DAYS", 30)
RETENTION_RUN_OUTPUTS_DAYS = _env_int("ALEPH_RETENTION_RUN_OUTPUTS_DAYS", 90)
RETENTION_AUDIT_DAYS = _env_int("ALEPH_RETENTION_AUDIT_DAYS", 365)


def ensure_safety_dir() -> Path:
    SAFETY_DIR.mkdir(parents=True, exist_ok=True)
    return SAFETY_DIR
