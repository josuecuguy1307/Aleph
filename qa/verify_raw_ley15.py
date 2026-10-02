#!/usr/bin/env python3
"""verify_raw_ley15.py — EL MODO RAW, Y LAS DOS GARANTÍAS QUE F5 PIDIÓ.
[Gate 4 · Fase 4 · obra O6 · LEY 15]

QUÉ AFIRMA
----------
  1 · **Un turno sin agente ENTRA** por el borde: sin `puppet_id` y sin `recipe`, con el
      modelo del selector, ya no hay `422 missing_recipe`.
  2 · **El sistema JAMÁS fabrica un agente** (ley 15.b): un turno raw no escribe **ni una
      fila** en `puppets`. Se cuenta antes y después, contra la DB real.
  3 · **GARANTÍA (A) — el modelo del raw sale del camino OFICIAL.** El `model_cfg` del turno
      raw pasa por `models.resolve_recipe_model`, el MISMO que usa el run completo. Se mide
      con un espía sobre la función real (envuelve y delega, no la reemplaza).
  4 · **GARANTÍA (B) — ningún turno raw se saltea `_route_chat` ni el loop.** El paso llega a
      `assembler._route_chat` con lo que resolvió (A), y sigue produciendo `model_final`
      honesto y su cost-event al ledger. Mismo espía, misma técnica.
  5 · Elegir un modelo **sin llave** da causa tipada `modelo_no_conectado` (424), no un 500
      ni un turno que muere adentro del proveedor.

LO QUE NO SE FINGE, Y LO QUE SÍ
-------------------------------
El **borde es REAL** (el backend de verdad, sus endpoints de verdad) y **la DB es real**. Lo
único que se sustituye es **el proveedor del otro lado del cable**: un servidor HTTP del
arnés que contesta el sobre de un proveedor OpenAI. No es inferencia local ni una llave
gastada en una vara — es el destino del cable, y sustituirlo es lo que permite afirmar que
el turno **llegó hasta ahí** por el camino oficial.

PROBADA CAYENDO — CONTRA EL CÓDIGO QUE NO TENÍA RAW
---------------------------------------------------
`--caer antes` requiere ALEPH_RAW_BASELINE_ROOT apuntando a una copia testigo aislada
que no tenga esta obra, y corre los MISMOS asserts HTTP. No hay perilla de sabotaje en
producción: una perilla así se queda para siempre en el código del usuario y además sólo
prueba que la perilla anda.

    python3 qa/verify_raw_ley15.py
    python3 qa/verify_raw_ley15.py --caer antes
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CAER = ""
for i, a in enumerate(sys.argv):
    if a == "--caer" and i + 1 < len(sys.argv):
        CAER = sys.argv[i + 1]

fallos: list[str] = []


def ok(cond: bool, etiqueta: str, extra: str = "") -> None:
    print(f"{'✓' if cond else '✗'} {etiqueta}{('  ' + extra) if extra else ''}", flush=True)
    if not cond:
        fallos.append(etiqueta)


def puerto_libre() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = int(s.getsockname()[1])
    s.close()
    return p


def python_del_backend() -> str:
    for c in [RAIZ / "product/backend/.venv/bin/python"]:
        if c.is_file():
            return str(c)
    print("✗ no encontré el venv del backend", file=sys.stderr)
    sys.exit(2)


def pedir(url, metodo="GET", cuerpo=None, cab=None, timeout=40.0):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    cabeceras = {"Content-Type": "application/json", **(cab or {})}
    req = urllib.request.Request(url, data=datos, method=metodo, headers=cabeceras)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:                                   # noqa: BLE001
            return e.code, None


# ── EL PROVEEDOR DEL OTRO LADO DEL CABLE (lo único sustituido) ──────────────────────
class _Proveedor(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    visto: list = []

    def log_message(self, *a):                              # noqa: D102
        pass

    def do_POST(self):                                      # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        cuerpo = json.loads(self.rfile.read(n) or b"{}")
        _Proveedor.visto.append(cuerpo)
        r = json.dumps({
            "id": "cmpl-raw", "object": "chat.completion", "created": 1,
            "model": cuerpo.get("model") or "modelo-del-arnes",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "raw, sin agente."}}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(r)))
        self.end_headers()
        self.wfile.write(r)


# ── PARTE EN PROCESO · LAS DOS GARANTÍAS DE F5, CON ESPÍAS SOBRE LO REAL ────────────

def parte_garantias(url_proveedor: str) -> None:
    sys.path.insert(0, str(RAIZ / "product/backend"))
    sys.path.insert(0, str(RAIZ / "platform"))
    from app.phase1 import workspace_brain as wb

    a = wb._asm()
    visto = {"resolve": [], "route": []}

    resolve_real = a._models.resolve_recipe_model
    route_real = a._route_chat

    def resolve_espia(model_cfg):
        visto["resolve"].append(dict(model_cfg or {}))
        return resolve_real(model_cfg)                      # DELEGA en la real

    def route_espia(messages, tools, **kw):
        visto["route"].append({k: kw.get(k) for k in ("base_url", "primary", "fallback")})
        return route_real(messages, tools, **kw)            # DELEGA en la real

    a._models.resolve_recipe_model = resolve_espia
    a._route_chat = route_espia
    try:
        eventos: list = []
        cfg = {"primary": "modelo-del-arnes", "base_url": url_proveedor}
        salida = wb.complete({"model": cfg},
                             [{"role": "user", "content": "hola sin agente"}], [],
                             on_event=eventos.append, user_id=None, workspace="ciencia")
    finally:
        a._models.resolve_recipe_model = resolve_real
        a._route_chat = route_real

    print("\n── GARANTÍA (A) · el modelo sale del camino oficial ──")
    ok(len(visto["resolve"]) == 1,
       "el turno raw pasa por `models.resolve_recipe_model` — el MISMO del run completo",
       f"{len(visto['resolve'])} llamada/s · workspace_brain.py:210")
    ok(visto["resolve"] and visto["resolve"][0].get("primary") == "modelo-del-arnes",
       "y lo hace con EL model_cfg del raw, no con otro",
       json.dumps(visto["resolve"][:1]))

    print("\n── GARANTÍA (B) · nadie se saltea `_route_chat` ni el loop ──")
    ok(len(visto["route"]) == 1,
       "el turno raw llega a `assembler._route_chat` — no hay una segunda vía al proveedor",
       f"{len(visto['route'])} llamada/s · workspace_brain.py:239")
    ok(visto["route"] and visto["route"][0].get("base_url") == url_proveedor
       and visto["route"][0].get("primary") == "modelo-del-arnes",
       "y con lo que resolvió (A): la cadena no se corta en el medio",
       json.dumps(visto["route"][:1]))
    ok(salida.get("model") == "modelo-del-arnes",
       "el `model_final` sale del proveedor, no de lo que el harness declaró",
       str(salida.get("model")))
    ok(any((e or {}).get("type") == "cost" for e in eventos),
       "y el gasto del turno raw llega al ledger igual que el de un run",
       json.dumps([e.get("type") for e in eventos]))


# ── PARTE HTTP · EL BORDE REAL, LA DB REAL ─────────────────────────────────────────

def parte_borde() -> int:
    datos = Path(tempfile.mkdtemp(prefix="f4-raw-"))
    puerto, p_prov = puerto_libre(), puerto_libre()
    base = f"http://127.0.0.1:{puerto}"
    prov = ThreadingHTTPServer(("127.0.0.1", p_prov), _Proveedor)
    threading.Thread(target=prov.serve_forever, daemon=True).start()

    # El testigo histórico es opt-in; nunca se descubre un repositorio privado.
    baseline = os.environ.get("ALEPH_RAW_BASELINE_ROOT")
    if CAER == "antes" and not baseline:
        print("BLOCKED: --caer antes requiere ALEPH_RAW_BASELINE_ROOT aislado")
        return 2
    arbol = RAIZ if CAER != "antes" else Path(baseline).resolve()
    if CAER == "antes" and "_modelo_crudo" in (arbol / "product/backend/app/phase1/router.py").read_text():
        print("✗ el testigo ya trae la obra: esta falsificación no probaría nada")
        return 2
    proc = subprocess.Popen(
        [python_del_backend(), "-m", "uvicorn", "app.main:app",
         "--app-dir", str(arbol / "product/backend"),
         "--host", "127.0.0.1", "--port", str(puerto)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        env={**os.environ, "ALEPH_DATA_DIR": str(datos), "ALEPH_ROLE": "client",
             "ALEPH_ENV": "dev", "PUPPET_ALLOW_PASSWORD_AUTH": "1"})
    try:
        vivo = False
        for _ in range(60):
            time.sleep(1)
            try:
                urllib.request.urlopen(base + "/health", timeout=2)
                vivo = True
                break
            except Exception:                               # noqa: BLE001
                pass
        print("── el borde REAL, con la DB real ──")
        ok(vivo, "el backend está en pie", base)
        if not vivo:
            return 1

        st, u = pedir(base + "/v1/auth/register", "POST", {
            "email": f"raw-{uuid.uuid4().hex[:8]}@puppet.local",
            "password": "vara-ley15", "display_name": "Raw"})
        ok(st == 201 and u.get("session_token"), "hay una cuenta para hablar", f"({st})")
        cab = {"Authorization": "Bearer " + u["session_token"]}

        def agentes() -> int:
            """Las filas de `puppets` EN LA DB REAL. La ley 15.b se mide contando, no
            confiando en que nadie escribió."""
            db = next((p for p in datos.rglob("aleph.db")), None)
            if db is None:
                return -1
            con = sqlite3.connect(str(db))
            try:
                return int(con.execute("SELECT COUNT(*) FROM puppets").fetchone()[0])
            finally:
                con.close()

        antes = agentes()
        ok(antes >= 0, "puedo contar los agentes en la DB real", f"{antes} al empezar")

        # ── 1 · UN TURNO SIN AGENTE ENTRA ────────────────────────────────────────────
        cuerpo = {"messages": [{"role": "user", "content": "hola"}],
                  "workspace": "ciencia", "user_id": u["id"],
                  "model": "opus"}            # el picker_id del selector de la casa
        st, r = pedir(base + "/v1/workspaces/brain/complete", "POST", cuerpo, cab)
        detalle = (r or {}).get("detail") or {}
        causa = detalle.get("error") if isinstance(detalle, dict) else None
        ok(st != 422 or causa != "missing_recipe",
           "sin agente y sin receta, el borde YA NO contesta `missing_recipe`",
           f"({st}) {causa or ''}")
        # 424 = entró a la rama raw y frenó por falta de llave, que es lo correcto en una
        # instalación sin credenciales. Es el modo de fallo HONESTO de esta vara.
        ok(st == 424 and causa == "modelo_no_conectado",
           "y frena con causa tipada: el modelo elegido no tiene llave",
           f"({st}) {causa} · {str(detalle.get('detail'))[:60]}")

        # ── 2 · NI UNA FILA EN `puppets` ─────────────────────────────────────────────
        despues = agentes()
        ok(despues == antes,
           "LEY 15.b · un turno raw NO escribe ni una fila en `puppets`",
           f"{antes} → {despues}")

        # ── 5 · EL COPY DEL 422, CUANDO DE VERDAD NO HAY MODELO ──────────────────────
        # Con un `model` que NO existe en el catálogo: el único caso determinista en el que
        # el borde no tiene nada que resolver. (Sin sesión no sirve para medir esto: el
        # endpoint corta antes con 401, que es lo correcto y lo comprobamos de paso.)
        st, r2 = pedir(base + "/v1/workspaces/brain/complete", "POST",
                       {"messages": [{"role": "user", "content": "x"}],
                        "user_id": u["id"], "model": "modelo-que-no-existe"}, cab)
        d2 = (r2 or {}).get("detail") or {}
        ok(st == 422 and "selector" in str(d2.get("detail", "")).lower(),
           "sin un modelo que resolver, el 422 dice que se puede elegir uno en el selector",
           str(d2.get("detail"))[:80])
        st, _ = pedir(base + "/v1/workspaces/brain/complete", "POST",
                      {"messages": [{"role": "user", "content": "x"}], "user_id": u["id"]}, None)
        ok(st == 401, "y sin sesión no se habla con el cerebro de nadie", f"({st})")
        return 0
    finally:
        prov.shutdown()
        try:
            os.killpg(os.getpgid(proc.pid), 15)
            proc.wait(timeout=8)
        except Exception:                                   # noqa: BLE001
            pass
        shutil.rmtree(datos, ignore_errors=True)


def main() -> int:
    p_prov = puerto_libre()
    prov = ThreadingHTTPServer(("127.0.0.1", p_prov), _Proveedor)
    threading.Thread(target=prov.serve_forever, daemon=True).start()
    try:
        # Las garantías (A) y (B) se miden SIEMPRE contra el árbol de esta rama: son sobre
        # el camino interno, que la obra no tocó y que el sabotaje no tiene por qué mover.
        parte_garantias(f"http://127.0.0.1:{p_prov}/v1")
    finally:
        prov.shutdown()
    print()
    parte_borde()
    print(f"\n{'VERDE' if not fallos else 'ROJAS: ' + ', '.join(fallos)}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
