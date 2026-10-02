"""
resolve_router.py — EL RIEL NUEVO: "servicio + credencial" → pieza equipada (FASE 1 · C7).

Pone ADELANTE del BYO-MCP el resolver que le faltaba al producto: el usuario dice un NOMBRE
de servicio ("stripe") + su credencial, y el sistema ENCUENTRA el MCP que ya existe (registro
oficial + matcher de similitud anti-impostor), le inyecta la credencial DESDE EL VAULT, lo
valida vivo y lo equipa — sin pegar un MCP a mano.

  GET  /v1/resolve/preview?service=stripe   → buscar+matchear+resolver (SIN credencial):
        muestra el MCP encontrado y dónde va la key, para que la UI pida la credencial.
  POST /v1/resolve                          → el flujo completo de 6 pasos con credencial:
        guarda la credencial CIFRADA en el vault → la lee de vuelta (round-trip por el
        vault, no del request) → valida vivo → equipa en el puppet del usuario.

SEGURIDAD:
  - El secreto se cifra Fernet en la tabla `keys` (repo.upsert_key); la VALIDACIÓN usa el
    secreto LEÍDO DEL VAULT (credential_broker.make_user_resolver), no el del request.
  - La belt forjada guarda un PLACEHOLDER ${VAR}, nunca el secreto (ver mcp_resolver).
  - puppet del usuario de la sesión (anti-IDOR); namespace por user_id real, nunca anon.
  - credencial mala → 401 propagado del MCP → 422 honesto, CERO pieza colocada.
  - servicio sin MCP confiable → 404 "no encontrado", nunca un MCP equivocado.
"""
from __future__ import annotations

import sys
import secrets
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

_REPO_ROOT = Path(__file__).resolve().parents[4]
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
_PLATFORM = _REPO_ROOT / "platform"
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection.space_access import SpaceAccessError, claim_space, validate_space_id


class ResolvePreviewRequest(BaseModel):
    service: str


class ResolveRequest(BaseModel):
    service: str                       # nombre del servicio: "stripe", "github", "airtable"…
    credential: Optional[str] = None   # la credencial del usuario (va al vault cifrada)
    puppet_id: Optional[str] = None    # dónde queda equipada la pieza (scopeada al user)
    space_id: Optional[str] = None
    allowed_tools: Optional[list[str]] = None


def _bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    a = authorization.strip()
    return a[7:].strip() if a.lower().startswith("bearer ") else a


def _session_user(authorization: Optional[str]) -> Optional[str]:
    from app.phase1 import repo
    return repo.session_owner(_bearer(authorization))


def _require_owned_puppet(puppet_id: str, user_id: Optional[str]) -> None:
    if not user_id:
        raise HTTPException(status_code=401, detail={"error": "no_session",
            "detail": "Inicia sesión para equipar una pieza en tu puppet."})
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
            "detail": "ese puppet no es tuyo"})


