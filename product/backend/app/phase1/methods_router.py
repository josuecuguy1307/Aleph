"""
methods_router.py — HTTP de la pieza MÉTODO (workflows · ORDEN_METODO.md).

Rutas de esta pieza (contrato exacto del frontend, METODO-FRONT-NOTES.md):
  · CRUD biblioteca:  GET/POST /v1/methods · GET/PUT/DELETE /v1/methods/{id}
  · Equipar por REFERENCIA: GET/POST /v1/puppets/{pid}/methods ·
    DELETE /v1/puppets/{pid}/methods/{mid}
    La referencia vive en recipe.belt.method_refs[] (puppets.config) — espejo de
    agent_refs. Equipar/desequipar = read-modify-write del config con
    validate_recipe + update_config + re-export del puente D3 (sin el re-export,
    el archivo hijo queda stale y los agentes anidados corren con el set VIEJO).

Anti-IDOR: sesión obligatoria (_owner_or_401); método/puppet ajeno == 404
indistinguible. Errores SIEMPRE JSON con detail (el front parsea d.detail).
"""

from __future__ import annotations

import json
import logging
import os
import uuid as _uuid
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.phase1 import methods_repo as mr
from app.phase1 import recipe_validator as rv

_log = logging.getLogger("puppet.methods")

try:
    import aleph_paths
except ImportError:
    import sys
    _platform = Path(__file__).resolve().parents[4] / "platform"
    if str(_platform) not in sys.path:
        sys.path.insert(0, str(_platform))
    import aleph_paths

REPO_ROOT = aleph_paths.resource_root()

_ALEPH_MAX_BYTES = 4 * 1024 * 1024   # tope del body del import (.aleph legítimo es chico)
_ALEPH_MAX_METHODS = 200             # tope de métodos embebidos por archivo


class MethodEquipRequest(BaseModel):
    method_id: str


class MethodStructureRequest(BaseModel):
    text: Optional[str] = None
    filename: Optional[str] = None
    mime: Optional[str] = None
    data_b64: Optional[str] = None
    lang: str = "es"


class MethodProposeEditRequest(BaseModel):
    instruction: str
    method: dict
    lang: str = "es"


class MethodFromRunRequest(BaseModel):
    run_id: str
    lang: str = "es"


class MethodMatchRequest(BaseModel):
    puppet_id: Optional[str] = None
    prompt: str


class MethodAdjustRequest(BaseModel):
    adjust: str
    run_id: Optional[str] = None
    lang: str = "es"


class MethodResumeRequest(BaseModel):
    method: Optional[dict] = None   # el método EDITADO en pausa (única edición en vivo)
    space: Optional[str] = None     # ticket 10 · retoma desde la Sala: la continuación narra por
                                    # este space FRESCO (la Sala lo maneja/streamea) en vez del space
                                    # del run viejo — cuyo events.jsonl ya tiene su 'closed' (el
                                    # consumer replaya-desde-0 y pararía ahí, sin ver la continuación).


class MethodRemedyRequest(BaseModel):
    step_id: Optional[str] = None   # null = el paso trabado vigente
    action: str                     # apply | retry | retry_in | skip | free_text
    minutes: Optional[int] = None
    text: Optional[str] = None


def _bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    a = authorization.strip()
    return a[7:].strip() if a.lower().startswith("bearer ") else (a or None)


def _owner_or_401(authorization: Optional[str]) -> str:
    from app.phase1 import repo
    owner = repo.session_owner(_bearer(authorization))
    if owner is None:
        raise HTTPException(status_code=401,
            detail={"error": "no_session", "detail": "Inicia sesión para ver tus métodos."})
    return str(owner)


def _valid_uuid(value: Optional[str]) -> bool:
    try:
        _uuid.UUID(str(value))
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def _sanitize(s: str) -> str:
    """Quita NUL/caracteres de control (excepto \\t\\n\\r) — hostiles al storage."""
    return "".join(c for c in (s or "") if ord(c) >= 0x20 or c in "\t\n\r")


def _method_404() -> HTTPException:
    return HTTPException(status_code=404,
        detail={"error": "method_not_found", "detail": "Ese método no existe (o no es tuyo)."})


def _es_cliente() -> bool:
    from app.phase1 import repo
    return repo._dbmod().es_cliente()


def _lock_config(conn, puppet_id: str) -> None:
    """Serializa equip/desequip del MISMO puppet, que hacen read-modify-write del config
    (update_config lo reemplaza ENTERO, last-write-wins). [Casa 2 · 2.4]

    PG: advisory lock xact-scoped (`pg_advisory_xact_lock`, se suelta al commit). SQLite:
    no tiene advisory locks —`pg_advisory_xact_lock` NO existe y revienta en ejecución, y
    el traductor no lo caza— así que se toma el write lock con BEGIN IMMEDIATE, que
    serializa igual hasta el commit. Debe ser la PRIMERA sentencia de la conexión: una
    lectura previa abre un snapshot y daría SQLITE_BUSY_SNAPSHOT (gotcha de 2.3)."""
    if _es_cliente():
        conn.raw.execute("BEGIN IMMEDIATE")
    else:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s)::bigint)",
                        (f"mrefs:{puppet_id}",))


