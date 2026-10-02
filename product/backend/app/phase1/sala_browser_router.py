"""sala_browser_router.py — el puente de la Sala a BROWSER USE. [Gate 4 · F6 · §6.a]

    POST /v1/sala/navegador          NDJSON: el progreso paso a paso y la obra
    POST /v1/sala/navegador/parar    corta el turno

UNA TOOL, NO VEINTE — decisión del dueño. El agente pide «hacé esto en el navegador» y el
loop entero corre del otro lado. Por eso **el gate aprueba LA TAREA, no cada click**: no hay
veinte llamadas que aprobar, hay una.

QUÉ SE LE MUESTRA AL USUARIO PARA QUE ESA APROBACIÓN SIGNIFIQUE ALGO. Aprobar «manejá el
navegador» sin más sería una firma en blanco — el loop puede dar treinta pasos y tocar
cualquier cosa. La tarjeta dice las tres cosas que acotan el permiso, y las tres son HECHOS
medibles antes de arrancar, no promesas:
  · la TAREA textual, tal cual la escribió el usuario;
  · el TECHO DE PASOS, que es el máximo de acciones que el loop puede dar;
  · si el cerebro VE o navega a ciegas, que cambia qué puede hacer y qué no.
Y lo que el permiso NO incluye queda dicho: el loopback ajeno sigue negado por
`platform/browser/loopback.py` aunque el usuario apruebe — la aprobación no levanta el guard.

NO SE REIMPLANTA EL `enter`: se llama (`ws_pack.levantar`, idempotente y compartido por
huella), igual que `sala_busqueda_router`. Y el NDJSON del motor se reenvía TAL CUAL: los
sobres los produce `platform/browser/servidor.py` y re-mapearlos acá sería el tercer lugar
donde vive el mismo contrato.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

_WS = "sala_browser"

#: Regla sellada: ninguna causa llega a una superficie sin copy.
_COPY = {
    "tarea_vacia": "Dime qué quieres que haga en el navegador.",
    "pack_no_arranco": "El navegador no llegó a levantarse.",
    "pack_no_instalado": "El navegador no viajó con esta instalación.",
    "motor_no_responde": "El navegador no contestó.",
    "necesita_ok": "Antes de manejar el navegador necesito tu OK.",
}

#: El techo por defecto. Es lo que la tarjeta MUESTRA, así que no puede ser un número
#: escondido: el usuario aprueba «hasta N pasos», no «los que hagan falta».
PASOS_POR_DEFECTO = 25


class NavegarRequest(BaseModel):
    tarea: str
    max_pasos: Optional[int] = None
    user_id: Optional[str] = None
    puppet_id: Optional[str] = None
    chat_id: Optional[str] = None
    space_id: Optional[str] = None
    turno_id: Optional[str] = None
    #: El OK del usuario a la tarjeta. Sin esto el gate contesta `needs_ok` y no se corre nada.
    aprobado: Optional[bool] = False


class PararRequest(BaseModel):
    turno_id: str


class ApagarLocal(BaseModel):
    """⚠️ AL NIVEL DEL MÓDULO, y no adentro del builder como estaba. FastAPI resuelve las
    anotaciones del handler con `typing.get_type_hints` sobre el ámbito del MÓDULO: una
    clase definida dentro de `build_…()` queda como ForwardRef sin resolver y el backend
    **no llega a servir** — `PydanticUserError: is not fully defined`. Sus dos hermanas ya
    estaban acá; ésta se escribió adentro y ninguna vara lo vio: lo cazó la prueba de humo
    de levantar el backend y pedirle el `openapi.json`."""
    run_id: str
    puerto: Optional[int] = None


def build_sala_browser_router(*, get_conn: Callable[[], Any]) -> APIRouter:
    router = APIRouter(prefix="/v1/sala", tags=["sala"])

    def _fila_cerebro(dueno: str) -> Optional[dict]:
        """La fila del cerebro elegido, para que `perfil.perillas` derive de ahí. Se lee del
        selector de la casa —la MISMA fuente que sirve la pantalla— y no de un mapa nuevo."""
        try:
            from app.phase1 import centro_modelos as cm
            sel = cm.selector_modelos(owner=dueno, get_conn=get_conn, contexto="sala", todos=True)
            elegido = str(sel.get("seleccion_id") or "")
            for f in sel.get("modelos") or []:
                if str(f.get("picker_id") or "") == elegido:
                    return f
        except Exception:                                   # noqa: BLE001
            return None
        return None

    def _tarjeta(tarea: str, pasos: int, fila: Optional[dict]) -> dict:
        """Lo que el usuario ve ANTES de aprobar. Tres hechos, cero promesas."""
        import sys as _s
        from pathlib import Path as _P
        _plat = str(_P(__file__).resolve().parents[4] / "platform")
        if _plat not in _s.path:
            _s.path.insert(0, _plat)
        from browser import perfil as PERFIL
        p = PERFIL.perillas(fila)
        return {
            "que_voy_a_hacer": tarea,
            "techo_de_pasos": pasos,
            "ve_la_pantalla": p["use_vision"],
            "aviso": (PERFIL.aviso(fila) or {}).get("copy"),
            "lo_que_no_incluye": ("Aunque digas que sí, no puedo abrir puertos locales que "
                                  "no haya levantado este mismo trabajo, ni tu red interna."),
        }

    @router.post("/navegador")
    def navegador(body: NavegarRequest, request: Request,
                  authorization: Optional[str] = Header(default=None)):
        from app.phase1.authz_http import owner_or_401
        dueno = owner_or_401(authorization,
                             detail="Inicia sesión para usar el navegador.",
                             copy="Inicia sesión para usar el navegador.")
        tarea = (body.tarea or "").strip()
        if not tarea:
            raise HTTPException(status_code=400, detail={
                "error": "tarea_vacia", "copy": _COPY["tarea_vacia"]})

        pasos = max(1, min(int(body.max_pasos or PASOS_POR_DEFECTO), 100))
        fila = _fila_cerebro(dueno)
        # ── EL ESPACIO SE ACUÑA ACÁ SI NADIE LO TRAE ──────────────────────────────────
        # MEDIDO en el turno completo del 2026-08-19: sin `space_id` la costura no manda
        # `X-Aleph-Space`, el borde produce cada paso y NO TIENE DÓNDE ARCHIVARLO, y el
        # `events.jsonl` del espacio no existe — o sea **S8 ciego a todo lo que este modo
        # produzca**. Es exactamente la deuda D8 que Finanzas ya pagó (`pack.py:449`) y la
        # razón por la que el plugin de Ciencia acuña uno por turno.
        #
        # Un espacio POR TURNO, no por sesión: un turno de navegador son decenas de pasos
        # del mismo trabajo, y mezclarlos con el turno siguiente haría irreconstruible cuál
        # produjo qué. El formato es el que `provenance.py:53` exige (`^[A-Za-z0-9._:-]{1,120}$`).
        import re as _re, time as _time
        espacio = body.space_id or (
            "space-browser-"
            + (_re.sub(r"[^A-Za-z0-9._:-]", "", str(body.turno_id or ""))[-24:] or "s")
            + f"-{int(_time.time() * 1000):x}")

        # ── EL GATE APRUEBA LA TAREA, UNA VEZ ────────────────────────────────────────
        # Sin `aprobado` se devuelve la tarjeta y NO se levanta nada: el pack ni siquiera
        # arranca. Fail-closed por construcción — no hay camino que ejecute sin el OK.
        if not body.aprobado:
            return {"necesita_ok": True, "error": "necesita_ok",
                    "copy": _COPY["necesita_ok"], "tarjeta": _tarjeta(tarea, pasos, fila)}

        from workspaces import pack as ws_pack
        from app.phase1.router import _WORKSPACE_STACKS
        meta = _WORKSPACE_STACKS.get(_WS)
        if not meta:
            raise HTTPException(status_code=404, detail={
                "error": "workspace_desconocido",
                "detail": f"«{_WS}» no es un workspace de esta instalación",
                "copy": _COPY["pack_no_instalado"]})
        base = str(request.base_url).rstrip("/")
        token = (authorization or "").split(" ", 1)[-1].strip()
        try:
            vivo = ws_pack.levantar(_WS, meta, base_aleph=base, user_id=dueno, token=token,
                                    puppet_id=body.puppet_id, chat_id=body.chat_id,
                                    space_id=espacio)
            internal_cap = ws_pack.capacidad_interna(_WS, meta, user_id=dueno)
        except ws_pack.PackError as exc:
            raise HTTPException(status_code=503, detail={
                "error": exc.causa, "detail": exc.detalle,
                "copy": _COPY.get(exc.causa, _COPY["pack_no_arranco"])})

        def cable():
            import urllib.error
            import urllib.request
            from browser import loopback as _loopback
            pedido = urllib.request.Request(
                vivo["url"].rstrip("/") + "/manejar",
                # LAS CAPACIDADES VIAJAN: el pack no ve el selector de modelos, así que el
                # único que puede decirle si el cerebro ve es este router, que ya las leyó
                # para armar la tarjeta. Sin esto `perfil.perillas` cae a fail-closed y el
                # aviso diría «no ve» de un cerebro que sí ve.
                data=json.dumps({"tarea": tarea, "max_pasos": pasos,
                                 "turno_id": body.turno_id, "run_id": body.turno_id,
                                 "space_id": espacio,
                                 # Only PID-bound grants recorded by trusted parent
                                 # code cross this authenticated pack request.
                                 "loopback_grants": _loopback.exportar_excepciones(str(body.turno_id)),
                                 "capacidades": (fila or {}).get("model_use_capabilities"),
                                 }).encode("utf-8"),
                headers={"Content-Type": "application/json",
                         "Authorization": "Bearer " + internal_cap})
            try:
                respuesta = urllib.request.urlopen(pedido, timeout=1800)
            except urllib.error.HTTPError as e:
                # ⚠️ EL CUERPO DEL HTTPError ES DONDE ESTÁ LA CAUSA, y esto lo tiraba.
                # Costó dos diagnósticos a ciegas: el motor contestaba
                # `{"error":"sin_cerebro","copy":…}` con un 503 perfectamente tipado y acá
                # salía «HTTPError» pelado. Un error que sabe su causa y no la pasa es peor
                # que uno que no la sabe: hace creer que no hay nada más que mirar.
                try:
                    d = json.loads(e.read().decode("utf-8", "replace"))
                except Exception:                               # noqa: BLE001
                    d = {}
                yield (json.dumps({
                    "tipo": "fallo",
                    "causa": d.get("error") or "motor_no_responde",
                    "copy": d.get("copy") or _COPY["motor_no_responde"],
                    "detalle": d.get("detail") or f"HTTP {e.code}"}) + "\n").encode()
                return
            except (urllib.error.URLError, OSError) as e:
                yield (json.dumps({"tipo": "fallo", "causa": "motor_no_responde",
                                   "copy": _COPY["motor_no_responde"],
                                   "detalle": type(e).__name__}) + "\n").encode()
                return
            with respuesta:
                for linea in respuesta:
                    yield linea

        return StreamingResponse(cable(), media_type="application/x-ndjson",
                                 headers={"Cache-Control": "no-store",
                                          "X-Accel-Buffering": "no"})

    # ══ EL WEBVIEW LOCAL GENÉRICO (ley 8) ═══════════════════════════════════════════
    # La ley 8 pone «webview local» en el segundo escalón de la jerarquía de visualización,
    # y hoy existe SÓLO para los seis del registro: seis páginas anfitrionas de ~390 líneas
    # que —normalizando el nombre— difieren entre 28 y 81 líneas (medido 2026-08-19). Falta
    # la que sirve para CUALQUIER proceso que el agente levantó.
    #
    # ⚠️ LA PÁGINA NO PUEDE CREERLE A SU PROPIA URL. Si `local.html?puerto=N` alcanzara para
    # mostrar un iframe, cualquiera que le pase un puerto en la query mira lo que quiera de
    # loopback — incluido el sidecar, que sirve TODA `/v1`. Así que la página PREGUNTA, y el
    # que contesta es el mismo guard que gobierna al navegador del agente: allowlist por
    # `(run_id, puerto)`, jamás por rango. Ver `platform/browser/REGLA-LOOPBACK.md`.
    @router.get("/local/{run_id}/{puerto}")
    def local_permitido(run_id: str, puerto: int,
                        authorization: Optional[str] = Header(default=None)):
        from app.phase1.authz_http import owner_or_401
        dueno = owner_or_401(authorization, detail="Inicia sesión.", copy="Inicia sesión.")
        import sys as _s
        from pathlib import Path as _P
        _plat = str(_P(__file__).resolve().parents[4] / "platform")
        if _plat not in _s.path:
            _s.path.insert(0, _plat)
        from browser import loopback as GUARD
        v = GUARD.permitir(f"http://127.0.0.1:{int(puerto)}/", run_id=run_id)
        if not v.ok:
            # 403 y no 404: el puerto puede existir perfectamente. Lo que no existe es el
            # permiso, y la causa lo dice con su copy.
            raise HTTPException(status_code=403, detail={
                "error": v.causa, "copy": v.copy, "detail": v.detalle})
        return {"ok": True, "url": f"http://127.0.0.1:{int(puerto)}/", "run_id": run_id}

    @router.post("/local/apagar")
    def local_apagar(body: ApagarLocal, authorization: Optional[str] = Header(default=None)):
        """La otra mitad del ciclo simétrico: al salir se DESANOTA el puerto.

        Que el proceso muera es del pack; que el permiso muera es de acá. Y el permiso tiene
        que morir aunque el proceso sobreviva —si no, un puerto reciclado por el sistema
        operativo quedaría autorizado para otro dueño—. Por eso desanotar es el paso que NO
        depende de que nadie conteste."""
        from app.phase1.authz_http import owner_or_401
        owner_or_401(authorization, detail="Inicia sesión.", copy="Inicia sesión.")
        import sys as _s
        from pathlib import Path as _P
        _plat = str(_P(__file__).resolve().parents[4] / "platform")
        if _plat not in _s.path:
            _s.path.insert(0, _plat)
        from browser import loopback as GUARD
        GUARD.desanotar(body.run_id, body.puerto)
        return {"ok": True, "quedan": sorted(GUARD.puertos_de(body.run_id))}

    @router.post("/navegador/parar")
    def parar(body: PararRequest, request: Request,
              authorization: Optional[str] = Header(default=None)):
        from app.phase1.authz_http import owner_or_401
        dueno = owner_or_401(authorization, detail="Inicia sesión.", copy="Inicia sesión.")
        from workspaces import pack as ws_pack
        from app.phase1.router import _WORKSPACE_STACKS
        meta = _WORKSPACE_STACKS.get(_WS)
        vivo = ws_pack.vivo(_WS, meta, user_id=dueno) if meta else None
        if not (meta and vivo):
            return {"ok": False, "error": "sin_turno", "copy": _COPY["motor_no_responde"]}
        try:
            internal_cap = ws_pack.capacidad_interna(_WS, meta, user_id=dueno)
        except ws_pack.PackError:
            return {"ok": False, "error": "sin_turno", "copy": _COPY["motor_no_responde"]}
        import urllib.error
        import urllib.request
        try:
            urllib.request.urlopen(urllib.request.Request(
                vivo["url"].rstrip("/") + "/parar",
                data=json.dumps({"turno_id": body.turno_id}).encode("utf-8"),
                headers={"Content-Type": "application/json",
                         "Authorization": "Bearer " + internal_cap}), timeout=10)
        except (urllib.error.URLError, OSError):
            return {"ok": False, "error": "motor_no_responde", "copy": _COPY["motor_no_responde"]}
        return {"ok": True}

    return router
