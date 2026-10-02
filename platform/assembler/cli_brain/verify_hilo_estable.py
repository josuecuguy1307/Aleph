#!/usr/bin/env python3
"""verify_hilo_estable.py — LAS TRES PUERTAS DE LA SESIÓN NORMALIZAN IGUAL.

    product/backend/.venv/bin/python platform/assembler/cli_brain/verify_hilo_estable.py
    …                                                              --caer   # el mutante

POR QUÉ EXISTE. La tanda de tokens cobró la sesión del CLI (Legal 66 %, Oficina 62 %,
Ciencia 42 %, Diseño −65/−71 %) y despues de integrarla NO RENDÍA NADA: seis claves
distintas para el mismo chat, todas `t0·completa`.

LA CAUSA, CAPTURADA —no deducida— con `ALEPH_GRABAR_PROMPT` contra la `.app` instalada,
Ciencia, dos turnos encadenados de la MISMA conversación. Correlacionando por
`prompt_chars` para saber cuál cruce es el del agente:

    turno 1 · agente · msg[1] · LISTA de 2 bloques · 3.890 chars
              «Contesta con el numero solo: …» + «<system-reminder>…» (3.716 chars)
    turno 2 · agente · msg[1] · CADENA pelada     ·    48 chars
              «Contesta con el numero solo: …»

Es el mismo turno de la conversación y cambian DOS cosas a la vez: la FORMA (bloques vs
cadena, porque el composer manda bloques y el historial se replica aplanado) y el
CONTENIDO (el andamiaje del harness está la primera vez y no está al replicar).

⚠️ Y NO ERA UNA PUERTA, ERAN TRES — por eso esta vara las mira juntas:
  A · la CLAVE  (`router._hilo_de`)        → `#hilo` distinto → sesión NUEVA
  B · el PREFIJO (`sesiones.huella_de`)    → forma distinta   → `prefijo_vivo` False
  E · el PREFIJO otra vez, con el ANDAMIAJE → contenido distinto → `prefijo_vivo` False

Y se descubrieron EN ESE ORDEN, cada una tapada por la anterior: arreglada A, la clave
quedó estable y el turno seguía `·completa` por B; arreglada B contra el fixture, en vivo
seguía `·completa` por E. Medido en la `.app` instalada las dos veces.

LOS ESPERADOS ESTÁN ESCRITOS A MANO y los bytes de entrada son los CAPTURADOS, no una
corrida previa: una vara que genera su esperado con la función bajo prueba no mide nada.

`--caer` monta el MUTANTE: `texto_de_contenido` vuelve a ser el `json.dumps` de antes.
A1, A2, B1 y B2 TIENEN que ponerse rojas. Si el mutante no las tumba, la vara no mide.
"""
from __future__ import annotations

import json
import os
import re
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
_ASM = os.path.dirname(_AQUI)
for _p in (_ASM,):
    if _p not in sys.path:
        sys.path.insert(0, _p)

CAER = "--caer" in sys.argv
_V = _R = 0


def ok(cond, etiqueta, detalle=""):
    global _V, _R
    if cond:
        _V += 1
        print(f"  🟢 {etiqueta}")
    else:
        _R += 1
        print(f"  🔴 {etiqueta}" + (f"   ← {detalle}" if detalle else ""))


from cli_brain import sesiones as S  # noqa: E402

if CAER:
    # EL MUTANTE: la normalización vuelve a ser la de antes (json.dumps a secas).
    def _mutante(content):
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        return json.dumps(content, ensure_ascii=False, sort_keys=True, default=str)
    S.texto_de_contenido = _mutante
    print("  ⚠️  MUTANTE: `texto_de_contenido` vuelve al json.dumps de antes\n")

# ── LOS BYTES REALES, tal como los capturó el tap ────────────────────────────────
HUMANO = "Contesta con el numero solo: cuanto es 12 mas 5?"
#: El andamiaje REAL: 3.716 chars pegados al mensaje la vez que se escribe, y AUSENTES
#: cuando el stack replica el historial. Acá va acortado; lo que importa son las etiquetas.
ANDAMIO = ("<system-reminder>\nYou are the primary Research agent.\n"
           + "x" * 200 + "\n</system-reminder>")
BLOQUES = [{"type": "text", "text": HUMANO}, {"type": "text", "text": ANDAMIO}]
CADENA = HUMANO

# la escalera del router, copiada en su parte de hash para poder medirla acá sin
# levantar FastAPI. ⚠️ NO reimplementa la normalización: llama a la MISMA función.
def hilo_de(msgs):
    """La parte de hash de la escalera del router. ⚠️ NO reimplementa NADA: el barrido del
    andamiaje y la normalización de forma los hace `texto_de_contenido`, que es justo lo
    que esta vara viene a proteger."""
    import hashlib
    for m in msgs or []:
        if (m.get("role") or "") == "user":
            c = S.texto_de_contenido(m.get("content")).strip()
            if not c:
                continue
            return hashlib.sha1(c.encode("utf-8", "replace")).hexdigest()[:12]
    return None


