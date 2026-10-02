#!/usr/bin/env python3
"""Auditoría de claves HUÉRFANAS del mapa TM de i18n.js.

La clave del TM **es** el string español que sale del DOM. Cambiar el ES sin renombrar la
clave no rompe nada visible en castellano — rompe la traducción al inglés, EN SILENCIO.
Huérfana = clave que ya no aparece en ninguna fuente de product/app: una traducción muerta.

Es la única forma de cazar esa clase, y el número ABSOLUTO no dice nada (hay deuda vieja de
otras superficies). Lo que se mide es el DELTA con el mismo instrumento:

    python3 qa/audit_tm.py .                    # el árbol de trabajo
    git archive <base> product/app | tar -x -C /tmp/base && python3 qa/audit_tm.py /tmp/base

y el criterio es CERO huérfanas nuevas contra la unión de las ramas que se integran.
(Integración tanda B, 2026-07-27: base 220 · T6 239 · P10 221 · P8 222 · integrado 242,
unión 245 → 0 nuevas.)

Uso: audit_tm.py <raiz-del-arbol>"""
import re, sys, os, io, json

root = sys.argv[1]
i18n = os.path.join(root, "product/app/design/i18n.js")
src = io.open(i18n, encoding="utf-8").read()
lines = src.split("\n")
start = next(i for i,l in enumerate(lines) if l.strip().startswith("var TM = {"))
end   = len(lines)
tm = "\n".join(lines[start:end])

# claves: "…": o '…':  al principio de línea (ignora comentarios)
keys = []
for l in tm.split("\n"):
    s = l.strip()
    if s.startswith("//") or s.startswith("/*") or s.startswith("*"): continue
    m = re.match(r'''^(["'])(.*?)\1\s*:''', s)
    if m: keys.append(m.group(2))

# corpus: todo lo que puede pintar esa clave
corpus = []
for base, dirs, files in os.walk(os.path.join(root, "product/app")):
    dirs[:] = [d for d in dirs if d not in ("screenshots","node_modules",".venv")]
    for f in files:
        if f.endswith((".html",".js",".mjs")) and f != "i18n.js":
            try: corpus.append(io.open(os.path.join(base,f), encoding="utf-8", errors="ignore").read())
            except Exception: pass
blob = "\n".join(corpus)

def unesc(k):
    return k.replace("\\'","'").replace('\\"','"').replace("\\\\","\\")

orphans = [k for k in keys if unesc(k) not in blob]
print(json.dumps({"total_claves": len(keys), "huerfanas": len(orphans),
                  "lista": sorted(orphans)}, ensure_ascii=False))
