#!/usr/bin/env python3
"""verify_siete_piezas.py — LAS SIETE QUE ESTABAN SANAS Y SE PINTABAN ROJAS.

FIX-P1B §7 encontró tres bugs distintos en el spawn del probe, y los tres tenían el mismo
síntoma para la persona: una pieza 🔴 «no arrancó» que en realidad funcionaba perfecto.

  · `${PUPPET_BELTS}` viajaba CRUDO      → el server no encontraba su propio script.
  · el `env` propio de un belt REEMPLAZABA el ambiente → sin `PATH`, `uvx`/`npx` no existen.
  · `${PUPPET_WORKDIR}` sin default      → un directorio con ese nombre literal, donde caiga.

Siete piezas caían por alguno de los tres. Esta vara es el assert explícito de que el fix
VIAJA al árbol integrado: las siete dan VERDE, con evidencia (tools reales del handshake).

NO alcanza con «dieron verde». La lección del punto ciego del slot (T7): si una vara puede
dar 0 por vacío, hay que probar que puede dar >0. Acá eso son DOS calibraciones:

  (cal-1) cada pieza declara de verdad la variable/binario que la rompía — si un belt dejara
          de usar `${PUPPET_BELTS}`, su verde no probaría nada del fix y hay que saberlo.
  (cal-2) con la expansión APAGADA, las que dependen de `${PUPPET_BELTS}` tienen que caer.
          Si pasan igual, la vara está midiendo otra cosa.

Se mide contra el SIDECAR CONGELADO — el binario que la persona va a correr. Un verde contra
el árbol suelto no dice nada del .app.

Uso:
  python3 qa/verify_siete_piezas.py --sidecar /ruta/al/aleph_sidecar [--port 8294]
  python3 qa/verify_siete_piezas.py --url http://127.0.0.1:8294      # uno ya corriendo
"""
from __future__ import annotations

import argparse
import atexit
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

PUERTO_DEFECTO = 8294
PROHIBIDOS = {25374}          # la .app de persona usuaria. Jamás.

REPO = Path(__file__).resolve().parents[1]
BELT_GEN = "catalog/templates/generalistas/belt-generalistas.mcp.json"
BELT_FIN = "catalog/templates/finanzas/belt-finanzas-markets.mcp.json"

#: (backed_by, belt_ref, qué bug de §7 la tenía roja, marca que lo demuestra en el belt)
SIETE = (
    ("pysandbox",  BELT_GEN, "belts",   "${PUPPET_BELTS}"),
    ("wikipedia",  BELT_GEN, "belts",   "${PUPPET_BELTS}"),
    ("datatools",  BELT_GEN, "belts",   "${PUPPET_BELTS}"),
    ("backtest",   BELT_FIN, "belts",   "${PUPPET_BELTS}"),
    ("sqlite",     BELT_GEN, "workdir", "${PUPPET_WORKDIR}"),
    ("git",        BELT_GEN, "path",    "uvx"),
    ("duckduckgo", BELT_GEN, "path",    "uvx"),
)

OK = 0
FAIL = 0
FALLAS: list[str] = []
#: las que dieron verde en la corrida BUENA. La calibración 2 sólo puede contar como «caída»
#: una que antes estaba verde — si no, un arnés roto (401, sidecar muerto) la haría pasar
#: por la razón equivocada, que es exactamente el punto ciego que esta vara existe para no tener.
VERDES_BUENA: set[str] = set()


def ok(cond, label: str, det: str = "") -> bool:
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  ✓ {label}" + (f"  ({det})" if det else ""))
    else:
        FAIL += 1
        FALLAS.append(label)
        print(f"  ✗ {label}" + (f"  ({det})" if det else ""))
    return bool(cond)


def sec(t: str) -> None:
    print("\n" + "─" * 78 + f"\n{t}\n" + "─" * 78)