print("── A · LA CLAVE: el `#hilo` no se mueve porque cambie la FORMA ──")
h_bloques = hilo_de([{"role": "user", "content": BLOQUES}])
h_cadena = hilo_de([{"role": "user", "content": CADENA}])
ok(h_bloques == h_cadena,
   "A1 · bloques y cadena dan el MISMO #hilo", f"{h_bloques} vs {h_cadena}")

# el turno 2 real: el historial ya tiene la respuesta y el pedido nuevo
t2 = [{"role": "user", "content": CADENA},
      {"role": "assistant", "content": "17"},
      {"role": "user", "content": "Ahora restale 3. Solo el numero."}]
ok(hilo_de(t2) == h_bloques,
   "A2 · el turno 2 cae en la MISMA conversación que el turno 1",
   f"{hilo_de(t2)} vs {h_bloques}")

ok(hilo_de([{"role": "user", "content": "otra conversacion distinta"}]) != h_bloques,
   "A3 · y dos conversaciones DISTINTAS siguen separadas")

print("\n── B · EL PREFIJO: `prefijo_vivo` no rechaza lo que no cambió ──")
t1 = [{"role": "user", "content": BLOQUES}]
hu1 = S.huella_de(t1)
ok(S.huella_de(t2[:1]) == hu1,
   "B1 · la huella del mensaje 0 sobrevive al cambio de forma",
   f"{S.huella_de(t2[:1])} vs {hu1}")


class _Ses:
    def __init__(self, n, h):
        self.enviados, self.huella = n, h


ok(S.prefijo_vivo(_Ses(1, hu1), t2) is True,
   "B2 · con el prefijo intacto, el turno 2 puede ir INCREMENTAL")

ok(S.prefijo_vivo(_Ses(1, hu1),
                  [{"role": "user", "content": "otra cosa"},
                   {"role": "user", "content": "x"}]) is False,
   "B3 · y un prefijo de VERDAD distinto se sigue rechazando")

print("\n── C · lo que NO se aplana: si hay una imagen, se conserva la forma cruda ──")
con_img = [{"type": "text", "text": HUMANO},
           {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]
otra_img = [{"type": "text", "text": HUMANO},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,BBBB"}}]
ok(S.texto_de_contenido(con_img) != S.texto_de_contenido(otra_img),
   "C1 · dos mensajes que difieren SÓLO en la imagen no colisionan")
ok(S.texto_de_contenido(con_img) != HUMANO,
   "C2 · y no se los confunde con el mensaje de texto pelado")

print("\n── D · los bordes ──")
ok(S.texto_de_contenido(None) == "", "D1 · None → cadena vacía")
ok(S.texto_de_contenido([]) == "", "D2 · lista vacía → cadena vacía")
ok(S.texto_de_contenido("  hola  ") == "hola", "D3 · la cadena se recorta")
ok(S.texto_de_contenido([{"type": "text", "text": "a"},
                         {"type": "text", "text": "b"}]) == "ab",
   "D4 · varios bloques de texto se pegan en orden")

print("\n── E · LA TERCERA PUERTA: el andamiaje que aparece y desaparece ──")
# tal cual lo capturó el tap: turno 1 el mensaje trae el reminder, turno 2 viene pelado
ok(S.texto_de_contenido(BLOQUES) == S.texto_de_contenido(CADENA),
   "E1 · el mismo mensaje con y sin andamiaje normaliza IGUAL",
   f"{S.texto_de_contenido(BLOQUES)!r} vs {S.texto_de_contenido(CADENA)!r}")
_t1 = [{"role": "system", "content": "SYS"}, {"role": "user", "content": BLOQUES}]
_t2 = [{"role": "system", "content": "SYS"}, {"role": "user", "content": CADENA},
       {"role": "assistant", "content": "17"},
       {"role": "user", "content": "Ahora restale 3."}]
ok(S.huella_de(_t2[:2]) == S.huella_de(_t1),
   "E2 · y la HUELLA del prefijo sobrevive a que el andamiaje se caiga",
   f"{S.huella_de(_t2[:2])} vs {S.huella_de(_t1)}")
ok(S.prefijo_vivo(_Ses(2, S.huella_de(_t1)), _t2) is True,
   "E3 · con eso el turno 2 puede ir INCREMENTAL (la puerta que faltaba)")

print(f"\n{_V} verdes · {_R} rojas" + ("   [MUTANTE]" if CAER else ""))
sys.exit(1 if _R else 0)
