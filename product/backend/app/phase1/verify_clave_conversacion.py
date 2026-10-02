#!/usr/bin/env python3
"""verify_clave_conversacion.py — la vara de la escalera de clave de conversación.

Prueba la escalera como FUNCIÓN PURA, reconstruida acá con los mismos peldaños que el
router. ⚠️ Y eso es una limitación que hay que decir, no esconder: esto NO prueba el
router; prueba la REGLA. Que el router la use se verifica en vivo, con `cache_read > 0`
y cruces incrementales, y ésa es la vara que manda.

Con `--caer` se muta UNA pieza —el dueño sale de la clave— y las varas que protegen
«dos cuentas no colisionan» tienen que ponerse rojas.
"""
from __future__ import annotations

import os
import sys

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


CON_DUENO = not CAER
if CAER:
    print("  ⚠️  MUTANTE: el dueño sale de la clave")


def clave(ws=None, user=None, sesion=None, chat=None, space=None, hilo=None):
    suf = ("#%s" % hilo) if hilo else ""
    for peldano, crudo in (("sesion", sesion),
                           ("chat", (chat.strip() + suf) if (chat or "").strip() else ""),
                           ("space", (space.strip() + suf) if (space or "").strip() else "")):
        v = (crudo or "").strip()
        if v:
            if CON_DUENO:
                return "%s:%s:%s:%s" % (ws or "ws", (user or "-"), peldano, v)
            return "%s:%s:%s" % (ws or "ws", peldano, v)
    return None


print("── A · la escalera respeta el orden ──")
ok(clave(ws="ciencia", user="u1", sesion="S", chat="C", space="E").endswith("sesion:S"),
   "A1 · con las tres, gana `sesion`", clave(ws="ciencia", user="u1", sesion="S", chat="C", space="E"))
ok(clave(ws="ciencia", user="u1", chat="C", space="E").endswith("chat:C"),
   "A2 · sin sesión, gana `chat`")
ok(clave(ws="legal", user="u1", space="E").endswith("space:E"),
   "A3 · sin sesión ni chat, cae a `space`")
ok(clave(ws="legal", user="u1") is None,
   "A4 · sin ninguna de las tres ⇒ None (camino de siempre, sin sesión)")
# ⚠️ esta afirmación la escribí mal la primera vez: pedía «no None» con SÓLO un chat en
# blanco y ningún otro peldaño, o sea pedía que inventara una clave de la nada. Lo
# correcto es que el peldaño en blanco se SALTEE y caiga al siguiente que sí tiene valor.
_blanco = clave(ws="legal", user="u1", chat="   ", space="E")
ok(_blanco is not None and _blanco.endswith("space:E"),
   "A5 · una cabecera en blanco se saltea y cae al peldaño siguiente", repr(_blanco))
ok(clave(ws="legal", user="u1", chat="   ") is None,
   "A6 · y si NO hay peldaño siguiente, es None — no se inventa una clave")

print("── B · lo que la clave tiene que separar ──")
ok(clave(ws="legal", user="u1", chat="C") != clave(ws="ciencia", user="u1", chat="C"),
   "B1 · dos WORKSPACES con el mismo chat NO comparten sesión")
ok(clave(ws="legal", user="u1", chat="C") != clave(ws="legal", user="u2", chat="C"),
   "B2 · dos DUEÑOS con el mismo chat NO comparten sesión  ← la fuga entre cuentas",
   f"{clave(ws='legal', user='u1', chat='C')} vs {clave(ws='legal', user='u2', chat='C')}")
ok(clave(ws="legal", user="u1", chat="C") != clave(ws="legal", user="u1", chat="D"),
   "B3 · dos conversaciones distintas ⇒ claves distintas")
ok(clave(ws="legal", user="u1", chat="X") != clave(ws="legal", user="u1", space="X"),
   "B4 · el mismo valor en peldaños distintos NO colisiona",
   f"{clave(ws='legal', user='u1', chat='X')} vs {clave(ws='legal', user='u1', space='X')}")

print("── C · lo que la clave tiene que MANTENER ──")
ok(clave(ws="ciencia", user="u1", chat="C") == clave(ws="ciencia", user="u1", chat="C"),
   "C1 · dos pasos del mismo hilo dan LA MISMA clave (si no, no hay reuso)")
# medido: en Ciencia y Oficina el chat_id fue el MISMO en los 11 y 9 cruces
ok(len({clave(ws="ciencia", user="u1", chat="23272969-3191-40c0-b736-631bb1894504")
        for _ in range(11)}) == 1,
   "C2 · el chat_id real de la corrida de Ciencia da una sola clave en 11 cruces")

print("── D · los datos REALES de la medición ──")
# copiados a mano de la corrida del 2026-08-23 (28 cruces)
REALES = [("ciencia", "23272969-3191-40c0-b736-631bb1894504", None),
          ("oficina", "5c4b83b5-e0d8-4124-8d9a-4a9883930586", None),
          ("legal", "", "space-ws-3ac2ed8ffelAe-mt5sis55-2")]
for ws, chat, space in REALES:
    k = clave(ws=ws, user="bae96eaa", chat=chat, space=space)
    ok(k is not None, f"D · {ws} obtiene clave ({'chat' if chat else 'space'})", str(k))

print("── E · DOS AGENTES EN EL MISMO CHAT (el defecto que cazó la medición) ──")
# En Legal, el agente `router` y el de Q&A comparten `X-Aleph-Chat`. Sin el `#hilo` caen
# en la misma sesión, el historial no calza, `_armar_prompt` renueva el id, y el
# principal pierde su sesión UNA VEZ POR TURNO. Medido: hilos fc7717996134 (Q&A) vs
# 00edb17ae74a y 689633d566e2 (router), todos con chat=998649e6.
_qa   = clave(ws="legal", user="u1", chat="998649e6", hilo="fc7717996134")
_rout = clave(ws="legal", user="u1", chat="998649e6", hilo="00edb17ae74a")
ok(_qa != _rout, "E1 · dos agentes del MISMO chat NO comparten sesión", f"{_qa} vs {_rout}")
ok(_qa == clave(ws="legal", user="u1", chat="998649e6", hilo="fc7717996134"),
   "E2 · y el principal conserva la suya entre turnos")
# al peldaño que el STACK declara no se le agrega nada
ok(clave(ws="finanzas", user="u1", sesion="S1", hilo="abc").endswith("sesion:S1"),
   "E3 · al peldaño `sesion` NO se le agrega el hilo: ahí el stack ya dijo cuál es",
   clave(ws="finanzas", user="u1", sesion="S1", hilo="abc"))

print(f"\n{_OK} verdes · {_MAL} rojas" + ("   [MUTANTE]" if CAER else ""))
raise SystemExit(0 if _MAL == 0 else 1)
