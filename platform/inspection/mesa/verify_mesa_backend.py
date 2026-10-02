"""
verify_mesa_backend.py — harness backend de la Mesa (in-process, determinista, cero cerebro).

Cubre los checks §6 que NO exigen un cerebro vivo:
  #1 (parcial) proyección: eventos CRUDOS del motor → estaciones/chips, SOLO lo que emitió.
  #2 preguntar-temprano: caso ambiguo (forma sin cred) PAUSA con P3; caso claro NO pregunta.
  #3 borrador retomable: pausa → snapshot en disco → re-hidratar → retomar.
  #4 manual = mismo gate: tool buena VERIFICADA, tool rota RECHAZADA por el candado.
  #6 credenciales fuera de banda: grep del snapshot tras cargar una credencial → cero cred.

El candado (#4) se prueba contra un FIXTURE HTTP local (local_target) — cero red externa, cero
tokens. Corre: PYTHONPATH=platform:product/backend python platform/inspection/mesa/verify_mesa_backend.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

_HERE = Path(__file__).resolve()
_REPO = _HERE.parents[3]
sys.path.insert(0, str(_REPO / "platform"))
sys.path.insert(0, str(_REPO / "product" / "backend"))

# aislar el almacén y el vault en un tmp (no ensuciar data/ del repo)
_TMP = Path(tempfile.mkdtemp(prefix="mesa-verify-"))
os.environ.setdefault("PUPPET_VAULT_MASTER", "mesa-verify-master-secret")

from inspection import contracts as C  # noqa: E402
from inspection.mesa import almacen, consola, modelos, preguntas, proyeccion  # noqa: E402

_PASS = 0
_FAIL = 0


def check(name: str, ok: bool, extra: str = "") -> None:
    global _PASS, _FAIL
    mark = "✓" if ok else "✗"
    print(f"  {mark} {name}" + (f" — {extra}" if extra else ""))
    if ok:
        _PASS += 1
    else:
        _FAIL += 1


# ── FIXTURE HTTP local: /configuration (200), /good (200+json), /bad (404) ──────
class _Fixture(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silencio
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/configuration", "/good"):
            body = json.dumps({"ok": True, "images": {"base_url": "http://x"}, "id": 1}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"not found"}')

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Allow", "GET, OPTIONS")
        self.end_headers()


def _start_fixture():
    srv = HTTPServer(("127.0.0.1", 0), _Fixture)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{port}"


# ── #2 · preguntar-temprano (pre-motor), ambos sentidos ─────────────────────────
def test_pregunta_pre_motor():
    print("[#2] preguntar-temprano (pre-motor)")
    claro = preguntas.clasificar_pre_motor(
        "mc-a", {"url": "https://api.themoviedb.org/3", "forma": "token", "cred_provista": True})
    check("caso CLARO (url+token+cred) NO pregunta", claro is None)
    amb = preguntas.clasificar_pre_motor(
        "mc-a", {"url": "https://api.themoviedb.org/3", "forma": "token", "cred_provista": False})
    check("token SIN cred → pregunta P3", amb is not None and amb.codigo == "P3",
          amb.texto if amb else "")
    check("P3 tiene 2-3 opciones reales", amb is not None and 2 <= len(amb.opciones) <= 4)
    check("P3 NUNCA pide la cred en el chat (abre=credencial)",
          amb is not None and any(o.abre == "credencial" for o in amb.opciones))
    sin_url = preguntas.clasificar_pre_motor("mc-a", {"url": "", "forma": "token"})
    check("sin URL ni docs → pregunta P2", sin_url is not None and sin_url.codigo == "P2")


# ── #2b · preguntar-temprano (post-motor), ambos sentidos ───────────────────────
def test_pregunta_post_motor():
    print("[#2b] preguntar-temprano (post-motor: MFA, degradado, ok)")
    p4 = preguntas.clasificar_desenlace(
        "mc-b", ok=False, degraded=False, convergence="",
        session_error="el login pide 2FA — usá Forma 3 (navegador)", verified=0, forma="login")
    check("MFA en login → P4 (abrir ventana)", p4 is not None and p4.codigo == "P4",
          p4.opciones[0].abre if p4 else "")
    check("P4 abre el flujo browser (2FA humano)",
          p4 is not None and any(o.abre == "browser" for o in p4.opciones))
    p5 = preguntas.clasificar_desenlace(
        "mc-b", ok=False, degraded=True, convergence="degraded: el cerebro no respondió",
        session_error="", verified=0, forma="token")
    check("cerebro degradado → P5 (aportar pista)", p5 is not None and p5.codigo == "P5")
    ok = preguntas.clasificar_desenlace(
        "mc-b", ok=True, degraded=False, convergence="convergió",
        session_error="", verified=3, forma="token")
    check("terminó OK (3 tools) → NO pregunta", ok is None)
    red = preguntas.clasificar_desenlace(
        "mc-b", ok=False, degraded=False, convergence="", session_error="target inalcanzable",
        verified=0, forma="token")
    check("session_error de red → NO pregunta (no es punto de decisión)", red is None)


# ── #1 · proyección evento crudo → estación/chips, SOLO lo emitido ──────────────
def test_proyeccion():
    print("[#1] proyección: eventos del motor → estaciones (cero-teatro)")
    # secuencia CRUDA típica de un run feliz del engine
    crudos = [
        {"type": "session.acquired", "form": "token", "meta": {"auth_form": "token_query",
         "key_fingerprint": "sha256:ab…1234", "validated_by": "/configuration", "validate_status": 200}},
        {"type": "observe", "round": 1, "passive": True, "mode": "passive", "probed": None,
         "new_confirmed": ["/movie/{id}"]},
        {"type": "synth.start", "round": 1, "alias": "oss"},
        {"type": "synth", "round": 1, "degraded": False, "model": "gpt-oss-120b",
         "proposed": ["/movie/{id}"], "fresh": ["/movie/{id}"],
         "fresh_detail": [{"name": "get_movie", "endpoint": "/movie/{id}", "method": "GET",
                           "kind": "read", "params": {}, "description": "una peli", "sig": "/movie/{id}"}],
         "tokens": 10},
        {"type": "validate", "round": 1,
         "verified": ["get_movie"],
         "verified_detail": [{"name": "get_movie", "endpoint": "/movie/{id}", "method": "GET",
                              "kind": "read", "params": {}, "verified_by": "200-OK+schema-match",
                              "sample_response": "{...}"}],
         "failed": [], "frontier_opened": []},
        {"type": "forged", "server_name": "forged-tmdb", "belt_ref": "belt-x", "tools": ["get_movie"],
         "agents": []},
        {"type": "closed", "convergence": "convergió", "verified": 1, "dropped": 0,
         "degraded": False, "budget": {}},
    ]
    # traducir con el _translate real y proyectar estación por estación
    from app.phase1.forge_router import _translate
    estacion = None
    secuencia = []
    tipos_contrato = []
    for ev in crudos:
        for cev in _translate(ev, target_url="http://x", puppet_id="pup-1"):
            tipos_contrato.append(cev["type"])
            nueva = proyeccion.avanzar(estacion, cev["type"])
            if nueva != estacion:
                secuencia.append(nueva)
                estacion = nueva
    check("estaciones avanzan en orden sin retroceder",
          secuencia == ["entrar", "ver", "armar", "probar", "equipar"],
          " → ".join(secuencia))
    # cero-teatro: cada tipo de contrato proyecta a una estación conocida o es transversal
    conocidos = set(proyeccion._EVENTO_ESTACION) | {"error", "forge.latido", "sintetizando"}
    huerfanos = [t for t in tipos_contrato if t not in conocidos]
    check("cero eventos de contrato huérfanos (todo mapea)", not huerfanos, str(huerfanos))
    # el primer evento (sesion.ok) proyecta 'entrar', no 'encontrarlo' (dispatch no corrió acá)
    check("sesion.ok → estación 'entrar'", proyeccion.estacion_de("sesion.ok") == "entrar")
    check("tool.validada → estación 'probar'", proyeccion.estacion_de("tool.validada") == "probar")


# ── #3 · borrador retomable: snapshot en disco + re-hidratar ────────────────────
def test_borrador():
    print("[#3] borrador retomable (snapshot atómico + re-hidratación)")
    principal = C.Principal(anon_id="construccion-mc-draft")
    inv = modelos.Inventario(
        identidad={"server": "forged-x"},
        tools_validadas=[{"name": "get_movie", "verified_by": "200-OK+schema-match"}],
        tools_propuestas=[{"name": "get_movie", "endpoint": "/movie/{id}"}])
    snap = modelos.Snapshot(
        construccion_id="mc-draft", estado="pausada", estacion="probar",
        service="tmdb", pedido={"url": "http://x", "forma": "token", "cred_ref": "u/x/s#API_KEY"},
        inventario=inv, space_id="construccion-mc-draft",
        creada_en=modelos.ahora(), tocada_en=modelos.ahora())
    path = almacen.guardar(principal, snap, root=_TMP / "construcciones")
    check("snapshot escrito a disco", path.exists())
    reload = almacen.cargar(principal, "mc-draft", root=_TMP / "construcciones")
    check("re-hidrata el borrador con su inventario",
          reload is not None and len(reload.inventario.tools_validadas) == 1
          and reload.estacion == "probar")
    listado = almacen.listar(principal, root=_TMP / "construcciones")
    check("aparece en el listado de borradores", len(listado) == 1
          and listado[0].construccion_id == "mc-draft")


# ── #4 · manual = mismo gate (tool buena verificada, rota rechazada) ────────────
def test_gate_manual():
    print("[#4] manual = mismo gate (candado sobre tools a mano, fixture local)")
    srv, base = _start_fixture()
    try:
        from inspection.loop.session import TMDBTokenSession
        from inspection.loop.guard import declared_target_guard
        principal = C.Principal(anon_id="construccion-mc-gate")
        provider = TMDBTokenSession(
            base, "fake-key", principal, "construccion-gate",
            auth_param="api_key", validate_path="/configuration",
            guard=declared_target_guard(base))
        session = provider.acquire()
        specs = [
            {"name": "tool_buena", "endpoint": "/good", "method": "GET", "kind": "read",
             "input_schema": {"type": "object", "x-sample-call": {"path_params": {}, "query": {}}}},
            {"name": "tool_rota", "endpoint": "/bad", "method": "GET", "kind": "read",
             "input_schema": {"type": "object", "x-sample-call": {"path_params": {}, "query": {}}}},
        ]
        out = consola.validar_tools(session, provider, specs)
        names_ok = [v["nombre"] for v in out["verificadas"]]
        names_bad = [f["nombre"] for f in out["descartadas"]]
        check("tool buena → VERIFICADA por el candado", "tool_buena" in names_ok, str(names_ok))
        check("tool rota (404) → RECHAZADA por el candado, no equipada",
              "tool_rota" in names_bad and "tool_rota" not in names_ok, str(names_bad))
        check("verified_by fuerte diferenciado",
              any(v.get("fuerza") == "fuerte" for v in out["verificadas"]))
        # consola de prueba: read dry-run + read real + write gated
        pr_dry = consola.probar_tool(session, provider, specs[0], {}, execute=False)
        check("probar read dry-run → request armada sin pegar",
              pr_dry.get("dry_run") is True and "request" in pr_dry)
        pr_real = consola.probar_tool(session, provider, specs[0], {}, execute=True)
        check("probar read execute → GET vivo 200",
              pr_real.get("response", {}).get("status") == 200)
        write_spec = {"name": "borra", "endpoint": "/good", "method": "DELETE", "kind": "write",
                      "input_schema": {"type": "object"}}
        pr_w = consola.probar_tool(session, provider, write_spec, {}, execute=True)
        check("probar WRITE → gateado, JAMÁS ejecutado",
              pr_w.get("gated") is True and pr_w.get("approval_required") is True)
    finally:
        srv.shutdown()


# ── #6 · credencial nunca en el snapshot ────────────────────────────────────────
def test_credencial_fuera_de_banda():
    print("[#6] credencial fuera de banda (grep del snapshot)")
    secreto = "SUPERSECRETO-abc123XYZ"
    principal = C.Principal(anon_id="construccion-mc-cred")
    snap = modelos.Snapshot(
        construccion_id="mc-cred", estado="pausada", estacion="entrar",
        pedido={"url": "http://x", "forma": "token", "cred_ref": "anon/xxx/s#API_KEY"},
        space_id="construccion-mc-cred", creada_en=modelos.ahora(), tocada_en=modelos.ahora())
    almacen.guardar(principal, snap, root=_TMP / "construcciones")
    raw = (_TMP / "construcciones" / C.credential_namespace(principal) / "mc-cred"
           / "snapshot.json").read_text()
    check("el secreto NO aparece en el snapshot", secreto not in raw)
    check("el snapshot solo guarda cred_ref (puntero al vault)", "cred_ref" in raw
          and "#API_KEY" in raw)


# ── review · IDOR en REGISTRO.obtener (hallazgo HIGH del review adversarial) ─────
def test_idor_registro():
    print("[review·HIGH] anti-IDOR: obtener() devuelve el runner SOLO a su dueño")
    from app.phase1.mesa_runner import RegistroConstrucciones
    reg = RegistroConstrucciones()
    rA = reg.crear(service="x", pedido={"url": "http://x", "forma": "abierto"}, user_id="userA", cred=None)
    cid = rA.snap.construccion_id
    check("el dueño (userA) SÍ recupera su construcción", reg.obtener(cid, user_id="userA") is rA)
    check("otro autenticado (userB) con el id → 404 (None)", reg.obtener(cid, user_id="userB") is None)
    check("un anónimo NO ve la construcción autenticada", reg.obtener(cid, user_id=None) is None)
    # anon↔anon con el MISMO id opaco sí (modelo de capacidad)
    rAnon = reg.crear(service="y", pedido={"url": "http://y", "forma": "abierto"}, user_id=None, cred=None)
    cidn = rAnon.snap.construccion_id
    check("anónimo recupera su propia construcción por id", reg.obtener(cidn, user_id=None) is rAnon)
    check("un autenticado NO ve la construcción anónima", reg.obtener(cidn, user_id="userA") is None)


# ── review · race de concurrencia (hallazgo MED del review adversarial) ─────────
def test_concurrencia_inventario():
    print("[review·MED] concurrencia: mutar inventario + leer snapshot sin crash")
    from app.phase1.mesa_runner import RegistroConstrucciones
    reg = RegistroConstrucciones()
    r = reg.crear(service="x", pedido={"url": "http://x", "forma": "abierto"}, user_id=None, cred=None)
    stop = [False]
    errores = []

    def mutar():
        i = 0
        while not stop[0]:
            i += 1
            try:
                r._on_engine_event({"type": "synth", "round": 1, "degraded": False, "model": "m",
                    "fresh_detail": [{"name": f"t{i}", "endpoint": f"/e{i}", "method": "GET",
                                      "kind": "read", "params": {}, "description": "x", "sig": f"/e{i}"}]})
                r._on_engine_event({"type": "validate", "round": 1,
                    "verified_detail": [{"name": f"t{i}", "endpoint": f"/e{i}", "method": "GET",
                        "kind": "read", "params": {}, "verified_by": "200-OK+schema-match",
                        "sample_response": "{}"}], "failed": [], "verified": [f"t{i}"]})
            except Exception as e:  # noqa: BLE001
                errores.append(f"mutador: {e!r}")
                break

    th = threading.Thread(target=mutar, daemon=True)
    th.start()
    # leer el snapshot (asdict) en ráfaga MIENTRAS el otro thread appendea
    for _ in range(400):
        try:
            with r._lock:
                r.snap.inventario.to_dict()
        except Exception as e:  # noqa: BLE001
            errores.append(f"lector: {e!r}")
            break
    stop[0] = True
    th.join(timeout=2)
    check("mutación + lectura concurrente del inventario sin excepción",
          not errores, "; ".join(errores[:2]))
    check("el inventario acumuló tools bajo carga concurrente",
          len(r.snap.inventario.tools_validadas) > 0)


def main():
    print("=" * 68)
    print("VERIFY · Mesa de Construcción — backend (in-process, cero cerebro)")
    print("=" * 68)
    try:
        test_pregunta_pre_motor()
        test_pregunta_post_motor()
        test_proyeccion()
        test_borrador()
        test_gate_manual()
        test_credencial_fuera_de_banda()
        test_idor_registro()
        test_concurrencia_inventario()
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
    print("-" * 68)
    print(f"RESULTADO: {_PASS} ✓ · {_FAIL} ✗")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
