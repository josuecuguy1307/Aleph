#!/usr/bin/env python3
"""codex_appserver.py — Codex como proceso vivo (`codex app-server`).

MEDIDO (E0 y pasos 1-2, codex-cli 0.147.0):
    initialize 0,044-0,394 s · thread/start 0,080-0,178 s (con los MCP apagados)
    turno 2 en 1,50-2,87 s · streamea deltas (`item/agentMessage/delta`) y tiene
    `turn/interrupt`

🔴 LAS TRES CONDICIONES, y las tres se ARRASTRAN desde el arranque del thread:

  1 · `sandbox:"read-only"` EXPLÍCITO en cada `thread/start`. Medido por el disco
      (paso 2): con el parámetro, 0 de 7 rutas escritas; **SIN el parámetro, 2 de 7** —
      codex cae al `~/.codex/config.toml` del usuario, que acá dice
      `sandbox_mode="workspace-write"`. La jaula no es del binario: es del parámetro.
  2 · `approvalPolicy:"never"`. Con la jaula puesta codex no pidió aprobación ni una vez,
      pero dejarle la política del usuario es dejarle una puerta.
  3 · `-c mcp_servers.<name>.enabled=false` POR SERVIDOR, en el argv del proceso. Medido:
      sin eso, `thread/start` pasa de 80 ms a **1.965 ms** y su app-server levanta los MCP
      del usuario (aparecieron errores de Linear en su stderr). `-c 'mcp_servers={}'` NO
      funciona — el apagado probado es por servidor.

⚠️ Y el turno 2 del MISMO proceso hereda la jaula del arranque: verificado por el disco.
Eso es lo que hace que estas tres sean condiciones del BROKER y no de cada turno.
"""
from __future__ import annotations

import os

from typing import Optional

from .adaptador import Adaptador, ResultadoTurno
from .vocabulario import ARRANQUE_S, Capabilities, Session

#: LA JAULA DEL BROKER — apagada por DECISIÓN DEL DUEÑO (2026-08-27).
#:
#: Antes era `"read-only"` fijo en cada `thread/start`. Ahora, por defecto, **no se manda el
#: parámetro**: codex cae a su `~/.codex/config.toml`, que en esta máquina dice
#: `sandbox_mode="workspace-write"`.
#:
#: ⚠️ LO QUE SE PIERDE, MEDIDO POR EL DISCO (paso 2, no estimado):
#:     con `sandbox:"read-only"`   →  0 de 7 rutas escritas
#:     SIN el parámetro            →  2 de 7 rutas escritas en el disco del usuario
#: Y con proceso vivo la config del ARRANQUE gobierna todos los turnos del hilo, así que
#: el turno 2 hereda lo que se decidió en el turno 1.
#:
#: El motivo del cambio es de producto y está medido: con la jaula, Oficina daba el total
#: correcto pero **no podía crear el `.xlsx`** («Sigo bloqueado hasta que esté disponible el
#: runtime de planillas»). El oficio del workspace es producir archivos.
#:
#: Se puede volver a poner sin tocar código: `PUPPET_CLI_BROKER_SANDBOX=read-only`.
#: La huella de config incluye este valor, así que cambiarlo NO reusa un proceso viejo.
_SANDBOX_DEFECTO = (os.environ.get("PUPPET_CLI_BROKER_SANDBOX", "").strip() or None)


