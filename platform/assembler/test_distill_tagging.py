"""ORDEN 2 · Unit del TAGGING skill|episódica + provenance en el destilador.

Puro (sin DB, sin modelo): prueba _classify_tag, _parse_distilled_memory y _build_distill_messages.
Correr:  ./product/backend/.venv/bin/python platform/assembler/test_distill_tagging.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))            # belt_resolver top-level
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from recipe_assembler import (_parse_distilled_memory as P, _build_distill_messages as B,
                              _classify_tag as C, _A3_DISTILL_MAX_ITEMS)

_fail = []
def ok(cond, label):
    print(("  ✓ " if cond else "  ✗ ") + label)
    if not cond:
        _fail.append(label)

print("== _classify_tag (kind, prov, recognized) ==")
ok(C("skill/hecho")   == ("skill", "hecho", True),          "skill/hecho")
ok(C("episodica/inferencia") == ("episodica", "inferencia", True), "episodica/inferencia")
ok(C("hecho")         == ("episodica", "hecho", True),      "[hecho] solo → kind default episodica")
ok(C("inferencia")    == ("episodica", "inferencia", True), "[inferencia] solo")
ok(C("skill")         == ("skill", "inferencia", True),     "[skill] solo → prov default inferencia")
ok(C("pericia")       == ("skill", "inferencia", True),     "sinónimo pericia→skill")
ok(C("hecho/skill")   == ("skill", "hecho", True),          "orden invertido")
ok(C("inferencia, episódica")[:2] == ("episodica", "inferencia"),  "acento + coma sep")
ok(C(" skill  hecho ") == ("skill", "hecho", True),         "espacios como sep")
ok(C("Python")        == ("episodica", "inferencia", False),"desconocido → recognized False + defaults")
ok(C("")              == ("episodica", "inferencia", False),"vacío → recognized False")

print("== _parse_distilled_memory ==")
r = P("- [skill/hecho] Prefiere SI\n- [episodica/inferencia] Logística\n- [episodica/hecho] Deadline 30 ago")
ok(len(r) == 3, "3 ítems two-axis")
ok(r[0] == {"content": "Prefiere SI", "provenance": "hecho", "kind": "skill"}, "ítem 0 shape completo")
ok(r[1]["kind"] == "episodica" and r[1]["provenance"] == "inferencia", "ítem 1 ejes")

bc = P("- [hecho] Se llama persona usuaria\n- [inferencia] Le gusta el detalle")
ok(bc[0]["kind"] == "episodica" and bc[0]["provenance"] == "hecho", "back-compat [hecho] → episodica/hecho")
ok(bc[1]["provenance"] == "inferencia", "back-compat [inferencia]")

ok(P("- Un dato sin etiqueta")[0] == {"content": "Un dato sin etiqueta",
    "provenance": "inferencia", "kind": "episodica"}, "bare → fail-safe episodica/inferencia")

unrec = P("- [Python] es un lenguaje")
ok(unrec[0]["content"] == "[Python] es un lenguaje", "corchete desconocido queda en el contenido")
ok(unrec[0]["kind"] == "episodica" and unrec[0]["provenance"] == "inferencia", "y usa defaults")

ok(P("- (ninguno)") == [] and P("NADA") == [] and P("") == [], "sentinelas/vacío → []")

# dedup + cap de ítems
dup = P("\n".join(["- [skill/hecho] X"] * 3))
ok(len(dup) == 1, "dedup por contenido")
manyx = "\n".join(f"- [episodica/hecho] dato {i}" for i in range(_A3_DISTILL_MAX_ITEMS + 4))
ok(len(P(manyx)) == _A3_DISTILL_MAX_ITEMS, f"cap a {_A3_DISTILL_MAX_ITEMS} ítems")

# fail-safe DURO: nunca sale un kind/prov fuera del dominio
for it in P("- [zzz/qqq] raro\n- [skill] a\n- bare b\n- [hecho] c"):
    ok(it["kind"] in ("skill", "episodica"), f"kind ∈ dominio ({it['kind']})")
    ok(it["provenance"] in ("hecho", "inferencia"), f"prov ∈ dominio ({it['provenance']})")

print("== _build_distill_messages ==")
msg = B("hola", "chau")[0]["content"]
ok("[tipo/origen]" in msg, "instrucción de formato de 2 ejes presente")
ok("skill" in msg and "episodica" in msg, "define skill y episodica")
ok("hecho" in msg and "inferencia" in msg, "conserva provenance hecho/inferencia")
ok("=== PEDIDO DEL USUARIO ===" in msg and "hola" in msg, "material citado (frontera de proveniencia)")
msg_shared = B("hola", "chau", shared=True)[0]["content"]
ok("COMPARTIR" in msg_shared or "OTROS agentes" in msg_shared, "variante shared conserva su meta")
msg_retry = B("hola", "chau", retry=True)[0]["content"]
ok("intento anterior" in msg_retry, "retry conserva su refuerzo")

print(f"\n{'ALL GREEN' if not _fail else 'FAILS: ' + str(_fail)}  ({'0' if not _fail else len(_fail)} fallos)")
sys.exit(1 if _fail else 0)
