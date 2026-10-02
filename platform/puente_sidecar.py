"""puente_sidecar.py — EL PUENTE BYO LO SIRVE EL PROPIO SIDECAR, no un python3 ajeno.

──────────────────────────────────────────────────────────────────────────────────────────
QUÉ PROBLEMA RESUELVE, MEDIDO

Toda pieza HTTP equipada se persiste con el puente stdio↔HTTP como receta ejecutable
(`byo_mcp.forge_byo_belt`):

    command: "python3"
    args:    ["${PUPPET_REPO}/platform/inspection/byo_mcp_server.py", "<manifest>.json"]

En el repo eso anda. En la `.app` NO, y la Obra 6a lo midió en dos capas:

  1. el archivo no viajaba en el bundle  → `[Errno 2] No such file or directory`.
     Arreglado: `deploy/fase4/bundle_datos.py` lo declara y el gate lo exige.
  2. con el archivo adentro, igual muere → `from inspection import transporte`
     → `ImportError: cannot import name 'transporte'`.

La (2) no se arregla sumando archivos, y por eso este módulo existe. `python3` acá es el
intérprete **del sistema del usuario**, un proceso aparte que NO puede leer el PYZ del
binario congelado. Para que funcionara habría que hacer viajar todo el cierre del puente
(`inspection/{__init__,transporte,transporte_sdk}.py`, `aleph_paths.py`, …) **y** exigir
que ese python3 tenga instalado el SDK `mcp`. Medido en la máquina de desarrollo: `python3`
resuelve a miniconda y sí lo tiene — pero eso es una casualidad de UNA máquina, no algo con
lo que una app distribuida pueda contar. Un arreglo que anda acá y falla en la máquina del
usuario es exactamente la clase de bug que este repo viene pagando desde FIX-P1B.

LA SALIDA: el sidecar YA tiene todo adentro —`inspection.transporte`, el SDK `mcp`, el
puente— así que se sirve a sí mismo. Congelado, la receta se ejecuta como

    <el propio binario del sidecar> --byo-mcp <manifest>.json

y `deploy/fase4/sidecar_serve.py` la despacha antes de levantar nada. Cero dependencia del
python3 del usuario, cero cierre que hacer viajar.

──────────────────────────────────────────────────────────────────────────────────────────
POR QUÉ SE TRADUCE AL LANZAR Y NO SE REESCRIBE LA RECETA

Podría persistirse ya traducida, y sería peor por tres razones medidas:

  · **La receta seguiría siendo portable.** El mismo belt tiene que servir corriendo suelto
    (donde `python3 byo_mcp_server.py` es correcto y no hay sidecar) y congelado. Una receta
    con la ruta de un binario adentro sólo vale en la máquina que la escribió — justo lo que
    el §1 del contrato del repo prohíbe.
  · **Las filas viejas reviven sin migración.** Los belts ya persistidos en el dir de datos
    del usuario —incluidas las piezas HTTP que hoy están rotas— vuelven a andar con sólo
    instalar la versión nueva. Migrar filas a mano para arreglar un bug nuestro es cobrarle
    al usuario nuestro problema.
  · **El registro no miente.** La receta dice qué pieza es y cómo se levanta; con qué
    intérprete se levanta es del entorno, igual que `${PUPPET_REPO}`.

⚠️ REGLA ESTRECHA A PROPÓSITO. Sólo traduce lo que es INEQUÍVOCAMENTE el puente BYO
—`byo_mcp_server.py` como script de un intérprete— y sólo en un build congelado. Cualquier
otro comando pasa intacto: éste no es un lugar para reescribir comandos ajenos.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional, Sequence

#: El nombre del script del puente. Se compara por BASENAME porque la ruta persistida trae
#: el placeholder `${PUPPET_REPO}` sin expandir, o ya expandido al `_MEIPASS` del arranque.
PUENTE_SCRIPT = "byo_mcp_server.py"

#: La bandera que `sidecar_serve.py` despacha antes de levantar uvicorn.
FLAG = "--byo-mcp"


def congelado() -> bool:
    """¿Estamos adentro del binario PyInstaller? (`sys.frozen` lo pone el bootloader)."""
    return bool(getattr(sys, "frozen", False))


def binario_del_sidecar() -> Optional[str]:
    """La ruta del binario que se está ejecutando, o None si no estamos congelados.

    `sys.executable` congelado ES el sidecar (no un python). Suelto es el intérprete, que
    no sabe de `--byo-mcp`: por eso devolvemos None y el comando queda como estaba."""
    if not congelado():
        return None
    exe = sys.executable
    return exe if exe and Path(exe).exists() else None


def es_el_puente(cmd: Sequence[str]) -> bool:
    """¿`cmd` es «<un intérprete> <ruta>/byo_mcp_server.py <manifest>»?"""
    if not cmd or len(cmd) < 3:
        return False
    return Path(str(cmd[1])).name == PUENTE_SCRIPT


def normalizar_cmd(cmd: Sequence[str]) -> list:
    """La lista de comando que hay que lanzar de verdad.

    Congelado + puente BYO → lo sirve el sidecar. Cualquier otro caso → intacta.
    Es idempotente: aplicarla dos veces da lo mismo."""
    cmd = list(cmd or [])
    if not es_el_puente(cmd):
        return cmd
    exe = binario_del_sidecar()
    if not exe:
        return cmd                     # suelto: `python3 byo_mcp_server.py` es lo correcto
    return [exe, FLAG, *cmd[2:]]


# ── EL OTRO LADO: lo que corre cuando el sidecar se lanza a sí mismo ────────────────────

def atender_si_es_puente(argv: Optional[Sequence[str]] = None) -> bool:
    """Si `argv` pide el puente, lo corre y NO vuelve. Devuelve False si no era para él.

    ⚠️ SE LLAMA ANTES QUE NADA en `sidecar_serve.main()`. El puente habla JSON-RPC por
    **stdout**: una sola línea de log de otro que se cuele ahí corrompe el protocolo y el
    server queda «sin saludo» — el mismo síntoma que veníamos arrastrando, con otra causa.
    """
    argv = list(argv if argv is not None else sys.argv[1:])
    if FLAG not in argv:
        return False
    i = argv.index(FLAG)
    if i + 1 < len(argv) and argv[i + 1]:
        # `byo_mcp_server._load_manifest()` ya lee esta env como fallback de argv[1]; usarla
        # evita tocar su parseo y deja el puente idéntico corriendo suelto o adentro.
        os.environ["BYO_MCP_MANIFEST"] = argv[i + 1]
    from inspection import byo_mcp_server
    byo_mcp_server.main()
    return True
