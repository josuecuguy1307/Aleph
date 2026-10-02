#!/usr/bin/env python3
"""Vara única Gate 3 · Obra B: EL MODELO QUE ELEGÍS ES EL QUE CORRE.

    python3 platform/assembler/verify_costura_obraB.py

Cierra los DOS cortes que midió `AUDITORIA-5-MODELO.md`:

  CORTE 1 · `sala.html` — el cerebro equipado en el Cuarto duraba una línea: se hidrataba y
            `applySalaSelectedModel()` lo pisaba con el selector del sidecar. **Frontend.**
  CORTE 2 · `stream_chat.py` — el fallback `primary→fallback` cambiaba de modelo a mitad de
            turno sin emitir NADA. **Backend.**

── LAS DOS ACTAS QUE LA ORDENAN (persona usuaria, 2026-08-07) ────────────────────────────────
ACTA 1 · UN SOLO ESTADO, PERSISTENTE. El cerebro equipado en el Cuarto es el que corre, por
  defecto, siempre. Se puede cambiar desde la Sala, con el MISMO widget del núcleo, y
  cambiarlo ahí MODIFICA EL AGENTE GUARDADO — un solo estado en dos lugares, no dos copias.
  Y pide confirmación: es editar tu agente desde otra pantalla.
ACTA 2 · SUSTITUIR SÍ, EN SILENCIO NO. Cuando el modelo elegido falla, el sistema sustituye
  para que no se caiga el trabajo, y AVISA: qué entró en lugar de qué, y por qué falló el
  primero.

── DE DÓNDE SALE CADA MEDICIÓN ─────────────────────────────────────────────────────
VB1-VB5 y VB7 los mide `arnes_costura_obraB.mjs` en WebKit REAL contra LA SALA DE ESTE
ÁRBOL, entrando por los caminos de producción (hidratar una receta · abrir el panel ·
elegir · confirmar) y leyendo el DOM y el PUT que salen. El `PUT /v1/puppets/{id}/config` se
INTERCEPTA: se mide QUÉ se iba a escribir —que es el contrato— sin tocar ninguna DB.

VB1 es la aserción central y está armada para no poder pasar por casualidad: el selector del
sidecar se siembra diciendo **otro** modelo que el del agente. Si algo vuelve a pisar, gana
el sembrado y la vara cae.

VB3 no se conforma con que el PUT salga: le da lo persistido a `modelIdForRecipe`, que es LA
función con la que el núcleo del Cuarto lee una receta. Si el Cuarto no lo leyera, «un solo
estado» sería una frase.

VB6 y VB8-VB9 se afirman contra los módulos reales, importados.

── LO QUE ESTA VARA NO HACE, A PROPÓSITO ───────────────────────────────────────────
NO SPAWNEA OTRAS VARAS (regla sellada). Las regresiones —obras 1·2·3·5, obraA, Gate 1,
`verify_f4a` con el venv, `test_executor`, `test_instrumentation` y las varas de Gate 2 que
tocan Sala/modelos/traductor— se corren APARTE y se reportan aparte.

**`verify_costura_obra4` NO entra en la verificación pre-merge:** tarda ~9 min y esta obra no
toca su territorio (`cli_brain`, sesiones, slots). Tenerla en el camino crítico fue lo que
abrió dos ventanas de carrera en el cierre de la obra 5. Sigue en la saneada, que es su lugar.

Cero red, cero backend, cero puertos fijos. JAMÁS :8377 ni :25374.
"""

from __future__ import annotations

import json
import subprocess
import pytest
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BACKEND = ROOT / "product" / "backend"
INSPECTION = ROOT / "platform" / "inspection"
for path in (HERE, ROOT / "platform", INSPECTION, BACKEND):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import errores_modelo as EM  # noqa: E402
import repair_clasificar as RC  # noqa: E402
from app.phase1 import motor_verdad as MV  # noqa: E402
from app.phase1 import stream_chat  # noqa: E402

ARNES = ROOT / "product" / "app" / "design" / "sala" / "arnes_costura_obraB.mjs"
SALA = ROOT / "product" / "app" / "design" / "sala" / "sala.html"

# [Convergencia · superficie 7 · paso 6] LA SALA VIEJA SE BORRÓ.
# Esta vara medía, entre otras cosas, texto de `sala/sala.html`. Esa pantalla ya no existe:
# su trabajo se rescató en la v2 y el resto murió con ella. La mitad que medía la Sala se
# SALTEA diciéndolo —no se borra la vara, porque el RESTO de lo que mide sigue vivo— y no
# se finge verde: un checkeo sin objeto es un salteo, jamás un ✓.
SALA_VIVA = SALA.exists()

SEMAFORO = ROOT / "product" / "app" / "design" / "cuarto" / "cuarto.semaforo.js"

PASSED = 0
FAILED = 0


def check(name: str, condition: bool, detail: Any = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"PASS {name}" + (f" — {detail}" if detail else ""))
    else:
        FAILED += 1
        print(f"FAIL {name} — {detail}")


