#!/usr/bin/env python3
"""verify_puente_legal.py — QUE LA PERILLA DE LEGAL GOBIERNE DE VERDAD.
[rediseño · fase 4 · 4.1 y 4.2]

EL DEFECTO QUE ESTA VARA EXISTE PARA IMPEDIR
────────────────────────────────────────────
Las perillas del estudio (Postura, Formalidad, Detalle) **no se leen del JSON**. El motor
lee `drafting.md`, que `dochaus/opencode.json:6` monta como
`"instructions": ["{env:WORKSPACE_ROOT}/.preferences/drafting.md"]` y relee EN CADA TURNO. Y
ese markdown **sólo se re-renderiza dentro de `writeDraftingPreferences`**
(`services/ingest/src/preferences.ts:66-67`: dos `writeFileSync` seguidos, el JSON y el md).

⇒ Un puente que escriba el JSON a mano deja las tres perillas cambiadas en pantalla **y al
  modelo obedeciendo el texto viejo**. Verde perfecto, cero efecto: el defecto nº12.

Por eso el mutante de esta vara **no rompe el código: hace exactamente eso**. Escribe el
JSON directo, sin pasar por el endpoint, y exige que la vara se ponga roja. Si no se pusiera,
la vara no estaría midiendo el defecto que la fase vino a evitar.

QUÉ SE MIDE, Y CONTRA QUÉ
─────────────────────────
Contra el servicio de ingest REAL del stack, levantado acá, con un `WORKSPACE_ROOT` propio:

  1. después de proyectar, `drafting.md` CAMBIÓ y dice la postura nueva
  2. …y `preferences.json` también (lo relee `lib/research.ts:78-84` por llamada — 4.2)
  3. …y el merge NO borró lo que el estudio tenía (Attorney, Firm, House style)
  4. `opencode.json` sigue declarando ese markdown como `instructions`

Las cuatro juntas son la cadena entera **menos la última milla**: que el modelo lea esas
instrucciones en su próximo turno. Eso pide motor + modelo vivos y queda **[no medible]**
acá, dicho y no escondido. Lo que sí queda probado es que el texto que el motor va a leer
cambió — que es lo único que el puente puede garantizar.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "platform"))
INGEST = RAIZ / "third_party/dochaus/services/ingest"
OPENCODE_JSON = RAIZ / "third_party/dochaus/dochaus/opencode.json"
MUT = "--mutante" in sys.argv
fallos: list[str] = []


def ok(cond: bool, msg: str) -> None:
    print(f"  {'✓' if cond else '✗'} {msg}")
    if not cond:
        fallos.append(msg)


def libre() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def proxy(puerto: int, ingest: int) -> HTTPServer:
    """`/ingest/*` → el servicio, igual que `apps/web/script/serve-dist.ts:27-31`.

    Se levanta el MISMO recorrido que en producción a propósito: si el puente funcionara
    sólo apuntando derecho al servicio, no probaría el camino que va a usar."""
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # silencio
            pass

        def _pasar(self, cuerpo=None):
            if not self.path.startswith("/ingest"):
                self.send_response(404); self.end_headers(); return
            destino = f"http://127.0.0.1:{ingest}" + (self.path[len("/ingest"):] or "/")
            req = urllib.request.Request(destino, data=cuerpo, method=self.command,
                                         headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    datos, estado = r.read(), r.status
            except Exception as e:  # noqa: BLE001
                datos, estado = str(e).encode(), 502
            self.send_response(estado)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(datos)))
            self.end_headers()
            self.wfile.write(datos)

        def do_GET(self):
            self._pasar()

        def do_PUT(self):
            n = int(self.headers.get("Content-Length") or 0)
            self._pasar(self.rfile.read(n))

    srv = HTTPServer(("127.0.0.1", puerto), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main() -> int:
    if not (INGEST / "node_modules").is_dir():
        print(f"✗ falta `node_modules` de {INGEST.relative_to(RAIZ)} — corré `bun install` ahí.")
        print("  Esta vara mide contra el servicio REAL del stack: sin él no se puede afirmar")
        print("  nada, y eso es rojo, no salteado.")
        return 1
    bun = shutil.which("bun")
    if not bun:
        print("✗ falta `bun` — esta vara levanta el servicio de ingest del stack. Rojo, no salteado.")
        return 1

    raiz_ws = Path(tempfile.mkdtemp(prefix="vara-puente-legal-"))
    p_ing, p_pub = libre(), libre()
    env = {**os.environ, "INGEST_PORT": str(p_ing), "WORKSPACE_ROOT": str(raiz_ws)}
    hijo = subprocess.Popen([bun, "run", "src/server.ts"], cwd=INGEST, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    srv = None
    try:
        base = f"http://127.0.0.1:{p_ing}/preferences"
        for _ in range(80):
            try:
                urllib.request.urlopen(base, timeout=1).read()
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.25)
        else:
            print("✗ el servicio de ingest no levantó")
            return 1
        srv = proxy(p_pub, p_ing)
        url = f"http://127.0.0.1:{p_pub}"

        from workspaces import memoria, puentes

        # El estudio ya tenía cosas suyas: el merge no las puede perder.
        urllib.request.urlopen(urllib.request.Request(
            base, method="PUT", headers={"Content-Type": "application/json"},
            data=json.dumps({"attorney": "Dra. Beatriz Roldán", "firm": "Roldán & Asoc.",
                             "houseStyle": "Sin adverbios de más.",
                             "posture": "balanced"}).encode()), timeout=10).read()

        md = raiz_ws / ".preferences" / "drafting.md"
        js = raiz_ws / ".preferences" / "preferences.json"
        antes = md.read_text() if md.is_file() else ""
        ok(bool(antes), "el estudio arranca con su `drafting.md` renderizado")

        cambios = {"legal_postura": "conservative", "legal_investigacion": "open"}
        decl = memoria.declarados()

        if MUT:
            # ⚠️ LA MUTACIÓN NO ROMPE EL CÓDIGO: HACE EL PUENTE MAL, que es el defecto que
            # esta fase vino a evitar. Escribe el JSON directo, sin pasar por el endpoint.
            cuerpo = json.loads(js.read_text())
            cuerpo["posture"] = "conservative"
            cuerpo["webResearch"] = "open"
            js.write_text(json.dumps(cuerpo, indent=2) + "\n")
            parte = {"ok": True, "campos": cuerpo, "causa": "MUTADO"}
        else:
            parte = puentes.proyectar("legal", url, cambios, decl)

        ok(parte.get("ok") is True, f"el puente reporta ok (causa: {parte.get('causa') or '—'})")

        despues = md.read_text() if md.is_file() else ""
        ok(despues != antes, "`drafting.md` CAMBIÓ — que es lo único que el motor lee cada turno")
        ok("conservative" in despues.lower() or "conservador" in despues.lower()
           or "protective" in despues.lower() or "cautious" in despues.lower(),
           f"…y dice la postura nueva (fragmento: {despues.strip().splitlines()[:1]})")

        cuerpo = json.loads(js.read_text()) if js.is_file() else {}
        ok(cuerpo.get("posture") == "conservative", "`preferences.json` también quedó con la postura")
        ok(cuerpo.get("webResearch") == "open",
           "…y con `webResearch` (4.2: `lib/research.ts` lo relee por llamada)")
        ok(cuerpo.get("attorney") == "Dra. Beatriz Roldán" and cuerpo.get("firm") == "Roldán & Asoc."
           and cuerpo.get("houseStyle") == "Sin adverbios de más.",
           "el merge NO le borró al estudio lo que ya tenía")

        try:
            cfg = json.loads(OPENCODE_JSON.read_text())
            instr = cfg.get("instructions") or []
        except Exception:  # noqa: BLE001
            instr = []
        ok(any("drafting.md" in str(x) for x in instr),
           "`opencode.json` sigue declarando ese markdown como `instructions`")
    finally:
        if srv:
            srv.shutdown()
        hijo.kill()
        shutil.rmtree(raiz_ws, ignore_errors=True)

    print("")
    if MUT:
        if not fallos:
            print("✗ LA VARA ESTÁ ROTA: se escribió el JSON por atrás y no cayó nada.")
            print("  Eso es exactamente el defecto que esta fase vino a evitar, sin detectar.")
            return 1
        print(f"✓ la vara puede dar rojo: {len(fallos)} afirmaciones cayeron con el puente mal tendido.")
        return 0
    if fallos:
        print(f"✗ {len(fallos)} rojas")
        return 1
    print("✓ la perilla llega hasta el texto que el motor lee — y el merge no pisó al estudio")
    print("  ~ [no medible acá] que el modelo lo obedezca en su próximo turno: pide motor + modelo vivos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