def build_methods_router(*, get_conn: Callable[[], Any],
                         events_dir: Optional[Callable[[], Path]] = None) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["methods"])

    def _conn():
        try:
            return get_conn()
        except Exception as exc:
            raise HTTPException(status_code=503,
                detail={"error": "db_unavailable", "detail": str(exc)})

    def _puppet_gate(conn, puppet_id: str, owner: str) -> dict:
        """Puppet del DUEÑO o 404 (ajeno == inexistente). Devuelve el row entero."""
        from app.phase1 import repo
        if not _valid_uuid(puppet_id):
            raise HTTPException(status_code=404,
                detail={"error": "puppet_not_found",
                        "detail": "Esa composición no existe (o no es tuya)."})
        p = repo.get_puppet(conn, puppet_id)
        if not p or str(p.get("owner_id")) != owner:
            raise HTTPException(status_code=404,
                detail={"error": "puppet_not_found",
                        "detail": "Esa composición no existe (o no es tuya)."})
        return p

    def _brain_http(exc) -> HTTPException:
        from app.phase1.method_brain import MethodBrainError
        assert isinstance(exc, MethodBrainError)
        if exc.kind == "vocabulary_unavailable":
            code = 503
        else:
            code = 422 if exc.kind in ("doc_invalid", "run_sin_material") else 502
        return HTTPException(status_code=code,
                             detail={"error": exc.kind, "detail": exc.detail})

    def _validated(method_raw: Any, *, extract_missing: bool = False) -> dict:
        m = mr.normalize_method(method_raw)
        if extract_missing and not isinstance(m.get("requires"), list):
            from app.phase1 import method_brain as mb
            try:
                m["requires"] = mb.extract_requires(m)
            except mb.MethodBrainError as exc:
                raise _brain_http(exc)
        errors, warnings = mr.validate_method(m)
        if errors:
            raise HTTPException(status_code=422,
                detail={"error": "method_invalid", "errors": errors, "warnings": warnings})
        if warnings:
            m["warnings"] = warnings
        return m

    def _backfill_requires(conn, owner: str, method: dict) -> dict:
        """Legado sin requires[] → extractor UNA vez + persistencia inmediata."""
        if isinstance(method.get("requires"), list):
            return method
        filled = _validated(method, extract_missing=True)
        updated = mr.update_method(conn, str(method["id"]), owner, filled)
        if not updated:
            raise _method_404()
        return updated

    def _space_emitter(space_id: Optional[str]):
        """Emitter al espinazo del space (persist-before-emit) para la CONTINUACIÓN
        de un método — mismo events.jsonl que consumía el run original, así la
        Sala/grafo siguen narrando sin canal nuevo. None si no hay space."""
        if not space_id or events_dir is None:
            return None
        try:
            from app.phase1 import event_stream as es
            path = Path(events_dir()) / str(space_id) / "events.jsonl"
            log = es._events_replay().EventLog(path)
        except Exception:
            return None

        def emit(evt: dict) -> None:
            e = dict(evt)
            e["space_id"] = str(space_id)
            try:
                log.append(e)
            except Exception:
                pass
        return emit

    def _export_bridge(puppet: Optional[dict]) -> bool:
        """Re-exporta el puente D3 tras mutar config (patrón PUT /puppets/{id}/config).
        Best-effort: False ⇒ el caller expone bridge_pending (no-fatal)."""
        if not puppet or not puppet.get("id"):
            return False
        try:
            from app.phase1 import agent_catalog
            agent_catalog.export_agent(puppet, REPO_ROOT)
            return True
        except Exception:
            _log.warning("export_agent falló para puppet %s", puppet.get("id"), exc_info=True)
            return False

    def _recalculate(conn, puppet: dict, owner: str) -> list[dict]:
        from app.phase1 import method_match
        return method_match.recalculate(conn, puppet, owner=owner, repo_root=REPO_ROOT)

    # ── CRUD de la biblioteca ────────────────────────────────────────────────

    @router.get("/methods")
    def list_methods(authorization: Optional[str] = Header(default=None)):
        owner = _owner_or_401(authorization)
        conn = _conn()
        try:
            methods = [_backfill_requires(conn, owner, m)
                       for m in mr.list_methods(conn, owner)]
            return {"methods": methods, "total": len(methods)}
        finally:
            conn.close()

    @router.get("/methods/{method_id}")
    def get_method(method_id: str, authorization: Optional[str] = Header(default=None)):
        owner = _owner_or_401(authorization)
        if not _valid_uuid(method_id):
            raise _method_404()
        conn = _conn()
        try:
            m = mr.get_method(conn, method_id, owner)
            if not m:
                raise _method_404()
            return {"method": _backfill_requires(conn, owner, m)}
        finally:
            conn.close()

    @router.post("/methods", status_code=201)
    def create_method(body: dict, authorization: Optional[str] = Header(default=None)):
        owner = _owner_or_401(authorization)
        m = _validated(body, extract_missing=True)
        conn = _conn()
        try:
            return mr.create_method(conn, user_id=owner, method=m)
        finally:
            conn.close()

    @router.put("/methods/{method_id}")
    def update_method(method_id: str, body: dict,
                      authorization: Optional[str] = Header(default=None)):
        owner = _owner_or_401(authorization)
        if not _valid_uuid(method_id):
            raise _method_404()
        m = _validated(body, extract_missing=True)
        conn = _conn()
        try:
            upd = mr.update_method(conn, method_id, owner, m)
            if not upd:
                raise _method_404()
            return upd
        finally:
            conn.close()

    @router.delete("/methods/{method_id}")
    def delete_method(method_id: str, authorization: Optional[str] = Header(default=None)):
        owner = _owner_or_401(authorization)
        if not _valid_uuid(method_id):
            raise _method_404()
        conn = _conn()
        try:
            if not mr.delete_method(conn, method_id, owner):
                raise _method_404()
            return {"ok": True, "id": method_id}
        finally:
            conn.close()

    # ── equipar por REFERENCIA (recipe.belt.method_refs[]) ──────────────────

    def _refs_of(config: dict) -> list[str]:
        belt = config.get("belt")
        if not isinstance(belt, dict):
            return []
        refs = belt.get("method_refs")
        return [r for r in refs if isinstance(r, str)] if isinstance(refs, list) else []

    def _write_refs(conn, puppet: dict, refs: list[str]) -> dict:
        """Escribe belt.method_refs (o la remueve si queda vacía), valida la receta
        ENTERA antes de tocar DB, persiste (version+1) y re-exporta el puente."""
        from app.phase1 import repo
        config = dict(puppet.get("config") or {})
        belt = config.get("belt")
        if not isinstance(belt, dict):
            raise HTTPException(status_code=422,
                detail={"error": "recipe_invalid",
                        "errors": ["la receta no tiene belt: no se puede equipar un método"]})
        belt = dict(belt)
        if refs:
            belt["method_refs"] = refs
        else:
            belt.pop("method_refs", None)   # condicional aditivo: sin métodos, receta byte-idéntica
        config["belt"] = belt
        try:
            rv.validate_recipe(config, repo_root=REPO_ROOT)
        except rv.RecipeValidationError as exc:
            raise HTTPException(status_code=422,
                detail={"error": "recipe_invalid", "errors": exc.errors, "warnings": exc.warnings})
        updated = repo.update_config(conn, str(puppet["id"]), config)
        if updated is None:
            raise HTTPException(status_code=404,
                detail={"error": "puppet_not_found",
                        "detail": "Esa composición no existe (o no es tuya)."})
        methods = _recalculate(conn, updated, str(puppet["owner_id"]))
        out = {"ok": True, "equipped": refs, "methods": methods}
        if not _export_bridge(updated):
            out["bridge_pending"] = True
        return out

    @router.get("/puppets/{puppet_id}/methods")
    def list_equipped(puppet_id: str, authorization: Optional[str] = Header(default=None)):
        owner = _owner_or_401(authorization)
        conn = _conn()
        try:
            puppet = _puppet_gate(conn, puppet_id, owner)
            refs = _refs_of(puppet.get("config") or {})
            methods, missing = [], []
            for ref in refs:
                m = mr.get_method(conn, ref, owner) if _valid_uuid(ref) else None
                if m:
                    methods.append(_backfill_requires(conn, owner, m))
                else:
                    missing.append(ref)
            # El extractor persistió primero; recién ahora el match puede hablar.
            methods = _recalculate(conn, {**puppet, "config": puppet.get("config") or {}}, owner)
            out: dict[str, Any] = {"methods": methods, "total": len(methods)}
            if missing:
                # honesto: refs colgantes (método borrado / import sin re-mapear)
                out["missing"] = missing
            return out
        finally:
            conn.close()

    @router.post("/puppets/{puppet_id}/methods", status_code=201)
    def equip_method(puppet_id: str, body: MethodEquipRequest,
                     authorization: Optional[str] = Header(default=None)):
        owner = _owner_or_401(authorization)
        conn = _conn()
        try:
            # serializa equips concurrentes sobre el mismo puppet: update_config
            # reemplaza el config ENTERO (last-write-wins) — sin esto, dos POST
            # paralelos se pisan la lista de refs. Por rol (ver _lock_config).
            _lock_config(conn, puppet_id)
            puppet = _puppet_gate(conn, puppet_id, owner)
            if not _valid_uuid(body.method_id) or not mr.get_method(conn, body.method_id, owner):
                raise _method_404()
            refs = _refs_of(puppet.get("config") or {})
            if body.method_id not in refs:
                refs = refs + [body.method_id]
            return _write_refs(conn, puppet, refs)
        finally:
            conn.close()

    # ── cerebro: structure / propose_edit / adjust · determinista: from_run / match ──

    @router.post("/methods/structure")
    def structure(body: MethodStructureRequest,
                  authorization: Optional[str] = Header(default=None)):
        """«Traer mi proceso»: texto/PDF/Word/imagen → draft de Method (SIN id).
        Fallo del cerebro = error honesto tipado, JAMÁS un draft inventado."""
        _owner_or_401(authorization)
        from app.phase1 import method_brain as mb
        try:
            draft = mb.structure_draft(text=body.text, filename=body.filename,
                                       mime=body.mime, data_b64=body.data_b64,
                                       lang=body.lang or "es")
        except mb.MethodBrainError as exc:
            raise _brain_http(exc)
        return {"draft": draft}

    @router.post("/methods/{method_id}/propose_edit")
    def propose_edit(method_id: str, body: MethodProposeEditRequest,
                     authorization: Optional[str] = Header(default=None)):
        """«Editar conversando»: instrucción → pasos NUEVOS COMPLETOS (el diff lo
        pinta el front; aceptar/rechazar es del humano). method_id puede ser
        'nuevo' (método aún no guardado): el método viaja ENTERO en el body y
        acá no se toca la DB — default no-mutar ante cualquier duda."""
        _owner_or_401(authorization)
        from app.phase1 import method_brain as mb
        try:
            out = mb.propose_edit(body.method, body.instruction, lang=body.lang or "es")
        except mb.MethodBrainError as exc:
            raise _brain_http(exc)
        return {"summary": out["summary"], "proposal": {"steps": out["steps"]}}

    @router.post("/methods/from_run", status_code=201)
    def from_run(body: MethodFromRunRequest,
                 authorization: Optional[str] = Header(default=None)):
        """Guardar-desde-run: congela el plan/las tools REALES del run como método
        en la biblioteca (determinista, cero LLM — el plan del run ES el método).
        Idempotente por run_id: dos POST devuelven el MISMO método."""
        owner = _owner_or_401(authorization)
        from app.phase1 import repo
        from app.phase1 import method_brain as mb
        if not _valid_uuid(body.run_id):
            raise HTTPException(status_code=404,
                detail={"error": "run_not_found", "detail": "Ese run no existe (o no es tuyo)."})
        conn = _conn()
        try:
            run = repo.get_run(conn, body.run_id)
            if not run or str(run.get("user_id")) != owner:
                raise HTTPException(status_code=404,
                    detail={"error": "run_not_found", "detail": "Ese run no existe (o no es tuyo)."})
            # idempotencia server-side: si este run ya se congeló, devolver ese método
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM methods WHERE user_id = %s "
                    "AND spec->'source'->>'run_id' = %s LIMIT 1",
                    (owner, body.run_id))
                row = cur.fetchone()
            if row:
                return {"method": mr.get_method(conn, str(row[0]), owner)}
            events: list[dict] = []
            space_id = run.get("space_id")
            if space_id and events_dir is not None:
                path = Path(events_dir()) / str(space_id) / "events.jsonl"
                if path.exists():
                    for line in path.read_text(encoding="utf-8").splitlines():
                        try:
                            events.append(json.loads(line))
                        except Exception:
                            continue
            try:
                draft = mb.freeze_from_run(events, run_id=body.run_id,
                                           intent=run.get("intent"), lang=body.lang or "es")
            except mb.MethodBrainError as exc:
                raise _brain_http(exc)
            draft = _validated(draft, extract_missing=True)
            created = mr.create_method(conn, user_id=owner, method=draft)
            return {"method": created}
        finally:
            conn.close()

    @router.post("/methods/match")
    def match(body: MethodMatchRequest,
              authorization: Optional[str] = Header(default=None)):
        """Propuesta contextual de la Sala. FAIL-OPEN por contrato (timeout 1.2s
        del front): léxico determinista sobre los métodos EQUIPADOS del puppet,
        cero LLM en el camino caliente; cualquier duda ⇒ {match: null}."""
        owner = _owner_or_401(authorization)
        if not body.puppet_id or not _valid_uuid(body.puppet_id):
            return {"match": None}
        from app.phase1 import repo
        conn = _conn()
        try:
            p = repo.get_puppet(conn, body.puppet_id)
            if not p or str(p.get("owner_id")) != owner:
                return {"match": None}
            refs = _refs_of(p.get("config") or {})
            for ref in refs:
                m = mr.get_method(conn, ref, owner) if _valid_uuid(ref) else None
                if m:
                    _backfill_requires(conn, owner, m)
            # GATE: sólo los completos llegan al matcher léxico de la Sala.
            from app.phase1 import method_match
            methods = method_match.eligible_for_sala(_recalculate(conn, p, owner))
            best = mr.match_method(methods, body.prompt)
            if not best:
                return {"match": None}
            out = {"method_id": best["id"], "name": best.get("name") or best["id"]}
            lra = best.get("last_run_at")
            if lra is not None:
                try:
                    from datetime import datetime, timezone
                    now = datetime.now(timezone.utc)
                    out["last_run_days"] = max(0, (now - lra).days)
                except Exception:
                    pass
            return {"match": out}
        finally:
            conn.close()

    @router.post("/methods/{method_id}/adjust_permanent")
    def adjust_permanent(method_id: str, body: MethodAdjustRequest,
                         authorization: Optional[str] = Header(default=None)):
        """«¿Guardar cambio permanente?» tras un run ajustado: aplica el ajuste al
        método de la biblioteca vía el cerebro y persiste. Fallo ⇒ el método NO
        se toca (default no-mutar) y el error viaja honesto."""
        owner = _owner_or_401(authorization)
        if not _valid_uuid(method_id):
            raise _method_404()
        from app.phase1 import method_brain as mb
        conn = _conn()
        try:
            m = mr.get_method(conn, method_id, owner)
            if not m:
                raise _method_404()
            try:
                out = mb.propose_edit(m, body.adjust, lang=body.lang or "es")
            except mb.MethodBrainError as exc:
                raise _brain_http(exc)
            m2 = dict(m)
            m2["steps"] = out["steps"]
            m2 = _validated(m2)
            log = list(m.get("adjust_log") or [])
            log.append({"adjust": body.adjust[:300], "run_id": body.run_id,
                        "summary": out["summary"]})
            m2["adjust_log"] = log[-20:]
            upd = mr.update_method(conn, method_id, owner, m2)
            if not upd:
                raise _method_404()
            return {"ok": True, "summary": out["summary"], "method": upd}
        finally:
            conn.close()

    @router.delete("/puppets/{puppet_id}/methods/{method_id}")
    def unequip_method(puppet_id: str, method_id: str,
                       authorization: Optional[str] = Header(default=None)):
        owner = _owner_or_401(authorization)
        conn = _conn()
        try:
            _lock_config(conn, puppet_id)          # por rol (ver _lock_config)
            puppet = _puppet_gate(conn, puppet_id, owner)
            refs = _refs_of(puppet.get("config") or {})
            if method_id not in refs:
                raise _method_404()
            return _write_refs(conn, puppet, [r for r in refs if r != method_id])
        finally:
            conn.close()

    # ── export / import .aleph + MURO PREMIUM (§7) ──────────────────────────
    #
    # Free: .aleph vivo SIEMPRE completo + PDF simple. Premium: export TOTAL
    # (docx/md/checklist/json crudo) + bóveda — fail-closed, staged por env
    # PUPPET_ENFORCE_METHOD_EXPORT (patrón exacto del muro de construcción).
    # Lo acumulado (stats/historial/adjust_log) NO viaja en NINGÚN export.

    _ENFORCE_EXPORT_ENV = "PUPPET_ENFORCE_METHOD_EXPORT"

    def _enforce_method_premium(feature: str, authorization: Optional[str]) -> Optional[dict]:
        """None = permitido; dict = rechazo honesto (402 en el caller).

        [Step 5 · P7] ACTIVO POR DEFAULT. [Casa 2 · Fase 4 · 4.3] El opt-out por env vale SÓLO
        en dev/CI: en un build SHIPPED (public/founder) el muro va BAKED — apagar la env NO
        regala premium-local (S3: el gating de premium-local se resuelve en COMPILACIÓN, no en
        runtime con una env que el usuario controla). El tier SIEMPRE sale de la CUENTA
        (server-side), fail-closed ante cualquier fallo."""
        import sys
        _plat = str(REPO_ROOT / "platform")
        if _plat not in sys.path:
            sys.path.insert(0, _plat)
        import build_id
        if build_id.is_dev() and os.environ.get(_ENFORCE_EXPORT_ENV, "1").strip().lower() in (
                "0", "false", "no", "off"):
            return None  # OPT-OUT: SÓLO en dev. Un build shipped IGNORA la env → muro puesto.
        try:
            from gates import tier_gate as _tg
            from app.phase1 import repo
            tok = _bearer(authorization)
            owner = repo.session_owner(tok) if tok else None
            tier = None
            if owner:
                c = repo.get_conn()
                try:
                    tier = _tg.resolve_account_tier(c, owner, repo)
                finally:
                    c.close()
            return _tg.require_feature(feature, tier)
        except Exception:
            return {"error": "El export total es una función Premium (no se pudo "
                             "verificar tu plan — por seguridad se niega).",
                    "feature": feature, "min_tier": "basico", "tier_gated": True}

    _FREE_FORMATS = ("aleph", "pdf")
    _PREMIUM_FORMATS = ("md", "markdown", "checklist", "json", "docx", "word")

    @router.get("/methods/{method_id}/export")
    def export_method(method_id: str, format: str = "aleph", lang: str = "es",
                      authorization: Optional[str] = Header(default=None)):
        from fastapi import Response
        from app.phase1 import method_export as mx
        owner = _owner_or_401(authorization)
        if not _valid_uuid(method_id):
            raise _method_404()
        fmt = (format or "aleph").strip().lower()
        if fmt not in _FREE_FORMATS + _PREMIUM_FORMATS:
            raise HTTPException(status_code=422,
                detail={"error": "bad_format",
                        "detail": f"format ∈ {'|'.join(_FREE_FORMATS + _PREMIUM_FORMATS)}"})
        if fmt in _PREMIUM_FORMATS:
            _rej = _enforce_method_premium("method_export_total", authorization)
            if _rej is not None:
                raise HTTPException(status_code=402, detail=_rej)
        conn = _conn()
        try:
            m = mr.get_method(conn, method_id, owner)
        finally:
            conn.close()
        if not m:
            raise _method_404()
        slug = "".join(c if c.isalnum() or c in "-_" else "-"
                       for c in (m.get("name") or "metodo").lower())[:48] or "metodo"
        if fmt == "aleph":
            body = json.dumps(mx.method_to_aleph(m), ensure_ascii=False, indent=2)
            return Response(content=body, media_type="application/json",
                            headers={"Content-Disposition":
                                     f'attachment; filename="{slug}.aleph"'})
        if fmt == "pdf":
            return Response(content=mx.to_pdf(m, lang), media_type="application/pdf",
                            headers={"Content-Disposition":
                                     f'attachment; filename="{slug}.pdf"'})
        if fmt in ("md", "markdown"):
            return Response(content=mx.to_markdown(m, lang), media_type="text/markdown",
                            headers={"Content-Disposition":
                                     f'attachment; filename="{slug}.md"'})
        if fmt == "checklist":
            return Response(content=mx.to_checklist(m, lang), media_type="text/plain",
                            headers={"Content-Disposition":
                                     f'attachment; filename="{slug}.txt"'})
        if fmt == "json":
            return Response(content=mx.to_json_raw(m), media_type="application/json",
                            headers={"Content-Disposition":
                                     f'attachment; filename="{slug}.json"'})
        try:
            body = mx.to_docx(m, lang)
        except mx.AlephError as exc:
            raise HTTPException(status_code=501,
                detail={"error": exc.kind, "detail": exc.detail})
        return Response(
            content=body,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{slug}.docx"'})

    @router.get("/methods/{method_id}/vault")
    def method_vault(method_id: str, authorization: Optional[str] = Header(default=None)):
        """Bóveda del servidor (§7): la FEATURE está registrada y el muro cerrado;
        la implementación (versiones/historial/sync) no es v1 — honesto 501."""
        _owner_or_401(authorization)
        _rej = _enforce_method_premium("method_vault", authorization)
        if _rej is not None:
            raise HTTPException(status_code=402, detail=_rej)
        raise HTTPException(status_code=501,
            detail={"error": "vault_not_built",
                    "detail": "La bóveda de métodos todavía no está construida (v1)."})

    @router.get("/puppets/{puppet_id}/export.aleph")
    def export_agent_aleph(puppet_id: str,
                           authorization: Optional[str] = Header(default=None)):
        """El .aleph vivo del AGENTE — free, siempre completo: receta CON canvas,
        SIN keys, métodos equipados EMBEBIDOS (el archivo es autónomo)."""
        from fastapi import Response
        from app.phase1 import method_export as mx
        owner = _owner_or_401(authorization)
        conn = _conn()
        try:
            puppet = _puppet_gate(conn, puppet_id, owner)
            refs = _refs_of(puppet.get("config") or {})
            methods = [_backfill_requires(conn, owner, m)
                       for r in refs if _valid_uuid(r)
                       for m in [mr.get_method(conn, r, owner)] if m]
        finally:
            conn.close()
        slug = "".join(c if c.isalnum() or c in "-_" else "-"
                       for c in (puppet.get("name") or "agente").lower())[:48] or "agente"
        body = json.dumps(mx.agent_to_aleph(puppet, methods), ensure_ascii=False, indent=2)
        return Response(content=body, media_type="application/json",
                        headers={"Content-Disposition":
                                 f'attachment; filename="{slug}.aleph"'})

    @router.post("/aleph/import", status_code=201)
    def import_aleph(body: dict, authorization: Optional[str] = Header(default=None)):
        """Importa un .aleph (el body ES el archivo). SIEMPRE re-inspeccionado:
        forma validada, UUIDs nuevos server-side, métodos embebidos entran a la
        biblioteca del receptor y belt.method_refs se RE-MAPEAN; los agent_refs
        del origen no resuelven acá → se DROPEAN con reporte (jamás verbatim
        mudo); belts se resuelven contra el catálogo local y lo no-resoluble se
        reporta honesto. `keys` del origen jamás entra."""
        from app.phase1 import method_export as mx
        from app.phase1 import repo
        owner = _owner_or_401(authorization)
        # G2 · tope de tamaño del body (DoS por amplificación autenticado): un .aleph
        # legítimo es chico; abortamos ANTES de procesar un archivo desmesurado.
        try:
            if len(json.dumps(body)) > _ALEPH_MAX_BYTES:
                raise HTTPException(status_code=413,
                    detail={"error": "aleph_too_large",
                            "detail": "El archivo .aleph excede el tamaño máximo."})
        except (TypeError, ValueError):
            raise HTTPException(status_code=422,
                detail={"error": "aleph_invalid", "detail": "El .aleph no es serializable."})
        try:
            a_type, payload = mx.parse_aleph(body)
        except mx.AlephError as exc:
            raise HTTPException(status_code=422,
                detail={"error": exc.kind, "detail": exc.detail})

        conn = _conn()
        try:
            if a_type == "method":
                m = _validated(payload["method"], extract_missing=True)
                m.pop("id", None)
                created = mr.create_method(conn, user_id=owner, method=m)
                return {"ok": True, "type": "method", "method": created}

            # type=agent · deep-strip de credenciales (keys top-level Y byok_ref
            # anidados en model.*/keys.*): un .aleph ajeno jamás inyecta secretos.
            recipe = mx._strip_secrets(dict(payload.get("recipe") or {}))
            recipe["schema_version"] = "v1"
            report: dict[str, Any] = {}
            raw_methods = payload.get("methods") or []
            if not isinstance(raw_methods, list) or len(raw_methods) > _ALEPH_MAX_METHODS:
                raise HTTPException(status_code=422,
                    detail={"error": "aleph_invalid",
                            "detail": f"El .aleph trae demasiados métodos (máx {_ALEPH_MAX_METHODS})."})

            # G1 · ATOMICIDAD: validar TODA la forma (métodos + receta) ANTES de crear
            # nada — una receta/método inválido JAMÁS deja la biblioteca poblada de basura.
            pre: list[tuple[str, dict]] = []
            for entry in raw_methods:
                rawm = (entry or {}).get("method") if isinstance(entry, dict) else None
                ref = str((entry or {}).get("ref") or "") if isinstance(entry, dict) else ""
                if not isinstance(rawm, dict):
                    report.setdefault("methods_invalid", []).append(ref or "?")
                    continue
                try:
                    m = _validated(rawm, extract_missing=True)
                except HTTPException:
                    report.setdefault("methods_invalid", []).append(ref or "?")
                    continue
                m.pop("id", None)
                pre.append((ref, m))
            # la receta se valida con method_refs VACIADO (los refs finales serán ids
            # nuevos, misma forma-string): captura 'falta meta/model/belt' SIN escribir.
            _belt0 = recipe.get("belt")
            _probe = dict(recipe)
            if isinstance(_belt0, dict):
                _pb = {k: v for k, v in _belt0.items() if k not in ("method_refs", "agent_refs")}
                _probe["belt"] = _pb
            try:
                rv.validate_recipe(_probe, repo_root=REPO_ROOT)
            except rv.RecipeValidationError as exc:
                raise HTTPException(status_code=422,
                    detail={"error": "recipe_invalid", "errors": exc.errors,
                            "warnings": exc.warnings})

            # forma OK → crear TODO en UNA transacción (commit=False + un solo commit
            # al final): si create_puppet falla (p.ej. NUL en un campo que se coló al
            # storage), el rollback deja CERO métodos huérfanos. G1·atomicidad real.
            id_map: dict[str, str] = {}
            imported = 0
            for ref, m in pre:
                created = mr.create_method(conn, user_id=owner, method=m, commit=False)
                imported += 1
                if ref:
                    id_map[ref] = created["id"]
            belt = recipe.get("belt")
            if isinstance(belt, dict):
                belt = dict(belt)
                old_refs = [r for r in (belt.get("method_refs") or []) if isinstance(r, str)]
                new_refs = [id_map[r] for r in old_refs if r in id_map]
                dropped_m = [r for r in old_refs if r not in id_map]
                if new_refs:
                    belt["method_refs"] = new_refs
                else:
                    belt.pop("method_refs", None)
                if dropped_m:
                    report["method_refs_dropped"] = dropped_m
                # agent_refs del ORIGEN: apuntan a catalog/agents/ de OTRA máquina →
                # en el receptor serían no-ops silenciosos; se dropean con reporte
                if belt.get("agent_refs"):
                    report["agent_refs_dropped"] = list(belt.get("agent_refs") or [])
                    belt.pop("agent_refs", None)
                recipe["belt"] = belt

            # revalidación final (los refs re-mapeados son ids nuevos; forma idéntica)
            try:
                rv.validate_recipe(recipe, repo_root=REPO_ROOT)
            except rv.RecipeValidationError as exc:
                raise HTTPException(status_code=422,
                    detail={"error": "recipe_invalid", "errors": exc.errors,
                            "warnings": exc.warnings})

            # re-inspección de belts contra el catálogo LOCAL (Motor B, capa
            #    barata): lo que no resuelve se reporta — el receptor decide
            #    curarlo/conectarlo por los flujos existentes (/v1/inspect/*)
            resolved, missing = [], []
            try:
                import sys
                _asmdir = str(REPO_ROOT / "platform" / "assembler")
                if _asmdir not in sys.path:
                    sys.path.insert(0, _asmdir)
                import belt_resolver as _br
                belt_cfg = recipe.get("belt") or {}
                _brefs = belt_cfg.get("belt_refs") or \
                    ([belt_cfg["belt_ref"]] if belt_cfg.get("belt_ref") else [])
                for bref in _brefs:
                    try:
                        _br.resolve_belt_ref(bref, REPO_ROOT)
                        resolved.append(bref)
                    except Exception:
                        missing.append(bref)
            except Exception:
                pass
            report["belts_resolved"] = resolved
            if missing:
                report["belts_missing"] = missing

            # nombre/nicho saneados (sin NUL/control chars) — defensa del storage
            _pname = _sanitize(str(payload.get("name") or "Agente importado"))[:80] or "Agente importado"
            _pnicho = _sanitize(str(payload.get("nicho") or "general"))[:40] or "general"
            try:
                puppet = repo.create_puppet(
                    conn, owner_id=owner, name=_pname, nicho=_pnicho,
                    config=recipe, commit=False)
                conn.commit()   # ← ÚNICO commit: métodos + puppet entran JUNTOS o nada
            except HTTPException:
                raise
            except Exception as exc:
                try:
                    conn.rollback()   # métodos creados en esta txn se DESHACEN (cero huérfanos)
                except Exception:
                    pass
                raise HTTPException(status_code=422,
                    detail={"error": "aleph_unstorable",
                            "detail": f"El .aleph no se pudo persistir: {type(exc).__name__}"})
            if not _export_bridge(puppet):
                puppet["bridge_pending"] = True
            # El requires[] importado viaja intacto, pero el veredicto pertenece al belt
            # DEL RECEPTOR y por eso se recalcula después de crear ese agente.
            method_states = _recalculate(conn, puppet, owner)
            return {"ok": True, "type": "agent", "puppet": puppet,
                    "methods_imported": imported, "method_states": method_states,
                    "reinspection": report}
        finally:
            conn.close()

    # ── control del run dirigido: pause / resume / remedy (§5 + §6) ─────────
    #
    # Dos regímenes, mismo contrato HTTP:
    #  · run VIVO  → se escribe el CONTROL-PLANE durable (method_runs.control) y
    #    el arnés lo consume entre turnos (la espera bloqueante vive en el arnés).
    #  · run YA CORTADO (el arnés cortó honesto: waiting_checkpoint / paused_* /
    #    scheduled_retry) → CONTINUACIÓN server-side: un run nuevo re-inyecta el
    #    estado durable (el arnés es dueño del estado — el proceso no importa) y
    #    narra por el MISMO space (la Sala/grafo captan el run_id nuevo por eventos).

    def _method_run_gate(conn, run_id: str, owner: str) -> dict:
        if not _valid_uuid(run_id):
            raise HTTPException(status_code=404,
                detail={"error": "method_run_not_found",
                        "detail": "Ese run no tiene método (o no es tuyo)."})
        mrun = mr.get_method_run(conn, run_id)
        if not mrun or str(mrun.get("user_id")) != owner:
            raise HTTPException(status_code=404,
                detail={"error": "method_run_not_found",
                        "detail": "Ese run no tiene método (o no es tuyo)."})
        return mrun

    _RESUMABLE = ("paused_user", "waiting_checkpoint", "paused_failure", "scheduled_retry",
                  "paused_incomplete")   # ticket 10 · pausa retomable "quedó a mitad" (paso manual)
    _LIVE_TTL_S = 180.0   # > duración de un turno (Opus ~60s); el arnés late durante las esperas

    def _run_is_live(conn, run_id: str, mrun: Optional[dict] = None) -> bool:
        """El run está VIVO (el arnés lo lee y consume control) sólo si el run sigue
        'running' Y la fila del método latió hace poco. Un run zombie (proceso muerto,
        status 'running' pegado) queda stale → se trata como no-vivo (recuperable por
        continuación) en vez de escribir control que nadie va a consumir."""
        from app.phase1 import repo
        run = repo.get_run(conn, run_id)
        if not (run and run.get("status") == "running"):
            return False
        m = mrun or mr.get_method_run(conn, run_id)
        ua = (m or {}).get("updated_at")
        if ua is None:
            return True
        try:
            from datetime import datetime, timezone
            return (datetime.now(timezone.utc) - ua).total_seconds() <= _LIVE_TTL_S
        except Exception:
            return True

    def _spawn_continuation(conn, mrun: dict, owner: str, *,
                            resume_spec: Optional[dict] = None,
                            control_seed: Optional[dict] = None,
                            space_override: Optional[str] = None) -> dict:
        """Relanza el método desde su estado durable. Requiere agente GUARDADO
        (métodos = puppets equipados, contrato del front). El costo del run nuevo
        sale igual por cost-events scopeados a user/run. `space_override` (ticket 10):
        la continuación narra por ESE space (la Sala lo maneja) en vez del space del
        run viejo — default = el mismo del run viejo (retoma desde el grafo)."""
        from app.phase1 import repo
        _emit_space = space_override or mrun.get("space_id")
        old_run_id = str(mrun["run_id"])
        puppet_id = str(mrun.get("puppet_id") or "") or None
        if not puppet_id:
            raise HTTPException(status_code=409,
                detail={"error": "resume_requires_saved_agent",
                        "detail": "Este método corrió con un agente sin guardar: "
                                  "guarda el agente para poder reanudar."})
        puppet = repo.get_puppet(conn, puppet_id)
        if not puppet or str(puppet.get("owner_id")) != owner:
            raise HTTPException(status_code=404,
                detail={"error": "puppet_not_found",
                        "detail": "Esa composición no existe (o no es tuya)."})
        old_run = repo.get_run(conn, old_run_id) or {}
        state = dict(mrun.get("state") or {})
        method_id = str(mrun.get("method_id") or "") or None
        if not method_id:
            raise HTTPException(status_code=409,
                detail={"error": "method_deleted",
                        "detail": "El método de este run ya no está en la biblioteca."})

        # H10 · un remedy que quedó pendiente en el control del run viejo (llegó 'live'
        # justo antes del corte, sin que el arnés lo consumiera) se FUNDE al seed en vez
        # de perderse cuando el claim limpia el control.
        if control_seed is None:
            _pending = (mrun.get("control") or {}).get("remedy")
            if isinstance(_pending, dict):
                control_seed = {"remedy": _pending}

        # checkpoint decidido POST-corte: no re-gatear (aprobado) / no revivir (rechazado)
        seed = dict(state)
        if mrun.get("status") == "waiting_checkpoint":
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status, args FROM held_actions WHERE run_id = %s "
                    "AND server = 'metodo' AND tool = 'checkpoint' "
                    "ORDER BY created_at DESC LIMIT 1", (old_run_id,))
                row = cur.fetchone()
            if row:
                h_status, h_args = row[0], (row[1] or {})
                if h_status == "rejected":
                    raise HTTPException(status_code=409,
                        detail={"error": "checkpoint_rejected",
                                "detail": "El checkpoint fue rechazado: el método se detuvo ahí."})
                if h_status == "executed":
                    seed["checkpoint_approved_step"] = h_args.get("step_id")

        # H2 · CLAIM ATÓMICO: sella 'abandoned' SOLO si el status sigue resumable. Dos
        # requests concurrentes (doble-click en Reanudar) → sólo UNO gana; el otro 409.
        if not mr.claim_continuation(conn, old_run_id, list(_RESUMABLE)):
            raise HTTPException(status_code=409,
                detail={"error": "already_resumed",
                        "detail": "Ese método ya se está reanudando."})

        # ganado el claim: recién ahora editamos la biblioteca (edición en pausa =
        # edición del método, referencia viva) y sembramos el remedio.
        if resume_spec is not None:
            m2 = _validated(resume_spec)
            if not mr.update_method(conn, method_id, owner, m2):
                raise _method_404()

        def _go():
            from app.phase1 import credential_broker, executor
            c2 = None
            try:
                c2 = repo.get_conn()
                on_event = _space_emitter(_emit_space)
                out = executor.run_puppet_e2e(
                    dict(puppet.get("config") or {}),
                    str(old_run.get("intent") or "continúa el método"),
                    puppet_id=puppet_id, user_id=owner,
                    space_id=_emit_space, conn=c2,
                    byok_resolver=credential_broker.make_user_resolver(
                        owner, get_conn=repo.get_conn),
                    deadline_s=240.0,
                    approve=lambda *_a, **_k: False,
                    on_event=on_event,
                    lang=str(state.get("lang") or "es"),
                    method_id=method_id,
                    method_seed_state=seed,
                )
            except Exception:
                _log.warning("continuación del método falló (run %s)", old_run_id,
                             exc_info=True)
            finally:
                try:
                    if c2 is not None:
                        c2.close()
                except Exception:
                    pass

        # el control-seed debe existir CUANDO el arnés nuevo lo lea: se siembra en
        # la fila NUEVA — pero el run_id nuevo no existe aún. Solución: el arnés lo
        # consume del seed_state directamente (remedy pre-aplicado acá, misma lógica).
        if control_seed and isinstance(control_seed.get("remedy"), dict):
            rem = control_seed["remedy"]
            att = dict(seed.get("attempts") or {})
            sid = rem.get("step_id")
            if rem.get("action") in ("retry", "apply") and sid:
                att[sid] = 0
                st = dict(seed.get("step_status") or {})
                if st.get(sid) == "failed":
                    st[sid] = "pending"
                seed["step_status"] = st
            if rem.get("action") == "free_text" and rem.get("text"):
                seed["free_notes"] = list(seed.get("free_notes") or []) + \
                    [str(rem["text"])[:500]]
                if sid:
                    att[sid] = 0
                    st = dict(seed.get("step_status") or {})
                    if st.get(sid) == "failed":
                        st[sid] = "pending"
                    seed["step_status"] = st
            if rem.get("action") == "skip" and sid:
                st = dict(seed.get("step_status") or {})
                st[sid] = "skipped"
                seed["step_status"] = st
                seed["skipped"] = list(seed.get("skipped") or []) + [{
                    "step_id": sid, "by": "user",
                    "reason": str(rem.get("text") or "")[:200] or "remedy_skip"}]
                # H9 · el salto pre-aplicado a la continuación se NARRA por el espinazo
                # (el grafo/Sala pintan la brasa por este evento; sin esto el skip es mudo)
                _em = _space_emitter(_emit_space)
                if _em is not None:
                    try:
                        _em({"type": "method_step_done", "run_id": old_run_id,
                             "step_id": sid, "skipped": True})
                    except Exception:
                        pass
            seed["attempts"] = att

        import threading
        if os.environ.get("PUPPET_METHOD_SYNC_RESUME") == "1":
            _go()   # tests: continuación inline (determinista)
        else:
            threading.Thread(target=_go, daemon=True,
                             name=f"method-resume-{old_run_id[:8]}").start()
        return {"ok": True, "resumed": "continuation"}

    def _schedule_retry(run_id: str, owner: str, minutes: int) -> None:
        """H8 · timer BEST-EFFORT: a los N minutos reanuda el método por su cuenta.
        Guardado por el claim atómico de la continuación → jamás dobla con un resume
        manual. Daemon: si el proceso se reinicia, degrada a reanudación manual (no hay
        scheduler durable en v1; los triggers automáticos son post-launch)."""
        import threading
        secs = float(os.environ.get("PUPPET_METHOD_RETRY_TEST_SECONDS") or (int(minutes) * 60))

        def _fire():
            c = None
            try:
                c = get_conn()
                m = mr.get_method_run(c, run_id)
                if m and str(m.get("user_id")) == owner and m.get("status") in _RESUMABLE:
                    _spawn_continuation(c, m, owner)
            except HTTPException:
                pass
            except Exception:
                _log.warning("retry_in del método falló (run %s)", run_id, exc_info=True)
            finally:
                try:
                    if c is not None:
                        c.close()
                except Exception:
                    pass
        threading.Timer(max(0.0, secs), _fire).start()

    @router.post("/runs/{run_id}/method/pause")
    def method_pause(run_id: str, authorization: Optional[str] = Header(default=None)):
        owner = _owner_or_401(authorization)
        conn = _conn()
        try:
            mrun = _method_run_gate(conn, run_id, owner)
            if not _run_is_live(conn, run_id, mrun):
                raise HTTPException(status_code=409,
                    detail={"error": "run_not_live",
                            "detail": "Ese run ya terminó: no hay nada que pausar."})
            mr.update_method_run(conn, run_id, control_merge={"pause": True})
            return {"ok": True, "status": mrun.get("status")}
        finally:
            conn.close()

    @router.post("/runs/{run_id}/method/resume")
    def method_resume(run_id: str, body: MethodResumeRequest = None,  # type: ignore[assignment]
                      authorization: Optional[str] = Header(default=None)):
        owner = _owner_or_401(authorization)
        body = body or MethodResumeRequest()
        conn = _conn()
        try:
            mrun = _method_run_gate(conn, run_id, owner)
            if _run_is_live(conn, run_id, mrun):
                merge: dict[str, Any] = {"resume": True}
                if body.method is not None:
                    m2 = _validated(body.method)
                    merge["resume_spec"] = m2
                    if mrun.get("method_id"):
                        mr.update_method(conn, str(mrun["method_id"]), owner, m2)
                mr.update_method_run(conn, run_id, control_merge=merge)
                return {"ok": True, "resumed": "live"}
            if mrun.get("status") not in _RESUMABLE:
                raise HTTPException(status_code=409,
                    detail={"error": "method_not_resumable",
                            "detail": f"El método quedó en '{mrun.get('status')}': "
                                      "no hay nada que reanudar."})
            return _spawn_continuation(conn, mrun, owner, resume_spec=body.method,
                                       space_override=body.space)
        finally:
            conn.close()

    @router.post("/runs/{run_id}/method/remedy")
    def method_remedy(run_id: str, body: MethodRemedyRequest,
                      authorization: Optional[str] = Header(default=None)):
        owner = _owner_or_401(authorization)
        if body.action not in ("apply", "retry", "retry_in", "skip", "free_text"):
            raise HTTPException(status_code=422,
                detail={"error": "bad_action",
                        "detail": "action ∈ apply|retry|retry_in|skip|free_text"})
        conn = _conn()
        try:
            mrun = _method_run_gate(conn, run_id, owner)
            state = mrun.get("state") or {}
            step_id = body.step_id or state.get("current")
            remedy = {"action": body.action, "step_id": step_id,
                      "minutes": body.minutes, "text": body.text}
            # retry_in agenda el reintento SIEMPRE (vivo o cortado): el timer reanuda
            # a los N minutos; guardado por el claim atómico (no dobla con un resume).
            if body.action == "retry_in":
                _schedule_retry(run_id, owner, body.minutes or 5)
            if _run_is_live(conn, run_id, mrun):
                mr.update_method_run(conn, run_id, control_merge={"remedy": remedy})
                return {"ok": True, "applied": "live"}
            if body.action == "retry_in":
                st = dict(state)
                st["retry_after_min"] = body.minutes or 5
                mr.update_method_run(conn, run_id, state=st, status="scheduled_retry")
                return {"ok": True, "applied": "scheduled"}
            if mrun.get("status") not in _RESUMABLE:
                raise HTTPException(status_code=409,
                    detail={"error": "method_not_resumable",
                            "detail": f"El método quedó en '{mrun.get('status')}'."})
            return _spawn_continuation(conn, mrun, owner,
                                       control_seed={"remedy": remedy})
        finally:
            conn.close()

    return router
