#!/usr/bin/env python3
"""verify_borde_caudal — ¿el cerebro CONECTA, o además RESPONDE?

POR QUÉ EXISTE ESTA SONDA, Y CONTRA QUÉ SONDA ES.
--------------------------------------------------
La sonda que veníamos usando para decir «el borde está sano» era ésta:

    POST …/chat/completions  {"messages":[{"role":"user","content":"decí PONG"}]}
    → HTTP 200 en ~9 s  ✅

Se usó dos veces el 2026-08-15 para declarar sano un borde que en ese mismo momento no
podía atender un turno real. **Mide que el puerto contesta, no que el cerebro trabaja**, y
un «decí PONG» es justamente el único pedido que un CLI resuelve sin pensar.

Medido ese día, mismo borde, mismo minuto, en serie:

    tarea trivial («decí PONG»)                          3/3 OK   7,1-9,9 s
    tarea que exige pensar, con max_tokens=4             0/3 OK   muere a 8,2-8,5 s

O sea que el disparador **no es el tamaño de la salida** —el tope de 4 tokens falla igual—
sino **cuánto tarda el CLI en emitir su primera línea**. Si tarda más que
`STREAM_CHUNK_TIMEOUT` (`platform/assembler/cli_brain/base.py`), el watchdog lo declara
muerto y el turno se cae con `cli_timeout`.

QUÉ HACE ESTA SONDA DISTINTO
-----------------------------
1. Pide DOS cosas por CLI: una trivial (¿conecta?) y una que obliga a pensar (¿responde?).
2. No juzga por el código HTTP: mira que haya CONTENIDO de vuelta.
3. Da rojo cuando el trabajo real falla aunque el trivial ande — que es exactamente el
   estado que la sonda vieja no podía ver.
4. Distingue las dos capas: el borde de Aleph (`:8330`) y el servicio de CLIs (`:8926`),
   para que el veredicto diga en cuál de las dos se rompe.

Uso:
    python3 qa/verify_borde_caudal.py            # contra la .app corriendo
    python3 qa/verify_borde_caudal.py --muestras 5
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

#: Trivial: un CLI la resuelve sin pensar. Si ESTO falla, no hay cerebro.
PROMPT_CONECTA = "decí PONG"
#: Exige planificar antes de emitir. Es la que destapa el watchdog.
PROMPT_RESPONDE = (
    "Escribí un texto continuo sobre principios de diseño visual. "
    "No pares hasta cubrir tipografía, color, espaciado y jerarquía."
)

_CFG_DISENO = (Path.home() / "Library/Application Support/Aleph/workspaces/diseno/"
               "config/open-codesign/config.toml")
_TOKEN_CLIS = Path.home() / "Library/Application Support/Aleph/cli_brain.token"


def _cabeceras_borde() -> tuple[str, dict[str, str]] | None:
    """La credencial del borde sale de la config que el pack le escribió a un workspace."""
    if not _CFG_DISENO.is_file():
        return None
    t = _CFG_DISENO.read_text(errors="replace")
    try:
        base = re.search(r'baseUrl = "([^"]+)"', t).group(1)          # type: ignore[union-attr]
        cab = {"Authorization": "Bearer "
               + re.search(r'Authorization = "Bearer ([^"]+)"', t).group(1)}  # type: ignore[union-attr]
        for clave, patron in (("X-Aleph-Space", r'X-Aleph-Space = "([^"]+)"'),
                              ("X-Aleph-User", r'X-Aleph-User = "([^"]+)"')):
            m = re.search(patron, t)
            if m:
                cab[clave] = m.group(1)
    except AttributeError:
        return None
    return base.rstrip("/") + "/chat/completions", cab


def _cabeceras_clis() -> dict[str, str]:
    if _TOKEN_CLIS.is_file():
        return {"Authorization": "Bearer " + _TOKEN_CLIS.read_text().strip()}
    return {}


def pedir(url: str, cab: dict[str, str], modelo: str, prompt: str,
          plazo: float = 240.0) -> dict:
    cuerpo = {"model": modelo, "messages": [{"role": "user", "content": prompt}],
              "stream": False}
    req = urllib.request.Request(url, data=json.dumps(cuerpo).encode(),
                                 headers={**cab, "Content-Type": "application/json"},
                                 method="POST")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=plazo) as r:
            d = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        b = e.read().decode("utf8", "replace")
        causa = b[:70]
        try:
            err = json.loads(b)
            err = err.get("detail", err).get("error", err)
            causa = "%s · %s" % (err.get("code") or err.get("type"),
                                 (err.get("message") or "")[:70])
        except Exception:                                            # noqa: BLE001
            pass
        return {"ok": False, "s": time.time() - t0, "estado": e.code, "causa": causa}
    except Exception as e:                                           # noqa: BLE001
        return {"ok": False, "s": time.time() - t0, "estado": "exc", "causa": str(e)[:70]}
    # NO SE JUZGA POR EL CÓDIGO: un 200 con el contenido vacío no es una respuesta.
    texto = ((d.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    deg = (d.get("aleph") or {}).get("degradado") or (d.get("aleph") or {}).get("degraded")
    return {"ok": len(texto.strip()) > 0, "s": time.time() - t0, "estado": 200,
            "chars": len(texto), "modelo": d.get("model"),
            "degradado": (deg or {}).get("actual_model"),
            "causa": "" if texto.strip() else "200 con contenido VACÍO"}


def tanda(titulo: str, url: str, cab: dict[str, str], modelo: str, n: int) -> dict:
    print("\n── %s ──" % titulo, flush=True)
    salida = {}
    for etiqueta, prompt in (("CONECTA (trivial)", PROMPT_CONECTA),
                             ("RESPONDE (pensar)", PROMPT_RESPONDE)):
        buenas, tiempos, causas = 0, [], []
        for _ in range(n):
            r = pedir(url, cab, modelo, prompt)
            tiempos.append(r["s"])
            if r["ok"]:
                buenas += 1
            else:
                causas.append("%s %s" % (r["estado"], r["causa"]))
        marca = "✅" if buenas == n else ("⚠️" if buenas else "❌")
        print("   %s %-20s %d/%d   %.1f-%.1f s%s"
              % (marca, etiqueta, buenas, n, min(tiempos), max(tiempos),
                 "   " + causas[0] if causas else ""))
        salida[etiqueta] = (buenas, n, causas)
    return salida


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--muestras", type=int, default=3)
    args = ap.parse_args()

    print("verify_borde_caudal · ¿conecta, o además responde?")
    resultados = {}

    borde = _cabeceras_borde()
    if borde is None:
        print("\n⏳ NO MEDIBLE · el borde — no hay config de un workspace en disco.\n"
              "   Entrá una vez a Diseño para que el pack la escriba.")
    else:
        url, cab = borde
        resultados["borde"] = tanda("A · el BORDE de Aleph (el que ve un workspace)",
                                    url, cab, "aleph-workspace", args.muestras)

    cab_clis = _cabeceras_clis()
    try:
        with urllib.request.urlopen("http://127.0.0.1:8926/v1/models", timeout=5) as r:
            modelos = [m.get("id") for m in (json.loads(r.read().decode()).get("data") or [])]
    except Exception:                                                # noqa: BLE001
        modelos = []
    if not modelos:
        print("\n⏳ NO MEDIBLE · el servicio de CLIs (:8926) no contesta su lista de modelos.")
    for modelo in modelos:
        resultados[modelo] = tanda("B · el CLI `%s` (:8926)" % modelo,
                                   "http://127.0.0.1:8926/v1/chat/completions",
                                   cab_clis, modelo, args.muestras)

    print("\n══ VEREDICTO ══")
    if not resultados:
        print("  ⏳ NO MEDIBLE — no se pudo alcanzar ninguna capa. No es un verde.")
        return 2
    rojo = False
    for capa, r in resultados.items():
        con = r["CONECTA (trivial)"][0]
        res = r["RESPONDE (pensar)"][0]
        if con and not res:
            rojo = True
            print("  ❌ %-16s CONECTA pero NO RESPONDE — es el estado que la sonda vieja"
                  " no veía." % capa)
            print("     Si la causa dice `cli_timeout`, el que corta es NUESTRO watchdog"
                  " (`STREAM_CHUNK_TIMEOUT`, base.py), no el proveedor.")
        elif not con:
            rojo = True
            print("  ❌ %-16s ni siquiera conecta." % capa)
        else:
            print("  ✅ %-16s conecta y responde." % capa)
    return 1 if rojo else 0


if __name__ == "__main__":
    raise SystemExit(main())
