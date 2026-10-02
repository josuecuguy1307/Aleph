"""
multiagente_router.py — la SUPERFICIE del multiagente (F1 · CADENA).

Spec: `docs/multiagente.md`. Tres endpoints, ninguno de UI:

  POST /v1/multiagente/plan       valida + planifica SIN correr. Es la superficie donde
                                  se ven los RECHAZOS (bucle, bifurcación, aleph repetido,
                                  modo no implementado, profundidad) con su CAUSA.
  POST /v1/multiagente/run        corre la cadena: un run del PADRE + un run NORMAL por
                                  salto, enlazados por campo, con la LATENCIA MEDIDA.
  GET  /v1/multiagente/runs/{id}  el transcript del padre releído de la DB.

── POR QUÉ UN ROUTER PROPIO Y NO UN FLAG EN /v1/puppets/run ────────────────────
Porque `/v1/puppets/run` **es** el ciclo de vida del run de un aleph, y el multiagente no
lo modifica: lo USA. Este router crea el run del padre, llama N veces a
`executor.run_puppet_e2e` (el runner de siempre, INYECTADO en el motor) y estampa el
enlace. Un flag adentro de `run_puppet_e2e` habría convertido un camino con un solo modo
de fallo en uno con dos.

── EL RUNNER INYECTADO ─────────────────────────────────────────────────────────
`platform/assembler/multiagente.py` es stdlib-only: no conoce FastAPI, ni la DB, ni el
executor. Acá se le pasan las dos funciones que necesita (`runner` y `enlazar`) y él pone
el contrato. Mismo patrón que `delegation.py`, y por el mismo motivo.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

try:
    import aleph_paths as _ap
except ImportError:  # pragma: no cover — dev sin platform/ en sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "platform"))
    import aleph_paths as _ap

_RESOURCE_ROOT = _ap.resource_root()
_ASSEMBLER_DIR = _RESOURCE_ROOT / "platform" / "assembler"

_ma = None


def _motor():
    """El módulo del motor multiagente. MISMA carga que usa el executor para sus hermanos
    de `platform/assembler` (sys.path + import): bajo PyInstaller el módulo viaja en el PYZ
    (`_TARGET_MODULES` del spec) y el archivo además viaja como dato (`_TARGET_DIRS`), así
    que los dos caminos existen. Si no carga, se LEVANTA — jamás se sirve un 200 con una
    cadena que nadie corrió."""
    global _ma
    if _ma is None:
        if str(_ASSEMBLER_DIR) not in sys.path:
            sys.path.insert(0, str(_ASSEMBLER_DIR))
        import multiagente as _m  # noqa: PLC0415
        _ma = _m
    return _ma


class PlanRequest(BaseModel):
    recipe: dict


class RunRequest(BaseModel):
    recipe: dict
    prompt: str
    user_id: Optional[str] = None
    space_id: Optional[str] = None
    deadline_s: float = 180.0
    lang: str = "es"


def _rechazo(exc) -> HTTPException:
    """Un rechazo del motor SIEMPRE sale con su CAUSA legible por máquina + su DETALLE
    legible por humano. 422 = «tu receta no describe algo que se pueda correr», que es
    distinto de un 500 (nosotros rotos)."""
    return HTTPException(status_code=422, detail={"error": "multiagente_rechazado",
                                                  **exc.as_dict()})


def build_multiagente_router(*, get_conn: Callable[[], Any],
                             repo_root: Optional[Path] = None) -> APIRouter:
    router = APIRouter(prefix="/v1/multiagente", tags=["multiagente"])
    root = Path(repo_root) if repo_root else _RESOURCE_ROOT

    def _autorizar(user_id: Optional[str], authorization: Optional[str]) -> None:
        """Misma frontera que `/v1/puppets/run`: una receta INLINE anónima es tu propia
        receta ad-hoc y está permitida (no toca datos de nadie); si el run se ATRIBUYE a
        una cuenta, esa cuenta tiene que ser la de la sesión."""
        if not user_id:
            return
        from app.phase1 import authz, repo as _repo
        owner = _repo.session_owner(authz.parse_bearer(authorization))
        if owner is None:
            raise HTTPException(status_code=401, detail={
                "error": "no_session", "detail": "Inicia sesión para continuar."})
        if str(owner) != str(user_id):
            raise HTTPException(status_code=403, detail={
                "error": "forbidden", "detail": "Esa cuenta no es la tuya."})

    def _validar_receta(recipe: dict) -> None:
        """La receta del globo pasa por el MISMO validador del contrato v1 que cualquier
        otra (nada entra al motor sin validar), y de ahí sale también la validación
        multiagente — que el validador delega en este mismo módulo del motor."""
        from app.phase1 import recipe_validator as rv
        try:
            rv.validate_recipe(recipe, repo_root=root)
        except rv.RecipeValidationError as exc:
            raise HTTPException(status_code=422, detail={
                "error": "recipe_invalid", "errors": exc.errors, "warnings": exc.warnings})

    # ── PLAN — valida y deriva SIN correr. Acá se ven los rojos. ────────────────
    @router.post("/plan", status_code=200)
    def plan(body: PlanRequest):
        ma = _motor()
        _validar_receta(body.recipe)
        try:
            p = ma.planificar(body.recipe, root)
        except ma.MultiagenteError as exc:
            raise _rechazo(exc)
        return {"ok": True, "plan": p.as_dict(),
                "piezas_aleph": ma.piezas_aleph(body.recipe)}

    # ── RUN — un padre + N saltos NORMALES enlazados por campo ──────────────────
    @router.post("/run", status_code=201)
    def run(body: RunRequest, authorization: Optional[str] = Header(default=None)):
        ma = _motor()
        _autorizar(body.user_id, authorization)
        _validar_receta(body.recipe)
        try:
            plan_ = ma.planificar(body.recipe, root)
        except ma.MultiagenteError as exc:
            raise _rechazo(exc)

        from app.phase1 import executor, multiagente_repo as mrepo, repo as _repo

        conn = get_conn()
        try:
            # EL RUN DEL PADRE: se crea por el camino de SIEMPRE (`repo.create_run` = el
            # choke point del latido) y recién después se le sella el `modo`. El padre es
            # un run normal con una columna más, no una entidad nueva.
            padre = _repo.create_run(conn, puppet_id=None, user_id=body.user_id,
                                     space_id=body.space_id, intent=body.prompt)
            padre_id = str(padre["id"])
            mrepo.marcar_padre(conn, padre_id, plan_.modo)

            def _runner(recipe: dict, prompt: str, eslabon) -> dict:
                """CADA SALTO ES UN RUN NORMAL. Se llama al executor de prod tal cual:
                mismo gate por receta, misma instrumentación, mismo cierre. El eslabón no
                hereda el OK de nadie ni saltea nada — es un run como cualquier otro."""
                return executor.run_puppet_e2e(
                    recipe, prompt,
                    user_id=body.user_id, space_id=body.space_id, conn=conn,
                    deadline_s=body.deadline_s, lang=body.lang,
                )

            def _enlazar(*, run_id: str, orden: int, latencia_ms: int) -> None:
                mrepo.enlazar_salto(conn, str(run_id), parent_run_id=padre_id,
                                    hop_index=orden, hop_latency_ms=latencia_ms)

            try:
                out = ma.correr_cadena(body.recipe, body.prompt, runner=_runner,
                                       repo_root=root, plan=plan_, enlazar=_enlazar)
            except Exception:
                # EL TURNO SIEMPRE CIERRA (FIX-P10 §1). Si la cadena explota, el run del
                # padre NO puede quedarse en 'running' para siempre: sería exactamente el
                # registro que miente que ese fix vino a matar. Los saltos ya cerraron solos
                # (cada uno es un run normal con su propio finish_run).
                try:
                    conn.rollback()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    _repo.finish_run(conn, padre_id, status="error")
                except Exception:  # noqa: BLE001
                    pass
                raise
            _repo.finish_run(conn, padre_id, status="done" if out["ok"] else "error")
            return {"run_id": padre_id, **out}
        finally:
            conn.close()

    # ── TRANSCRIPT — el padre y sus saltos, releídos de la DB ───────────────────
    @router.get("/runs/{run_id}", status_code=200)
    def transcript(run_id: str, authorization: Optional[str] = Header(default=None)):
        from app.phase1 import multiagente_repo as mrepo
        conn = get_conn()
        try:
            fila = mrepo.run_padre(conn, run_id)
        finally:
            conn.close()
        if fila is None:
            raise HTTPException(status_code=404, detail={
                "error": "no_es_un_run_multiagente",
                "detail": f"'{run_id}' no existe o es un run normal (sin `modo`)."})
        return fila

    return router


__all__ = ["build_multiagente_router"]
