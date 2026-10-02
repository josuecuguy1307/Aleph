"""
mesa_runner.py — el RUNNER de una construcción (lado producto: costura motor↔Mesa).

Envuelve el Motor B (run_internal_loop) en una máquina de estados RETOMABLE y proyecta su
stream sobre las 6 estaciones, cableando las dos inversiones de la ola:

  • RESULTADOS-PRIMERO: cada evento del motor se traduce (con el _translate del forge_router,
    cero dialecto nuevo para lo del motor) y se escribe al SPACE (events.jsonl → el stream
    existente /v1/spaces/{id}/stream da replay + reconexión gratis). En cada transición de
    estación se escribe un SNAPSHOT compacto → el borrador retomable.
  • PREGUNTAR-TEMPRANO: antes de lanzar el motor se evalúan las preguntas PRE-MOTOR (falta URL,
    forma/credencial); al terminar un intento se clasifica el desenlace (MFA, degradado, cero
    tools) → si es askable, PAUSA con la pregunta preservando el inventario.

NO reconstruye el motor: run_internal_loop, provider_and_auth y _translate se reusan tal cual.
El runner corre cada intento en un thread daemon FINITO; una pausa = sin thread + pregunta en
el snapshot (sobrevive reinicios del server). Retomar re-lanza el motor sembrando el inventario.

Vocabulario: construcción, jamás forja.
"""
from __future__ import annotations

import sys
import threading
import uuid
from pathlib import Path
from typing import Any, Optional

_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[4]
_PLATFORM = _REPO_ROOT / "platform"
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection import contracts as C  # noqa: E402
from inspection.bridge import SpaceEmitter  # noqa: E402
from inspection.loop.budget import Budget  # noqa: E402
from inspection.loop.engine import run_internal_loop  # noqa: E402
from inspection.mesa import almacen, preguntas, proyeccion  # noqa: E402
from inspection.mesa.modelos import Inventario, Snapshot, ahora  # noqa: E402

from app.phase1.forge_router import (  # noqa: E402
    ForgeRequest, _translate, provider_and_auth, resolve_forma, _slug, _fingerprint)


def _principal_de(user_id: Optional[str], construccion_id: str) -> C.Principal:
    """Autenticado → Principal(user_id) estable; anónimo → anon_id derivado del id de la
    construcción (ESTABLE por construcción → el namespace del vault sobrevive pausas/retomas,
    a diferencia del anon efímero por-request del forge)."""
    if user_id:
        return C.Principal(user_id=user_id)
    return C.Principal(anon_id=f"construccion-{construccion_id}")


