"""
inspect_router.py — el TRIGGER del motor de inspección desde el producto (FASE 5).

`POST /v1/inspect` corre el LOOP COMPLETO usuario→agente y lo emite a un space; el
Cuarto (que abre el EventSource a /v1/spaces/{id}/stream) lo anima en vivo:

    software.detectado → inspeccion.analizando → accion.observada → tool.sintetizada
    → tool.equipada (queda en la receta del puppet) → gate.held / tool_call / eco
    → closed   (+ cost por call, §4.6)

Así la inspección deja de ser una animación: NACE una tool, queda EQUIPADA en el puppet
del usuario y se ejecuta GATEADA. `POST /v1/inspect/healthcheck` re-observa el software y,
si derivó, re-forja la tool (versión+1) — health-check de drift.

El recon corre en un SUBPROCESO aislado (Playwright + asyncio, fuera del event-loop de
uvicorn): platform/inspection/inspect_run.py. Hoy inspecciona el target SHOWCASE benigno
(el path headed/local-attach contra el software real del usuario es el próximo).

SCOPE (§4.5): si viene `puppet_id`, la sesión es OBLIGATORIA y el puppet DEBE ser del
usuario de la sesión (authz: no se registra una tool en el puppet de otro). Sin puppet_id,
la inspección corre anónima (sólo anima + sintetiza, no registra).
"""
from __future__ import annotations

import subprocess
import json
import sys
import os
import secrets
import signal
import logging
import threading
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

_REPO_ROOT = (Path(sys._MEIPASS) if getattr(sys, "frozen", False)
              else Path(__file__).resolve().parents[4])
_RUNNER = _REPO_ROOT / "platform" / "inspection" / "inspect_run.py"


def _runner_command() -> list[str]:
    # A frozen sidecar already contains the inspection dependencies. Running
    # a PATH Python against extracted source would lose that dependency set.
    if getattr(sys, "frozen", False):
        return [sys.executable, "--inspect-runner"]
    return [sys.executable, str(_RUNNER)]
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

_ESPACIOS = _dir_datos("espacios")

# [T9-safety] la capa de guards vive en platform/safety; asegurar que importe desde el backend.
_PLATFORM = _REPO_ROOT / "platform"
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection.space_access import SpaceAccessError, claim_space, space_dir, validate_space_id

from app.phase1 import inspect_quota

_LOG = logging.getLogger(__name__)


def _subject(user_id: Optional[str]) -> str:
    return str(user_id) if user_id else "anonymous-dev"


def _consume_recon_rate(user_id: Optional[str], *, label: str) -> None:
    try:
        from safety import rate_limit
        allowed, info = rate_limit.check_and_consume(_subject(user_id), bucket="recon")
        if not allowed:
            raise HTTPException(status_code=429, detail={"error": f"rate-limit de {label}", **info})
    except ImportError:
        pass


def _claim(space_id: str, user_id: Optional[str]) -> str:
    try:
        sid = validate_space_id(space_id)
        claim_space(_ESPACIOS, sid, owner_id=user_id, public=user_id is None)
        return sid
    except SpaceAccessError as exc:
        raise HTTPException(status_code=422,
                            detail={"error": "space_id_invalid", "detail": str(exc)}) from exc


def _timeout() -> int:
    return max(10, int(os.environ.get("ALEPH_INSPECT_TIMEOUT_S", "300")))


def _reserve(owner: str) -> str:
    try:
        per_owner = max(1, int(os.environ.get("ALEPH_INSPECT_MAX_PER_OWNER", "2")))
        global_max = max(1, int(os.environ.get("ALEPH_INSPECT_MAX_GLOBAL", "8")))
        return inspect_quota.reserve(owner, per_owner, global_max, _timeout() + 30)
    except inspect_quota.CapacityFull as exc:
        raise HTTPException(status_code=429, detail={
            "error": "inspect_capacity", "detail": "Hay demasiadas inspecciones activas."}) from exc
    except Exception as exc:
        _LOG.exception("inspect quota unavailable; admission denied")
        raise HTTPException(status_code=503, detail={"error": "inspect_quota_unavailable"}) from exc


def _release(lease_id: str, status: str = "finished") -> None:
    try:
        inspect_quota.release(lease_id, status=status)
    except Exception:
        _LOG.exception("inspect quota lease release failed; admission stays closed until recovery")


class InspectRequest(BaseModel):
    target_url: Optional[str] = None   # reservado: target real (path headed, próximo)
    intent: Optional[str] = None
    space_id: Optional[str] = None
    puppet_id: Optional[str] = None    # dónde queda equipada la tool (scopeado al user)
    auto_approve: bool = False         # OK del humano: ejecuta la tool write (eco real)