class CodexAppServer(Adaptador):
    provider_id = "codex_cli"
    CAPS = Capabilities(
        multiplexa_sesiones=True,       # `thread/start` → N hilos en UN proceso
        streaming_incremental=True,     # `item/agentMessage/delta`
        interrumpible=True,             # `turn/interrupt`
        reporta_usage=True,
        campo_cache_lectura="cached_input_tokens",
        campo_cache_escritura="cache_write_input_tokens",
        jaula_por_turno=False,          # la hereda del `thread/start` — medido
    )

    @staticmethod
    def config(*, modelo: str, mcp_apagados: tuple,
               sandbox: str = _SANDBOX_DEFECTO,
               aprobacion: str = "never", effort: str = "") -> dict:
        return {"cli": "codex", "modelo": modelo,
                "mcp_apagados": sorted(mcp_apagados), "sandbox": sandbox,
                "aprobacion": aprobacion, "effort": effort or ""}

    def argv_de_arranque(self) -> list:
        argv = [self.binario, "app-server"]
        for nombre in (self.cfg.get("mcp_apagados") or []):
            argv += ["-c", f"mcp_servers.{_clave_toml(nombre)}.enabled=false"]
        return argv

    def saludar(self, plazo: float = ARRANQUE_S) -> None:
        self.cano.abrir()
        self._rid = 0
        #: último `tokenUsage.total` visto por hilo, para poder publicar la DIFERENCIA.
        self._totales: dict = {}
        obj, muerto = self._pedir("initialize",
                                  {"clientInfo": {"name": "aleph", "title": "Aleph",
                                                  "version": "0.1.2"}}, plazo)
        if muerto or obj is None or "result" not in obj:
            raise RuntimeError(f"codex: initialize falló ({self.cano.stderr()[-300:]})")
        self.cano.escribir({"jsonrpc": "2.0", "method": "initialized"})
        self.info = obj["result"]

    def _pedir(self, metodo: str, params: dict, plazo: float, on_linea=None):
        self._rid += 1
        rid = self._rid
        self.cano.escribir({"jsonrpc": "2.0", "id": rid, "method": metodo, "params": params})
        return self._esperar(
            lambda o: o.get("id") == rid and ("result" in o or "error" in o),
            plazo, on_linea=on_linea)

    def abrir_sesion(self, ses: Session, plazo: float = ARRANQUE_S) -> None:
        params = {
            "cwd": self.cwd,
            "ephemeral": True,
            # ── LAS TRES CONDICIONES, acá y explícitas ────────────────────────────
            # DECISIÓN DEL DUEÑO (2026-08-27): sin jaula por defecto. Ver `_SANDBOX_DEFECTO`.
            # `None` ⇒ NO se manda el parámetro y codex cae a su `~/.codex/config.toml`.
            **({"sandbox": self.cfg["sandbox"]} if self.cfg.get("sandbox") else {}),
            "approvalPolicy": self.cfg.get("aprobacion") or "never",
        }
        if self.cfg.get("modelo"):
            params["model"] = self.cfg["modelo"]
        obj, muerto = self._pedir("thread/start", params, plazo)
        if muerto or obj is None or "result" not in obj:
            # ⚠️ EL MOTIVO ESTÁ EN EL SOBRE JSON-RPC, NO EN stderr. MEDIDO el 2026-08-26
            # contra Oficina: el broker caía con `turno_exploto` y el mensaje decía
            # literalmente «thread/start falló ()» — paréntesis VACÍO — porque sólo miraba
            # `stderr`, y un `error` de JSON-RPC no escribe en stderr: viaja en `obj["error"]`.
            # Dos turnos seguidos cayeron al respaldo sin que nadie pudiera decir por qué.
            # Se dicen las TRES cosas que distinguen los casos: si el proceso murió, qué
            # trajo el sobre, y qué hay en stderr.
            _err = (obj or {}).get("error")
            raise RuntimeError(
                "codex: thread/start falló · "
                + (f"proceso muerto · " if muerto else "")
                + (f"error={_err} · " if _err else ("sin `result` ni `error` · " if obj else "sin respuesta · "))
                + f"stderr={self.cano.stderr()[-200:]!r}")
        ses.id_remoto = ((obj["result"].get("thread") or {}).get("id"))

    def turno(self, ses: Session, prompt: str, on_evento=None,
              plazo: float = 180.0) -> ResultadoTurno:
        if not ses.id_remoto:
            self.abrir_sesion(ses)
        estado = {"texto": "", "uso": {}, "err": [], "exec": 0, "fin": False,
                  "modelo": None, "tokens": {}}

        def _mirar(o: dict) -> None:
            m = o.get("method") or ""
            p = o.get("params") or {}
            it = p.get("item") or {}
            if m == "item/agentMessage/delta":
                d = p.get("delta") or p.get("chunk") or ""
                if d and on_evento:
                    on_evento("texto", str(d))
            elif m == "item/reasoning/textDelta" or m == "item/reasoning/summaryTextDelta":
                d = p.get("delta") or p.get("chunk") or ""
                if d and on_evento:
                    on_evento("pensando", str(d))
            elif m == "item/completed":
                if it.get("type") == "agentMessage" and it.get("text"):
                    estado["texto"] = str(it["text"])
                # CUALQUIER ejecución del CLI por su cuenta viola el contrato de pureza.
                # Misma lista que `codex_cli._EXEC_EVENT_RE`, con los nombres de app-server.
                if it.get("type") in ("commandExecution", "fileChange", "mcpToolCall",
                                      "webSearch", "patchApply"):
                    estado["exec"] += 1
            elif m == "thread/tokenUsage/updated":
                # 🔴 ACÁ VIENE EL USAGE DE CODEX, y NO en `turn/completed`.
                # ⚠️ CORRIGE AL PASO 1, que declaró «los `turn/completed` de app-server
                # llegan con `usage: {}`» y lo dio por ausencia del CLI. El `usage` de ese
                # evento sí viene vacío — pero los tokens viajan en ESTA notificación
                # aparte, con `tokenUsage.total`. Sin leerla, el broker dejaba el ledger de
                # codex CIEGO (medido: `prompt=None cache_r=None` por el broker contra
                # `prompt=12.586 cache_r=12.032` por el camino de hoy), que es exactamente
                # la clase de optimización que hace que algo deje de decirse.
                tot = ((p.get("tokenUsage") or {}).get("total")) or {}
                if tot:
                    estado["tokens"] = dict(tot)
            elif m == "turn/completed":
                estado["fin"] = True
                u = p.get("usage") or (p.get("turn") or {}).get("usage") or {}
                if u:
                    estado["uso"] = dict(u)
            elif m == "turn/failed":
                estado["fin"] = True
                estado["err"].append(str((p.get("error") or {}).get("message") or "")[:300])

        obj, muerto = self._pedir(
            "turn/start", {"threadId": ses.id_remoto,
                           "input": [{"type": "text", "text": prompt}]},
            plazo, on_linea=_mirar)
        if muerto:
            return ResultadoTurno(ok=False, proceso_perdido=True,
                                  error_detalle="el app-server de codex cerró a mitad del turno")
        # ⚠️ `turn/start` DEVUELVE UN ACK, no el turno. El E0 ya se equivocó una vez acá y
        # reportó «0 deltas» porque midió el ACK. El turno termina por NOTIFICACIÓN.
        # ── CORTAR EN LA PRIMERA ACCIÓN, NO AL FINAL ────────────────────────────────
        # MEDIDO en un turno real de Oficina el 2026-08-26:
        #
        #   ✗ codex_cli model_error (65,0 s): Codex ejecutó 10 acción(es) por su cuenta
        #                                      — resultado descartado por seguridad
        #   → codex_cli (7381 chars)          ← el MISMO prompt, de nuevo
        #   ✓ codex_cli (11,1 s)              ← y esta vez salió bien
        #
        # El guard de pureza (`base.py:1470`) corre AL FINAL: se esperaban los 65 s enteros
        # y recién ahí se tiraba el resultado. Pero `estado["exec"]` ya se incrementa en el
        # instante de la PRIMERA acción — el dato estaba, y nadie lo miraba hasta el final.
        # 65 s de un turno de 76 s eran una generación condenada desde su primer segundo.
        #
        # Y `turn/interrupt` YA ESTABA DECLARADO (`CAPS.interrumpible=True`, documentado en
        # la cabecera de este archivo) **y no lo llamaba nadie**. El mecanismo existía y le
        # faltaba el llamador — la duodécima vez en esta obra.
        #
        # Se corta, se interrumpe el turno para que el proceso del pool quede SANO (sin un
        # turno colgado que rompa al siguiente), y se devuelve exactamente lo que se habría
        # devuelto al final: `ok=True` con `exec_events`. Así el guard de arriba produce su
        # mensaje de siempre y NO se inventa una causa nueva.
        # ⚠️ DETRÁS DE UNA PERILLA, Y APAGADA POR DEFECTO. El ahorro está medido
        # (65,0 s → 12,1 s en la generación descartada, y corta con 1 acción en vez de
        # dejar pasar 10), pero en la ÚNICA corrida que tengo con el corte puesto **la
        # entrega salió peor**:
        #
        #   sin corte:  «El total es 11.100. Sigo bloqueado para crear el .xlsx…»
        #   con corte:  «¿Podés habilitar acceso de escritura y @oai/artifact-tool…»  ← sin número
        #
        # No es una fuga —la respuesta es nueva y coherente, no el texto del turno
        # interrumpido— pero con N=1 de cada lado **no puedo afirmar que el corte no sea la
        # causa**. Y la vara que decide no es el tiempo: es la entrega. Un turno más rápido
        # con peor respuesta no es una optimización.
        #
        # Queda cableado y medible con `PUPPET_CLI_BROKER_CORTE_EXEC=on`, para que la
        # próxima pasada lo cierre con N≥3 por brazo comparando ENTREGAS, no tiempos.
        _cortar_en_exec = (os.environ.get("PUPPET_CLI_BROKER_CORTE_EXEC", "").strip().lower()
                           in ("1", "on", "true", "si", "sí"))
        fin = _hasta(self, plazo, _mirar,
                     lambda: estado["fin"] or (_cortar_en_exec and estado["exec"] > 0))
        if _cortar_en_exec and estado["exec"] > 0 and not estado["fin"]:
            try:
                self._pedir("turn/interrupt", {"threadId": ses.id_remoto}, 5.0)
            except Exception:                               # noqa: BLE001 — interrumpir es
                pass                                        # best-effort; el guard igual corta
            return ResultadoTurno(
                ok=True, texto=estado["texto"],
                model_final=(self.cfg.get("modelo") or None),
                usage_bruto=dict(estado["uso"]),
                exec_events=estado["exec"])
        if fin == "muerto":
            return ResultadoTurno(ok=False, proceso_perdido=True,
                                  error_detalle="el app-server de codex murió esperando el turno")
        if fin == "plazo":
            return ResultadoTurno(ok=False, proceso_perdido=True,
                                  error_detalle=f"codex no cerró el turno en {plazo:.0f} s")
        if estado["err"]:
            return ResultadoTurno(ok=False, error_detalle=" · ".join(estado["err"])[:300],
                                  exec_events=estado["exec"])
        # `turn/completed.usage` primero (por si un día lo llena), y si no el acumulado de
        # `thread/tokenUsage/updated`, traducido a los nombres que `base.usage_del_cli`
        # conoce. La traducción es de NOMBRES, no de números.
        u = dict(estado["uso"])
        if not u and estado["tokens"]:
            # ⚠️ `thread/tokenUsage.total` ES ACUMULADO DEL HILO, no del turno. Medido:
            # por el broker salía 15.074 → 31.916 → 48.857 en tres turnos, contra ~12.5k
            # por turno en el camino de hoy. Publicar el acumulado en el campo que el
            # ledger lee como «este turno» sería MENTIR un número, no reportarlo: la
            # tarjeta de costo del turno 3 diría 48.857 tokens de prompt.
            # Se reporta la DIFERENCIA contra el total anterior de ESTE hilo.
            t = estado["tokens"]
            prev = self._totales.get(ses.id_remoto or "", {})
            def _d(clave):
                v = t.get(clave)
                if v is None:
                    return None
                return max(0, int(v) - int(prev.get(clave) or 0))
            u = {"input_tokens": _d("inputTokens"),
                 "output_tokens": _d("outputTokens"),
                 "cached_input_tokens": _d("cachedInputTokens"),
                 "reasoning_output_tokens": _d("reasoningOutputTokens")}
            u = {k: v for k, v in u.items() if v is not None}
            self._totales[ses.id_remoto or ""] = dict(t)
        return ResultadoTurno(
            ok=True, texto=estado["texto"],
            model_final=(self.cfg.get("modelo") or None),
            usage_bruto=dict(u),          # crudo: `usage_del_cli` conoce sus nombres
            cache_lectura=u.get("cached_input_tokens"),
            cache_escritura=u.get("cache_write_input_tokens"),
            razonamiento=u.get("reasoning_output_tokens"),
            # ⚠️ MEDIDO Y DECLARADO EN EL PASO 1: los `turn/completed` de app-server llegan
            # con `usage: {}`. `tokens_medidos=False` es «no hay dato», que NO es cero.
            tokens_medidos=bool(u),
            exec_events=estado["exec"],
            meta={"usage_de": ("turn/completed" if estado["uso"]
                               else ("thread/tokenUsage" if estado["tokens"] else "ninguno"))})


def _hasta(ad: Adaptador, plazo: float, on_linea, listo) -> str:
    """Sigue leyendo hasta que `listo()` diga que sí. `'ok' | 'muerto' | 'plazo'`."""
    if listo():
        return "ok"
    obj, muerto = ad._esperar(lambda _o: listo(), plazo, on_linea=on_linea)
    if muerto:
        return "muerto"
    return "ok" if listo() else "plazo"


def _clave_toml(nombre: str) -> str:
    """Nombre de servidor MCP como CLAVE TOML.

    ⚠️ SE IMPORTA, NO SE COPIA. `codex_cli._toml_key` ya resuelve esto para el camino de
    hoy, y dos funciones que tienen que dar el MISMO string son una función que algún día
    no lo va a dar — y el día que difieran, el apagado de MCP deja de matchear y el
    `thread/start` se va de 80 ms a 1.965 ms sin que nadie vea por qué.
    """
    from ..codex_cli import _toml_key
    return _toml_key(str(nombre))


__all__ = ["CodexAppServer"]