def main() -> int:
    # ══ EL FRENTE · CORTE 1 (VB1-VB5, VB7) ═════════════════════════════════════════
    if not SALA_VIVA:
        # El arnés abre `sala/sala.html` en un navegador REAL. Sin pantalla no hay nada
        # que abrir: se saltea diciéndolo, jamás se finge verde.
        pytest.skip("el arnés medía la Sala vieja, que se borró (paso 6)")
    corrida = subprocess.run(["node", str(ARNES)], cwd=ROOT, text=True, capture_output=True)
    if corrida.returncode != 0:
        check("arnés del frente corre", False, (corrida.stderr or corrida.stdout)[-400:])
        print(f"=== {PASSED} passed, {FAILED} failed ===")
        return 1
    front = json.loads(corrida.stdout)
    check("arnés del frente sin errores de página", not front["errores_de_pagina"],
          front["errores_de_pagina"])

    # VB1 · el cerebro del agente MANDA, con el pisador diciendo otra cosa
    v1 = front["vb1"]
    check("VB1 el cerebro equipado sobrevive a la hidratación y es el que va a correr",
          v1["manda"] is True and v1["power"] == "qwen-local"
          and v1["primary_a_correr"] == v1["esperado"], v1)
    check("VB1b …y el selector del sidecar decía OTRA cosa (si pisara, la vara cae)",
          v1["selector_decia"] == "oss" and v1["primary_a_correr"] != "openai/gpt-oss-120b",
          {"selector": v1["selector_decia"], "corre": v1["primary_a_correr"]})
    check("VB1c la receta viaja ENTERA, no sólo el nombre (base_url del agente)",
          v1["base_url_a_correr"] == "http://127.0.0.1:11434/v1", v1["base_url_a_correr"])

    # VB2 · el MISMO widget, no una copia con estilo parecido
    v2 = front["vb2"]
    check("VB2 el selector de la Sala es el MISMO widget del Cuarto (mismas clases del AMS)",
          v2["montado"] and v2["clases_sala"] == v2["clases_widget"]
          and not v2["solo_en_sala"] and len(v2["comunes"]) >= 2, v2)

    # VB3 · un solo estado: Sala → persistencia → el Cuarto lo lee
    v3 = front["vb3"]
    check("VB3 confirmar escribe UNA vez en la fuente única (PUT /v1/puppets/{id}/config)",
          v3["puts"] == 1, v3)
    check("VB3b lo persistido es el modelo nuevo, compilado por la MISMA pieza que el Cuarto",
          v3["primary_persistido"] == "openai/gpt-oss-120b", v3)
    check("VB3c EL VIAJE COMPLETO: `modelIdForRecipe` (el lector del núcleo) devuelve el nuevo",
          v3["id_que_leeria_el_cuarto"] == "oss", v3)
    check("VB3d y la Sala queda con lo MISMO que persistió (cero divergencia en memoria)",
          v3["power_en_sala"] == "oss" and v3["receta_en_memoria"] == "openai/gpt-oss-120b", v3)

    # VB4 · sin confirmar no se escribe
    v4 = front["vb4"]
    check("VB4 elegir con un agente cargado PIDE confirmación (no aplica solo)",
          v4["pide_confirmacion"] is True and len(v4["botones"]) == 2, v4["botones"])
    check("VB4b sin confirmar NO se escribe nada y el agente queda intacto",
          v4["puts"] == 0 and v4["receta_primary"] == "qwen3:8b", v4)
    check("VB4c cancelar tampoco escribe, y el cerebro sigue siendo el de antes",
          v4["puts_tras_cancelar"] == 0 and v4["receta_tras_cancelar"] == "qwen3:8b", v4)

    # VB5 · sin agente, todo como hoy
    v5 = front["vb5"]
    check("VB5 chat SIN agente: no hay receta que modificar, el selector aplica directo",
          v5["manda"] is False and v5["puts"] == 0 and v5["power"] == "oss", v5)

    # VB7 · el aviso se VE, y no es rojo
    v7 = front["vb7"]
    check("VB7 el usuario VE con qué modelo corrió: pedido, usado y por qué falló el primero",
          v7["texto_tiene_aviso"] and v7["menciona_pedido"] and v7["menciona_usado"]
          and v7["menciona_causa"], v7)
    check("VB7b …y NO se pinta como fallo: el turno salió (cero cards rojas)",
          v7["cards_rojas"] == 0, v7["cards_rojas"])

    # ══ EL BACKEND · CORTE 2 (VB6) ═════════════════════════════════════════════════
    # El primario NO emite nada y revienta con una causa tipada; el fallback sí emite.
    # Es el caso exacto de `stream_chat.py:695`.
    receta = {"model": {"primary": "modelo-elegido", "fallback": "modelo-respaldo",
                        "base_url": "https://api.groq.com/openai/v1"},
              "framing": {"inline": "hola"}}
    original = stream_chat._stream_openai
    orig_sys, orig_key = stream_chat._system_content, stream_chat._resolve_llm_key

    def falso_stream(base_url, model, key, system, prompt, max_tokens, temperature,
                     cli_model=None, effort=None):
        if model == "modelo-elegido":
            raise EM.ErrorDeModelo(
                EM.CausaModelo(causa=EM.PROVEEDOR_CAIDO, estado=EM.ROTO,
                               detalle="El proveedor devolvió 502.",
                               reintentable=True, fuente=EM.FUENTE_URLLIB), "502")
        yield ("token", "salió igual")

    stream_chat._stream_openai = falso_stream
    stream_chat._system_content = lambda r: ""
    stream_chat._resolve_llm_key = lambda r, res: ("", False)
    try:
        emitido = list(stream_chat.stream_answer(receta, "hola"))
    finally:
        stream_chat._stream_openai = original
        stream_chat._system_content, stream_chat._resolve_llm_key = orig_sys, orig_key

    avisos = [json.loads(s) for k, s in emitido if k == "modelo_sustituido"]
    check("VB6 el fallback EMITE la sustitución (antes cambiaba de modelo en silencio)",
          len(avisos) == 1, [k for k, _ in emitido])
    a = avisos[0] if avisos else {}
    check("VB6b …con los TRES datos del acta: qué se pidió, qué entró, por qué falló",
          a.get("pedido") == "modelo-elegido" and a.get("usado") == "modelo-respaldo"
          and a.get("causa_origen") == EM.PROVEEDOR_CAIDO, a)
    check("VB6c la causa del fallo original sale del VOCABULARIO, no de texto libre",
          a.get("causa_origen") in EM.CAUSAS, a.get("causa_origen"))
    check("VB6d el aviso va ANTES del primer token del respaldo (se avisa, y después se sirve)",
          [k for k, _ in emitido][:2] == ["modelo_sustituido", "token"], [k for k, _ in emitido])
    check("VB6e y el turno SALE igual: la sustitución no se come la respuesta",
          any(k == "token" for k, _ in emitido), emitido)

    # ══ EL VOCABULARIO (VB8) ═══════════════════════════════════════════════════════
    check("VB8 `modelo_sustituido` está en el vocabulario CERRADO de la UI",
          "modelo_sustituido" in MV.CAUSAS and "modelo_sustituido" in EM.CAUSAS)
    check("VB8b …y repair la clasifica: el turno salió, no hay nada que reparar",
          RC.clasificar("modelo_sustituido").accion == RC.SIN_ALARMA
          and RC.clasificar("modelo_sustituido").boton is None,
          RC.clasificar("modelo_sustituido").como_dict())
    check("VB8c JAMÁS cae en una acción que reintente (la respuesta ya se entregó)",
          RC.clasificar("modelo_sustituido").accion not in (RC.BACKOFF, RC.UNA_VUELTA))
    check("VB8d cero causas del motor sin clasificar en repair (la invariante de la obra A)",
          not sorted(set(MV.CAUSAS) - RC.CAUSAS_CUBIERTAS),
          sorted(set(MV.CAUSAS) - RC.CAUSAS_CUBIERTAS))
    # el copy: RESOLUBLE, no sólo presente. Lo mide el arnés pidiéndoselo a `caraDeCausa`.
    dic = SEMAFORO.read_text()
    check("VB8e tiene entrada en el diccionario único, con copy en los dos idiomas",
          "modelo_sustituido:" in dic and "Corrí con el modelo de respaldo" in dic
          and "Ran with the backup model" in dic)
    check("VB8f …y con `alarma: false`: el turno salió, pintarlo rojo sería mentir",
          "modelo_sustituido:" in dic
          and "alarma: false" in dic.split("modelo_sustituido:")[1].split("\n")[0])

    # ══ VB9 · NADIE PINTA ESTADO DE MODELO POR SU CUENTA ═══════════════════════════
    # La regla sellada por Gate 2: `semaforoDe` es el derivador único. Lo que esta obra
    # agregó a la Sala tiene que derivar del diccionario, no escribir copy de causa a mano.
    if not SALA_VIVA:
        print("  ~ SALTEADO: la Sala vieja se borró (paso 6) — esta mitad no tiene objeto")
        return
    sala = SALA.read_text()
    check("VB9 el aviso de sustitución deriva del diccionario único (`Sem.caraDeCausa`)",
          "function avisarSustitucion" in sala
          and "Sem.caraDeCausa({ causa:'modelo_sustituido'" in sala)
    check("VB9b …y no escribe a mano el copy de NINGUNA causa del vocabulario",
          "Corrí con el modelo de respaldo'" not in sala.replace(
              "trS('sala.modelo.sustituido','Corrí con el modelo de respaldo')", ""),
          "el fallback de trS es el único literal, y sólo para cuando el diccionario no cargó")

    print(f"=== {PASSED} passed, {FAILED} failed ===")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
