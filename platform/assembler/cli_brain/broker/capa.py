#!/usr/bin/env python3
"""capa.py — el enganche del broker en `invoke`, con caída al camino de hoy.

DÓNDE ENGANCHA Y POR QUÉ AHÍ: en `CliBrainProvider.invoke`, que es el único lugar donde
hoy nace un proceso de CLI. El borde de LEY 12 no se toca, el `:8926` sigue siendo
OpenAI-compat, y `parse_result` de cada provider sigue siendo el que traduce el camino de
hoy. Lo único que cambia es QUIÉN corre el turno.

🔴 EL RESPALDO ES EL CAMINO DE HOY, NO UN ERROR. Cualquier fallo del broker —el pool
lleno, el handshake que no vuelve, el proceso que murió a mitad— devuelve `None` y `invoke`
sigue de largo como si el broker no existiera. Un broker que rompe turnos es peor que no
tener broker.

⚠️ LA PERILLA SE LEE CON `get(VAR, DEFAULT)`, JAMÁS `get(VAR) or DEFAULT`. Con `or`,
`PUPPET_CLI_BROKER=` (vacío, que es como se apaga algo desde un `.plist` o un script) cae
otra vez en el default y la perilla no apaga nada. Ya se pagó en otra obra.
"""
from __future__ import annotations

import os
import sys
import time
from typing import Optional

from .adaptador import ResultadoTurno
from .pool import POOL, BrokerError
from .vocabulario import (DESCUBRIMIENTO, Capabilities, Harness, Session,
                          dueno_de_clave, huella_de_config)

_log = sys.stderr

#: EL LIBRO DE CAÍDAS. Sin esto, «¿cuántas veces se cayó al respaldo y por qué?» no tiene
#: respuesta: cinco de los `return None` de `intentar_turno` eran MUDOS (sin `cfg`, sin
#: adaptador, sin clave de conversación, la perilla apagada), así que el broker podía no
#: entrar nunca y parecer que entraba siempre. Es la regla de la casa —fallo visible, jamás
#: mudo— aplicada a un camino que NO es un fallo: caer al respaldo es el diseño, pero tiene
#: que poder contarse. Clave: (provider, motivo). Se lee por `caidas()`.
_CAIDAS: dict = {}
_ATENDIDOS: dict = {}


def _cae(pid: str, motivo: str, detalle: str = "") -> None:
    """Anota la caída y la dice. `None` no es un error, pero tampoco es invisible."""
    _CAIDAS[(pid or "?", motivo)] = _CAIDAS.get((pid or "?", motivo), 0) + 1
    if motivo != "perilla_apagada":          # la perilla apagada no ensucia el log
        print(f"[broker] {pid or '?'} → cae al camino de hoy · motivo={motivo}"
              + (f" · {detalle}" if detalle else ""), file=_log, flush=True)


def caidas() -> dict:
    """El parte: cuántos turnos atendió el broker y cuántos cayeron, por CLI y por motivo."""
    porcli: dict = {}
    for (pid, motivo), n in _CAIDAS.items():
        porcli.setdefault(pid, {}).setdefault("caidas", {})[motivo] = n
    for pid, n in _ATENDIDOS.items():
        porcli.setdefault(pid, {})["atendidos"] = n
    return porcli

#: LA PERILLA. Default APAGADO hasta que los tres midan bien.
_ENV_PERILLA = "PUPPET_CLI_BROKER"


def encendido() -> bool:
    """Se lee EN CADA LLAMADA, como `dueno.encendido()`: así una vara que la mueva la ve y
    un rollback no exige reiniciar el sidecar."""
    return os.environ.get(_ENV_PERILLA, "off").strip().lower() in ("on", "1", "true")


# ── el censo, poblado al importar ────────────────────────────────────────────────
def _adaptadores() -> dict:
    from .claude_streamjson import ClaudeStreamJson
    from .codex_appserver import CodexAppServer
    from .grok_acp import GrokACP
    return {a.provider_id: a for a in (GrokACP, CodexAppServer, ClaudeStreamJson)}


