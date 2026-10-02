"""
mesa/preguntas.py — el catálogo de PREGUNTAS TEMPRANAS + la clasificación de cuándo preguntar.

La inversión "preguntar-temprano > morir-tarde" vive acá. Dos familias:

  • PRE-MOTOR (P2, P3): condiciones detectables ANTES de lanzar el motor — falta URL, forma
    ambigua / credencial faltante. El runner las evalúa al crear/retomar; si dispara, PAUSA
    con la pregunta antes de gastar un intento.
  • POST-MOTOR (P4, P5): el motor corrió y murió en un punto ASKABLE — MFA detectado (Forma 2
    remite a Forma 3) o cerebro degradado / cero candidatas. El runner clasifica el desenlace
    del intento y, si es askable, PAUSA con la pregunta preservando el inventario (borrador).

Anti-fatiga (regla dura): SOLO puntos de decisión genuinos. Un caso CLARO (url + forma +
credencial) NO dispara ninguna pregunta y fluye directo. `clasificar_pre_motor` devuelve None
en el caso claro; `clasificar_desenlace` devuelve None cuando el intento terminó (ok o cierre
honesto no-askable) — el harness prueba ambos sentidos.

La pregunta JAMÁS pide la credencial en el chat: si la respuesta implica credencial, la opción
lleva `abre="credencial"` (o "browser" para 2FA) y el front abre el flujo existente que la pide
por su canal (deep-link / vault / captura browser).
"""
from __future__ import annotations

import re
from typing import Optional

from inspection.mesa.modelos import Opcion, Pregunta

# formas de sesión reconocidas (espeja resolve_forma del forge_router)
_FORMAS_VALIDAS = {"abierto", "open", "token", "login", "browser", "browser-oauth"}


def _pid(construccion_id: str, codigo: str) -> str:
    return f"{construccion_id}:{codigo}"


# ── PRE-MOTOR ───────────────────────────────────────────────────────────────────
def clasificar_pre_motor(construccion_id: str, pedido: dict) -> Optional[Pregunta]:
    """Antes de lanzar el motor. Devuelve la pregunta a hacer, o None si el pedido está claro.

    pedido: {service?, url?, forma?, cred_provista:bool, session_key?, docs_url?}."""
    url = (pedido.get("url") or "").strip()
    forma = (pedido.get("forma") or "").strip().lower()
    cred_provista = bool(pedido.get("cred_provista"))
    session_key = (pedido.get("session_key") or "").strip()
    docs = (pedido.get("docs_url") or "").strip()

    # P2 · sin URL y sin docs para deducirla → no hay a qué entrar. Pedir la URL/docs.
    if not url and not docs:
        return Pregunta(
            pregunta_id=_pid(construccion_id, "P2"), estacion="encontrarlo", codigo="P2",
            texto="No tengo la dirección del servicio. ¿De dónde saco su API?",
            opciones=[
                Opcion("aportar-url", "Pegar la URL o la doc de la API",
                       "Su dirección base o un link a la documentación.", abre="docs"),
                Opcion("guardar-borrador", "Guardar y seguir después",
                       "Queda como borrador retomable."),
            ],
        )

    # P3 · forma ambigua o credencial faltante para la forma elegida → preguntar cómo se entra.
    # Caso CLARO (no dispara): forma válida + (abierto | token con cred | login con creds |
    # browser con session_key).
    forma_falta = forma not in _FORMAS_VALIDAS
    token_sin_cred = forma in ("token",) and not cred_provista
    browser_sin_key = forma in ("browser", "browser-oauth") and not session_key
    if forma_falta or token_sin_cred or browser_sin_key:
        return Pregunta(
            pregunta_id=_pid(construccion_id, "P3"), estacion="entrar", codigo="P3",
            texto="¿Cómo se entra a este servicio?",
            opciones=[
                Opcion("token", "Con una clave (API key / token)",
                       "Te la pido por su canal seguro, no aquí.", abre="credencial"),
                Opcion("login", "Con usuario y contraseña",
                       "Un login que la propia API define.", abre="credencial"),
                Opcion("abierto", "Es abierto, sin credencial",
                       "El servicio se describe solo."),
                Opcion("browser", "Necesita que entre yo (2FA)",
                       "Abres una ventana, haces el login y el 2FA tú.", abre="browser"),
            ][:3] if not browser_sin_key else [
                Opcion("browser", "Abrir la ventana para entrar",
                       "Haces el login y el segundo factor tú.", abre="browser"),
                Opcion("guardar-borrador", "Guardar y seguir después", ""),
            ],
        )

    return None  # caso claro → sin pregunta (anti-fatiga)


# ── POST-MOTOR ────────────────────────────────────────────────────────────────────
_MFA_RE = re.compile(r"2fa|mfa|multi[- ]?factor|segundo factor|verificaci[oó]n en dos|otp", re.I)
_FORMA3_RE = re.compile(r"forma\s*3|navegador|browser", re.I)


def clasificar_desenlace(
    construccion_id: str, *, ok: bool, degraded: bool, convergence: str,
    session_error: str, verified: int, forma: str,
) -> Optional[Pregunta]:
    """Después de un intento del motor. Devuelve la pregunta askable, o None si no hay que
    preguntar (terminó ok, o cerró honesto sin punto de decisión genuino).

    session_error: el detail del session.error (vacío si no hubo). convergence: el motivo de
    cierre del loop. verified: cuántas tools sobrevivieron el candado."""
    if ok and verified > 0:
        return None  # equipó algo → no se pregunta

    # P4 · MFA/2FA detectado en el login (Forma 2 remite a Forma 3). El motor NUNCA resuelve el
    # segundo factor: se lo pasa al humano por el flujo browser existente.
    if session_error and (_MFA_RE.search(session_error) or
                          (_FORMA3_RE.search(session_error) and "login" in session_error.lower())):
        return Pregunta(
            pregunta_id=_pid(construccion_id, "P4"), estacion="entrar", codigo="P4",
            texto="Este login pide un segundo factor (2FA). No lo puedo resolver yo.",
            opciones=[
                Opcion("abrir-ventana", "Abrir una ventana para que entres tú",
                       "Haces el login + 2FA; reuso esa sesión sin verla.", abre="browser"),
                Opcion("guardar-borrador", "Guardar y seguir después", ""),
            ],
        )

    # P5 · el cerebro se cayó (degradado) o no quedó ninguna tool → pedir un empujón concreto en
    # vez de rendirse. Docs claras o un ejemplo real de llamada destraban la síntesis.
    degradado = degraded or "degraded" in (convergence or "").lower()
    sin_tools = verified == 0
    if (degradado or sin_tools) and not session_error:
        motivo = ("El cerebro no respondió a tiempo" if degradado
                  else "No logré confirmar ninguna herramienta sola")
        return Pregunta(
            pregunta_id=_pid(construccion_id, "P5"), estacion="armar", codigo="P5",
            texto=f"{motivo}. ¿Me das una pista para armar las herramientas?",
            opciones=[
                Opcion("aportar-docs", "Pegar un link a la documentación",
                       "Oriento la síntesis con la doc real.", abre="docs"),
                Opcion("aportar-ejemplo", "Darme un ejemplo de llamada que funcione",
                       "Un endpoint que sabes que anda; lo verifico y sigo.", abre="ejemplo"),
                Opcion("guardar-borrador", "Guardar y seguir después", ""),
            ],
        )

    return None  # cierre honesto sin punto de decisión genuino (p.ej. session_error de red)


__all__ = ["clasificar_pre_motor", "clasificar_desenlace"]
