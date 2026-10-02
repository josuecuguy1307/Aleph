#!/usr/bin/env python3
"""verify_cuando_se_verifica.py — CUÁNDO SE VERIFICA UN CONECTOR. [TANDA 2 · obra A]

EL CRITERIO QUE ESTA VARA DEFIENDE, en una línea
------------------------------------------------
Un conector se verifica **cuando se conecta** y **cuando se va a usar**; el veredicto
guardado se lee, y sólo se re-pregunta si un insumo suyo cambió (`medicionRancia`) o si su
causa anterior es reintentable (`MV.REINTENTABLE`). **Abrir la app no es un momento de
verificación.**

QUÉ MIDE, y por qué cada mitad
------------------------------
1. **El arranque no verifica.** `main.py` no puede volver a llamar a `re_verificar_local`.
   Estático a propósito: el rojo tiene que aparecer donde se edita, no sólo tras un build
   de 25 minutos.
2. **El censo no sale a ningún lado.** `censo_local` corre con `_spawn` y la red
   SABOTEADOS: si toca cualquiera de los dos, revienta y la vara lo dice.
3. **Lo que se sabe sin red no se pregunta.** Una receta que pide credencial sin credencial
   guardada devuelve `falta_key` **sin spawnear**.
4. **`key_invalida` no es `sin_red`.** La clasificación de reintento existe como un solo
   sello y no como dos tuplas sueltas.

`falta_key` tiene copy en `CAUSAS_HUMANAS` (`cuarto/cuarto.semaforo.js`) — no se inventa
causa nueva. La vara lo comprueba, porque una causa sin copy es una causa que no llega.

CORRE: `python3 qa/verify_cuando_se_verifica.py`
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
for _d in ("platform", "platform/db", "platform/inspection", "platform/assembler",
           "product/backend"):
    sys.path.insert(0, str(RAIZ / _d))
os.environ.setdefault("ALEPH_ROLE", "client")

FALLOS: list[str] = []


def ok(cond: bool, etiqueta: str, extra: str = "") -> None:
    print(f"  {'✓' if cond else '✗'} {etiqueta}" + ("" if cond or not extra else f" — {extra}"))
    if not cond:
        FALLOS.append(etiqueta)


class Delator(Exception):
    """Se levanta cuando el código bajo prueba hace lo que juró no hacer."""


def main() -> int:  # noqa: C901 — es una vara, la linealidad se lee mejor
    # ── 1 · EL ARRANQUE NO VERIFICA (estático) ───────────────────────────────────────
    main_py = (RAIZ / "product" / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    # Sólo las líneas de CÓDIGO: el comentario que explica por qué se sacó tiene que poder
    # nombrarlo. Una vara que prohíbe la palabra prohíbe también documentar la decisión.
    codigo = "\n".join(l for l in main_py.splitlines()
                       if not l.lstrip().startswith("#"))
    ok("re_verificar_local" not in codigo,
       "el arranque NO llama a `re_verificar_local`")
    ok("censo_local" in codigo, "el arranque llama a `censo_local` en su lugar")
    ok("censo de arranque" in main_py,
       "y lo DICE: el arranque no queda mudo sobre el catálogo")

    # ── 2 · EL CENSO NO SALE A NINGÚN LADO ───────────────────────────────────────────
    from app.phase1 import centro_conexiones as CC
    from app.phase1 import conexiones_verificador as V
    from app.phase1 import repo

    import socket
    import subprocess

    # ⚠️ EL DELATOR DICE QUIÉN, no un nombre fijo. La primera versión gritaba siempre
    # «censo_local spawneó…», así que el mutante que rompía el atajo sin-red de
    # `verificar_uno` daba rojo acusando al módulo equivocado. Un rojo con la causa mal
    # atribuida manda a arreglar donde no está el bug.
    espia = {"spawn": 0, "socket": 0, "popen": 0, "quien": "censo_local"}

    def _spawn_delator(*a, **k):
        espia["spawn"] += 1
        raise Delator(f"{espia['quien']} spawneó un server MCP")

    class _SockDelator(socket.socket):
        def connect(self, *a, **k):  # noqa: D102
            espia["socket"] += 1
            raise Delator(f"{espia['quien']} abrió una conexión de red")

    def _popen_delator(*a, **k):
        espia["popen"] += 1
        raise Delator(f"{espia['quien']} lanzó un proceso")

    v_spawn, s_sock, s_popen = V._spawn, socket.socket, subprocess.Popen
    V._spawn, socket.socket, subprocess.Popen = _spawn_delator, _SockDelator, _popen_delator
    try:
        censo = CC.censo_local(repo.get_conn)
        reventó = None
    except Delator as e:
        censo, reventó = None, str(e)
    except Exception as e:  # noqa: BLE001 — cualquier otro fallo también es rojo
        censo, reventó = None, f"{type(e).__name__}: {e}"
    finally:
        V._spawn, socket.socket, subprocess.Popen = v_spawn, s_sock, s_popen

    ok(reventó is None, "`censo_local` corre sin spawnear ni tocar la red", reventó or "")
    if censo:
        ok(censo["piezas"] > 0, "el censo cuenta piezas de verdad", json.dumps(censo)[:90])
        ok(censo["ms"] < 2000, "y cuesta milisegundos, no decenas de segundos",
           f"{censo['ms']} ms")
        # `sin_veredicto` es un null declarado, no un cero de relleno: tiene que ser la
        # cuenta de los que nadie midió, y sus NOMBRES tienen que estar.
        ok(censo["sin_veredicto"] == len(censo["nombres_sin_veredicto"]),
           "`sin_veredicto` coincide con los nombres que declara (no es un cero de relleno)",
           f"{censo['sin_veredicto']} vs {len(censo['nombres_sin_veredicto'])}")

    # ── 3 · LO QUE SE SABE SIN RED NO SE PREGUNTA ────────────────────────────────────
    # Se busca una pieza REAL que pida credencial y no la tenga. Si no hay ninguna en esta
    # máquina, se dice — no se inventa un fixture que pase solo.
    from app.phase1 import conexiones_repo as CR

    MV = V._mv()
    belts = CC._belts_por_servidor()
    entorno = MV._entorno_de_belts()
    conn = repo.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT user_id FROM conexiones")
            duenos = [str(r[0]) for r in cur.fetchall()]
        candidatas = []
        for u in duenos:
            for e in CR.listar_entidades(conn, u):
                eid = str(e.get("entity_id"))
                ref = (belts.get(eid) or {}).get("belt_ref") or CC._belt_ref_de_fila(e)
                if not ref or not e.get("habilitado", True):
                    continue
                candidatas.append((u, ref, eid))
    finally:
        conn.close()

    from app.phase1.credential_broker import make_user_resolver

    sin_llave = None
    for u, ref, eid in candidatas:
        try:
            spec = MV._spec_de_belt(ref, eid)
        except Exception:  # noqa: BLE001
            continue
        if not spec or not V._pide_llave(spec, entorno):
            continue
        try:
            real = make_user_resolver(u, get_conn=repo.get_conn)(
                spec.get("connector") or eid) or ""
        except Exception:  # noqa: BLE001
            real = ""
        if not real and not (V._credenciales_por_var(spec, u, repo.get_conn) or {}):
            sin_llave = (u, ref, eid)
            break

    if sin_llave is None:
        print("  · [no medible] esta máquina no tiene ninguna pieza que pida credencial "
              "sin tenerla; el atajo sin-red no se pudo ejercer con datos reales")
    else:
        u, ref, eid = sin_llave
        espia["spawn"] = 0
        espia["quien"] = f"verificar_uno({eid})"
        V._spawn = _spawn_delator
        try:
            fila = V.verificar_uno(ref, eid, owner=u, get_conn=repo.get_conn,
                                   solo_conexion=True)
            cx = fila.get("conexion") or {}
            ok(espia["spawn"] == 0,
               f"«{eid}» pide credencial y no la tiene: NO se spawnea nada",
               f"{espia['spawn']} spawn(s)")
            ok(cx.get("causa") == MV.FALTA_KEY,
               f"«{eid}» devuelve la causa `falta_key`", str(cx.get("causa")))
            ok((fila.get("credencial") or {}).get("estado") == V.SIN_MEDIR,
               "y la credencial queda en `sin_medir` (null declarado, no un veredicto)",
               str((fila.get("credencial") or {}).get("estado")))
        except Delator as e:
            ok(False, f"«{eid}» pide credencial y no la tiene: NO se spawnea nada", str(e))
        finally:
            V._spawn = v_spawn

    # LA CAUSA LLEVA COPY. Sin esto el atajo produce un rojo que la pantalla no sabe decir.
    semaforo = (RAIZ / "product" / "app" / "design" / "cuarto"
                / "cuarto.semaforo.js").read_text(encoding="utf-8")
    ok(re.search(r"\bfalta_key\b", semaforo) is not None,
       "`falta_key` tiene copy en el diccionario sellado del semáforo")

    # ── 4 · `key_invalida` NO ES `sin_red` ───────────────────────────────────────────
    ok(hasattr(MV, "REINTENTABLE") and hasattr(MV, "es_reintentable"),
       "el criterio de reintento está sellado en `motor_verdad`")
    ok(MV.es_reintentable(MV.SIN_RED) is True, "`sin_red` es reintentable")
    ok(MV.es_reintentable(MV.TIMEOUT) is True, "`timeout` es reintentable")
    ok(MV.es_reintentable(MV.RATE_LIMIT) is True, "`rate_limit` es reintentable")
    ok(MV.es_reintentable(MV.KEY_INVALIDA) is False, "`key_invalida` NO es reintentable")
    ok(MV.es_reintentable(MV.OAUTH_REVOCADO) is False, "`oauth_revocado` NO es reintentable")
    ok(MV.es_reintentable(MV.FALTA_KEY) is False, "`falta_key` NO es reintentable")
    ok(MV.es_reintentable(None) is False,
       "`None` NO es reintentable (sin causa no hay fallo: un null no se rellena)")
    ok(MV.es_reintentable("una_causa_que_no_existe") is False,
       "una causa desconocida NO es reintentable (el default seguro es no gastar)")
    ok(MV.REINTENTABLE <= MV.CAUSAS,
       "toda causa reintentable está en el vocabulario cerrado (o sea: tiene copy)",
       str(sorted(MV.REINTENTABLE - MV.CAUSAS)))

    # Y la tupla suelta no puede volver: dos copias del criterio es cómo se desincronizan.
    cc = (RAIZ / "product" / "backend" / "app" / "phase1"
          / "centro_conexiones.py").read_text(encoding="utf-8")
    ok("MV.SIN_CREDITO, MV.RATE_LIMIT, MV.SIN_RED, MV.TIMEOUT" not in cc,
       "no quedó ninguna copia suelta del criterio en centro_conexiones")

    print("\n✗ %d fallo(s)" % len(FALLOS) if FALLOS
          else "\n✓ cuándo se verifica: todo verde")
    return 1 if FALLOS else 0


if __name__ == "__main__":
    raise SystemExit(main())