class RunnerConstruccion:
    """Una construcción viva: su snapshot (fuente de verdad, persistida), el emitter al space,
    y el thread del intento actual. Thread-safe: un lock serializa mutaciones del snapshot."""

    def __init__(self, snap: Snapshot, principal: C.Principal, *, user_id: Optional[str] = None):
        self.snap = snap
        self.principal = principal
        self.user_id = user_id
        self._cred: Optional[str] = None    # SOLO en memoria — jamás al snapshot
        self._emitter = SpaceEmitter(snap.space_id, owner_id=user_id,
                                     public=user_id is None, claim=True)
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()

    # ── emisión al space (el stream de la construcción) ─────────────────────────
    def _emit(self, tipo: str, **payload) -> None:
        self._emitter.emit(tipo, construccion_id=self.snap.construccion_id, **payload)

    def _persistir(self) -> None:
        self.snap.tocada_en = ahora()
        almacen.guardar(self.principal, self.snap)

    # ── credencial (al vault + memoria; nunca al snapshot) ──────────────────────
    def set_credencial(self, cred: Optional[str], *, slug: Optional[str] = None) -> None:
        if not cred:
            return
        self._cred = cred
        sl = slug or self._slug_de()
        try:
            store = C.FernetCredentialStore(self.principal, sl, root=C.SYNTH_BELTS_DIR)
            store.put("API_KEY", cred)
            self.snap.pedido["cred_ref"] = (
                f"{C.credential_namespace(self.principal)}/{sl}#API_KEY")
        except Exception:
            # el vault podría no estar disponible en algún entorno de test; la memoria alcanza
            # para el intento en curso (el snapshot NO guarda la cred).
            self.snap.pedido["cred_ref"] = self.snap.pedido.get("cred_ref")

    def _leer_cred_vault(self) -> Optional[str]:
        """Recupera la credencial del vault por su cred_ref (para retomar tras reinicio)."""
        if self._cred:
            return self._cred
        ref = (self.snap.pedido or {}).get("cred_ref") or ""
        if "#" not in ref:
            return None
        try:
            store = C.FernetCredentialStore(self.principal, self._slug_de(), root=C.SYNTH_BELTS_DIR)
            return store.get("API_KEY")
        except Exception:
            return None

    def _slug_de(self) -> str:
        p = self.snap.pedido or {}
        host = (p.get("url") or p.get("service") or self.snap.service or "servicio")
        import re as _re
        host = _re.sub(r"^https?://", "", host).split("/")[0]
        return p.get("slug") or f"construccion-{_slug(host)}"

    # ── el pedido como ForgeRequest (para reusar provider_and_auth) ─────────────
    def _forge_request(self, *, seed_forma: Optional[str] = None) -> ForgeRequest:
        p = dict(self.snap.pedido or {})
        forma = seed_forma or p.get("forma") or "token"
        data: dict[str, Any] = {
            "url": p.get("url") or "",
            "cred": self._cred,
            "forma": forma,
            "puppet_id": p.get("puppet_id"),
            "local_target": bool(p.get("local_target")),
            "api_shape_hint": p.get("api_shape_hint") or "",
            "slug": self._slug_de(),
        }
        for k in ("auth_in", "auth_param", "auth_header", "auth_template", "validate_path",
                  "session_key", "login_url", "login_path", "login_credentials",
                  "login_token_where", "login_token_key", "login_inject_where",
                  "login_inject_name", "login_inject_template", "login_body_format"):
            if p.get(k) is not None:
                data[k] = p[k]
        return ForgeRequest(**data)

    # ── proyección de un evento del motor sobre las estaciones + inventario ─────
    def _on_engine_event(self, ev: dict) -> None:
        """Corre en el thread del motor. Traduce el evento crudo al contrato, lo escribe al
        space, actualiza inventario/estación y snapshotea en cada transición."""
        target = (self.snap.pedido or {}).get("url") or ""
        puppet_id = (self.snap.pedido or {}).get("puppet_id")
        for cev in _translate(ev, target_url=target, puppet_id=puppet_id):
            tipo = cev.get("type")
            self._emit(tipo, **{k: v for k, v in cev.items() if k != "type"})
            # La mutación del snapshot (inventario + estación) corre bajo el MISMO RLock que usan
            # los lectores HTTP (GET snapshot) y los otros mutadores (responder/retomar). Sin esto,
            # el thread del motor appendea a las listas del inventario mientras un GET hace asdict()
            # → "list changed size during iteration". RLock reentrante: _persistir() re-adquiere ok.
            with self._lock:
                self._absorber(cev)
                nueva = proyeccion.avanzar(self.snap.estacion, tipo)
                if nueva and nueva != self.snap.estacion:
                    previa = self.snap.estacion
                    self.snap.estacion = nueva
                    self._emit("estacion.cambio", estacion=nueva, previa=previa,
                               n=proyeccion.indice(nueva))
                    self._persistir()

    def _absorber(self, cev: dict) -> None:
        """Acumula el inventario aprovechable desde el evento del contrato (borrador)."""
        inv = self.snap.inventario
        t = cev.get("type")
        if t == "sesion.ok":
            inv.identidad.setdefault("host", (self.snap.pedido or {}).get("url"))
            inv.identidad["auth_form"] = cev.get("auth_form")
        elif t == "observando":
            for ep in cev.get("new_confirmed") or []:
                if ep not in inv.superficie:
                    inv.superficie.append(ep)
        elif t == "tool.propuesta":
            inv.tools_propuestas.append({
                "name": cev.get("nombre"), "endpoint": cev.get("endpoint"),
                "method": cev.get("method"), "kind": cev.get("kind"),
                "params": cev.get("params") or {}, "description": cev.get("description")})
        elif t == "tool.validada":
            inv.tools_validadas.append({
                "name": cev.get("nombre"), "verified_by": cev.get("verified_by"),
                "status": cev.get("status")})
        elif t == "tool.descartada":
            inv.tools_descartadas.append({
                "name": cev.get("nombre"), "motivo": cev.get("motivo"),
                "clase": cev.get("clase"), "move": cev.get("move")})
        elif t == "mcp.forjado":
            inv.belt_ref = cev.get("belt_ref")
            inv.puppet_id = cev.get("puppet_id")
            inv.identidad["server"] = cev.get("server")

    # ── el intento del motor (cuerpo del thread) ────────────────────────────────
    def _correr_intento(self, *, seed_candidates: tuple = (), seed_forma: Optional[str] = None) -> None:
        p = dict(self.snap.pedido or {})
        try:
            forma = resolve_forma(seed_forma or p.get("forma") or "token")
        except Exception:
            forma = "token"
        slug = self._slug_de()
        principal = self.principal
        body = self._forge_request(seed_forma=forma)
        budget = Budget(max_rounds=int(p.get("max_rounds", 3)),
                        max_live_calls=int(p.get("max_calls", 30)),
                        max_synth_tokens=int(p.get("max_tokens", 300_000)))
        try:
            provider, eff_auth_param = provider_and_auth(forma, body, principal, slug)
        except Exception as e:  # noqa: BLE001
            self._emit("error", stage="entrar", detail=str(e))
            self._terminar_intento(ok=False, session_error=str(e), convergence="",
                                   degraded=False, verified=0, forma=forma)
            return

        # guard del default token-query (provider None) — estricto salvo local_target declarado.
        guard = None
        try:
            from inspection.loop.guard import PublicHTTPGuard, declared_target_guard
            guard = (declared_target_guard(body.url) if p.get("local_target")
                     else PublicHTTPGuard())
        except Exception:
            guard = None

        result = None
        try:
            result = run_internal_loop(
                body.url, self._cred, principal, slug=slug, budget=budget,
                on_event=self._on_engine_event, synth_alias=p.get("synth_alias", "oss"),
                auth_param=eff_auth_param, validate_path=body.validate_path,
                validate_query=body.validate_query, provider=provider, guard=guard,
                seed_candidates=seed_candidates, api_shape_hint=body.api_shape_hint,
            )
        except Exception as e:  # noqa: BLE001
            self._emit("error", stage="motor", detail=f"{type(e).__name__}: {e}")
            self._terminar_intento(ok=False, session_error=str(e), convergence="",
                                   degraded=False, verified=0, forma=forma)
            return

        verified = len(result.verified)
        session_error = ""
        if not result.ok and result.error:
            session_error = result.error
        # session.error también viaja en events; el LoopResult.error lo captura para Forma 1/header.
        for ev in result.events:
            if ev.get("type") == "session.error":
                session_error = ev.get("detail") or session_error
        self._terminar_intento(
            ok=bool(result.ok), session_error=session_error,
            convergence=result.convergence, degraded=result.degraded,
            verified=verified, forma=forma)

    def _terminar_intento(self, *, ok: bool, session_error: str, convergence: str,
                          degraded: bool, verified: int, forma: str) -> None:
        """Cierra un intento: emite el borrador y decide pausa-con-pregunta vs terminación."""
        with self._lock:
            self.snap.convergencia = convergence or self.snap.convergencia
            inv = self.snap.inventario
            self._emit("construccion.borrador", estacion=self.snap.estacion,
                       inventario={"tools_validadas": len(inv.tools_validadas),
                                   "tools_propuestas": len(inv.tools_propuestas),
                                   "superficie": len(inv.superficie),
                                   "belt_ref": inv.belt_ref})
            pregunta = preguntas.clasificar_desenlace(
                self.snap.construccion_id, ok=ok, degraded=degraded,
                convergence=convergence, session_error=session_error,
                verified=verified, forma=forma)
            if pregunta is not None:
                self.snap.pregunta = pregunta
                self.snap.estado = "pausada"
                self.snap.estacion = pregunta.estacion
                self._emit("pregunta.pendiente", **pregunta.to_dict())
                self._emit("construccion.pausada", motivo="pregunta")
                self._persistir()
                self._thread = None
                return
            self.snap.pregunta = None
            self.snap.estado = "terminada"
            self.snap.ok = bool(ok and verified > 0)
            self._emit("construccion.cerrada", ok=self.snap.ok,
                       resultado={"tools_validadas": verified, "belt_ref": inv.belt_ref,
                                  "convergencia": convergence})
            self._persistir()
            self._thread = None

    # ── lanzamiento / pausa pre-motor ───────────────────────────────────────────
    def arrancar(self) -> None:
        """Evalúa las preguntas PRE-MOTOR y, si el pedido está claro, lanza el motor."""
        with self._lock:
            self._emit("construccion.creada", service=self.snap.service,
                       puppet_id=(self.snap.pedido or {}).get("puppet_id"),
                       space_id=self.snap.space_id)
            pedido_check = dict(self.snap.pedido or {})
            pedido_check["cred_provista"] = bool(self._cred)
            pregunta = preguntas.clasificar_pre_motor(self.snap.construccion_id, pedido_check)
            if pregunta is not None:
                self.snap.pregunta = pregunta
                self.snap.estado = "pausada"
                self.snap.estacion = pregunta.estacion
                self._emit("estacion.cambio", estacion=pregunta.estacion, previa=None,
                           n=proyeccion.indice(pregunta.estacion))
                self._emit("pregunta.pendiente", **pregunta.to_dict())
                self._emit("construccion.pausada", motivo="pregunta")
                self._persistir()
                return
        self._lanzar_motor()

    def _lanzar_motor(self, *, seed_candidates: tuple = (), seed_forma: Optional[str] = None) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return  # ya hay un intento vivo
            self.snap.estado = "trabajando"
            self.snap.pregunta = None
            self._persistir()
        th = threading.Thread(
            target=self._correr_intento,
            kwargs={"seed_candidates": seed_candidates, "seed_forma": seed_forma},
            name=f"construccion-{self.snap.construccion_id}", daemon=True)
        with self._lock:
            self._thread = th
        th.start()

    # ── responder una pregunta pendiente ────────────────────────────────────────
    def responder(self, opcion: str, *, aporte: Optional[dict] = None) -> dict:
        """Aplica la respuesta a la pregunta pendiente y destraba (relanza el motor) o re-pausa."""
        with self._lock:
            preg = self.snap.pregunta
            if preg is None:
                return {"ok": False, "error": "no hay pregunta pendiente"}
            validas = {o.id for o in preg.opciones}
            if opcion not in validas:
                return {"ok": False, "error": f"opción inválida (válidas: {sorted(validas)})"}
            self.snap.decisiones.append({
                "pregunta_id": preg.pregunta_id, "codigo": preg.codigo,
                "opcion": opcion, "at": ahora()})
            self._emit("pregunta.respondida", pregunta_id=preg.pregunta_id, opcion=opcion)
            codigo = preg.codigo
            self.snap.pregunta = None

        aporte = aporte or {}

        # guardar-borrador: queda pausada, sin relanzar.
        if opcion == "guardar-borrador":
            with self._lock:
                self.snap.estado = "pausada"
                self._emit("construccion.pausada", motivo="cancelada")
                self._persistir()
            return {"ok": True, "estado": "pausada", "reanuda": False}

        seed_forma: Optional[str] = None
        seed_candidates: tuple = ()

        # P3 · elección de forma. token/login → necesita credencial por su canal (no acá).
        if codigo == "P3":
            if opcion in ("token", "login", "abierto"):
                with self._lock:
                    self.snap.pedido["forma"] = "abierto" if opcion == "abierto" else opcion
                if opcion in ("token", "login") and not self._cred:
                    # re-pausar hasta que llegue la credencial por /credencial (fuera de banda).
                    with self._lock:
                        self.snap.estado = "pausada"
                        self._emit("construccion.pausada", motivo="espera_credencial")
                        self._persistir()
                    return {"ok": True, "estado": "pausada", "reanuda": False,
                            "espera": "credencial",
                            "detalle": "Carga la credencial por su canal (POST /credencial); "
                                       "al recibirla arranca sola."}
                seed_forma = self.snap.pedido.get("forma")
            elif opcion == "browser":
                with self._lock:
                    self.snap.pedido["forma"] = "browser"
                    self.snap.estado = "pausada"
                    self._emit("construccion.pausada", motivo="espera_sesion_browser")
                    self._persistir()
                return {"ok": True, "estado": "pausada", "reanuda": False,
                        "espera": "browser",
                        "detalle": "Captura la sesión (POST /v1/inspect/session/browser) y "
                                   "reenvía su session_key por /respuesta o /retomar."}

        # P4 · MFA → abrir ventana: espera la captura browser (session_key) y retoma en Forma 3.
        elif codigo == "P4":
            if opcion == "abrir-ventana":
                sk = (aporte.get("session_key") or "").strip()
                with self._lock:
                    self.snap.pedido["forma"] = "browser"
                    if sk:
                        self.snap.pedido["session_key"] = sk
                if not sk:
                    with self._lock:
                        self.snap.estado = "pausada"
                        self._emit("construccion.pausada", motivo="espera_sesion_browser")
                        self._persistir()
                    return {"ok": True, "estado": "pausada", "reanuda": False, "espera": "browser"}
                seed_forma = "browser"

        # P5 · pista para armar: docs → api_shape_hint; ejemplo → seed candidate por el candado.
        elif codigo == "P5":
            if opcion == "aportar-docs":
                docs = (aporte.get("docs_url") or aporte.get("hint") or "").strip()
                with self._lock:
                    self.snap.pedido["api_shape_hint"] = (
                        (self.snap.pedido.get("api_shape_hint") or "") + " " + docs).strip()
            elif opcion == "aportar-ejemplo":
                seed_candidates = _ejemplo_a_seed(aporte.get("ejemplo") or aporte)

        # P2 · aportar URL/docs.
        elif codigo == "P2":
            if opcion == "aportar-url":
                url = (aporte.get("url") or "").strip()
                docs = (aporte.get("docs_url") or "").strip()
                with self._lock:
                    if url:
                        self.snap.pedido["url"] = url
                    if docs:
                        self.snap.pedido["docs_url"] = docs
                        self.snap.pedido["api_shape_hint"] = (
                            (self.snap.pedido.get("api_shape_hint") or "") + " " + docs).strip()
                # tras aportar la URL puede seguir faltando la forma → re-evaluar pre-motor.
                if not (self.snap.pedido.get("url") or "").strip():
                    with self._lock:
                        self.snap.estado = "pausada"
                        self._persistir()
                    return {"ok": True, "estado": "pausada", "reanuda": False}

        self._emit("construccion.reanudada", estacion=self.snap.estacion)
        # re-chequear pre-motor por si el aporte no alcanzó (p.ej. sigue sin forma/cred)
        with self._lock:
            pedido_check = dict(self.snap.pedido or {})
            pedido_check["cred_provista"] = bool(self._cred)
            pre = preguntas.clasificar_pre_motor(self.snap.construccion_id, pedido_check)
        if pre is not None:
            with self._lock:
                self.snap.pregunta = pre
                self.snap.estado = "pausada"
                self.snap.estacion = pre.estacion
                self._emit("pregunta.pendiente", **pre.to_dict())
                self._emit("construccion.pausada", motivo="pregunta")
                self._persistir()
            return {"ok": True, "estado": "pausada", "reanuda": False, "pregunta": pre.to_dict()}

        self._lanzar_motor(seed_candidates=seed_candidates, seed_forma=seed_forma)
        return {"ok": True, "estado": "trabajando", "reanuda": True}

    def continuar_tras_credencial(self) -> dict:
        """Llamado por POST /credencial cuando la construcción esperaba la credencial."""
        with self._lock:
            esperaba = self.snap.estado == "pausada" and self.snap.pregunta is None
        if not esperaba:
            return {"ok": True, "reanuda": False}
        self._emit("construccion.reanudada", estacion=self.snap.estacion)
        self._lanzar_motor(seed_forma=self.snap.pedido.get("forma"))
        return {"ok": True, "reanuda": True, "estado": "trabajando"}

    # ── retomar un borrador ─────────────────────────────────────────────────────
    def retomar(self, *, session_key: Optional[str] = None) -> dict:
        """Re-arranca desde la estación guardada, sembrando las tools ya validadas para no
        re-descubrirlas. Si hay pregunta pendiente, retomar equivale a re-emitirla."""
        with self._lock:
            if session_key:
                self.snap.pedido["session_key"] = session_key
                self.snap.pedido["forma"] = "browser"
            if self.snap.pregunta is not None:
                self._emit("pregunta.pendiente", **self.snap.pregunta.to_dict())
                return {"ok": True, "estado": "pausada", "pregunta": self.snap.pregunta.to_dict()}
            if self._thread is not None and self._thread.is_alive():
                return {"ok": True, "estado": "trabajando", "reanuda": False}
        if self._cred is None:
            self._cred = self._leer_cred_vault()
        seeds = _validadas_a_seed(self.snap.inventario.tools_validadas
                                  + self.snap.inventario.tools_propuestas)
        self._emit("construccion.reanudada", estacion=self.snap.estacion)
        self._lanzar_motor(seed_candidates=seeds, seed_forma=self.snap.pedido.get("forma"))
        return {"ok": True, "estado": "trabajando", "reanuda": True}


