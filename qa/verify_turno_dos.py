#!/usr/bin/env python3
"""verify_turno_dos — ¿EL SEGUNDO TURNO REUSA LA SESIÓN, O RE-MANDA TODO?

LA PREGUNTA. El harness de un stack manda el HISTORIAL COMPLETO en cada paso. Si el CLI
de abajo reabre su sesión, ese historial cae sobre un prefijo que ya está en disco y se
lee del caché; si no, se re-renderiza entero, y el costo del turno N crece con N.

CÓMO SE MIDE, Y LA TRAMPA QUE HAY QUE ESQUIVAR. No alcanza con repetir un pedido: la
clave de conversación del borde (`router._clave_de_conversacion`) incluye `_hilo_de`, que
hashea **el primer mensaje humano**. Dos pedidos con preguntas distintas son dos
conversaciones distintas por definición, así que una vara que varía el prompt para no
pegarle al caché de respuesta **se saca sola el resume que venía a medir** — le pasó a
`verify_primer_texto`, que reportó `cache_read=0` para tres stacks y eso era cierto de la
vara y falso del producto.

Acá el turno 2 es la CONTINUACIÓN del turno 1 —mismo primer mensaje humano, más la
respuesta, más una pregunta nueva— que es exactamente lo que manda un harness real.

    turno 1   [user Q1]
    turno 2   [user Q1, assistant A1, user Q2]     ← mismo `#hilo`, misma sesión

VEREDICTO: `cache_read` del turno 2 > 0 es prefijo reusado. Cero es `sesion=None`.

⚠️ `cache_read` SÓLO CRUZA EN STREAMING `real` (medido: en `emulado` el sobre `usage` sale
`{prompt_tokens, completion_tokens, total_tokens}` y nada más). Contra un borde en
`emulado` esta vara no puede ver el dato y lo dice: [no medible], no cero.

Uso:
    python3 qa/verify_turno_dos.py --puerto 8331
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from verify_primer_texto import LECTORES                      # noqa: E402

Q1 = "Explicá en 3 oraciones qué es la refracción de la luz."
Q2 = "Ahora, en 3 oraciones más, contame qué es la reflexión total interna."


def _pedir(base, key, cab, modelo, mensajes, plazo=300.0):
    url = base.rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        url, method="POST",
        data=json.dumps({"model": modelo, "stream": True, "messages": mensajes}).encode(),
        headers={**cab, "Authorization": "Bearer " + key,
                 "Content-Type": "application/json", "Accept": "text/event-stream"})
    t0 = time.perf_counter()
    texto, usage, t1 = [], None, None
    try:
        resp = urllib.request.urlopen(req, timeout=plazo)
    except Exception as e:                                     # noqa: BLE001
        return {"error": str(e)[:120], "t_total": time.perf_counter() - t0}
    with resp:
        for cruda in resp:
            linea = cruda.decode("utf8", "replace").strip()
            if not linea.startswith("data:"):
                continue
            p = linea[5:].strip()
            if p == "[DONE]":
                break
            try:
                d = json.loads(p)
            except Exception:                                  # noqa: BLE001
                continue
            if isinstance(d.get("usage"), dict):
                usage = d["usage"]
            for ch in (d.get("choices") or []):
                c = ((ch.get("delta") or {}).get("content")) or ""
                if c:
                    if t1 is None:
                        t1 = time.perf_counter() - t0
                    texto.append(c)
    return {"t_1er_texto": t1, "t_total": time.perf_counter() - t0,
            "texto": "".join(texto), "usage": usage}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ws", default=",".join(LECTORES))
    ap.add_argument("--puerto", default="")
    ap.add_argument("--como-plugin", action="store_true")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    salida, filas = {}, []
    for ws in [w.strip() for w in args.ws.split(",") if w.strip()]:
        if ws not in LECTORES:
            continue
        try:
            base, key, cab, modelo = LECTORES[ws]()
        except Exception as e:                                 # noqa: BLE001
            print("  ⚪ %-10s [no medible] config ilegible: %s" % (ws, str(e)[:60]))
            continue
        if args.como_plugin:
            cab.setdefault("X-Aleph-Space", "space-ws-%s-varaturnodos" % ws)
            cab.setdefault("X-Aleph-Chat", "vara-turno-dos-%s" % ws)
        if args.puerto:
            base = re.sub(r"//127\.0\.0\.1:\d+", "//127.0.0.1:" + args.puerto, base)

        t1 = _pedir(base, key, cab, modelo, [{"role": "user", "content": Q1}])
        if t1.get("error"):
            print("  ❌ %-10s turno 1: %s" % (ws, t1["error"])); continue
        t2 = _pedir(base, key, cab, modelo,
                    [{"role": "user", "content": Q1},
                     {"role": "assistant", "content": t1["texto"]},
                     {"role": "user", "content": Q2}])
        salida[ws] = {"t1": {k: v for k, v in t1.items() if k != "texto"},
                      "t2": {k: v for k, v in t2.items() if k != "texto"}}
        filas.append((ws, t1, t2))

    print("\n%-11s %-28s %-28s %s"
          % ("workspace", "turno 1 (1er txt / total)", "turno 2 (1er txt / total)",
             "cache_read t2"))
    print("─" * 92)
    for ws, t1, t2 in filas:
        u2 = t2.get("usage") or {}
        # ⚠️ EL CAMPO TIENE DOS NOMBRES SEGÚN QUIÉN ARMA EL SOBRE. `cli_brain.base` lo
        # normaliza a `cache_read_tokens`; el sobre OpenAI del borde lo publica en
        # `prompt_tokens_details.cached_tokens`, que es donde lo busca un cliente OpenAI.
        # Mirar uno solo hizo que esta vara dijera «no medible» sobre un dato que SÍ estaba
        # en el cable — se corrige acá en vez de dejarlo como una ausencia falsa.
        cr = u2.get("cache_read_tokens")
        if cr is None and isinstance(u2.get("prompt_tokens_details"), dict):
            cr = u2["prompt_tokens_details"].get("cached_tokens")
        if cr is None:
            v = "⚪ [no medible] el sobre no trae caché (¿borde en `emulado`?)"
        elif cr > 0:
            v = "✅ %d — prefijo REUSADO" % cr
        else:
            v = "❌ 0 — sin resume, historial entero"
        def f(t):
            a = t.get("t_1er_texto")
            return "%8s / %6.2f s" % ("—" if a is None else "%.2f s" % a, t.get("t_total", 0))
        _cc = (u2.get("cache_creation_input_tokens")
               or u2.get("cache_write_tokens") or 0)
        print("%-11s %-28s %-28s %s" % (ws, f(t1), f(t2), v + ("  (+%d nuevos)" % _cc if _cc else "")))
    if args.json:
        open(args.json, "w").write(json.dumps(salida, indent=1))
        print("\n→ %s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
