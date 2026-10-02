"""
espacios.py — EL ESPACIO CONECTADO (V2-2 núcleo, PRODUCT-V2-DESIGN §4).

Un ESPACIO es la sala durable donde el agente (Pim) vive entre visitas. Esta
pieza es ADITIVA sobre lo probado:
  - EspaciosStore: registro JSONL append-only + workdir por espacio en
    product/backend/data/espacios/{id}/ con events.jsonl, state.json y
    mensajes.jsonl.
  - SessionManager: park/resume de la Sesión VIVA (platform/assembler/session.py).
    La fábrica de sesiones es INYECTABLE — en producción crea una Session real con
    carril local; en TESTS se stubbea para que la inferencia NUNCA corra (el test
    no espera 80s de qwen).
  - Router FastAPI: POST /espacios, GET /espacios/{id},
    POST /espacios/{id}/mensajes, GET /espacios/{id}/stream (SSE esqueleto real),
    POST /espacios/{id}/aprobaciones/{gate_id}.

Nada de nombres de producto/dominio hardcodeados (D3). El arrancador (template del
catálogo) se consume como DATA SOURCE: su config.json se copia a la config del
espacio, editable.
"""

from __future__ import annotations

import importlib.util
import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel


# ── Rutas base ────────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[3]  # product/backend/app -> repo root
def _espacios_default() -> Path:
    """El MISMO dir que usa `main.py`. Antes esto era `_REPO_ROOT/product/backend/data/
    espacios` y `main.py` usaba `aleph_paths.espacios_dir()`: el MISMO event-log terminaba
    en DOS lugares según quién lo abriera —`main.py` en el dir del usuario,
    `run_handler.py` en el árbol/bundle—. Un event-log partido no es un log: es dos
    historias incompletas de la misma sesión.
    """
    try:
        import aleph_paths
        return aleph_paths.espacios_dir()
    except Exception:                    # noqa: BLE001 — dev sin platform en el path
        return _REPO_ROOT / "product" / "backend" / "data" / "espacios"


DEFAULT_ESPACIOS_DIR = _espacios_default()
#: La ruta huérfana, para que la reconciliación de cortesía sepa dónde mirar.
_ESPACIOS_DIR_VIEJA = _REPO_ROOT / "product" / "backend" / "data" / "espacios"
_SESSION_PATH = _REPO_ROOT / "platform" / "assembler" / "session.py"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── EspaciosStore (JSONL + workdir por espacio) ───────────────────────────────

