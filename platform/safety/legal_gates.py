"""
legal_gates.py — postura LEGAL por nicho (capa encima del gate de aprobación).

El approval_gate del org ya envuelve send/money con la matriz de UX. Esto es OTRA capa,
ortogonal: la obligación LEGAL del campo, que no depende de si la acción "toca plata".
Lee `recipe.meta.nicho` (el campo canónico) y devuelve una postura:

  - INGENIERÍA → human-in-the-loop OBLIGATORIO en cualquier entregable/acción con efecto.
    Un cálculo estructural / un plano que sale sin que un ingeniero responsable lo apruebe
    es responsabilidad profesional (sellado/PE). La capa fuerza require_human=True.
  - FINANZAS → redistribución/atribución: los datos (SEC EDGAR, FRED, etc.) tienen términos
    de redistribución y el output NO es asesoría de inversión. Adjunta el aviso obligatorio.
  - MEDICINA → HIPAA: el belt dicom/Orthanc es DEV/TEST ONLY. En env=prod se BLOQUEA;
    en dev/test se permite con el banner "datos sintéticos / no-PHI".

Es ADITIVO: solo puede BLOQUEAR o EXIGIR-HUMANO o ANEXAR-AVISO. Nunca afloja nada.
Parametrizable: agregar un nicho = agregar una entrada acá, no tocar el core.
"""
from __future__ import annotations

import os
from typing import Any, Optional

# Normalización: el mismo nicho llega con/ sin acento, en es/en.
_ALIASES = {
    "ingenieria": "ingenieria", "ingeniería": "ingenieria", "engineering": "ingenieria",
    "mech": "ingenieria", "mecanica": "ingenieria", "mecánica": "ingenieria",
    "finanzas": "finanzas", "finance": "finanzas", "fin": "finanzas",
    "medicina": "medicina", "medicine": "medicina", "medical": "medicina",
    "salud": "medicina", "health": "medicina", "dicom": "medicina",
}

# Postura por nicho. require_human / blocked_envs / notice.
_POLICY: dict[str, dict[str, Any]] = {
    "ingenieria": {
        "require_human": True,
        "blocked_envs": (),
        "notice": ("Entregable de ingeniería: requiere revisión y aprobación de un "
                   "profesional responsable antes de su uso. Aleph no sella ni certifica."),
        "basis": "responsabilidad profesional / human-in-the-loop (requisito legal del campo)",
    },
    "finanzas": {
        "require_human": False,
        "blocked_envs": (),
        "notice": ("No es asesoría de inversión. Datos de fuentes públicas (SEC EDGAR, FRED, "
                   "etc.) sujetos a sus términos de redistribución y atribución."),
        "basis": "redistribución de datos + descargo de asesoría",
    },
    "medicina": {
        "require_human": True,
        "blocked_envs": ("prod", "production"),
        "notice": ("HIPAA: belt clínico habilitado SOLO para dev/test con datos sintéticos "
                   "(no-PHI). Prohibido procesar datos de pacientes reales."),
        "basis": "HIPAA — dev/test only, sin PHI real",
    },
}

_OPEN = {"require_human": False, "blocked_envs": (), "notice": None, "basis": "sin obligación legal específica"}


def _canon(nicho: Optional[str]) -> str:
    return _ALIASES.get((nicho or "").strip().lower(), (nicho or "").strip().lower())


def policy_for(nicho: Optional[str]) -> dict[str, Any]:
    return _POLICY.get(_canon(nicho), _OPEN)


def _env() -> str:
    # [audit superficie] DEFAULT = prod. La AUSENCIA de la variable se trata como
    # PRODUCCIÓN (el modo más restrictivo) — misma doctrina que P7: un gate legal cuyo
    # default es "dev" deja el belt clínico HIPAA sin bloqueo en cualquier deploy que se
    # olvide de setear la env (que es exactamente lo que pasaba en Render). Sólo un
    # `ALEPH_ENV=dev` EXPLÍCITO relaja; el stack de desarrollo lo setea.
    return (os.environ.get("ALEPH_ENV") or os.environ.get("ENV") or "prod").strip().lower()


def enforce(recipe: dict, *, env: Optional[str] = None) -> dict[str, Any]:
    """
    Decisión legal ADITIVA para un run. NO ejecuta nada — devuelve qué debe imponer el
    caller:
      {
        "nicho": str, "allow": bool, "require_human": bool,
        "notice": str|None, "reason": str|None, "basis": str
      }
    - allow=False  → el run NO debe correr (ej. medicina en prod). El caller corta.
    - require_human=True → todo efecto externo del run debe pasar por OK humano explícito
      (el caller fuerza el send/money-gate a confirma-siempre / no auto-aprueba).
    """
    env = (env or _env()).lower()
    nicho = (recipe.get("meta") or {}).get("nicho") if isinstance(recipe, dict) else None
    pol = policy_for(nicho)
    blocked = env in pol["blocked_envs"]
    return {
        "nicho": _canon(nicho),
        "allow": not blocked,
        "require_human": bool(pol["require_human"]),
        "notice": pol["notice"],
        "reason": (f"{_canon(nicho)} bloqueado en env={env}: {pol['basis']}" if blocked else None),
        "basis": pol["basis"],
        "env": env,
    }