class HealthcheckRequest(BaseModel):
    belt_ref: str                      # belt sintetizado a re-chequear
    space_id: Optional[str] = None
    puppet_id: Optional[str] = None
    drift: bool = False                # hook de test: re-observa la variante derivada


class ByoRequest(BaseModel):
    """C3 · "pegá tu MCP → Sumar": el usuario trae su PROPIO MCP server.

    transport="http": un MCP público por Streamable HTTP (`url` [+ `headers`]).
    transport="stdio": un MCP local (`command` [+ `args` + `env`]).
    Si viene `puppet_id` (scopeado al user), el belt se REGISTRA en su receta y el agente
    lo usa; sin él, solo se valida+forja (anónimo). `allowed_tools` recorta el subset.
    """
    transport: str = "http"
    url: Optional[str] = None
    headers: Optional[dict] = None
    command: Optional[str] = None
    args: Optional[list] = None
    env: Optional[dict] = None
    label: Optional[str] = None
    allowed_tools: Optional[list[str]] = None
    space_id: Optional[str] = None
    puppet_id: Optional[str] = None


def _bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    a = authorization.strip()
    return a[7:].strip() if a.lower().startswith("bearer ") else a


def _session_user(authorization: Optional[str]) -> Optional[str]:
    """user_id de la sesión (o None si no hay sesión válida)."""
    from app.phase1 import repo
    return repo.session_owner(_bearer(authorization))


def _require_owned_puppet(puppet_id: str, user_id: Optional[str]) -> None:
    """El agente debe existir y ser del usuario de la sesión (authz / anti-IDOR)."""
    if not user_id:
        raise HTTPException(status_code=401,
            detail={"error": "no_session", "detail": "Inicia sesión para equipar una tool en tu agente."})
    from app.phase1 import repo
    conn = repo.get_conn()
    try:
        puppet = repo.get_puppet(conn, puppet_id)
    finally:
        conn.close()
    if puppet is None:
        raise HTTPException(status_code=404, detail={"error": "puppet_not_found",
            "detail": f"puppet '{puppet_id}' no existe"})
    if str(puppet.get("owner_id")) != str(user_id):
        raise HTTPException(status_code=403, detail={"error": "not_owner",
            "detail": "ese agente no es tuyo"})


def _spawn(args: list[str], space_id: str, lease_id: str) -> None:
    """Lanza el runner tras una reserva; libera la reserva al fallar o al terminar."""
    if os.name != "posix":
        _release(lease_id, "failed")
        raise HTTPException(status_code=503, detail={"error": "inspect_watchdog_unavailable"})
    try:
        directory = space_dir(_ESPACIOS, space_id, create=True)
        log = open(directory / "runner.log", "ab")
    except Exception:
        _release(lease_id, "failed")
        raise
    try:
        env = {**os.environ, "ALEPH_INSPECT_HARD_TIMEOUT_S": str(_timeout() + 10)}
        proc = subprocess.Popen([*_runner_command(), *args], stdout=log, stderr=log,
                                cwd=str(_REPO_ROOT), env=env,
                                start_new_session=(os.name == "posix"))
    except Exception:
        log.close()
        _release(lease_id, "failed")
        raise

    try:
        if not inspect_quota.mark_running(lease_id, proc.pid):
            raise RuntimeError("inspection reservation expired before launch")
    except Exception:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=5)
        log.close()
        _release(lease_id, "failed")
        raise HTTPException(status_code=503, detail={"error": "inspect_quota_unavailable"})

    timeout = _timeout()

    def reap() -> None:
        outcome = "finished"
        try:
            proc.wait(timeout=timeout)
            if proc.returncode != 0:
                outcome = "failed"
        except subprocess.TimeoutExpired:
            outcome = "cancelled"
            try:
                if os.name == "posix":
                    os.killpg(proc.pid, signal.SIGTERM)
                else:
                    proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                pass
        finally:
            # The leader may exit while Chromium/grandchildren ignore TERM. Do not
            # release capacity until the dedicated process group is killed.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except Exception:
                _LOG.exception("could not kill inspection process group")
            log.close()
            _release(lease_id, outcome)
    try:
        threading.Thread(target=reap, name=f"inspect-reap-{proc.pid}", daemon=True).start()
    except Exception:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)
        finally:
            log.close()
            _release(lease_id, "failed")
        raise


class _BYOInvalid(Exception):
    pass


