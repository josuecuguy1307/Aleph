"""verify_inbox_persistente.py — EL ADJUNTO SOBREVIVE AL TURNO. [T2.5c]

LA PREGUNTA: adjuntás un PDF, preguntás por algo que está adentro, y DOS TURNOS DESPUÉS
seguís pudiendo preguntar. Si el archivo vive en el turno, la respuesta a la segunda
pregunta es «no lo tengo» — y eso es lo que esta vara existe para que no pase.

EL SECRETO ES EL INSTRUMENTO. Cada archivo lleva una cadena que no está en ningún otro
lado y que no se puede adivinar. Si vuelve, se leyó. No se mira «devolvió 200»: se mira
el secreto. Los lectores son los REALES del kit (`markitdown`, `filesystem`), levantados
con el cliente de PROD.

LOS CUATRO BLOQUES, y por qué cada uno:

  R1 · PERSISTE ENTRE TURNOS. Se simulan DOS runs con `run_id` distinto —que es lo que
       pasa de verdad: `executor` arma `run_outputs/<run_id>` nuevo cada vez— y se copia
       el inbox a cada uno. El secreto tiene que salir en LOS DOS. Un solo turno no
       prueba nada: el bug que esto persigue aparece recién en el segundo.

  R2 · AISLADO POR DUEÑO. El inbox de otro usuario NO contiene el archivo. Y no es un
       chequeo que se pueda olvidar: son carpetas distintas, así que se mide que las
       RUTAS difieran y que la del otro esté vacía.

  R3 · AISLADO POR SESIÓN. Dos conversaciones del MISMO dueño no se mezclan.

  R4 · EL ADJUNTO NO ES UNA OBRA. Lo que el usuario sube no puede aparecer en su
       Biblioteca como si el agente lo hubiera producido: la captura del workdir tiene
       que SALTEAR `adjuntos/`.

PROBADA CAYENDO: R1 se corre además con el inbox BORRADO entre los dos turnos — el
segundo turno DEBE perder el secreto. Si igual lo encuentra, la vara está midiendo una
copia vieja y no mide nada.

    product/backend/.venv/bin/python qa/verify_inbox_persistente.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "product" / "backend"))
sys.path.insert(0, str(_REPO / "platform" / "assembler"))

# AISLAMIENTO: el árbol NO se toca. `_TREE_DATA` escribe adentro si nadie lo redirige.
_TMP_DATA = tempfile.mkdtemp(prefix="inbox-vara-")
os.environ["ALEPH_DATA_DIR"] = _TMP_DATA

from app.phase1 import inbox_store as IB          # noqa: E402
from app.phase1.executor import ADJUNTOS_DIR      # noqa: E402
from assembler import MCPServer                   # noqa: E402

SECRETO = "PELICANO-8834"
DUENO_A, DUENO_B = "usuario-A", "usuario-B"
CHAT_1, CHAT_2 = "chat-uno", "chat-dos"

_V, _R, _FIN = "\033[32m", "\033[31m", "\033[0m"
_filas: list[tuple[str, bool]] = []


def _anotar(bloque: str, ok: bool, detalle: str) -> None:
    _filas.append((bloque, ok))
    print(f"  [{(_V + 'VERDE' + _FIN) if ok else (_R + 'ROJA' + _FIN)}] {bloque} — {detalle}")


def _pdf_con_secreto() -> bytes:
    from reportlab.pdfgen import canvas as _c
    p = Path(_TMP_DATA) / "fuente.pdf"
    cv = _c.Canvas(str(p)); cv.drawString(72, 720, f"Codigo interno: {SECRETO}"); cv.save()
    return p.read_bytes()


def _markitdown(workdir: Path) -> MCPServer:
    kit = json.loads((_REPO / "catalog/templates/kit/belt-kit.mcp.json").read_text())
    scfg = kit["mcpServers"]["markitdown"]
    env = dict(os.environ)
    env["PUPPET_WORKDIR"] = str(workdir)
    env["PUPPET_BELTS"] = str(_REPO / "product" / "belts")
    return MCPServer("markitdown", scfg.get("command", ""), list(scfg.get("args") or []), env=env)


def _turno(inbox: Path, srv: MCPServer, n: int) -> bool:
    """Simula UN turno: workdir nuevo (como hace el executor), copia del inbox, lectura."""
    wd = Path(tempfile.mkdtemp(prefix=f"run{n}-"))
    dst = wd / ADJUNTOS_DIR
    dst.mkdir(parents=True, exist_ok=True)
    for f in sorted(inbox.iterdir()):
        if f.is_file() and not f.name.startswith((".", "_")):
            shutil.copy2(f, dst / f.name)
    hallados = list(dst.glob("*.pdf"))
    if not hallados:
        return False
    try:
        r = srv.call_tool("convert_to_markdown", {"uri": hallados[0].as_uri()})
        return SECRETO in (r if isinstance(r, str) else json.dumps(r))
    except Exception:
        return False


def main() -> int:
    print(f"\n{'':2}inbox persistente · secreto {SECRETO} · datos en {_TMP_DATA}\n")
    pdf = _pdf_con_secreto()

    ficha = IB.guardar(DUENO_A, CHAT_1, "../../contrato.pdf", pdf)   # ← con traversal adentro
    inbox_a1 = IB.dir_de(DUENO_A, CHAT_1)

    srv = _markitdown(inbox_a1)
    if not srv.start():
        print(f"{_R}NO MEDIBLE{_FIN} · markitdown no arrancó")
        return 1

    print("MEDICIÓN")
    # R0 · el traversal no escapó
    dentro = Path(ficha["ruta"]).resolve().is_relative_to(inbox_a1.resolve())
    _anotar("R0 · el nombre no escapa", dentro and ".." not in ficha["nombre"],
            f"«../../contrato.pdf» → «{ficha['nombre']}» dentro del inbox")

    t1 = _turno(inbox_a1, srv, 1)
    t2 = _turno(inbox_a1, srv, 2)
    _anotar("R1 · persiste entre turnos", t1 and t2,
            f"turno 1 {'lee' if t1 else 'NO lee'} · turno 2 {'lee' if t2 else 'NO lee'} (run_id distinto)")

    inbox_b1 = IB.dir_de(DUENO_B, CHAT_1)
    aislado_dueno = inbox_b1 != inbox_a1 and not list(inbox_b1.glob("*.pdf"))
    _anotar("R2 · aislado por dueño", aislado_dueno,
            f"el inbox de {DUENO_B} es otra carpeta y no tiene el archivo")

    inbox_a2 = IB.dir_de(DUENO_A, CHAT_2)
    aislado_sesion = inbox_a2 != inbox_a1 and not list(inbox_a2.glob("*.pdf"))
    _anotar("R3 · aislado por sesión", aislado_sesion,
            f"{CHAT_2} del mismo dueño es otra carpeta y no tiene el archivo")

    from app.phase1 import executor as EX
    fuente = Path(EX.__file__).read_text()
    saltea = f'parts[:1] == (ADJUNTOS_DIR,)' in fuente
    _anotar("R4 · el adjunto no es una obra", saltea,
            "la captura del workdir saltea la carpeta de adjuntos")

    print("\nPROBADA CAYENDO")
    for f in inbox_a1.iterdir():
        if f.is_file():
            f.unlink()
    t3 = _turno(inbox_a1, srv, 3)
    _anotar("R1 · CAÍDA", not t3,
            f"con el inbox vacío el turno {'NO lee (bien)' if not t3 else 'SIGUE LEYENDO — mide una copia vieja'}")

    try:
        srv.stop()
    except Exception:
        pass
    shutil.rmtree(_TMP_DATA, ignore_errors=True)

    verde = all(ok for _, ok in _filas)
    print(f"\n{'=' * 70}")
    print(f"{(_V + 'VERDE' + _FIN) if verde else (_R + 'ROJA' + _FIN)} · "
          + ("el adjunto sobrevive al turno, aislado por dueño y por sesión"
             if verde else ", ".join(b for b, ok in _filas if not ok)))
    print("=" * 70)
    return 0 if verde else 1


if __name__ == "__main__":
    raise SystemExit(main())
