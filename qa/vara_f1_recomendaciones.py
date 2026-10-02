#!/usr/bin/env python3
"""VARA · F2·E — las recomendaciones por workspace: cobertura total y forma.

QUÉ CUIDA. `catalog/connectors/workspace-recommendations.json` dice, para cada conector curado,
en qué workspaces se recomienda. El defecto que esta vara existe para impedir es el **hueco que
se ve como decisión**: un conector nuevo en `onboarding/` que nadie clasificó queda sin
recomendación, la cara no lo ofrece en ninguna parte, y eso es indistinguible de «se decidió que
no va en ninguno». Por eso la cobertura tiene que ser TOTAL: `[]` es una decisión declarada, la
ausencia de la clave es un olvido.

Es la misma familia que Fase 0 pagó dos veces con el censo: decía 10 MCP curados cuando eran 45,
y 7 con key cuando eran 21. Un catálogo que no se mide contra el árbol miente por omisión.

    python3 qa/vara_f1_recomendaciones.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

_RAIZ = Path(os.environ.get("ALEPH_VARA_RAIZ") or Path(__file__).resolve().parent.parent)
_ONB = _RAIZ / "catalog" / "connectors" / "onboarding"
_REC = _RAIZ / "catalog" / "connectors" / "workspace-recommendations.json"

_verdes: list[str] = []
_rojas: list[str] = []


def _ok(nombre: str, cond: bool, detalle: str = "") -> None:
    (_verdes if cond else _rojas).append(nombre)
    print(f"  {'✅' if cond else '❌'} {nombre}" + (f"  — {detalle}" if detalle and not cond else ""))


def main() -> int:
    if not _REC.is_file():
        # ASÍ CAE CONTRA UN ÁRBOL SIN LA OBRA. No se concluye nada: no hay qué medir.
        print(f"❌ no existe {_REC.relative_to(_RAIZ)} — ¿estás en un árbol sin la obra?")
        return 1
    rec = json.loads(_REC.read_text(encoding="utf-8"))
    decl = rec.get("recomendaciones") or {}
    ws_validos = set(rec.get("workspaces") or [])
    del_arbol = {p.stem for p in _ONB.glob("*.json")}

    print(f"── EL TERRENO ────────────────────────────────────────────────────────")
    print(f"  conectores en onboarding/ : {len(del_arbol)}")
    print(f"  con recomendación declarada: {len(decl)}")
    print(f"  workspaces declarados      : {len(ws_validos)} → {sorted(ws_validos)}")

    print(f"\n── COBERTURA (el hueco no puede parecerse a una decisión) ────────────")
    faltan = sorted(del_arbol - set(decl))
    sobran = sorted(set(decl) - del_arbol)
    _ok("todo conector del árbol tiene decisión", not faltan, f"sin clasificar: {faltan}")
    _ok("ninguna recomendación apunta a un conector inexistente", not sobran,
        f"sobran: {sobran}")

    print(f"\n── FORMA ─────────────────────────────────────────────────────────────")
    malos_ws = {k: [w for w in v.get("en", []) if w not in ws_validos]
                for k, v in decl.items() if [w for w in v.get("en", []) if w not in ws_validos]}
    _ok("todos los workspaces nombrados existen", not malos_ws, f"desconocidos: {malos_ws}")
    sin_por_que = sorted(k for k, v in decl.items() if not (v.get("por_que") or "").strip())
    # El motivo no es adorno: es lo que convierte una asignación en una decisión con autor
    # («declarado ≠ inventado», CLAUDE.md §1). Sin motivo, nadie puede auditarla ni discutirla.
    _ok("cada decisión trae su motivo", not sin_por_que, f"sin por_que: {sin_por_que}")
    dup = sorted(k for k, v in decl.items() if len(v.get("en", [])) != len(set(v.get("en", []))))
    _ok("ninguna lista repite un workspace", not dup, f"con repetidos: {dup}")

    print(f"\n── LA REGLA: LA RECOMENDACIÓN NO ES EXCLUSIVA ────────────────────────")
    multi = {k: v["en"] for k, v in decl.items() if len(v.get("en", [])) > 1}
    # Si esto diera 0, la tabla estaría modelando exclusividad sin decirlo — que es justo la
    # regla que el dueño fijó al revés. No es un chequeo de estilo: es el invariante.
    _ok("hay conectores recomendados en MÁS de un workspace", len(multi) > 0,
        "ninguno cruza workspaces: la tabla estaría modelando exclusividad")
    for k, v in sorted(multi.items()):
        print(f"     {k:18s} → {', '.join(v)}")

    print(f"\n── REPARTO POR WORKSPACE ─────────────────────────────────────────────")
    for w in sorted(ws_validos):
        cuales = sorted(k for k, v in decl.items() if w in v.get("en", []))
        print(f"  {w:10s} {len(cuales):2d}  {', '.join(cuales)}")
    ninguno = sorted(k for k, v in decl.items() if not v.get("en"))
    print(f"  {'(llavero)':10s} {len(ninguno):2d}  {', '.join(ninguno) or '—'}")
    total_asig = sum(len(v.get("en", [])) for v in decl.values())
    print(f"\n  {len(decl)} conectores · {total_asig} asignaciones · "
          f"{total_asig / max(len(decl), 1):.2f} workspaces por conector")

    print("\n" + "─" * 70)
    print(f"VERDES {len(_verdes)} · ROJAS {len(_rojas)}")
    if _rojas:
        print("rojas: " + ", ".join(_rojas))
    return 1 if _rojas else 0


if __name__ == "__main__":
    raise SystemExit(main())