# ── el frozen ────────────────────────────────────────────────────────────────────────
def _libre(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _pedir(url: str, body: dict | None = None, timeout: float = 120.0,
           token: str | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    h = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return {"_http": e.code, "_body": e.read().decode("utf-8", "replace")[:400]}


def sesion(base: str) -> str:
    """El owner de una prueba SIEMPRE sale de la sesión (anti-IDOR): sin token, /probar es 401.
    Un 401 se ve igual que «la pieza está rota» si no se mira — de ahí que esto reviente."""
    r = _pedir(base + "/v1/auth/local", {}, timeout=30.0)
    tok = r.get("session_token")
    if not tok:
        raise SystemExit(f"✗ no pude abrir sesión local contra el frozen: {str(r)[:300]}")
    return tok


def _esperar(base: str, segundos: float, proc=None) -> bool:
    limite = time.time() + segundos
    while time.time() < limite:
        if proc is not None and proc.poll() is not None:
            return False
        try:
            _pedir(base + "/health", timeout=1.5)
            return True
        except Exception:
            time.sleep(0.35)
    return False


def _matar(proc) -> None:
    if proc is None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)   # el bootloader FORKEA: matar el grupo
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _levantar(binario: Path, port: int, extra_env: dict | None = None):
    while not _libre(port):
        port += 1
        if port in PROHIBIDOS:
            port += 1
    base = f"http://127.0.0.1:{port}"
    # TMPDIR propio: el onefile se descomprime entero (~170 MB) y sólo lo borra al salir
    # limpio; acá se mata con SIGKILL, así que sin esto queda huérfano SIEMPRE.
    tmp = tempfile.mkdtemp(prefix="aleph-siete-")
    atexit.register(lambda: shutil.rmtree(tmp, ignore_errors=True))
    env = dict(os.environ, ALEPH_ROLE=os.environ.get("ALEPH_ROLE", "client"),
               PUPPET_PORT=str(port), PORT=str(port), TMPDIR=tmp, **(extra_env or {}))
    proc = subprocess.Popen([str(binario), "--port", str(port)], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            start_new_session=True)
    if not _esperar(base, 90.0, proc):
        _matar(proc)
        raise SystemExit("✗ el sidecar congelado no arrancó — no hay a quién preguntarle")
    return proc, base


def probar(base: str, backed_by: str, belt_ref: str, token: str) -> dict:
    r = _pedir(base + "/v1/motor/probar",
               {"tipo": "mcp", "ref": belt_ref, "belt_ref": belt_ref,
                "backed_by": backed_by, "force": True, "motivo": "manual"}, token=token)
    if "_http" in r:      # 401/422/500 NO es «la pieza está roja»: es la vara midiendo mal
        raise SystemExit(f"✗ /probar respondió http {r['_http']} para {backed_by}: "
                         f"{r.get('_body')}\n  Eso es un fallo del arnés, no de la pieza.")
    return r


def main() -> int:
    ap = argparse.ArgumentParser(description="Las siete piezas sanas que se pintaban rojas")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--sidecar", help="ruta al binario congelado")
    g.add_argument("--url", help="sidecar YA corriendo (no lo levanta ni lo mata)")
    ap.add_argument("--port", type=int, default=PUERTO_DEFECTO)
    a = ap.parse_args()
    if a.port in PROHIBIDOS:
        raise SystemExit(f"✗ el puerto {a.port} está reservado — usá otro")

    # ── (cal-1) el belt declara de verdad lo que la rompía ───────────────────────────
    # Va ANTES de levantar nada: si esto no se cumple, el verde de abajo no prueba el fix.
    sec("CALIBRACIÓN 1 · cada pieza declara la marca del bug que la tenía roja")
    for backed_by, belt_ref, bug, marca in SIETE:
        belt = json.loads((REPO / belt_ref).read_text(encoding="utf-8"))
        entry = (belt.get("mcpServers") or {}).get(backed_by) or {}
        cmd = " ".join([entry.get("command", "")] + list(entry.get("args") or []))
        ok(marca in cmd, f"{backed_by} declara {marca} — su verde SÍ prueba el fix «{bug}»",
           cmd[:90])

    proc = None
    try:
        if a.url:
            base = a.url.rstrip("/")
        else:
            binario = Path(a.sidecar)
            if not binario.exists():
                raise SystemExit(f"✗ no existe {binario}")
            proc, base = _levantar(binario, a.port)

        # ── las siete, contra el frozen ──────────────────────────────────────────────
        sec("LAS SIETE · verdes, con evidencia (tools REALES del handshake)")
        tok = sesion(base)
        verdes = 0
        for backed_by, belt_ref, bug, _marca in SIETE:
            r = probar(base, backed_by, belt_ref, tok)
            estado = r.get("estado")
            ev = r.get("evidencia") or {}
            n = ev.get("tool_count") or 0
            tools = ", ".join((ev.get("tools") or [])[:4])
            det = (f"{n} tools · {tools}" if estado == "probado"
                   else f"estado={estado} causa={r.get('causa')} "
                        f"detail={str(ev.get('detail'))[:120]}")
            if ok(estado == "probado" and n > 0,
                  f"[{bug:7}] {backed_by} → VERDE con tools reales", det):
                verdes += 1
                VERDES_BUENA.add(backed_by)
        ok(verdes == len(SIETE), "las SIETE en verde (no 6, no 5)", f"{verdes}/{len(SIETE)}")

    finally:
        _matar(proc)

    # ── (cal-2) con `PUPPET_BELTS` mal, las cuatro que la usan tienen que CAER ────────
    # `_expandir` lee la variable con `setdefault`: si el entorno ya la trae, se respeta ésa.
    # Apuntándola a una ruta inexistente, las cuatro pierden su script. Que caigan prueba dos
    # cosas a la vez: que la expansión OCURRE (si no ocurriera, el comando sería el literal
    # `${PUPPET_BELTS}/…` y fallarían igual, pero entonces tampoco habrían dado verde arriba)
    # y que el valor que usa en la corrida buena es el que las hace andar.
    sec("CALIBRACIÓN 2 · con ${PUPPET_BELTS} mal apuntada, las 4 caen (si no, la vara miente)")
    proc2 = None
    try:
        if a.url:
            print("  · omitida: con --url no puedo cambiarle el entorno al proceso ajeno")
        else:
            proc2, base2 = _levantar(Path(a.sidecar), a.port + 1,
                                     {"PUPPET_BELTS": "/no/existe/este/arbol"})
            tok2 = sesion(base2)
            # sólo cuenta como «caída» una que estaba VERDE en la corrida buena: si el arnés
            # se rompe, esto da 0 y la calibración falla — no pasa por accidente.
            esperadas = [x for x in SIETE if x[2] == "belts" and x[0] in VERDES_BUENA]
            caidas = 0
            for backed_by, belt_ref, _bug, _m in esperadas:
                r = probar(base2, backed_by, belt_ref, tok2)
                if r.get("estado") != "probado":
                    caidas += 1
                else:
                    print(f"     ⚠ {backed_by} pasó igual con la ruta rota")
            ok(len(esperadas) == 4 and caidas == 4,
               "las 4 de ${PUPPET_BELTS} caen con la ruta rota",
               f"{caidas} caídas de {len(esperadas)} que estaban verdes")
    finally:
        _matar(proc2)

    # [H3] El detalle de las fallas y la barra van ARRIBA; la ÚLTIMA línea es el veredicto.
    print("\n" + "═" * 78)
    if FALLAS:
        for f in FALLAS:
            print(f"   ✗ {f}")
    print(f"RESULTADO: {OK} ✓   {FAIL} ✗")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
