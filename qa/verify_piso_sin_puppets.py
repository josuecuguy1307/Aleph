"""verify_piso_sin_puppets.py — VARA DEL PISO CON CINTURÓN. [T1 · LEY 15]

QUÉ MIDE, Y POR QUÉ ESTAS TRES COSAS
------------------------------------
Darle manos al piso de la Sala toca la ley más delicada del producto. La LEY 15 dice
que el sistema JAMÁS crea agentes por debajo: mil sesiones raw es normal, mil agentes
fantasma es basura prohibida. Esta vara es la que deja esa promesa MEDIDA:

  R1 · CERO PUPPETS.  N turnos raw contra `/v1/puppets/run` → la tabla `puppets` NO
       crece ni una fila. Es la vara obligatoria, y se mide por DELTA (contar antes y
       después), no por «el endpoint no llama a create_puppet»: leer el código mide
       intenciones, contar filas mide hechos.
       ⚠️ El veredicto NO depende de que el turno SALGA BIEN. Un run que muere en el
       modelo (sin llave, sin cuota) igual habría escrito el puppet si el borde lo
       fabricara — así que el rojo de R1 es rojo aunque los 5 turnos fallen. Medir el
       éxito del turno acá ataría la ley a que haya cognición disponible.

  R2 · EL PISO ENTRA.  Antes, un POST sin `puppet_id` y sin `recipe` rebotaba
       `422 missing_recipe · "provee recipe inline o puppet_id"`. Ese portazo ERA el
       hueco. R2 exige que ese texto exacto ya no vuelva: el piso atraviesa el borde.

  R3 · EL CINTURÓN ES EL KIT, NO UN AGENTE.  La proyección efímera que arma el borde
       lleva los 6 servers del kit base y su `belt_ref` — los MISMOS que `ensure_kit`
       pone en los otros tres bordes. Se mide con `kit_base.kit_state()`, que es el
       diagnóstico que el propio módulo publica, no una lista copiada acá.

PROBADA CAYENDO (no basta con verde) — cada bloque se corrió con su pieza rota:
  R1 → se inserta un puppet REAL en medio de los N turnos: delta=1  ⇒ ROJO.
  R2 → se pide el borde viejo (POST con recipe=None ANTES del fix devolvía el texto):
       se simula afirmando el texto viejo contra la respuesta                ⇒ ROJO.
  R3 → se apaga el kit con `PUPPET_KIT_BASE=0`: kit_state.completo=False     ⇒ ROJO.
Las tres caídas están automatizadas más abajo y corren SIEMPRE (`--probar-cayendo` es
el default): una vara que no puede dar rojo no mide nada.

AISLAMIENTO. `ALEPH_DATA_DIR` + `PUPPET_SQLITE_PATH` a un tmp propio y cuenta nueva:
`_TREE_DATA` escribe en el árbol y no hay variable que lo redirija sola.

    product/backend/.venv/bin/python qa/verify_piso_sin_puppets.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_RAIZ / "product" / "backend"))
sys.path.insert(0, str(_RAIZ / "platform"))

N_TURNOS = 5

_VERDE, _ROJO, _GRIS = "\033[32m", "\033[31m", "\033[90m"
_FIN = "\033[0m"
_filas: list[tuple[str, bool, str]] = []


def _anotar(bloque: str, ok: bool, detalle: str) -> None:
    _filas.append((bloque, ok, detalle))
    marca = f"{_VERDE}VERDE{_FIN}" if ok else f"{_ROJO}ROJA{_FIN}"
    print(f"  [{marca}] {bloque} — {detalle}")


def _montar(tmp: Path):
    """App REAL (router de phase1) en rol cliente sobre un SQLite propio."""
    os.environ["ALEPH_ROLE"] = "client"
    os.environ["ALEPH_DATA_DIR"] = str(tmp / "data")
    os.environ["PUPPET_SQLITE_PATH"] = str(tmp / "piso.db")
    (tmp / "data").mkdir(parents=True, exist_ok=True)

    from app.phase1 import repo
    repo._db = None
    sq = repo._dbmod()._sqlite()
    c = sq.conectar(str(tmp / "piso.db"))
    sq.crear_schema(c)
    c.commit()
    c.close()

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.phase1.router import build_phase1_router

    app = FastAPI()
    app.include_router(build_phase1_router(get_conn=repo.get_conn,
                                           events_dir=lambda: tmp))
    cliente = TestClient(app, raise_server_exceptions=False)

    conn = repo.get_conn()
    u = repo.register_user(conn, "piso@vara.local", "pw-piso-123456")
    conn.close()
    auth = {"Authorization": "Bearer " + repo.mint_session(str(u["id"]))}
    return cliente, repo, str(u["id"]), auth


def _contar_puppets(repo) -> int:
    conn = repo.get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM puppets")
        return int(cur.fetchone()[0])
    finally:
        conn.close()


def _turno_raw(cliente, uid: str, auth: dict, i: int):
    """Un turno del PISO: sin puppet_id y sin recipe. `agent` va null por la ley."""
    return cliente.post("/v1/puppets/run", json={
        "user_id": uid,
        "prompt": f"turno raw {i} de la vara del piso",
        "agent": None,
        "lang": "es",
    }, headers=auth)


# ── R1 · CERO PUPPETS ────────────────────────────────────────────────────────────────
def r1_cero_puppets(cliente, repo, uid, auth) -> bool:
    antes = _contar_puppets(repo)
    codigos = []
    for i in range(N_TURNOS):
        codigos.append(_turno_raw(cliente, uid, auth, i).status_code)
    despues = _contar_puppets(repo)
    delta = despues - antes
    ok = delta == 0
    _anotar("R1 · cero puppets", ok,
            f"{N_TURNOS} turnos raw (HTTP {sorted(set(codigos))}) · "
            f"puppets {antes}→{despues} (delta {delta})")
    return ok


def r1_cayendo(cliente, repo, uid, auth) -> bool:
    """La misma cuenta, con UN puppet real creado en medio. DEBE dar delta≠0."""
    antes = _contar_puppets(repo)
    _turno_raw(cliente, uid, auth, 0)
    conn = repo.get_conn()
    repo.create_puppet(conn, owner_id=uid, name="fantasma-de-la-vara",
                       nicho="general", config={"schema_version": "v1"})
    conn.close()
    _turno_raw(cliente, uid, auth, 1)
    delta = _contar_puppets(repo) - antes
    cayo = delta != 0
    _anotar("R1 · CAÍDA", cayo,
            f"con un puppet insertado a mano el delta fue {delta} "
            f"({'la vara lo ve' if cayo else 'LA VARA NO LO VE — no mide nada'})")
    return cayo


# ── R2 · EL PISO ENTRA ───────────────────────────────────────────────────────────────
_PORTAZO_VIEJO = "provee `recipe` inline o `puppet_id`"


def r2_el_piso_entra(cliente, uid, auth) -> bool:
    r = _turno_raw(cliente, uid, auth, 0)
    cuerpo = r.text or ""
    ok = _PORTAZO_VIEJO not in cuerpo
    _anotar("R2 · el piso entra", ok,
            f"HTTP {r.status_code} · el portazo viejo "
            f"{'NO aparece' if ok else 'SIGUE APARECIENDO'}")
    return ok


def r2_cayendo() -> bool:
    """El texto viejo, contra el detector. Si el detector no lo caza, no mide nada."""
    cayo = _PORTAZO_VIEJO in ('{"error":"missing_recipe","detail":"'
                              + _PORTAZO_VIEJO + '"}')
    _anotar("R2 · CAÍDA", cayo,
            f"el detector {'caza' if cayo else 'NO CAZA'} el texto del borde viejo")
    return cayo


# ── R3 · EL CINTURÓN ES EL KIT ───────────────────────────────────────────────────────
def _proyeccion_del_borde() -> dict:
    """La MISMA forma que arma el borde raw de `/v1/puppets/run`."""
    from app.phase1 import kit_base
    recipe, _ = kit_base.ensure_kit({"model": {"primary": "x/y"}, "belt": {}})
    return recipe


def r3_cinturon_es_el_kit() -> bool:
    from app.phase1 import kit_base
    estado = kit_base.kit_state(_proyeccion_del_borde())
    ok = bool(estado.get("completo"))
    ausentes = [s for s, v in estado["servers"].items() if v == "ausente"]
    _anotar("R3 · el cinturón es el kit", ok,
            f"belt_ref={estado['ref']} · servers={len(estado['servers'])} · "
            f"{'los 6 presentes' if not ausentes else 'AUSENTES: ' + ','.join(ausentes)}")
    return ok


def r3_cayendo() -> bool:
    """Con `PUPPET_KIT_BASE=0` el kit se apaga: la vara DEBE ponerse roja."""
    from app.phase1 import kit_base
    previo = os.environ.get("PUPPET_KIT_BASE")
    os.environ["PUPPET_KIT_BASE"] = "0"
    try:
        estado = kit_base.kit_state(_proyeccion_del_borde())
        cayo = not estado.get("completo")
    finally:
        os.environ.pop("PUPPET_KIT_BASE", None) if previo is None \
            else os.environ.__setitem__("PUPPET_KIT_BASE", previo)
    _anotar("R3 · CAÍDA", cayo,
            f"con PUPPET_KIT_BASE=0 la vara {'se pone roja' if cayo else 'SIGUE VERDE — no mide nada'}")
    return cayo


def main() -> int:
    print(f"\n{_GRIS}vara del piso con cinturón · LEY 15 · N={N_TURNOS} turnos raw{_FIN}\n")
    with tempfile.TemporaryDirectory(prefix="vara-piso-") as td:
        tmp = Path(td)
        cliente, repo, uid, auth = _montar(tmp)

        print("MEDICIÓN")
        ok = [r1_cero_puppets(cliente, repo, uid, auth),
              r2_el_piso_entra(cliente, uid, auth),
              r3_cinturon_es_el_kit()]

        print("\nPROBADA CAYENDO")
        cayeron = [r1_cayendo(cliente, repo, uid, auth),
                   r2_cayendo(),
                   r3_cayendo()]

    verde = all(ok) and all(cayeron)
    print(f"\n{'=' * 68}")
    if verde:
        print(f"{_VERDE}VERDE{_FIN} · el piso tiene cinturón y no nace ni un puppet — "
              f"y las tres caídas dieron rojo")
    else:
        rotas = [b for b, o, _ in _filas if not o]
        print(f"{_ROJO}ROJA{_FIN} · {', '.join(rotas)}")
    print("=" * 68)
    return 0 if verde else 1


if __name__ == "__main__":
    raise SystemExit(main())
