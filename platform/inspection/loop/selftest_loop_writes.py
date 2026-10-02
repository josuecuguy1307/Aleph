#!/usr/bin/env python3
"""
selftest_loop_writes.py — GATE VERDE de FASE 4-WRITES (§7 · read/write split) ·
verify-from-environment · DETERMINÍSTICO (sin cerebro, sin red externa, sin quemar Opus).

La tesis del split (§7): el candado VERIFICA los writes por FORMA (schema / OPTIONS /
dry-run) SIN ejecutarlos — un write JAMÁS se pega para validar (mutaría data real) — y el
MCP forjado los emite GATED (gate humano visible antes de tocar el mundo). Los READS
siguen idénticos.

Cómo se prueba contra el ENTORNO (un server local benigno con estado MUTABLE que yo
controlo), sin tocar ninguna data real:

  1. candidatas write HECHAS A MANO (no del synth → determinístico) → el candado las
     verifica por OPTIONS/dry-run/schema y PRUEBA cero-mutación: STATE["writes"]==0
     después (el server jamás recibió un POST/PUT/PATCH/DELETE).
  2. el candado NO expande frontera con writes (no se ejecutaron → no hay respuesta).
  3. SSRF: el guard REAL bloquea loopback ANTES de cualquier OPTIONS (cero requests).
  4. el MCP forjado emite la write GATED (gated:True · zone=entrega) en el belt + spec.
  5. el server forjado, ante una write: en ejecución exige el GATE (no pega); en
     FORGE_DRY_RUN devuelve la request armada sin pegarla — STATE["writes"] sigue 0.
  6. los READS sin regresión: se verifican por llamada real (200-OK+schema-match) y
     SÍ minan frontera.

Uso (sin secretos, sin red externa):
    product/backend/.venv/bin/python platform/inspection/loop/selftest_loop_writes.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import threading
import uuid
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from socketserver import TCPServer
from urllib.parse import parse_qs, urlparse

_PLATFORM = Path(__file__).resolve().parents[2]
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection import contracts as C  # noqa: E402
from inspection.loop.emit import MCPEmitter  # noqa: E402
from inspection.loop.guard import PublicHTTPGuard  # noqa: E402
from inspection.loop.live_http import LiveHTTP  # noqa: E402
from inspection.loop.validator import LiveValidator  # noqa: E402

_FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "✓" if cond else "✗"
    print(f"  {mark} {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        _FAILS.append(name)


# ── server local benigno con ESTADO MUTABLE (el target controlado por el test) ──────
# STATE["writes"] cuenta TODA mutación. La tesis: tras verificar writes por forma, sigue 0.
STATE = {"writes": 0, "options": 0, "items": [{"id": 1, "name": "alpha"},
                                              {"id": 2, "name": "beta"}]}
_ITEM_ID = re.compile(r"^/items/\d+$")


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_a):           # silencio: no ensuciar el gate
        return

    def _json(self, code: int, obj) -> None:
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _allow(self, methods: str) -> None:
        self.send_response(204)
        self.send_header("Allow", methods)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _mutate(self, code: int) -> None:
        # SI ALGUNA VEZ entra acá, el split está roto: una mutación real ocurrió.
        STATE["writes"] += 1
        self._json(code, {"mutated": True, "writes": STATE["writes"]})

    def do_GET(self) -> None:
        u = urlparse(self.path)
        if u.path == "/items":
            self._json(200, {"results": STATE["items"], "page": 1,
                             "total_pages": 2, "count": len(STATE["items"])})
        elif u.path == "/items/validate":            # endpoint dry-run (GET, no muta)
            self._json(200, {"valid": True, "echo": parse_qs(u.query)})
        elif _ITEM_ID.match(u.path):
            iid = int(u.path.rsplit("/", 1)[1])
            self._json(200, {"id": iid, "name": f"item-{iid}"})
        else:
            self._json(404, {"error": "not found"})

    def do_OPTIONS(self) -> None:
        STATE["options"] += 1
        path = urlparse(self.path).path
        if path == "/items":
            self._allow("GET, POST, OPTIONS")
        elif _ITEM_ID.match(path):
            self._allow("GET, PUT, PATCH, DELETE, OPTIONS")
        else:
            self._json(404, {"error": "no such endpoint"})

    def do_POST(self) -> None:
        self._mutate(201)

    def do_PUT(self) -> None:
        self._mutate(200)

    def do_PATCH(self) -> None:
        self._mutate(200)

    def do_DELETE(self) -> None:
        self._mutate(200)


def _start_server() -> tuple[TCPServer, str]:
    srv = TCPServer(("127.0.0.1", 0), _Handler)
    srv.allow_reuse_address = True
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{port}"


class _LoopbackGuard(C.SSRFGuard):
    """Guard de TEST: aprueba loopback explícitamente (opt-in) porque el target es el
    server local que ESTE test levantó — benigno y controlado. La puerta SIGUE corriendo
    un guard; el check de SSRF de abajo usa el guard REAL para probar que sin este opt-in,
    loopback se BLOQUEA antes de cualquier fetch."""

    def check(self, url: str) -> C.GuardVerdict:
        return C.GuardVerdict(True, "loopback test (target controlado)")


# ── candidatas WRITE hechas a mano (determinísticas, no del synth) ──────────────────
def _write_candidates() -> list[C.CandidateTool]:
    return [
        # verificable por OPTIONS (Allow /items incluye POST) · con cuerpo declarado:
        C.CandidateTool(
            name="create_item", kind=C.ToolKind.WRITE, endpoint="/items", method="POST",
            input_schema={"type": "object", "properties": {"name": {"type": "string"}},
                          "x-sample-call": {"body": {"name": "gamma"}}},
            description="crea un item"),
        # verificable por OPTIONS (Allow /items/{id} incluye PUT):
        C.CandidateTool(
            name="update_item", kind=C.ToolKind.WRITE, endpoint="/items/{id}", method="PUT",
            input_schema={"type": "object", "properties": {"name": {"type": "string"}},
                          "x-sample-call": {"path_params": {"id": 1}, "body": {"name": "x"}}},
            description="actualiza un item"),
        # DELETE: sin cuerpo (se identifica por path), Allow incluye DELETE:
        C.CandidateTool(
            name="delete_item", kind=C.ToolKind.WRITE, endpoint="/items/{id}", method="DELETE",
            input_schema={"type": "object", "x-sample-call": {"path_params": {"id": 2}}},
            description="borra un item"),
        # verificable por DRY-RUN: declara un validate_path (GET, no muta):
        C.CandidateTool(
            name="create_item_dryrun", kind=C.ToolKind.WRITE, endpoint="/items", method="POST",
            input_schema={"type": "object", "properties": {"name": {"type": "string"}},
                          "x-sample-call": {"body": {"name": "d"}},
                          "x-dry-run": {"validate_path": "/items/validate", "query": {"name": "d"}}},
            description="crea un item (con dry-run validate)"),
    ]


def _write_failures() -> list[C.CandidateTool]:
    return [
        # FORMA incoherente: POST sin cuerpo ni properties → BAD_SHAPE (schema, sin red):
        C.CandidateTool(
            name="bad_create", kind=C.ToolKind.WRITE, endpoint="/items", method="POST",
            input_schema={"type": "object", "x-sample-call": {}},
            description="write sin cuerpo declarado"),
        # endpoint inexistente: OPTIONS /ghost → 404 → NOT_FOUND:
        C.CandidateTool(
            name="ghost_write", kind=C.ToolKind.WRITE, endpoint="/ghost", method="POST",
            input_schema={"type": "object", "properties": {"x": {"type": "string"}},
                          "x-sample-call": {"body": {"x": "1"}}},
            description="write a un endpoint que no existe"),
        # método no permitido: DELETE sobre la colección (Allow /items no trae DELETE) → NOT_FOUND:
        C.CandidateTool(
            name="delete_collection", kind=C.ToolKind.WRITE, endpoint="/items", method="DELETE",
            input_schema={"type": "object", "x-sample-call": {}},
            description="DELETE sobre la colección (método no aceptado)"),
    ]


def _read_candidate() -> C.CandidateTool:
    return C.CandidateTool(
        name="list_items", kind=C.ToolKind.READ, endpoint="/items", method="GET",
        input_schema={"type": "object", "x-sample-call": {}},
        description="lista los items")


def _session(base: str) -> C.Session:
    return C.Session(form=C.AuthForm.TOKEN, base_url=base)


# ── [1] verificar writes por forma SIN ejecutarlos + cero-mutación ──────────────────
def gate_verify_without_executing(base: str) -> C.Validation:
    print("\n[1] el candado VERIFICA writes por forma (schema/OPTIONS/dry-run) SIN ejecutar")
    http = LiveHTTP(timeout=5.0)
    validator = LiveValidator(http, guard=_LoopbackGuard())
    writes_before = STATE["writes"]
    opts_before = STATE["options"]

    v = validator.validate(_session(base), tuple(_write_candidates()))
    verified = {vt.candidate.name: vt for vt in v.verified}

    check("STATE['writes'] == 0 — CERO mutación tras verificar los writes",
          STATE["writes"] == writes_before,
          f"writes={STATE['writes']} (era {writes_before})")
    check("el server SÍ recibió OPTIONS (la verificación es por preflight real)",
          STATE["options"] > opts_before, f"options={STATE['options']}")
    check("create_item verificada por OPTIONS",
          verified.get("create_item") and verified["create_item"].verified_by == "OPTIONS",
          verified["create_item"].verified_by if "create_item" in verified else "ausente")
    check("update_item (PUT) verificada por OPTIONS",
          verified.get("update_item") and verified["update_item"].verified_by == "OPTIONS")
    check("delete_item (DELETE, sin cuerpo) verificada por OPTIONS",
          verified.get("delete_item") and verified["delete_item"].verified_by == "OPTIONS")
    check("create_item_dryrun verificada por DRY-RUN (GET validate, no muta)",
          verified.get("create_item_dryrun") and verified["create_item_dryrun"].verified_by == "dry-run",
          verified["create_item_dryrun"].verified_by if "create_item_dryrun" in verified else "ausente")
    check("NINGUNA verificada dice verified_by='200-OK...' (un write no se ejecutó)",
          all("200-OK" not in vt.verified_by for vt in v.verified))
    check("los writes NO expandieron frontera (no se ejecutaron → nada que minar)",
          v.frontier == (), f"{len(v.frontier)} leads")
    return v


# ── [1b] los writes mal formados / inexistentes CAEN por la tabla §5 ────────────────
def gate_write_failures(base: str) -> None:
    print("\n[1b] writes incoherentes/inexistentes caen por §5 (sin mutar)")
    http = LiveHTTP(timeout=5.0)
    validator = LiveValidator(http, guard=_LoopbackGuard())
    writes_before = STATE["writes"]
    v = validator.validate(_session(base), tuple(_write_failures()))
    failed = {f.candidate.name: f for f in v.failed}

    check("STATE['writes'] == 0 — los fallos tampoco mutaron nada", STATE["writes"] == writes_before)
    check("bad_create → BAD_SHAPE (schema estático, sin red)",
          failed.get("bad_create") and failed["bad_create"].failure is C.FailureClass.BAD_SHAPE)
    check("ghost_write → NOT_FOUND (OPTIONS 404)",
          failed.get("ghost_write") and failed["ghost_write"].failure is C.FailureClass.NOT_FOUND,
          failed["ghost_write"].failure.name if "ghost_write" in failed else "ausente")
    check("delete_collection → NOT_FOUND (Allow no incluye DELETE)",
          failed.get("delete_collection") and failed["delete_collection"].failure is C.FailureClass.NOT_FOUND)
    check("ninguno de los 3 entró a VERIFIED", len(v.verified) == 0)


# ── [2] SSRF: el guard REAL bloquea loopback ANTES de cualquier OPTIONS ──────────────
def gate_ssrf_before_options(base: str) -> None:
    print("\n[2] SSRF guard corre ANTES del fetch (incluido OPTIONS)")
    real = PublicHTTPGuard()                          # fail-closed: solo https público
    verdict = real.check(base.rstrip("/") + "/items")
    check("el guard REAL DENIEGA el target loopback", not verdict.allowed, verdict.reason)

    # con el guard real inyectado, verificar un write NO debe emitir ni un OPTIONS.
    opts_before = STATE["options"]
    http = LiveHTTP(timeout=5.0)
    validator = LiveValidator(http, guard=real)
    v = validator.validate(_session(base), (_write_candidates()[0],))
    check("ningún OPTIONS salió a la red (guard cortó antes del fetch)",
          STATE["options"] == opts_before, f"options={STATE['options']} (era {opts_before})")
    check("la candidata cayó FORBIDDEN por SSRF (no verificada)",
          len(v.failed) == 1 and v.failed[0].failure is C.FailureClass.FORBIDDEN
          and "SSRF" in v.failed[0].detail, v.failed[0].detail if v.failed else "sin fallo")


# ── [3] el MCP forjado emite la write GATED ─────────────────────────────────────────
def gate_forge_gated(base: str, verified_writes: C.Validation, root: Path):
    print("\n[3] el MCP forjado emite la write GATED (gated:True · zone=entrega)")
    principal = C.Principal(anon_id=f"writes-gate-{uuid.uuid4().hex[:10]}")
    slug = "writes-gate"
    # forjamos con writes verificados + 1 read (el belt mixto read/write):
    http = LiveHTTP(timeout=5.0)
    read_v = LiveValidator(http, guard=_LoopbackGuard()).validate(_session(base), (_read_candidate(),))
    verified = list(verified_writes.verified) + list(read_v.verified)
    emitter = MCPEmitter(principal, slug, base, cred_root=root, niche="writes-selftest")
    forged = emitter.emit(verified)

    out_dir = C.credential_dir(principal, slug, root=root)
    forge_spec = json.loads((out_dir / f"{slug}.forge.json").read_text())
    belt = json.loads((out_dir / f"belt-{slug}.mcp.json").read_text())

    spec_tools = {t["name"]: t for t in forge_spec["tools"]}
    write_tools = ["create_item", "update_item", "delete_item", "create_item_dryrun"]
    check("toda write en el forge_spec trae gated:True + kind:write",
          all(spec_tools[n].get("gated") is True and spec_tools[n].get("kind") == "write"
              for n in write_tools if n in spec_tools),
          f"{[n for n in write_tools if n in spec_tools]}")
    check("la read NO está gated (kind:read)",
          spec_tools.get("list_items", {}).get("gated") is False
          and spec_tools["list_items"].get("kind") == "read")

    cards = {c["id"]: c for c in belt["_meta"]["cards"]}
    check("las cards write salen gated:True + zone=entrega",
          all(cards[n].get("gated") is True and cards[n].get("zone") == "entrega"
              for n in write_tools if n in cards))
    check("la card read sigue en zone=fuentes (no gated)",
          cards.get("list_items", {}).get("zone") == "fuentes"
          and cards["list_items"].get("gated") is False)
    check("el _meta es honesto: cuenta write_gated",
          belt["_meta"]["source"].get("write_gated") == len(write_tools),
          f"write_gated={belt['_meta']['source'].get('write_gated')}")
    return out_dir / f"{slug}.forge.json"


# ── [4] el server forjado GATEA la write por stdio (no la pega) ─────────────────────
def _rpc(forge_path: Path, cred_file: Path, calls: list[dict], *, dry_run: bool) -> list[dict]:
    import os
    env = dict(os.environ)
    env["FORGE_SPEC"] = str(forge_path)
    env["FORGE_CRED_FILE"] = str(cred_file)
    env["FORGE_EXECUTE"] = "1"
    if dry_run:
        env["FORGE_DRY_RUN"] = "1"
    else:
        env.pop("FORGE_DRY_RUN", None)
    server = Path(__file__).resolve().parent / "forged_mcp_server.py"
    lines = ([json.dumps({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}})]
             + [json.dumps(c) for c in calls])
    proc = subprocess.run([sys.executable, str(server)], input="\n".join(lines) + "\n",
                          capture_output=True, text=True, env=env, timeout=30)
    out = []
    for ln in proc.stdout.splitlines():
        ln = ln.strip()
        if ln:
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                pass
    return out


def _content(resp: dict) -> dict:
    try:
        return json.loads(resp["result"]["content"][0]["text"])
    except (KeyError, IndexError, json.JSONDecodeError, TypeError):
        return {}


def gate_forged_server_gates(forge_path: Path) -> None:
    print("\n[4] el server forjado exige el gate por stdio (write NO se pega)")
    cred_file = forge_path.parent / "credentials.enc"      # puede no existir: la write no necesita secreto
    writes_before = STATE["writes"]

    # 4a · EJECUCIÓN: una write devuelve gated/approval_required, NO muta.
    call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "create_item", "arguments": {"name": "should-not-happen"}}}
    resp = [r for r in _rpc(forge_path, cred_file, [call], dry_run=False) if r.get("id") == 1]
    body = _content(resp[0]) if resp else {}
    check("write en ejecución → gated:True + approval_required:True",
          body.get("gated") is True and body.get("approval_required") is True, json.dumps(body)[:160])
    check("la request armada muestra el método mutante real (POST)",
          (body.get("request") or {}).get("method") == "POST")
    check("STATE['writes'] == 0 — el server forjado NO pegó la write",
          STATE["writes"] == writes_before, f"writes={STATE['writes']}")

    # 4b · DRY-RUN: devuelve la request armada sin pegarla.
    resp_dr = [r for r in _rpc(forge_path, cred_file, [call], dry_run=True) if r.get("id") == 1]
    body_dr = _content(resp_dr[0]) if resp_dr else {}
    check("write en FORGE_DRY_RUN → dry_run:True + request armada (sin pegar)",
          body_dr.get("dry_run") is True and body_dr.get("gated") is True
          and (body_dr.get("request") or {}).get("method") == "POST", json.dumps(body_dr)[:160])
    check("STATE['writes'] == 0 — dry-run tampoco mutó", STATE["writes"] == writes_before)

    # 4c · READ por el server forjado: SÍ ejecuta (GET vivo) — no regresión del read.
    rcall = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "list_items", "arguments": {}}}
    resp_r = [r for r in _rpc(forge_path, cred_file, [rcall], dry_run=False) if r.get("id") == 2]
    body_r = _content(resp_r[0]) if resp_r else {}
    check("read por el server forjado ejecuta de verdad (GET 200)",
          (body_r.get("response") or {}).get("status") == 200, json.dumps(body_r)[:120])
    check("STATE['writes'] == 0 — el read no mutó nada", STATE["writes"] == writes_before)


# ── [5] READS sin regresión (llamada real + frontera minada) ────────────────────────
def gate_reads_no_regression(base: str) -> None:
    print("\n[5] los READS siguen verificándose por llamada real (sin regresión)")
    http = LiveHTTP(timeout=5.0)
    validator = LiveValidator(http, guard=_LoopbackGuard())
    v = validator.validate(_session(base), (_read_candidate(),))
    check("el read verifica por LLAMADA real (verified_by=200-OK+schema-match)",
          len(v.verified) == 1 and v.verified[0].verified_by == "200-OK+schema-match",
          v.verified[0].verified_by if v.verified else "sin verificada")
    check("el read trae sample_response real (cuerpo vivo)",
          bool(v.verified[0].sample_response) if v.verified else False)
    check("el read SÍ mina frontera (paginación + sub-recursos por id)",
          len(v.frontier) >= 1, f"{len(v.frontier)} leads: {[f.hint for f in v.frontier][:4]}")


def main() -> int:
    print("═" * 74)
    print("  GATE VERDE · FASE 4-WRITES (§7 read/write split) · DETERMINÍSTICO")
    print("═" * 74)
    srv, base = _start_server()
    root = Path(tempfile.mkdtemp(prefix="loop-writes-gate-"))
    try:
        v = gate_verify_without_executing(base)
        gate_write_failures(base)
        gate_ssrf_before_options(base)
        forge_path = gate_forge_gated(base, v, root)
        gate_forged_server_gates(forge_path)
        gate_reads_no_regression(base)

        print("\n  ── resumen de mutación del target ──")
        print(f"   STATE['writes']  = {STATE['writes']}  (debe ser 0)")
        print(f"   STATE['options'] = {STATE['options']}  (los preflights de verificación)")
        check("INVARIANTE FINAL: el target nunca fue mutado (writes==0)", STATE["writes"] == 0)
    finally:
        srv.shutdown()

    print("\n" + "═" * 74)
    if _FAILS:
        print(f"  ROJO — {len(_FAILS)} check(s) fallaron: {_FAILS}")
        return 1
    print("  VERDE — los writes se verifican por forma SIN ejecutarse, salen GATED, "
          "y los reads no regresan")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
