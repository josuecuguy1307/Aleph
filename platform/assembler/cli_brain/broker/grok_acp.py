#!/usr/bin/env python3
"""grok_acp.py — Grok como proceso vivo por ACP (`grok agent stdio`).

MEDIDO (E0 · 2026-08-22 y paso 1 · 2026-08-24, grok 1.0.5):
    initialize 0,509-0,960 s · session/new 0,790-1,426 s · turno 2 en 1,04-1,72 s
    y el sobrecosto del PROCESO es ~24 ms sobre una API de 1.696 ms

🔴 LA BANDERA QUE SE ARRASTRA — Y QUE CUESTA 11k TOKENS POR TURNO:
`grok agent stdio` **a secas NO aplica el perfil `aleph-zero`**. Medido: el preámbulo sube
de 21.695 a **32.884 tokens**. Con `--agent-profile <ruta>/aleph-zero.md` vuelve a 22.029 y
el turno 2 baja a 1.044 ms. El perfil es lo que le vacía la allowlist de tools
(`tools: []`, `mcpInheritance: none`), o sea que sin él **además** se pierde la pureza del
wrapper — no es sólo caro, es otra cosa.

⚠️ Y el perfil va en el ARRANQUE, no por turno: con proceso vivo, lo que se configuró al
arrancarlo gobierna todos los turnos. Por eso está en la huella de config.
"""
from __future__ import annotations

import os
from typing import Optional

from .adaptador import Adaptador, ResultadoTurno
from .vocabulario import ARRANQUE_S, Capabilities, Session


