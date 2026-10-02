"""ORDEN 4 · Unit de HERENCIA (apply_inheritance) + estante agrupado (group_shelf) — puro, sin DB.
Correr:  cd product/backend && ./.venv/bin/python app/phase1/test_memory_inheritance.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from app.phase1.memory_recall import (apply_inheritance, group_shelf, _is_confidential,
                                      _project_of, _kind_of)

_fail = []
def ok(c, label):
    print(("  ✓ " if c else "  ✗ ") + label)
    if not c: _fail.append(label)

def M(content, kind=None, source="agent", run_id=None, confidential=False, mid=None):
    meta = {}
    if kind: meta["kind"] = kind
    if run_id: meta["run_id"] = run_id
    if confidential: meta["confidential"] = True
    return {"id": mid or content, "content": content, "source": source, "meta": meta}

def contents(sel):
    return [m["content"] for m in sel]

# estante base: 1 pericia + 3 episódicas de 2 proyectos + 1 captura de usuario + 1 confidencial
SHELF = [
    M("Prefiere voseo", "skill"),                                       # pericia
    M("Deadline Nordvik 30 ago", "episodica", run_id="run-A", mid="e1"),# proyecto A
    M("Plano de Nordvik rev 3", "episodica", run_id="run-A", mid="e2"), # proyecto A
    M("Cliente Zephyr en Lima", "episodica", run_id="run-B", mid="e3"), # proyecto B
    M("Soy alérgico al maní", None, source="user", mid="u1"),           # captura usuario (sin kind)
    M("Password del build server", "episodica", run_id="run-A", confidential=True, mid="c1"),
]

print("== helpers ==")
ok(_is_confidential(M("x", confidential=True)) and not _is_confidential(M("x")), "confidential flag")
ok(_project_of(M("x", run_id="run-A")) == "run-A" and _project_of(M("x")) is None, "project = run_id")

print("== policy None → continuación (no acota) pero lo confidencial NUNCA viaja ==")
sel = apply_inheritance(SHELF, None)
ok("Prefiere voseo" in contents(sel) and "Deadline Nordvik 30 ago" in contents(sel), "None deja pasar todo")
ok("Password del build server" not in contents(sel), "confidencial fuera aun sin herencia")
ok(len(sel) == 5, "None: 6 - 1 confidencial = 5")

# REGRESIÓN review orden 6 (MEDIUM): un 'skill_only' PERSISTIDO en la receta corre en el A3-read de
# TODO run (antes que select_relevant_memories) → si apply_inheritance dropeara la captura EXPLÍCITA del
# usuario (source='user', "recordá esto"), rompería la doble-llave (always_sources nunca alcanzaría a
# rescatarla). Regla: source='user' viaja como la pericia bajo CUALQUIER política; sólo lo destilado
# (source='agent') es podable. La confidencial nunca viaja.
print("== 'skill_only' → pericia + captura EXPLÍCITA del usuario; sin episódica destilada ni confidencial ==")
for pol in ("skill_only", "skill", "solo_pericia", {"episodic": "none"}, {"skill_only": True}, {}):
    s = apply_inheritance(SHELF, pol)
    ok(set(contents(s)) == {"Prefiere voseo", "Soy alérgico al maní"},
       f"[solo pericia] via {pol!r} → pericia + la captura del usuario (nunca se cae 'lo guardé')")
    ok("Deadline Nordvik 30 ago" not in contents(s) and "Password del build server" not in contents(s),
       f"[solo pericia] via {pol!r} → sin episódica destilada (source='agent') ni confidencial")

print("== dict VACÍO / desconocido = default duro 'sólo pericia' (+ la captura de usuario, que siempre viaja) ==")
ok(set(contents(apply_inheritance(SHELF, 12345))) == {"Prefiere voseo", "Soy alérgico al maní"},
   "forma desconocida → fail-safe solo pericia (+ source='user')")

print("== '+ proyecto A' → pericia + episódica de run-A (no run-B, no confidencial) + captura de usuario ==")
sa = apply_inheritance(SHELF, {"projects": ["run-A"]})
ok("Prefiere voseo" in contents(sa), "pericia siempre")
ok("Deadline Nordvik 30 ago" in contents(sa) and "Plano de Nordvik rev 3" in contents(sa), "las 2 de run-A")
ok("Cliente Zephyr en Lima" not in contents(sa), "run-B NO entra")
ok("Password del build server" not in contents(sa), "la confidencial de run-A tampoco (no mezclable)")
ok("Soy alérgico al maní" in contents(sa), "la captura de usuario (source='user') viaja bajo CUALQUIER política")

print("== 'elegir entradas' → pericia + esas entradas por id (incluida una captura de usuario) ==")
se = apply_inheritance(SHELF, {"entries": ["e3", "u1"]})
ok(set(contents(se)) == {"Prefiere voseo", "Cliente Zephyr en Lima", "Soy alérgico al maní"},
   "pericia + e3 + u1 (por id), nada más")
sec = apply_inheritance(SHELF, {"entries": ["c1"]})
ok(set(contents(sec)) == {"Prefiere voseo", "Soy alérgico al maní"},
   "una entrada confidencial elegida por id IGUAL se excluye (queda pericia + captura de usuario)")

print("== combo proyecto + entradas = unión (+ la captura de usuario, siempre) ==")
scom = apply_inheritance(SHELF, {"projects": ["run-B"], "entries": ["e1"]})
ok(set(contents(scom)) == {"Prefiere voseo", "Cliente Zephyr en Lima", "Deadline Nordvik 30 ago", "Soy alérgico al maní"},
   "pericia + run-B (e3) + e1 elegida + captura de usuario")

print("== group_shelf: pericia / proyectos / sueltas, confidencial excluido ==")
g = group_shelf(SHELF)
ok(contents(g["skill"]) == ["Prefiere voseo"], "skill agrupada")
ok(set(g["projects"].keys()) == {"run-A", "run-B"}, "proyectos = run-A, run-B (la confidencial no crea grupo)")
ok(len(g["projects"]["run-A"]) == 2, "run-A tiene 2 (sin la confidencial)")
ok(contents(g["loose"]) == ["Soy alérgico al maní"], "la captura sin run_id = suelta")
ok(all("Password" not in c for grp in g["projects"].values() for c in contents(grp)), "confidencial en ningún grupo")

print("== bordes ==")
ok(apply_inheritance([], "skill_only") == [], "estante vacío → []")
ok(group_shelf([]) == {"skill": [], "projects": {}, "loose": []}, "group_shelf vacío")

print(f"\n{'ALL GREEN' if not _fail else 'FAILS: ' + str(_fail)}  ({len(_fail)} fallos)")
sys.exit(1 if _fail else 0)
