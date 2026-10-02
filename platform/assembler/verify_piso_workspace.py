#!/usr/bin/env python3
"""verify_piso_workspace.py — `financial_rigor` sobrevive al repliegue del borde.

EL RIESGO QUE MIDE. `workspace_brain` llamaba a `tool_budget.repliegue(tools)` SIN piso.
Con las 94 tools de Finanzas eso conservaba `financial_rigor` por accidente: está en la
posición 19 y el repliegue corta a la mitad (47). El mutante que reordena el catálogo
—lo mismo que haría registrar una tool nueva antes que ella— la deja afuera.

Se mide sobre el catálogo REAL de Finanzas si está disponible (94 nombres capturados de
un turno desde la pantalla); si no, sobre un catálogo sintético de 94 con la misma forma.
La vara dice cuál usó: un catálogo que no es el real mide menos y tiene que decirlo.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import tool_budget as B  # noqa: E402

FR = "financial_rigor"
fallos: list[str] = []


def check(ok: bool, etiqueta: str, extra: str = "") -> None:
    print(("OK  " if ok else "ROJO ") + etiqueta + (f"   [{extra}]" if extra else ""))
    if not ok:
        fallos.append(etiqueta)


def _catalogo() -> tuple[list, str]:
    """El catálogo real si hay una captura; si no, uno sintético equivalente."""
    ruta = os.environ.get("ALEPH_CATALOGO_FINANZAS", "")
    if ruta and Path(ruta).is_file():
        datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
        tools = datos["tools"] if isinstance(datos, dict) else datos
        nombres = [(t.get("function", t) or {}).get("name") for t in tools]
        if FR in nombres:
            return tools, f"REAL ({len(tools)} tools, {FR} en la posición {nombres.index(FR)})"
    tools = [{"type": "function",
              "function": {"name": f"tool_{i:02d}", "description": "x",
                           "parameters": {"type": "object", "properties": {}}}}
             for i in range(94)]
    tools[19]["function"]["name"] = FR
    return tools, "SINTÉTICO (94 tools; la captura real no estaba disponible)"


TOOLS, PROCEDENCIA = _catalogo()
print(f"catálogo: {PROCEDENCIA}\n")


def nombres(rec) -> list:
    return [B.nombre_de(t) for t in rec.enviadas]


# ── A · la tabla declarada ────────────────────────────────────────────────────────
check(B.piso_de_workspace("finanzas") == frozenset({FR}),
      "A1 el piso de `finanzas` es exactamente {financial_rigor}")
check(B.piso_de_workspace("FINANZAS") == frozenset({FR}),
      "A2 el rótulo no depende de la caja")
check(B.piso_de_workspace("  finanzas ") == frozenset({FR}),
      "A3 el rótulo tolera espacios (viene por HTTP)")
for otro in ("legal", "ciencia", "educacion", "diseno", "oficina", "", None, 7):
    if B.piso_de_workspace(otro) != frozenset():
        check(False, f"A4 workspace sin piso declarado → vacío ({otro!r})")
        break
else:
    check(True, "A4 los otros workspaces (y None/'' /no-str) → piso VACÍO, cero regresión")

# ── B · EL BUG, con su mutante ────────────────────────────────────────────────────
tal_cual = B.repliegue(TOOLS)
check(FR in nombres(tal_cual),
      "B1 con el orden de HOY el repliegue conserva financial_rigor… por posición",
      f"{len(tal_cual.enviadas)} de {len(TOOLS)}")

mutado = list(reversed(TOOLS))          # el catálogo reordenado: FR queda al final
sin_piso = B.repliegue(mutado)
check(FR not in nombres(sin_piso),
      "B2 MUTANTE · con el catálogo reordenado y SIN piso, financial_rigor DESAPARECE",
      "si esto da verde, el mutante no muerde")

con_piso = B.repliegue(mutado, piso=B.piso_de_workspace("finanzas"))
check(FR in nombres(con_piso),
      "B3 el mismo mutante CON el piso → financial_rigor SOBREVIVE")
check(nombres(con_piso).count(FR) == 1, "B4 …y exactamente una vez")
check(not any(d["name"] == FR for d in con_piso.demoradas),
      "B5 financial_rigor nunca aparece entre las demoradas")

# ── C · el piso no compra alcance de más ──────────────────────────────────────────
check(len(con_piso.enviadas) <= len(sin_piso.enviadas) + 1,
      "C1 el piso no infla el pedido: entra ella, no un lote",
      f"{len(sin_piso.enviadas)} → {len(con_piso.enviadas)}")
check(all(d["motivo"] == B.POR_REPLIEGUE for d in con_piso.demoradas),
      "C2 todo lo demorado sale con motivo `repliegue` (no hay recorte mudo)")

# ── D · los otros cinco workspaces no cambian ─────────────────────────────────────
for ws in ("legal", "ciencia", "educacion", "diseno", "oficina"):
    a = nombres(B.repliegue(mutado))
    b = nombres(B.repliegue(mutado, piso=B.piso_de_workspace(ws)))
    if a != b:
        check(False, f"D1 `{ws}` cambió de comportamiento")
        break
else:
    check(True, "D1 los otros cinco workspaces salen byte-idénticos a antes de la obra")

# ── E · el borde lo pasa de verdad (no alcanza con que la función exista) ─────────
wb = (HERE.parent.parent / "product" / "backend" / "app" / "phase1" / "workspace_brain.py")
if wb.is_file():
    src = wb.read_text(encoding="utf-8")
    check(src.count("a._budget.repliegue(") == 2
          and src.count("piso=a._budget.piso_de_workspace(workspace)") == 2,
          "E1 los DOS repliegues del borde (complete y complete_stream) pasan el piso",
          f"repliegues={src.count('a._budget.repliegue(')} "
          f"con_piso={src.count('piso=a._budget.piso_de_workspace(workspace)')}")
else:
    check(False, "E1 no encontré workspace_brain.py", str(wb))

print()
if fallos:
    print(f"ROJO — {len(fallos)} vara(s) caídas: {fallos}")
    sys.exit(1)
print("PASS — el piso de financial_rigor sobrevive al repliegue, y sólo en finanzas")
