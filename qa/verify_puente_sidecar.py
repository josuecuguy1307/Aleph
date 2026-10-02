#!/usr/bin/env python3
"""verify_puente_sidecar.py — LA VARA DEL PUENTE: que lo sirva el sidecar, no el python3 ajeno.

    python3 qa/verify_puente_sidecar.py [--nuevo <sidecar construido>]

──────────────────────────────────────────────────────────────────────────────────────────
QUÉ MIDE

Obra 6a hizo viajar `byo_mcp_server.py` y NO alcanzó: lo corre el `python3` del SISTEMA, que
no puede leer el PYZ del binario congelado, así que muere en `from inspection import
transporte`. Medido: las dos filas HTTP del usuario siguieron rotas con `causa: arranque`.

Acá el puente lo sirve el propio sidecar (`--byo-mcp <manifest>`). Los testigos:

  1 · suelto NO se toca            — el árbol de desarrollo sigue corriendo el script
  2 · congelado traduce            — y sólo el puente
  3 · no toca comandos ajenos      — npx/uvx/otro script quedan intactos (regla estrecha)
  4 · el binario nuevo ATIENDE     — `--byo-mcp` habla MCP de verdad contra un HTTP real
  5 · stdout limpio                — ni una línea nuestra antes del JSON-RPC
  6 · el negativo                  — sin la traducción, el mismo manifest NO arranca

⚠️ EL TESTIGO 6 ES EL QUE VALE. Un arreglo que nunca se probó contra el fallo que dice
arreglar no probó nada: se corre el camino VIEJO (python3 + el script) dentro de un entorno
sin el cierre, y tiene que fallar. Si no falla, el testigo 4 no está midiendo el arreglo.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "platform"))

FALLOS: list[str] = []
RESULTADO: dict[str, object] = {}


def ok(nombre: str, cond: bool, detalle=None) -> bool:
    RESULTADO[nombre] = bool(cond)
    print(("✅ " if cond else "❌ ") + nombre + (f": {detalle}" if detalle is not None else ""))
    if not cond:
        FALLOS.append(nombre)
    return bool(cond)


def no_medible(nombre: str, motivo: str) -> None:
    RESULTADO[nombre] = "NO_MEDIBLE"
    print(f"⚪ {nombre}: NO MEDIBLE — {motivo}")
    FALLOS.append(f"{nombre} (no medible)")


PUENTE = ["python3", "${PUPPET_REPO}/platform/inspection/byo_mcp_server.py", "/x/manifest.json"]

#: Un MCP HTTP público, keyless y de LECTURA PURA, para que el puente tenga con quién hablar.
#: Constante declarada (contrato del repo §1: territorio propio o constante neutra), medida
#: viva el 2026-08-06. Si el día de mañana no responde, el testigo se declara NO MEDIBLE —
#: jamás verde por omisión.
URL_PRUEBA = "https://base.datakoot.com/mcp"


def _hablar_mcp(cmd: list[str], manifest: Path, timeout: float = 90.0) -> dict:
    """Lanza `cmd` como server MCP stdio y hace el saludo + tools/list. Devuelve el veredicto."""
    env = dict(os.environ, BYO_MCP_MANIFEST=str(manifest))
    try:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, env=env)
    except Exception as e:  # noqa: BLE001
        return {"arranco": False, "error": f"{type(e).__name__}: {e}"}
    pedido = (json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                          "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                                     "clientInfo": {"name": "vara", "version": "1"}}}) + "\n"
              + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
              + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n")
    try:
        out, err = p.communicate(pedido, timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        return {"arranco": False, "error": "timeout"}
    lineas = [l for l in (out or "").splitlines() if l.strip()]
    respuestas, basura = [], []
    for l in lineas:
        try:
            respuestas.append(json.loads(l))
        except json.JSONDecodeError:
            basura.append(l[:80])
    tools = []
    for r in respuestas:
        if r.get("id") == 2 and isinstance(r.get("result"), dict):
            tools = [t.get("name") for t in (r["result"].get("tools") or [])]
    return {"arranco": bool(respuestas), "tools": tools, "basura_en_stdout": basura,
            "stderr": (err or "")[-260:], "rc": p.returncode}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nuevo", help="sidecar construido desde esta rama")
    a = ap.parse_args()

    import puente_sidecar as P
    print("═" * 90)
    print("VARA DEL PUENTE · que lo sirva el sidecar")
    print("═" * 90)

    # ── 1 · suelto no se toca ───────────────────────────────────────────────────────────
    frozen_previo = getattr(sys, "frozen", None)
    if hasattr(sys, "frozen"):
        del sys.frozen
    ok("1_suelto_no_se_toca", P.normalizar_cmd(PUENTE) == PUENTE,
       {"cmd": P.normalizar_cmd(PUENTE)[:2]})

    # ── 2 y 3 · congelado traduce, y sólo el puente ─────────────────────────────────────
    sys.frozen = True
    exe_previo = sys.executable
    sys.executable = str(RAIZ)  # una ruta que existe; sólo importa la FORMA del resultado
    t = P.normalizar_cmd(PUENTE)
    ok("2_congelado_traduce",
       t[0] == str(RAIZ) and t[1] == P.FLAG and t[2] == PUENTE[2] and len(t) == 3, {"cmd": t})
    ajenos = [["npx", "-y", "@algo/mcp"], ["uvx", "mcp-server-time"],
              ["python3", "/x/otro_server.py", "a"], ["docker", "run", "-i", "x"]]
    ok("3_no_toca_comandos_ajenos",
       all(P.normalizar_cmd(c) == c for c in ajenos) and P.normalizar_cmd(t) == t,
       {"probados": len(ajenos), "idempotente": True})
    sys.executable = exe_previo
    if frozen_previo is None:
        del sys.frozen
    else:
        sys.frozen = frozen_previo

    # ── 4/5/6 · contra el binario de verdad ─────────────────────────────────────────────
    nuevo = Path(a.nuevo) if a.nuevo else None
    if not nuevo or not nuevo.exists():
        for n in ("4_el_binario_atiende", "5_stdout_limpio", "6_negativo_el_camino_viejo_falla"):
            no_medible(n, "no se pasó --nuevo (o no existe)")
    else:
        tmp = Path(tempfile.mkdtemp(prefix="aleph-puente-vara-"))
        manifest = tmp / "manifest.json"
        manifest.write_text(json.dumps({"url": URL_PRUEBA, "label": "vara"}), encoding="utf-8")

        v = _hablar_mcp([str(nuevo), P.FLAG, str(manifest)], manifest)
        if not v["arranco"] and "timeout" in str(v.get("error", "")):
            no_medible("4_el_binario_atiende", f"{URL_PRUEBA} no respondió a tiempo")
            no_medible("5_stdout_limpio", "sin diálogo que mirar")
        else:
            ok("4_el_binario_atiende", v["arranco"] and len(v.get("tools") or []) > 0,
               {"tools": (v.get("tools") or [])[:6], "rc": v.get("rc"),
                "stderr": v.get("stderr", "")[-120:]})
            ok("5_stdout_limpio", not v.get("basura_en_stdout"),
               {"lineas_no_json_en_stdout": v.get("basura_en_stdout")})

        # ── 6 · EL NEGATIVO: el camino viejo, en un entorno sin el cierre del puente ─────
        # Se corre `python3 <script>` con un PYTHONPATH que NO tiene `platform/`, que es
        # exactamente la situación adentro del .app. Tiene que fallar.
        script = RAIZ / "platform" / "inspection" / "byo_mcp_server.py"
        env_pelado = dict(os.environ, PYTHONPATH="", PYTHONHOME="")
        vacio = Path(tempfile.mkdtemp(prefix="aleph-sin-cierre-"))
        copia = vacio / "byo_mcp_server.py"
        copia.write_text(script.read_text(encoding="utf-8"), encoding="utf-8")
        try:
            p = subprocess.run(["python3", str(copia), str(manifest)], input="",
                               capture_output=True, text=True, timeout=60, env=env_pelado)
            fallo = p.returncode != 0 or "ImportError" in (p.stderr or "") \
                or "ModuleNotFoundError" in (p.stderr or "")
            ok("6_negativo_el_camino_viejo_falla", fallo,
               {"rc": p.returncode, "stderr": (p.stderr or "").strip()[-160:]})
        except subprocess.TimeoutExpired:
            ok("6_negativo_el_camino_viejo_falla", False, {"error": "no murió: quedó colgado"})

    print()
    print("═" * 90)
    print("MEDIDO=" + json.dumps(RESULTADO, ensure_ascii=False))
    if FALLOS:
        print(f"\n❌ verify_puente_sidecar: {len(FALLOS)} sin verde → {FALLOS}")
        return 1
    print("\n✅ verify_puente_sidecar: TODO VERDE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