def build_resolve_router(*, get_conn=None) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["resolve"])

    @router.get("/resolve/preview")
    def resolve_preview(service: str):
        """Pasos 1-3 SIN credencial: ¿hay un MCP confiable para este servicio y dónde va la
        key? La UI lo usa para mostrar 'encontré X → conecta tu credencial'."""
        from inspection import mcp_resolver
        try:
            r = mcp_resolver.resolve_service(service)
        except mcp_resolver.RegistryUnavailable as e:
            # [T-3] registro caído ≠ inexistente → 503 (reintentá), NUNCA 404 "no existe".
            raise HTTPException(status_code=503, detail={"error": "registry_unreachable",
                "service": service, "detail": str(e), "retry": True})
        except mcp_resolver.NotFound as e:
            raise HTTPException(status_code=404, detail={"error": "no_encontrado",
                "service": service, "detail": str(e)})
        except mcp_resolver.ResolveError as e:
            raise HTTPException(status_code=502, detail={"error": "resolve_error",
                "service": service, "detail": str(e)})
        spec = r["spec"]
        return {
            "found": True, "service": service, "server_name": r["server_name"],
            "source": r["source"], "vendor_kind": r.get("vendor_kind"),
            # [T-3] from_cache=True → el registro estaba caído y ésta es una resolución previa
            # validada (degradación graceful honesta), no un hallazgo fresco. La UI lo marca.
            "from_cache": bool(r.get("from_cache")), "registry_down": bool(r.get("registry_down")),
            "reason": r.get("reason"), "ranked": r.get("ranked", []),
            "credential": {
                "needed": spec.get("needs_credential", True),
                "where": ("header: " + spec.get("header_name", "")) if spec["transport"] == "http"
                         else ("env: " + str(spec.get("package_env_var"))),
                "transport": spec["transport"],
                "endpoint": spec.get("url") or spec.get("command"),
            },
        }

    @router.post("/resolve", status_code=200)
    def resolve(body: ResolveRequest, authorization: Optional[str] = Header(default=None)):
        """Flujo completo de 6 pasos. Síncrono (corre en threadpool) para feedback inmediato;
        emite el ciclo al space para que el Cuarto lo anime con el MISMO vocabulario del BYO."""
        user_id = _session_user(authorization)
        if body.puppet_id:
            _require_owned_puppet(body.puppet_id, user_id)
        service = (body.service or "").strip()
        if not service:
            raise HTTPException(status_code=400, detail={"error": "service_vacio"})
        # [T9-safety] rate-limit por sujeto SIEMPRE (defense-in-depth)
        try:
            from safety import rate_limit
            allowed, info = rate_limit.check_and_consume(user_id or "anonymous-dev", bucket="recon")
            if not allowed:
                raise HTTPException(status_code=429,
                                    detail={"error": "rate-limit del resolver", **info})
        except ImportError:
            pass

        try:
            space_id = validate_space_id(
                (body.space_id or "").strip() or f"resolve-{secrets.token_hex(12)}")
            claim_space(_ESPACIOS, space_id, owner_id=user_id, public=user_id is None)
        except SpaceAccessError as exc:
            raise HTTPException(status_code=422,
                                detail={"error": "space_id_invalid", "detail": str(exc)}) from exc

        from inspection import mcp_resolver
        from app.phase1 import repo as _repo, credential_broker

        # emitter del space (anima detectado → analizando → sintetizada → equipada)
        emitter = None
        try:
            from inspection.bridge import SpaceEmitter
            emitter = SpaceEmitter(space_id, str(_ESPACIOS), owner_id=user_id,
                                   public=user_id is None, claim=True)
            emitter.software_detectado(label=f"Servicio: {service}", url="", title="resolve")
            emitter.inspeccion_analizando()
        except Exception:
            emitter = None

        provider = mcp_resolver.provider_for(service)
        _get_conn = get_conn or _repo.get_conn

        # PASOS 1-3: BUSCAR → MATCHER → RESOLVER PAQUETE. Fail-fast: si no hay MCP confiable,
        # 404 honesto SIN tocar el vault (no guardamos credencial de un servicio que no equipa).
        try:
            resolution = mcp_resolver.resolve_service(service)
        except mcp_resolver.RegistryUnavailable as e:
            # [T-3] registro caído ≠ inexistente → 503 (reintentá), NUNCA 404 "no existe".
            if emitter is not None:
                emitter.error(stage="resolve.registro", detail=str(e)); emitter.close()
            raise HTTPException(status_code=503, detail={"error": "registry_unreachable",
                "service": service, "detail": str(e), "retry": True})
        except mcp_resolver.NotFound as e:
            if emitter is not None:
                emitter.error(stage="resolve.buscar", detail=str(e)); emitter.close()
            raise HTTPException(status_code=404, detail={"error": "no_encontrado",
                "service": service, "detail": str(e)})
        except mcp_resolver.ResolveError as e:
            if emitter is not None:
                emitter.error(stage="resolve.resolver", detail=str(e)); emitter.close()
            raise HTTPException(status_code=502, detail={"error": "resolve_error",
                "service": service, "detail": str(e)})

        # PASO 4 INYECTAR: la credencial del request → VAULT cifrado (Fernet). La validación de
        # abajo la lee DE VUELTA del vault (credential_broker, no el request) → round-trip real.
        secret_from_vault = None
        needs = resolution["spec"].get("needs_credential", True)
        if body.credential:
            if not user_id:
                raise HTTPException(status_code=401, detail={"error": "no_session",
                    "detail": "Inicia sesión para guardar tu credencial en el vault."})
            conn0 = _get_conn()
            try:
                _repo.upsert_key(conn0, user_id=user_id, provider=provider, secret=body.credential)
            finally:
                conn0.close()
            resolver = credential_broker.make_user_resolver(user_id, get_conn=_get_conn)
            secret_from_vault = resolver(f"keys:{provider}")  # descifra solo en memoria
        if needs and not secret_from_vault:
            raise HTTPException(status_code=400, detail={"error": "falta_credencial",
                "service": service, "server_name": resolution["server_name"],
                "detail": f"{resolution['server_name']} requiere credencial; envía 'credential'."})

        # PASO 5 VALIDAR VIVO + PASO 6 EQUIPAR
        conn = _get_conn() if body.puppet_id else None
        try:
            probe = mcp_resolver.validate_live(
                resolution["spec"], secret_from_vault or "",
                label=resolution["server_name"], allowed_tools=body.allowed_tools)
            equipped = mcp_resolver.equip_resolved(
                resolution, probe, user_id=user_id, puppet_id=body.puppet_id,
                service=service, conn=conn)
        except Exception as e:  # byo_mcp.BYOValidationError / ResolveError / otros
            name = type(e).__name__
            if name == "BYOValidationError":
                if emitter is not None:
                    emitter.error(stage="resolve.validar", detail=str(e)); emitter.close()
                raise HTTPException(status_code=422, detail={"error": "validacion_fallo",
                    "service": service, "server_name": resolution["server_name"],
                    "detail": str(e)})
            if emitter is not None:
                emitter.error(stage="resolve.equipar", detail=str(e)); emitter.close()
            raise HTTPException(status_code=502, detail={"error": "resolve_error",
                "service": service, "detail": str(e)})
        finally:
            if conn is not None:
                conn.close()

        result = {
            "ok": True, "found": True, "validated": True,
            "service": service, "server_name": resolution["server_name"],
            "source": resolution["source"], "vendor_kind": resolution.get("vendor_kind"),
            "match": resolution.get("match"), "ranked": resolution.get("ranked", []),
            "reason": resolution.get("reason"),
            "server_info": probe.get("server_info", {}),
            "tools_detail": [{"name": t["name"], "description": t.get("description", "")[:120]}
                             for t in probe["tools"]],
            **equipped,
        }

        if emitter is not None:
            for c in result.get("cards", []):
                emitter.tool_sintetizada(label=c.get("label") or c.get("id"),
                                         category=c.get("zone", "mesa"),
                                         fields=c.get("tools", []))
            if result.get("registered"):
                for tn in result["tools"]:
                    emitter.tool_equipada(
                        label=result["server_name"], belt_ref=result["belt_ref"],
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