class GrokACP(Adaptador):
    provider_id = "grok_cli"
    CAPS = Capabilities(
        multiplexa_sesiones=True,       # `session/new` → N charlas en UN proceso
        streaming_incremental=True,     # `agent_message_chunk` / `agent_thought_chunk`
        interrumpible=False,            # ACP tiene `session/cancel`; NO lo medimos → no se promete
        reporta_usage=True,
        campo_cache_lectura="cache_read_input_tokens",
        campo_cache_escritura="cache_creation_input_tokens",
        jaula_por_turno=False,          # el perfil se aplica al arrancar
    )

    @staticmethod
    def config(*, modelo: str, perfil: str, effort: str = "") -> dict:
        """Lo que entra en la HUELLA. Si algo de esto cambia, el proceso tiene que ser otro."""
        return {"cli": "grok", "modelo": modelo, "perfil": perfil, "effort": effort or ""}

    def argv_de_arranque(self) -> list:
        argv = [self.binario, "agent"]
        perfil = (self.cfg.get("perfil") or "").strip()
        if perfil:
            argv += ["--agent-profile", perfil]     # ← sin esto, 21,7k → 32,9k tokens
        modelo = (self.cfg.get("modelo") or "").strip()
        if modelo:
            argv += ["-m", modelo]
        eff = (self.cfg.get("effort") or "").strip().lower()
        if eff in ("low", "medium", "high", "max"):
            argv += ["--reasoning-effort", eff]
        argv.append("stdio")
        return argv

    def saludar(self, plazo: float = ARRANQUE_S) -> None:
        self.cano.abrir()
        self._rid = 0
        obj, muerto = self._pedir("initialize",
                                  {"protocolVersion": 1,
                                   "clientCapabilities": {"fs": {"readTextFile": False,
                                                                 "writeTextFile": False}}},
                                  plazo)
        if muerto or obj is None or "result" not in obj:
            raise RuntimeError(f"grok: initialize falló ({self.cano.stderr()[-300:]})")
        self.info = obj["result"]

    def _pedir(self, metodo: str, params: dict, plazo: float, on_linea=None):
        self._rid += 1
        rid = self._rid
        self.cano.escribir({"jsonrpc": "2.0", "id": rid, "method": metodo, "params": params})
        return self._esperar(
            lambda o: o.get("id") == rid and ("result" in o or "error" in o),
            plazo, on_linea=on_linea)

    def abrir_sesion(self, ses: Session, plazo: float = ARRANQUE_S) -> None:
        # `mcpServers: []` explícito: el perfil ya dice `mcpInheritance: none`, y las dos
        # cosas juntas son la misma promesa por dos caminos. Medido en el paso 1:
        # `_x.ai/mcp_initialized → {mcpToolCount: 0, elapsedMs: 0}`.
        obj, muerto = self._pedir("session/new", {"cwd": self.cwd, "mcpServers": []}, plazo)
        if muerto or obj is None or "result" not in obj:
            raise RuntimeError(f"grok: session/new falló ({self.cano.stderr()[-300:]})")
        ses.id_remoto = obj["result"].get("sessionId")

    def turno(self, ses: Session, prompt: str, on_evento=None,
              plazo: float = 180.0) -> ResultadoTurno:
        if not ses.id_remoto:
            self.abrir_sesion(ses)
        uso = {}
        tools_anunciadas: Optional[list] = None
        eventos_tool = 0
        # ⚠️ EL TEXTO SE ACUMULA DE LOS CHUNKS, no se saca del `result`. Medido: el
        # `session/prompt` de ACP responde `{"stopReason": …}` **sin el texto**, así que
        # leerlo de ahí devolvía la respuesta VACÍA — el turno más rápido del mundo con la
        # entrega rota. Es el mismo acumulador que `grok_cli` ya tiene en su `_tls.text`.
        partes: list = []

        def _mirar(o: dict) -> None:
            nonlocal uso, tools_anunciadas, eventos_tool
            p = o.get("params") or {}
            u = p.get("update") or {}
            tipo = u.get("sessionUpdate")
            if tipo == "agent_message_chunk":
                t = ((u.get("content") or {}).get("text")) or ""
                if t:
                    partes.append(t)
                    if on_evento:
                        on_evento("texto", t)
            elif tipo == "agent_thought_chunk" and on_evento:
                t = ((u.get("content") or {}).get("text")) or ""
                if t:
                    on_evento("pensando", t)
            elif tipo == "available_commands_update":
                tools_anunciadas = list(u.get("availableTools") or u.get("tools") or [])
            elif tipo in ("tool_call", "tool_call_update"):
                eventos_tool += 1
            elif tipo in ("turn_completed", "response_completed"):
                uso = dict(u.get("usage") or {})

        obj, muerto = self._pedir(
            "session/prompt",
            {"sessionId": ses.id_remoto, "prompt": [{"type": "text", "text": prompt}]},
            plazo, on_linea=_mirar)
        if muerto:
            return ResultadoTurno(ok=False, proceso_perdido=True,
                                  error_detalle="el proceso de grok cerró a mitad del turno")
        if obj is None:
            return ResultadoTurno(ok=False, proceso_perdido=True,
                                  error_detalle=f"grok no contestó en {plazo:.0f} s")
        if "error" in obj:
            return ResultadoTurno(ok=False,
                                  error_detalle=str(obj["error"])[:300])
        texto = "".join(partes)
        if not texto:
            # respaldo, por si una versión futura sí lo mandara en el resultado
            for c in ((obj.get("result") or {}).get("content") or []):
                if isinstance(c, dict) and c.get("text"):
                    texto += c["text"]
            texto = texto or str((obj.get("result") or {}).get("text") or "")
        # `inputTokens`/`input_tokens`: los DOS nombres viven en el stream de grok
        # (`turn_completed` usa camelCase, `response_completed` snake_case). Se normaliza a
        # snake_case porque es el que `base.usage_del_cli` conoce — y ESA es la única
        # traducción que hacemos: los nombres de CACHÉ se le dejan a la casa.
        def _t(*nombres):
            for n in nombres:
                if uso.get(n) is not None:
                    return int(uso[n])
            return None

        crudo = dict(uso)
        for camel, snake in (("inputTokens", "input_tokens"),
                             ("outputTokens", "output_tokens"),
                             ("cachedReadTokens", "cache_read_input_tokens"),
                             ("cacheCreationTokens", "cache_creation_input_tokens"),
                             ("reasoningTokens", "reasoning_tokens")):
            if crudo.get(snake) is None and uso.get(camel) is not None:
                crudo[snake] = uso[camel]
        return ResultadoTurno(
            ok=True, texto=texto,
            model_final=(self.cfg.get("modelo") or None),
            usage_bruto=crudo,
            cache_lectura=_t("cachedReadTokens", "cache_read_input_tokens"),
            cache_escritura=_t("cacheCreationTokens", "cache_creation_input_tokens"),
            razonamiento=_t("reasoningTokens", "reasoning_tokens"),
            tokens_medidos=bool(uso),
            exec_events=eventos_tool,
            meta={"advertised_tools": tools_anunciadas,
                  "api_ms": uso.get("apiDurationMs")})


__all__ = ["GrokACP"]
