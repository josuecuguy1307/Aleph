"""
main.py — puppet-ai-core FastAPI application

Endpoints:
  GET  /health
  GET  /catalog/{nicho}          — list templates for a nicho (tier-gated)
  /v1/*                          — FASE 1 canónico (router phase1): auth, catálogo de
                                   puppets, workshop/config (validador ANIDADO), storage
                                   (runs/keys), BYOK, event-stream SSE, instrumentación.

FUENTE ÚNICA (migración 2026-06-15): el validador canónico es el ANIDADO
(app.phase1.recipe_validator) y el store canónico es POSTGRES (app.phase1.repo →
platform/db, base puppet_ai). El validador PLANO (config_validator) y el store
SQLite/JSONL (agents_store + data/agents.jsonl) fueron RETIRADOS. El moat
(instrumentation_logs) vive SOLO en Postgres vía /v1/runs/{id}/instrument.
"""

import json
import os
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel

from app.catalog import CATALOG_ROOT, load_catalog, nicho_exists
from app.launch_cap import current as _current_launch_cap
from app.brands import load_brands
# NOTA (Fase 4 cutover): los routers V2 `/espacios/*` (espacios.py + conexiones.py) quedaron
# RETIRADOS — superseded por el path canónico /v1/* (runs/approve, spaces/stream). Se conserva
# EspaciosStore SOLO como almacén del events.jsonl por space_id (lo consume el SSE de phase1).
from app.espacios import (
    EspaciosStore,
    SessionManager,
    SessionFactory,
)
from app.phase1.router import build_phase1_router, install_byok_handler
from app.phase1.connectors_router import build_connectors_router
from app.phase1.connector_entities_router import build_connector_entities_router
from app.phase1.belts_router import build_belts_router
from app.phase1.atoms_router import build_atoms_router
from app.phase1.tools_router import build_tools_router
from app.phase1 import repo as phase1_repo

# ── Response models ───────────────────────────────────────────────────────────

class SurgeryParams(BaseModel):
    """Free-form surgery params from config.json — passed through as-is."""
    model_config = {"extra": "allow"}


class TemplateItem(BaseModel):
    """Single template as returned by GET /catalog/{nicho}.

    belt_path is DECLARED by the catalog (read from the template's real
    config.json) — the UI consumes it verbatim and never derives it.
    """
    id: str
    nombre: str
    descripcion: str
    tier: str
    friccion: str
    friccion_detalle: str
    belt_path: str
    tool_filters: dict[str, Any] = {}
    surgery_params: dict[str, Any]


class CatalogResponse(BaseModel):
    """Response shape for GET /catalog/{nicho}.

    El tier sale de la SESIÓN (Authorization: Bearer), nunca de un parámetro.
    Sin sesión → 'free', lo más restrictivo (7 templates para finanzas).
    """
    nicho: str
    total: int
    templates: list[TemplateItem]


# ── App ───────────────────────────────────────────────────────────────────────

# Lifespan (T8-infra): arranca/para el worker pool que drena la cola durable. Las
# guardas (PUPPET_WORKERS=0 / pytest) viven en bootstrap — la suite NO spinnea workers.
from app.infra.observability import init_observability  # noqa: E402


def _purge_enabled() -> bool:
    """Guardas del purgador (mismo criterio que bootstrap): pytest jamás purga por
    instanciar la app; PUPPET_PURGE_DISABLED=1 lo apaga explícito."""
    import sys as _sys
    if os.environ.get("PUPPET_PURGE_DISABLED", "").strip() == "1":
        return False
    if "pytest" in _sys.modules:
        return False
    return True


async def _purge_loop():
    """Día-30 del borrado de cuenta (ticket 2): purga periódica de cuentas cuya
    ventana venció. El intervalo NO es la garantía de exactitud — purge_after sí:
    cada pasada purga TODO lo vencido, y el login post-ventana también purga lazy."""
    import asyncio
    import logging
    from starlette.concurrency import run_in_threadpool

    log = logging.getLogger("aleph.purge")
    interval = float(os.environ.get("PUPPET_PURGE_INTERVAL_S", "21600") or "21600")

    def _tick():
        from app.phase1 import account_deletion, repo as _repo
        conn = _repo.get_conn()
        try:
            results = account_deletion.purge_expired(conn)
            if results:
                log.info("purga de cuentas vencidas: %s", results)
        finally:
            conn.close()

    while True:
        try:
            await run_in_threadpool(_tick)
        except Exception as exc:  # la purga jamás tumba el server; reintenta al próximo tick
            log.warning("purge_loop: %s", exc)
        await asyncio.sleep(interval)


