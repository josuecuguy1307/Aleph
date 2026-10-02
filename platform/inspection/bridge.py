"""
bridge.py — FASE 2: conecta el motor de inspección al Cuarto, EN VIVO.

Emite el ciclo de vida del recon como eventos de un SPACE, reusando el event-store
del org (platform/flywheel/events_replay.EventLog): append atómico (lock+fsync) a
`product/backend/data/espacios/<space_id>/events.jsonl`. El backend YA corriendo en
:8080 tailea ese archivo cada 250ms y lo emite por SSE (/v1/spaces/{id}/stream) —
así NO hay que reiniciar :8080: un append desde este proceso aparece en el stream
vivo. El Cuarto (Pixi) abre un EventSource y lo anima.

Eventos (contrato de la directiva):
  software.detectado → inspeccion.analizando → accion.observada → tool.sintetizada
y un `closed` final para cerrar el stream limpio.

Estado en memoria + push del backend; nada de localStorage.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]    # platform/inspection/bridge.py → puppet-ai/
_EVENTS_PY = _REPO_ROOT / "platform" / "flywheel" / "events_replay.py"
def _dir_datos(nombre: str) -> Path:
    """`<data_root>/<nombre>` — el dir de datos del USUARIO, no el árbol.
    ⚠️ EL BUNDLE ES SÓLO LECTURA (CLAUDE.md · clase ya pagada en synth_belts, el pin
    del sello y la caché del resolver). Bajo PyInstaller `_REPO_ROOT` cae dentro de
    `_MEIPASS`, el temp que se borra al cerrar: lo que se escriba ahí NO existe en el
    arranque siguiente. Todo lo que se ESCRIBE va al dir de datos del usuario.
    Cae al árbol sólo si `aleph_paths` no se puede importar (dev suelto): en frozen siempre
    resuelve, porque `aleph_paths` viaja en el bundle.
    """
    try:
        import aleph_paths
        return aleph_paths.data_root() / nombre
    except Exception:                    # noqa: BLE001
        return _REPO_ROOT / "product" / "backend" / "data" / nombre

_DEFAULT_ESPACIOS = _dir_datos("espacios")

# bootstrap del paquete inspection
_PLATFORM_DIR = _REPO_ROOT / "platform"
if str(_PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_DIR))

# [Casa 2 · Fase 4 · carve] observe/* y session.cloud son FORGE (no viajan). Import LAZY
# dentro de run_recon_to_space (abajo): SpaceEmitter —lo único que usa el curado/
# resolve_router— NO los necesita. `from __future__ import annotations` mantiene la anotación
# `Optional[CloudSession]` como string (no se evalúa al importar). Ver inspection/zones.py.


def _load_event_log_cls():
    spec = importlib.util.spec_from_file_location("puppet_events_replay_inspection", _EVENTS_PY)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar el event-store en {_EVENTS_PY}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.EventLog


class SpaceEmitter:
    """Emite eventos del recon al events.jsonl de un space (lo crea si no existe)."""

    def __init__(self, space_id: str, espacios_dir: str | Path | None = None, *,
                 owner_id: Optional[str] = None, public: bool = False,
                 claim: bool = False):
        from inspection.space_access import claim_space, space_dir, validate_space_id
        self.space_id = validate_space_id(space_id)
        base = Path(espacios_dir) if espacios_dir else _DEFAULT_ESPACIOS
        if claim:
            claim_space(base, self.space_id, owner_id=owner_id, public=public)
        self.events_path = space_dir(base, self.space_id, create=True) / "events.jsonl"
        EventLog = _load_event_log_cls()
        self._log = EventLog(self.events_path)   # auto-crea dir + archivo

    def emit(self, etype: str, **payload) -> None:
        # Campos al TOP-LEVEL (misma convención que el emitter del run): el frontend
        # hace JSON.parse(data) y lee e.type/e.label/e.method/... directo.
        try:
            self._log.append({"type": etype, "space_id": self.space_id, **payload})
        except Exception:
            pass  # un fallo emitiendo NUNCA tumba el recon (mismo criterio que el run)

    def software_detectado(self, *, label: str, host: str = "", url: str = "", title: str = "") -> None:
        self.emit("software.detectado", label=label, host=host, url=url, title=title)

    def inspeccion_analizando(self, *, requests: Optional[int] = None) -> None:
        self.emit("inspeccion.analizando", requests=requests)

    def accion_observada(self, *, method: Optional[str], path: Optional[str], fields: list[str]) -> None:
        self.emit("accion.observada", method=method, path=path, fields=fields)

    def tool_sintetizada(self, *, label: str, category: str, fields: list[Any]) -> None:
        self.emit("tool.sintetizada", label=label, category=category, fields=fields)

    # ── FASE 5: el cierre del loop usuario→agente (tipos recon, owner §4.4) ──────
    def tool_equipada(self, *, label: str, belt_ref: str, server: str, tool: str,
                      puppet_id: Optional[str], belt_refs: list[str], version: int = 1) -> None:
        """La tool sintetizada quedó REGISTRADA en el puppet (recipe.belt_refs)."""
        self.emit("tool.equipada", label=label, belt_ref=belt_ref, server=server,
                  tool=tool, puppet_id=puppet_id, belt_refs=belt_refs, version=version)

    def gate_held(self, *, server: str, tool: str, args: dict, level: str = "write",
                  reason: str = "") -> None:
        """El candado: la tool toca el mundo → frena y pide OK (no ejecutó)."""
        self.emit("gate.held", server=server, tool=tool, args=args, level=level, reason=reason)

    def tool_call(self, *, server: str, tool: str, args: dict, dry_run: bool) -> None:
        self.emit("tool_call", server=server, tool=tool, args=args, dry_run=dry_run)

    def gate_approved(self, *, server: str, tool: str, approval_id: Optional[str] = None) -> None:
        self.emit("gate.approved", server=server, tool=tool, approval_id=approval_id)

    def gate_rejected(self, *, server: str, tool: str, reason: str = "") -> None:
        self.emit("gate.rejected", server=server, tool=tool, reason=reason)

    def eco(self, *, server: str, tool: str, status: Optional[int], echo: Any = None,
            ok: bool = False, refused: bool = False, reason: Optional[str] = None) -> None:
        """La línea de retorno: tool corrió → el mundo respondió (el agente re-decide).
        `refused`/`reason`: la capa de safety (T9) puede FRENAR el replay (p.ej. target loopback/
        interno: política pública estricta de escritura). El eco entonces es honesto-refused, no silencioso."""
        self.emit("eco", server=server, tool=tool, status=status, echo=echo, ok=ok,
                  refused=refused, reason=reason)

    def cost(self, *, user_id: Optional[str], run_id: Optional[str], tool: str,
             tokens: int = 0, usd: float = 0.0, model: Optional[str] = None) -> None:
        """COST-EVENT (§4.6): costo por call. Recon/replay determinista → ~0 tokens."""
        self.emit("cost", user_id=user_id, run_id=run_id, tool=tool, model=model,
                  tokens=tokens, usd=usd)

    def drift(self, *, belt_ref: str, server: str, tool: str, healthy: bool,
              detail: dict) -> None:
        """Health-check de drift: el software cambió bajo la tool sintetizada."""
        self.emit("tool.drift", belt_ref=belt_ref, server=server, tool=tool,
                  healthy=healthy, detail=detail)

    def error(self, *, stage: str, detail: str) -> None:
        self.emit("inspeccion.error", stage=stage, detail=detail)

    def close(self) -> None:
        self.emit("closed")


Beat = Optional[Callable[[str], Awaitable[None]]]


async def run_recon_to_space(
    *,
    space_id: str,
    target_url: str,
    intent: str,
    demo=None,
    espacios_dir: str | Path | None = None,
    session: Optional[CloudSession] = None,
    on_beat: Beat = None,
    settle_ms: int = 2000,
    pace_ms: int = 1100,
    emitter: Optional[SpaceEmitter] = None,
    close: bool = True,
    subject: Optional[str] = None,
    allow_local_fixture: bool = False,
):
    """
    Corre el recon completo y emite sus 4 beats al space, con pacing para que la
    animación del Cuarto sea legible. Devuelve (ObservedAction, capability dict).

    `emitter`/`close`: por defecto crea su propio emitter y cierra el stream al final.
    El runner del loop completo (inspect_run) pasa su PROPIO emitter y close=False para
    seguir emitiendo (tool.equipada → gate → eco) sobre el mismo stream antes de cerrar.
    """
    from inspection.observe.correlate import correlate               # [carve] FORGE, lazy
    from inspection.observe.recorder import record_demonstration     # [carve] FORGE, lazy
    from inspection.observe.synthesize import synthesize_capability  # [carve] FORGE, lazy
    from inspection.session.cloud import CloudSession                # [carve] FORGE, lazy
    # [T9-safety] guard ANTI-SSRF + rate-limit ANTES de tocar la red. El target externo
    # no puede ser metadata de cloud / loopback / LAN interna. El fixture benigno local
    # pasa allow_local_fixture=True (demo_live). Si frena, NO se levanta browser.
    try:
        from safety.guards import guard_recon, SafetyBlocked   # additivo, encima
        try:
            target_url = guard_recon(target_url, subject=subject or space_id,
                                     allow_local_fixture=allow_local_fixture)
        except SafetyBlocked as _sb:
            _e = SpaceEmitter(space_id, espacios_dir)
            _e.emit("software.detectado", label="⛔ target rechazado por safety",
                    host="", url=target_url, title=str(_sb))
            _e.close()
            raise
    except ImportError:
        pass  # capa de safety ausente (build incompleto): el core sigue sin guard

    # T4: respetar el emitter pasado por inspect_run (close=False para seguir el stream)
    emitter = emitter or SpaceEmitter(space_id, espacios_dir)
    own_session = session is None
    session = session or CloudSession(headless=True)
    ctx = await session.provide_context()

    async def _beat(name: str) -> None:
        if on_beat is not None:
            await on_beat(name)
        if pace_ms:
            await asyncio.sleep(pace_ms / 1000)

    async def on_phase(phase: str, info: dict) -> None:
        if phase == "detectado":
            emitter.software_detectado(
                label=info.get("label") or info.get("host") or "Software",
                host=info.get("host", ""), url=info.get("url", ""), title=info.get("title", ""),
            )
        elif phase == "analizando":
            emitter.inspeccion_analizando(requests=info.get("requests"))
        await _beat(phase)

    try:
        bundle = await record_demonstration(
            ctx, intent=intent, target_url=target_url, demo=demo,
            settle_ms=settle_ms, on_event=on_phase,
        )
        action = correlate(bundle)

        p = action.primary_request
        emitter.accion_observada(
            method=p.method if p else None,
            path=p.path if p else None,
            fields=[f.name for f in action.field_schema if f.variable],
        )
        await _beat("observada")

        cap = synthesize_capability(action)
        emitter.tool_sintetizada(label=cap["label"], category=cap["category"], fields=cap["params"])
        await _beat("sintetizada")

        if close:
            emitter.close()
        return action, cap
    finally:
        await ctx.aclose()
        if own_session:
            pass  # CloudSession cleanup ya corre en ctx.aclose()
