#!/usr/bin/env python3
"""
INTEGRACIÓN — cablea las 4 piezas al runtime del assembler, SIN tocar
assembler.py (aditivo, reversible).

`GatedRegistry` envuelve el `ToolRegistry` del assembler:

    call(tool, args)
      -> ApprovalGate.evaluate(server, tool, args)
         · EXECUTE   -> ejecuta la tool real (super().call)
         · NEEDS_OK  -> NO ejecuta; devuelve al modelo el payload del gate y
                        delega la recolección del OK a un callback de aprobación
                        (en producción = el botón del workshop / Telegram).
         · BLOCKED   -> NO ejecuta; devuelve el motivo en lenguaje claro.
      -> el resultado de la tool pasa por OutputScrubber antes de volver al modelo
         (red de seguridad B1: nada con forma de secreto vuelve al contexto).

El vault inyecta las keys al ARRANCAR los MCP servers (env del subprocess), nunca
acá. El sandbox se aplica a las tools de ejecución de código (guard_code).

PARAMETRIZABLE: todo el comportamiento viene de la matriz + config; este archivo
es genérico.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Callable, Optional

_GATES_DIR = Path(__file__).resolve().parent


def _load(name: str):
    import aleph_paths
    return aleph_paths.load_module_by_path(f"puppet_gates_{name}", _GATES_DIR / f"{name}.py")


_ag = _load("approval_gate")
_sb = _load("scrubber")
_sx = _load("sandbox")

ApprovalGate = _ag.ApprovalGate
GateDecision = _ag.GateDecision
OutputScrubber = _sb.OutputScrubber
SandboxGuard = _sx.SandboxGuard
SandboxError = _sx.SandboxError


# El server dueño de cada tool lo sabe el ToolRegistry; lo exponemos por nombre.
def _server_of(registry, tool_name: str) -> str:
    srv = getattr(registry, "_servers", {}).get(tool_name)
    return getattr(srv, "name", "*") if srv else "*"


class GateBlocked(Exception):
    """La acción fue frenada por el gate; el motivo es para mostrar al usuario."""


def make_gated_registry(base_registry_cls):
    """
    Fábrica: devuelve una subclase de `base_registry_cls` (el ToolRegistry del
    assembler) con las 4 piezas montadas. Recibe la clase para no importar el
    assembler acá (lo hace quien integra).
    """

    class GatedRegistry(base_registry_cls):
        def __init__(self, servers, tool_filters, *,
                     gate: ApprovalGate,
                     scrubber: OutputScrubber,
                     sandbox: Optional[SandboxGuard] = None,
                     approval_callback: Optional[Callable[[dict], bool]] = None,
                     code_tools: Optional[list] = None):
            super().__init__(servers, tool_filters)
            self._gate = gate
            self._scrubber = scrubber
            self._sandbox = sandbox
            # approval_callback(payload)->bool: en producción recolecta el OK del
            # usuario (botón del workshop / Telegram). En tests, se inyecta un
            # stub. Si es None -> el gate NUNCA auto-aprueba (seguro por defecto).
            self._approval_callback = approval_callback
            self._code_tools = set(code_tools or ["execute_code", "stata_run", "run_code", "execute_cell"])
            # bitácora para los tests/UX: qué frenó, qué dejó pasar.
            self.gate_log: list = []

        def call(self, tool_name: str, arguments: dict) -> str:
            server = _server_of(self, tool_name)

            # 0) sandbox: si es una tool de ejecución de código, validá ANTES.
            if tool_name in self._code_tools and self._sandbox is not None:
                code = arguments.get("code") or arguments.get("source") or ""
                try:
                    self._sandbox.guard_code(code)
                except SandboxError as e:
                    self.gate_log.append({"tool": tool_name, "decision": "sandbox-blocked", "msg": str(e)})
                    return f"[bloqueado por la caja de seguridad] {e}"

            # 1) gate de aprobación
            decision = self._gate.evaluate(server, tool_name, arguments)

            if decision.action == GateDecision.BLOCKED:
                motivo = decision.payload.get("motivo", "Acción no permitida.")
                self.gate_log.append({"tool": tool_name, "decision": "blocked", "level": decision.level, "payload": decision.payload})
                return f"[gate: prohibido] {motivo}"

            if decision.action == GateDecision.NEEDS_OK:
                self.gate_log.append({"tool": tool_name, "decision": "needs_ok", "level": decision.level, "payload": decision.payload})
                approved = False
                if self._approval_callback is not None:
                    approved = bool(self._approval_callback(decision.payload))
                if not approved:
                    # SIN OK -> NO se ejecuta. Devolvemos el contrato de UX al modelo
                    # para que se lo muestre al usuario y espere.
                    p = decision.payload
                    return (
                        "[gate: requiere tu OK — NO ejecutado]\n"
                        f"Qué va a hacer: {p['que_va_a_hacer']}\n"
                        f"Dónde afecta: {p['donde_afecta']}\n"
                        f"Vista previa: {p['vista_previa']}\n"
                        f"({p['leyenda']}) — esperando que toques «{p['boton_ok']}»."
                    )
                # OK recibido -> registralo (para confirma-una-vez) y ejecutá.
                self._gate.grant_ok(server, tool_name)

            # 2) ejecutar la tool real
            raw = super().call(tool_name, arguments)

            # 3) scrubber sobre el resultado antes de devolverlo al modelo
            report = self._scrubber.scrub(raw)
            if report.blocked:
                self.gate_log.append({"tool": tool_name, "decision": "scrubbed-result", "findings": report.findings})
            return report.clean_text

    return GatedRegistry
