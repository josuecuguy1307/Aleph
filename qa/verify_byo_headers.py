#!/usr/bin/env python3
"""verify_byo_headers.py — EL CHECK DE SEGURIDAD DEL BYO-HTTP (`DISEÑO-SUITE-v1.md` §4).

⚠️ **ESTE CHECK ARRANCA ROJO, Y ARRANCAR ROJO ES SU TRABAJO.**

No es un test que se rompió: es la medición de un agujero que existe hoy, escrita ANTES del
arreglo para que el arreglo tenga contra qué medirse. Mientras esté rojo, dice el
`archivo:línea` exacto de la línea que lo causa. Cuando S4 lo arregle, esto pasa a verde
solo — y a partir de ahí custodia que no vuelva.

    product/backend/.venv/bin/python qa/verify_byo_headers.py
      exit 0 → el agujero está cerrado (S4 hecha)
      exit 1 → el agujero sigue abierto, con el detalle de cuál de las dos aserciones falla
      exit 2 → no se pudo medir (y eso NO se cuenta como verde)

LAS DOS ASERCIONES (DECISIÓN 4.A del diseño):

  1. **El header no puede quedar en claro en disco.** Se forja un BYO-HTTP con un header
     falso y reconocible y se exige que ese valor NO aparezca en `manifest.json`.
  2. **El manifest no puede ser legible por otros.** Se exige `0600`.

CONTRA QUÉ SE CONTRASTA. El resto del producto ya cumple la regla: el registro de conexiones
guarda **nombres, jamás valores** (`env_template`), con un guard duro que levanta si a
alguien se le escapa un literal (`conexiones_repo.py`, `_sin_secretos`). El BYO-HTTP es el
único camino que la esquiva — y lo hace con el token que el usuario pega, que es exactamente
donde vive un `Authorization: Bearer …`.

NO SE ARREGLA ACÁ, y el diseño lo dice: el arreglo no es de una línea. Hay que decidir si el
header va al llavero cifrado (como el resto) o si el manifest se cifra entero, y eso es una
sesión con su vara (S4). Medir primero, arreglar después, con el rojo escrito.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "platform"))
sys.path.insert(0, str(ROOT / "platform" / "inspection"))

#: Un valor que no se parece a nada del sistema y que se busca por igualdad exacta. No hace
#: falta que PAREZCA un token: lo que se mide es si el valor pegado sobrevive en disco.
HEADER_FALSO = "Bearer aleph-check-byo-NO-DEBE-ESTAR-EN-DISCO-0000"

FALLOS: list = []
NOTAS: list = []


def ok(cond, etiqueta, detalle=""):
    print(("  ✅ " if cond else "  ❌ ") + etiqueta + (f"\n       {detalle}" if detalle else ""))
    if not cond:
        FALLOS.append(etiqueta)
    return cond


def _cita_de_la_linea() -> str:
    """El `archivo:línea` de la línea que causa el agujero, buscada AHORA y no citada de
    memoria: un número de línea envejece, y este check tiene que seguir señalando bien
    después de que alguien mueva el archivo."""
    p = ROOT / "platform" / "inspection" / "byo_mcp.py"
    try:
        for i, linea in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if '"headers": probe.get("headers")' in linea:
                return f"platform/inspection/byo_mcp.py:{i} → {linea.strip()}"
    except OSError:
        pass
    return "platform/inspection/byo_mcp.py (no encontré la línea; ¿ya se arregló?)"


def main() -> int:
    print("══ §4 · BYO-HTTP · ¿el header del usuario queda en claro? ══\n")

    # ⚠️ EL DATADIR SE AÍSLA **ANTES** DE IMPORTAR. `registry.SYNTH_BELTS_DIR` se resuelve
    # al importar el módulo, así que ponerlo después no sirve — y no es un detalle: la
    # primera versión de este check usó el nombre equivocado (`PUPPET_DATA_DIR`) y forjó
    # contra el datadir REAL de persona usuaria, dejándole un manifest con el header falso adentro.
    # La variable es `ALEPH_DATA_DIR` (`platform/aleph_paths.py:61`).
    tmp = Path(tempfile.mkdtemp(prefix="aleph-byo-check-"))
    previo = os.environ.get("ALEPH_DATA_DIR")
    os.environ["ALEPH_DATA_DIR"] = str(tmp)
    try:
        import byo_mcp                                     # noqa: E402
        import registry                                    # noqa: E402
    except Exception as e:                                 # noqa: BLE001
        print(f"  ⏸  no pude importar byo_mcp: {type(e).__name__}: {e}")
        print("     NO se cuenta como verde: un check de seguridad que no pudo medir")
        print("     no dice que el agujero esté cerrado.")
        return 2

    # [S4] EL VAULT DEL DATADIR AISLADO, CON SU SCHEMA. Desde S4 el forjado guarda los
    # headers CIFRADOS en el llavero y **falla cerrado** si no puede: sin esta línea el
    # check no mide el agujero, mide que el fixture está incompleto (y sale 2). Es ARREGLO
    # DEL ARRANGE, no de las aserciones — las dos de abajo no se tocaron.
    try:
        sys.path.insert(0, str(ROOT / "platform" / "db"))
        import sqlite_db                                   # noqa: E402
        sqlite_db.asegurar_schema()
        # `keys` tiene FK a `users`: sin dueño, el llavero rechaza la fila y el forjado
        # falla cerrado con razón. El usuario de prueba vive SÓLO en este datadir temporal.
        _c = sqlite_db.conectar()
        with _c.cursor() as _cur:
            _cur.execute("INSERT OR IGNORE INTO users (id, email) VALUES (%s, %s)",
                         ("check-byo-user", "check-byo@aleph.local"))
        _c.commit()
        _c.close()
    except Exception as e:                                 # noqa: BLE001
        print(f"  ⏸  no pude preparar el vault de prueba: {type(e).__name__}: {e}")
        return 2
    try:
        # Una sonda BYO-HTTP mínima, con la forma que `forge_byo_belt` espera. No se
        # contacta ningún servidor: lo que se mide es qué escribe el forjado en disco.
        probe = {
            "transport": "http",
            "url": "https://example.com/mcp",              # constante neutra (IANA)
            "headers": {"Authorization": HEADER_FALSO},
            "tools": [{"name": "leer_algo"}],
            "server_info": {"name": "check-byo"},
        }
        # El forjado escribe el manifest y DESPUÉS calcula un `belt_ref` relativo al repo;
        # con el datadir afuera del árbol eso levanta ValueError. No importa: lo que se está
        # midiendo ya está en disco para entonces, así que el manifest se busca por su ruta
        # canónica en vez de depender del valor de retorno.
        try:
            byo_mcp.forge_byo_belt(probe, user_id="check-byo-user", label="check byo")
        except Exception as e:                             # noqa: BLE001
            NOTAS.append(f"el forjado terminó con {type(e).__name__} (el manifest ya estaba escrito)")
        mp = registry.belt_dir_for("check-byo-user", "byo-check-byo") / "manifest.json"
        if not mp.is_file():
            print(f"  ⏸  el forjado no dejó manifest.json en {mp} — no hay qué medir.")
            return 2
        crudo = mp.read_text(encoding="utf-8")

        # ── ASERCIÓN 1 · el header no puede estar en claro ────────────────────────────
        print("1 · el header del usuario NO puede quedar en claro en disco")
        limpio = HEADER_FALSO not in crudo
        ok(limpio, "el valor pegado por el usuario no aparece en manifest.json",
           "" if limpio else
           f"aparece TAL CUAL en {mp}\n"
           f"       la línea que lo escribe: {_cita_de_la_linea()}\n"
           f"       dos líneas más abajo el propio código lo reconoce como secreto\n"
           f"       (`has_secret = bool((probe.get(\"headers\") or {{}}))`), así que no es\n"
           f"       que no se sepa: se sabe y se escribe igual.")

        # ── ASERCIÓN 2 · el manifest no puede ser legible por otros ───────────────────
        print("\n2 · el manifest NO puede ser legible por otros usuarios de la máquina")
        modo = stat.S_IMODE(mp.stat().st_mode)
        cerrado = not (modo & 0o077)
        ok(cerrado, "manifest.json está en 0600",
           "" if cerrado else
           f"permisos {oct(modo)} — cualquier proceso o usuario de esta máquina lo lee.\n"
           f"       Contrasta con la regla que el resto del producto sí cumple: el registro\n"
           f"       guarda nombres, jamás valores (`conexiones_repo._sin_secretos`).")

        # Contexto medido, para que el rojo se pueda accionar sin ir a buscarlo.
        try:
            datos = json.loads(crudo)
            NOTAS.append(f"claves del manifest: {sorted(datos)}")
            NOTAS.append(f"headers guardados: {len(datos.get('headers') or {})}")
        except json.JSONDecodeError:
            pass
    finally:
        if previo is None:
            os.environ.pop("ALEPH_DATA_DIR", None)
        else:
            os.environ["ALEPH_DATA_DIR"] = previo
        shutil.rmtree(tmp, ignore_errors=True)

    for n in NOTAS:
        print(f"\n  · {n}")

    if FALLOS:
        print(f"\n══ ❌ EL AGUJERO SIGUE ABIERTO · {len(FALLOS)} de 2 aserciones en rojo ══")
        print("   Esto es lo ESPERADO hoy. El arreglo es S4 (§7): header al llavero cifrado")
        print("   o manifest cifrado — es una decisión de diseño, no una línea. Cuando esté,")
        print("   este mismo check pasa a verde y queda de guardia.")
        return 1
    print("\n══ ✅ EL AGUJERO ESTÁ CERRADO — S4 hecha, y este check queda de guardia ══")
    return 0


if __name__ == "__main__":
    sys.exit(main())
