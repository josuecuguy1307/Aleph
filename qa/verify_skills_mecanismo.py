"""verify_skills_mecanismo.py — EL MECANISMO PROPIO DE SKILLS. [T3.2]

Aleph no tenía ninguno. Las 11 de Legal las carga el motor de opencode por su plugin
(`pack.py` enlaza `.opencode/{agent,skill,command,tool}`) — es de ESE motor, no de la casa.
Y ⚠️ los 140 hits de «skill» en código propio son TIPOS DE MEMORIA (`skill|episodica`): una
trampa de nombre que ya mordió una vez, y por eso esta vara mide el server, no un grep.

QUÉ MIDE, contra el server REAL levantado con el cliente de PROD:

  R1 · DESCUBRE DE VARIOS ORÍGENES. officecli (10 legibles) y gws (4) a la vez. Una sola raíz no
       probaría lo que el mecanismo promete: cargar `SKILL.md` venga de donde venga.

  R2 · DIVULGACIÓN PROGRESIVA — que es la mitad del formato. El índice trae nombre y
       descripción y NO el cuerpo; el cuerpo llega sólo cuando se lo pide. Si `list_skills`
       devolviera los cuerpos, el mecanismo estaría pagando en cada turno por lo que no se
       usa, que es exactamente lo que el formato existe para evitar.

  R3 · EL CUERPO ES EL DE VERDAD. Se compara contra el archivo en disco, no contra sí mismo.

  R4 · EL PATH NO ESCAPA. `read_skill_file` recibe un path DEL MODELO: un `../../../etc/passwd`
       tiene que rebotar. Se mide el rebote, no la intención.

  R5 · SIN RAÍCES DECLARADAS NO HAY SKILLS, y lo DICE. Barrer el disco levantaría las del
       Claude Code del desarrollador, que no son del producto. «No hay» y «nadie dijo dónde
       mirar» son dos estados distintos y el server los distingue.

PROBADA CAYENDO: R1 se corre además con una raíz inexistente — el total DEBE dar 0. Si
igual encontrara algo, estaría descubriendo por su cuenta y la vara no mediría nada.

    product/backend/.venv/bin/python qa/verify_skills_mecanismo.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "platform" / "assembler"))
from assembler import MCPServer  # noqa: E402

_V, _R, _FIN = "\033[32m", "\033[31m", "\033[0m"
_filas: list[tuple[str, bool]] = []

OFFICECLI = _REPO / "third_party/officecli/skills"
GWS = _REPO / "third_party/gws/skills"


def _anotar(b: str, ok: bool, det: str) -> None:
    _filas.append((b, ok))
    print(f"  [{(_V+'VERDE'+_FIN) if ok else (_R+'ROJA'+_FIN)}] {b} — {det}")


def _servidor(raices: str) -> MCPServer:
    env = dict(os.environ)
    env["ALEPH_SKILL_PATHS"] = raices
    return MCPServer("skills", sys.executable,
                     [str(_REPO / "product/belts/generalistas/skills_server.py")], env=env)


def _llamar(srv: MCPServer, tool: str, args: dict) -> dict:
    r = srv.call_tool(tool, args)
    txt = r if isinstance(r, str) else json.dumps(r)
    try:
        return json.loads(txt)
    except ValueError:
        # el cliente envuelve el content; se busca el JSON adentro
        i, j = txt.find("{"), txt.rfind("}")
        return json.loads(txt[i:j + 1]) if i >= 0 else {"error": txt[:120]}


def main() -> int:
    print("\n  mecanismo de skills · formato Anthropic Agent Skills\n")
    srv = _servidor(f"{OFFICECLI}{os.pathsep}{GWS}")
    if not srv.start():
        print(f"{_R}NO MEDIBLE{_FIN} · el server no arrancó")
        return 1

    print("MEDICIÓN")
    idx = _llamar(srv, "list_skills", {})
    nombres = {s["name"] for s in idx.get("skills", [])}
    # LEGIBLES, no listados. ⚠️ MEDIDO: `officecli/skills` lista 11 `SKILL.md` y sólo 10 se
    # pueden leer — `skills/officecli/` quedó vacía en el import. El server ya lo tolera
    # (OSError → sigue), y la vara cuenta lo que de verdad se puede cargar: contar lo
    # listado la pondría roja por un defecto del árbol importado, no del mecanismo.
    def _legibles(raiz):
        out = []
        for c in sorted(raiz.rglob("SKILL.md")):
            try:
                c.read_text(encoding="utf-8", errors="replace")
                out.append(c)
            except OSError:
                continue
        return out
    oc, gws = _legibles(OFFICECLI), _legibles(GWS)
    n_oc, n_gws = len(oc), len(gws)
    _anotar("R1 · descubre de varios orígenes", idx.get("total") == n_oc + n_gws,
            f"{idx.get('total')} skills = officecli {n_oc} + gws {n_gws}")

    sin_cuerpo = all("body" not in s for s in idx.get("skills", []))
    con_desc = all(s.get("description") for s in idx.get("skills", []))
    _anotar("R2 · divulgación progresiva", sin_cuerpo and con_desc,
            f"el índice trae description y NO body · {len(json.dumps(idx))} bytes para {idx.get('total')} skills")

    elegida = "officecli-pptx" if "officecli-pptx" in nombres else sorted(nombres)[0]
    cuerpo = _llamar(srv, "read_skill", {"name": elegida})
    md = next((c for c in oc + gws
               if elegida in c.read_text(encoding="utf-8", errors="replace")[:400]), None)
    real = md.read_text(encoding="utf-8", errors="replace") if md else ""
    trozo = (cuerpo.get("body") or "")[:120]
    _anotar("R3 · el cuerpo es el de verdad", bool(trozo) and trozo in real,
            f"«{elegida}» · {len(cuerpo.get('body') or '')} chars, y coinciden con el archivo en disco")

    fuga = _llamar(srv, "read_skill_file", {"name": elegida, "path": "../../../../etc/passwd"})
    _anotar("R4 · el path no escapa", bool(fuga.get("error")),
            f"«../../../../etc/passwd» → {fuga.get('error') or 'LO LEYÓ'}")
    srv.stop()

    vacio = _servidor("")
    vacio.start()
    idx0 = _llamar(vacio, "list_skills", {})
    _anotar("R5 · sin raíces lo dice", idx0.get("total") == 0 and idx0.get("sin_raices_declaradas") is True,
            f"total={idx0.get('total')} · sin_raices_declaradas={idx0.get('sin_raices_declaradas')}")
    vacio.stop()

    print("\nPROBADA CAYENDO")
    falso = _servidor(str(_REPO / "no-existe-esta-carpeta"))
    falso.start()
    idxf = _llamar(falso, "list_skills", {})
    cayo = idxf.get("total") == 0
    _anotar("R1 · CAÍDA", cayo,
            f"con una raíz inexistente encontró {idxf.get('total')} "
            f"({'bien: no descubre por su cuenta' if cayo else 'DESCUBRE SOLO — no mide nada'})")
    falso.stop()

    verde = all(ok for _, ok in _filas)
    print(f"\n{'='*70}")
    print(f"{(_V+'VERDE'+_FIN) if verde else (_R+'ROJA'+_FIN)} · "
          + ("Aleph carga SKILL.md de cualquier origen, con divulgación progresiva"
             if verde else ", ".join(b for b, ok in _filas if not ok)))
    print("=" * 70)
    return 0 if verde else 1


if __name__ == "__main__":
    raise SystemExit(main())
