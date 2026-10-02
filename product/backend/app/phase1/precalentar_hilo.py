"""precalentar_hilo.py — los MCP del hilo, arrancados MIENTRAS el dueño escribe.

EL NÚMERO QUE ATACA. Con el workdir estable por hilo y el dueño sosteniendo, el turno 2 en
adelante cuesta 26-88 ms de `asm.restaurar`. El turno 1 de una conversación nueva paga
2.331 ms: las 4 piezas atadas al workdir (`filesystem`, `sqlite`, `pysandbox`, `officecli`)
todavía no existen para ESE hilo. Las otras 4 (`duckduckgo`, `fetch`, `markitdown`,
`skills`) ya están calientes desde cualquier hilo anterior — su huella no lleva el workdir.

LA VENTANA ES EL TIPEO. Este módulo se dispara al CREAR el hilo, que desde la obra que lo
acompaña pasa a ocurrir con la primera tecla del composer y no al mandar. Entre esa tecla y
el envío hay segundos de sobra para 2,3 s de arranque.

⚠️ POR QUÉ NO ES `calentar_cinturon`, que ya existe. Aquél calienta las piezas de un
AGENTE GUARDADO: las lee del registro por `puppet_id`, las verifica una por una y persiste
el veredicto en su fila — su trabajo es que la card diga la verdad antes de escribir. El
piso de la Sala no tiene `puppet_id` ni filas de registro que actualizar: corre el KIT, que
es un belt fijo. Son dos trabajos distintos sobre el mismo mecanismo, y meterlos en una
función sería la duplicación al revés. Lo que sí se reusa es TODO lo que importa: el
restaurador, el dueño y el mismo `_servidor_stdio` que usa el turno.

⚠️ LA HUELLA TIENE QUE SER LA MISMA O ESTO NO SIRVE DE NADA. Por eso el spec no se arma
acá: se pide por las MISMAS funciones del assembler que arma el turno (`_puppet_run_env`,
`_expand_server_cfg`, `_servidor_stdio`), y el workdir sale del MISMO
`_carpeta_del_turno`. Una huella distinta no es «no ganamos»: es arrancar 8 procesos que
nadie va a reusar. Lo mide `qa/verify_precalentado_hilo.py`: tras precalentar, el turno NO
agrega filas a `procesos.jsonl`.

FIRE-AND-FORGET, SIEMPRE. Corre en un hilo daemon y no devuelve nada a nadie. Si falla, si
tarda, o si el dueño está apagado, el turno arranca sus servers como siempre: este módulo
sólo puede hacer que el t1 sea MÁS RÁPIDO, nunca más lento ni más frágil.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from typing import Optional

_log = sys.stderr

#: Apagado con `ALEPH_PRECALENTAR=off`. Prendido es el default: sin esto la obra no hace
#: nada, y el costo de equivocarse es un arranque que igual iba a pasar en el turno.
def _encendido() -> bool:
    return (os.environ.get("ALEPH_PRECALENTAR") or "on").strip().lower() in ("on", "1", "true")


#: Cuántos hilos se pueden estar precalentando a la vez. No es el techo del dueño (ése
#: cuenta conexiones vivas): es cuántos ARRANQUES simultáneos tolera la máquina antes de
#: que competir por CPU los haga a todos más lentos que hacerlos de a uno.
_MAX_EN_VUELO = int(os.environ.get("ALEPH_PRECALENTAR_MAX", "2"))
_EN_VUELO: set = set()
_LOCK = threading.Lock()


def precalentar(chat_id: str, *, owner: Optional[str] = None) -> bool:
    """Arranca en background los MCP del hilo. Devuelve si SE LANZÓ (no si funcionó)."""
    if not _encendido() or not chat_id:
        return False
    cid = str(chat_id)
    with _LOCK:
        if cid in _EN_VUELO or len(_EN_VUELO) >= _MAX_EN_VUELO:
            return False                       # ya viene uno, o hay demasiados naciendo
        _EN_VUELO.add(cid)
    h = threading.Thread(target=_correr, args=(cid, owner), daemon=True,
                         name=f"precalentar-{cid[:8]}")
    h.start()
    return True


def _correr(chat_id: str, owner: Optional[str]) -> None:
    t0 = time.perf_counter()
    try:
        from app.phase1 import executor as EX, kit_base as K
        asm = EX._asm()
        if asm is None or not getattr(asm, "_restaurador", None):
            return

        # EL MISMO WORKDIR QUE USARÁ EL TURNO. No se calcula acá: se pide a quien lo decide.
        carpeta = EX._carpeta_del_turno(chat_id, None, chat_id)
        workdir = str((EX._RUN_OUTPUTS_ROOT / carpeta).resolve())
        Path(workdir).mkdir(parents=True, exist_ok=True)

        servers_raw = _servers_del_kit(asm, K)
        if not servers_raw:
            return

        # Y EL MISMO ENV. `_puppet_run_env` respeta un PUPPET_WORKDIR ya puesto y marca la
        # conexión como NO efímera, que es lo que la hace reusable.
        base_env = asm._puppet_run_env(EX._RESOURCE_ROOT, {"PUPPET_WORKDIR": workdir})

        r = asm._restaurador.restaurar_servers(
            servers_raw, base_env,
            expandir=asm._expand_server_cfg,
            mcp_server_cls=asm._servidor_stdio(owner),
            leer_entidad=asm._lector_de_entidades(owner),
            env_efectivo=asm._env_efectivo_del_registro(),
        )
        # SOLTAR NO ES MATAR: con el dueño encendido, `stop()` devuelve el préstamo y la
        # conexión queda viva por ociosidad. Es exactamente lo que hace el turno al cerrar.
        for p in (r.arrancadas or []):
            try:
                p.stop()
            except Exception:                  # noqa: BLE001
                pass
        ms = (time.perf_counter() - t0) * 1000
        print(f"[precalentar] hilo {chat_id[:8]}: {len(r.arrancadas or [])} pieza(s) "
              f"calientes, {len(r.caidas or [])} caída(s) · {ms:.0f} ms", file=_log, flush=True)
    except Exception as e:                     # noqa: BLE001 — jamás tumba nada
        print(f"[precalentar] hilo {chat_id[:8]} NO se pudo: {type(e).__name__}: {e}",
              file=_log, flush=True)
    finally:
        with _LOCK:
            _EN_VUELO.discard(str(chat_id))


def _servers_del_kit(asm, K) -> dict:
    """Los `mcpServers` del kit, por el MISMO resolvedor de belts que usa el turno.

    `resolve_belt_ref` devuelve un `ResolvedBelt` con la RUTA del `.mcp.json`, no el dict:
    el archivo se lee acá, que es lo que hace el assembler dos líneas después de resolver.
    """
    import json
    from app.phase1 import executor as EX
    try:
        from belt_resolver import resolve_belt_ref                # type: ignore
    except Exception:                                             # noqa: BLE001
        return {}
    try:
        res = resolve_belt_ref(K.KIT_BELT_REF, Path(EX._RESOURCE_ROOT))
        cfg = json.loads(Path(res.mcp_json_path).read_text("utf-8"))
    except Exception:                                             # noqa: BLE001
        return {}
    servers = cfg.get("mcpServers") if isinstance(cfg, dict) else None
    return servers if isinstance(servers, dict) else {}


__all__ = ["precalentar"]