def _run_byo_bounded(body: "ByoRequest", user_id: Optional[str], lease_id: str) -> dict:
    """Run BYO outside the web worker, with a recoverable database lease."""
    if os.name != "posix":
        raise RuntimeError("BYO inspection requires POSIX process-group supervision")
    request = body.model_dump(exclude={"space_id"})
    request["user_id"] = user_id
    payload = json.dumps(request, ensure_ascii=False).encode("utf-8")
    if len(payload) > 131072:
        raise _BYOInvalid("BYO request too large")
    env = {**os.environ, "ALEPH_INSPECT_HARD_TIMEOUT_S": str(_timeout() + 10),
           "ALEPH_INSPECT_OUTPUT_LIMIT_BYTES": str(2 * 1024 * 1024)}
    if body.transport == "stdio":
        env["ALEPH_TRANSPORTE"] = "sdk"
    with tempfile.TemporaryDirectory(prefix="aleph-byo-output-") as scratch:
        with open(Path(scratch) / "stdout", "w+b") as out, open(Path(scratch) / "stderr", "w+b") as err:
            proc = subprocess.Popen([*_runner_command(), "byo"], stdin=subprocess.PIPE,
                                    stdout=out, stderr=err, cwd=str(_REPO_ROOT), env=env,
                                    start_new_session=True)
            try:
                try:
                    if not inspect_quota.mark_running(lease_id, proc.pid):
                        raise RuntimeError("BYO reservation expired before launch")
                    proc.communicate(input=payload, timeout=_timeout())
                except subprocess.TimeoutExpired as exc:
                    raise RuntimeError("BYO inspection exceeded its hard deadline") from exc
                if os.fstat(out.fileno()).st_size > 2 * 1024 * 1024 or os.fstat(err.fileno()).st_size > 1024 * 1024:
                    raise RuntimeError("BYO inspection output exceeded its limit")
                out.seek(0)
                try:
                    response = json.loads(out.read(2 * 1024 * 1024 + 1))
                except (ValueError, UnicodeDecodeError) as exc:
                    raise RuntimeError("BYO runner produced an invalid response") from exc
                if not isinstance(response, dict):
                    raise RuntimeError("BYO runner produced an invalid response")
                if response.get("kind") == "invalid":
                    raise _BYOInvalid(str(response.get("detail", "invalid MCP")))
                if proc.returncode != 0 or response.get("kind") != "ok" or not isinstance(response.get("result"), dict):
                    raise RuntimeError(str(response.get("detail", "BYO runner failed")))
                result = response["result"]
                if body.transport == "stdio":
                    result["inspection_transport"] = "sdk_group_supervised"
                return result
            finally:
                # The ordinary MCP stdio transport shares this group. Never
                # free capacity before terminating the supervised process group.
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=5)
                if proc.stdin is not None:
                    proc.stdin.close()


