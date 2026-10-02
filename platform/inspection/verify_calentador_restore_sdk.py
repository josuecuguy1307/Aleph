#!/usr/bin/env python3
"""verify_calentador_restore_sdk.py — el CICLO matar/relevantar sobre el transporte nuevo.

Dos piezas del producto que levantan servers por su cuenta y que la vara de la sesión 2
exige medir por el puente:

  A · EL CALENTADOR (§6) — `calentar_cinturon.calentar()`, lo que la Sala dispara al abrir
      un agente. Levanta cada pieza habilitada, la mide y persiste. Se corre con los DOS
      transportes sobre el MISMO agente y se comparan los veredicto pieza por pieza.

  B · EL RESTORE — `restaurador.restaurar_servers()`, lo que arma el pool de un run desde
      el registro. Se corre con los DOS transportes y se compara el `parte()`; después se
      APAGA el pool y se cuenta si quedó algún proceso vivo. Ése es el ciclo completo:
      levantar de verdad, hablar, y morir sin dejar nada.

⚠️ DRY-RUN, Y NO ES OPCIONAL. `calentar()` **PERSISTE**: escribe `conexion`, `credencial`,
`era` y `version_negociada` en el registro del usuario y hace `commit()`. Correrlo desde una
vara con la conexión real le REESCRIBE el registro — y con el SDK la versión negociada es
otra (2025-11-25 vs el 2024-11-05 clavado del cliente viejo), así que una corrida de
verificación le dejaría al usuario datos de un transporte que todavía está a revisión.

PASÓ, la primera vez que se corrió esto: cinco filas (filesystem · fetch · context7 · exa ·
pandoc) quedaron con `version_negociada=2025-11-25`. Se restauraron re-midiéndolas con
`ALEPH_TRANSPORTE=viejo` —re-medir no es fabricar: el valor volvió a salir del mismo lugar
del que había salido— y el registro quedó como estaba (14× 2024-11-05 · 28 sin dato).

Por eso `_ConnSinCommit`: se ejerce TODO el camino, escritura incluida, y al cerrar se hace
rollback. **No sacar ese wrapper.** El restore nunca escribió y no necesita el guard.

Correr:
    product/backend/.venv/bin/python platform/inspection/verify_calentador_restore_sdk.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
_RAIZ = _AQUI.parents[1]
for _p in (_RAIZ / "platform", _RAIZ / "platform/db", _RAIZ / "platform/inspection",
           _RAIZ / "platform/assembler", _RAIZ / "product/backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
os.environ.setdefault("ALEPH_ROLE", "client")

#: Las piezas del restore: dos que arrancan y una que no. Reales, del registro.
PIEZAS_RESTORE = ["sqlite", "fetch", "time"]

_fallos = 0


def ok(cond, nombre, detalle=""):
    global _fallos
    if cond:
        print(f"    ✓ {nombre}")
    else:
        _fallos += 1
        print(f"    ✗ {nombre}" + (f" — {detalle}" if detalle else ""))


def _limpiar():
    """Soltar todo lo que cachea la clase de transporte entre corrida y corrida."""
    for nombre in list(sys.modules):
        raiz = nombre.split(".")[0]
        if raiz in {"transporte", "transporte_sdk", "byo_mcp", "traductor_errores",
                    "puppet_transporte"} or nombre.startswith("app.phase1."):
            sys.modules.pop(nombre, None)


def _procesos_vivos(marcas) -> list:
    r = subprocess.run(["ps", "-eo", "pid,command"], capture_output=True, text=True)
    return [l.strip()[:110] for l in r.stdout.splitlines()
            if any(m in l for m in marcas) and "ps -eo" not in l]


# ══════════════════════════════════════════════════════════════════════════════════
# A · EL CALENTADOR
# ══════════════════════════════════════════════════════════════════════════════════

#: Cuántas piezas del agente se calientan acá. El agente real tiene 22 y cada una con
#: llave paga DOS spawns (la prueba doble): medir las 22 por DOS transportes son minutos.
#: Se acota, se declara, y el recorte es idéntico en las dos corridas — así lo comparado
#: sigue siendo lo mismo.
MAX_PIEZAS_VARA = 6


class _ConnSinCommit:
    """La conexión real, con `commit()` desactivado y `close()` que hace ROLLBACK.

    ⚠️ HACE FALTA: `calentar()` NO es una medición pura — persiste lo medido en el registro
    (`CR.upsert_entidad` + `conn.commit()`). Correrlo dos veces desde una vara le
    reescribiría al usuario `era` y `version_negociada`, y con el SDK esa versión ES
    distinta (2026-07-28 negociado hacia abajo vs el 2024-11-05 clavado del cliente viejo).
    Una vara que para medir cambia lo que mide no es una vara. Acá se ejerce TODO el camino
    —incluida la escritura— y al final se descarta.
    """

    def __init__(self, real):
        self._real = real

    def __getattr__(self, nombre):
        return getattr(self._real, nombre)

    def commit(self):
        return None

    def close(self):
        try:
            self._real.rollback()
        except Exception:                                    # noqa: BLE001
            pass
        return self._real.close()


def _calentar_con(transporte: str, puppet_id: str, owner: str, get_conn) -> dict:
    os.environ["ALEPH_TRANSPORTE"] = transporte
    _limpiar()
    from app.phase1 import calentar_cinturon as C            # noqa: E402
    import transporte as TP                                  # noqa: E402
    t0 = time.perf_counter()
    salida = C.calentar(puppet_id, owner=owner,
                        get_conn=lambda: _ConnSinCommit(get_conn()),
                        max_piezas=MAX_PIEZAS_VARA)
    return {"elegido": TP.elegido()["transporte"], "ms": int((time.perf_counter() - t0) * 1000),
            "salida": salida}


def _resumen_calentado(salida: dict) -> dict:
    """Lo que tiene que coincidir: por pieza, el veredicto. Latencias y textos no.

    `era`/`version_negociada` quedan AFUERA de la comparación a propósito, y es el único
    campo que se espera distinto: el cliente viejo pide `2024-11-05` clavado y el SDK
    negocia lo que el server ofrezca. No es un veredicto — es con qué revisión se habló — y
    se reporta aparte."""
    piezas = {}
    for p in salida.get("piezas") or []:
        piezas[p.get("server")] = {"conexion": p.get("conexion"), "causa": p.get("causa"),
                                   "credencial": p.get("credencial")}
    return {"piezas": piezas,
            "apagadas": sorted(salida.get("apagadas") or []),
            "sin_registro": sorted(salida.get("sin_registro") or []),
            "sin_medir": sorted(salida.get("sin_medir") or [])}


def _eras(salida: dict) -> dict:
    return {p.get("server"): p.get("era") for p in (salida.get("piezas") or [])}


def parte_a(owner, get_conn) -> None:
    print("── A · EL CALENTADOR (§6) ─────────────────────────────────────────────")
    from app.phase1 import calentar_cinturon as C0           # noqa: E402
    conn = get_conn()
    try:
        elegido_id, cuantas = None, 0
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM puppets")
            ids = [r[0] for r in cur.fetchall()]
        for pid in ids:
            n = len(C0.piezas_del_agente(conn, pid))
            if n > cuantas:
                elegido_id, cuantas = pid, n
    finally:
        conn.close()
    if not elegido_id:
        ok(False, "hay un agente con piezas para calentar", "ninguno declara piezas")
        return
    print(f"    agente {elegido_id[:8]}… con {cuantas} pieza(s)")
    viejo = _calentar_con("viejo", elegido_id, owner, get_conn)
    nuevo = _calentar_con("sdk", elegido_id, owner, get_conn)
    ok(viejo["elegido"] == "legacy" and nuevo["elegido"] == "sdk",
       "cada corrida calentó con el transporte pedido",
       f"{viejo['elegido']} / {nuevo['elegido']}")
    rv, rn = _resumen_calentado(viejo["salida"]), _resumen_calentado(nuevo["salida"])
    print(f"      viejo  ({viejo['ms']:>5} ms)  {json.dumps(rv, ensure_ascii=False)}")
    print(f"      puente ({nuevo['ms']:>5} ms)  {json.dumps(rn, ensure_ascii=False)}")
    ok(rv == rn, "el calentado da EL MISMO veredicto por pieza en los dos transportes")
    if not rv == rn:
        for k in sorted(set(rv["piezas"]) | set(rn["piezas"])):
            if rv["piezas"].get(k) != rn["piezas"].get(k):
                print(f"        {k}: viejo={rv['piezas'].get(k)} puente={rn['piezas'].get(k)}")
    ok(_eras(viejo["salida"]) == _eras(nuevo["salida"]),
       "la ERA del protocolo también coincide (`handshake` en los dos)",
       f"viejo={_eras(viejo['salida'])} puente={_eras(nuevo['salida'])}")
    ok(viejo["salida"].get("sin_medir") == nuevo["salida"].get("sin_medir"),
       f"el recorte a {MAX_PIEZAS_VARA} piezas fue el mismo en las dos corridas")


# ══════════════════════════════════════════════════════════════════════════════════
# B · EL RESTORE + EL CIERRE
# ══════════════════════════════════════════════════════════════════════════════════

def _restaurar_con(transporte: str, owner: str) -> dict:
    os.environ["ALEPH_TRANSPORTE"] = transporte
    _limpiar()
    import importlib.util

    import aleph_paths                                        # noqa: E402
    import transporte as TP                                   # noqa: E402
    from app.phase1 import conexiones_repo as CR              # noqa: E402
    from app.phase1 import repo                               # noqa: E402

    ruta = aleph_paths.resource_root() / "platform" / "assembler" / "restaurador.py"
    sp = importlib.util.spec_from_file_location("restaurador_vara", str(ruta))
    R = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(R)

    conn = repo.get_conn()
    try:
        filas = {e["entity_id"]: e for e in CR.listar_entidades(conn, owner)}
    finally:
        conn.close()
    presentes = [n for n in PIEZAS_RESTORE if n in filas]

    # `servers_raw` es el bloque del `.mcp.json`; acá sólo hace falta que EXISTA la clave,
    # porque las tres piezas salen del REGISTRO (que es el primer lector).
    servers_raw = {n: {"command": filas[n].get("command") or "",
                       "args": list(filas[n].get("args") or [])} for n in presentes}

    # ⚠️ EL EXPANSOR Y EL `env_efectivo` SON LOS DEL PRODUCTO, no stubs. Con un stub, las
    # tres piezas caían («arrancadas: []») y la comparación daba verde comparando dos
    # nadas — el guard de «levantó procesos de verdad» es lo que lo destapó.
    RA = aleph_paths.load_module_by_path(
        "recipe_assembler_vara",
        aleph_paths.resource_root() / "platform" / "assembler" / "recipe_assembler.py")
    base_env = RA._puppet_run_env(str(aleph_paths.resource_root()), dict(os.environ)) \
        if hasattr(RA, "_puppet_run_env") else dict(os.environ)

    t0 = time.perf_counter()
    res = R.restaurar_servers(
        servers_raw, base_env,
        expandir=RA._expand_server_cfg,
        mcp_server_cls=TP.servidor_stdio(),
        leer_entidad=lambda n: filas.get(n),
        env_efectivo=CR.env_efectivo,
    )
    parte = res.parte()
    vivos_antes = _procesos_vivos(("mcp-server-fetch", "mcp-server-sqlite", "mcp-server-time"))
    for p in res.piezas:                                      # EL CICLO: ahora se apagan
        if p.servidor is not None:
            try:
                p.servidor.stop()
            except Exception:                                 # noqa: BLE001
                pass
    time.sleep(1.2)
    vivos_despues = _procesos_vivos(("mcp-server-fetch", "mcp-server-sqlite", "mcp-server-time"))
    return {"elegido": TP.elegido()["transporte"], "presentes": presentes,
            "ms": int((time.perf_counter() - t0) * 1000),
            "parte": {k: parte.get(k) for k in ("total", "arrancadas", "caidas")},
            "vivos_antes": vivos_antes, "vivos_despues": vivos_despues}


def parte_b(owner) -> None:
    print("\n── B · EL RESTORE + EL CIERRE ─────────────────────────────────────────")
    viejo = _restaurar_con("viejo", owner)
    nuevo = _restaurar_con("sdk", owner)
    ok(viejo["elegido"] == "legacy" and nuevo["elegido"] == "sdk",
       "cada corrida restauró con el transporte pedido")
    ok(viejo["presentes"] == nuevo["presentes"] and viejo["presentes"],
       f"las mismas piezas del registro: {viejo['presentes']}")
    print(f"      viejo  ({viejo['ms']:>5} ms)  {json.dumps(viejo['parte'], ensure_ascii=False)}")
    print(f"      puente ({nuevo['ms']:>5} ms)  {json.dumps(nuevo['parte'], ensure_ascii=False)}")
    ok(viejo["parte"] == nuevo["parte"],
       "el `parte()` del restore es IDÉNTICO en los dos transportes")
    ok(len(nuevo["vivos_antes"]) > 0,
       f"el puente levantó procesos de verdad ({len(nuevo['vivos_antes'])} vivos)",
       "si es 0, no se midió nada")
    ok(nuevo["vivos_despues"] == [],
       "tras apagar el pool por el puente NO queda ningún proceso vivo",
       str(nuevo["vivos_despues"]))
    ok(viejo["vivos_despues"] == [],
       "…y el cliente viejo tampoco deja ninguno (paridad, no mejora)",
       str(viejo["vivos_despues"]))


# ══════════════════════════════════════════════════════════════════════════════════
# C · EL CALENTADOR CON DUEÑO (D3) · lo que sostener compra, medido
# ══════════════════════════════════════════════════════════════════════════════════

def _calentar_medido(puppet_id, owner, get_conn, max_piezas):
    from app.phase1 import calentar_cinturon as C            # noqa: E402
    t0 = time.perf_counter()
    salida = C.calentar(puppet_id, owner=owner,
                        get_conn=lambda: _ConnSinCommit(get_conn()),
                        max_piezas=max_piezas)
    return int((time.perf_counter() - t0) * 1000), salida


def _veredictos(salida):
    return {p["server"]: (p["conexion"], p["causa"], p["credencial"])
            for p in (salida.get("piezas") or [])}


def parte_c(owner, get_conn) -> None:
    print("\n── C · EL CALENTADOR CON DUEÑO (D3) ──────────────────────────────────")
    from app.phase1 import calentar_cinturon as C0           # noqa: E402
    conn = get_conn()
    try:
        elegido_id, cuantas = None, 0
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM puppets")
            ids = [r[0] for r in cur.fetchall()]
        for pid in ids:
            n = len(C0.piezas_del_agente(conn, pid))
            if n > cuantas:
                elegido_id, cuantas = pid, n
    finally:
        conn.close()
    if not elegido_id:
        ok(False, "hay un agente con piezas", "ninguno declara piezas")
        return

    # ── (1) SIN dueño: el comportamiento de siempre, y la referencia de tiempo
    os.environ.pop("ALEPH_DUENO", None)
    _limpiar()
    ms_sin_1, sal_sin_1 = _calentar_medido(elegido_id, owner, get_conn, MAX_PIEZAS_VARA)
    ms_sin_2, sal_sin_2 = _calentar_medido(elegido_id, owner, get_conn, MAX_PIEZAS_VARA)
    ok(_veredictos(sal_sin_1) == _veredictos(sal_sin_2),
       "sin dueño, dos pasadas dan el mismo veredicto (la medición es estable)")

    # ── (2) CON dueño: la 1ª spawnea todo, la 2ª tiene que ENCONTRAR procesos vivos
    os.environ["ALEPH_DUENO"] = "on"
    _limpiar()
    import dueno as DU                                       # noqa: E402
    DU._reset_para_tests()
    ms_con_1, sal_con_1 = _calentar_medido(elegido_id, owner, get_conn, MAX_PIEZAS_VARA)
    _ev1 = DU.actual().estado()["eventos"]
    spawns_1, efim_1 = _ev1["spawns"], _ev1["efimeras_cerradas"]
    vivas_1 = DU.actual().estado()["vivas"]
    ok(len(vivas_1) > 0,
       f"tras calentar, el dueño SOSTIENE {len(vivas_1)} conexión(es) — antes se apagaban todas")
    ok(sorted(sal_con_1.get("sostenidas") or []) == sorted({v["entity_id"] for v in vivas_1}),
       "…y el calentado lo REPORTA por nombre (`sostenidas`)",
       str(sal_con_1.get("sostenidas")))
    pids_vivos = [pid for v in vivas_1 for pid in v["pids"]]
    ok(_procesos_vivos_por_pid(pids_vivos) == pids_vivos,
       "los procesos están vivos DE VERDAD, no sólo en la tabla",
       f"{len(pids_vivos)} pids anotados")

    ms_con_2, sal_con_2 = _calentar_medido(elegido_id, owner, get_conn, MAX_PIEZAS_VARA)
    _ev2 = DU.actual().estado()["eventos"]
    spawns_2 = _ev2["spawns"] - spawns_1
    efim_2 = _ev2["efimeras_cerradas"] - efim_1
    compartidas = _ev2["compartidas"]
    rotas = len([p for p in (sal_con_2.get("piezas") or []) if p.get("conexion") == "rota"])
    ok(compartidas > 0,
       f"la SEGUNDA pasada REUSÓ conexiones vivas ({compartidas} veces)",
       "si es 0, no encontró nada y sostener no sirvió de nada")

    # ── (3) LOS VEREDICTOS NO CAMBIAN. Es la regla madre, y es lo que se para si falla.
    ok(_veredictos(sal_sin_1) == _veredictos(sal_con_1),
       "1ª pasada: MISMO veredicto por pieza con dueño y sin dueño")
    ok(_veredictos(sal_sin_2) == _veredictos(sal_con_2),
       "2ª pasada: MISMO veredicto por pieza — reusar un proceso no cambia lo que se mide")
    ok(sorted(sal_sin_1.get("sin_medir") or []) == sorted(sal_con_1.get("sin_medir") or []),
       "y el recorte de piezas es el mismo")

    # ── (4) EL BENEFICIO, medido
    print(f"      spawns      1ª {spawns_1:>6}      2ª {spawns_2:>6}"
          f"      (reusos en la 2ª: {compartidas})")
    print(f"      sin dueño   1ª {ms_sin_1:>6} ms   2ª {ms_sin_2:>6} ms")
    print(f"      con dueño   1ª {ms_con_1:>6} ms   2ª {ms_con_2:>6} ms"
          f"   → vs sin dueño: {ms_sin_2 - ms_con_2:+d} ms")

    # ⚠️ LO QUE SE AFIRMA SON LOS SPAWNS, NO EL RELOJ. El reloj de pared acá está DOMINADO
    # POR LA RED: exa y context7 hacen llamadas reales en la prueba doble de credencial, y
    # sobre ~9 s de total el ahorro del spawn son 2-3 s. Medido en cuatro corridas, el delta
    # dio +4490, +3089, +879 ms… y una vez −9372, porque una llamada a la API tardó diez
    # segundos de más. Un umbral de tiempo sobre eso no mide sostener: mide la red del día.
    #
    # Los SPAWNS sí son deterministas y son exactamente la afirmación: la segunda pasada no
    # levanta procesos porque los encontró vivos. El tiempo se REPORTA —es lo que el usuario
    # siente— pero no decide el verde.
    # LO QUE LA 2ª PASADA TIENE QUE SPAWNEAR, y nada más:
    #   · las sondas de credencial con basura, que son EFÍMERAS por diseño y se cierran al
    #     soltarlas — respawnearlas cada vez es correcto, sostenerlas sería el desperdicio;
    #   · las piezas ROTAS, que nunca llegaron a arrancar y por lo tanto no hay qué sostener.
    # Todo lo demás tiene que venir de la tabla. El número sale de los datos de la corrida,
    # no de una constante: si mañana el agente tiene otra pieza, la cuenta se acomoda sola.
    esperados = efim_2 + rotas
    ok(spawns_2 == esperados,
       f"la 2ª pasada spawneó SÓLO lo que no se puede reusar: {spawns_2} "
       f"({efim_2} sondas efímeras + {rotas} rota(s)) — el resto lo encontró vivo",
       f"spawneó {spawns_2}, esperados {esperados}")
    ok(compartidas >= len(vivas_1),
       f"y REUSÓ las {len(vivas_1)} conexiones sostenidas ({compartidas} reusos)",
       f"{compartidas} reusos para {len(vivas_1)} sostenidas")
    # ⚠️ EL RELOJ SE REPORTA, NO SE JUZGA — y hasta hoy esta línea se juzgaba a sí misma.
    # Era un `ok(ms_con_2 < ms_sin_2, …)` cuyo propio mensaje decía «REPORTE, no gate», o
    # sea que contaba como FALLO algo que declaraba no ser un gate. Medido en dos pasadas
    # seguidas del MISMO código: +474 ms (verde) y −3405 ms (rojo). Es la trampa 8 del acta
    # —el reloj está dominado por la red, porque exa/context7 hacen llamadas reales— y el
    # gate del beneficio son los SPAWNS, que se miden dos líneas más arriba y sí son
    # estables. Una vara que cría lobos deja de leerse, y entonces no sirve la vez que
    # tiene razón.
    _delta = ms_sin_2 - ms_con_2
    print(f"    ⏱  reloj (REPORTE, no gate): 2ª pasada {ms_con_2} ms con dueño vs "
          f"{ms_sin_2} ms sin dueño → {_delta:+d} ms")
    if _delta <= 0:
        print("       (negativo: es la red del momento, no una regresión — mirá los spawns)")

    # ── (5) LA SONDA DE CREDENCIAL NO SE SOSTIENE (D3)
    ok(not any(v["efimera"] for v in DU.actual().estado()["vivas"]),
       "ninguna conexión EFÍMERA quedó sostenida — la sonda con basura se cierra sola",
       str([v["entity_id"] for v in DU.actual().estado()["vivas"] if v["efimera"]]))
    ok(DU.actual().estado()["eventos"]["efimeras_cerradas"] > 0,
       "…y se cerraron las que hubo, contadas",
       str(DU.actual().estado()["eventos"]["efimeras_cerradas"]))

    # ── (6) CERO HUÉRFANOS al apagar
    todos = [pid for v in DU.actual().estado()["vivas"] for pid in v["pids"]]
    DU.actual().apagar_todo(motivo="fin de la vara")
    time.sleep(1.0)
    ok(_procesos_vivos_por_pid(todos) == [],
       "y al apagar el dueño no queda NINGÚN proceso vivo (evidencia ps)",
       str(_procesos_vivos_por_pid(todos)))
    os.environ.pop("ALEPH_DUENO", None)


def _procesos_vivos_por_pid(pids):
    import dueno as DU
    return [p for p in pids if DU._vive(p)]


def main() -> int:
    from app.phase1 import repo                               # noqa: E402
    conn = repo.get_conn()
    owner = None
    try:
        with conn.cursor() as cur:
            # EL DUEÑO DEL REGISTRO ES EL QUE TIENE CONEXIONES, no el que tiene una
            # llave cualquiera. `SELECT user_id FROM keys LIMIT 1` aguantó mientras hubo un
            # solo usuario; hoy las varas y la suite crean usuarios de PRUEBA con llave
            # propia (broker-test-a/b, zotero-inject-a, cowork-approve-test), así que un
            # `LIMIT 1` sin ORDER BY devuelve cualquiera — y con un usuario de prueba esto
            # mide el catálogo entero contra un registro VACÍO. Determinista y no vacío.
            cur.execute("SELECT user_id FROM conexiones GROUP BY user_id "
                        "ORDER BY COUNT(*) DESC, user_id LIMIT 1")
            r = cur.fetchone()
            if r is None:                      # sin conexiones no hay registro que mirar;
                cur.execute("SELECT user_id FROM keys LIMIT 1")   # una cuenta suelta sirve
                r = cur.fetchone()
            owner = r[0] if r else None
    finally:
        conn.close()
    if not owner:
        print("✗ no hay owner en `keys`.")
        return 1
    print(f"CALENTADOR + RESTORE · viejo vs puente · owner={owner[:8]}…\n")
    parte_a(owner, repo.get_conn)
    parte_b(owner)
    parte_c(owner, repo.get_conn)
    print(f"\n{'TODO VERDE' if _fallos == 0 else str(_fallos) + ' FALLO(S)'}")
    return 0 if _fallos == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
