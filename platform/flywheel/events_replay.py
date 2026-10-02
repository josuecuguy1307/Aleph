#!/usr/bin/env python3
"""
events_replay.py — La lib de eventos del espacio de Puppet AI (PRODUCT-V2-DESIGN).

Contrato (PRODUCT-V2-DESIGN, "el espacio vivo"):
  "cada evento se persiste ANTES de emitirse; reconexión con Last-Event-ID = replay
   exacto". Esta lib es la fuente de verdad append-only que hace ese replay POSIBLE
   y AUDITABLE.

Por qué existe:
  session.py ya appendea eventos a events.jsonl *antes* de emitir al callback
  (persist-before-emit), pero usa `time.time()` como pseudo-id y NO garantiza un id
  monotónico sin huecos ni atomicidad entre writers concurrentes. El espacio V2
  necesita las TRES cosas para que "reconexión con Last-Event-ID" sea EXACTA:
    1. id monotónico, contiguo (1,2,3,…) — sin huecos, sin duplicados;
    2. asignación de id atómica bajo concurrencia (dos writers no corrompen ni
       pisan ids) — lock de archivo (fcntl) + append O_APPEND;
    3. replay EXACTO: read_since(N) devuelve {N+1 … max}, ni uno de más ni de menos.

Diseño:
  - Append-only JSONL. Una línea = un evento. Nunca se reescribe ni se borra.
  - El id se asigna DENTRO del lock leyendo el último id del archivo (cola), de modo
    que el id es función del estado persistido, no de un contador en memoria (que se
    perdería entre procesos). Persist-before-emit: append() PRIMERO escribe (con
    fsync) y RECIÉN entonces es seguro emitir.
  - Taxonomía alineada 1:1 con platform/assembler/session.py (la REAL) + lo que V2
    suma. Ver EVENTS-SCHEMA.md.

Público:
    EVENT_TYPES                      # frozenset de tipos válidos (taxonomía V2)
    EventLog(path)                   # abre/crea un log append-only en `path`
        .append(event) -> dict       # valida, asigna id monotónico atómico, persiste
                                     #   (con fsync) ANTES de devolver; devuelve el
                                     #   evento persistido (con id/ts asignados)
        .read_since(last_event_id)   # -> list[dict] replay EXACTO de ids > last
        .read_all() -> list[dict]
        .last_id() -> int            # 0 si vacío
    verify_integrity(path) -> Report # huecos / duplicados / corrupción / orden / ts

stdlib only. Cero paths absolutos hardcodeados.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Nota de diseño: NO usamos @dataclass en este módulo a propósito. session.py carga
# sus dependencias por ruta de archivo (importlib.util.spec_from_file_location sin
# registrar en sys.modules); bajo ese loader, @dataclass no puede resolver sus type
# hints (busca sys.modules[cls.__module__].__dict__, que no existe) y explota al
# importar. Clases planas con __init__ son inmunes a eso y igual de claras.

# ── Lock de archivo: fcntl en POSIX, msvcrt en Windows (ambos stdlib) ──────────
try:
    import fcntl  # POSIX

    def _lock(fh) -> None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)

    def _unlock(fh) -> None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    _LOCK_BACKEND = "fcntl"
except ImportError:  # pragma: no cover - Windows
    import msvcrt

    def _lock(fh) -> None:
        # Bloqueo del primer byte; LK_LOCK bloquea hasta poder tomar el lock.
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)

    def _unlock(fh) -> None:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)

    _LOCK_BACKEND = "msvcrt"


# ── Taxonomía: 1:1 con la REAL de platform/assembler/session.py + V2 ───────────
# Tipos que session.py EMITE hoy (leídos de _emit(...) en la fuente real):
#   belt_ready, turn_started, tool_call_started, tool_call_finished,
#   gate_waiting, gate_resolved, final, closed
# Lo que V2 sumará (PRODUCT-V2-DESIGN, este mandato):
#   artifact_created, equipment_changed
EVENT_TYPES = frozenset({
    # lifecycle del espacio / sesión viva
    # `belt_starting` es el par de apertura de `belt_ready`: lo emite
    # `recipe_assembler` ANTES de arrancar el cinturón, y es el PRIMER evento del
    # turno. MEDIDO en vivo el 2026-08-26: sin él acá, `EventLog.append` lo
    # rechazaba y `_make_space_emitter` se comía la excepción con un `except:
    # pass` — el evento se perdía MUDO y la Sala volvía a callar 25 s. Un tipo
    # nuevo que no entra a esta taxonomía no falla: desaparece.
    "belt_starting",
    "belt_ready",
    "turn_started",
    "tool_call_started",
    "tool_call_finished",
    "gate_waiting",
    "gate_resolved",
    "final",
    "closed",
    # adiciones V2
    "artifact_created",
    "equipment_changed",
    # motor de inspección de contexto (capas 1→3): el ciclo de vida del recon que
    # el Cuarto anima en vivo (software externo → capability-block). Additivo y
    # backward-compatible: el lector del stream no re-valida, sólo formatea SSE.
    "software.detectado",
    "inspeccion.analizando",
    "accion.observada",
    "tool.sintetizada",
    # FASE 5 — cierre del loop usuario→agente (tipos recon, owner §4.4): la tool
    # sintetizada queda equipada en el puppet y se ejecuta GATEADA, con eco real y
    # costo por call; + el health-check de drift. Additivo y backward-compatible.
    "tool.equipada",      # la tool quedó registrada en recipe.belt_refs del puppet
    "tool_call",          # invocación de la tool (dry_run o real)
    "gate.held",          # el candado retuvo una acción que toca el mundo (pide OK)
    "gate.approved",      # el humano aprobó → la acción corre
    "gate.rejected",      # el humano rechazó → la acción se descarta
    "eco",                # la línea de retorno: el mundo respondió (el agente re-decide)
    "cost",               # COST-EVENT (§4.6): costo por call
    "tool.drift",         # health-check: el software cambió bajo la tool sintetizada
    "inspeccion.error",   # falla honesta del recon/loop (no se finge verde)
    # STEP 2 · A1 — SANDBOX / LOOPS CONTROLADOS / MUERTE LIMPIA. El run gestiona su
    # contexto y corta honesto; estos eventos hacen VISIBLE al frontend lo que pasó
    # (nunca un spinner infinito ni un pruning silencioso). Additivo/backward-compatible.
    "context_compacted",  # se podó historial viejo para no reventar la ventana (cuánto)
    "loop_detected",      # mismo tool+args repetido N× → se cortó el loop honesto
    "budget_exhausted",   # se alcanzó el techo de tool-calls del run → corte honesto
    # OLA UX · B2 — PLAN DECLARADO. El cerebro abre su primer turno con un bloque de pasos
    # ({"plan":[{paso,tool}]}); el assembler lo captura y lo emite UNA vez. La checklist
    # del Brief se marca SOLO con eventos reales posteriores (tool_call_finished /
    # gate_waiting / closed) — paso sin evento confirmatorio queda pendiente (honesto).
    "plan_declared",
    # STEP 2 · B1 — MULTIAGENTE / DELEGACIÓN EN VIVO. El árbol de sub-agentes se hace
    # VISIBLE: el círculo del Cuarto se enciende cuando un sub-agente trabaja AHORA y se
    # apaga (o queda en "espera tu OK") al terminar. Additivo/backward-compatible.
    "sub_agent_started",     # el padre delegó → un sub-agente arrancó su loop (trabajando AHORA)
    "sub_agent_finished",    # el sub-agente terminó (ok/error/held) → el padre integra su resultado
    "delegation_serialized",  # el tier permite < paralelos que los pedidos → corren en fila (aviso honesto)
    # BYO-CLI (D4) — DEGRADACIÓN NARRADA. `notice` es el aviso genérico honesto que el motor
    # YA emitía (kind:"degraded", uno por run) y que hasta acá se caía SILENCIOSO en la lista
    # blanca (EventValidationError tragado por los emitters) — registrado para que la Sala lo
    # narre. `brain_window_exhausted` = la ventana de la SUSCRIPCIÓN del cerebro BYO-CLI se
    # agotó a mitad de run (con provider_name y reset_hint) → fila narrada + badge no-verde.
    "notice",
    "brain_window_exhausted",
    # OLA CONSTRUCCIÓN-ASISTIDA — LA MESA DE CONSTRUCCIÓN. El stream de una construcción ES el
    # space stream (replay + reconexión gratis): la Mesa persiste acá SUS eventos meta + el
    # contrato del Motor B (que hasta hoy sólo se emitía por SSE directo, sin space). Additivo/
    # backward-compatible: un lector viejo ignora los tipos que no conoce; el reader no revalida.
    # (a) meta de la Mesa:
    "construccion.creada",     # la construcción arrancó (con su space_id)
    "estacion.cambio",         # avanzó a la estación N (encontrarlo→…→equipar)
    "pregunta.pendiente",      # el motor PAUSA y pregunta (2-3 opciones) en la estación de la duda
    "pregunta.respondida",     # el humano eligió una opción → destraba
    "construccion.pausada",    # sin thread; espera respuesta/credencial/sesión (borrador retomable)
    "construccion.reanudada",  # se relanzó el motor tras la respuesta
    "construccion.borrador",   # snapshot del inventario aprovechable al cerrar un intento
    "construccion.cerrada",    # equipó la pieza (ok) o cerró sin nada (revisar `ok`)
    "construccion.latido",     # keepalive mientras el motor trabaja (cerebro pensando)
    # (b) contrato del Motor B (traducido de los eventos crudos del engine, cero dialecto nuevo):
    "forge.iniciado", "forge.latido", "sesion.ok", "observando", "sintetizando",
    "tool.propuesta", "tool.validando", "tool.validada", "tool.descartada",
    "mcp.forjado", "mcp.equipado", "cerrado", "error",
    "dispatch.iniciado", "dispatch.forjando", "resolver.buscando", "resolver.encontrado",
    "resolver.miss", "browser.session.iniciado", "browser.fase", "sesion.capturada",
    # OLA PULSO · §1 — EL PULSO DEL LOOP. Un evento por-iteración de un loop iterativo
    # {name,value,target,iteration,unit,goal,passed} normalizado en el assembler desde
    # el convergence.json que cada hero belt YA escribe. La Sala dibuja la curva
    # iteración→valor con línea de target EN VIVO. Additivo/backward-compatible: sin
    # este tipo en la lista blanca el evento se DROPEA silencioso (EventValidationError
    # tragado por los emitters) y el Pulso queda mudo → esta línea es load-bearing.
    "metric",
    # [FIX-P9] TOOL DEL CLIENTE — el modelo pidió una tool que la SUPERFICIE ejecuta (pintar
    # las opciones del turno). El motor no la corre: la devuelve. Esta línea es load-bearing
    # igual que la de `metric`: sin el tipo en la lista blanca el evento se DROPEA en
    # SILENCIO (EventValidationError tragado por los emitters) y las opciones del turno no
    # aparecerían en vivo — sólo al cerrar el POST, y sin causa visible de por qué.
    "client_call",
    # PIEZA MÉTODO (workflows) — EL ARNÉS NARRA. El estado del workflow vive FUERA del
    # modelo (method_runs); estos eventos son la telemetría REAL que la Sala (chip
    # "dirigiendo" + card §5) y el grafo Obsidian vivo consumen (contrato exacto en
    # METODO-FRONT-NOTES.md). Additivo/backward-compatible; sin estas líneas el arnés
    # queda MUDO (EventValidationError tragado por los emitters) — load-bearing.
    "method_started",             # el run corre dirigido por un método {method_id, name, run_id}
    "method_step_started",        # paso EN CURSO {step_id, executor|null, run_id} → chispa
    "method_step_done",           # paso con evidencia real {step_id, executor?} → brasa
    "method_checkpoint_waiting",  # checkpoint esperando el OK humano → respiración en el Núcleo
    "method_step_failed",         # 3 intentos sin evidencia {diagnosis, remedies} → card §5
    "method_paused",              # el arnés se pausó (usuario o fallo) → estado del strip
    "method_resumed",             # el arnés retomó (resume / remedy) → estado del strip
    # [GATE 4 · FASE 3 · 3.2 · ley 2] WORKSPACE HEREDADO — UN PASO DE OTRO LOOP.
    # El harness de un stack importado corre SU loop y
    # ejecuta SUS tools; Aleph sólo le contesta «qué hace el modelo ahora»
    # (`/v1/workspaces/brain/complete`). Este evento anota ESE paso: qué workspace, qué
    # turno, qué modelo respondió, cuántas tools declaró y cuáles pidió.
    #
    # NO ES `tool_call_finished`, Y ESA ES LA DECISIÓN: `provenance._resolve_events`
    # cuenta `tool_call_finished{executed:true}` como HECHO medido. Escribir eso por lo
    # que otro proceso declara haber ejecutado fabricaría justo la señal que el
    # anti-grift juzga (la lección de 2.5: un auditor con su propia copia audita su
    # copia). Lo que Aleph midió acá es el MODELO; lo que el harness ejecutó es suyo, y
    # el artefacto que nazca de eso lo confiesa con `capture_quality: "declared"`.
    #
    # Load-bearing, igual que `metric` y `client_call`: sin esta línea el evento se
    # DROPEA EN SILENCIO (EventValidationError tragado por los emitters) y `close` no
    # tendría de dónde re-derivar `model_final` — el artefacto del workspace quedaría
    # `partial` para siempre y nadie sabría por qué.
    "workspace_step",
    # ── [obra 3 · el defecto de señal] LAS SEÑALES DEL BORDE, TODAS EN UN SOLO LUGAR
    # Nacían MUDAS: `append` valida `type` contra este frozenset, `_validate` levanta, y
    # el `except: pass` de `router._make_space_emitter` se lo come. **Cero eventos en
    # disco, cero señal de error.** Medido: el plegado corrió (5.935 chars ahorrados,
    # reproducido contra los mensajes grabados) y el espacio no tenía una sola línea
    # suya. Es exactamente el verde mudo que esta casa persigue, y le tocaba a la casa.
    #
    # ⚠️ DOS SESIONES DECLARARON `aleph_salidas_diferidas` POR SEPARADO y el merge las
    # dejó a las dos adentro del mismo frozenset. Un set las deduplica, así que no
    # cambiaba nada — y por eso mismo hay que sacarla: dos comentarios diciendo cada uno
    # que él es el que la introduce es cómo se pierde de vista quién declara qué.
    "aleph_salidas_diferidas",  # Aleph plegó salidas ya vistas (cuántas, cuánto ahorró)
    "aleph_leer_salida",        # el modelo pidió el resto de una salida recortada
    "codemode_script_inicio",
    "codemode_script_fin",
    "codemode_script_ilegible",
})

# Campos que la lib administra/asigna ella misma; el caller NO debe fijarlos.
_RESERVED = ("id",)
# Campos obligatorios en TODO evento del espacio.
_REQUIRED = ("type", "space_id")


class EventValidationError(ValueError):
    """El evento ofrecido a append() viola el schema. Nada se persiste."""


def _coerce_path(path: Union[str, os.PathLike]) -> Path:
    return path if isinstance(path, Path) else Path(os.fspath(path))


def _scan_last_id(fh) -> int:
    """
    Lee el id del ÚLTIMO evento bien-formado del archivo abierto `fh` (modo binario,
    posicionado donde sea). Recorre desde el inicio: O(n) en líneas, pero el id es
    siempre función del estado persistido — robusto entre procesos. Devuelve 0 si
    vacío. Ignora líneas en blanco; una línea corrupta hace fallar la asignación
    (no queremos asignar un id sobre un archivo que ya está roto).
    """
    fh.seek(0)
    last = 0
    for raw in fh:
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            cur = int(obj["id"])
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            raise EventValidationError(
                f"El log está corrupto en una línea previa; no se puede asignar un id "
                f"nuevo sin riesgo de huecos: {e}"
            )
        last = cur
    return last


class EventLog:
    """
    Un log de eventos del espacio: append-only, JSONL, con ids monotónicos
    contiguos asignados atómicamente bajo lock de archivo.
    """

    def __init__(self, path: Union[str, os.PathLike]) -> None:
        self.path = _coerce_path(path)
        parent = self.path.parent
        if str(parent) and not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
        # Crea el archivo si no existe, sin truncar uno existente.
        if not self.path.exists():
            self.path.touch()

    # ── escritura ──────────────────────────────────────────────────────────────

    def append(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Valida `event`, le asigna un id monotónico contiguo de forma ATÓMICA
        (lock exclusivo de archivo: dos writers concurrentes nunca corrompen ni
        repiten ids), lo persiste con fsync, y RECIÉN ahí devuelve el evento
        persistido. Persist-before-emit: cuando esta función retorna, el evento ya
        está en disco; el caller puede emitirlo con seguridad.

        - `type` debe estar en EVENT_TYPES.
        - `space_id` es obligatorio (string no vacío).
        - `ts` se asigna si falta (time.time()).
        - `id` lo asigna la lib SIEMPRE; si el caller lo trae, se rechaza.
        """
        validated = self._validate(event)

        # Abrimos en r+b para poder leer la cola (asignar id) y appendear bajo el
        # MISMO lock. O_APPEND no garantiza por sí solo lectura+escritura atómica
        # del id, por eso usamos un lock exclusivo de archivo alrededor de
        # leer-último-id + escribir.
        with open(self.path, "r+b") as fh:
            _lock(fh)
            try:
                next_id = _scan_last_id(fh) + 1
                record = dict(validated)
                record["id"] = next_id
                if "ts" not in record or record["ts"] is None:
                    record["ts"] = time.time()
                line = json.dumps(record, ensure_ascii=False, sort_keys=False)
                # Append físico al final, dentro del lock.
                fh.seek(0, os.SEEK_END)
                fh.write((line + "\n").encode("utf-8"))
                fh.flush()
                os.fsync(fh.fileno())  # durabilidad: en disco ANTES de soltar el lock
            finally:
                _unlock(fh)
        return record

    def _validate(self, event: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(event, dict):
            raise EventValidationError("El evento debe ser un dict.")
        for r in _RESERVED:
            if r in event and event[r] is not None:
                raise EventValidationError(
                    f"Campo reservado '{r}' lo asigna la lib; el caller no debe fijarlo."
                )
        for req in _REQUIRED:
            if req not in event or event[req] in (None, ""):
                raise EventValidationError(f"Falta el campo obligatorio '{req}'.")
        etype = event["type"]
        if etype not in EVENT_TYPES:
            raise EventValidationError(
                f"Tipo de evento desconocido: {etype!r}. "
                f"Válidos: {sorted(EVENT_TYPES)}"
            )
        if not isinstance(event["space_id"], str):
            raise EventValidationError("'space_id' debe ser string.")
        if "ts" in event and event["ts"] is not None:
            if not isinstance(event["ts"], (int, float)):
                raise EventValidationError("'ts' debe ser numérico (epoch seconds).")
        # debe ser serializable a JSON — lo verificamos acá, no a mitad del write.
        try:
            json.dumps(event, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            raise EventValidationError(f"El evento no es serializable a JSON: {e}")
        return event

    # ── lectura / replay ────────────────────────────────────────────────────────

    def read_all(self) -> List[Dict[str, Any]]:
        return self._read(min_exclusive=0)

    def read_since(self, last_event_id: int) -> List[Dict[str, Any]]:
        """
        Replay EXACTO: devuelve todos los eventos con id > last_event_id, en orden.
        Reconexión con Last-Event-ID=N => read_since(N) => exactamente {N+1..max}.
        last_event_id=0 (o ausente) => el log completo desde el principio.
        """
        try:
            floor = int(last_event_id)
        except (TypeError, ValueError):
            raise ValueError("last_event_id debe ser un entero.")
        if floor < 0:
            raise ValueError("last_event_id no puede ser negativo.")
        return self._read(min_exclusive=floor)

    def _read(self, *, min_exclusive: int) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        with open(self.path, "rb") as fh:
            _lock(fh)  # lectura consistente respecto a writers concurrentes
            try:
                fh.seek(0)
                for raw in fh:
                    line = raw.strip()
                    if not line:
                        continue
                    obj = json.loads(line.decode("utf-8"))
                    if int(obj["id"]) > min_exclusive:
                        out.append(obj)
            finally:
                _unlock(fh)
        return out

    def last_id(self) -> int:
        with open(self.path, "rb") as fh:
            _lock(fh)
            try:
                return _scan_last_id(fh)
            finally:
                _unlock(fh)


# ── verificación de integridad ─────────────────────────────────────────────────

class IntegrityReport:
    """Resultado de auditar un log. ok=True solo si no hay ninguna anomalía."""

    def __init__(self, ok: bool = True) -> None:
        self.ok: bool = ok
        self.count: int = 0
        self.max_id: int = 0
        self.gaps: List[int] = []           # ids esperados y ausentes
        self.duplicates: List[int] = []     # ids repetidos
        self.corrupt_lines: List[int] = []  # nº de línea (1-based)
        self.out_of_order: List[int] = []   # nº de línea donde el id no crece
        self.errors: List[str] = []         # mensajes legibles

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "count": self.count,
            "max_id": self.max_id,
            "gaps": self.gaps,
            "duplicates": self.duplicates,
            "corrupt_lines": self.corrupt_lines,
            "out_of_order": self.out_of_order,
            "errors": self.errors,
        }


def verify_integrity(path: Union[str, os.PathLike]) -> IntegrityReport:
    """
    Audita un log de eventos. Detecta:
      - corrupción: línea no-JSON, falta 'id'/'type'/'space_id', tipo inválido;
      - duplicados: el mismo id aparece más de una vez;
      - huecos: la secuencia 1..max_id no es contigua;
      - desorden: un id menor o igual al anterior (el log es estrictamente creciente);
    Devuelve un IntegrityReport. ok=True solo si NO hay ninguno de los anteriores.
    """
    p = _coerce_path(path)
    rep = IntegrityReport(ok=True)
    if not p.exists():
        rep.ok = False
        rep.errors.append(f"El log no existe: {p}")
        return rep

    seen: Dict[int, int] = {}  # id -> primera línea donde apareció
    prev_id: Optional[int] = None
    ids: List[int] = []

    with open(p, "rb") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                rep.corrupt_lines.append(lineno)
                rep.errors.append(f"línea {lineno}: JSON inválido")
                continue
            if not isinstance(obj, dict):
                rep.corrupt_lines.append(lineno)
                rep.errors.append(f"línea {lineno}: el evento no es un objeto JSON")
                continue
            # campos obligatorios
            missing = [k for k in ("id", "type", "space_id") if k not in obj]
            if missing:
                rep.corrupt_lines.append(lineno)
                rep.errors.append(f"línea {lineno}: faltan campos {missing}")
                continue
            try:
                eid = int(obj["id"])
            except (ValueError, TypeError):
                rep.corrupt_lines.append(lineno)
                rep.errors.append(f"línea {lineno}: 'id' no es entero ({obj['id']!r})")
                continue
            if obj["type"] not in EVENT_TYPES:
                rep.corrupt_lines.append(lineno)
                rep.errors.append(
                    f"línea {lineno}: tipo desconocido {obj['type']!r}"
                )
                continue

            # duplicados
            if eid in seen:
                rep.duplicates.append(eid)
                rep.errors.append(
                    f"línea {lineno}: id duplicado {eid} (visto en línea {seen[eid]})"
                )
            else:
                seen[eid] = lineno
                ids.append(eid)

            # orden estrictamente creciente
            if prev_id is not None and eid <= prev_id:
                rep.out_of_order.append(lineno)
                rep.errors.append(
                    f"línea {lineno}: id {eid} no es mayor al anterior {prev_id}"
                )
            prev_id = eid

    rep.count = len(ids)
    rep.max_id = max(ids) if ids else 0

    # huecos: la secuencia debe ser 1..max_id contigua
    if ids:
        present = set(ids)
        expected = set(range(1, rep.max_id + 1))
        missing_ids = sorted(expected - present)
        if missing_ids:
            rep.gaps = missing_ids
            rep.errors.append(f"huecos en la secuencia de ids: {missing_ids}")

    rep.ok = not (
        rep.gaps or rep.duplicates or rep.corrupt_lines or rep.out_of_order
    )
    return rep


__all__ = [
    "EVENT_TYPES",
    "EventLog",
    "EventValidationError",
    "IntegrityReport",
    "verify_integrity",
]


if __name__ == "__main__":  # smoke manual: python3 events_replay.py <log.jsonl>
    import sys

    if len(sys.argv) == 2:
        r = verify_integrity(sys.argv[1])
        print(json.dumps(r.as_dict(), ensure_ascii=False, indent=2))
    else:
        print("uso: python3 events_replay.py <ruta-al-log.jsonl>   # verify_integrity")