def build_inspect_router() -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["inspect"])

    @router.post("/inspect", status_code=202)
    def inspect(body: InspectRequest, authorization: Optional[str] = Header(default=None)):
        user_id = _session_user(authorization)
        if body.puppet_id:
            _require_owned_puppet(body.puppet_id, user_id)

        # [T9-safety] gate de borde (defense-in-depth): rate-limit por sujeto SIEMPRE, y
        # si llega un target_url real (path headed), validarlo anti-SSRF acá también — no
        # solo dentro del motor. Devuelve 429/400 honesto. El recon re-valida en bridge.
        try:
            from safety import url_guard
            _consume_recon_rate(user_id, label="recon")
            if (body.target_url or "").strip():
                ok, reason = url_guard.is_safe(body.target_url.strip())
                if not ok:
                    raise HTTPException(status_code=400,
                                        detail={"error": "target sin derecho a inspección",
                                                "reason": reason})
        except ImportError:
            pass  # capa de safety ausente (build incompleto): el core sigue

        owner = _subject(user_id)
        lease_id = _reserve(owner)
        try:
            space_id = _claim((body.space_id or "").strip() or f"inspect-{secrets.token_hex(12)}", user_id)
        except Exception:
            _release(lease_id, "failed")
            raise

        # T4: spawn auth-aware (puppet_id/user_id/approve) → inspect_run.py, log a runner.log.
        # [fix-puerta · Gap#1] forwardamos target_url + intent: ANTES se descartaban acá y el
        # runner caía SIEMPRE al showcase (BenignTestApp), ignorando el target tipeado. run_inspection
        # ya los honra (target → recon del target con allow_local_fixture=False · guard anti-SSRF
        # completo). Aditivo: con "-" el runner usa el showcase como fallback (sin target → demo).
        _spawn([space_id, body.puppet_id or "-", user_id or "-",
                "approve" if body.auto_approve else "-",
                (body.target_url or "").strip() or "-",
                (body.intent or "").strip() or "-"], space_id, lease_id)
        return {
            "space_id": space_id,
            "stream": f"/v1/spaces/{space_id}/stream",
            "cuarto": f"/cuarto/cuarto.pixi.html?recon={space_id}",
            "puppet_id": body.puppet_id,
            "user_id": user_id,
        }

    @router.post("/inspect/healthcheck", status_code=202)
    def inspect_healthcheck(body: HealthcheckRequest,
                            authorization: Optional[str] = Header(default=None)):
        user_id = _session_user(authorization)
        if body.puppet_id:
            _require_owned_puppet(body.puppet_id, user_id)
        _consume_recon_rate(user_id, label="healthcheck")
        owner = _subject(user_id)
        lease_id = _reserve(owner)
        try:
            space_id = _claim((body.space_id or "").strip() or f"healthcheck-{secrets.token_hex(12)}", user_id)
        except Exception:
            _release(lease_id, "failed")
            raise
        _spawn(["healthcheck", space_id, body.belt_ref, body.puppet_id or "-",
                user_id or "-", "drift" if body.drift else "-"], space_id, lease_id)
        return {
            "space_id": space_id,
            "stream": f"/v1/spaces/{space_id}/stream",
            "belt_ref": body.belt_ref,
            "puppet_id": body.puppet_id,
        }

    @router.post("/inspect/byo", status_code=200)
    def inspect_byo(body: ByoRequest, authorization: Optional[str] = Header(default=None)):
        """C3 · BYO-MCP REAL: pegá tu MCP → validar (conectar+listar tools) → forjar belt →
        registrar en tu puppet → el agente lo usa. NO es la card falsa: si no conecta o no
        expone tools, falla HONESTO. Síncrono (corre en threadpool) para dar feedback de
        validez al toque, y emite el ciclo al space para que el Cuarto lo anime en vivo."""
        user_id = _session_user(authorization)
        if body.transport == "stdio" and not user_id:
            raise HTTPException(status_code=401, detail={"error": "session_required_for_local_mcp"})
        if body.puppet_id:
            _require_owned_puppet(body.puppet_id, user_id)

        ref_for_log = (body.url or body.command or "").strip()

        # [T9-safety] rate-limit por sujeto SIEMPRE (defense-in-depth; el probe http re-valida
        # anti-SSRF la URL). 429 honesto si excede.
        try:
            _consume_recon_rate(user_id, label="BYO")
        except ImportError:
            pass
        owner = _subject(user_id)
        lease_id = _reserve(owner)
        try:
            space_id = _claim((body.space_id or "").strip() or f"byo-{secrets.token_hex(12)}", user_id)
        except Exception:
            _release(lease_id, "failed")
            raise

        # emitter del space: anima detectado → analizando → sintetizada → equipada, reusando
        # el MISMO vocabulario que el motor de inspección (la gramática del Cuarto se mantiene;
        # cero tipos nuevos en el event-store). Eventos REALES, no teatro.
        emitter = None
        try:
            from inspection.bridge import SpaceEmitter
            emitter = SpaceEmitter(space_id, str(_ESPACIOS), owner_id=user_id,
                                   public=user_id is None, claim=True)
            emitter.software_detectado(label=f"Tu MCP: {body.label or ref_for_log}",
                                       url=ref_for_log if body.transport == "http" else "",
                                       title=body.transport)
            emitter.inspeccion_analizando()
        except Exception:
            emitter = None

        outcome = "failed"
        try:
            result = _run_byo_bounded(body, user_id, lease_id)
            outcome = "finished"
        except _BYOInvalid as e:
            if emitter is not None:
                emitter.error(stage="byo.validar", detail=str(e))
                emitter.close()
            raise HTTPException(status_code=422,
                                detail={"error": "byo_invalido", "detail": str(e)})
        except Exception as e:  # noqa: BLE001
            if emitter is not None:
                emitter.error(stage="byo.forjar", detail=str(e))
                emitter.close()
            raise HTTPException(status_code=502,
                                detail={"error": "byo_forge_error", "detail": str(e)})
        finally:
            _release(lease_id, outcome)

        if emitter is not None:
            # una pieza "sintetizada" por cada tool del MCP propio (con su zona)
            for c in result.get("cards", []):
                emitter.tool_sintetizada(label=c.get("label") or c.get("id"),
                                         category=c.get("zone", "mesa"),
                                         fields=c.get("tools", []))
            # si quedó registrada en el puppet, una "equipada" por tool (cierra el loop)
            if result.get("registered"):
                for tn in result["tools"]:
                    emitter.tool_equipada(
                        label=result["label"], belt_ref=result["belt_ref"],
                        server=result["server"], tool=tn, puppet_id=body.puppet_id,
                        belt_refs=result.get("belt_refs", []), version=1)
            emitter.close()

        return {
            "space_id": space_id,
            "stream": f"/v1/spaces/{space_id}/stream",
            "user_id": user_id,
            **result,
        }

    return router
