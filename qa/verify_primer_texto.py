#!/usr/bin/env python3
"""verify_primer_texto — EL RELOJ DEL PRIMER TEXTO VISIBLE, por workspace.

QUÉ MIDE Y POR QUÉ NO ALCANZA CON EL TOTAL
-------------------------------------------
Un turno puede tardar 8 s y sentirse instantáneo si el texto empieza a salir al segundo,
o tardar los mismos 8 s y sentirse roto si aparece todo junto al final. El total no
distingue esos dos mundos. Esta vara cronometra el borde de dialecto
(`POST /v1/workspaces/brain/openai/chat/completions` con `stream:true`) y anota CUATRO
instantes del MISMO pedido:

    t_cabeceras   el 200 y los headers          (¿el transporte contesta?)
    t_1er_chunk   el primer `data:` del SSE     (¿arrancó el stream?)
    t_1er_texto   el primer `delta.content` NO VACÍO   ← EL QUE IMPORTA
    t_fin         el `[DONE]`

LA FIRMA DEL ACUMULADOR es `t_1er_texto ≈ t_fin`: el borde esperó la respuesta entera y
recién ahí fabricó los chunks. Con streaming de verdad hay separación entre los dos.

DE DÓNDE SALEN LAS CABECERAS: de la config que el pack le ESCRIBIÓ a cada workspace, no
de una lista acá adentro. Si el stack manda `X-Aleph-Chat` esta vara lo manda; si no lo
manda, tampoco. Medir con cabeceras inventadas mide un camino que nadie recorre.

Uso:
    python3 qa/verify_primer_texto.py                    # los cinco, 1 muestra
    python3 qa/verify_primer_texto.py --n 2 --ws ciencia,legal
    python3 qa/verify_primer_texto.py --json /tmp/antes.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time

BASE = pathlib.Path.home() / "Library/Application Support/Aleph/workspaces"

#: Obliga a producir varias frases: con una respuesta de un token no hay stream que medir.
#:
#: ⚠️ EL NONCE NO ES DECORACIÓN. Con el prompt FIJO, la primera corrida de Ciencia dio
#: 796 chars en 0,09 s — noventa milisegundos no los produce ningún CLI. Era el pedido
#: anterior volviendo de algún caché, y habría entrado a la tabla como un verde. Cada
#: corrida pide algo que nunca se pidió; si igual vuelve en 90 ms, ESO sí es un hallazgo.
_TEMAS = ["la difracción de la luz", "la tensión superficial", "el efecto Doppler",
          "la capilaridad", "la refracción en un prisma", "el empuje de Arquímedes",
          "la resonancia acústica", "la dilatación térmica"]


def _prompt(i: int) -> str:
    return ("Explicá en 4 oraciones qué es %s. "
            "Escribí las 4 oraciones completas, sin listas." % _TEMAS[i % len(_TEMAS)])

#: Éxito según el encargo: el primer texto se ve antes de los 2 s.
TOPE_S = 2.0


def _cfg_ciencia():
    d = json.loads((BASE / "ciencia/config/openscience.json").read_text())
    o = d["provider"]["aleph"]["options"]
    return o["baseURL"], o["apiKey"], dict(o.get("headers") or {}), "aleph/cerebro"


def _cfg_opencode(ws: str, rel: str):
    d = json.loads((BASE / rel).read_text())
    o = d["provider"]["aleph"]["options"]
    return o["baseURL"], o["apiKey"], dict(o.get("headers") or {}), "aleph/cerebro"


def _cfg_educacion():
    d = json.loads((BASE / "educacion/runtime/data/user/settings/model_catalog.json").read_text())
    p = d["services"]["llm"]["profiles"][0]
    return p["base_url"], p["api_key"], dict(p.get("extra_headers") or {}), p["models"][0]["model"]


def _cfg_finanzas():
    t = (BASE / "finanzas/data/.env").read_text()
    def g(k):
        m = re.search(rf"^{k}=(.*)$", t, re.M)
        return m.group(1).strip() if m else ""
    cab = {}
    for linea in (g("OPENAI_CUSTOM_HEADERS") or "").split("\\n"):
        if ":" in linea:
            k, v = linea.split(":", 1)
            cab[k.strip()] = v.strip()
    return g("OPENAI_BASE_URL"), g("OPENAI_API_KEY"), cab, "aleph/cerebro"


LECTORES = {
    "ciencia":   _cfg_ciencia,
    "legal":     lambda: _cfg_opencode("legal", "legal/config/opencode.json"),
    "oficina":   lambda: _cfg_opencode("oficina", "oficina/config/runtime-opencode-config.json"),
    "educacion": _cfg_educacion,
    "finanzas":  _cfg_finanzas,
}


def una_corrida(base: str, key: str, cab: dict, modelo: str, i: int = 0,
                plazo: float = 300.0) -> dict:
    """Un pedido con `stream:true`, cronometrado chunk por chunk."""
    import urllib.request
    url = base.rstrip("/") + "/chat/completions"
    cuerpo = json.dumps({"model": modelo, "stream": True,
                         "messages": [{"role": "user", "content": _prompt(i)}]}).encode()
    req = urllib.request.Request(
        url, data=cuerpo, method="POST",
        headers={**cab, "Authorization": "Bearer " + key,
                 "Content-Type": "application/json", "Accept": "text/event-stream"})
    # LOS TRES CAMPOS QUE EL COMENTARIO DE `ModoStream` ACUSÓ EN 2026-08-14, MEDIDOS.
    # La rama `real` se apagó porque el turno volvía vacío y se anotaron tres sospechosos:
    # el chunk inicial con `choices: []`, el `model` VACÍO en todos los chunks y que NO
    # viajara el chunk de `usage`. Dos ya se ven arreglados leyendo el código; leer no es
    # medir, así que la vara los mira en el cable y lo dice.
    r = {"chunks": 0, "chars": 0, "t_cab": None, "t_1er_chunk": None,
         "t_1er_texto": None, "t_fin": None, "estado": None, "causa": "",
         "modelos_delta": [], "modelo_usage": None, "usage": None,
         "t_1er_razon": None,
         "finish": None, "done": False}
    t0 = time.perf_counter()
    try:
        resp = urllib.request.urlopen(req, timeout=plazo)
    except Exception as e:                                     # noqa: BLE001
        cuerpo_err = ""
        try:
            cuerpo_err = e.read().decode("utf8", "replace")[:200]   # type: ignore[attr-defined]
        except Exception:                                      # noqa: BLE001
            pass
        r["estado"] = getattr(e, "code", "exc")
        r["causa"] = (cuerpo_err or str(e))[:200]
        r["t_fin"] = time.perf_counter() - t0
        return r
    r["estado"] = resp.status
    r["t_cab"] = time.perf_counter() - t0
    # Lectura línea a línea: `readline` sobre la respuesta NO bufferiza el cuerpo entero.
    with resp:
        for cruda in resp:
            ahora = time.perf_counter() - t0
            linea = cruda.decode("utf8", "replace").strip()
            if not linea.startswith("data:"):
                continue
            payload = linea[5:].strip()
            if payload == "[DONE]":
                r["done"] = True
                break
            r["chunks"] += 1
            if r["t_1er_chunk"] is None:
                r["t_1er_chunk"] = ahora
            try:
                d = json.loads(payload)
            except Exception:                                  # noqa: BLE001
                continue
            for ch in (d.get("choices") or []):
                raz = ((ch.get("delta") or {}).get("reasoning_content")
                       or (ch.get("delta") or {}).get("reasoning") or "")
                if raz and r.get("t_1er_razon") is None:
                    r["t_1er_razon"] = ahora
            if isinstance(d.get("usage"), dict):
                r["usage"] = d["usage"]
                r["modelo_usage"] = d.get("model")
            for ch in (d.get("choices") or []):
                if ch.get("finish_reason"):
                    r["finish"] = ch["finish_reason"]
                txt = ((ch.get("delta") or {}).get("content")) or ""
                if txt:
                    r["chars"] += len(txt)
                    m = d.get("model")
                    if m not in r["modelos_delta"]:
                        r["modelos_delta"].append(m)
                    if r["t_1er_texto"] is None:
                        r["t_1er_texto"] = ahora
    r["t_fin"] = time.perf_counter() - t0
    if not r["chars"]:
        r["causa"] = r["causa"] or "stream SIN texto (0 chars en delta.content)"
    return r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ws", default=",".join(LECTORES))
    ap.add_argument("--n", type=int, default=1)
    ap.add_argument("--json", default="")
    # A/B CONTRA OTRO BORDE. La bandera `ALEPH_BRAIN_STREAM_*` la lee el proceso que sirve
    # el borde, así que comparar `emulado` con `real` es comparar DOS procesos. Se le cambia
    # el puerto a la config que el pack escribió y todo lo demás —token, cabeceras, modelo—
    # queda igual: la única variable entre las dos columnas es la bandera.
    ap.add_argument("--puerto", default="", help="reapunta el baseURL a 127.0.0.1:<puerto>")
    # ⚠️ SIN ESTO LA SONDA MIDE UN CAMINO QUE NADIE RECORRE, PARA TRES DE LOS CINCO.
    # Ciencia, Legal y Oficina NO llevan `X-Aleph-Space`/`Chat` en el archivo de config: se
    # los pone su PLUGIN en vivo (`openscience.js:329-331`, `chat.headers`). Leyendo sólo el
    # archivo, la escalera de sesión se queda sin peldaño y la sonda reporta `cache_read=0`
    # para los tres — que es cierto de la sonda y FALSO del producto. Con `--como-plugin` se
    # agregan esas cabeceras, estables entre corridas, que es lo que hace la conversación.
    ap.add_argument("--como-plugin", action="store_true",
                    help="agrega X-Aleph-Space/Chat/Turn como los inyecta el plugin")
    args = ap.parse_args()

    filas, salida = [], {}
    _sem = 0
    for ws in [w.strip() for w in args.ws.split(",") if w.strip()]:
        if ws not in LECTORES:
            print("  ?  %-10s workspace desconocido" % ws); continue
        try:
            base, key, cab, modelo = LECTORES[ws]()
        except Exception as e:                                 # noqa: BLE001
            print("  ⚪ %-10s [no medible] no pude leer su config: %s" % (ws, str(e)[:70]))
            salida[ws] = {"no_medible": str(e)[:120]}
            continue
        if getattr(args, "como_plugin", False):
            cab.setdefault("X-Aleph-Space", "space-ws-%s-varaprimertexto" % ws)
            cab.setdefault("X-Aleph-Chat", "vara-primer-texto-%s" % ws)
            cab.setdefault("X-Aleph-Turn", "1")
        if args.puerto:
            base = re.sub(r"//127\.0\.0\.1:\d+", "//127.0.0.1:" + args.puerto, base)
        corridas = [una_corrida(base, key, cab, modelo, _sem + k)
                    for k in range(args.n)]
        salida[ws] = {"cabeceras": sorted(cab), "modelo": modelo, "corridas": corridas}
        _sem += args.n
        for c in corridas:
            filas.append((ws, c))

    print("\n%-11s %6s %8s %9s %9s %8s %7s  %s"
          % ("workspace", "HTTP", "t_cab", "1er_chunk", "1er_TEXTO", "t_fin", "chars", "veredicto"))
    print("─" * 92)
    for ws, c in filas:
        def f(v):
            return "  —  " if v is None else "%5.2f" % v
        if c["t_1er_texto"] is None:
            v = "❌ sin texto · %s" % c["causa"][:40]
        elif c["t_1er_texto"] <= TOPE_S:
            v = "✅ <%.0fs" % TOPE_S
        elif c["t_fin"] and (c["t_fin"] - c["t_1er_texto"]) < 0.25:
            v = "❌ ACUMULADO (1er texto = fin, Δ%.2fs)" % (c["t_fin"] - c["t_1er_texto"])
        else:
            v = "⚠️ %.2fs > %.0fs" % (c["t_1er_texto"], TOPE_S)
        _pr = c.get("t_1er_razon")
        print("%-11s %6s %8s %9s %9s %8s %7d  %s%s"
              % (ws, c["estado"], f(c["t_cab"]), f(c["t_1er_chunk"]),
                 f(c["t_1er_texto"]), f(c["t_fin"]), c["chars"], v,
                 "" if _pr is None else "  · 1er razonamiento %.2fs" % _pr))
    # EL SOBRE DEL TURNO. Las cuatro columnas de la derecha son las que apagaron la rama
    # `real` en 2026-08-14 («finish=unknown · tokens input=0 · sin part de texto») y la que
    # dice si la SESIÓN se reusó: `cache_read` > 0 es prefijo reusado, o sea que el turno
    # no volvió a mandar el historial entero. Cero es la firma de `sesion=None`.
    print("\n%-11s %-9s %6s %9s %9s  %-22s %s"
          % ("workspace", "finish", "DONE", "tok_in", "cache_rd", "model en delta",
             "model en usage"))
    print("─" * 92)
    for ws, c in filas:
        u = c.get("usage") or {}
        _cr = u.get("cache_read_tokens")
        if _cr is None:
            _cr = ((u.get("prompt_tokens_details") or {}).get("cached_tokens")
                   if isinstance(u.get("prompt_tokens_details"), dict) else None)
        print("%-11s %-9s %6s %9s %9s  %-22s %s"
              % (ws, c.get("finish") or "—", "sí" if c.get("done") else "NO",
                 u.get("prompt_tokens", "—"), "—" if _cr is None else _cr,
                 ",".join(str(m) for m in (c.get("modelos_delta") or ["—"]))[:22],
                 c.get("modelo_usage") or "—"))
    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(salida, indent=1))
        print("\n→ %s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