ADAPTADORES = _adaptadores()
for _pid, _cls in ADAPTADORES.items():
    DESCUBRIMIENTO.registrar(_pid, _cls.CAPS)


def _workdir_de(harness: Harness) -> str:
    """Un directorio por proceso del pool, estable entre turnos y fuera del árbol.

    Va bajo el dir de datos del usuario por el mismo motivo que los workdirs de sesión:
    el bundle es SÓLO LECTURA y un `_MEIPASS` se borra al cerrar la app.
    """
    import hashlib
    sello = hashlib.sha256(
        f"{harness.provider_id}|{harness.dueno}|{harness.huella_config}".encode()
    ).hexdigest()[:20]
    try:
        import aleph_paths
        raiz = os.path.join(str(aleph_paths.data_root()), "broker_workdirs")
    except Exception:                                       # noqa: BLE001
        raiz = os.path.join(os.path.expanduser("~"), ".aleph-broker-workdirs")
    d = os.path.join(raiz, sello)
    os.makedirs(d, exist_ok=True)
    return d


def _config_de(provider, modelo: str, effort: str) -> Optional[dict]:
    """La config que va a la HUELLA, armada con lo que el provider de hoy ya sabe.

    ⚠️ NO SE INVENTA NADA ACÁ. El perfil de grok sale de `grok_cli._perfil_path()` y los
    MCP a apagar de `codex_cli.list_mcp_server_names()` — las MISMAS fuentes que usa el
    camino de hoy. Dos fuentes para el mismo dato es la forma de que un día no coincidan.
    """
    pid = provider.provider_id
    if pid == "grok_cli":
        from ..grok_cli import _perfil_path
        from .grok_acp import GrokACP
        return GrokACP.config(modelo=modelo, perfil=_perfil_path(), effort=effort)
    if pid == "codex_cli":
        from ..codex_cli import list_mcp_server_names
        from .codex_appserver import CodexAppServer
        return CodexAppServer.config(modelo=modelo,
                                     mcp_apagados=tuple(list_mcp_server_names()),
                                     effort=effort)
    if pid == "claude_cli":
        from .claude_streamjson import ClaudeStreamJson
        return ClaudeStreamJson.config(modelo=modelo, effort=effort)
    return None


