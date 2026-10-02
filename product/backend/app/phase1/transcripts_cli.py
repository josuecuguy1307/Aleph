"""transcripts_cli.py — LO QUE EL CLI ESCRIBE EN TU DISCO, VISIBLE Y BORRABLE (F4b · obra 4).

F2e prendió las sesiones del BYO-CLI, y eso tuvo un costo que quedó ESCRITO en su propio
módulo: sacar `--no-session-persistence` significa que **la conversación queda en
`~/.claude/projects/` en texto plano** hasta que el CLI la rote. F2e midió además que no
hay dónde moverla (`CLAUDE_CONFIG_DIR` mueve el store pero PIERDE EL AUTH), así que la
respuesta no puede ser esconderla: es **decirlo y poder borrarlo**.

Sin drama en el copy, porque no lo hay: es el CLI oficial de Anthropic guardando su propia
historia, como lo hace cuando lo usás en tu terminal. Lo que Aleph agrega es que se vea y
que se pueda sacar.

══ EL CANDADO, QUE ES LO ÚNICO DELICADO DE ESTE ARCHIVO ═══════════════════════════════

En `~/.claude/projects/` **también viven tus propias conversaciones con `claude`**, las
que abrís en tu terminal y no tienen nada que ver con Aleph. Borrar de más acá no es un
bug: es destruir trabajo de la persona.

Por eso la pertenencia **NO se adivina con un heurístico de nombres**. Se DERIVA de la
misma función que creó esos directorios:

    Sesiones.raiz            = aleph_paths.data_root()/cli_sesiones   ← nuestros workdirs
    sesiones.slug_de(cwd)    = realpath(cwd) con «/» → «-»            ← cómo el CLI los nombra

O sea que un directorio del store es NUESTRO si y sólo si su nombre empieza con
`slug_de(<raíz de cli_sesiones>)`. Cualquier otro es tuyo y este módulo no lo toca. La vara
lo verifica creando un directorio ajeno al lado y exigiendo que sobreviva.

Sólo LEE de `cli_brain` (`raiz_del_store`, `slug_de`, la raíz de `Sesiones`): el borrado
vive de este lado, que es el que tiene la superficie.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Optional

_REPO = Path(__file__).resolve().parents[4]
_ASM = _REPO / "platform" / "assembler"


def _ses():
    """El módulo de sesiones de F2e. `None` si no está — sin él no se borra NADA.

    Fallar cerrado no es prolijidad: sin `slug_de` no hay forma de saber qué directorio es
    nuestro, y borrar sin ese dato es exactamente lo que este módulo existe para no hacer.
    """
    try:
        if str(_ASM) not in sys.path:
            sys.path.insert(0, str(_ASM))
        from cli_brain import sesiones as _s   # type: ignore
        return _s
    except Exception:                          # noqa: BLE001
        return None


def _slug_real(ruta: str) -> str:
    """`ruta` → el nombre que el CLI le pone a su directorio en el store.

    ══ F4d · UNIFICADA. Acá vivía una COPIA de la regla, y ya no hace falta ══════════
    F4b tuvo que derivarla por su cuenta porque `sesiones.slug_de` estaba MAL (traducía
    sólo `/`) y `cli_brain` era de sólo lectura en esa fase. Sin la regla real este
    candado no habría encontrado JAMÁS un directorio de Aleph, y el botón de borrado
    habría dicho «0» para siempre — un botón que miente.

    F4d arregló `slug_de` en su origen, así que la copia se borra y se consume la de
    `cli_brain`: **una sola regla, un solo lugar**, que era la condición de la unificación.

    Se conserva el NOMBRE (en vez de disolverla en los call-sites) porque es el punto
    único donde este módulo declara de quién depende: si la regla vuelve a moverse, hay
    un solo lugar donde mirar de este lado.
    """
    s = _ses()
    if s is None:                                  # pragma: no cover — sin el módulo no se borra
        return ""
    return s.slug_de(ruta)


def _prefijo_nuestro(s) -> Optional[str]:
    """El prefijo de slug que identifica a los workdirs de Aleph. `None` = no se pudo saber.

    [F4d] Ahora consume `sesiones.slug_de` vía `_slug_real`. Hasta F4d no podía: esa
    función traducía sólo `/` y el workdir de Aleph en macOS tiene un espacio Y un guión
    bajo (`~/Library/Application Support/Aleph/cli_sesiones`), así que el prefijo no
    coincidía con NINGÚN directorio del store. El histórico está en el docstring de
    `slug_de`, que es donde vive la regla.
    """
    try:
        raiz = s.SESIONES.raiz if hasattr(s, "SESIONES") else None
        return _slug_real(raiz) if raiz else None
    except Exception:                          # noqa: BLE001
        return None


def _dirs(config_dir: Optional[str] = None) -> tuple[list, list]:
    """(nuestros, ajenos) — los directorios del store, separados por pertenencia DERIVADA."""
    s = _ses()
    if s is None:
        return [], []
    raiz = Path(s.raiz_del_store(config_dir))
    pref = _prefijo_nuestro(s)
    nuestros, ajenos = [], []
    if not raiz.is_dir():
        return [], []
    for d in sorted(raiz.iterdir()):
        if not d.is_dir():
            continue
        (nuestros if (pref and d.name.startswith(pref)) else ajenos).append(d)
    return nuestros, ajenos


def _medir(dirs) -> tuple[int, int]:
    """(cuántos transcripts, cuántos bytes). Cuenta `.jsonl`, que es lo que el CLI escribe."""
    n = b = 0
    for d in dirs:
        try:
            for f in d.rglob("*.jsonl"):
                try:
                    b += f.stat().st_size
                    n += 1
                except OSError:
                    continue
        except OSError:
            continue
    return n, b


def donde(config_dir: Optional[str] = None) -> dict:
    """QUÉ HAY Y DÓNDE — para que la pantalla lo diga en vez de insinuarlo.

    Devuelve también `ajenos`, y no es un detalle de implementación: es la prueba, en el
    mismo payload, de que sabemos separar lo nuestro de lo tuyo. La pantalla lo usa para
    decir «hay N conversaciones tuyas ahí que Aleph no toca».
    """
    s = _ses()
    nuestros, ajenos = _dirs(config_dir)
    n_ours, b_ours = _medir(nuestros)
    n_theirs, _ = _medir(ajenos)
    return {
        "disponible": s is not None,
        "carpeta": s.raiz_del_store(config_dir) if s else None,
        "perilla": os.environ.get("PUPPET_CLI_SESIONES", "1"),
        "activo": (os.environ.get("PUPPET_CLI_SESIONES", "1").strip().lower()
                   not in ("0", "false", "no")),
        "de_aleph": {"carpetas": len(nuestros), "transcripts": n_ours, "bytes": b_ours},
        "tuyos": {"carpetas": len(ajenos), "transcripts": n_theirs},
        "que_contienen": ("El texto de las conversaciones que tuviste con tu CLI a través "
                          "de Aleph, tal como el CLI las guarda."),
    }


def limpiar(config_dir: Optional[str] = None, *, dry_run: bool = False) -> dict:
    """Borra los transcripts que Aleph generó. **Sólo los suyos.**

    `dry_run=True` devuelve exactamente lo que borraría sin tocar nada — la vara lo usa
    para probar el candado sin depender de que el borrado ande.

    Devuelve lo MEDIDO (carpetas y transcripts borrados, bytes liberados), no una promesa:
    un botón de borrado que dice «listo» sin haber contado nada es la clase de cosa que
    hace que la gente no confíe en el siguiente.
    """
    s = _ses()
    if s is None:
        return {"ok": False, "motivo": "no se pudo determinar qué es de Aleph", "borradas": 0}
    nuestros, ajenos = _dirs(config_dir)
    n, b = _medir(nuestros)
    if dry_run:
        return {"ok": True, "dry_run": True, "borradas": len(nuestros),
                "transcripts": n, "bytes": b, "intactas_tuyas": len(ajenos)}
    borradas, fallidas = 0, []
    for d in nuestros:
        try:
            shutil.rmtree(d)
            borradas += 1
        except OSError as e:
            fallidas.append({"carpeta": d.name, "error": type(e).__name__})
    return {"ok": not fallidas, "borradas": borradas, "transcripts": n, "bytes": b,
            "intactas_tuyas": len(ajenos), "fallidas": fallidas}


__all__ = ["donde", "limpiar"]