# ── helpers de siembra (dict → CandidateTool) ───────────────────────────────────
def _ejemplo_a_seed(ej: dict) -> tuple:
    """Un ejemplo de llamada del usuario → CandidateTool (pasa por el MISMO candado)."""
    ej = ej or {}
    endpoint = (ej.get("endpoint") or ej.get("path") or "").strip()
    if not endpoint:
        return ()
    kind = C.ToolKind.WRITE if (ej.get("kind") == "write") else C.ToolKind.READ
    return (C.CandidateTool(
        name=ej.get("name") or _slug(endpoint),
        kind=kind, endpoint=endpoint,
        method=(ej.get("method") or "GET").upper(),
        input_schema={"type": "object", "x-sample-call": {
            "path_params": ej.get("path_params") or {},
            "query": ej.get("query") or {}}},
        description=ej.get("description") or "ejemplo aportado por el usuario"),)


def _validadas_a_seed(tools: list[dict]) -> tuple:
    """Tools del inventario (dict) → CandidateTool para sembrar la retoma."""
    from inspection.library import store
    out = []
    vistos = set()
    for t in tools or []:
        name = t.get("name")
        endpoint = t.get("endpoint")
        if not endpoint or name in vistos:
            continue
        vistos.add(name)
        d = {"name": name, "endpoint": endpoint, "method": t.get("method", "GET"),
             "kind": t.get("kind", "read"), "input_schema": t.get("params") or {},
             "description": t.get("description", "")}
        try:
            out.append(store.candidate_from_dict(d))
        except Exception:
            continue
    return tuple(out)


