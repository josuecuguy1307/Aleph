"""
infra_router.py — endpoints ADITIVOS de infra (T8). No tocan ni reemplazan los de
features; agregan el camino ASÍNCRONO (encolar) y la observabilidad operacional.

  POST /v1/runs/enqueue   — encola un puppet run (validado+autorizado al toque) y
                            devuelve un job_id; el worker pool lo ejecuta. El request
                            NO se bloquea por la duración del run.
  GET  /v1/jobs/{job_id}  — estado del job (scopeado al dueño).
  GET  /v1/jobs           — los jobs del usuario autorizado.
  GET  /health/deep       — salud profunda: ping a DB + profundidad de la cola.

El enqueue replica las MISMAS comprobaciones de borde que /v1/puppets/run (authz por
sesión, carga de receta desde puppet_id, RAG-guard de aislamiento, validación contra
el schema) — router.run_puppet es la referencia. Lo pesado (la ejecución) lo difiere.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from app.phase1 import recipe_validator as rv

_PLATFORM_DB = Path(__file__).resolve().parents[4] / "platform" / "db"
if str(_PLATFORM_DB) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_DB))


def _pooled():
    from pool import pooled_conn
    return pooled_conn()


class EnqueueRunRequest(BaseModel):
    recipe: Optional[dict[str, Any]] = None
    puppet_id: Optional[str] = None
    user_id: Optional[str] = None
    space_id: Optional[str] = None
    prompt: str
    deadline_s: float = 180.0
    images: Optional[list[str]] = None
    lang: str = "es"
    priority: int = 0
    max_attempts: int = 1


def build_infra_router(
    *,
    get_conn: Callable[[], Any],
    events_dir: Callable[[], Path],
    repo_root: Path,
) -> APIRouter:
    router = APIRouter(tags=["infra"])

    def _bearer(authorization: Optional[str]) -> Optional[str]:
        if not authorization:
            return None
        a = authorization.strip()
        return a[7:].strip() if a.lower().startswith("bearer ") else (a or None)

    def _authorize(claimed_user_id: Optional[str], authorization: Optional[str]) -> Optional[str]:
        """Mismo contrato anti-IDOR que el router de features: la sesión debe ser dueña
        del user_id reclamado. Un run anónimo (sin user_id) no exige sesión."""
        if not claimed_user_id:
            return None
        from app.phase1 import repo
        owner = repo.session_owner(_bearer(authorization))
        if owner is None:
            raise HTTPException(status_code=401,
                detail={"error": "no_session", "detail": "Inicia sesión para continuar."})
        if str(owner) != str(claimed_user_id):
            raise HTTPException(status_code=403,
                detail={"error": "forbidden", "detail": "Esa cuenta no es la tuya."})
        return owner

    # ── POST /v1/runs/enqueue ──────────────────────────────────────────────────
    @router.post("/v1/runs/enqueue", status_code=201)
    def enqueue_run(body: EnqueueRunRequest,
                    authorization: Optional[str] = Header(default=None)):
        if body.user_id:
            _authorize(body.user_id, authorization)

        from app.phase1 import repo as _repo, rag_store

        # 1) resolver receta (inline o desde puppet_id) — igual que el endpoint síncrono
        recipe = body.recipe
        if recipe is None:
            if not body.puppet_id:
                raise HTTPException(status_code=422, detail={
                    "error": "missing_recipe", "detail": "provee `recipe` inline o `puppet_id`"})
            # [audit superficie · H3] Misma frontera que /puppets/run: cargar una receta
            # GUARDADA exige ser su dueño. `enqueue` tenía el bug idéntico — encolar la
            # receta de otro sin sesión → el worker la corría a costa de Aleph. Cerrar
            # sólo el endpoint síncrono habría dejado el mismo agujero por la cola.
            _runner = _repo.session_owner(_bearer(authorization))
            if not _runner:
                raise HTTPException(status_code=401, detail={
                    "error": "no_session",
                    "detail": "Encolar un agente guardado necesita tu sesión."})
            with _pooled() as conn:
                puppet = _repo.get_puppet(conn, body.puppet_id)
            if puppet is None or str(puppet.get("owner_id")) != str(_runner):
                raise HTTPException(status_code=404, detail=f"puppet '{body.puppet_id}' no encontrado")
            recipe = puppet["config"]

        # 2) RAG-guard de aislamiento (no leer docs de otra cuenta)
        _rag = (recipe or {}).get("rag") if isinstance(recipe, dict) else None
        if isinstance(_rag, dict) and _rag.get("enabled") and _rag.get("dir"):
            if not rag_store.is_owned_rag_dir(_rag.get("dir"), body.user_id):
                recipe = {**recipe, "rag": {**_rag, "enabled": False, "dir": None,
                                            "_blocked": "rag.dir no pertenece a tu cuenta"}}

        # 3) validar contra el schema → 422 al toque (no encolar basura)
        try:
            rv.validate_recipe(recipe, repo_root=repo_root)
        except rv.RecipeValidationError as exc:
            raise HTTPException(status_code=422, detail={
                "error": "recipe_invalid", "errors": exc.errors, "warnings": exc.warnings})

        # 4) encolar — el worker pool ejecuta; el request vuelve YA.
        from app.infra import jobs
        payload = {
            "recipe": recipe, "prompt": body.prompt, "user_id": body.user_id,
            "space_id": body.space_id, "puppet_id": body.puppet_id,
            "deadline_s": body.deadline_s, "images": body.images, "lang": body.lang,
            "events_root": str(events_dir()),
        }
        with _pooled() as conn:
            job = jobs.enqueue(
                conn, "puppet_run", payload,
                user_id=body.user_id, priority=body.priority,
                max_attempts=max(1, body.max_attempts),
            )
        return {"job_id": job["id"], "status": job["status"],
                "kind": job["kind"], "run_id": job["run_id"]}

    # ── GET /v1/jobs/{job_id} ──────────────────────────────────────────────────
    @router.get("/v1/jobs/{job_id}")
    def get_job(job_id: str, authorization: Optional[str] = Header(default=None)):
        from app.infra import jobs
        with _pooled() as conn:
            job = jobs.get(conn, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail={"error": "job_not_found"})
        if job.get("user_id"):
            _authorize(str(job["user_id"]), authorization)
        # no devolvemos el payload crudo (puede traer la receta entera); sí el estado.
        return {
            "job_id": str(job["id"]), "kind": job["kind"], "status": job["status"],
            "attempts": job["attempts"], "max_attempts": job["max_attempts"],
            "run_id": str(job["run_id"]) if job["run_id"] else None,
            "error": job["error"], "result": job["result"],
            "created_at": job["created_at"].isoformat() if job["created_at"] else None,
            "started_at": job["started_at"].isoformat() if job["started_at"] else None,
            "finished_at": job["finished_at"].isoformat() if job["finished_at"] else None,
        }

    # ── GET /v1/jobs ───────────────────────────────────────────────────────────
    @router.get("/v1/jobs")
    def list_jobs(limit: int = Query(default=50, le=200),
                  authorization: Optional[str] = Header(default=None)):
        # [hallazgo #1] la identidad sale de la SESIÓN, no de un ?user_id=. Antes tomaba
        # user_id del query (validado contra la sesión por _authorize, pero es la forma
        # que erradicamos): ahora es innecesario y el param se elimina.
        from app.phase1 import authz
        user_id = authz.require_actor(authorization)
        if not user_id:
            raise HTTPException(status_code=401, detail={"error": "no_session"})
        from app.infra import jobs
        with _pooled() as conn:
            rows = jobs.list_for_user(conn, user_id, limit=limit)
        return {"user_id": user_id, "total": len(rows), "jobs": [
            {"job_id": str(r["id"]), "kind": r["kind"], "status": r["status"],
             "run_id": str(r["run_id"]) if r["run_id"] else None,
             "created_at": r["created_at"].isoformat() if r["created_at"] else None}
            for r in rows]}

    # ── GET /health/deep ───────────────────────────────────────────────────────
    @router.get("/health/deep")
    def health_deep():
        """Salud operacional para monitores externos: DB viva + profundidad de cola.
        Si la cola 'queued' crece sin drenar, o hay 'error', se ve acá (señal de alerta)."""
        out: dict[str, Any] = {"status": "ok", "db": "ok", "queue": None}
        try:
            from app.infra import jobs
            with _pooled() as conn:
                out["queue"] = jobs.stats(conn)
        except Exception as exc:
            out["status"] = "degraded"
            out["db"] = f"error: {exc}"
        return out

    return router
