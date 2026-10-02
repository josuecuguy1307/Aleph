#!/usr/bin/env python3
"""Vara · ESTANDARIZACIÓN DE IDIOMAS (2026-09-11): el system le dice al modelo en qué idioma,
con qué tono y con qué registro contestar — y ese texto CRUZA el borde, por los dos transportes.

    product/backend/.venv/bin/python platform/assembler/verify_idioma_registro.py
    product/backend/.venv/bin/python platform/assembler/verify_idioma_registro.py --caer

── QUÉ CIERRA ──────────────────────────────────────────────────────────────────────
Había tres lugares que nombraban el idioma («en el idioma del usuario») y ninguno hablaba de
tono ni de registro; uno lo pedía escrito en voseo en la misma línea. Ahora hay UN bloque
(`_build_idioma_block`) pegado al framing, y esta vara mide que:

  A · el bloque existe, nombra el idioma de respaldo correcto y no trae voseo;
  B · en el LOOP REAL (`assemble_and_run` con el LLM stubbeado) el `messages[0]` que va al
      modelo lo lleva, después del framing y antes del [PLAN];
  C · el transporte CLI (`prompt_bridge.render_prompt`) lo pone en la cabeza del prompt —
      el mismo texto le llega a Claude Code / Codex / Grok;
  D · el CENSO: los armadores de prompt que le hablan al modelo (Capa C, domain, el bloque
      de tools del bridge, los framings del catálogo, los agentes del catálogo) tienen CERO
      voseo, con el patrón ampliado de la sesión.

── LA PRUEBA DE CAÍDA ──────────────────────────────────────────────────────────────
`--caer` apaga el bloque (monkeypatch a "") y EXIGE que B y C se pongan en rojo. Una vara
que no puede caer no está midiendo.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))
sys.path.insert(0, str(_THIS / "cli_brain"))
import recipe_assembler as ra          # noqa: E402
import prompt_bridge as PB             # noqa: E402

REPO_ROOT = _THIS.parents[1]
CALC_BELT_REF = "platform/assembler/fixtures/belt-calc.mcp.json"
CAER = "--caer" in sys.argv
_passed = 0
_failed = 0

# El patrón AMPLIADO del censo de la sesión (el del acta era un punto de partida): -á/-é/-í
# imperativos de vos con tilde, presentes -ás/-és/-ís, `vos`/`sos`, y enclíticos frecuentes.
_VOSEO = re.compile(
    r"(?<![A-Za-zÁÉÍÓÚÑáéíóúñ])(?:vos|sos|tenés|podés|querés|sabés|hacés|decís|"
    r"decime|contame|fijate|acordate|hacelo|hacela|ponelo|ponela|usalo|usala|usalos|dejalo|"
    r"logueate|mostrame|avisame|escribime|pasame|mandame|"
    r"mirá|probá|pegá|copiá|tocá|poné|hacé|leé|corré|volvé|respondé|devolvé|extraé|traé|"
    r"escribí|elegí|abrí|seguí|decí|vení|salí|subí|repetí|corregí|resumí|imprimí|"
    r"[a-záéíóúñ]{3,}(?:ás|és|ís)|[a-záéíóúñ]{3,}(?:cá|gá|tá|ná|rá|lá|sá|zá|dá|má|pá|bá|vá|ñá|já|quá))"
    r"(?![A-Za-zÁÉÍÓÚÑáéíóúñ])", re.I)
_NO_VOSEO = {"más","además","atrás","detrás","jamás","demás","estás","quizás","después","través",
             "interés","inglés","francés","estrés","revés","país","así","está","será","irá","podrá",
             "habrá","tendrá","hará","dirá","vendrá","estará","quedará","seguirá","llegará","pasará",
             "aparecerá","mostrará","cerrará","abrirá","volverá","verás","podrás","tendrás","dará",
             "acá","allá","quizá","ojalá","mamá","papá","sofá","sabrá","valdrá","querrá","cabrá",
             "saldrá","pondrá","entrará","servirá","permitirá","recibirá","generará","funcionará",
             "tardará","cambiará","necesitará","usará","tomará","terminará","empezará","pedirá",
             "devolverá","faltará","ayudará","deberá","esperará","leerá","escribirá","responderá",
             "llamará","buscará","encontrará","aprenderá","recordará","creará","borrará","dejará",
             "guardará","cargará","correrá","saldrá","sonará","traerá","vivirá","sufrirá"}


def voseo_en(texto: str) -> list:
    out = []
    for m in _VOSEO.finditer(texto):
        w = m.group(0)
        if w.lower() in _NO_VOSEO or w.isupper() and len(w) <= 3:
            continue
        # futuro regular: infinitivo + á (mirará, leerá, abrirá) — se excluye por forma
        wl = w.lower()
        if wl.endswith(("ará", "erá", "irá")) and wl[:-1].endswith(("ar", "er", "ir")) and \
                wl[:-1] not in ("mir", "esper", "gener", "consider", "recuper", "oper", "prepar", "compar"):
            continue
        out.append(w)
    return out


def check(name: str, cond: bool, detail: str = "") -> None:
    global _passed, _failed
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if cond:
        _passed += 1
    else:
        _failed += 1


def caediza(name: str, cond: bool, detail: str = "") -> None:
    if CAER:
        check(f"[caída] NO se cumple sin el bloque · {name}", not cond, detail)
    else:
        check(name, cond, detail)


def _recipe() -> dict:
    return {
        "schema_version": "v1",
        "meta": {"name": "idioma-registro", "nicho": "test"},
        "model": {"primary": "stub", "base_url": "http://127.0.0.1:0/v1",
                  "temperature": 0, "max_tokens": 64, "max_turns": 2},
        "belt": {"belt_ref": CALC_BELT_REF, "tool_filters": {"calc": None}},
        "framing": {"inline": "Eres un test."},
        "rag": {"enabled": False}, "keys": {}, "gates": {},
    }


def _correr(lang: str) -> dict:
    """El loop real con el LLM stubbeado: devuelve lo que el modelo RECIBIÓ."""
    capt: dict = {}

    def fake_chat(messages, tools, base_url, model, api_key, max_tokens, temperature, **kw):
        capt.setdefault("messages", [dict(m) for m in messages])
        return {"choices": [{"finish_reason": "stop",
                             "message": {"role": "assistant", "content": "listo"}}]}

    orig = ra._asm._chat
    ra._asm._chat = fake_chat
    try:
        out = ra.assemble_and_run(_recipe(), "hello there", repo_root=REPO_ROOT, lang=lang)
    finally:
        ra._asm._chat = orig
    capt["out"] = out
    return capt


def bloque_A() -> None:
    b_es, b_en = ra._build_idioma_block("es"), ra._build_idioma_block("en")
    check("A1 el bloque existe y se titula", b_es.startswith("\n\n## Idioma, tono y registro"))
    check("A2 dice idioma DEL USUARIO, tono y registro (las tres cosas)",
          "idioma de su último mensaje" in b_es and "tono" in b_es and "registro" in b_es)
    check("A6 petición explícita y mensaje actual tienen prioridad sobre UI e historial",
          "pide explícitamente un idioma" in b_es and "por encima del idioma de la interfaz" in b_es)
    check("A7 español e inglés neutros, sin imponer español por la UI",
          "español neutro" in b_es and "inglés estándar neutro" in b_es
          and "nunca impongas español" in b_es)
    check("A3 el respaldo sigue a `lang`: es → español, en → inglés",
          "usa español" in b_es and "usa inglés" in b_en)
    check("A4 `lang` raro o vacío no rompe (pt-BR → portugués, None → español, xx → xx)",
          "usa portugués" in ra._build_idioma_block("pt-BR")
          and "usa español" in ra._build_idioma_block(None)
          and "usa xx" in ra._build_idioma_block("xx"))
    check("A5 el bloque mismo no trae voseo", voseo_en(b_es) == [], str(voseo_en(b_es)))


def bloque_B_C() -> None:
    for lang, nombre in (("en", "inglés"), ("es", "español")):
        capt = _correr(lang)
        msgs = capt.get("messages") or []
        sysm = msgs[0]["content"] if msgs and msgs[0].get("role") == "system" else ""
        caediza(f"B1[{lang}] el system que RECIBE el modelo lleva el bloque",
                "## Idioma, tono y registro" in sysm, sysm[:80].replace("\n", "⏎"))
        caediza(f"B2[{lang}] …con el respaldo correcto ({nombre})", f"usa {nombre}" in sysm)
        if "## Idioma, tono y registro" in sysm:
            i_capa = sysm.find("Escucha el pedido LITERAL")
            i_bloq = sysm.find("## Idioma, tono y registro")
            i_plan = sysm.find("[PLAN]")
            check(f"B3[{lang}] va DESPUÉS del framing y ANTES del [PLAN]",
                  0 <= i_capa < i_bloq and (i_plan < 0 or i_bloq < i_plan),
                  f"capa={i_capa} bloque={i_bloq} plan={i_plan}")
        check(f"B4[{lang}] el run sale (el bloque no rompe el turno)",
              capt["out"].get("ok") is True, str(capt["out"].get("error"))[:100])
        # C · el transporte CLI: el mismo messages[] pasa por el bridge
        prompt = PB.render_prompt(msgs, [])
        caediza(f"C1[{lang}] el bridge del CLI pone el bloque en la cabeza del prompt",
                "## Idioma, tono y registro" in prompt.split("=== CONVERSACIÓN ===")[0])
        check(f"C2[{lang}] el bridge etiqueta en neutro ([Tú], no [Vos])",
              "[Vos" not in prompt and "no tú)" in PB._tools_block([{"function": {"name": "t", "description": "d"}}]))


def bloque_D() -> None:
    fuentes = {
        "Capa C": ra._CAPA_C,
        "domain research": ra._RESEARCH_DOMAIN,
        "bloque de tools del bridge": PB._tools_block([{"function": {"name": "t", "description": "d"}}],
                                                       tool_choice="required"),
        "cola del bridge": PB.render_prompt([{"role": "system", "content": "s"},
                                             {"role": "user", "content": "u"}], []),
    }
    for p in sorted((REPO_ROOT / "catalog" / "templates").glob("*/framing-*.md")):
        fuentes[f"catálogo · {p.parent.name}/{p.name}"] = p.read_text(encoding="utf-8")
    for p in sorted(q for q in (REPO_ROOT / "catalog" / "agents").glob("*.config.json") if not q.name.startswith("agent-")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:                                  # noqa: BLE001
            continue
        fr = (d.get("framing") or {})
        txt = fr.get("inline") if isinstance(fr, dict) else ""
        if txt:
            fuentes[f"catálogo · agents/{p.name}"] = txt
    for nombre, texto in fuentes.items():
        v = voseo_en(texto)
        check(f"D · cero voseo en «{nombre}»", v == [], ", ".join(v[:6]))


def main() -> int:
    print("=== vara · idioma, tono y registro en el system" + (" · PRUEBA DE CAÍDA" if CAER else "") + " ===\n")
    bloque_A()                                        # el bloque en sí, antes de apagarlo
    if CAER:
        ra._build_idioma_block = lambda lang: ""      # el bloque apagado: B y C deben caer
    bloque_B_C()
    bloque_D()
    print(f"\n{_passed} verdes · {_failed} rojas")
    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
