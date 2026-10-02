#!/usr/bin/env python3
"""verify_grabador_prompt.py — la vara del instrumento de la obra A.

Un instrumento que no puede dar rojo no mide nada. Con `--caer` se muta UNA pieza
(el grabador deja de guardar el contenido de los mensajes) y las varas que dependen
de esa pieza tienen que ponerse rojas. Si con `--caer` sigue todo verde, la vara es
decoración y el número que produce no vale.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _AQUI)

CAER = "--caer" in sys.argv
_OK = _MAL = 0


def ok(cond, etiqueta, detalle=""):
    global _OK, _MAL
    if cond:
        _OK += 1
        print(f"  🟢 {etiqueta}")
    else:
        _MAL += 1
        print(f"  🔴 {etiqueta}" + (f"  ← {detalle}" if detalle else ""))


# ⚠️ EL CONTENIDO DE PRUEBA NO PUEDE SER `"X" * 4000`. Medido acá mismo: 4.000 equis
# repetidas dan **258 tokens**, no ~1.000 — el BPE se come la repetición. Una salida de
# tool real es texto o JSON variado, y ahí el ratio es ~4 chars/token. Usar relleno
# degenerado hace que la vara mida el compresor, no el instrumento.
_SALIDA = json.dumps([{"id": i, "titulo": f"paper numero {i} sobre difusion latente",
                       "autores": ["A. Prueba", "B. Testigo"], "anio": 2020 + i % 6,
                       "resumen": "un resumen razonablemente largo que se parece a lo "
                                  "que devuelve de verdad una tool de busqueda"}
                      for i in range(20)], ensure_ascii=False)

MSGS = [
    {"role": "system", "content": "Sos el cerebro de un workspace."},
    {"role": "user", "content": "¿cuánto da 13^8?"},
    {"role": "assistant", "content": "", "tool_calls": [
        {"id": "c1", "type": "function",
         "function": {"name": "read", "arguments": '{"filePath":"/a.txt"}'}}]},
    {"role": "tool", "tool_call_id": "c1", "name": "read", "content": _SALIDA},
    {"role": "assistant", "content": "listo"},
]
TOOLS = [{"type": "function", "function": {
    "name": "read", "description": "lee un archivo",
    "parameters": {"type": "object", "properties": {"filePath": {"type": "string"}},
                   "required": ["filePath"]}}}]

print("── A · el grabador ──")
import grabador_prompt as gp  # noqa: E402

if CAER:
    # LA MUTACIÓN: el grabador guarda el largo pero TIRA el contenido. Es exactamente
    # el atajo tentador («¿para qué guardar el texto si sólo quiero el tamaño?») y
    # rompe dos cosas: no se puede tokenizar, y no se puede reconocer una salida
    # repetida entre cruces. Las varas B y C tienen que cazarlo.
    _orig = gp._mensaje

    def _mutado(m, i):
        f = _orig(m, i)
        f["content"] = ""
        return f
    gp._mensaje = _mutado
    print("  ⚠️  MUTANTE: `_mensaje` tira el contenido")

os.environ.pop("ALEPH_GRABAR_PROMPT", None)
gp.grabar_cruce("borde", "ciencia", MSGS, TOOLS)
ok(gp.encendido() == "", "A1 · sin la variable el grabador está apagado")

d = tempfile.mkdtemp(prefix="varaprompt-")
ruta = os.path.join(d, "cruces.jsonl")
os.environ["ALEPH_GRABAR_PROMPT"] = ruta
for _ in range(3):                      # tres cruces con la MISMA salida adentro
    gp.grabar_cruce("borde", "ciencia", MSGS, TOOLS, paso="p")
filas = [json.loads(x) for x in open(ruta, encoding="utf-8") if x.strip()]
ok(len(filas) == 3, "A2 · una línea por cruce", f"salieron {len(filas)}")
ok(all(f["n_messages"] == 5 for f in filas), "A3 · cuenta los mensajes")

# la vara del efecto observador: un mensaje enorme no puede tardar una eternidad
import time  # noqa: E402
GRANDE = MSGS[:3] + [{"role": "tool", "tool_call_id": "c1", "name": "read",
                      "content": _SALIDA * 60}] + MSGS[4:]
t0 = time.time()
gp.grabar_cruce("borde", "ciencia", GRANDE, TOOLS)
dt = time.time() - t0
ok(dt < 0.25, f"A4 · {len(_SALIDA)*60//1000}k chars se graban en {dt*1000:.0f} ms (sin efecto observador)",
   f"tardó {dt:.2f}s")

print("── B · la descomposición ──")
import analizar_prompt as ap  # noqa: E402

f = ap.analizar_fila(filas[0])
ok(f["total"] > 0, "B1 · el prompt tiene tokens")
ok(f["salidas"] > 900,
   f"B2 · la salida de {len(_SALIDA):,} chars pesa {f['salidas']} tok",
   f"dio {f['salidas']} sobre {len(_SALIDA)} chars")
# La tolerancia es RELATIVA a propósito: la tokenización no es aditiva y los bordes
# entre segmentos funden tokens. Medido acá: 6 de deriva sobre 1.366 (0,4 %). Una
# tolerancia absoluta de 5 daba rojo por física, no por defecto — y una vara que da
# rojo cuando el instrumento está bien es tan inútil como una que nunca lo da.
deriva = abs(f["salidas"] - f["salidas_marginal"])
_tope = max(8, 0.01 * f["salidas"])
ok(deriva <= _tope, f"B3 · suma de partes ≡ contrafáctico (deriva {deriva}, tope "
   f"{_tope:.0f})", f"partes={f['salidas']} marginal={f['salidas_marginal']}")
ok(f["catalogo"] > 0, "B4 · el catálogo pesa")
ok(f["resto"] >= 0, f"B5 · el residuo no es negativo ({f['resto']})", f"dio {f['resto']}")
ok(f["total"] == f["catalogo"] + f["salidas"] + f["resto"], "B6 · las partes cierran")

print("── C · el re-leído ──")
res = ap.analizar_fila(filas[0])
hashes = {d["hash"] for d in res["detalle"]}
ok(len(hashes) == 1 and "" not in hashes, "C1 · la salida tiene identidad",
   f"hashes={hashes}")
h0 = list(hashes)[0] if hashes else None
mismos = all(list({d["hash"] for d in ap.analizar_fila(x)["detalle"]}) == [h0]
             for x in filas)
ok(mismos, "C2 · la MISMA salida da el MISMO hash en los tres cruces")
distinto = ap.analizar_fila(json.loads(json.dumps(filas[0])))
distinto["detalle"] = None
otra = MSGS[:3] + [{"role": "tool", "tool_call_id": "c1", "name": "read",
                    "content": _SALIDA + " otra cosa"}] + MSGS[4:]
gp.grabar_cruce("borde", "ciencia", otra, TOOLS)
f2 = [json.loads(x) for x in open(ruta, encoding="utf-8") if x.strip()][-1]
h2 = {d["hash"] for d in ap.analizar_fila(f2)["detalle"]}
ok(h2 and h2 != hashes, "C3 · otra salida da OTRO hash (el hash discrimina)",
   f"{h2} vs {hashes}")

print("── D · el tap no cambia el prompt ──")
from cli_brain.prompt_bridge import render_con_imagenes, render_prompt  # noqa: E402
sys.path.insert(0, os.path.join(_AQUI, "cli_brain"))
import cli_brain.server as srv  # noqa: E402
p_directo = render_prompt(MSGS, TOOLS, None)
p_tap, inc, ims = srv._grabado(render_con_imagenes(MSGS, TOOLS, None), False,
                               MSGS, TOOLS, None)
ok(p_tap == p_directo and inc is False, "D1 · `_grabado` devuelve lo mismo, byte por byte")
ok(ims == [], "D2 · y sin imágenes en el mensaje, la lista de adjuntos viene vacía")

print(f"\n{_OK} verdes · {_MAL} rojas" + ("   [MUTANTE]" if CAER else ""))
raise SystemExit(0 if _MAL == 0 else 1)