@asynccontextmanager
async def _lifespan(_app: "FastAPI"):
    import asyncio
    from app.infra import bootstrap, db_boot
    # Acá y no al final del import: un middleware puede registrarse después —al montar un
    # router, por ejemplo— y el arranque es el último momento con la pila ya completa y
    # cero requests servidas. Tira si el guardián dejó de ser el más externo.
    _verificar_guardian_externo(_app)
    # [GAP §2.1] El schema del CLIENTE se asegura ANTES de arrancar lo que escribe:
    # workers (reclaim toca job_queue) y purga (toca users). DB rota → NO arrancan y
    # la superficie entera pasa a 503 claro (middleware _db_fail_visible): la regla
    # es FALLO VISIBLE, JAMÁS MUDO — servir "como si nada" fue exactamente el bug.
    db_ok = db_boot.asegurar()
    if db_ok:
        # [FIX-P10 §1] EL REAPER. Al arrancar, ningún run puede estar corriendo: el proceso
        # que lo estaba corriendo ya no existe. Todo 'running' que sobreviva a un boot es un
        # turno CORTADO y se marca huérfano, para que el registro deje de mentir. Corre antes
        # que los workers (nadie escribe runs todavía) y jamás tumba el boot.
        try:
            from app.phase1 import run_lifecycle as _rl
            _rl.reapear_al_arrancar()
        except Exception as exc:  # noqa: BLE001
            print(f"[runs] reaper de huérfanos NO corrió: {exc}", flush=True)
        # MUDANZA DE CORTESÍA. Los índices RAG y los event-logs de espacios se escribían
        # en rutas derivadas del árbol, que bajo PyInstaller caen dentro de `_MEIPASS` y
        # se borran al cerrar. Ya está arreglado en origen; esto trae lo que un usuario
        # alcanzó a escribir en el lugar viejo. NUNCA borra: mueve y fusiona. Idempotente
        # —deja marca en el destino— y jamás tumba el arranque.
        try:
            from app.infra import mudanza_datos as _mud
            _m = _mud.mudar_todo()
            _rag, _esp = _m.get("rag") or {}, _m.get("espacios") or {}
            if _rag.get("movidos") or _esp.get("eventos_sumados"):
                print(f"[mudanza] rag: {_rag.get('movidos', 0)} docs · "
                      f"espacios: {_esp.get('eventos_sumados', 0)} eventos en "
                      f"{_esp.get('espacios', 0)} espacio(s)", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[mudanza] NO corrió: {exc}", flush=True)
        bootstrap.start()
    # EL DUEÑO · BARRIDO DE ARRANQUE (DISEÑO-DUEÑO-v1 §3.3). Lo que dejó vivo un sidecar
    # anterior se mata acá, con verificación de identidad (comando + ventana de hora): un
    # pid reciclado es el pid de OTRO y no se toca. NO se readopta —los pipes murieron con
    # el padre— así que barrer es la operación honesta. Sin esto, esos procesos sobreviven
    # al reinicio y sólo los caza, si acaso, el barrido de `_MEI`, que mira directorios.
    # Fuera del `if db_ok`: los procesos MCP no dependen de que la DB esté sana, y dejarlos
    # vivos porque la base está rota sería sumar una fuga a un fallo.
    try:
        from inspection import dueno as _dueno
        _parte = _dueno.actual().barrer_al_arrancar()
        if _parte.get("matadas") or _parte.get("recicladas") or _parte.get("sin_pid"):
            print(f"[dueño] barrido de arranque: {_parte}", flush=True)
    except Exception as exc:  # noqa: BLE001 — el boot no se cae por esto
        print(f"[dueño] barrido de arranque NO corrió: {exc}", flush=True)
    # REPAIR (R3 · DISEÑO-REPAIR-v1 §7.1) — se engancha al dueño acá, donde el dueño ya está
    # vivo. **`ALEPH_REPAIR=off` por default**: reparar es cambiar el mundo, así que
    # encenderlo es una decisión. Sin la perilla, `cablear` devuelve False y no toca nada —
    # el dueño queda sin guardia y sin suscriptor, o sea exactamente como antes de repair.
    try:
        from inspection import dueno as _dueno
        from inspection import repair as _repair
        if _repair.cablear(_dueno):
            print("[repair] enganchado al dueño (ALEPH_REPAIR=on)", flush=True)
    except Exception as exc:  # noqa: BLE001 — el boot NO se cae porque repair no cargue
        print(f"[repair] NO se enganchó: {exc}", flush=True)
    # ══ EL CATÁLOGO LOCAL AL ARRANCAR · SE CUENTA, NO SE VERIFICA ═══════════════════════
    #
    # [TANDA 2 · obra A · decisión del dueño] Acá corría `re_verificar_local`, que levantaba
    # UN SERVER MCP POR PIEZA en cada arranque. MEDIDO contra la `.app` instalada
    # `6c79c933`:
    #
    #   · 47 piezas · 36,8 s de barrido · 47 spawns
    #   · **0 de 50 veredictos guardados cambiaron** tras un arranque completo (snapshot
    #     de `conexiones.conexion`/`credencial` antes y después, diff = 0)
    #   · y 47 es el número de ESTA máquina. Quien más conecta, más castigado: el costo de
    #     abrir Aleph crecía con lo que el usuario había construido. Eso no escala.
    #
    # El argumento que lo justificaba —«un binario que el usuario desinstaló ayer sigue
    # figurando ✅»— es cierto pero NO pide verificar al abrir: pide que el veredicto se
    # muestre CON SU EDAD y que caduque por CAUSA. Las dos cosas ya existen y no las
    # llamaba nadie desde acá: `MV.estado` (lectura no bloqueante, «nunca verde sin
    # evidencia», no caduca por reloj sino por huella) y `medicionRancia`
    # (`conectores/widget.js:89`, marca rancio lo que es anterior a sus insumos).
    #
    # EL CRITERIO, EN UNA LÍNEA: **un conector se verifica cuando se conecta y cuando se va
    # a usar; el veredicto guardado se lee, y sólo se re-pregunta si un insumo suyo cambió o
    # si su causa anterior es reintentable (`MV.REINTENTABLE`). Abrir la app no es un
    # momento de verificación.**
    #
    # Los otros dos momentos ya tienen dueño y no se tocan:
    #   · AL CONECTAR → `MV.al_conectar` / `_sembrar_motor` + el `verificar_uno` que
    #     `connectors_router` corre detrás del response.
    #   · AL USAR → el cinturón se levanta DENTRO del run, así que usar una pieza ya la
    #     verifica y persiste su veredicto. No hace falta un tercer disparo.
    #
    # LO QUE SÍ CORRE ACÁ ES UN CENSO SIN RED: cuenta lo que hay guardado y lo dice. **Un
    # arranque mudo sobre el catálogo sería peor que uno lento** — el silencio no distingue
    # «no hay nada que barrer» de «el barrido no corrió», que es justo la razón por la que
    # el barrido viejo imprimía siempre. Cero spawns, cero red, una consulta.
    if db_ok:
        def _censo_local():
            try:
                from app.phase1 import centro_conexiones as _CC
                from app.phase1 import repo as _repo
                _c = _CC.censo_local(_repo.get_conn)
                if not _c["duenos"]:
                    print("[local] censo de arranque: nadie tiene catálogo local", flush=True)
                    return
                print(f"[local] censo de arranque: {_c['piezas']} pieza(s) de "
                      f"{_c['duenos']} dueño(s) · {_c['con_veredicto']} con veredicto "
                      f"guardado · {_c['sin_veredicto']} sin medir nunca · "
                      f"{_c['apagadas']} apagadas (lápida) · {_c['sin_belt']} sin belt "
                      f"· {_c['ms']} ms, 0 spawns", flush=True)
                # LO QUE NO SE PUDO MIRAR, POR NOMBRE — la regla del barrido viejo sigue.
                if _c["nombres_sin_veredicto"]:
                    print("[local]   sin veredicto (se medirán al usarse): "
                          + ", ".join(_c["nombres_sin_veredicto"][:12])
                          + ("…" if len(_c["nombres_sin_veredicto"]) > 12 else ""),
                          flush=True)
            except Exception as exc:  # noqa: BLE001 — el boot no se cae por esto
                print(f"[local] censo de arranque NO corrió: {exc}", flush=True)
        threading.Thread(target=_censo_local, name="censo-local", daemon=True).start()

        # MODELOS · CADUCIDAD AL ARRANCAR (Gate 2 · F4c · momento 1 de 3).
        # Mismo motivo y misma forma que el barrido local de dos bloques arriba: lo que era
        # cierto ayer puede no serlo hoy (se apagó Ollama, se cerró la sesión del CLI,
        # venció una llave), y un verde viejo es una afirmación que ya no se puede sostener.
        #
        # EN HILO Y BARATO: sólo re-mide lo que AFIRMA estar bien con una medición vencida
        # — que es lo único que puede estar mintiendo en verde. Abrir Aleph no espera por
        # esto: la pantalla se pinta con lo último que se sabe y se repinta al volver.
        #
        # ⚠️ El re-verify NO degrada `ultimo_veredicto` (usa `anotar_medicion`). Si lo
        # hiciera, un modelo roto hoy aparecería mañana en la ADUANA como si nunca hubiera
        # andado: el anti-yo-yo muerto en silencio.
        def _caducidad_modelos():
            try:
                from app.phase1 import modelos_caducidad as _MC
                from app.phase1 import repo as _repo
                conn = _repo.get_conn()
                try:
                    with conn.cursor() as cur:
                        cur.execute("SELECT DISTINCT user_id FROM conexiones")
                        duenos = [r[0] for r in cur.fetchall()]
                finally:
                    conn.close()
                for _u in duenos:
                    _p = _MC.barrer_al_arrancar(str(_u), _repo.get_conn)
                    if _p.get("re_medidas") or _p.get("fallaron"):
                        print(f"[modelos] caducidad de arranque: {_p}", flush=True)
            except Exception as exc:  # noqa: BLE001 — el boot no se cae por esto
                print(f"[modelos] caducidad de arranque NO corrió: {exc}", flush=True)
        threading.Thread(target=_caducidad_modelos, name="caducidad-modelos",
                         daemon=True).start()

    # CLI_BRAIN · BARRIDO DE ARRANQUE (F2d, cable 1 de 3). Mismo motivo y misma forma que
    # el del dueño, dos bloques más arriba: un `claude -p` que dejó vivo un sidecar anterior
    # sigue quemando la ventana de la suscripción por una respuesta que ya nadie va a
    # recibir. **NO readopta** —los pipes murieron con el padre— así que terminarlo es lo
    # único honesto. Fuera del `if db_ok`: un CLI huérfano no depende de que la base esté
    # sana, y dejarlo vivo porque la DB está rota sería sumar una fuga a un fallo.
    try:
        from cli_brain.registro import barrer_cli_al_arrancar
        _p = barrer_cli_al_arrancar()
        if _p.get("matados") or _p.get("ajenos") or _p.get("sin_pid"):
            print(f"[cli_brain] barrido de arranque: {_p}", flush=True)
    except Exception as exc:  # noqa: BLE001 — el boot no se cae por esto
        print(f"[cli_brain] barrido de arranque NO corrió: {exc}", flush=True)
    # BROKER · el barrido de SU familia (paso 3). Un `grok agent stdio` o un `codex
    # app-server` sostenidos entre turnos que sobrevivieron a un `kill -9` del sidecar no
    # están en `cli_procesos.jsonl` —ése es de turnos— sino en `broker_procesos.jsonl`.
    # Mata por PID **y comprobando el comando**: un pid reciclado con otro comando no se
    # toca. Corre siempre, tenga la perilla prendida o no: los huérfanos que hay que barrer
    # son de un arranque ANTERIOR, donde la perilla pudo estar en otra posición.
    try:
        from cli_brain.broker.pool import POOL as _POOL_BROKER
        _pb = _POOL_BROKER.barrer_al_arrancar()
        if _pb.get("muertas") or _pb.get("ajenas"):
            print(f"[broker] barrido de arranque: {_pb}", flush=True)
    except Exception as exc:  # noqa: BLE001 — el boot no se cae por esto
        print(f"[broker] barrido de arranque NO corrió: {exc}", flush=True)
    # LiteLLM · SELLADO DE ARRANQUE (Gate 2 · F4a, obra 3). UNA vez por proceso, y ACÁ.
    #
    # POR QUÉ EN EL ARRANQUE Y NO PEREZOSO: `init_litellm()` no sólo importa la librería —
    # apaga lo que la auditoría 1 midió como activo por defecto, y **dos de esas cosas hay
    # que apagarlas ANTES del primer import**, porque `litellm/__init__.py` las ejecuta al
    # importarse: un GET a raw.githubusercontent.com (§P4.a) y un `load_dotenv()` que bajo
    # PyInstaller lee el `.env` que el usuario tenga al lado de la `.app` (§P4.b). Si el
    # primer import ocurriera dentro de un turno cualquiera, el sellado dependería de qué
    # turno llegó primero. Acá no depende de nada.
    #
    # Y LOS CUATRO FALLBACKS QUEDAN EN None, que es el punto de la obra: `fallbacks`,
    # `model_fallbacks`, `context_window_fallbacks` y `content_policy_fallbacks`. El
    # cascade es de `_route_chat`, que además lo NARRA (`degraded` + cost-event + la causa
    # de F4a). Dos capas de sustitución y una sola de narración es cómo se pierde una
    # degradación sin que nadie se entere.
    #
    # COSTO MEDIDO en esta máquina: 0,97 s de import. Es sincrónico a propósito — un hilo
    # ahorraría ese segundo a cambio de que el sellado y el primer turno pudieran cruzarse.
    # Con la perilla apagada (`PUPPET_LITELLM=0`) no se importa nada y el arranque es
    # byte-idéntico al de antes de F4a. Jamás tumba el boot: si litellm no está, el camino
    # C/D corre por urllib como siempre y se dice.
    if os.environ.get("PUPPET_LITELLM", "1").strip().lower() not in ("0", "false", "no"):
        try:
            # `platform/assembler` NO está en el sys.path de este proceso (arriba sólo se
            # mete `platform/`), así que se agrega acá y sólo acá. Scoped a propósito:
            # meterlo al tope del módulo también «arreglaría» el barrido de cli_brain de
            # tres bloques más arriba, que hoy no corre por lo mismo — y prender un
            # barrido que mata procesos como efecto colateral de esta obra no se hace.
            # Va al reporte de la fase.
            _asm_dir = str(_REPO_ROOT / "platform" / "assembler")
            if _asm_dir not in sys.path:
                sys.path.insert(0, _asm_dir)
            from adaptador_litellm import init_litellm as _init_litellm
            _l = _init_litellm()
            print(f"[litellm] sellado en el arranque · v{getattr(_l, '__version__', '?')} · "
                  f"fallbacks={_l.fallbacks} num_retries={_l.num_retries}", flush=True)
        except Exception as exc:  # noqa: BLE001 — el boot no se cae por esto
            print(f"[litellm] NO se selló ({exc}) — el camino C/D va por urllib", flush=True)

    purge_task = (asyncio.create_task(_purge_loop())
                  if db_ok and _purge_enabled() else None)
    try:
        yield
    finally:
        if purge_task is not None:
            purge_task.cancel()
        bootstrap.stop()
        # EL DUEÑO · APAGAR TODO (DISEÑO-DUEÑO-v1 §1.4). **Acá `main.py` por fin sabe qué
        # matar al cerrar**: hasta ahora este `finally` paraba workers y cerraba la DB, y
        # los procesos MCP quedaban vivos porque nadie tenía la lista. Va ANTES del cierre
        # del almacén: apagar un server puede querer escribir su último diagnóstico, y
        # además el orden natural es soltar lo de afuera antes que lo de adentro.
        # En paralelo (§1.4): 8 conexiones en serie serían hasta 32 s de cierre y un ⌘Q
        # impaciente dejaría los huérfanos que esto viene a evitar.
        try:
            from inspection import dueno as _dueno
            _dueno.actual().apagar_todo(motivo="cierre del sidecar")
        except Exception as exc:  # noqa: BLE001 — el shutdown no se cae por esto
            print(f"[dueño] apagar_todo NO corrió: {exc}", flush=True)
        # CLI_BRAIN · CIERRE (F2d, cable 2 de 3). Bajo `sidecar_serve` no hacía falta —ese sí
        # lo llama, en `_request_shutdown` y en su `finally`— pero cuando el backend corre
        # SOLO (dev, `start_caso3_stack.sh`, una vara) el que muere es el backend y los
        # `claude -p` en vuelo quedan huérfanos. Va junto al `apagar_todo` del dueño porque
        # es el mismo verbo sobre la otra familia de procesos.
        # Con `start_caso3_stack.sh` el :8926 es un proceso aparte y esto es un no-op sano:
        # el lifecycle de ESTE backend no posee ese listener y `stop()` sólo mata lo suyo.
        try:
            from cli_brain.lifecycle import stop_managed_service
            stop_managed_service()
        except Exception as exc:  # noqa: BLE001 — el shutdown no se cae por esto
            print(f"[cli_brain] cierre NO corrió: {exc}", flush=True)
        # BROKER · los CLIs que quedaron VIVOS entre turnos (paso 3). Es la tercera familia
        # de procesos y necesita su propio verbo por la misma razón que las otras dos: el
        # `_ACTIVE_PROCESSES` de `base` sólo conoce los de un turno en vuelo, y un `grok
        # agent stdio` sostenido 60 s no está en ninguno de los dos. Si esto no corre, el
        # barrido de arranque del pool los caza en el próximo boot — pero un huérfano que
        # vive hasta el próximo arranque igual le come la ventana a la persona.
        try:
            from cli_brain.broker.pool import POOL as _POOL_BROKER
            _POOL_BROKER.apagar_todo(motivo="cierre del sidecar")
        except Exception as exc:  # noqa: BLE001 — el shutdown no se cae por esto
            print(f"[broker] apagar_todo NO corrió: {exc}", flush=True)
        # Cierre REAL de las conexiones ociosas del almacén (ver sqlite_db §EL DEADLOCK
        # DEL VFS): en régimen no se cierra ninguna, así que el único cierre masivo es
        # éste, y va acá —con el proceso ya sin tráfico— donde no puede pisarse con una
        # apertura. En control es no-op (no hay almacén SQLite).
        try:
            import sqlite_db
            n = sqlite_db.cerrar_almacen()
            if n:
                print(f"[db] almacén cerrado: {n} conexiones", flush=True)
        except Exception:  # noqa: BLE001 — el shutdown no se cae por esto
            pass
        db_boot.limpiar()


app = FastAPI(
    title="puppet-ai-core",
    version="0.2.0",
    description="Backend API for Puppet AI — agent creation platform",
    lifespan=_lifespan,
)
# Observabilidad (Sentry guardado por SENTRY_DSN + middleware de telemetría). A nivel
# módulo: el middleware debe montarse ANTES del primer request. No-op sin DSN.
init_observability(app)

# ── Borrado de cuenta (ticket 2): "el acceso muere YA" ─────────────────────────
# La sesión Fernet ya valida TTL y generación, pero el estado deleted_at es una frontera
# distinta → el corte de acceso de una cuenta en soft-delete se aplica ACÁ, el único
# choke point que cubre TODOS los routers a la vez (Bearer y ?token= del SSE), presentes
# y futuros. Enmienda al contrato AUTH v1: sesión válida ∧ cuenta NO borrada.
#
# Excepciones: /v1/auth/login (la puerta de reactivación) y /v1/auth/register. Fail-open
# ante errores de infra: sin DB los endpoints de datos fallan solos; este check bloquea
# únicamente cuando la DB confirma deleted_at. El costo es un SELECT por PK por request
# AUTENTICADA (sin token no consulta nada).
_DELETED_EXEMPT_PATHS = {"/v1/auth/login", "/v1/auth/register"}


# ── BLINDAJE SISTÉMICO · sesión-por-default (hallazgo #1) ──────────────────────
# Toda MUTACIÓN /v1 (POST/PUT/PATCH/DELETE) exige una sesión válida, SALVO la allowlist
# pública de authz.is_public_v1 (auth + webhook firmado). Un endpoint nuevo, sin tocar
# nada, queda cerrado — mata la clase "identidad del cliente" en la raíz: ya no se puede
# gastar recursos ni crear filas anónimamente omitiendo el user_id.
#
# Las LECTURAS quedan como están (owner-gated donde tienen dueño; catálogo público). El
# daño de la clase estaba en las mutaciones (crear runs, quemar cognición, guardar creds).
#
# OPT-OUT de dev/CI: PUPPET_ALLOW_ANON_V1=1 (default AUSENTE = cerrado, doctrina P7). Lo
# prende start_caso3_stack.sh y la suite; producción NO lo setea.
def _anon_v1_permitido() -> bool:
    return str(os.environ.get("PUPPET_ALLOW_ANON_V1", "")).strip().lower() in (
        "1", "true", "yes", "on")


@app.middleware("http")
async def _require_session_by_default(request, call_next):
    from starlette.responses import JSONResponse
    path = request.url.path
    method = request.method.upper()
    if (path.startswith("/v1")
            and method in ("POST", "PUT", "PATCH", "DELETE")
            and not _anon_v1_permitido()):
        from app.phase1 import authz
        if not authz.is_public_v1(path, method):
            token = authz.pick_token(request.headers.get("authorization"),
                                     request.query_params.get("token"))
            if authz.session_owner(token) is None:
                return JSONResponse(status_code=401, content={"detail": {
                    "error": "no_session",
                    "detail": "Esta acción necesita tu sesión. Inicia sesión."}})
    return await call_next(request)


@app.middleware("http")
async def _block_deleted_accounts(request, call_next):
    from starlette.concurrency import run_in_threadpool
    from starlette.responses import JSONResponse

    path = request.url.path
    token = None
    if path.startswith("/v1") and path not in _DELETED_EXEMPT_PATHS:
        from app.phase1 import authz
        token = authz.pick_token(request.headers.get("authorization"),
                                 request.query_params.get("token"))
    if token:
        from app.phase1 import authz
        owner = authz.session_owner(token)
        if owner:
            def _deleted_state():
                from app.phase1 import repo as _repo
                conn = _repo.get_conn()
                try:
                    return _repo.user_deleted_state(conn, owner)
                finally:
                    conn.close()
            try:
                state = await run_in_threadpool(_deleted_state)
            except Exception:
                state = None  # infra caída → fail-open (los endpoints fallan solos)
            if state and state.get("deleted_at"):
                return JSONResponse(status_code=401, content={"detail": {
                    "error": "account_deleted",
                    "purge_at": state.get("purge_after"),
                    "detail": ("Tu cuenta está desactivada. Inicia sesión de nuevo antes de "
                               f"{(state.get('purge_after') or '')[:10]} para reactivarla."),
                }})
    return await call_next(request)


# ── FALLO VISIBLE, JAMÁS MUDO [GAP-DEV-DESKTOP §2.1] ──────────────────────────
# Si el bootstrap de DB del cliente falló en el lifespan, NO se sirve "como si
# nada": TODA la superficie (menos /health, que lo REPORTA para monitoreo/watchdog)
# responde 503 con el motivo — página legible si lo pide un browser (la .app es un
# webview: esto ES el "error claro en UI"), JSON si lo pide la API. Registrado
# DESPUÉS de los otros middlewares = corre PRIMERO (Starlette apila al revés).
from app.infra import db_boot  # noqa: E402

_DB_ERROR_HTML = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Aleph — error de datos</title></head>
<body style="margin:0;font-family:-apple-system,system-ui,sans-serif;background:#14101f;
color:#efeaff;display:flex;min-height:100vh;align-items:center;justify-content:center;">
<div style="max-width:34rem;padding:2rem;text-align:center;">
<h1 style="color:#b9a6ff;font-size:1.4rem;">Aleph no puede acceder a tus datos</h1>
<p>La base de datos local no se pudo abrir o quedó incompleta, así que Aleph prefirió
detenerse antes que funcionar a medias y perder lo que guardes.</p>
<p>Cierra y vuelve a abrir la app. Si sigue pasando, este mensaje es el dato que
necesita soporte.</p>
<p style="opacity:.65;font-size:.8rem;word-break:break-word;">Detalle técnico: __DETALLE__</p>
</div></body></html>"""


# ── EL DISCO LLENO, DICHO EN LA SUPERFICIE QUE SEA ────────────────────────────────────
#
# Hermano de `_db_fail_visible`, y por el mismo motivo: sin esto, un `[Errno 28]` sale como
# HTTP 500 y cada superficie lo cuenta a su manera. Medido: un `.json.tmp` que no se pudo
# escribir terminó en la pantalla como «el entorno bloqueó la escritura temporal requerida»
# —que suena a permisos— y mandó a investigar el sandbox del CLI durante una hora.
#
# 507 y no 500: «Insufficient Storage» significa exactamente esto, así que un cliente que
# mire el código ya sabe, sin leer el texto.
#
# VA ANTES QUE EL DE LA DB EN EL ARCHIVO —o sea DESPUÉS en la cadena de ejecución, que es
# como Starlette los apila— a propósito: si el disco está lleno, la DB también va a fallar,
# y la causa que sirve es la de abajo, no la de arriba.
@app.middleware("http")
async def _disco_lleno_visible(request, call_next):
    from app.infra import disco
    try:
        return await call_next(request)
    except Exception as exc:  # noqa: BLE001
        if not disco.es_disco_lleno(exc):
            raise
        from starlette.responses import HTMLResponse, JSONResponse
        if "text/html" in (request.headers.get("accept") or ""):
            return HTMLResponse(
                _DB_ERROR_HTML.replace("__DETALLE__", disco.COPY), status_code=507)
        return JSONResponse(status_code=507, content={
            "error": disco.CAUSA,
            "detail": str(exc),
            "copy": disco.COPY,
            "disco": disco.estado()})


@app.middleware("http")
async def _db_fail_visible(request, call_next):
    err = db_boot.boot_error()
    if err is None or request.url.path == "/health":
        return await call_next(request)
    from starlette.responses import HTMLResponse, JSONResponse
    if "text/html" in (request.headers.get("accept") or ""):
        return HTMLResponse(_DB_ERROR_HTML.replace("__DETALLE__", err), status_code=503)
    return JSONResponse(status_code=503, content={
        "error": "db_unavailable",
        "detail": f"La base de datos local no está disponible: {err}"})


# ── EL GUARDIÁN DEL «¿TODAVÍA HAY ALGUIEN?» ───────────────────────────────────
#
# ⚠️ TIENE QUE SER EL ÚLTIMO MIDDLEWARE REGISTRADO DEL ARCHIVO. No es estilo: es la única
# posición en la que sirve, y el chequeo de arranque de abajo lo obliga.
#
# QUÉ ARREGLA. `request.is_disconnected()` NO FUNCIONA detrás de un `BaseHTTPMiddleware`
# —y `@app.middleware("http")` ES uno—: cada uno envuelve el `receive` del ASGI con el
# suyo, y el envuelto nunca le entrega el `http.disconnect` al endpoint, así que la
# pregunta contesta False para siempre. Bug conocido de Starlette, discussion #2094:
# https://github.com/Kludex/starlette/discussions/2094
#
# MEDIDO acá con un juguete de la misma forma que esta app:
#     0 middlewares → detecta a los 2,0s · 1 → NUNCA · 2 → NUNCA · 3 → NUNCA
# No es «cuál de los tres»: alcanza con que haya UNO.
#
# POR QUÉ EL ORDEN. El workaround es guardar la referencia ANTES de `call_next`, pero sólo
# sirve la del middleware MÁS EXTERNO — el único cuyo `receive` sigue siendo el del
# servidor. En Starlette el ÚLTIMO registrado queda MÁS AFUERA (`user_middleware[0]`).
# Medido: con el guardián adentro seguía dando NUNCA; movido afuera, 2,0s.
#
# POR QUÉ NO ALCANZA SOLO — Y POR QUÉ IGUAL HACE FALTA. Este guardián se probó una vez
# aislado y NO movió la fuga (25,1 → 25,3 s), porque la cancelación de Starlette ya llegaba
# por otro lado. Pero llega TARDE: `iterate_in_threadpool` corre el generador sync en un
# hilo no cancelable, así que el `CancelledError` no se entrega hasta que el `next()` en
# curso vuelve — o sea cuando el CLI ya terminó. La señal de este guardián es la que llega
# a tiempo. Sin ella no hay a quién preguntarle; sin el socket atado no hay qué cerrar.
# Hacen falta las dos, y por eso ésta volvió después de haber sido descartada.
#
# QUÉ PASA SI SE ROMPE. Si alguien registra otro `@app.middleware("http")` DESPUÉS, el
# chequeo vuelve a mentir en silencio y con él vuelve la fuga: el usuario cierra la Sala y
# el CLI sigue quemándole la ventana de su suscripción. Por eso el chequeo de abajo no
# avisa — tumba el arranque.
@app.middleware("http")
async def _guardar_chequeo_de_desconexion(request, call_next):
    request.state.is_disconnected = request.is_disconnected
    return await call_next(request)


def _verificar_guardian_externo(_app: "FastAPI") -> None:
    """El guardián es el más externo, o la app NO arranca. FALLO VISIBLE, JAMÁS MUDO.

    Dejar pasar es lo que convierte esto en un bug de seis meses: nada se rompe a la
    vista, sólo se le empieza a quemar cuota al usuario, y no hay superficie donde se note.
    """
    pila = list(getattr(_app, "user_middleware", []) or [])
    externo = pila[0] if pila else None
    if externo is not None and (externo.kwargs or {}).get(
            "dispatch") is _guardar_chequeo_de_desconexion:
        return
    culpable = getattr((getattr(externo, "kwargs", None) or {}).get("dispatch"),
                       "__name__", None) or "«no hay middlewares»"
    raise RuntimeError(
        f"[middleware] {culpable} quedó por FUERA del guardián de desconexión "
        "`_guardar_chequeo_de_desconexion`. En Starlette el ÚLTIMO middleware registrado "
        "es el más externo, y el guardián sólo funciona ahí: es el único lugar donde el "
        "`receive` todavía es el del servidor y no uno envuelto por otro "
        "BaseHTTPMiddleware (github.com/Kludex/starlette/discussions/2094). "
        "CONSECUENCIA: `is_disconnected()` contesta False para siempre, el backend no se "
        "entera de que el cliente cerró la Sala, y el CLI del cerebro sigue generando para "
        "nadie — quemándole al usuario la ventana de su suscripción. "
        f"ARREGLO: mueve el `@app.middleware(\"http\")` de {culpable} a ANTES del guardián "
        "en app/main.py, para que el guardián siga siendo el último del archivo.")


# ── Repo root resolution ──────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[3]  # product/backend/app -> repo root

# ── Frescura del código (Step 2 · A1) ─────────────────────────────────────────
# El backend corre SIN --reload → su código queda CONGELADO en este import. Calculamos
# la huella del árbol runtime UNA vez, ACÁ (= exactamente lo que el proceso cargó), y la
# publicamos en /health. El harness la compara contra el disco antes de cada tanda: si el
# disco es más nuevo → backend stale → abortar (evita testear código viejo = root-cause A1).
_STARTED_AT = time.time()
try:
    if str(_REPO_ROOT / "platform") not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT / "platform"))
    from gates.code_freshness import compute_fingerprint as _compute_fp
    _CODE_FP = _compute_fp(_REPO_ROOT)
except Exception as _fp_exc:  # nunca tumbar el arranque por la huella
    _CODE_FP = {"error": f"fingerprint-failed: {_fp_exc}"}

# ── LA FRONTERA cliente / plano de control [Casa 2 · Fase 2 · 2.0] ────────────────
# Se importa ACÁ, después de meter platform/ en el sys.path y ANTES de montar routers:
# el rol decide QUÉ superficie existe en este proceso. Ver platform/role.py.
# El default es `client` (fail-closed): un rol sin declarar NO expone pagos.
if str(_REPO_ROOT / "platform") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "platform"))
import role as _rol  # noqa: E402
import build_id as _build  # noqa: E402  [4.4.3] founder = BUILD baked → Motor B LOCAL (no tier)
import aleph_paths  # noqa: E402  [Casa 2 · Fase 3 · B3] dónde escribe el runtime (rol-aware)
# flush=True NO es decorativo: sin él la línea queda en el buffer de stdout y, si el
# proceso muere antes de vaciarlo, EL ROL NO APARECE EN EL LOG. Verificado: arrancando
# bajo uvicorn y matando el proceso, esta línea se perdía mientras las de TELEMETRY (que
# usan logger) sí salían. Es LA señal para saber con qué rol arrancó un deploy — si se
# puede perder, no sirve.
print(f"[rol] {_rol.describe()}", flush=True)

# ── Stores (singleton per process; tests inject via dependency override) ──────

# [Casa 2 · Fase 3 · B3] El DÓNDE de espacios/vault lo decide aleph_paths por rol:
# cliente → dir de datos del usuario (fuera del árbol); control → product/backend/data
# (histórico, prod NO se mueve). Ver platform/aleph_paths.py.
_VAULT_PY = _REPO_ROOT / "platform" / "gates" / "vault.py"

_espacios_store: Optional[EspaciosStore] = None
_session_manager: Optional[SessionManager] = None
_session_factory: Optional[SessionFactory] = None
_vault: Optional[Any] = None


def _load_vault_module():
    """Carga platform/gates/vault.py por ruta de archivo (mismo patrón que espacios
    usa para session.py): el backend no asume que platform sea un paquete."""
    import aleph_paths
    return aleph_paths.load_module_by_path("puppet_vault", _VAULT_PY)


def get_vault() -> Any:
    """
    Vault de credenciales del runtime (cifrado Fernet). El secreto maestro vive en
    el entorno (PUPPET_VAULT_MASTER); en su ausencia (dev local), uno derivado del
    host — NUNCA en código de dominio. El valor de una credencial jamás se
    serializa a una respuesta ni a un log (contrato del vault).
    """
    global _vault
    if _vault is None:
        vault_mod = _load_vault_module()
        try:
            _node = os.uname().nodename                # POSIX (control/prod byte-idéntico)
        except AttributeError:                          # [Fase 3 · B1] Windows: os.uname no existe
            import platform as _pf
            _node = _pf.node() or "aleph-client"
        master = os.environ.get("PUPPET_VAULT_MASTER") or f"puppet-dev-{_node}"
        vault_file = aleph_paths.vault_path()          # [Fase 3 · B3] fuera del árbol en cliente
        vault_file.parent.mkdir(parents=True, exist_ok=True)
        _vault = vault_mod.CredentialVault(str(vault_file), master_secret=master)
    return _vault


def _visible_tiers_for_session(authorization: Optional[str]) -> set[str]:
    """Tiers de template visibles para la cuenta de ESTA sesión.

    Fail-closed en cada escalón: sin token, token inválido, cuenta inexistente o
    cualquier excepción resolviendo el tier → lo más restrictivo (free). Un catálogo
    que se abre de más por un error es exactamente lo que la muralla evita.
    """
    from app.phase1 import repo
    try:
        from gates import tier_gate
    except Exception:
        return {"average"}          # capa de tier rota → mínimo, nunca máximo

    tok = (authorization or "").strip()
    if tok.lower().startswith("bearer "):
        tok = tok[7:].strip()
    if not tok:
        return tier_gate.visible_template_tiers("free")

    try:
        owner = repo.session_owner(tok)
        if not owner:
            return tier_gate.visible_template_tiers("free")
        conn = repo.get_conn()
        try:
            tier = tier_gate.resolve_account_tier(conn, owner, repo)
        finally:
            conn.close()
        return tier_gate.visible_template_tiers(tier)
    except Exception:
        return tier_gate.visible_template_tiers("free")


def get_espacios_store() -> EspaciosStore:
    global _espacios_store
    if _espacios_store is None:
        _espacios_store = EspaciosStore(aleph_paths.espacios_dir())  # [Fase 3 · B3]
    return _espacios_store


def get_session_manager() -> SessionManager:
    global _session_manager
    if _session_manager is None:
        # _session_factory is None in production → SessionManager uses its real
        # default (a live Session on the config's local lane). Tests inject a stub.
        _session_manager = SessionManager(factory=_session_factory)
    return _session_manager


def load_arrancador_config(nicho: str, arrancador_id: str) -> Optional[dict]:
    """
    The catalog is the DATA SOURCE for starter kits: read the template's real
    config.json from catalog/templates/{nicho}/{arrancador_id}/config.json and
    return it to be copied into the new espacio. Zero hardcoded config (D3).
    """
    cfg_path = CATALOG_ROOT / nicho / arrancador_id / "config.json"
    if not cfg_path.exists():
        return None
    try:
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


# ── Dependency injection helpers (for tests) ─────────────────────────────────

def set_espacios_store(store: EspaciosStore) -> None:
    global _espacios_store
    _espacios_store = store


def set_session_manager(manager: SessionManager) -> None:
    global _session_manager
    _session_manager = manager


def set_vault(vault: Any) -> None:
    """Inyecta el vault (tests: un CredentialVault sobre tmp_path)."""
    global _vault
    _vault = vault


def set_session_factory(factory: Optional[SessionFactory]) -> None:
    """
    Inject the session factory used by a freshly-built SessionManager. In tests
    this is a stub that returns a fake session WITHOUT running any LLM. Setting it
    also invalidates the cached manager so the next get_session_manager() rebuilds
    with the new factory.
    """
    global _session_factory, _session_manager
    _session_factory = factory
    _session_manager = None


def reset_stores() -> None:
    """Reset all stores to None (used in tests)."""
    global _espacios_store, _session_manager, _session_factory, _vault
    # park any live sessions before dropping the manager (closes fake/real belts)
    if _session_manager is not None:
        try:
            _session_manager.park_all()
        except Exception:
            pass
    _espacios_store = None
    _session_manager = None
    _session_factory = None
    _vault = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

def _sello_build() -> dict:
    """Identidad del PROCESO que contesta: commit + tipo de build + arranque.

    Existe para no volver a hablarle a un proceso fantasma — un sidecar viejo que quedó
    escuchando el puerto y contesta con código de hace días. Sin rutas ni nada del
    entorno: sólo lo que identifica la compilación."""
    sello = {"build": _build.current(), "started_at": round(_STARTED_AT, 3)}
    sha = _CODE_FP.get("git_sha") if isinstance(_CODE_FP, dict) else None
    if sha:
        sello["commit"] = sha[:12]
        sello["dirty"] = bool(_CODE_FP.get("git_dirty"))
    return sello


def _estado_datos() -> Optional[dict]:
    """Salud del camino de datos del cliente (watchdog del deadlock del VFS), o None
    en el plano de control (allá la base es Postgres y esto no aplica)."""
    if not _rol.is_client():
        return None
    try:
        import sqlite_db
        return sqlite_db.estado_db()
    except Exception as exc:  # noqa: BLE001 — el health JAMÁS se cae por reportar
        return {"estado": "desconocido", "motivo": f"{type(exc).__name__}: {exc}"}


@app.get("/health")
def health_check():
    out = {"status": "ok", "service": "puppet-ai-core", "version": "0.2.0"}
    # [GAP §2.1] FALLO VISIBLE: si el bootstrap de DB falló, /health lo DICE — es el
    # único endpoint que responde normal (para que monitoreo/watchdog lean el motivo;
    # el resto de la superficie responde 503 vía _db_fail_visible).
    db_err = db_boot.boot_error()
    if db_err:
        out["status"] = "error"
        out["db"] = db_err
    # [disco] EL AVISO TEMPRANO. `/health` ya reportaba la DB y el VFS; el disco faltaba,
    # y es la causa que más se disfraza. Con poco espacio el estado deja de ser «ok» aunque
    # todavía no haya fallado nada: es el único momento en que el aviso sirve.
    try:
        from app.infra import disco as _disco
        _d = _disco.estado()
        out["disco"] = _d
        if _d.get("estado") == "bajo":
            out["status"] = "degradado"
            out["copy"] = _disco.COPY
    except Exception:  # mirar el disco jamás puede tumbar /health
        pass
    out["proceso"] = _sello_build()
    # WATCHDOG DEL CAMINO DE DATOS. Antes /health decía "ok" mientras el proceso tenía el
    # VFS de SQLite trabado y la app entera se moría muda (ver sqlite_db §EL DEADLOCK DEL
    # VFS). Un `ok` que convive con "no se puede guardar nada" es peor que un error: hace
    # que el supervisor NO reinicie. Ahora se REPORTA, con motivo.
    datos = _estado_datos()
    if datos is not None:
        out["datos"] = datos
        if datos.get("estado") == "trabado" and out["status"] == "ok":
            out["status"] = "degraded"
    # `code` = huella de frescura del proceso (Step 2 · A1) que el harness compara contra el disco
    # antes de cada tanda. Es info del entorno (git_sha/dirty/mtime) → NO se expone por default en un
    # endpoint público; SÓLO cuando el stack de test lo habilita con PUPPET_HEALTH_FRESHNESS (lo setea
    # restart_backend.sh). En prod (sin el flag) /health queda mínimo. Nunca van rutas absolutas.
    if os.environ.get("PUPPET_HEALTH_FRESHNESS"):
        code = {k: v for k, v in _CODE_FP.items() if k not in ("repo_root", "newest_source")}
        code["started_at"] = round(_STARTED_AT, 3)
        out["code"] = code
    return out


@app.get("/catalog/brands")
def get_brands():
    """
    Declared brands per belt server + per-template gate copy.
    The UI consumes this verbatim (label, monogram, color, logo, human connection
    name) and NEVER guesses. Registered before /catalog/{nicho} so 'brands' is
    not matched as a nicho. PARAMETRIZABLE — see catalog/brands.json.
    """
    return load_brands()


@app.get("/catalog/{nicho}", response_model=CatalogResponse)
def get_catalog(
    nicho: str,
    authorization: Optional[str] = Header(default=None),
):
    """
    List templates for a given nicho.
    nicho is a path parameter — fully parametrizable, zero hardcoded domain names.
    Templates are filtered by the tier of the SESSION's account.

    [Step 5 · P8 · T-S5-01] El tier salía de un `user_id` de QUERY STRING, o sea de
    input del cliente: `GET /catalog/finanzas?user_id=<uuid-de-un-premium>` devolvía
    el listado premium a cualquiera. Violaba la doctrina de la muralla ("el cliente
    JAMÁS se confía"). Ahora sale de la sesión y el parámetro NO existe: no hay nada
    que falsificar. Sin sesión → free, que es lo más restrictivo (fail-closed).

    Además lee de POSTGRES vía tier_gate. Antes consultaba un SQLite de cuentas
    PARALELO (product/backend/data/users.db) que nadie sincronizaba: una cuenta
    premium en Postgres era free acá. Ese store murió en P8 — una sola fuente de
    verdad (§2.4).
    """
    if not nicho_exists(nicho):
        raise HTTPException(status_code=404, detail=f"Nicho '{nicho}' no encontrado en el catálogo")

    templates = load_catalog(nicho)

    # Tier gating — SIEMPRE server-side, desde la cuenta de la sesión.
    visible_tiers = _visible_tiers_for_session(authorization)

    filtered = [t for t in templates if t.get("tier", "") in visible_tiers]

    return {
        "nicho": nicho,
        "total": len(filtered),
        "templates": filtered,
    }


# ── Routers V2 `/espacios/*` (espacios + conexiones) — RETIRADOS (Fase 4) ─────
# Superseded por el path canónico /v1/* (runs/approve, spaces/stream, connectors).
# 0 referencias del frontend. NO se montan → /espacios/* devuelve 404. Los archivos
# espacios.py/conexiones.py quedan en el repo como legacy (reversible); EspaciosStore
# sigue vivo solo como almacén de events.jsonl para el SSE de phase1 (ver _phase1_events_dir).


# ── Router FASE 1 canónico (/v1/*) ─────────────────────────────────────────────
# La FUENTE ÚNICA del path de prod: validador ANIDADO (recipe_validator) + store
# POSTGRES (repo → platform/db, base puppet_ai). Reemplaza al validador plano y al
# store SQLite/JSONL (retirados en la migración 2026-06-15).
#
# Inyección por callables (mismo patrón que espacios/conexiones): el router resuelve
# get_conn y events_dir en tiempo de request. get_conn devuelve una conexión psycopg2
# fresca a puppet_ai (el endpoint la cierra). events_dir apunta al workdir de espacios
# donde el loop persiste events.jsonl por space_id (token-cost CERO en el stream SSE).

def _phase1_get_conn():
    """Conexión psycopg2 fresca a puppet_ai (vía la capa canónica platform/db)."""
    return phase1_repo.get_conn()


def _phase1_events_dir() -> Path:
    """Dir raíz de los events.jsonl por space_id (el del store de espacios)."""
    return get_espacios_store().root


app.include_router(
    build_phase1_router(
        get_conn=_phase1_get_conn,
        events_dir=_phase1_events_dir,
    )
)
# (e) BYOK falla a media tarea → 424 + señal TIPADA (screen 11), no un 500 mudo.
install_byok_handler(app)


# ── El camino de datos trabado sale TIPADO, no como 500 mudo ────────────────────
# `DBNoDisponible` la levanta `sqlite_db` cuando la apertura/cierre real de SQLite no se
# pudo tomar dentro del plazo — o sea, el VFS quedó trabado (ver sqlite_db §EL DEADLOCK
# DEL VFS). Antes eso era un cuelgue infinito y la app quedaba muda; ahora el front recibe
# 503 con causa y puede DECIRLO. `Retry-After` porque no se arregla solo: hay que reiniciar.
if _rol.is_client():
    try:
        from sqlite_db import DBNoDisponible as _DBNoDisponible

        @app.exception_handler(_DBNoDisponible)
        async def _db_trabada_handler(request, exc):  # noqa: ANN001
            from starlette.responses import JSONResponse
            return JSONResponse(status_code=503, headers={"Retry-After": "5"}, content={
                "detail": {"error": "db_wedged", "detail": str(exc),
                           "recuperable": False}})
    except ImportError:                              # pragma: no cover — empaquetado raro
        pass

# ── Connectors router (D2: connect-wizard genérico vía connect_engine) ──────────
app.include_router(build_connectors_router(get_conn=_phase1_get_conn))
app.include_router(build_connector_entities_router(get_conn=_phase1_get_conn))

# ── Belts router (cards legibles del belt por nicho — vista de usuario, data-driven) ──
app.include_router(build_belts_router(get_conn=_phase1_get_conn))

# ── Atoms router (GET /v1/atoms/catalog — inventario de piezas del diorama, zonado C3) ──
app.include_router(build_atoms_router(get_conn=_phase1_get_conn))

# ── Cinturón (/v1/cinturon/calentar) — el disparo del §6: levantar al ABRIR el agente ──
# `calentar_cinturon.calentar()` existía y no lo llamaba nadie. Ésta es su única ruta: la
# Sala la pega al abrir y las cards se pintan solas leyendo el registro.
from app.phase1.cinturon_router import build_cinturon_router
app.include_router(build_cinturon_router(get_conn=_phase1_get_conn))

# ── Motor de verdad (CUARTO HONESTO · T1 · §2) — /v1/motor/* : ESTADO VERIFICADO ──
# La capa que convierte "existe" (vitrina/estado_honesto) en "lo probé, hace N seg, esto
# respondió" — o "roto, por ESTA causa, arreglalo acá". Pruebas reales por tipo (cerebro/
# mcp/key/cli), resultado tipado {estado,causa,evidencia,ts}, cache TTL en memoria. Cliente
# + SQLite (la prueba de key lee la tabla `keys` vía get_conn); byo_mcp/cli_brain viajan al
# sidecar frozen (zona RESOLVE). El estado del cerebro del Guía y del selector sale de acá.
from app.phase1.motor_verdad import build_motor_router
app.include_router(build_motor_router(get_conn=_phase1_get_conn))

# ── Conexiones router (/v1/conexiones/* — EL CENTRO DE CONEXIONES · nivel 2) ──
# El motor de arriba dice "roto por ESTA causa"; éste dice QUÉ FALTA, requisito por
# requisito, en vivo (SSE con latido) y con EL COMANDO exacto cuando el arreglo es del
# humano. No duplica el motor: lo usa (mismo vocabulario CERRADO de causas, misma cache).
# También es donde vive "agregar key" de verdad: valida contra el proveedor ANTES de
# guardar y deja la llave cifrada + PROBADA (sin volver a pegarla nunca).
from app.phase1.centro_conexiones import build_conexiones_router
app.include_router(build_conexiones_router(get_conn=_phase1_get_conn))

# ── Modelos router (/v1/modelos/* — EL CENTRO DE MODELOS · FIX-P8 · el punto 35) ──
# La separación que ordena el producto: MODELOS = lo que piensa · CONECTORES = lo que
# hace. Los MCPs viven en el Catálogo y no cruzan a esta pantalla, por construcción (este
# módulo no conoce belts). Acá viven los 3 modos (CLI · API con tu llave · LOCAL
# descargado), las 5 categorías, el catálogo VIVO de Hugging Face, el veredicto contra tu
# máquina (disco/RAM), la descarga guiada cancelable con su PRUEBA AUTOMÁTICA, y el
# capability gating (nada corre mudo: si el modelo no alcanza, se dice antes de correr).
from app.phase1.centro_modelos import build_modelos_router
app.include_router(build_modelos_router(get_conn=_phase1_get_conn))

# ── Contrato canónico de uso de modelos (/v1/model-use/*) ──────────────────────
# Preflight secretless y selector común. Aditivo: todavía NO desvía tráfico; fija owner,
# scope, capacidades y selección antes de que los adaptadores de Cuarto/Sala entren.
from app.phase1.model_use_router import build_model_use_router
app.include_router(build_model_use_router(get_conn=_phase1_get_conn))

# ── Catalog search router (GET /v1/catalog/search — el CATÁLOGO VISIBLE de conectores) ──
# Invierte el descubrimiento: el usuario BUSCA y VE (interno curado + registro público) con
# BADGE de confianza; el resolver pasa a ser la validación al elegir. T-3: registro caído →
# registry_status:"unreachable" + notice, NUNCA lista vacía fingida.
from app.phase1.catalog_search_router import build_catalog_search_router
app.include_router(build_catalog_search_router(get_conn=_phase1_get_conn))

# ── Dos catálogos: local persistido + ingesta visible del registro público ──
# Lee manifests existentes (NO Motor B), limpia/clasifica/sintetiza y persiste sólo
# entradas que cumplen el contrato compartido. La ingesta emite las cuatro etapas.
from app.phase1.catalog_ingest_router import build_catalog_ingest_router
app.include_router(build_catalog_ingest_router())

# ── Catalog validate router (GET /v1/catalog/validate — RESOLVER-AL-ELEGIR) ──
# Tras navegar el catálogo y ELEGIR, aplica la validación anti-impostor (mcp_resolver.
# classify_service) → veredicto de 3 valores: confiable | dudoso | nada. Anti-impostor al
# elegir (picked_is_trusted). T-3: registro caído → registry_status:"unreachable" + verdict:null.
from app.phase1.catalog_validate_router import build_catalog_validate_router
app.include_router(build_catalog_validate_router())

# ── Catalog equip router (POST /v1/catalog/equip — EQUIPAR-DESDE-REGISTRO · FREE) ──
# El carril LIBRE que faltaba en el cliente: buscar (registro) → CURAR (validate_live · el
# sistema inmune) → equipar, SIN tocar el Motor B. Reemplaza el dead-end del dispatcher (que
# importa forge_router, EXCLUIDO del cliente, y muere). REUSA el curador del dispatcher
# (_resolve_decision + _equip_found · forge-free). MISS no forja: corta honesto → premium.
# SIN gate de rol: usar/conectar lo que YA existe = FREE. Construir lo que NO = premium (dispatch).
from app.phase1.catalog_equip_router import build_catalog_equip_router
app.include_router(build_catalog_equip_router(get_conn=_phase1_get_conn))

# ── Instructions router (Ola UX-UNIVERSAL · B5) — instrucciones persistentes ──
# CRUD de instrucciones por cuenta/composición (anti-IDOR por sesión). Se inyectan al
# framing de cada run (executor→assembler y stream_chat); las propuestas del agente
# nacen INERTES y sólo el humano las activa (el PATCH enabled es el gate).
from app.phase1.instructions_router import build_instructions_router
app.include_router(build_instructions_router(get_conn=_phase1_get_conn))

# ── Methods router (pieza MÉTODO · workflows) — biblioteca + equipar por referencia ──
# CRUD de la biblioteca de métodos por cuenta (anti-IDOR por sesión) + equipar/desequipar
# = recipe.belt.method_refs[] (referencia, no copia — espejo de agent_refs; el puente D3
# se re-exporta al mutar para que los agentes anidados vean el set nuevo). El arnés del
# run resuelve method_id→biblioteca en el executor (el motor queda DB-agnóstico).
from app.phase1.methods_router import build_methods_router
app.include_router(build_methods_router(get_conn=_phase1_get_conn,
                                        events_dir=_phase1_events_dir))

# ── Account router (ORDEN 5 · gate de propuesta de MEMORIA DE CUENTA · Sistema 2) ──
# El run PROPONE hechos sobre la persona (inertes, pinned=FALSE); acá el humano los CONFIRMA
# (pinned=TRUE → recién ahí sus agentes los leen) o rechaza. Anti-IDOR por owner de la sesión;
# la cuenta jamás cruza de usuario (invariante #4).
from app.phase1.account_router import build_account_router
app.include_router(build_account_router(get_conn=_phase1_get_conn))

# ── Chats router (Ola UX-UNIVERSAL · A1/A2) — historial persistente de la Sala ──
# CRUD + búsqueda de conversaciones por composición (anti-IDOR por sesión). Los TURNOS
# los persisten los endpoints de run cuando el body trae chat_id (el registro nace del
# turno real); acá solo se lista/retoma/busca/renombra/borra.
from app.phase1.chats_router import build_chats_router
app.include_router(build_chats_router(get_conn=_phase1_get_conn))

# Buscar en LO PROPIO: hilos + mensajes + artefactos en una consulta (el alcance que se
# midió en OpenScience) sobre FTS5 (el motor que ya trae SQLite), con el dueño y el espacio
# como TOKENS del MATCH y no como filtro posterior. `/v1/chats/search` sigue vivo y sigue
# siendo el que usa el sidebar de la Sala: éste no lo reemplaza, lo ensancha.
from app.phase1.busqueda_router import build_busqueda_router
app.include_router(build_busqueda_router(get_conn=_phase1_get_conn))

# ── [Gate 4 · F6 · §6.a.bis] La búsqueda WEB de la Sala ───────────────────────────────
# No confundir con el de arriba: `busqueda_router` busca en LO PROPIO (hilos, artefactos);
# éste sale a internet y trae fuentes citadas. Son dos capacidades distintas que la
# palabra «búsqueda» junta, y por eso el prefijo las separa (`/v1/busqueda` vs `/v1/sala`).
from app.phase1.sala_busqueda_router import build_sala_busqueda_router
app.include_router(build_sala_busqueda_router(get_conn=_phase1_get_conn))
# [Gate 4 · Fase 6 · §6.a] BROWSER USE y el webview local genérico, por la MISMA puerta.
from app.phase1.sala_browser_router import build_sala_browser_router
app.include_router(build_sala_browser_router(get_conn=_phase1_get_conn))

# [§6.a] EL SIDECAR DECLARA SU PROPIO PUERTO al guard de loopback. Sin esto el guard es
# fail-closed para TODO loopback —correcto, porque no puede descartar que un puerto sea el
# suyo— y el webview local no mostraría nada nunca. Lo destapó la prueba de humo.
try:
    import os as _os
    from browser import loopback as _lb
    _p = int(_os.environ.get("ALEPH_SIDECAR_PORT") or _os.environ.get("PORT") or 0)
    if _p:
        _lb.fijar_sidecar(_p)
except Exception:                                    # noqa: BLE001
    pass

# [§6.f] Y EL MODO LARGO, que es otra capacidad y no una variante de la anterior: una
# tarda segundos, la otra minutos. Comparten el prefijo `/v1/sala` porque las dos son
# capacidades de LA SALA —no workspaces—, y se separan por su verbo: `buscar` vs
# `investigar`. El segundo trae además `investigar/parar`, que el primero no necesita.
from app.phase1.sala_research_router import build_sala_research_router
app.include_router(build_sala_research_router(get_conn=_phase1_get_conn))

# ── Preferencias: los ajustes de la casa, por dueño y por ámbito ──────────────────────
# [Convergencia · superficie 3 · fase 2] Los tres ejes transversales que no tenían dónde
# vivir —tamaño de texto (de Legal), idioma de salida del modelo y tema de código (de
# Educación)—. No hay `get_conn`: el almacén es el MISMO archivo por dueño que ya usa la
# memoria de workspaces (`platform/workspaces/memoria.py`), con su candado, su escritura
# atómica 0600 y su `schema_version` leída. Un segundo almacén sería un segundo lugar
# donde arreglar el día que la clave de dominio cambie.
from app.phase1.preferencias_router import build_preferencias_router
app.include_router(build_preferencias_router())

# ── Tools router (GET /v1/tools/{ref}/handler — código del handler, READ-ONLY · profundidad 3) ──
app.include_router(build_tools_router())

# ── Abrir router (POST /v1/dev/abrir — [reforma · l] el código se abre en VS Code, no se
# edita en un <pre>. Sólo cliente de escritorio; el path lo resuelve el backend, nunca el
# cliente. Ver el contrato de seguridad en abrir_router.py) ──
from app.phase1.abrir_router import build_abrir_router
app.include_router(build_abrir_router())

# ── Icons router (GET /v1/icons/{slug} — la cara de cada servicio: favicon curado y
# cacheado server-side; desconocido/takedown → 404 → fallback genérico en el front) ──
from app.phase1.icons_router import build_icons_router
app.include_router(build_icons_router())

# ── Gate Advisor (POST /v1/advisor/classify — consecuencia por tool para el Cuarto:
# fail-closed, exfil incluida; reusa los hints del gate de runtime, no ejecuta nada) ──
from app.phase1.advisor import build_advisor_router
app.include_router(build_advisor_router())

# ── Inspect router (POST /v1/inspect — dispara el motor de inspección → space; el Cuarto lo anima) ──
if _rol.is_control() or _build.is_founder():   # [4.2.a·D-A] Motor B NO viaja al cliente público;
    # [4.4.3] SÍ al founder (build baked, no un tier flippable) → forja LOCAL.
    from app.phase1.inspect_router import build_inspect_router
    app.include_router(build_inspect_router())

# ── Forge router (POST /v1/inspect/forge — LA COSTURA · Ola 0) — entrada HTTP al MOTOR B ──
# Invoca el pipeline real de platform/inspection (loop §3) y emite el STREAM DE EVENTOS del
# CONTRATO por SSE (sesion.ok → observando → tool.propuesta → tool.validando →
# tool.validada/descartada → mcp.forjado), cada uno con evidencia CRUDA. ADITIVO: corre en
# PARALELO a /v1/inspect (Motor A · recon-demo), no lo reemplaza. Vive en la familia
# /v1/inspect/* (el path /v1/forge ya es de "LA FORJA" de recetas). Esta ola: forma="token".
if _rol.is_control() or _build.is_founder():   # [4.2.a·D-A] EL MOAT no viaja al cliente público;
    # [4.4.3] el build founder lo lleva y forja LOCAL (is_founder = baked, jamás un tier).
    from app.phase1.forge_router import build_forge_router
    app.include_router(build_forge_router())

# ── Cuarto guide router (POST /v1/cuarto/guide — LA COSTURA CHAT del GUÍA del Cuarto) ──
# UNA vuelta stateless del cerebro-guía (el loop de tool-calling vive en el cliente,
# cuarto.guide.js, que ejecuta cada tool_call llamando el mismo handler que el mouse). Reenvía
# {messages, tools} al cerebro elegido (models.resolve) y devuelve el turno del asistente. No
# ejecuta ninguna tool del Cuarto ni toca el mundo — la línea de seguridad la enforcea el host.
from app.phase1.cuarto_guide import build_cuarto_guide_router
app.include_router(build_cuarto_guide_router())

# ── Session router (Ola 3 · 3-browser-oauth) — POST /v1/inspect/session/browser ──
# La CUARTA forma de sesión: software detrás de OAuth+2FA. Abre un navegador INSTRUMENTADO
# donde el HUMANO hace el login + el segundo factor (línea roja §2: el motor NUNCA automatiza
# el 2FA), captura la sesión resultante (storage_state, CIFRADO) y devuelve un session_key que
# el forge REUSA (forma="browser-oauth"). Reemplaza el 501 que 2f-formas dejó marcado. ADITIVO:
# no toca las otras 3 formas (abierto/token/login).
if _rol.is_control():   # [4.2.a · D-A] Motor B (session Forma 3) NO viaja al cliente
    from app.phase1.session_router import build_session_router
    app.include_router(build_session_router())

# ── Resolve router (C7) — /v1/resolve : "servicio + credencial" → pieza equipada ──
# El riel que faltaba ADELANTE del BYO-MCP: encuentra el MCP que YA existe (registro oficial
# registry.modelcontextprotocol.io + matcher anti-impostor), inyecta la credencial DESDE EL
# VAULT y la equipa reusando la forja del BYO. ADITIVO (no toca /v1/inspect/byo).
from app.phase1.resolve_router import build_resolve_router
app.include_router(build_resolve_router(get_conn=_phase1_get_conn))

# ── Dispatch router (§0.5) — /v1/inspect/dispatch : BUSCÁ-ANTES-DE-FORJAR ──
# El "if que ordena": PRIMERO el resolver (¿hay un MCP verificado en el registry?), y SOLO si
# no existe → el Motor B (/v1/inspect/forge). Encontrado→equip 1-B (sin forjar); miss→forja.
# NO reescribe resolver ni Motor B — los reusa tal cual; respeta el anti-impostor DNS.
from app.phase1.dispatch_router import build_dispatch_router
app.include_router(build_dispatch_router(get_conn=_phase1_get_conn))

# ── Mesa router (ola construcción-asistida) — /v1/construcciones/* : LA MESA DE CONSTRUCCIÓN ──
# Reorganiza el Motor B en una co-construcción VISIBLE de 6 estaciones, con dos inversiones:
# resultados-primero (borrador retomable) + preguntar-temprano (el motor pausa y pregunta donde
# duda). El stream de la construcción ES el space stream existente; este router expone los
# controles (crear/responder/aportar/retomar/validar-tools/probar/equipar). NO reconstruye el
# motor: reusa run_internal_loop + provider_and_auth + el candado 5/5. Vocabulario: construcción.
if _rol.is_control():   # [4.2.a · D-A] Motor B (mesa de construcción) NO viaja al cliente
    from app.phase1.mesa_router import build_mesa_router
    app.include_router(build_mesa_router())

# ── Billing router (T7) — /v1/billing/* : metering + cap de presupuesto + Stripe ──
# Consume el COST-EVENT (§4.6) y CORTA al usuario que excede su quota (no funde la cuenta).
if _rol.is_control():
    from app.phase1.billing_router import build_billing_router   # [4.2.a] import gateado tb (no viaja al cliente)
    app.include_router(build_billing_router(get_conn=_phase1_get_conn))
else:
    # [Casa 2 · 2.0] Billing entero es del plano de control: sus 4 tablas (billing_ledger,
    # billing_quota, billing_runs_ingested, billing_stripe_events) NUNCA salen de ahí, así
    # que en el cliente estos endpoints no tendrían contra qué responder. Y /webhook/stripe
    # no puede existir en la máquina de un usuario.
    print("[rol] billing_router NO montado (control-plane-only)", flush=True)

# ── Payments router (Step 5 · Casa 1) — /v1/payments/* : EL PUENTE PAGO → TIER ──
# OJO, no confundir con billing (arriba): billing acredita PRESUPUESTO de gasto
# (billing_quota.credits_usd, carril Stripe); esto activa el FLAG DE TIER (users.tier,
# carril Dodo). Ejes distintos, tablas distintas, a propósito.
# Habla la interfaz de platform/payments — jamás el SDK de un procesador (§4-bis).
from app.phase1.payments_router import build_payments_router
# [Casa 2 · 2.0] Acá el corte NO puede ser por router: payments mezcla los dos lados.
# `/webhook/{procesador}`, `/checkout` y `/reconcile` son del plano de control — cobrar y
# activar el plan. Pero `GET /me/tier` lo NECESITA el cliente: es cómo pregunta su plan, y
# por D1 lo contesta desde su caché local en vez de llamar a casa en cada check (eso
# rompería local-first). Por eso el rol entra AL builder y el corte es por endpoint.
app.include_router(build_payments_router(get_conn=_phase1_get_conn, rol=_rol.current()))

# ── Infra router (T8): cola ASÍNCRONA durable (/v1/runs/enqueue, /v1/jobs) + /health/deep.
# ADITIVO: no toca /v1/puppets/run (síncrono) — agrega el camino que no bloquea y sobrevive
# reinicios. Reusa get_conn/events_dir/repo_root del path canónico.
from app.infra.infra_router import build_infra_router
app.include_router(build_infra_router(
    get_conn=_phase1_get_conn,
    events_dir=_phase1_events_dir,
    repo_root=_REPO_ROOT,
))

# ── Multiagente router (F1 · CADENA — docs/multiagente.md) ────────────────────────────────
# POST /v1/multiagente/{plan,run} + GET /v1/multiagente/runs/{id}. ADITIVO: NO toca
# /v1/puppets/run — lo USA. Cada salto de la cadena es un run NORMAL por el executor de
# prod; lo único que agrega es el enlace por campo (runs.parent_run_id/hop_*) y la latencia
# medida. Los modos orquesta/oficina/abanico existen en el schema y se RECHAZAN con causa.
# ⚠️ NO se le pasa `_REPO_ROOT`: es un `Path(__file__).parents[3]` y bajo PyInstaller
# apunta AFUERA del bundle (main.py viaja en el PYZ). El router usa `resource_root()`
# — frozen-aware, `_MEIPASS` congelado / árbol en dev — que es donde viven de verdad
# `catalog/agents/*.config.json`. Medido: con `_REPO_ROOT`, TODO agent_ref resolvía a
# `aleph_no_resuelve` en el frozen y a nada en dev. Es el mismo `parents[N]` que dejó a
# la .app sin poder probar ningún MCP stdio (integración tanda B2).
from app.phase1.multiagente_router import build_multiagente_router
app.include_router(build_multiagente_router(get_conn=_phase1_get_conn))


# ── [Casa 2 · Fase 4 · 4.4.0 · serving=C] EL BACKEND SIRVE EL FRONTEND (design/) ──────────────
# Portado de product/app/serve.py: en el `.exe` el backend es el ÚNICO proceso (same-origin, sin
# CORS, sin serve.py). En DEV serve.py sigue andando — esto es ADITIVO. El proxy /v1 de serve.py
# NO se porta: acá el backend ES el origen → PATCH/PUT/DELETE los manejan los routers nativos.
# design/ sale de resource_root() (frozen-aware: _MEIPASS bajo el `.exe`, árbol en dev).
from fastapi import Request  # noqa: E402
from fastapi.responses import FileResponse, RedirectResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

_DESIGN_DIR = aleph_paths.resource_root() / "product" / "app" / "design"


@app.get("/", include_in_schema=False)
def _serve_home():
    """La homepage = el hub (Home.dc.html), igual que serve.py ('/' → Home)."""
    return RedirectResponse(url="/Home.dc.html", status_code=307)


@app.get("/Cuarto.dc.html", include_in_schema=False)
@app.get("/cuarto/cuarto.html", include_in_schema=False)
def _cuarto_canonical(request: Request):
    """CUTOVER (de serve.py): el Cuarto canónico es el de inspección dinámica (Pixi). Redirige a
    cuarto.pixi.html salvo ?builder=legacy, preservando el resto del query."""
    q = dict(request.query_params)
    if q.get("builder") == "legacy":
        f = _DESIGN_DIR / request.url.path.lstrip("/")
        return FileResponse(str(f)) if f.is_file() else Response(status_code=404)
    q.pop("builder", None)
    from urllib.parse import urlencode
    qs = urlencode(q)
    return RedirectResponse(url="/cuarto/cuarto.pixi.html" + (("?" + qs) if qs else ""),
                            status_code=307)


# ── [OAuth desktop · loopback] el botón abre el NAVEGADOR DEL SISTEMA, no la webview ──────
# Google BLOQUEA OAuth en webviews embebidas (disallowed_useragent, política de Google). En el
# `.app` el botón abre el navegador con la URL de OAuth de siempre; Supabase (flow PKCE)
# devuelve un código a ESTE loopback — el MISMO puerto que ya sirve la webview
# (window.location.origin). Acá: (a) una página callback que recibe sólo el authorization code
# PKCE y lo POSTea, (b) un buzón por-nonce que la webview pollea. Los tokens nunca cruzan este
# buzón: el canje usa el verifier que quedó en la webview iniciadora. NADA toca la web:
# allá el redirectTo es el origen web y este loopback nunca se usa. Middlewares gatean sólo /v1.
_desktop_oauth_box: dict = {}      # nonce -> (payload | None(pendiente), epoch_monotónico, state)
_DESKTOP_OAUTH_TTL = 300.0         # 5 min
_DESKTOP_OAUTH_CLAIMED = object()
import threading as _oauth_threading
_desktop_oauth_lock = _oauth_threading.RLock()


def _desktop_oauth_gc() -> None:
    import time as _t
    with _desktop_oauth_lock:
        ahora = _t.monotonic()
        for k, entry in list(_desktop_oauth_box.items()):
            if ahora - entry[1] <= _DESKTOP_OAUTH_TTL:
                continue
            _desktop_oauth_box.pop(k, None)


@app.get("/auth/desktop/callback", include_in_schema=False)
def _desktop_oauth_callback(request: Request):
    """Callback del navegador del sistema: deposita sólo código PKCE o error, nunca tokens."""
    _require_desktop_oauth_origin(request)
    html = (
        "<!doctype html><html lang=\"es\"><head><meta charset=\"utf-8\">"
        "<title>Aleph — ingreso</title><style>"
        "html,body{margin:0;height:100%;background:#0b0b12;color:#e7e0ff;"
        "font:15px/1.5 -apple-system,system-ui,sans-serif;display:grid;place-items:center;text-align:center}"
        ".c{max-width:440px;padding:24px}.h{font-size:18px;margin:0 0 8px}.d{color:#9a92c0;font-size:13px}"
        "</style></head><body><div class=\"c\">"
        "<div class=\"h\" id=\"h\">Confirmando tu ingreso…</div>"
        "<div class=\"d\" id=\"d\">Un segundo.</div></div><script>"
        "(function(){function P(s){return new URLSearchParams((s||'').replace(/^[#?]/,''));}"
        "var h=P(location.hash),q=P(location.search);"
        "var nonce=q.get('aleph_nonce')||h.get('aleph_nonce');"
        "var state=q.get('aleph_state')||h.get('aleph_state');"
        "var err=h.get('error')||q.get('error');var code=q.get('code')||h.get('code');"
        "try{history.replaceState(null,'','/auth/desktop/callback');}catch(e){}"
        "var pl={aleph_nonce:nonce,aleph_state:state};"
        "if(err){pl.error=err;pl.error_description=h.get('error_description')||q.get('error_description')||'';}"
        "else{pl.code=code;}"
        "try{fetch('/auth/desktop/log',{method:'POST',headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify({paso:'callback-recibido'})});}catch(e){}"
        "function done(ok){document.getElementById('h').textContent=ok?'\\u00a1Listo!':"
        "'No pudimos completar el ingreso';document.getElementById('d').textContent=ok?"
        "'Volv\\u00e9 a Aleph \\u2014 ya pod\\u00e9s cerrar esta pesta\\u00f1a.':"
        "(pl.error_description||pl.error||'Prob\\u00e1 de nuevo desde la app.');}"
        "if(!nonce||!state||(!pl.code&&!pl.error)){done(false);return;}"
        "fetch('/auth/desktop/session',{method:'POST',headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify(pl)}).then(function(r){done(r.ok&&!pl.error);}).catch(function(){done(false);});"
        "})();</script></body></html>"
    )
    return Response(content=html, media_type="text/html", headers={
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'",
    })


def _require_desktop_oauth_origin(request: Request, *, require_origin: bool = False) -> None:
    """The callback browser and webview must use the sidecar's exact loopback origin."""
    from urllib.parse import urlsplit as _urlsplit

    def authority(raw: str):
        try:
            parsed = _urlsplit(raw if "://" in raw else "http://" + raw)
            host = (parsed.hostname or "").lower().rstrip(".")
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except (TypeError, ValueError):
            return None, None
        if parsed.scheme != "http" or parsed.username or parsed.password or parsed.path not in ("", "/"):
            return None, None
        return (host, port) if host == "127.0.0.1" else (None, None)

    host, port = authority(request.headers.get("host") or "")
    if host is None:
        raise HTTPException(status_code=403, detail={"error": "local_origin_required"})
    origin = (request.headers.get("origin") or "").strip()
    if require_origin and not origin:
        raise HTTPException(status_code=403, detail={"error": "local_origin_required"})
    if origin:
        origin_host, origin_port = authority(origin)
        if origin_host != host or origin_port != port:
            raise HTTPException(status_code=403, detail={"error": "local_origin_required"})
    if port != int(os.environ.get("ALEPH_SIDECAR_PORT") or 0):
        raise HTTPException(status_code=403, detail={"error": "sidecar_origin_mismatch"})


def _require_desktop_oauth_claim_boundary(request: Request, launch_cap: str = "") -> None:
    """Bind session start/claim to this Tauri launch and its exact loopback port."""
    import hmac as _hmac
    _require_desktop_oauth_origin(request)
    expected = _current_launch_cap()
    if not expected:
        raise HTTPException(status_code=503, detail={"error": "local_auth_unavailable"})
    if not launch_cap or not _hmac.compare_digest(launch_cap.strip(), expected):
        raise HTTPException(status_code=403, detail={"error": "launch_cap_required"})


@app.post("/auth/desktop/start", include_in_schema=False)
async def _desktop_oauth_start(request: Request,
                               launch_cap: Optional[str] = Header(default=None, alias="X-Aleph-Launch")):
    """Register the one pending nonce from the trusted desktop main frame."""
    import re as _re
    import time as _t
    _require_desktop_oauth_claim_boundary(request, launch_cap or "")
    try:
        body = await request.json()
    except Exception:
        return Response(status_code=400)
    if not isinstance(body, dict):
        return Response(status_code=400)
    nonce = str((body or {}).get("aleph_nonce") or "")
    state = str((body or {}).get("aleph_state") or "")
    if not _re.fullmatch(r"[A-Za-z0-9._:-]{16,128}", nonce) or \
       not _re.fullmatch(r"[A-Za-z0-9._:-]{16,128}", state):
        return Response(status_code=400)
    with _desktop_oauth_lock:
        _desktop_oauth_gc()
        if nonce in _desktop_oauth_box:
            return Response(status_code=409)
        _desktop_oauth_box[nonce] = (None, _t.monotonic(), state)
    return Response(status_code=204)


@app.post("/auth/desktop/session", include_in_schema=False)
async def _desktop_oauth_deposit(request: Request):
    import hmac as _hmac
    import time as _t
    _require_desktop_oauth_origin(request, require_origin=True)
    try:
        body = await request.json()
    except Exception:
        return Response(status_code=400)
    if not isinstance(body, dict):
        return Response(status_code=400)
    nonce = str(body.get("aleph_nonce") or "")
    state = str(body.get("aleph_state") or "")
    if any(k in body for k in ("access_token", "refresh_token", "token_type", "expires_in")):
        return Response(status_code=400)
    code = body.get("code")
    error = body.get("error")
    description = body.get("error_description")
    if code and error:
        return Response(status_code=400)
    if code:
        if not isinstance(code, str) or not (1 <= len(code) <= 4096):
            return Response(status_code=400)
        payload = {"code": code}
    elif error:
        if not isinstance(error, str) or not (1 <= len(error) <= 200):
            return Response(status_code=400)
        if description is not None and (not isinstance(description, str) or len(description) > 1000):
            return Response(status_code=400)
        payload = {"error": error, "error_description": description or ""}
    else:
        return Response(status_code=400)
    with _desktop_oauth_lock:
        _desktop_oauth_gc()
        current = _desktop_oauth_box.get(nonce)
        if current is None:
            return Response(status_code=404)
        if not _hmac.compare_digest(state, current[2]):
            return Response(status_code=403)
        if current[0] is not None:
            return Response(status_code=409)  # first callback wins, including concurrent posts
        _desktop_oauth_box[nonce] = (payload, _t.monotonic(), current[2])
    return Response(status_code=204)


@app.get("/auth/desktop/session", include_in_schema=False)
def _desktop_oauth_claim(request: Request, aleph_nonce: str = "",
                         launch_cap: Optional[str] = Header(default=None, alias="X-Aleph-Launch")):
    from fastapi.responses import JSONResponse
    _require_desktop_oauth_claim_boundary(request, launch_cap or "")
    with _desktop_oauth_lock:
        _desktop_oauth_gc()
        entry = _desktop_oauth_box.get(aleph_nonce) if aleph_nonce else None
        if not entry or entry[0] is None or entry[0] is _DESKTOP_OAUTH_CLAIMED:
            return Response(status_code=204)   # pending or already claimed
        _desktop_oauth_box[aleph_nonce] = (_DESKTOP_OAUTH_CLAIMED, entry[1], entry[2])
        return JSONResponse(content=entry[0])  # atomic, one-shot claim


@app.post("/auth/desktop/log", include_in_schema=False)
async def _desktop_oauth_log(request: Request):
    """Canal de diagnóstico event-only; nunca persiste URLs, nonces, errores ni tokens."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    allowed = {
        "inicio", "signInWithOAuth:error", "signInWithOAuth:sin-url",
        "signInWithOAuth:ok", "abrirNavegador:ok", "abrirNavegador:error",
        "poll:inicio", "poll:ok", "poll:error", "setSession:error",
        "setSession:ok", "navegando", "FALLO", "callback-recibido",
    }
    paso = body.get("paso") if isinstance(body, dict) else None
    if paso not in allowed:
        return Response(status_code=204)
    print(f"[oauth-diag] {paso}", flush=True)
    try:
        import time as _t
        p = aleph_paths.user_data_dir() / "oauth-diag.log"
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(p, flags, 0o600)
        try:
            os.fchmod(fd, 0o600)
            os.write(fd, f"{_t.strftime('%H:%M:%S')} {paso}\n".encode("utf-8"))
        finally:
            os.close(fd)
    except Exception:
        pass
    return Response(status_code=204)


class _FrontendStatic(StaticFiles):
    """serving=C: el backend sirve design/ como catch-all. PERO el catch-all NO debe
    shadowear los 404 de la API. Un método ≠ GET/HEAD que llega hasta acá es un path
    SIN router (los routers reales matchean antes por path+método) → merece el **404
    nativo** de "recurso inexistente", no el **405** que StaticFiles da por método.
    Sin esto, un POST a `/espacios/*` (routers retirados en Fase 4) devolvía 405 en vez
    de 404 (rompía test_espacios ×3). Los GET a archivos inexistentes ya dan 404."""

    async def get_response(self, path: str, scope):  # type: ignore[override]
        if scope["method"] not in ("GET", "HEAD"):
            return Response(status_code=404)
        resp = await super().get_response(path, scope)
        # ── `no-cache` NO ES «no cachees»: ES «revalidá ANTES de usar» ───────────────────
        # Servíamos `ETag` y `Last-Modified` sin `Cache-Control`, así que el navegador
        # cacheaba por HEURÍSTICA: se guardaba el archivo y lo volvía a servir SIN
        # preguntar. MEDIDO el 2026-08-12, dos veces en la misma sesión: se arregla algo en
        # `sala-v2/`, la pantalla sigue mostrando lo viejo, y se pierden vueltas
        # persiguiendo un fantasma —el bug ya estaba arreglado en disco—. El síntoma es
        # cruel porque parece que el arreglo no funciona.
        #
        # No cuesta ancho de banda: el `ETag` sigue ahí, así que lo normal es un 304 vacío
        # contra loopback. Lo que se compra es que la pantalla no pueda mentir sobre qué
        # versión está corriendo.
        #
        # Va para TODO el frontend, no sólo en dev: después de actualizar la `.app`, un
        # usuario con el bundle viejo en caché tiene exactamente el mismo problema y ni
        # siquiera sabe que existe.
        resp.headers.setdefault("Cache-Control", "no-cache")
        return resp


# [T6 §10 · LEY MINIMALISTA] docs/guia servido como ESTÁTICO, ANTES del catch-all.
# §10 saca la explicación larga de la UI del Cuarto y la deja en docs/guia; el [?] de la
# pantalla (cuarto.ayuda.js) lee ESE MD por HTTP. El Guía ya los inyecta como contexto
# (cuarto_guide.py · poder SABE) — es la MISMA fuente, ahora también legible por el cliente.
# Va montado en su propio path (no dentro de design/) porque el frozen ya los empaqueta en
# resource_root()/docs/guia (deploy/fase4/aleph_sidecar.spec · _DATA_DIRS) y porque el Guía
# los lee de ahí: una sola copia, dos consumidores.
_GUIA_DIR = aleph_paths.resource_root() / "docs" / "guia"
if _GUIA_DIR.is_dir():
    app.mount("/docs/guia", StaticFiles(directory=str(_GUIA_DIR)), name="guia")
    print(f"[serving] docs/guia montado desde {_GUIA_DIR}", flush=True)
else:
    # §4h · fallo VISIBLE: sin esto el [?] del Cuarto abre un popover que dice "no pude leer
    # la guía" y el usuario no sabe por qué. Que el log lo diga en el arranque.
    print(f"[serving] docs/guia AUSENTE en {_GUIA_DIR} — el [?] del Cuarto va a fallar visible", flush=True)

# StaticFiles AL FINAL (catch-all): /health, /catalog, /v1 (arriba) matchean primero; el resto =
# design/ (.dc.html + vendor + fonts). Sólo si el dir existe (en el `.exe` = datas de Capa 0).
if _DESIGN_DIR.is_dir():
    app.mount("/", _FrontendStatic(directory=str(_DESIGN_DIR), html=True), name="frontend")
    print(f"[serving] frontend montado desde {_DESIGN_DIR}", flush=True)
else:
    print(f"[serving] design/ AUSENTE en {_DESIGN_DIR} — frontend NO montado (gap de datas Capa 0)", flush=True)
