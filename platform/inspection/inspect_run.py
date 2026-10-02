#!/usr/bin/env python3
"""
inspect_run.py — FASE 5: `/v1/inspect` COMPLETO. Cierra el loop usuario→agente.

El runner del producto: lo dispara `POST /v1/inspect` (subproceso aislado, fuera del
event-loop de uvicorn) y hace, EMITIENDO cada beat al space (que el Cuarto anima en vivo):

  recon  → software.detectado · inspeccion.analizando · accion.observada · tool.sintetizada
  forja  → escribe el belt sintetizado (durable, por-usuario) + lo SELLA con su firma de drift
  equipa → lo REGISTRA en la receta del puppet (recipe.belt.belt_refs)  → tool.equipada
  corre  → EJECUCIÓN GATEADA de la tool: write → gate.held (sin OK no toca el mundo);
           con OK (auto_approve / aprobación humana) → corre de verdad y emite el ECO real
  costo  → COST-EVENT por call (§4.6)

A diferencia de demo_live (que sólo animaba el recon), esto deja una tool EQUIPADA en el
puppet del usuario y demuestra su ejecución gateada end-to-end. El target hoy es el
SHOWCASE benigno (BenignTestApp); el path headed/local-attach contra el software real del
usuario es el próximo (misma interfaz).

Uso:  python platform/inspection/inspect_run.py <space_id> [puppet_id|-] [user_id|-] [approve]
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import select
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional


def _arm_hard_deadline() -> None:
    """An independent watchdog survives both worker and blocked-interpreter crashes."""
    output_limit = int(os.environ.get("ALEPH_INSPECT_OUTPUT_LIMIT_BYTES", "0"))
    if output_limit:
        import resource
        if output_limit < 1 or output_limit > 8 * 1024 * 1024:
            raise RuntimeError("invalid inspection output limit")
        resource.setrlimit(resource.RLIMIT_FSIZE, (output_limit, output_limit))
    seconds = int(os.environ.get("ALEPH_INSPECT_HARD_TIMEOUT_S", "0"))
    if seconds <= 0:
        return
    if os.name != "posix" or os.getpid() != os.getpgrp():
        raise RuntimeError("inspection deadline needs a dedicated POSIX process group")

    # SIGALRM's Python handler alone cannot interrupt arbitrary native code.
    # A separate member of this group owns the kernel-clock deadline; the web
    # reaper kills it on normal completion, and it kills the whole group after
    # an orphaned or wedged run. No DB lease can expire before this deadline.
    watchdog_code = (
        "import os,signal,time; print('READY',flush=True); "
        "time.sleep(int(os.environ['ALEPH_INSPECT_HARD_TIMEOUT_S'])); "
        "os.killpg(os.getpgrp(),signal.SIGKILL)"
    )
    watchdog_command = ([sys.executable, "--inspect-watchdog"] if getattr(sys, "frozen", False)
                        else [sys.executable, "-I", "-c", watchdog_code])
    watchdog = subprocess.Popen(watchdog_command,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, close_fds=True,
                                env={"PATH": "/usr/bin:/bin", "ALEPH_INSPECT_HARD_TIMEOUT_S": str(seconds),
                                     **({"PYTHONHOME": os.environ["PYTHONHOME"]}
                                        if "PYTHONHOME" in os.environ else {})})
    assert watchdog.stdout is not None
    if not select.select([watchdog.stdout], [], [], 5)[0] or watchdog.stdout.readline() != b"READY\n":
        watchdog.kill()
        raise RuntimeError("inspection watchdog did not start")
    watchdog.stdout.close()

    def expire(_signum, _frame):
        os.killpg(os.getpgrp(), signal.SIGKILL)

    signal.signal(signal.SIGALRM, expire)
    signal.alarm(seconds)


if __name__ == "__main__":
    # Arm before importing the inspection stack: even a hung import must not
    # outlive the database lease if its parent web worker disappears.
    _arm_hard_deadline()

_PLATFORM = Path(__file__).resolve().parents[1]
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection import registry
from inspection.bridge import SpaceEmitter, run_recon_to_space
from inspection.fixtures.demos.attendance import demo as attendance_demo
from inspection.fixtures.test_app import BenignTestApp
from inspection.observe.healthcheck import stamp_spec
from inspection.observe.synthesize import synthesize_tool


def _load_mcpserver_cls():
    """EL CLIENTE REAL, el mismo que usa el agente al equipar el belt.

    Desde la sesión 3 «el real» lo decide `inspection.transporte`: el puente al SDK por
    default, el cliente viejo con `ALEPH_TRANSPORTE=viejo`. Ese es justamente el punto —
    este runner existe para probar la tool con EL cliente de producción, así que si el
    producto cambió de transporte y esto no, la prueba deja de probar lo que dice."""
    asm_dir = str(_REPO_ROOT / "platform" / "assembler")
    if asm_dir not in sys.path:
        sys.path.insert(0, asm_dir)
    from inspection import transporte as _TP
    return _TP.servidor_stdio()


def _synthetic_args(spec: dict[str, Any]) -> dict[str, Any]:
    """Valores NUEVOS para los params requeridos (prueba que la tool corre con datos
    distintos a los demostrados — no es un replay del input original)."""
    schema = spec["mcp_tool"]["inputSchema"]
    props = schema.get("properties", {}) or {}
    out: dict[str, Any] = {}
    for name in schema.get("required", []) or []:
        t = (props.get(name, {}) or {}).get("type", "string")
        if t == "integer":
            out[name] = 4242
        elif t == "number":
            out[name] = 42.42
        elif t == "boolean":
            out[name] = True
        else:
            out[name] = f"{name}-verif"
    return out


def _call_synth(Servidor, art: dict, args: dict, *, execute: bool, allow_write: bool):
    """Lanza el synth MCP server con los flags de gate y llama la tool por JSON-RPC."""
    server_name = art["server_name"]
    cfg = art["belt"]["mcpServers"][server_name]
    from inspection.transporte_sdk import entorno_hijo
    env = entorno_hijo(cfg.get("env") or {})
    if execute:
        env["SYNTH_EXECUTE"] = "1"
    if allow_write:
        env["SYNTH_ALLOW_WRITE"] = "1"
    srv = Servidor(server_name, cfg["command"], cfg["args"], env=env)
    started = srv.start()
    out_text = srv.call_tool(art["tool_name"], args) if started else "(no start)"
    srv.stop()
    try:
        out = json.loads(out_text)
    except (json.JSONDecodeError, TypeError):
        # El cliente MCP prefija los resultados con isError=true con "[tool error] ". El synth
        # server igual serializa el resultado ESTRUCTURADO (incl. {refused, by:"safety"} cuando la
        # capa T9 frena el replay-write a loopback/interno): recuperá ese JSON para no perder la
        # señal honesta y degradar a eco-null mudo. [seam parser synth↔cliente MCP↔inspect_run]
        txt = out_text.strip() if isinstance(out_text, str) else out_text
        if isinstance(txt, str) and txt.startswith("[tool error]"):
            txt = txt[len("[tool error]"):].strip()
        try:
            out = json.loads(txt)
        except (json.JSONDecodeError, TypeError):
            out = {"raw": out_text}
    return started, out


def _is_write(spec: dict[str, Any]) -> bool:
    return (spec.get("category") in ("write", "send")) or (
        (spec.get("request", {}) or {}).get("method", "GET").upper()
        in ("POST", "PUT", "PATCH", "DELETE"))


async def run_inspection(*, space_id: str, puppet_id: Optional[str] = None,
                         user_id: Optional[str] = None, intent: str = "registrar asistencia",
                         target_url: Optional[str] = None, demo=attendance_demo,
                         settle_ms: int = 2200, pace_ms: int = 2200,
                         auto_approve: bool = False) -> dict[str, Any]:
    emitter = SpaceEmitter(space_id, owner_id=user_id, public=user_id is None, claim=True)
    r = registry.repo()
    run_id: Optional[str] = None
    conn = None
    result: dict[str, Any] = {"space_id": space_id, "puppet_id": puppet_id, "user_id": user_id}
    try:
        # run row para atribuir el costo del recon/tool (si hay puppet o user)
        if puppet_id or user_id:
            conn = r.get_conn()
            try:
                run = r.create_run(conn, puppet_id=puppet_id, user_id=user_id,
                                   space_id=space_id, intent=intent)
                run_id = run.get("id") if isinstance(run, dict) else None
            except Exception:
                run_id = None

        with BenignTestApp() as app:
            base = target_url or app.base_url
            print(f"[inspect_run] space={space_id} target={base} puppet={puppet_id}", flush=True)

            # ── recon (4 beats, sin cerrar el stream: seguimos el loop) ──────────
            # [integrador · seam T4↔T9] el fixture benigno local (loopback) es confiable →
            # allow_local_fixture=True SOLO cuando NO hay target_url externo. Un target real
            # (path headed) pasa con allow_local_fixture=False → guard anti-SSRF de T9 completo.
            action, _cap = await run_recon_to_space(
                space_id=space_id, target_url=base, intent=intent, demo=demo,
                settle_ms=settle_ms, pace_ms=pace_ms, emitter=emitter, close=False,
                allow_local_fixture=(not target_url))
            emitter.cost(user_id=user_id, run_id=run_id, tool="inspection.recon")

            # ── forja: tool MCP + sello de drift (firma + versión) ───────────────
            spec = synthesize_tool(action)
            stamp_spec(spec, action, version=1, observed_at=time.time())

            # ── persistir el belt (durable, por-usuario) ─────────────────────────
            art = registry.persist_belt(spec, user_id=user_id)
            result.update({"belt_ref": art["belt_ref"], "server": art["server_name"],
                           "tool": art["tool_name"], "spec_path": art["spec_path"]})

            # ── equipar: registrar en la receta del puppet ───────────────────────
            reg = None
            if puppet_id:
                reg = registry.register_into_puppet(
                    puppet_id, art["belt_ref"], art["server_name"], art["tool_name"], conn=conn)
            belt_refs = (reg or {}).get("belt_refs") or [art["belt_ref"]]
            emitter.tool_equipada(
                label=spec.get("label", art["tool_name"]), belt_ref=art["belt_ref"],
                server=art["server_name"], tool=art["tool_name"], puppet_id=puppet_id,
                belt_refs=belt_refs, version=1)
            result.update({"registered": bool(reg and reg.get("registered")),
                           "already_present": bool(reg and reg.get("already_present")),
                           "belt_refs": belt_refs, "validation": (reg or {}).get("validation"),
                           "run_id": run_id})

            # ── ejecución GATEADA de la tool sintetizada ─────────────────────────
            Servidor = _load_mcpserver_cls()
            args = _synthetic_args(spec)
            server_name, tool_name = art["server_name"], art["tool_name"]
            if _is_write(spec) and not auto_approve:
                # HONESTO: una tool write sintetizada NO toca el mundo sin OK humano.
                _started, _dry = _call_synth(Servidor, art, args, execute=False, allow_write=False)
                emitter.tool_call(server=server_name, tool=tool_name, args=args, dry_run=True)
                emitter.gate_held(server=server_name, tool=tool_name, args=args, level="write",
                                  reason="tool sintetizada (write) — requiere OK humano para ejecutar")
                result["gated"] = "held"
            else:
                # OK (aprobación humana / read auto): corre de verdad → ECO real del mundo,
                # SALVO que la capa de safety (T9) frene el replay. Decisión de dueños 2026-06-21
                # (opción B): `guard_replay` mantiene política pública estricta de ESCRITURA (sin
                # bypass loopback, a diferencia del recon). Contra un target interno/loopback (fixture,
                # SHOWCASE) el eco queda refused-by-safety — comportamiento CORRECTO, eco honesto.
                emitter.tool_call(server=server_name, tool=tool_name, args=args, dry_run=False)
                _started, out = _call_synth(Servidor, art, args, execute=True, allow_write=True)
                emitter.gate_approved(server=server_name, tool=tool_name)
                if isinstance(out, dict) and out.get("refused"):
                    by = out.get("by") or "safety"
                    reason = out.get("reason") or "replay frenado por safety"
                    emitter.eco(server=server_name, tool=tool_name, status=None, echo=None,
                                ok=False, refused=True, reason=reason)
                    result.update({"gated": "approved", "eco_status": None, "eco_ok": False,
                                   "eco": None, "eco_refused": True, "eco_by": by, "eco_reason": reason})
                else:
                    resp = (out.get("response") or {}) if isinstance(out, dict) else {}
                    status = resp.get("status")
                    rjson = resp.get("json") if isinstance(resp, dict) else None
                    echo = rjson.get("echo") if isinstance(rjson, dict) and "echo" in rjson else rjson
                    ok = status in (200, 201, 204)
                    emitter.eco(server=server_name, tool=tool_name, status=status, echo=echo, ok=ok)
                    result.update({"gated": "approved", "eco_status": status, "eco_ok": ok,
                                   "eco": echo, "eco_refused": False})

            emitter.cost(user_id=user_id, run_id=run_id, tool=f"{server_name}.{tool_name}")

        emitter.close()
        if run_id:
            try:
                r.finish_run(conn, run_id, "done")
            except Exception:
                pass
        print(f"[inspect_run] listo: {json.dumps(result, ensure_ascii=False)}", flush=True)
        return result
    except Exception as exc:  # noqa: BLE001
        emitter.error(stage="inspect_run", detail=str(exc))
        emitter.close()
        print(f"[inspect_run] ERROR: {exc}", flush=True)
        raise
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


# ── DRIFT: re-inspección / health-check de una tool sintetizada ─────────────────

def _spec_path_for_belt(belt_ref: str) -> str:
    """El .spec.json que el belt referencia (env SYNTH_TOOL_SPEC); fallback al sibling."""
    belt_path = Path(belt_ref) if Path(belt_ref).is_absolute() else (_REPO_ROOT / belt_ref)
    belt = json.loads(belt_path.read_text(encoding="utf-8"))
    for srv in (belt.get("mcpServers") or {}).values():
        sp = (srv.get("env") or {}).get("SYNTH_TOOL_SPEC")
        if sp and Path(sp).exists():
            return sp
    sibs = sorted(belt_path.parent.glob("*.spec.json"))
    if sibs:
        return str(sibs[0])
    raise FileNotFoundError(f"no encuentro el .spec.json del belt {belt_ref}")


def _cura_is_net_new(frozen_tool_name, new_tool_name) -> bool:
    """FRONTERA CURA (bypass inverso · persona usuaria): ¿la re-síntesis del health-check produce una
    capability NET-NEW (identidad distinta a la del manifest previo) en vez de re-versionar la
    MISMA tool? La identidad = el nombre de la tool (mcp_tool.name = slug del intent, la clave del
    manifest). Re-versión (misma identidad) = CURA libre. Identidad distinta = síntesis de lo
    inexistente = PREMIUM → no se fabrica inline por el path libre de cura.

    FAIL-CLOSED: si cualquiera de los dos nombres falta/está vacío, tratamos como NET-NEW (gate) —
    mejor una cura que escala de más (molesto) que una que fabrica una tool nueva gratis (bypass)."""
    fz = (str(frozen_tool_name).strip() if frozen_tool_name else "")
    nw = (str(new_tool_name).strip() if new_tool_name else "")
    if not fz or not nw:
        return True
    return nw != fz


async def re_inspect(*, space_id: str, belt_ref: Optional[str] = None,
                     spec_path: Optional[str] = None, puppet_id: Optional[str] = None,
                     user_id: Optional[str] = None, intent: str = "registrar asistencia",
                     demo=attendance_demo, fixture_drift: bool = False,
                     settle_ms: int = 2200, auto_resynth: bool = True) -> dict[str, Any]:
    """
    HEALTH-CHECK de DRIFT: re-observa el software y compara su firma fresca contra la
    CONGELADA en el spec. Si derivó (shape o endpoint): emite tool.drift y —si
    auto_resynth— RE-FORJA la tool (versión+1), re-persiste el belt y lo re-registra;
    si no, marca el belt stale. Cierra el lazo "se rompe silenciosa → la atrapamos".
    """
    from inspection.observe.correlate import correlate
    from inspection.observe.healthcheck import healthcheck_spec, stamp_spec
    from inspection.observe.recorder import record_demonstration
    from inspection.session.cloud import CloudSession

    emitter = SpaceEmitter(space_id, owner_id=user_id, public=user_id is None, claim=True)
    if spec_path is None:
        if not belt_ref:
            raise ValueError("re_inspect requiere belt_ref o spec_path")
        spec_path = _spec_path_for_belt(belt_ref)
    frozen = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    server_name = frozen["mcp_tool"]["name"]
    cur_version = int((frozen.get("_synth") or {}).get("version") or 1)
    result: dict[str, Any] = {"space_id": space_id, "belt_ref": belt_ref, "version": cur_version}
    try:
        emitter.inspeccion_analizando(requests=None)   # "re-chequeando el software…"
        with BenignTestApp(drift=fixture_drift) as app:
            session = CloudSession(headless=True)
            ctx = await session.provide_context()
            try:
                bundle = await record_demonstration(
                    ctx, intent=intent, target_url=app.base_url, demo=demo, settle_ms=settle_ms)
                fresh_action = correlate(bundle)
            finally:
                await ctx.aclose()

            diff = healthcheck_spec(frozen, fresh_action)
            result.update(diff)
            emitter.drift(
                belt_ref=belt_ref or spec_path, server=server_name, tool=server_name,
                healthy=diff["healthy"],
                detail={k: diff[k] for k in
                        ("drift", "endpoint_changed", "changes", "fields_added", "fields_removed")})

            if diff["healthy"]:
                if belt_ref:
                    registry.mark_belt(belt_ref, stale=False, reason="health-check: sin drift",
                                       version=cur_version)
                result["action"] = "healthy"
            elif auto_resynth:
                new_version = cur_version + 1
                new_spec = synthesize_tool(fresh_action)
                _new_name = (new_spec.get("mcp_tool") or {}).get("name")
                # ── FRONTERA CURA (bypass inverso) ────────────────────────────────────
                # La cura re-versiona la MISMA tool (v+1) GRATIS. Pero si la deriva es tan grande
                # que la re-síntesis daría una capability NET-NEW (identidad distinta = no estaba en
                # el manifest previo), NO se fabrica inline por este path libre: se ESCALA al gate
                # premium de construcción. Re-versionar-lo-existente = libre · sintetizar-lo-inexistente
                # = premium. Acá NO persistimos ni registramos la tool nueva (eso vaciaría el moat).
                if _cura_is_net_new(server_name, _new_name):
                    if belt_ref:
                        registry.mark_belt(belt_ref, stale=True, version=cur_version,
                                           reason="drift a capability NET-NEW — requiere construcción premium")
                    emitter.drift(
                        belt_ref=belt_ref or spec_path, server=server_name, tool=server_name,
                        healthy=False,
                        detail={"net_new": True, "needs_premium_construction": True,
                                "frozen_tool": server_name, "would_synthesize": _new_name,
                                "reason": ("la cura detectó una capability que no estaba en el manifest "
                                           "previo; construir tools nuevas es Premium, no se fabrica en la cura")})
                    result.update({"action": "escalate_construction", "net_new": True,
                                   "would_synthesize": _new_name, "version": cur_version})
                else:
                    stamp_spec(new_spec, fresh_action, version=new_version, observed_at=time.time())
                    art = registry.persist_belt(new_spec, user_id=user_id)
                    if puppet_id:
                        registry.register_into_puppet(
                            puppet_id, art["belt_ref"], art["server_name"], art["tool_name"])
                    registry.mark_belt(art["belt_ref"], stale=False,
                                       reason="re-forjada tras drift", version=new_version)
                    result.update({"action": "resynthesized", "version": new_version,
                                   "new_belt_ref": art["belt_ref"]})
            else:
                if belt_ref:
                    registry.mark_belt(belt_ref, stale=True, reason="drift detectado",
                                       version=cur_version)
                result.update({"action": "marked_stale"})
        emitter.close()
        print(f"[re_inspect] {json.dumps(result, ensure_ascii=False)}", flush=True)
        return result
    except Exception as exc:  # noqa: BLE001
        emitter.error(stage="re_inspect", detail=str(exc))
        emitter.close()
        raise


def _arg(i: int) -> Optional[str]:
    if len(sys.argv) > i:
        v = sys.argv[i].strip()
        return v if v and v != "-" else None
    return None


def _flag(s: Optional[str]) -> bool:
    return bool(s) and s.strip().lower() in ("1", "true", "yes", "approve", "ok", "drift")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "byo":
        from inspection import byo_mcp

        try:
            request = json.loads(sys.stdin.read(131073))
            if not isinstance(request, dict) or len(json.dumps(request).encode()) > 131072:
                raise ValueError("BYO request too large")
            if request.get("transport") == "stdio":
                from inspection.grouped_stdio import install as install_grouped_stdio
                install_grouped_stdio()
            from inspection import registry as _registry
            conn = _registry.repo().get_conn() if request.get("puppet_id") else None
            try:
                result = byo_mcp.forge_byo(
                    transport=request["transport"], user_id=request.get("user_id"),
                    puppet_id=request.get("puppet_id"), url=request.get("url"),
                    headers=request.get("headers"), command=request.get("command"),
                    args=request.get("args"), env=request.get("env"),
                    label=request.get("label"), allowed_tools=request.get("allowed_tools"),
                    conn=conn)
            finally:
                if conn is not None:
                    conn.close()
            response = {"kind": "ok", "result": result}
        except byo_mcp.BYOValidationError as exc:
            response = {"kind": "invalid", "detail": str(exc)}
        except Exception as exc:
            response = {"kind": "failed", "detail": str(exc)}
        print(json.dumps(response, ensure_ascii=False), flush=True)
        raise SystemExit(0 if response["kind"] == "ok" else 1)
    # modo health-check:  inspect_run.py healthcheck <space> <belt_ref> [puppet|-] [user|-] [drift]
    if len(sys.argv) > 1 and sys.argv[1] == "healthcheck":
        sid = _arg(2) or f"healthcheck-{int(time.time())}"
        belt = _arg(3)
        pid = _arg(4)
        uid = _arg(5)
        drift = _flag(sys.argv[6]) if len(sys.argv) > 6 else False
        # contra el fixture drift, el usuario re-demuestra sobre la UI cambiada
        demo = attendance_demo
        if drift:
            from inspection.fixtures.demos.attendance_drift import demo as demo
        out = asyncio.run(re_inspect(space_id=sid, belt_ref=belt, puppet_id=pid,
                                     user_id=uid, fixture_drift=drift, demo=demo))
        print(json.dumps(out, ensure_ascii=False), flush=True)
        raise SystemExit(0)

    # modo inspección:  inspect_run.py <space> [puppet|-] [user|-] [approve] [target_url|-] [intent|-]
    sid = _arg(1) or f"inspect-{int(time.time())}"
    pid = _arg(2)
    uid = _arg(3)
    approve = _flag(sys.argv[4]) if len(sys.argv) > 4 else False
    # [fix-puerta · Gap#1] target_url + intent forwardeados por inspect_router (antes se perdían acá
    # → showcase hardcodeado). run_inspection YA los honra: con target_url inspecciona el target REAL
    # (allow_local_fixture=False → guard anti-SSRF completo); sin él, BenignTestApp como fallback.
    # Aditivo: NO toca el cuerpo del run-loop ni el timeout — sólo forwardea dos params ya existentes.
    target = _arg(5)
    intent = _arg(6)
    kw = {"space_id": sid, "puppet_id": pid, "user_id": uid, "auto_approve": approve}
    if target:
        kw["target_url"] = target
    if intent:
        kw["intent"] = intent
    out = asyncio.run(run_inspection(**kw))
    print(json.dumps(out, ensure_ascii=False), flush=True)
    raise SystemExit(0)
