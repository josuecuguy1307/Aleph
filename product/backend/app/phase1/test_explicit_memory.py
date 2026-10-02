#!/usr/bin/env python3
"""test_explicit_memory.py — Pieza 1 · el detector de captura explícita es determinista y CONSERVADOR.

Llave B (forense, sin DB/red): prueba que detect_capture DISPARA verbatim ante directivas de
captura reales y NO dispara ante pedidos de recall/preguntas (que ensuciarían la memoria).
Corre:  python3 .../test_explicit_memory.py   (o pytest)
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_REPO = _HERE.parents[4]
for _p in (str(_REPO / "product" / "backend"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.phase1.explicit_memory import (
    detect_capture, detect_forget, detect_correction, MAX_CAPTURE_CHARS,
)


# (prompt, expected_captured_substring_or_None)
CASES = [
    # ── POSITIVOS: directiva de captura + payload → captura verbatim ──
    ("recordá esto: el deadline es el 15 de mayo",           "el deadline es el 15 de mayo"),
    ("Recordá que prefiero respuestas cortas",               "prefiero respuestas cortas"),
    ("guardá estos datos: cliente Nordvik, código CENTINELA", "cliente Nordvik, código CENTINELA"),
    ("guarda esto: mi color favorito es el violeta",         "mi color favorito es el violeta"),
    ("anotá que el buque es el OVERSEAS HOUSTON",            "el buque es el OVERSEAS HOUSTON"),
    ("apuntá esto: reunión los martes 10am",                 "reunión los martes 10am"),
    ("remember that my name is persona usuaria",                       "my name is persona usuaria"),
    ("remember this: the API key rotates monthly",           "the API key rotates monthly",),
    ("save this: budget is 5000 USD",                        "budget is 5000 USD"),
    ("note that the client prefers email",                   "the client prefers email"),
    ("Por favor recordá esto: la premisa es no pagar sin OK", "la premisa es no pagar sin OK"),
    ("recordá: reunión mañana",                              "reunión mañana"),                 # ':' directo
    # multi-línea: sólo la línea de la directiva, NO el follow-up de tarea
    ("guardá esto: el deadline es 15 de mayo\nahora buscá vuelos a Quito", "el deadline es 15 de mayo"),
    # comillas envolventes se limpian
    ('recordá esto: "el pin es 4471"',                       "el pin es 4471"),

    # ── [ticket 24] BURIED-IN-CONTEXT: el "recordá esto" enterrado ya NO cae al destilador ──
    # (a) ANAFÓRICA: el hecho va ANTES de un "recordá esto/eso" que CIERRA el mensaje (cola trivial ok)
    ("el grillete GY-24-004 quedó en cuarentena por óxido, no usarlo hasta nueva inspección. recordá esto.",
     "el grillete GY-24-004 quedó en cuarentena por óxido, no usarlo hasta nueva inspección"),
    ("estuvimos toda la mañana con los grilletes. el mínimo operativo es 6. recordá esto, ¿ok?",
     "el mínimo operativo es 6"),                             # ← caso de diseño exacto del ticket
    ("el buque zarpa el jueves 12. guardá esto porfa",       "el buque zarpa el jueves 12"),
    # (b) FILLER intercalado entre verbo y conector/':'
    ("recordá bien esto: el grillete GY-24-004 está en cuarentena", "el grillete GY-24-004 está en cuarentena"),
    ("recordá una cosa: la regla de Sofía es no usar vencidos", "la regla de Sofía es no usar vencidos"),
    ("recordá por las dudas que el buque es el OVERSEAS HOUSTON", "el buque es el OVERSEAS HOUSTON"),
    # (b2) SUBJUNTIVO recuerdes/recuerde ("quiero que recuerdes esto: X")
    ("quiero que recuerdes esto: el mínimo operativo es 6",  "el mínimo operativo es 6"),
    ("necesito que recuerde que el cliente es Nordvik",      "el cliente es Nordvik"),
    # (c) conector "lo del/de"
    ("recordá lo del código de acceso: es 4471",             "código de acceso: es 4471"),

    # ── NEGATIVOS: recall / preguntas / nada → None ──
    ("¿recordás el trato que hicimos?",                      None),   # 'recordás' tú/voseo presente = recall
    ("recordá esto, ¿ok?",                                   None),   # anafórico SIN hecho antes → None
    ("recordame la premisa que fijamos al arrancar",         None),   # enclítico = recall
    ("recordame que era la palabra clave",                   None),
    ("¿podés recordarme la regla de oro?",                   None),   # infinitivo+me = recall
    ("¿te acordás de lo que hablamos?",                       None),  # pregunta, verbo no-captura
    ("recuérdame el nombre del cliente",                      None),  # enclítico estándar
    ("remind me what the deadline was",                       None),
    ("¿qué te dije que recordaras?",                          None),  # pregunta de recall
    ("calculá el sharpe del portfolio",                       None),  # sin verbo de captura
    ("necesito que me ayudes con un email",                   None),  # 'que' sin verbo de captura
    ("recordá esto",                                          None),  # sin payload inline → no determinista
    ("",                                                      None),
    (None,                                                    None),
]


def _run():
    ok = 0
    for prompt, expected in CASES:
        got = detect_capture(prompt)
        if expected is None:
            passed = got is None
        else:
            passed = got == expected
        label = (prompt or "∅")[:52].replace("\n", "⏎")
        print(f"  [{'PASS' if passed else 'FAIL'}] {label!r:56} → {got!r}")
        if not passed:
            print(f"        expected {expected!r}")
        ok += passed
    return ok, len(CASES)


def test_detect_capture_positives_and_recall_negatives():
    ok, total = _run()
    assert ok == total, f"detector: {ok}/{total} — hay falsos-positivos (recall capturado) o falsos-negativos"


def test_payload_is_capped():
    huge = "recordá esto: " + ("X" * (MAX_CAPTURE_CHARS + 500))
    got = detect_capture(huge)
    assert got is not None and len(got) <= MAX_CAPTURE_CHARS, "el payload debe capearse a MAX_CAPTURE_CHARS"


def test_determinism_same_input_same_output():
    p = "guardá estos datos: cliente Nordvik, deadline 15 de mayo, código CENTINELA"
    outs = {detect_capture(p) for _ in range(20)}
    assert len(outs) == 1 and next(iter(outs)) == "cliente Nordvik, deadline 15 de mayo, código CENTINELA", \
        "determinista: mismo input → mismo output SIEMPRE (jamás None ni variación)"


# ── PIEZA 2 · OLVIDO (destructivo → los negativos son de SEGURIDAD: un falso olvido BORRA datos) ──
FORGET_CASES = [
    # POSITIVOS
    ("olvidá lo del deadline",                       {"mode": "match", "target": "deadline"}),
    ("borrá lo que guardaste sobre Nordvik",         {"mode": "match", "target": "Nordvik"}),
    ("olvidá que el cliente es Nordvik",             {"mode": "match", "target": "el cliente es Nordvik"}),
    ("forget about the deadline",                    {"mode": "match", "target": "the deadline"}),
    ("delete the memory of the API key",             {"mode": "match", "target": "the API key"}),
    ("olvidá todo",                                  {"mode": "all"}),
    ("borrá toda la memoria",                        {"mode": "all"}),
    ("forget everything",                            {"mode": "all"}),
    ("clear my memory",                              {"mode": "all"}),
    # NEGATIVOS DE SEGURIDAD (deben ser None — NO borrar)
    ("no te olvides del deadline",                   None),   # negación = KEEP, no borres
    ("don't forget the meeting",                     None),
    ("no olvides que el cliente es Nordvik",         None),
    ("olvidá eso",                                   None),   # deíctico sin blanco → no determinista
    ("¿te olvidaste de algo?",                       None),   # pregunta
    ("necesito olvidarme de mi ex",                  None),   # no es op de memoria (infinitivo)
    ("recordá esto: el deadline es mayo",            None),   # es captura, no olvido
    ("calculá el sharpe",                            None),
    ("",                                             None),
    (None,                                           None),
]

CORRECTION_CASES = [
    # POSITIVOS (requieren el marcador con dos-puntos)
    ("corregí: el cliente es Vestas, no Nordvik",    {"new": "el cliente es Vestas", "old": "Nordvik"}),
    ("corrección: el deadline es el 20 de mayo",     {"new": "el deadline es el 20 de mayo", "old": None}),
    ("correction: my budget is 8000, not 5000",      {"new": "my budget is 8000", "old": "5000"}),
    # NEGATIVOS (sin marcador → NO es corrección de memoria)
    ("corregí este código por favor",               None),   # TAREA, no corrección de memoria
    ("corregime la tarea de física",                None),
    ("en realidad no sé la respuesta",              None),   # casual, no marcador
    ("actually I changed my mind",                  None),
    ("recordá esto: X",                             None),
    ("",                                            None),
]


def _run_dict_cases(fn, cases):
    ok = 0
    for prompt, expected in cases:
        got = fn(prompt)
        passed = got == expected
        label = (prompt or "∅")[:48].replace("\n", "⏎")
        print(f"  [{'PASS' if passed else 'FAIL'}] {label!r:52} → {got!r}")
        if not passed:
            print(f"        expected {expected!r}")
        ok += passed
    return ok, len(cases)


def test_detect_forget_positives_and_safety_negatives():
    ok, total = _run_dict_cases(detect_forget, FORGET_CASES)
    assert ok == total, f"forget: {ok}/{total} — un falso-positivo BORRARÍA datos del usuario"


def test_detect_correction_requires_explicit_marker():
    ok, total = _run_dict_cases(detect_correction, CORRECTION_CASES)
    assert ok == total, f"correction: {ok}/{total}"


if __name__ == "__main__":
    print("── CAPTURA (pieza 1) ──")
    ok, total = _run()
    print("\n── OLVIDO (pieza 2) ──")
    fok, ftot = _run_dict_cases(detect_forget, FORGET_CASES)
    print("\n── CORRECCIÓN (pieza 2) ──")
    cok, ctot = _run_dict_cases(detect_correction, CORRECTION_CASES)
    tot_ok, tot_all = ok + fok + cok, total + ftot + ctot
    print(f"\n  {tot_ok}/{tot_all} verdes")
    try:
        test_payload_is_capped(); print("  ✓ payload capped")
        test_determinism_same_input_same_output(); print("  ✓ determinismo (20×)")
    except AssertionError as e:
        print(f"  ✗ {e}"); raise SystemExit(1)
    raise SystemExit(0 if tot_ok == tot_all else 1)