class EspaciosStore:
    """
    Registro de espacios. Un índice JSONL (append-only) más un directorio
    durable por espacio:

        {root}/espacios.jsonl                 — índice (1 línea por espacio)
        {root}/{id}/state.json                — estado del espacio (config + meta)
        {root}/{id}/events.jsonl              — hilo de eventos del runtime
        {root}/{id}/mensajes.jsonl            — cola de mensajes encolados
    """

    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root else DEFAULT_ESPACIOS_DIR
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "espacios.jsonl"

    # ── helpers de rutas ──────────────────────────────────────────────────────

    def espacio_dir(self, espacio_id: str) -> Path:
        return self.root / espacio_id

    def state_path(self, espacio_id: str) -> Path:
        return self.espacio_dir(espacio_id) / "state.json"

    def events_path(self, espacio_id: str) -> Path:
        return self.espacio_dir(espacio_id) / "events.jsonl"

    def mensajes_path(self, espacio_id: str) -> Path:
        return self.espacio_dir(espacio_id) / "mensajes.jsonl"

    # ── creación ──────────────────────────────────────────────────────────────

    def create(
        self,
        nombre: str,
        nicho: str,
        config: dict[str, Any],
        *,
        arrancador_id: Optional[str] = None,
    ) -> dict:
        """
        Crea un espacio durable. `config` ya viene resuelta (el endpoint copió la
        del arrancador si correspondía). Persiste índice + state.json y prepara el
        workdir con events.jsonl/mensajes.jsonl vacíos.
        """
        espacio_id = str(uuid.uuid4())
        now = _now_iso()
        record = {
            "id": espacio_id,
            "nombre": nombre,
            "nicho": nicho,
            "arrancador_id": arrancador_id,
            "created_at": now,
            "updated_at": now,
        }

        edir = self.espacio_dir(espacio_id)
        edir.mkdir(parents=True, exist_ok=True)

        state = {
            **record,
            "config": config,
            "estado": "vacio",  # vacio | vivo | esperando-ok | descansa
            "mensajes_encolados": 0,
        }
        self.state_path(espacio_id).write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # tocar los archivos del hilo para que el stream tenga algo que leer
        self.events_path(espacio_id).touch()
        self.mensajes_path(espacio_id).touch()

        # índice JSONL (append-only)
        with self.index_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        return state

    # ── lectura ───────────────────────────────────────────────────────────────

    def get(self, espacio_id: str) -> Optional[dict]:
        """Estado completo del espacio (incluye config) desde state.json."""
        sp = self.state_path(espacio_id)
        if not sp.exists():
            return None
        try:
            return json.loads(sp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def exists(self, espacio_id: str) -> bool:
        return self.state_path(espacio_id).exists()

    def update_state(self, espacio_id: str, **fields: Any) -> Optional[dict]:
        state = self.get(espacio_id)
        if state is None:
            return None
        state.update(fields)
        state["updated_at"] = _now_iso()
        self.state_path(espacio_id).write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return state

    # ── mensajes (cola durable) ───────────────────────────────────────────────

    def enqueue_mensaje(self, espacio_id: str, texto: str) -> dict:
        msg = {
            "id": uuid.uuid4().hex[:12],
            "ts": time.time(),
            "texto": texto,
        }
        with self.mensajes_path(espacio_id).open("a", encoding="utf-8") as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
        state = self.get(espacio_id)
        n = (state.get("mensajes_encolados", 0) if state else 0) + 1
        self.update_state(espacio_id, mensajes_encolados=n)
        return msg

    def read_mensajes(self, espacio_id: str) -> list[dict]:
        mp = self.mensajes_path(espacio_id)
        if not mp.exists():
            return []
        out: list[dict] = []
        for line in mp.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    # ── eventos (hilo del runtime; persistir-antes-de-emitir lo hace Session) ──

    def append_event(self, espacio_id: str, evt: dict) -> None:
        """
        Appendea un evento al events.jsonl del espacio. La Sesión viva ya persiste
        por su cuenta cuando corre con su propio events_path; este helper existe
        para los eventos del backend (mensaje encolado, etc.) y para los fixtures.
        """
        with self.events_path(espacio_id).open("a", encoding="utf-8") as f:
            f.write(json.dumps(evt, ensure_ascii=False) + "\n")

    def read_events(self, espacio_id: str) -> list[dict]:
        ep = self.events_path(espacio_id)
        if not ep.exists():
            return []
        out: list[dict] = []
        for line in ep.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out


# ── Carga perezosa de la Sesión viva (platform/assembler/session.py) ──────────

_session_module = None


def _load_session_module():
    global _session_module
    if _session_module is None:
        import aleph_paths
        _session_module = aleph_paths.load_module_by_path("puppet_session", _SESSION_PATH)
    return _session_module


# Tipo de la fábrica: (config, events_path) -> objeto con .send/.approve/.reject/.close
SessionFactory = Callable[[dict, Path], Any]


def _default_session_factory(config: dict, events_path: Path) -> Any:
    """
    Fábrica de producción: crea una Session real (carril local del config) cuyo
    events.jsonl ES el del espacio. La inferencia corre en un worker thread del
    SessionManager — el endpoint solo lee la cola.
    """
    session_mod = _load_session_module()
    workdir = events_path.parent
    return session_mod.Session(
        config,
        repo_root=_REPO_ROOT,
        workdir=workdir,
        on_event=None,
    )


# ── SessionManager (park/resume de las sesiones vivas) ────────────────────────

class SessionManager:
    """
    Mantiene las sesiones vivas por espacio. park() las saca de memoria (cierra el
    belt); resume()/get_or_create() las trae de vuelta. La fábrica es inyectable:
    en TESTS se pasa una que devuelve un stub sin LLM.
    """

    def __init__(self, factory: Optional[SessionFactory] = None):
        self._factory = factory or _default_session_factory
        self._sessions: dict[str, Any] = {}
        self._lock = threading.Lock()

    def has(self, espacio_id: str) -> bool:
        with self._lock:
            return espacio_id in self._sessions

    def get(self, espacio_id: str) -> Optional[Any]:
        with self._lock:
            return self._sessions.get(espacio_id)

    def get_or_create(self, espacio_id: str, config: dict, events_path: Path) -> Any:
        with self._lock:
            sess = self._sessions.get(espacio_id)
            if sess is None:
                sess = self._factory(config, events_path)
                self._sessions[espacio_id] = sess
            return sess

    def park(self, espacio_id: str) -> bool:
        """Saca la sesión de memoria y cierra su belt. Idempotente."""
        with self._lock:
            sess = self._sessions.pop(espacio_id, None)
        if sess is None:
            return False
        try:
            sess.close()
        except Exception:
            pass
        return True

    def park_all(self) -> None:
        with self._lock:
            ids = list(self._sessions.keys())
        for eid in ids:
            self.park(eid)


# ── Respuestas / requests del router ──────────────────────────────────────────

class EspacioCreateRequest(BaseModel):
    nombre: str
    nicho: str
    # arrancador_id: si viene, copia la config del template del catálogo (data source).
    arrancador_id: Optional[str] = None
    # config opcional explícita (override / espacio armado de cero pieza por pieza).
    config: Optional[dict[str, Any]] = None


class EspacioResponse(BaseModel):
    id: str
    nombre: str
    nicho: str
    arrancador_id: Optional[str] = None
    estado: str
    config: dict[str, Any]
    mensajes_encolados: int
    created_at: str
    updated_at: str


class MensajeRequest(BaseModel):
    texto: str


class MensajeEncoladoResponse(BaseModel):
    espacio_id: str
    mensaje_id: str
    encolado: bool
    sesion_viva: bool
    estado: str


class AprobacionRequest(BaseModel):
    # 'aprueba' True = OK del usuario; False = rechazo. razon es opcional (UX).
    aprueba: bool = True
    razon: str = ""


class AprobacionResponse(BaseModel):
    espacio_id: str
    gate_id: str
    resuelto: bool
    aprobado: bool
    detalle: str


# ── Builder del router ────────────────────────────────────────────────────────

def _state_to_response(state: dict) -> dict:
    return {
        "id": state["id"],
        "nombre": state["nombre"],
        "nicho": state["nicho"],
        "arrancador_id": state.get("arrancador_id"),
        "estado": state.get("estado", "vacio"),
        "config": state.get("config", {}),
        "mensajes_encolados": state.get("mensajes_encolados", 0),
        "created_at": state["created_at"],
        "updated_at": state["updated_at"],
    }


def _sse_pack(event_id: int, evt: dict, *, event_name: Optional[str] = None) -> str:
    """Empaqueta un dict como un bloque de evento SSE (id + event + data)."""
    name = event_name or evt.get("type", "message")
    payload = json.dumps(evt, ensure_ascii=False)
    return f"id: {event_id}\nevent: {name}\ndata: {payload}\n\n"


def build_espacios_router(
    *,
    get_store: Callable[[], EspaciosStore],
    get_manager: Callable[[], SessionManager],
    load_arrancador_config: Callable[[str, str], Optional[dict]],
    heartbeat_s: float = 15.0,
    stream_idle_limit: int = 0,
) -> APIRouter:
    """
    Construye el router de espacios. Las dependencias se inyectan (store, manager,
    cargador del arrancador) para que los tests usen tmp_path y stubs sin LLM.

    load_arrancador_config(nicho, arrancador_id) -> dict | None
        Devuelve la config.json del template del catálogo a copiar, o None si no
        existe. El catálogo es el DATA SOURCE — no se hardcodea ninguna config.

    stream_idle_limit: nº máximo de ciclos de heartbeat sin eventos nuevos antes de
        cerrar el stream (0 = sin tope, para producción; los tests pasan un tope
        para que el generador termine sin LLM).
    """
    router = APIRouter(prefix="/espacios", tags=["espacios"])

    # ── POST /espacios ────────────────────────────────────────────────────────
    @router.post("", status_code=201, response_model=EspacioResponse)
    def crear_espacio(body: EspacioCreateRequest):
        """
        Crea un espacio. Si viene `arrancador_id`, copia la config del template del
        catálogo (el catálogo como data source); `config` explícita la sobreescribe
        (espacio armado de cero). Sin ninguno, arranca con config mínima vacía.
        """
        config: dict[str, Any] = {}

        if body.arrancador_id:
            arr = load_arrancador_config(body.nicho, body.arrancador_id)
            if arr is None:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        f"Arrancador '{body.arrancador_id}' no encontrado en el "
                        f"nicho '{body.nicho}'."
                    ),
                )
            config = dict(arr)

        if body.config is not None:
            # override pieza por pieza sobre lo del arrancador (o desde cero)
            config = {**config, **body.config}

        store = get_store()
        state = store.create(
            body.nombre, body.nicho, config, arrancador_id=body.arrancador_id
        )
        return _state_to_response(state)

    # ── GET /espacios/{id} ────────────────────────────────────────────────────
    @router.get("/{espacio_id}", response_model=EspacioResponse)
    def obtener_espacio(espacio_id: str):
        store = get_store()
        state = store.get(espacio_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Espacio '{espacio_id}' no encontrado.")
        return _state_to_response(state)

    # ── POST /espacios/{id}/mensajes ──────────────────────────────────────────
    @router.post("/{espacio_id}/mensajes", response_model=MensajeEncoladoResponse)
    def encolar_mensaje(espacio_id: str, body: MensajeRequest):
        """
        Encola el mensaje en la cola durable del espacio. Si no hay sesión viva, la
        crea vía session.py (carril local del config). En TESTS la fábrica de
        sesiones está stubbeada: NO corre inferencia (el test no espera 80s de
        qwen). El loop real de tool-use corre en el worker thread del SessionManager.
        """
        texto = (body.texto or "").strip()
        if not texto:
            raise HTTPException(status_code=422, detail={"errors": ["el mensaje está vacío"]})

        store = get_store()
        state = store.get(espacio_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Espacio '{espacio_id}' no encontrado.")

        msg = store.enqueue_mensaje(espacio_id, texto)
        # evento del hilo: el mensaje entró (persistido en el events.jsonl del espacio)
        store.append_event(espacio_id, {
            "ts": time.time(),
            "type": "mensaje_encolado",
            "espacio_id": espacio_id,
            "mensaje_id": msg["id"],
        })

        manager = get_manager()
        sesion_viva = manager.has(espacio_id)
        if not sesion_viva:
            # crear (o resumir) la sesión viva — la fábrica decide si arranca un belt
            # real (producción) o un stub (tests). NO bloqueamos en inferencia acá.
            manager.get_or_create(espacio_id, state.get("config", {}), store.events_path(espacio_id))
            sesion_viva = True

        nuevo_estado = "vivo"
        store.update_state(espacio_id, estado=nuevo_estado)

        return {
            "espacio_id": espacio_id,
            "mensaje_id": msg["id"],
            "encolado": True,
            "sesion_viva": sesion_viva,
            "estado": nuevo_estado,
        }

    # ── GET /espacios/{id}/stream ─────────────────────────────────────────────
    @router.get("/{espacio_id}/stream")
    def stream_espacio(
        request: Request,
        espacio_id: str,
        last_event_id: Optional[int] = Query(default=None, alias="lastEventId"),
    ):
        """
        SSE esqueleto real: sirve los eventos del events.jsonl del espacio como
        text/event-stream, con id incremental por evento + heartbeat. Soporta
        Last-Event-ID (header estándar o ?lastEventId=) para replay: arranca en el
        siguiente evento. NO replay fingido — cada evento nace del events.jsonl real
        (que la Sesión persiste antes de emitir).
        """
        store = get_store()
        if not store.exists(espacio_id):
            raise HTTPException(status_code=404, detail=f"Espacio '{espacio_id}' no encontrado.")

        # Last-Event-ID: header del navegador (reconexión) o query param.
        header_leid = request.headers.get("last-event-id")
        start_after = -1
        if last_event_id is not None:
            start_after = int(last_event_id)
        elif header_leid is not None:
            try:
                start_after = int(header_leid)
            except ValueError:
                start_after = -1

        events_path = store.events_path(espacio_id)

        def event_gen() -> Iterator[str]:
            # 'cursor' = índice (0-based) del último evento servido. start_after es
            # el ÚLTIMO id ya visto por el cliente; servimos desde el siguiente.
            cursor = start_after
            idle = 0
            # estado inicial del espacio como primer evento de orientación
            opening = {
                "ts": time.time(),
                "type": "stream_open",
                "espacio_id": espacio_id,
                "from_id": cursor + 1,
            }
            yield _sse_pack(cursor + 1 if cursor >= 0 else 0, opening, event_name="stream_open")

            while True:
                evts = store.read_events(espacio_id)
                served_any = False
                for idx in range(cursor + 1, len(evts)):
                    yield _sse_pack(idx, evts[idx])
                    cursor = idx
                    served_any = True

                if served_any:
                    idle = 0
                else:
                    idle += 1
                    # heartbeat (comentario SSE — no dispara onmessage en el cliente)
                    yield f": heartbeat {int(time.time())}\n\n"
                    if stream_idle_limit and idle >= stream_idle_limit:
                        # cierre honesto: sin más eventos y alcanzamos el tope.
                        yield _sse_pack(cursor + 1, {
                            "ts": time.time(),
                            "type": "stream_idle_close",
                            "espacio_id": espacio_id,
                        }, event_name="stream_idle_close")
                        return

                time.sleep(heartbeat_s)

        return StreamingResponse(
            event_gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # ── POST /espacios/{id}/aprobaciones/{gate_id} ────────────────────────────
    @router.post("/{espacio_id}/aprobaciones/{gate_id}", response_model=AprobacionResponse)
    def resolver_aprobacion(espacio_id: str, gate_id: str, body: AprobacionRequest):
        """
        Conecta el OK/NO del usuario al .approve()/.reject() de la Sesión viva (el
        contrato de 0014). Si no hay sesión viva, o no hay gate pendiente, lo dice
        honestamente (no inventa una aprobación). El gate_id se registra para
        trazabilidad y se persiste como evento del hilo.
        """
        store = get_store()
        if not store.exists(espacio_id):
            raise HTTPException(status_code=404, detail=f"Espacio '{espacio_id}' no encontrado.")

        manager = get_manager()
        sess = manager.get(espacio_id)
        if sess is None:
            raise HTTPException(
                status_code=409,
                detail="No hay sesión viva en este espacio; no hay nada que aprobar.",
            )

        pending = getattr(sess, "pending_approval", None)
        if pending is None:
            raise HTTPException(
                status_code=409,
                detail="No hay un gate esperando OK en este momento.",
            )

        if body.aprueba:
            sess.approve(reason=body.razon)
            detalle = "OK recibido — el agente continúa."
        else:
            sess.reject(reason=body.razon)
            detalle = "Rechazado — el agente NO ejecuta la acción."

        # evento del hilo (persistido en el events.jsonl del espacio)
        store.append_event(espacio_id, {
            "ts": time.time(),
            "type": "gate_resolved_by_user",
            "espacio_id": espacio_id,
            "gate_id": gate_id,
            "aprobado": bool(body.aprueba),
        })
        store.update_state(espacio_id, estado="vivo")

        return {
            "espacio_id": espacio_id,
            "gate_id": gate_id,
            "resuelto": True,
            "aprobado": bool(body.aprueba),
            "detalle": detalle,
        }

    return router
