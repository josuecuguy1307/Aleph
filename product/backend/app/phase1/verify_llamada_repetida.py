#!/usr/bin/env python3
"""verify_llamada_repetida.py — la vara del eco.

Con `--caer` se muta UNA pieza —la huella deja de mirar el contenido de los mensajes—
y las varas que protegen «sólo se contesta del eco lo que es IDÉNTICO» tienen que
ponerse rojas. Si con `--caer` sigue todo verde, la vara no mide.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from app.phase1 import llamada_repetida as LR  # noqa: E402

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


if CAER:
    # LA MUTACIÓN: la huella mira sólo el workspace y la CANTIDAD de mensajes, no su
    # contenido. Es el atajo barato («total, el título siempre viene igual») y hace que
    # dos pedidos DISTINTOS se contesten con la misma respuesta — que es exactamente el
    # daño que esta pieza no puede causar.
    def _huella_boba(workspace, messages, max_tokens, temperature):
        return "%s::%d" % (workspace or "", len(messages or []))
    LR.clave_de = _huella_boba
    print("  ⚠️  MUTANTE: la huella ignora el contenido de los mensajes")

TITULO = [{"role": "system", "content": "You are a title generator."},
          {"role": "user", "content": "The following is the text to summarize:\nOf those "
                                      "five, which has the earliest arXiv id?"}]
OTRO = [{"role": "system", "content": "You are a title generator."},
        {"role": "user", "content": "The following is the text to summarize:\nNow search "
                                    "arXiv for medusa decoding heads."}]

llamadas = {"n": 0}
eventos = []


def modelo(texto="Titulo A"):
    def _f():
        llamadas["n"] += 1
        return {"content": f"{texto} #{llamadas['n']}", "tool_calls": [],
                "model": "claude-opus-5", "usage": {"prompt_tokens": 868},
                "cost_events": [{"x": 1}]}
    return _f


def correr(msgs, ws="ciencia", tools=None, clave="ciencia:chat1", texto="Titulo A"):
    return LR.paso(clave=clave, workspace=ws, messages=msgs, tools=tools or [],
                   llamar_modelo=modelo(texto), on_event=eventos.append)


print("── A · la perilla ──")
# ⚠️ ESTA SECCIÓN CAMBIÓ CUANDO EL ECO PASÓ A ENVIARSE PRENDIDO. Antes «apagada» se
# escribía sacando la variable, porque el default era vacío. Ahora el default de fábrica
# es `ciencia` (ver `llamada_repetida.POR_DEFECTO` y por qué), así que sacar la variable
# lo PRENDE. La aserción no se ablandó: se re-apuntó al contrato nuevo — «apagada» es
# ahora la variable puesta en vacío, que es la forma documentada de apagarlo.
os.environ.pop("ALEPH_ECO_AUXILIAR_WS", None)
ok(LR.encendido_para("ciencia"), "A0 · de fábrica viene PRENDIDO en Ciencia")
ok(not LR.encendido_para("oficina"), "A0b · y en nadie más")
os.environ["ALEPH_ECO_AUXILIAR_WS"] = ""
ok(correr(TITULO) is None, "A1 · apagada (variable vacía): `None`, camino de siempre")
os.environ["ALEPH_ECO_AUXILIAR_WS"] = "ciencia"
ok(LR.encendido_para("ciencia") and not LR.encendido_para("oficina"),
   "A2 · la perilla es POR STACK")

print("── B · el par idéntico ──")
LR._ECOS.clear(); llamadas["n"] = 0; eventos.clear()
a = correr(TITULO)
b = correr(TITULO)
ok(llamadas["n"] == 1, "B1 · dos pedidos IDÉNTICOS ⇒ UNA sola llamada al modelo",
   f"llamadas={llamadas['n']}")
ok(a["content"] == b["content"], "B2 · la respuesta es la misma")
ok(b.get("aleph_eco", {}).get("servido") is True, "B3 · y viene marcada como eco")

print("── C · lo que NO se repite ──")
LR._ECOS.clear(); llamadas["n"] = 0; eventos.clear()
correr(TITULO); d = correr(OTRO)
ok(llamadas["n"] == 2, "C1 · un pedido DISTINTO va al modelo", f"llamadas={llamadas['n']}")
ok("medusa" not in "" and d.get("aleph_eco") is None, "C2 · y no viene marcado como eco")

LR._ECOS.clear(); llamadas["n"] = 0
correr(TITULO, ws="ciencia", clave="ciencia:chat1")
correr(TITULO, ws="ciencia", clave="ciencia:chat2")
ok(llamadas["n"] == 2, "C3 · el eco NO cruza de conversación", f"llamadas={llamadas['n']}")

LR._ECOS.clear(); llamadas["n"] = 0
correr(TITULO, tools=[{"type": "function", "function": {"name": "read"}}])
correr(TITULO, tools=[{"type": "function", "function": {"name": "read"}}])
ok(llamadas["n"] == 0, "C4 · con tools el eco NI SE INTENTA (devuelve None)",
   f"llamadas={llamadas['n']}")

print("── D · una sola repetición, y ventana corta ──")
LR._ECOS.clear(); llamadas["n"] = 0
correr(TITULO); correr(TITULO); correr(TITULO)
ok(llamadas["n"] == 2, "D1 · la TERCERA idéntica vuelve al modelo", f"{llamadas['n']}")

LR._ECOS.clear(); llamadas["n"] = 0
correr(TITULO)
for v in LR._ECOS.values():
    v["ts"] = time.time() - (LR.VENTANA_S + 5)
correr(TITULO)
ok(llamadas["n"] == 2, "D2 · fuera de la ventana, al modelo", f"{llamadas['n']}")

print("── E · nada deja de decirse ──")
LR._ECOS.clear(); llamadas["n"] = 0; eventos.clear()
correr(TITULO); correr(TITULO)
pasos = [e for e in eventos if e.get("type") == "workspace_step"]
ok(len(pasos) == 1 and pasos[0].get("servido_del_eco") is True,
   "E1 · el paso servido del eco EMITE su workspace_step", str(pasos)[:150])
ok("sin llamar al modelo" in (pasos[0].get("detalle") or ""),
   "E2 · y dice por qué", str(pasos)[:150])
segunda = correr.__wrapped__ if hasattr(correr, "__wrapped__") else None
LR._ECOS.clear(); llamadas["n"] = 0
x = correr(TITULO); y = correr(TITULO)
ok(y.get("usage") is None, "E3 · el `usage` NO se repite (contarlo dos veces es inventar)",
   str(y.get("usage")))
ok(y.get("cost_events") == [], "E4 · ni el cost-event: no hubo llamada al modelo",
   str(y.get("cost_events")))
ok(x.get("usage") is not None, "E5 · pero la PRIMERA sí reporta lo suyo")

print("── F · una jugada de tool no se cachea ──")
LR._ECOS.clear(); llamadas["n"] = 0


def _modelo_tool():
    llamadas["n"] += 1
    return {"content": None, "tool_calls": [{"id": "c1", "name": "read", "arguments": "{}"}],
            "model": "m", "usage": None, "cost_events": []}


for _ in range(2):
    LR.paso(clave="k", workspace="ciencia", messages=TITULO, tools=[],
            llamar_modelo=_modelo_tool, on_event=eventos.append)
ok(llamadas["n"] == 2, "F1 · si la respuesta trae tool_calls, no se guarda eco",
   f"llamadas={llamadas['n']}")

print("── G · LA GEMELA EN VUELO (el caso real) ──")
# ⚠️ ÉSTE es el caso que la medición encontró y que la primera versión NO cubría: las dos
# llamadas idénticas llegan SOLAPADAS, no una después de la otra. Una caché de resultados
# terminados nunca le acierta. Si esta vara no estuviera, la pieza pasaría en verde y no
# ahorraría un solo token en producción — que es exactamente lo que pasó dos corridas.
import threading  # noqa: E402

LR._ECOS.clear()
llamadas["n"] = 0
eventos.clear()
_arranco = threading.Event()


def _modelo_lento():
    llamadas["n"] += 1
    _arranco.set()
    time.sleep(1.0)                     # la gemela llega DURANTE este rato
    return {"content": "Titulo compartido", "tool_calls": [], "model": "m",
            "usage": {"prompt_tokens": 868}, "cost_events": [{"x": 1}]}


res = {}


def _primera():
    res["a"] = LR.paso(clave="ciencia:chat1", workspace="ciencia", messages=TITULO,
                       tools=[], llamar_modelo=_modelo_lento, on_event=eventos.append)


h = threading.Thread(target=_primera)
h.start()
_arranco.wait(5)                        # la gemela entra con la primera EN VUELO
res["b"] = LR.paso(clave="ciencia:chat1", workspace="ciencia", messages=TITULO, tools=[],
                   llamar_modelo=_modelo_lento, on_event=eventos.append)
h.join(10)
ok(llamadas["n"] == 1, "G1 · gemela EN VUELO ⇒ UNA sola llamada al modelo",
   f"llamadas={llamadas['n']}")
ok(res["a"] and res["b"] and res["a"]["content"] == res["b"]["content"],
   "G2 · las dos salen con la misma respuesta", str(res)[:160])
ok(res["b"].get("aleph_eco", {}).get("servido") is True,
   "G3 · la segunda viene marcada como eco")
ok(res["b"].get("usage") is None and res["a"].get("usage") is not None,
   "G4 · sólo la primera reporta usage")
pasos = [e for e in eventos if e.get("type") == "workspace_step"]
ok(len(pasos) == 1 and pasos[0].get("servido_del_eco") is True,
   "G5 · y el paso se emite igual", str(pasos)[:140])

print("── H · si la primera se cae, la gemela no se cuelga ──")
LR._ECOS.clear()
llamadas["n"] = 0
_arranco2 = threading.Event()


def _modelo_roto():
    llamadas["n"] += 1
    _arranco2.set()
    time.sleep(0.4)
    raise RuntimeError("el modelo se cayó")


def _primera_rota():
    try:
        LR.paso(clave="k", workspace="ciencia", messages=TITULO, tools=[],
                llamar_modelo=_modelo_roto)
    except RuntimeError:
        pass


h2 = threading.Thread(target=_primera_rota)
h2.start()
_arranco2.wait(5)
t0 = time.time()
salida = LR.paso(clave="k", workspace="ciencia", messages=TITULO, tools=[],
                 llamar_modelo=modelo("Rescate"))
h2.join(10)
tardo = time.time() - t0
ok(tardo < LR.ESPERA_S / 2, f"H1 · la gemela NO espera el timeout entero ({tardo:.1f}s)",
   f"{tardo:.1f}s")
ok(salida and "Rescate" in (salida.get("content") or ""),
   "H2 · hace su propia llamada y contesta", str(salida)[:120])

print(f"\n{_OK} verdes · {_MAL} rojas" + ("   [MUTANTE]" if CAER else ""))
raise SystemExit(0 if _MAL == 0 else 1)
