#!/usr/bin/env python3
"""verify_salidas_diferidas.py — la vara de las salidas diferidas.

Con `--caer` se muta UNA pieza —el pliegue deja de decir cómo pedir el resto— y las
varas que protegen «nada se recorta en silencio» tienen que ponerse rojas. Si con
`--caer` sigue todo verde, la vara no está midiendo lo que dice medir.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from app.phase1 import salidas_diferidas as SD  # noqa: E402

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
    # LA MUTACIÓN: el pliegue recorta y NO dice cómo recuperar lo recortado. Es el
    # atajo tentador («total, el modelo ya lo vio») y es exactamente el verde mudo
    # que esta pieza existe para no cometer.
    def _mudo(sid, nombre, texto):
        return texto[:SD.CABEZA_CHARS]
    SD._pliegue = _mudo
    print("  ⚠️  MUTANTE: el pliegue recorta sin declarar el recorte")

GRANDE = json.dumps([{"fila": i, "region": "Este", "producto": "Sensor A1",
                      "unidades": 100 + i, "ingreso": 1234.56 + i}
                     for i in range(200)], ensure_ascii=False)
CHICA = "ok, 3 archivos"
CANARIO = "MARCA-PROFUNDA-7Q4Z"
CON_CANARIO = GRANDE[:len(GRANDE) // 2] + CANARIO + GRANDE[len(GRANDE) // 2:]


def msgs(*salidas):
    out = [{"role": "system", "content": "sos un agente"},
           {"role": "user", "content": "sumá la columna ingreso"}]
    for i, (nombre, texto) in enumerate(salidas):
        out.append({"role": "assistant", "content": "",
                    "tool_calls": [{"id": f"c{i}", "type": "function",
                                    "function": {"name": nombre, "arguments": "{}"}}]})
        out.append({"role": "tool", "tool_call_id": f"c{i}", "name": nombre,
                    "content": texto})
    return out


print("── A · la perilla ──")
os.environ.pop("ALEPH_SALIDAS_DIFERIDAS_WS", None)
m = msgs(("read", GRANDE), ("bash", CHICA))
p, extra, inf = SD.plegar(m, "oficina", "k0")
ok(p is m and extra == [] and inf["plegadas"] == 0,
   "A1 · apagada: los MISMOS mensajes, sin tool extra")
os.environ["ALEPH_SALIDAS_DIFERIDAS_WS"] = "oficina"
ok(SD.encendido_para("oficina") and not SD.encendido_para("legal"),
   "A2 · la perilla es POR STACK")

print("── B · la más nueva nunca se pliega ──")
p1, e1, i1 = SD.plegar(msgs(("read", GRANDE)), "oficina", "k1")
ok(i1["plegadas"] == 0 and e1 == [],
   "B1 · primera vuelta: la salida cruza ENTERA (el modelo no la vio)",
   f"plegadas={i1['plegadas']}")
p2, e2, i2 = SD.plegar(msgs(("read", GRANDE), ("bash", CHICA)), "oficina", "k1")
ok(i2["plegadas"] == 1, "B2 · segunda vuelta: la vieja SÍ se pliega",
   f"plegadas={i2['plegadas']}")
ok(p2[-1]["content"] == CHICA, "B3 · la MÁS NUEVA sigue entera aunque sea vieja de nombre")
ok(len(p2[3]["content"]) < len(GRANDE), "B4 · el pliegue achica de verdad",
   f"{len(p2[3]['content'])} vs {len(GRANDE)}")

print("── C · nada se recorta en silencio ──")
doblado = p2[3]["content"]
ok(str(len(GRANDE)) in doblado, "C1 · dice el tamaño ORIGINAL", doblado[:120])
ok(SD.NOMBRE_LECTOR in doblado, "C2 · dice CÓMO pedir el resto", doblado[:120])
ok('id="s1"' in doblado, "C3 · dice CON QUÉ ID pedirlo", doblado[:160])
ok(e2 and e2[0]["function"]["name"] == SD.NOMBRE_LECTOR,
   "C4 · y declara la tool que lo hace posible")

print("── D · el crudo sigue entero y alcanzable ──")
todo = SD._leer("k1", {"id": "s1", "desde": 0, "cuanto": 10 ** 6})
ok(GRANDE in todo, "D1 · el lector devuelve el texto COMPLETO")
trozo = SD._leer("k1", {"id": "s1", "desde": 100, "cuanto": 50})
ok(GRANDE[100:150] in trozo, "D2 · lee desde un offset exacto")
ok("quedan" in trozo, "D3 · y avisa cuánto falta todavía")
mal = SD._leer("k1", {"id": "s99"})
ok("no existe" in mal and "s1" in mal, "D4 · un id inexistente se dice, no se inventa")

print("── E · el canario: lo recortado se puede recuperar ──")
SD.plegar(msgs(("read", CON_CANARIO)), "oficina", "k2")
pe, _, ie = SD.plegar(msgs(("read", CON_CANARIO), ("bash", CHICA)), "oficina", "k2")
ok(CANARIO not in pe[3]["content"], "E1 · el canario NO está en el fragmento plegado")
ok(CANARIO in SD._leer("k2", {"id": "s1", "desde": 0, "cuanto": 10 ** 6}),
   "E2 · pero SÍ está cuando se lo pide (no se perdió)")

print("── F · el bucle del lector ──")
vueltas = {"n": 0}


def _modelo_que_lee(_m, _t):
    vueltas["n"] += 1
    if vueltas["n"] == 1:
        return {"content": None, "tool_calls": [
            {"id": "r1", "name": SD.NOMBRE_LECTOR, "arguments": '{"id":"s1","desde":0}'}]}
    return {"content": "listo", "tool_calls": []}


os.environ["ALEPH_SALIDAS_DIFERIDAS_WS"] = "oficina"
SD.plegar(msgs(("read", GRANDE)), "oficina", "k3")
out = SD.paso(clave="k3", workspace="oficina",
              messages=msgs(("read", GRANDE), ("bash", CHICA)),
              tools=[{"type": "function", "function": {"name": "read", "parameters": {}}}],
              llamar_modelo=_modelo_que_lee)
ok(vueltas["n"] == 2, "F1 · la lectura NO vuelve al stack: se contesta y se re-pregunta",
   f"vueltas={vueltas['n']}")
ok(out and out.get("content") == "listo" and not out.get("tool_calls"),
   "F2 · lo que sale es la jugada del stack, sin rastro del lector", str(out)[:160])

tope = {"n": 0}


def _modelo_en_bucle(_m, _t):
    tope["n"] += 1
    if tope["n"] > SD.MAX_LECTURAS + 3:
        return {"content": "corto", "tool_calls": []}
    return {"content": None, "tool_calls": [
        {"id": f"r{tope['n']}", "name": SD.NOMBRE_LECTOR, "arguments": '{"id":"s1"}'}]}


SD.plegar(msgs(("read", GRANDE)), "oficina", "k4")
out2 = SD.paso(clave="k4", workspace="oficina",
               messages=msgs(("read", GRANDE), ("bash", CHICA)),
               tools=[], llamar_modelo=_modelo_en_bucle)
ok(tope["n"] <= SD.MAX_LECTURAS + 2,
   f"F3 · el techo de lecturas corta el bucle ({tope['n']} vueltas)", f"{tope['n']}")

print("── G · sin nada que plegar, no hay desvío ──")
os.environ["ALEPH_SALIDAS_DIFERIDAS_WS"] = "oficina"
nada = SD.paso(clave="k5", workspace="oficina", messages=msgs(("bash", CHICA)),
               tools=[], llamar_modelo=lambda a, b: {"content": "x"})
ok(nada is None, "G1 · nada plegado ⇒ `None` ⇒ camino de siempre")
otro = SD.paso(clave="k6", workspace="legal", messages=msgs(("read", GRANDE)),
               tools=[], llamar_modelo=lambda a, b: {"content": "x"})
ok(otro is None, "G2 · un stack sin la perilla nunca entra")

print("── H · LA COMPOSICIÓN: el plegado adentro del closure de code execution ──")
# Las dos firmas de `llamar_modelo` son la misma —(messages, tools) -> out— y eso es lo
# que hace posible componerlas. Acá se prueba la FORMA de la composición: el plegado
# envuelve un `crudo` y devuelve algo que el llamante de arriba puede usar igual.
LR_ECOS = None
SD._ECOS = {}
os.environ["ALEPH_SALIDAS_DIFERIDAS_WS"] = "oficina"
llamadas_crudas = {"n": 0, "ultimo_msgs": None, "ultimas_tools": None}


def _crudo(m, t):
    llamadas_crudas["n"] += 1
    llamadas_crudas["ultimo_msgs"] = m
    llamadas_crudas["ultimas_tools"] = t
    return {"content": "ok", "tool_calls": [], "model": "m", "usage": None,
            "cost_events": []}


def _compuesto(m, t):
    """Lo mismo que hace el router: plegado adentro, crudo si no hay nada que plegar."""
    r = SD.paso(clave="ce:k", workspace="oficina", messages=m, tools=t,
                llamar_modelo=_crudo)
    return r if r is not None else _crudo(m, t)


_una = msgs(("read", GRANDE))
_compuesto(_una, [])                       # primera vuelta: nada plegado ⇒ crudo
ok(llamadas_crudas["n"] == 1 and llamadas_crudas["ultimo_msgs"] is _una,
   "H1 · sin nada que plegar, la composición pasa los MISMOS mensajes al crudo")
_dos = msgs(("read", GRANDE), ("bash", CHICA))
_compuesto(_dos, [])                       # segunda: la vieja se pliega
ok(llamadas_crudas["n"] == 2, "H2 · y sigue llamando al modelo una sola vez por paso")
_enviado = llamadas_crudas["ultimo_msgs"]
ok(len(_enviado[3]["content"]) < len(GRANDE),
   "H3 · lo que llegó al crudo VA PLEGADO", f"{len(_enviado[3]['content'])}")
ok(any((t.get("function") or {}).get("name") == SD.NOMBRE_LECTOR
       for t in (llamadas_crudas["ultimas_tools"] or [])),
   "H4 · y con el lector declarado al lado de las tools que venían")
ok(_dos[3]["content"] == GRANDE,
   "H5 · el mensaje ORIGINAL del llamante no se mutó (el pliegue es una copia)")

print(f"\n{_OK} verdes · {_MAL} rojas" + ("   [MUTANTE]" if CAER else ""))
raise SystemExit(0 if _MAL == 0 else 1)