def intentar_turno(provider, *, prompt: str, modelo: str, effort: str,
                   sesion, workdir: str, env: dict, binario: str,
                   clave_conversacion: str = "",
                   on_evento=None, plazo: float = 180.0) -> Optional[ResultadoTurno]:
    """El turno por el broker, o `None` si no se pudo (y entonces manda el camino de hoy).

    `None` NUNCA es un error del usuario: es «acá no fue» y `invoke` sigue.
    """
    pid = getattr(provider, "provider_id", "")
    if not encendido():
        _cae(pid, "perilla_apagada")
        return None
    cls = ADAPTADORES.get(pid)
    if cls is None:
        _cae(pid, "sin_adaptador")
        return None
    caps: Capabilities = cls.CAPS

    # ── EL DUEÑO. Sin clave de conversación no hay reuso posible y tampoco tiene sentido:
    # un turno sin conversación no tiene historial que amortizar. Se declara y se sale.
    # La clave llega SUELTA porque `server.py` vacía la del `sesion` cuando el CLI no
    # tiene el `--resume` probado, y eso no aplica al broker (son dos mecanismos).
    clave_conv = (str(clave_conversacion or "").strip()
                  or str(getattr(sesion, "clave", "") or "").strip())
    if not clave_conv:
        _cae(pid, "sin_clave_de_conversacion")
        return None
    dueno = dueno_de_clave(clave_conv)

    cfg = _config_de(provider, modelo, effort)
    if cfg is None:
        _cae(pid, "sin_config")
        return None
    harness = Harness(provider_id=pid, dueno=dueno, huella_config=huella_de_config(cfg))

    # ⚠️ EL WORKDIR DEL BROKER ES SUYO Y ES ESTABLE. NO el `mkdtemp` del turno: `invoke`
    # lo borra en su `finally` y el proceso vivo se quedaría con el cwd arrancado de
    # abajo en el turno siguiente. Y no siempre hay `sesion` (grok y codex llegan con
    # `sesion=None` por el gate de `RESUME_PROBADO`), así que se deriva de la clave del
    # pool: un directorio por (dueño, CLI, config), que es exactamente lo que comparte
    # el proceso.
    cwd = _workdir_de(harness)

    def _fabricar():
        ad = cls(cfg, binario, env, cwd)
        ad.saludar()
        return ad

    t0 = time.monotonic()
    try:
        prestamo = POOL.pedir(harness=harness, caps=caps,
                              clave_conversacion=clave_conv, fabricar=_fabricar)
    except BrokerError as e:
        _cae(pid, "pool_no_presto", str(e))
        return None
    except Exception as e:                                  # noqa: BLE001 — el handshake
        _cae(pid, "arranque_fallo", f"{type(e).__name__}: {e}")
        return None

    ms_pool = (time.monotonic() - t0) * 1000.0
    try:
        res = prestamo.adaptador.turno(prestamo.sesion, prompt,
                                       on_evento=on_evento, plazo=plazo)
    except Exception as e:                                  # noqa: BLE001
        prestamo.marcar_muerto(f"{type(e).__name__}: {e}")
        prestamo.soltar()
        _cae(pid, "turno_exploto", f"{type(e).__name__}: {e}")
        return None

    if res.proceso_perdido:
        # el proceso murió o se colgó: se saca del pool para que el SIGUIENTE no lo
        # encuentre, y este turno se rehace por el camino de hoy.
        prestamo.marcar_muerto(res.error_detalle)
        prestamo.soltar()
        _cae(pid, "proceso_perdido", str(res.error_detalle))
        return None

    _ATENDIDOS[pid] = _ATENDIDOS.get(pid, 0) + 1
    res.meta = dict(res.meta or {})
    res.meta.update({"broker": True, "pool_ms": round(ms_pool, 1),
                     "pid": prestamo.pid,
                     "reusado": bool(prestamo.sesion.turnos),
                     "sesion_remota": prestamo.sesion.id_remoto,
                     "caps": caps.como_dict()})
    prestamo.soltar()
    return res


def a_brain_result(res: ResultadoTurno, provider, modelo: str):
    """`ResultadoTurno` → `BrainResult`, sin inventar campos.

    ⚠️ `usage_del_cli(..., medido=...)` es el MISMO que usa el camino de hoy, y por el mismo
    motivo: un `usage` sin dato tiene que salir `None`, jamás 0. «No medible» y «cero» son
    cosas distintas, y el §P3.c ya cerró ese hueco una vez.
    """
    from ..base import BrainResult, ERR_MODEL, usage_del_cli
    if not res.ok:
        return BrainResult(ok=False, error_kind=ERR_MODEL,
                           error_detail=res.error_detalle[:300],
                           exec_events=res.exec_events,
                           meta=dict(res.meta or {}))
    usage, medido = usage_del_cli(res.usage_bruto if res.tokens_medidos else None,
                                  medido=res.tokens_medidos)
    meta = dict(res.meta or {})
    # el caché viaja con el NOMBRE de cada proveedor ya traducido por el adaptador, y el
    # annex del server lo publica igual que en el camino de hoy.
    if res.cache_lectura is not None:
        meta["cache_read_tokens"] = res.cache_lectura
    if res.cache_escritura is not None:
        meta["cache_write_tokens"] = res.cache_escritura
    if res.razonamiento is not None:
        meta["reasoning_tokens"] = res.razonamiento
    return BrainResult(ok=True, text=res.texto,
                       model_final=res.model_final or modelo,
                       model_final_source="cli-reported" if res.model_final else "",
                       usage=usage, tokens_medidos=medido,
                       exec_events=res.exec_events, meta=meta)


__all__ = ["encendido", "intentar_turno", "a_brain_result", "ADAPTADORES", "DESCUBRIMIENTO"]
