#!/usr/bin/env python3
"""verify_obra6b.py — LA VARA DE LOS CUATRO CHICOS. Una sola invocación.

    python3 qa/verify_obra6b.py

Cada punto trae su NEGATIVO. Un testigo que no puede rojear no mide: puede estar mirando la
nada y salir verde igual. Los negativos de acá no son mocks — son la misma función con la
entrada que la hacía fallar, o el dato real que dejó el código de antes.

  #4 · el header con plantilla deja de contar como credencial huérfana (backend + front)
  #5 · la reserva y la evidencia tienen un CLICK que las muestra
  #6 · una pieza traída es átomo equipable, con `belt_ref` relativo al dir de DATOS,
       y NO entra a la receta de ningún agente
  #7 · el equip deja de escribir vocabulario vivo en la memoria del veredicto
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "platform"))
sys.path.insert(0, str(RAIZ / "product" / "backend"))

FALLOS: list[str] = []
RESULTADO: dict[str, object] = {}


def ok(nombre: str, cond: bool, detalle=None) -> bool:
    RESULTADO[nombre] = bool(cond)
    print(("✅ " if cond else "❌ ") + nombre + (f": {detalle}" if detalle is not None else ""))
    if not cond:
        FALLOS.append(nombre)
    return bool(cond)


def no_medible(nombre: str, motivo: str) -> None:
    RESULTADO[nombre] = "NO_MEDIBLE"
    print(f"⚪ {nombre}: NO MEDIBLE — {motivo}")
    FALLOS.append(f"{nombre} (no medible)")


# ══ #4a · EL BACKEND DICE A QUÉ VARIABLE APUNTA CADA HEADER ═══════════════════════════
def bloque_4a() -> None:
    from app.phase1 import centro_conexiones as CC

    fila = {"headers_template": {"Authorization": "Bearer ${RESOLVER_X_API_KEY}"},
            "env_template": {}, "command": None, "url": "https://x.example/mcp",
            "transporte": "stdio", "args": []}
    belt = CC._belt_derivado_de_fila(fila)
    refs = (belt or {}).get("headers_ref") or {}
    ok("4a_el_backend_publica_la_referencia",
       refs.get("Authorization") == ["RESOLVER_X_API_KEY"], {"headers_ref": refs})

    # ⚠️ LA LEY DEL BLOQUE: nombres y referencias, JAMÁS valores. El valor real no puede
    # cruzar la API ni siquiera cuando es plantilla — `Bearer sk-live-abc${FOO}` filtraría
    # el prefijo. Este testigo es el que impide que "arreglarlo" se convierta en una fuga.
    crudo = json.dumps(belt, ensure_ascii=False)
    ok("4a_negativo_el_valor_no_viaja",
       "Bearer" not in crudo and "«valor literal»" in crudo,
       {"headers": (belt or {}).get("headers")})

    # NEGATIVO 2 · un header SIN referencia no inventa una: el mapa queda vacío.
    fila2 = dict(fila, headers_template={"X-Api-Key": "un-literal-cualquiera"})
    belt2 = CC._belt_derivado_de_fila(fila2)
    ok("4a_negativo_sin_plantilla_no_hay_referencia",
       not ((belt2 or {}).get("headers_ref") or {}),
       {"headers_ref": (belt2 or {}).get("headers_ref")})


# ══ #6 · LOS BELTS DEL USUARIO SON ÁTOMOS ════════════════════════════════════════════
def bloque_6() -> None:
    datos = Path(tempfile.mkdtemp(prefix="aleph-6b-datos-"))
    slug = "byo-com-ejemplo-mcp"
    d = datos / "synth_belts" / "u-1" / slug
    d.mkdir(parents=True)
    (d / f"belt-{slug}.mcp.json").write_text(json.dumps({
        "_meta": {"belt": slug, "slug": slug, "byo": True, "source": "registry",
                  "cards": [{"id": "ej-uno", "label": "Ejemplo", "sub": "una card traída",
                             "backed_by": slug, "tools": ["ping"], "auth": "keyless"}]},
        "mcpServers": {slug: {"command": "python3", "args": ["x.py"], "env": {}}},
    }), encoding="utf-8")

    os.environ["ALEPH_DATA_DIR"] = str(datos)
    os.environ["PUPPET_DATA_DIR"] = str(datos)
    import aleph_paths
    for nombre in list(sys.modules):
        if nombre.startswith("app.phase1.atoms_router"):
            del sys.modules[nombre]
    if hasattr(aleph_paths, "data_root") and hasattr(aleph_paths.data_root, "cache_clear"):
        aleph_paths.data_root.cache_clear()
    from app.phase1 import atoms_router as AR

    # ⚠️ EL DUEÑO SE DECLARA (A1 · la fuga entre cuentas). El belt vive bajo `u-1`, y desde
    # que el walk filtra por cuenta hay que decir de quién es la pantalla: pedir el catálogo
    # sin dueño ya no sirve piezas traídas de nadie, que es justamente el arreglo.
    raices = AR._raices_de_belts("u-1")
    atoms = AR.collect_atoms(owner="u-1")
    mio = [a for a in atoms if a.get("id") == "ej-uno"]
    ok("6_la_pieza_traida_es_atomo", len(mio) == 1,
       {"atomos_totales": len(atoms), "raices": len(raices)})

    # …y el testigo que A1 sumó: OTRA cuenta no la ve. La pieza es de `u-1` y de nadie más.
    ajena = [a for a in AR.collect_atoms(owner="u-2") if a.get("id") == "ej-uno"]
    ok("6_y_otra_cuenta_no_la_ve", not ajena, {"encontrados": len(ajena)})

    if mio:
        ref = mio[0].get("belt_ref") or ""
        ok("6_belt_ref_relativo_al_data_root",
           ref.startswith("synth_belts/") and not os.path.isabs(ref)
           and str(RAIZ) not in ref and str(datos) not in ref,
           {"belt_ref": ref})
    else:
        no_medible("6_belt_ref_relativo_al_data_root", "el átomo no apareció")

    # NEGATIVO · con la lista de raíces de antes (sólo el catálogo), el átomo NO existe.
    original = AR._raices_de_belts
    try:
        AR._raices_de_belts = lambda *_a, **_k: [(x, AR._REPO) for x in AR._BELT_DIRS]
        sin = [a for a in AR.collect_atoms(owner="u-1") if a.get("id") == "ej-uno"]
        ok("6_negativo_sin_synth_belts_no_aparece", not sin, {"encontrados": len(sin)})
    finally:
        AR._raices_de_belts = original

    # TRAER ≠ EQUIPAR · el catálogo de átomos no toca puppets, y el equip sólo registra
    # cuando le pasan un puppet_id explícito.
    fuente = (RAIZ / "platform" / "inspection" / "mcp_resolver.py").read_text(encoding="utf-8")
    ok("6_el_equip_solo_registra_con_puppet_id_explicito",
       "if puppet_id:" in fuente and "_register_resolved" in fuente,
       {"guarda": "equip_resolved registra sólo bajo `if puppet_id:`"})
    shutil.rmtree(datos, ignore_errors=True)


# ══ #7 · UN SOLO DUEÑO DEL VEREDICTO ═════════════════════════════════════════════════
def bloque_7() -> None:
    """Se mide sobre el equip REAL: se corre `verify_entrar.py`, que equipa de verdad
    contra un store temporal, y se le mira la fila que dejó."""
    r = subprocess.run([sys.executable, str(RAIZ / "verify_entrar.py")],
                       capture_output=True, text=True, timeout=900, cwd=str(RAIZ))
    linea = [l for l in (r.stdout or "").splitlines() if l.startswith('{"tmp"')]
    if r.returncode != 0 or not linea:
        no_medible("7_el_equip_no_escribe_la_memoria",
                   f"verify_entrar no dejó fila utilizable (rc={r.returncode})")
        no_medible("7_el_estado_vivo_no_se_pierde", "sin fila")
        return
    tmp = Path(json.loads(linea[-1])["tmp"])
    dbs = sorted(tmp.rglob("*.db")) + sorted(tmp.rglob("*.sqlite*"))
    if not dbs:
        no_medible("7_el_equip_no_escribe_la_memoria", f"no encontré la db bajo {tmp}")
        no_medible("7_el_estado_vivo_no_se_pierde", "sin db")
        return
    con = sqlite3.connect(str(dbs[0]))
    filas = con.execute(
        "SELECT entity_id, COALESCE(ultimo_veredicto,''), COALESCE(conexion,'') "
        "FROM conexiones").fetchall()
    con.close()
    equipadas = [f for f in filas if f[0].startswith("byo-")]
    ok("7_el_equip_no_escribe_la_memoria",
       bool(equipadas) and all(f[1] == "" for f in equipadas),
       {"filas": [(f[0], f[1] or "(vacío)") for f in equipadas]})
    vivos = [json.loads(f[2]).get("estado") for f in equipadas if f[2]]
    ok("7_el_estado_vivo_no_se_pierde", all(v for v in vivos), {"conexion.estado": vivos})

    # NEGATIVO · así se veía con el código de antes. Se lee de la db REAL del usuario, que
    # esas filas las escribió el equip viejo: si acá no hubiera vocabulario vivo, este
    # testigo no estaría midiendo nada.
    real = Path.home() / "Library" / "Application Support" / "Aleph" / "aleph.db"
    if not real.exists():
        no_medible("7_negativo_el_equip_viejo_si_la_escribia", "no hay db real que mirar")
        return
    con = sqlite3.connect(f"file:{real}?mode=ro", uri=True)
    viejas = con.execute(
        "SELECT entity_id, ultimo_veredicto FROM conexiones "
        "WHERE entity_id LIKE 'byo-%' AND COALESCE(ultimo_veredicto,'') <> ''").fetchall()
    con.close()
    ok("7_negativo_el_equip_viejo_si_la_escribia", bool(viejas),
       {"filas_del_codigo_viejo": viejas})


def _belt_real() -> str:
    """El belt de una fila REAL con header-plantilla, derivado por el backend real.

    Se lee del registro del usuario si existe. Sin él, el testigo end-to-end se declara NO
    MEDIBLE: fabricar la fila sería probar contra lo que yo mismo escribí."""
    real = Path.home() / "Library" / "Application Support" / "Aleph" / "aleph.db"
    if not real.exists():
        return ""
    con = sqlite3.connect(f"file:{real}?mode=ro", uri=True)
    fila = con.execute(
        "SELECT entity_id, headers_template, env_template, command, args, url, transporte,"
        " credencial_ref, conexion, credencial FROM conexiones"
        " WHERE COALESCE(headers_template,'') <> '' LIMIT 1").fetchone()
    con.close()
    if not fila:
        return ""
    from app.phase1 import centro_conexiones as CC
    jd = lambda v: json.loads(v) if v else {}          # noqa: E731
    cruda = {"headers_template": jd(fila[1]), "env_template": jd(fila[2]),
             "command": fila[3], "args": json.loads(fila[4]) if fila[4] else [],
             "url": fila[5], "transporte": fila[6], "credencial_ref": fila[7]}
    belt = CC._belt_derivado_de_fila(cruda)
    # La MISMA ficha que arma el backend para esta fila. Pasarla en `None` inventaría un
    # «el registro no pide llave» que no existe, y la vara mediría su propio banco.
    ficha = CC._ficha_derivada_de_fila(cruda, belt)
    alias = {}
    if fila[7]:
        for v in (belt or {}).get("env") or {}:
            alias[str(v)] = str(fila[7])
            alias[str(v).upper()] = str(fila[7])
    p = Path(tempfile.mkdtemp(prefix="aleph-6b-belt-")) / "belt.json"
    # La MEDICIÓN REAL de la fila. Con `{}` el adaptador lee `credencial.estado=""` y
    # dispara una contradicción que en la app no existe: la vara estaría midiendo su banco.
    medicion = {"conexion": jd(fila[8]), "credencial": jd(fila[9])}
    p.write_text(json.dumps({"belt": belt, "alias": alias, "entityId": fila[0],
                             "ficha": ficha, "medicion": medicion,
                             "credencialRef": fila[7]}), encoding="utf-8")
    return str(p)


def bloque_front() -> None:
    cmd = ["node", str(RAIZ / "qa" / "verify_obra6b_front.mjs")]
    belt = _belt_real()
    if belt:
        cmd.append(belt)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=str(RAIZ))
    marca = [l for l in (r.stdout or "").splitlines() if l.startswith("__JSON__")]
    if not marca:
        print((r.stdout or "")[-800:], (r.stderr or "")[-800:])
        for n in ("4b_header_que_renderiza_no_cuenta", "5_la_reserva_tiene_un_click"):
            no_medible(n, "la vara de superficie no devolvió JSON")
        return
    for nombre, v in json.loads(marca[-1][len("__JSON__"):]).items():
        detalle = {k: x for k, x in v.items() if k != "ok"} if isinstance(v, dict) else None
        valor = v.get("ok") if isinstance(v, dict) else v
        if valor is None:                       # el front declaró que no pudo medir
            no_medible(nombre, (detalle or {}).get("motivo", "sin datos"))
            continue
        ok(nombre, bool(valor), detalle)


def main() -> int:
    print("═" * 90)
    print("OBRA 6b · LOS CUATRO CHICOS")
    print("═" * 90)
    print("\n── #4a · backend ──")
    bloque_4a()
    print("\n── #4b y #5 · superficie ──")
    bloque_front()
    print("\n── #6 · átomos ──")
    bloque_6()
    print("\n── #7 · el dueño del veredicto ──")
    bloque_7()
    print()
    print("═" * 90)
    print("MEDIDO=" + json.dumps(RESULTADO, ensure_ascii=False))
    if FALLOS:
        print(f"\n❌ verify_obra6b: {len(FALLOS)} sin verde → {FALLOS}")
        return 1
    print("\n✅ verify_obra6b: TODO VERDE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
