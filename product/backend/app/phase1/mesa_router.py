"""
mesa_router.py — la API HTTP de la Mesa de Construcción (familia /v1/construcciones/*).

Construir un MCP se vuelve una construcción visible y retomable. El STREAM de la construcción
ES el space stream existente (GET /v1/spaces/{id}/stream: replay + reconexión gratis) — este
router solo expone los CONTROLES: crear, ver, responder preguntas, aportar, retomar, validar
tools a mano, probarlas y equipar.

Piso de seguridad intacto: la credencial va al vault (POST /credencial), JAMÁS al transcript ni
a los args de la Mesa; rate-limit por sujeto en cada borde; el candado 5/5 valida TODO igual
venga del motor o de una tool escrita a mano. Vocabulario: construcción (jamás forja).
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[4]
_PLATFORM = _REPO_ROOT / "platform"
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))


def _session_user(authorization: Optional[str]) -> Optional[str]:
    try:
        from app.phase1 import repo
        a = (authorization or "").strip()
        tok = a[7:].strip() if a.lower().startswith("bearer ") else (a or None)
        return repo.session_owner(tok) if tok else None
    except Exception:
        return None


def _rate_ok(subject: str) -> None:
    try:
        from safety import rate_limit
        allowed, info = rate_limit.check_and_consume(subject, bucket="recon")
        if not allowed:
            raise HTTPException(status_code=429, detail={"error": "rate-limit de la mesa", **info})
    except ImportError:
        pass


# ── request bodies ──────────────────────────────────────────────────────────────
class CrearRequest(BaseModel):
    service: Optional[str] = None
    url: Optional[str] = None
    forma: Optional[str] = None
    cred: Optional[str] = None
    puppet_id: Optional[str] = None
    alcance: Optional[str] = None
    session_key: Optional[str] = None
    self_hosted: bool = False
    docs_url: Optional[str] = None
    api_shape_hint: Optional[str] = None
    # perillas de forma (defaults = TMDB-like), todas opcionales
    auth_in: Optional[str] = None
    auth_param: Optional[str] = None
    auth_header: Optional[str] = None
    auth_template: Optional[str] = None
    validate_path: Optional[str] = None
    login_path: Optional[str] = None
    login_credentials: Optional[dict] = None
    max_rounds: Optional[int] = None
    max_calls: Optional[int] = None
    synth_alias: Optional[str] = None


class RespuestaRequest(BaseModel):
    opcion: str
    aporte: Optional[dict] = None


class AportarRequest(BaseModel):
    docs_url: Optional[str] = None
    url: Optional[str] = None
    ejemplo: Optional[dict] = None


class RedirigirRequest(BaseModel):
    alcance: str


class CredencialRequest(BaseModel):
    cred: str


class RetomarRequest(BaseModel):
    session_key: Optional[str] = None


class ValidarToolsRequest(BaseModel):
    tools: list[dict]
    # auth para armar la sesión (si difiere del pedido guardado); opcional
    forma: Optional[str] = None
    cred: Optional[str] = None


class ProbarToolRequest(BaseModel):
    tool: dict
    args: Optional[dict] = None
    execute: bool = False
    forma: Optional[str] = None
    cred: Optional[str] = None


class EquiparRequest(BaseModel):
    keep: Optional[list[str]] = None


def _pedido_de(body: "CrearRequest") -> dict:
    p: dict[str, Any] = {
        "url": (body.url or "").strip(),
        "service": (body.service or "").strip() or None,
        "forma": (body.forma or "").strip().lower() or ("token" if body.cred else ""),
        "puppet_id": body.puppet_id,
        "alcance": body.alcance,
        "session_key": (body.session_key or "").strip() or None,
        "local_target": bool(body.self_hosted),
        "docs_url": (body.docs_url or "").strip() or None,
        "api_shape_hint": body.api_shape_hint or "",
    }
    for k in ("auth_in", "auth_param", "auth_header", "auth_template", "validate_path",
              "login_path", "login_credentials", "max_rounds", "max_calls", "synth_alias"):
        v = getattr(body, k, None)
        if v is not None:
            p[k] = v
    return {k: v for k, v in p.items() if v is not None}


def build_mesa_router() -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["mesa-construccion"])

    def _runner(construccion_id: str, authorization: Optional[str]):
        from app.phase1.mesa_runner import REGISTRO
        r = REGISTRO.obtener(construccion_id, user_id=_session_user(authorization))
        if r is None:
            raise HTTPException(status_code=404, detail={
                "error": "construccion_no_encontrada",
                "detail": f"no existe la construcción '{construccion_id}' (o no es tuya)."})
        return r

    # ── crear + arrancar ────────────────────────────────────────────────────────
    @router.post("/construcciones")
    def crear(body: CrearRequest, authorization: Optional[str] = Header(default=None)):
        user_id = _session_user(authorization)
        _rate_ok(body.puppet_id or user_id or "anon")
        from app.phase1.mesa_runner import REGISTRO
        runner = REGISTRO.crear(
            service=(body.service or None), pedido=_pedido_de(body),
            user_id=user_id, cred=body.cred)
        runner.arrancar()
        return {"construccion_id": runner.snap.construccion_id,
                "space_id": runner.snap.space_id,
                "stream": f"/v1/spaces/{runner.snap.space_id}/stream",
                "estado": runner.snap.estado,
                "estacion": runner.snap.estacion}

    # ── listar borradores retomables ──────────────────────────────────────────────
    @router.get("/construcciones")
    def listar(authorization: Optional[str] = Header(default=None)):
        from app.phase1.mesa_runner import REGISTRO
        return {"construcciones": REGISTRO.listar(user_id=_session_user(authorization))}

    # ── snapshot de una construcción ──────────────────────────────────────────────
    @router.get("/construcciones/{construccion_id}")
    def ver(construccion_id: str, authorization: Optional[str] = Header(default=None)):
        r = _runner(construccion_id, authorization)
        s = r.snap
        from inspection.mesa.proyeccion import indice as _indice
        # leer bajo el RLock del runner: el thread del motor puede estar appendeando al inventario
        # justo ahora (asdict sobre listas en mutación → RuntimeError sin este lock).
        with r._lock:
            return {
                "construccion_id": s.construccion_id, "estado": s.estado,
                "estacion": s.estacion, "estacion_n": (0 if not s.estacion else _indice(s.estacion)),
                "ok": s.ok, "service": s.service,
                "pregunta": s.pregunta.to_dict() if s.pregunta else None,
                "inventario": s.inventario.to_dict(),
                "decisiones": list(s.decisiones),
                "convergencia": s.convergencia,
                "stream": f"/v1/spaces/{s.space_id}/stream",
            }

    # ── responder una pregunta temprana ───────────────────────────────────────────
    @router.post("/construcciones/{construccion_id}/respuesta")
    def responder(construccion_id: str, body: RespuestaRequest,
                  authorization: Optional[str] = Header(default=None)):
        r = _runner(construccion_id, authorization)
        out = r.responder(body.opcion, aporte=body.aporte or {})
        if not out.get("ok"):
            raise HTTPException(status_code=400, detail={"error": "respuesta_invalida", **out})
        return out

    # ── aportar docs / URL / ejemplo (gesto Aportar) ──────────────────────────────
    @router.post("/construcciones/{construccion_id}/aportar")
    def aportar(construccion_id: str, body: AportarRequest,
                authorization: Optional[str] = Header(default=None)):
        r = _runner(construccion_id, authorization)
        # si hay pregunta pendiente, el aporte la responde; si no, ajusta el pedido y no relanza.
        if r.snap.pregunta is not None:
            codigo = r.snap.pregunta.codigo
            opcion = ("aportar-url" if codigo == "P2" else
                      "aportar-ejemplo" if (body.ejemplo and codigo == "P5") else
                      "aportar-docs")
            return r.responder(opcion, aporte=body.model_dump())
        with r._lock:
            if body.docs_url:
                r.snap.pedido["docs_url"] = body.docs_url.strip()
                r.snap.pedido["api_shape_hint"] = (
                    (r.snap.pedido.get("api_shape_hint") or "") + " " + body.docs_url).strip()
            if body.url:
                r.snap.pedido["url"] = body.url.strip()
            r._persistir()
        return {"ok": True, "estado": r.snap.estado}

    # ── redirigir el alcance (gesto Redirigir · curación de scope) ────────────────
    @router.post("/construcciones/{construccion_id}/redirigir")
    def redirigir(construccion_id: str, body: RedirigirRequest,
                  authorization: Optional[str] = Header(default=None)):
        r = _runner(construccion_id, authorization)
        with r._lock:
            r.snap.pedido["alcance"] = body.alcance.strip()
            # el alcance orienta la síntesis (se appendéa al shape hint del motor)
            r.snap.pedido["api_shape_hint"] = (
                (r.snap.pedido.get("api_shape_hint") or "") +
                f" · alcance pedido: {body.alcance.strip()}").strip()
            r._persistir()
        r._emit("construccion.reanudada", estacion=r.snap.estacion)
        return {"ok": True, "alcance": body.alcance.strip(), "estado": r.snap.estado}

    # ── credencial → vault (canal propio, JAMÁS en /respuesta) ────────────────────
    @router.post("/construcciones/{construccion_id}/credencial")
    def credencial(construccion_id: str, body: CredencialRequest,
                   authorization: Optional[str] = Header(default=None)):
        r = _runner(construccion_id, authorization)
        if not (body.cred or "").strip():
            raise HTTPException(status_code=400, detail={"error": "cred_vacia"})
        r.set_credencial(body.cred.strip())
        out = r.continuar_tras_credencial()
        return {"ok": True, "guardada": True, **out}

    # ── retomar un borrador ────────────────────────────────────────────────────────
    @router.post("/construcciones/{construccion_id}/retomar")
    def retomar(construccion_id: str, body: RetomarRequest = RetomarRequest(),
                authorization: Optional[str] = Header(default=None)):
        r = _runner(construccion_id, authorization)
        return r.retomar(session_key=(body.session_key or None))

    # ── validar tools escritas/editadas a mano (mismo candado 5/5) ────────────────
    @router.post("/construcciones/{construccion_id}/tools/validar")
    def validar_tools(construccion_id: str, body: ValidarToolsRequest,
                      authorization: Optional[str] = Header(default=None)):
        r = _runner(construccion_id, authorization)
        if not body.tools:
            raise HTTPException(status_code=400, detail={"error": "sin_tools"})
        _rate_ok(r.snap.pedido.get("puppet_id") or "anon")
        session, provider = _armar_sesion(r, forma=body.forma, cred=body.cred)
        from inspection.mesa import consola
        out = consola.validar_tools(session, provider, body.tools)
        return out

    # ── consola de prueba por tool (dry-run / read real / write gated) ────────────
    @router.post("/construcciones/{construccion_id}/tools/probar")
    def probar_tool(construccion_id: str, body: ProbarToolRequest,
                    authorization: Optional[str] = Header(default=None)):
        r = _runner(construccion_id, authorization)
        _rate_ok(r.snap.pedido.get("puppet_id") or "anon")
        session, provider = _armar_sesion(r, forma=body.forma, cred=body.cred)
        from inspection.mesa import consola
        return consola.probar_tool(session, provider, body.tool, body.args or {},
                                   execute=bool(body.execute))

    # ── equipar (emit + registro, curado por keep[]) ───────────────────────────────
    @router.post("/construcciones/{construccion_id}/equipar")
    def equipar(construccion_id: str, body: EquiparRequest = EquiparRequest(),
                authorization: Optional[str] = Header(default=None)):
        r = _runner(construccion_id, authorization)
        belt_ref = r.snap.inventario.belt_ref
        if not belt_ref:
            raise HTTPException(status_code=409, detail={
                "error": "sin_pieza",
                "detail": "todavía no hay un MCP construido para equipar (retoma y termina la "
                          "construcción, o valida tools a mano primero)."})
        # el registro real en el puppet ya lo hizo el motor al forjar (register_into_puppet);
        # acá confirmamos y devolvemos la pieza (la curación por keep[] se aplica en el front al
        # componer la receta — belt_refs[] ya trae el belt_ref del MCP construido).
        return {"ok": True, "belt_ref": belt_ref,
                "server": r.snap.inventario.identidad.get("server"),
                "puppet_id": r.snap.inventario.puppet_id,
                "keep": body.keep or [t.get("name") for t in r.snap.inventario.tools_validadas]}

    # ── cancelar → borrador ────────────────────────────────────────────────────────
    @router.delete("/construcciones/{construccion_id}")
    def cancelar(construccion_id: str, authorization: Optional[str] = Header(default=None)):
        r = _runner(construccion_id, authorization)
        with r._lock:
            r.snap.estado = "pausada"
            r._emit("construccion.pausada", motivo="cancelada")
            r._persistir()
        return {"ok": True, "estado": "pausada", "retomable": True,
                "construccion_id": construccion_id}

    return router


def _armar_sesion(runner, *, forma: Optional[str], cred: Optional[str]):
    """Arma (session, provider) para validar/probar tools a mano, reusando provider_and_auth.
    La credencial puede venir en el request o del vault (cred_ref del pedido)."""
    from app.phase1.forge_router import provider_and_auth, resolve_forma
    if cred:
        runner.set_credencial(cred)
    if runner._cred is None:
        runner._cred = runner._leer_cred_vault()
    forma_norm = resolve_forma(forma or runner.snap.pedido.get("forma") or "token")
    body = runner._forge_request(seed_forma=forma_norm)
    try:
        provider, _ = provider_and_auth(forma_norm, body, runner.principal, runner._slug_de())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail={"error": "sesion_invalida", "detail": str(e)})
    if provider is None:
        # Forma 1 token-en-query: el motor arma el default. Para validar a mano necesitamos una
        # sesión concreta → construimos el TMDBTokenSession real.
        from inspection.loop.session import TMDBTokenSession
        from inspection.loop.guard import PublicHTTPGuard, declared_target_guard
        guard = (declared_target_guard(body.url) if runner.snap.pedido.get("local_target")
                 else PublicHTTPGuard())
        provider = TMDBTokenSession(
            body.url, runner._cred or "", runner.principal, runner._slug_de(),
            auth_param=body.auth_param, validate_path=body.validate_path,
            validate_query=body.validate_query, guard=guard)
    try:
        session = provider.acquire()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=422, detail={
            "error": "puerta_no_abre",
            "detail": f"no se pudo abrir la sesión para probar tools: {e}"})
    return session, provider


__all__ = ["build_mesa_router"]
