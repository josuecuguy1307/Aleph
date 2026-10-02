#!/usr/bin/env python3
"""Vara única Gate 3 · Obra 6: EL AVISO DE MEMORIA PERDIDA (G-6).

    product/backend/.venv/bin/python platform/assembler/verify_costura_obra6.py

⚠️ **NO ANIDA VARAS** (regla sellada en F4a). Lo único que corre acá adentro es el ARNÉS
del frente, que no es una vara: mide y devuelve JSON, y las aserciones viven acá.

── EL PROBLEMA QUE CIERRA ──────────────────────────────────────────────────────────
La obra 4 hizo que el agente recupere su conversación tras reiniciar. Cuando NO puede
—store del CLI rotado, proyecto movido, archivo borrado— cae a sesión nueva y emite la
causa SELLADA `sesion_perdida` (F1c). Correcto. Pero esa causa **moría en el backend**:
`stream_chat.py` leía el annex del `:8926` y de todo él sacaba `turno_id` y nada más.

El usuario seguía escribiendo creyendo que el agente recuerda lo de ayer, y estaba en
cero. **Perder memoria en silencio es peor que perderla con aviso.**

── EL CAMINO COMPLETO, MEDIDO ANTES DE TOCAR NADA ──────────────────────────────────
  1. `cli_brain/sesiones.py:784`     emite la causa (`evidencia.guard = sesion_perdida`)
  2. `cli_brain/server.py:104-116`   la emite SÓLO si venía del mapa, y UNA SOLA VEZ
                                     (`sesion.perdida_reportada`) — el guard ya existía
  3. `cli_brain/server.py:635-640`   viaja en `annex.sesion.causa` del turno EXITOSO
  4. `stream_chat.py:382-384`        ⛔ **ACÁ MORÍA** — del annex sólo salía `turno_id`
  5. `router.py:2506`                el SSE no tenía canal para ella
  6. `sala.html:3618`                la Sala no la escuchaba

Los eslabones 4·5·6 son esta obra. Los 1·2·3 ya estaban y NO se tocaron: la prueba es
que V2 no agrega ningún guard nuevo y sigue dando «una sola vez».

── DÓNDE ESTABA EL COPY (medido, no redactado) ─────────────────────────────────────
`cuarto.semaforo.js:112` — «Se rearmó la conversación» / «Conversation restarted», con
sus dos idiomas, escrito desde F4b y **sin un solo consumidor**. Acá no nace copy nuevo.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BACKEND = ROOT / "product" / "backend"
for _p in (str(HERE), str(ROOT / "platform"), str(BACKEND)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

ARNES = ROOT / "product" / "app" / "design" / "sala" / "arnes_costura_obra6.mjs"
SALA = ROOT / "product" / "app" / "design" / "sala" / "sala.html"

# [Convergencia · superficie 7 · paso 6] LA SALA VIEJA SE BORRÓ.
# Esta vara medía, entre otras cosas, texto de `sala/sala.html`. Esa pantalla ya no existe:
# su trabajo se rescató en la v2 y el resto murió con ella. La mitad que medía la Sala se
# SALTEA diciéndolo —no se borra la vara, porque el RESTO de lo que mide sigue vivo— y no
# se finge verde: un checkeo sin objeto es un salteo, jamás un ✓.
SALA_VIVA = SALA.exists()

STREAM = BACKEND / "app" / "phase1" / "stream_chat.py"
ROUTER = BACKEND / "app" / "phase1" / "router.py"
SEMAFORO = ROOT / "product" / "app" / "design" / "cuarto" / "cuarto.semaforo.js"
I18N = ROOT / "product" / "app" / "design" / "i18n.js"

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


def seccion(t: str) -> None:
    print(f"\n── {t} " + "─" * max(0, 74 - len(t)))


# ══════════════════════════════════════════════════════════════════════════════════════
# EL STUB DEL `:8926` — el annex REAL, copiado por valor de `server.py:625-641`
# ══════════════════════════════════════════════════════════════════════════════════════
# Se copia la FORMA y no se importa el server: si alguien cambia el contrato del annex,
# esta vara tiene que enterarse rompiéndose, no adaptarse sola.
def _chunk(texto: str, annex: dict) -> str:
    return "data: " + json.dumps({
        "choices": [{"delta": {"content": texto}}],
        "aleph_cli_brain": annex,
    }) + "\n\n"


_ANNEX_PERDIDA = {
    "turno_id": "T-vara-obra6",
    "sesion": {"id": "S-nuevo", "turno": 1, "incremental": False, "rehecha": False,
               "mensajes_enviados": 3, "restaurada": True,
               "causa": {"causa": "sesion_perdida", "estado": "roto",
                         "detalle": "la sesión restaurada del mapa ya no existía",
                         "evidencia": {"guard": "sesion_perdida", "sesion_id": "S-viejo"},
                         "reintentable": True, "fuente": "cli"}},
}
#: El turno NORMAL: la sesión se recuperó. `causa` es None, `restaurada` puede ser True.
_ANNEX_OK = {
    "turno_id": "T-vara-obra6",
    "sesion": {"id": "S-viejo", "turno": 2, "incremental": True, "rehecha": False,
               "mensajes_enviados": 1, "restaurada": True, "causa": None},
}


def _tirar(annex: dict) -> list:
    """Corre el bucle REAL de `_stream_openai` sobre un cuerpo fabricado y junta los yields.

    No se levanta un HTTP: se le da a la función el iterador de líneas que `urlopen`
    habría devuelto. El bucle que se ejercita es el de producción, sin copiarlo.
    """
    import app.phase1.stream_chat as SC

    cuerpo = (_chunk("hola", annex) + "data: [DONE]\n\n").encode("utf-8")

    class _Resp:
        def __iter__(self):
            return iter(cuerpo.splitlines(keepends=True))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return cuerpo

    _orig = SC.urllib.request.urlopen
    SC.urllib.request.urlopen = lambda *a, **k: _Resp()          # type: ignore[assignment]
    try:
        return list(SC._stream_openai(                            # noqa: SLF001
            "http://127.0.0.1:8926/v1", "claude-code-cli", "", None, "hola",
            700, 0.0))
    finally:
        SC.urllib.request.urlopen = _orig                         # type: ignore[assignment]


def main() -> int:
    print("=" * 80)
    print("VARA · OBRA 6 · EL AVISO DE MEMORIA PERDIDA (G-6)")
    print("=" * 80)

    # ══ V1a · EL ESLABÓN QUE MORÍA: stream_chat emite la causa ═══════════════════════
    seccion("V1a · la causa sobrevive a `stream_chat` (el eslabón que moría)")
    salida = _tirar(_ANNEX_PERDIDA)
    kinds = [k for k, _ in salida]
    check("V1a `stream_chat` emite el canal `sesion_perdida`",
          "sesion_perdida" in kinds, str(kinds))
    _payload = next((json.loads(v) for k, v in salida if k == "sesion_perdida"), None)
    check("V1a …con la causa del vocabulario SELLADO",
          bool(_payload) and _payload.get("causa") == "sesion_perdida", str(_payload))
    check("V1a …y `reintentable` viaja tal como lo selló el vocabulario (la Sala NO lo "
          "deriva del nombre — obra 5)",
          bool(_payload) and _payload.get("reintentable") is True, str(_payload))
    check("V1a el turno NO se rompe: el texto del modelo sale igual",
          ("token", "hola") in salida, str(salida))
    check("V1a y el `turno_id` sigue saliendo (no se pisó el canal de F4b)",
          ("turno", "T-vara-obra6") in salida, str(kinds))

    # ══ V1b · EL ROUTER LE DA CANAL SSE ══════════════════════════════════════════════
    seccion("V1b · el router traduce el canal a un frame SSE propio")
    _rt = ROUTER.read_text(encoding="utf-8")
    check("V1b `router.py` tiene el frame `type: sesion_perdida`",
          'kind == "sesion_perdida"' in _rt and '"type": "sesion_perdida"' in _rt)
    check("V1b …y va ANTES del `full.append`: es un dato del turno, no texto de la "
          "respuesta (si cayera al acumulador, metería un JSON crudo en lo que se lee)",
          _rt.index('kind == "sesion_perdida"') < _rt.index("full.append(tok)"))

    # ══ V3 · EL CAMINO NORMAL, BYTE-COMPARABLE ═══════════════════════════════════════
    # Va antes que V1c porque es la que protege: si el turno bueno cambió, nada de lo
    # demás importa.
    seccion("V3 · sesión que SÍ se recupera → cero aviso, y el resto byte-comparable")
    _ok = _tirar(_ANNEX_OK)
    check("V3 con `causa: None` NO se emite ningún aviso",
          "sesion_perdida" not in [k for k, _ in _ok], str([k for k, _ in _ok]))
    _sin_annex = _tirar({"turno_id": "T-vara-obra6"})
    check("V3 y sin `sesion` en el annex tampoco (el turno de un proveedor que no es CLI)",
          "sesion_perdida" not in [k for k, _ in _sin_annex], str([k for k, _ in _sin_annex]))
    check("V3 ★ BYTE-COMPARABLE: el turno normal emite EXACTAMENTE lo mismo con y sin "
          "el campo `sesion` en el annex",
          _ok == _sin_annex, f"{_ok} vs {_sin_annex}")
    _perd_sin_aviso = [x for x in salida if x[0] != "sesion_perdida"]
    check("V3 ★ y el turno CON memoria perdida es byte-comparable al normal salvo por el "
          "aviso: el arreglo AGREGA un canal, no cambia el turno",
          _perd_sin_aviso == _ok, f"{_perd_sin_aviso} vs {_ok}")

    # ══ V2 · UNA SOLA VEZ ════════════════════════════════════════════════════════════
    seccion("V2 · una sola vez por sesión afectada — y el guard NO es nuevo")
    _srv = (HERE / "cli_brain" / "server.py").read_text(encoding="utf-8")
    check("V2 el guard vive en `cli_brain/server.py` y es de la obra 4, no de ésta",
          "sesion.perdida_reportada" in _srv and "una sola vez" in _srv)
    check("V2 …y la condición es la sellada: sólo si venía del mapa Y no se reportó antes",
          "if not sesion.restaurada or sesion.perdida_reportada:" in _srv)
    if not SALA_VIVA:
        print("  ~ SALTEADO: la Sala vieja se borró (paso 6) — esta mitad no tiene objeto")
        return
    _sala = SALA.read_text(encoding="utf-8")
    check("V2 ★ la Sala NO agrega un contador propio: un segundo lugar que decide lo "
          "mismo se desincroniza (la regla de `_causa_de_error`, obra B)",
          "avisoMemoriaVisto" not in _sala and "memoriaPerdidaYaAvisada" not in _sala)

    # ══ EL COPY SALE DEL DICCIONARIO, NO DE LA SALA ══════════════════════════════════
    seccion("copy · del diccionario único, jamás escrito a mano en la superficie")
    _sem = SEMAFORO.read_text(encoding="utf-8")
    check("copy `sesion_perdida` ya tenía su entrada en el diccionario ÚNICO desde F4b",
          "sesion_perdida:" in _sem and "Se rearmó la conversación" in _sem)
    check("copy ★ la Sala lo consume por `Sem.caraDeCausa` — el mismo derivador que el "
          "resto de las superficies, no una cadena propia",
          "Sem.caraDeCausa({ causa:'sesion_perdida'" in _sala)
    _i18n = I18N.read_text(encoding="utf-8")
    check("copy las claves de la frase de contexto están en i18n.js, en los DOS idiomas",
          _i18n.count('"sala.sesion.perdida"') == 2 and
          _i18n.count('"sala.sesion.sinmemoria"') == 2,
          f'{_i18n.count(chr(34) + "sala.sesion.perdida" + chr(34))} / '
          f'{_i18n.count(chr(34) + "sala.sesion.sinmemoria" + chr(34))}')

    # ══ EL FRENTE, EN DOM REAL ═══════════════════════════════════════════════════════
    seccion("V1c · V4 · V5 — el DOM real, medido por el arnés en WebKit")
    corrida = subprocess.run(["node", str(ARNES)], cwd=ROOT, text=True, capture_output=True,
                             timeout=600, env=dict(os.environ))
    if corrida.returncode != 0:
        check("el arnés del frente corre", False, (corrida.stderr or "")[-400:])
        print(f"\n=== {PASSED} passed, {FAILED} failed ===")
        return 1
    try:
        A = json.loads(corrida.stdout)
    except json.JSONDecodeError:
        check("el arnés del frente devuelve JSON", False, (corrida.stdout or "")[-300:])
        print(f"\n=== {PASSED} passed, {FAILED} failed ===")
        return 1

    check("el arnés no dejó errores de página", not A["errores_de_pagina"],
          str(A["errores_de_pagina"][:2]))

    # V1c — el aviso se VE
    _v1 = A["v1"]
    check("V1c ★ el aviso APARECE en el DOM real (no «la función corrió»: un nodo nuevo)",
          _v1["despues"] > _v1["antes"] and len(_v1["nuevas"]) == 1,
          f'antes={_v1["antes"]} después={_v1["despues"]}')
    _txt = (_v1["nuevas"][0]["texto"] if _v1["nuevas"] else "")
    check("V1c …y dice el copy del diccionario, no un string inventado",
          "Se rearmó la conversación" in _txt, _txt[:90])
    check("V1c …y dice que NO recuerda: el título solo no alcanzaba para que la persona "
          "entienda que está en cero",
          "arranca de cero" in _txt, _txt[:90])

    # V2 (frente) — el front no inventa repeticiones
    check("V2 ★ sin un segundo evento, el front NO agrega otro aviso",
          A["v2"]["sin_evento_nuevo"] == 0, str(A["v2"]))

    # V3 (frente) — cero aviso en el camino normal
    check("V3 ★ sin evento, la Sala no pinta NADA (cero aviso en el turno bueno)",
          A["v3"]["antes"] == 0 and A["v3"]["despues"] == 0, str(A["v3"]))

    # V4 — no colapsa con los estados de la obra 5
    _v4 = A["v4"]
    check("V4 el derivador de la obra 5 sigue dando sus tres estados",
          _v4["hay_costura"] and {_v4["fail"], _v4["nocorrio"], _v4["held"]} ==
          {"fail", "nocorrio", "held"}, str(_v4))
    check("V4 ★ el aviso NO entra por la maquinaria de estados de la costura: su nodo no "
          "lleva ninguna clase `.ac-act.*`, así que es imposible confundirlo con un fallo, "
          "un «no corrió» o un gate reteniendo",
          _v4["lleva_clase_de_estado"] is False, str(_v4["nodo_aviso"]))
    check("V4 el nodo es el de `vitals` — el MISMO tratamiento que `modelo_sustituido` "
          "(obra B), que ya está certificado como «no es un fallo»",
          (_v4["nodo_aviso"] or {}).get("clase") == "ac-vitals", str(_v4["nodo_aviso"]))
    # ⚠️ EL DATO QUE NO SE TAPA: el gris del aviso es el MISMO que el de `nocorrio`
    # (`rgb(160,160,166)`, obra 5). No se cambia —«cero paleta nueva», y es EL color de
    # `vitals`— y no colapsa porque no son el mismo elemento ni el mismo lugar. Queda
    # medido acá para que nadie lo descubra de nuevo creyendo que encontró algo.
    check("V4 (declarado) el aviso comparte el gris de `vitals` con `nocorrio`: se deja a "
          "propósito, y el discriminante es la CLASE, no el color",
          (_v4["nodo_aviso"] or {}).get("color") == "rgb(160, 160, 166)",
          str((_v4["nodo_aviso"] or {}).get("color")))
    check("V4 `alarma` sigue siendo True y NO se tocó: `sesion_perdida` también llega por "
          "el 409 del `:8926`, donde SÍ es un fallo — marcarla `sin_alarma` para este "
          "camino habría apagado el rojo del otro",
          _v4["alarma"] is True, str(_v4["alarma"]))

    # V5 — i18n
    _v5 = A["v5"]
    _es = (_v5["es"]["nuevas"] or [""])[0]
    _en = (_v5["en"]["nuevas"] or [""])[0]
    check("V5 ★ el aviso resuelve en ESPAÑOL", "Se rearmó la conversación" in _es, _es[:70])
    check("V5 ★ y en INGLÉS — el idioma cambia de verdad, no cae al fallback",
          "Conversation restarted" in _en and "Se rearmó" not in _en, _en[:70])
    check("V5 …y el inglés es EL DEL DICCIONARIO, no una traducción propia",
          (_v4["dic"] or {}).get("en") == "Conversation restarted", str(_v4["dic"]))

    print("\n     [invocación única del chequeo completo]  "
          "product/backend/.venv/bin/python qa/correr_varas.py")
    print(f"\n=== {PASSED} passed, {FAILED} failed ===")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