# ── registro in-process de construcciones vivas ─────────────────────────────────
class RegistroConstrucciones:
    """Mapa construccion_id → RunnerConstruccion, thread-safe. Re-hidrata del snapshot si el
    runner no está en memoria (p.ej. tras reinicio del server)."""

    def __init__(self):
        self._runners: dict[str, RunnerConstruccion] = {}
        self._lock = threading.Lock()

    def crear(self, *, service: Optional[str], pedido: dict, user_id: Optional[str],
              cred: Optional[str]) -> RunnerConstruccion:
        construccion_id = "mc-" + uuid.uuid4().hex[:16]
        principal = _principal_de(user_id, construccion_id)
        space_id = "construccion-" + construccion_id
        snap = Snapshot(
            construccion_id=construccion_id, estado="trabajando", estacion=None,
            service=service, pedido=dict(pedido), space_id=space_id,
            principal_ns=C.credential_namespace(principal),
            creada_en=ahora(), tocada_en=ahora(),
            inventario=Inventario(puppet_id=pedido.get("puppet_id")))
        runner = RunnerConstruccion(snap, principal, user_id=user_id)
        if cred:
            runner.set_credencial(cred)
        with self._lock:
            self._runners[construccion_id] = runner
        return runner

    def obtener(self, construccion_id: str, *, user_id: Optional[str]) -> Optional[RunnerConstruccion]:
        with self._lock:
            r = self._runners.get(construccion_id)
        if r is not None:
            # ANTI-IDOR (defense-in-depth): el runner cacheado se devuelve SOLO a su dueño. Un
            # autenticado B con el id de A (o un anónimo pidiendo el de un autenticado, o viceversa)
            # ve 404, no la construcción ajena. Anónimo↔anónimo con el MISMO id sí (modelo de
            # capacidad: quien tiene el id opaco). El id es uuid4 (no adivinable) — esto es el piso.
            if r.user_id == user_id:
                return r
            return None
        # re-hidratar del snapshot (post-reinicio). El snapshot vive en el namespace del principal,
        # así que un principal distinto NO encuentra el de otro (aislamiento por-namespace del vault).
        principal = _principal_de(user_id, construccion_id)
        snap = almacen.cargar(principal, construccion_id)
        if snap is None:
            return None
        r = RunnerConstruccion(snap, principal, user_id=user_id)
        with self._lock:
            self._runners[construccion_id] = r
        return r

    def listar(self, *, user_id: Optional[str]) -> list[dict]:
        principal = _principal_de(user_id, "")  # el listado usa el namespace del user
        # para autenticado el namespace es u/<user>; para anónimo el listado es por-runner vivo.
        vivos = []
        if user_id:
            snaps = almacen.listar(C.Principal(user_id=user_id))
            return [s.resumen() for s in snaps]
        with self._lock:
            for r in self._runners.values():
                if r.user_id is None:
                    vivos.append(r.snap.resumen())
        vivos.sort(key=lambda s: s.get("tocada_en", 0), reverse=True)
        return vivos


# instancia módulo-global (una por proceso backend)
REGISTRO = RegistroConstrucciones()

__all__ = ["RunnerConstruccion", "RegistroConstrucciones", "REGISTRO"]
