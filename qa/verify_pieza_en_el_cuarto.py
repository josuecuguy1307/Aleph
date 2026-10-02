#!/usr/bin/env python3
"""verify_pieza_en_el_cuarto.py — LA VARA DE LA LEY DEL GATE. Una sola invocación.

    python3 qa/verify_pieza_en_el_cuarto.py

LA LEY: una pieza traída del catálogo público tiene que ser INDISTINGUIBLE de las que
vienen en la caja. Entra al catálogo local, queda conectada… y hasta acá llegaba. En El
Cuarto no aparecía, así que no se podía equipar a ningún agente: distinguible justo en lo
único que importa.

El arreglo #6 de la Obra 6b (`atoms_router._raices_de_belts` + el `synth_belts` del dir de
datos) NO alcanzó, y la medición dijo por qué: **arreglaba una capa que la ruta viva no
consulta**. El Cuarto no pinta desde `/v1/atoms/catalog`; pinta desde
`/v1/connector-entities` (`cuarto.catalog.js:511` — si esa proyección responde, los átomos
se ignoran por completo). Medido contra el binario INSTALADO, con los datos reales:

    GET /v1/atoms/catalog       → 200 · 239 átomos (184 traídos)   ← la 6b funciona
    GET /v1/connector-entities  → 500 · IndexError                 ← lo que El Cuarto mira

Dos defectos, los dos de superficie común (ninguno nombra una pieza):

  1 · UNA PIEZA MALA NO PUEDE TUMBAR EL CATÁLOGO. `build_entities` resolvía el proveedor de
      credencial con `sorted(providers)[0]` sobre un conjunto que puede estar vacío: una
      sola card que pide credencial sin declarar proveedor mataba la proyección ENTERA —
      las traídas y las de la caja. Si nadie declara proveedor, el proveedor es el servicio
      (que ya calculamos y es su nombre canónico). No se inventa nada: se usa lo que la
      pieza ya tiene.

  2 · EL BELT TRAÍDO TIENE QUE RESOLVER. `_server_cfg` anclaba el `belt_ref` sólo al repo,
      y un belt del usuario vive en `data_root()/synth_belts/…` (la forma portable que ya
      persiste `conexion.belt_ref`). Resultado: `{}` para TODA pieza traída → la entidad
      entraba sin `command`, sin `args` y sin origen, y declarando `stdio` cuando el
      usuario la trajo por HTTP. Misma clase de bug que la 6d: resolver contra la raíz
      equivocada. Las raíces las declara `atoms_router._raices_de_belts()` — una sola
      fuente de verdad para «dónde vive un belt», no dos listas que se desincronizan.

CADA PUNTO TRAE SU NEGATIVO, y los negativos no son mocks: son ESTA MISMA función con el
código de antes (el módulo re-ejecutado con la línea vieja) o con la entrada que la hacía
fallar. Un testigo que no puede rojear no mide.

Bloques:
  1 · la proyección sobrevive a una pieza sin proveedor declarado  (+2 negativos)
  2 · la pieza traída llega a El Cuarto como entidad equipable     (+1 negativo)
  3 · el belt traído resuelve y su origen viaja entero             (+2 negativos)
  4 · GUARD · el catálogo de la caja no se movió ni un veredicto
  5 · GUARD DE ALCANZABILIDAD · aparece y se equipa POR CLICKS     (qa/verify_pieza_en_el_cuarto_front.mjs)
"""
from __future__ import annotations

import json
import os
import shutil
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


# ── EL DATO DE ANTES ───────────────────────────────────────────────────────────────────
# Las dos líneas que el arreglo cambia, textuales. El negativo re-ejecuta el módulo con
# ellas puestas: si alguna deja de encontrarse, el negativo se declara NO MEDIBLE en vez
# de pasar en verde — un negativo que no corrió no probó nada.
_LINEA_NUEVA_PROVEEDOR = "provider = canonical_provider or _proveedor_por_defecto(providers, service)"
_LINEA_VIEJA_PROVEEDOR = "provider = canonical_provider or sorted(providers)[0]"
_MARCA_NUEVA_RUTA = "for _dir, raiz in _raices_de_belts(owner):"


def _modulo_de_antes():
    """`connector_entities` re-ejecutado con el código PREVIO al arreglo.

    No es un stub: es el archivo real con las dos líneas revertidas. Corre contra el mismo
    fixture y tiene que fallar donde fallaba."""
    src = (RAIZ / "product/backend/app/phase1/connector_entities.py").read_text(encoding="utf-8")
    if _LINEA_NUEVA_PROVEEDOR not in src:
        return None, "no encontré la línea nueva del proveedor (¿cambió el arreglo?)"
    src = src.replace(_LINEA_NUEVA_PROVEEDOR, _LINEA_VIEJA_PROVEEDOR)
    if _MARCA_NUEVA_RUTA not in src:
        return None, "no encontré la resolución nueva del belt_ref (¿cambió el arreglo?)"
    # revierte `_server_cfg` a su forma vieja: una sola raíz, la del repo.
    inicio = src.index("def _server_cfg(")
    fin = src.index("def _safe_prefix(")
    src = src[:inicio] + (
        "def _server_cfg(belt_ref: str, server: str, owner=None) -> dict:\n"
        "    try:\n"
        "        path = (_ROOT / belt_ref).resolve()\n"
        "        root = _ROOT.resolve()\n"
        "        if root != path and root not in path.parents:\n"
        "            return {}\n"
        "        obj = json.loads(path.read_text(encoding='utf-8'))\n"
        "        return dict((obj.get('mcpServers') or {}).get(server) or {})\n"
        "    except (OSError, json.JSONDecodeError):\n"
        "        return {}\n\n\n"
    ) + src[fin:]
    ns: dict = {"__name__": "connector_entities_de_antes"}
    exec(compile(src, "connector_entities_de_antes", "exec"), ns)  # noqa: S102
    return ns, None


# ── EL FIXTURE ─────────────────────────────────────────────────────────────────────────
#: El dueño de la pieza traída. Desde A1 (la fuga entre cuentas) NO es una etiqueta: es una
#: CUENTA DE VERDAD, creada en la base del fixture, con su sesión. El Cuarto sólo sirve las
#: piezas de quien mira, así que sin sesión esta vara mediría un catálogo vacío y creería
#: que la pieza no llegó.
USUARIO = "u-vara-0001"
URL_ORIGEN = "https://example.com/mcp"     # constante neutra (contrato del repo §1)


def _belt_traido(slug: str, *, cards: list[dict]) -> dict:
    """La forma EXACTA que forja `byo_mcp.py` para una pieza traída por HTTP: el server se
    lanza por el puente (stdio) y declara su origen real bajo `byo`."""
    return {
        "_meta": {"belt": slug, "slug": slug, "byo": True,
                  "que_es": f"MCP propio del usuario: {slug}",
                  "source": {"transport": "http", "ref": URL_ORIGEN},
                  "cards": cards},
        "mcpServers": {
            slug: {
                "command": "python3",
                "args": ["${PUPPET_REPO}/platform/inspection/byo_mcp_server.py",
                         f"/x/{slug}/manifest.json"],
                "description": f"MCP propio (HTTP): {slug}",
                "byo": {"transport": "http", "url": URL_ORIGEN},
            }
        },
    }


def _escribir_fixture(datos: Path) -> None:
    base = datos / "synth_belts" / USUARIO

    # (a) LA PIEZA BUENA — dos tools reales, keyless, como cualquiera de las de la caja.
    buena = _belt_traido("pieza-traida", cards=[
        {"id": "pieza-traida.get_cosa", "label": "get cosa", "backed_by": "pieza-traida",
         "auth": "keyless", "tools": ["get_cosa"]},
        {"id": "pieza-traida.buscar_cosa", "label": "buscar cosa", "backed_by": "pieza-traida",
         "auth": "keyless", "tools": ["buscar_cosa"]},
    ])
    d = base / "pieza-traida"
    d.mkdir(parents=True, exist_ok=True)
    (d / "belt-pieza-traida.mcp.json").write_text(json.dumps(buena), encoding="utf-8")

    # (b) LA PIEZA QUE MATABA EL CATÁLOGO — pide credencial y no declara proveedor. Es el
    #     dato REAL que dejó el forjado (`auth: "token-query (vault)"`, `connector: null`),
    #     no un caso inventado: 32 filas así viven hoy en el dir de datos de la app.
    mala = _belt_traido("pieza-sin-proveedor", cards=[
        {"id": "pieza-sin-proveedor.get_algo", "label": "get algo",
         "backed_by": "pieza-sin-proveedor", "auth": "token-query (vault)",
         "tools": ["get_algo"]},
    ])
    d = base / "pieza-sin-proveedor"
    d.mkdir(parents=True, exist_ok=True)
    (d / "belt-pieza-sin-proveedor.mcp.json").write_text(json.dumps(mala), encoding="utf-8")


def _atomos(datos: Path | None) -> list[dict]:
    """`collect_atoms` REAL sobre el dir de datos que se le diga. Sin dir → sólo la caja.

    ⚠️ `ALEPH_DATA_DIR` queda apuntando al fixture DURANTE TODA la corrida (lo fija
    `main`), no sólo durante este walk: `build_entities` vuelve a resolver el `belt_ref`
    más tarde, y si para entonces el dir de datos ya no está, la vara mide el arreglo con
    la raíz apagada y lo acusa de un fallo que es suyo."""
    from app.phase1 import atoms_router as AR
    anterior = os.environ.get("ALEPH_DATA_DIR")
    if datos is None:
        os.environ["ALEPH_DATA_DIR"] = str(Path(tempfile.mkdtemp(prefix="aleph-vacio-")))
    try:
        # ⚠️ EL DUEÑO SE DECLARA (A1). El fixture escribe bajo `synth_belts/<USUARIO>/`, y
        # desde que el walk filtra por cuenta, pedir el catálogo sin dueño no sirve ninguna
        # pieza traída — que es el arreglo, no un defecto.
        return AR.collect_atoms(set(), set(), owner=USUARIO)
    finally:
        if anterior is None:
            os.environ.pop("ALEPH_DATA_DIR", None)
        else:
            os.environ["ALEPH_DATA_DIR"] = anterior


def _entidad_de(data: dict, server: str) -> dict | None:
    for e in data.get("entities") or []:
        if server in {s["name"] for s in e.get("servers") or []}:
            return e
    return None


# ══ 1 · UNA PIEZA MALA NO TUMBA EL CATÁLOGO ═══════════════════════════════════════════
def bloque_1(datos: Path) -> dict:
    from app.phase1 import connector_entities as CE

    atomos = _atomos(datos)
    RESULTADO["_atomos_del_fixture"] = len(atomos)

    try:
        data = CE.build_entities(atomos, key_rows=[], owner=USUARIO)
        levanto = None
    except Exception as e:  # noqa: BLE001
        data, levanto = None, f"{type(e).__name__}: {e}"

    ok("1_la_proyeccion_sobrevive_a_la_pieza_sin_proveedor",
       data is not None, levanto or {"entidades": len(data["entities"])})
    if data is None:
        return {}

    # La pieza mala no se esconde: entra como su propio servicio, con su credencial
    # apuntando a sí misma. Fabricarle un proveedor ajeno sería peor que reventar.
    mala = _entidad_de(data, "pieza-sin-proveedor")
    ok("1_la_pieza_sin_proveedor_entra_y_apunta_a_si_misma",
       bool(mala) and (mala.get("credential") or {}).get("provider") == "pieza-sin-proveedor",
       {"credential": (mala or {}).get("credential")})

    # ── NEGATIVO 1 · el MISMO fixture contra el código de antes: tiene que morir.
    antes, motivo = _modulo_de_antes()
    if antes is None:
        no_medible("1_negativo_el_codigo_de_antes_muere", motivo)
    else:
        try:
            antes["build_entities"](atomos, key_rows=[], owner=USUARIO)
            murio = None
        except Exception as e:  # noqa: BLE001
            murio = f"{type(e).__name__}: {e}"
        ok("1_negativo_el_codigo_de_antes_muere",
           murio is not None and "IndexError" in murio, murio or "NO murió (el testigo 1 no mide)")

    # ── NEGATIVO 2 · y lo que se llevaba puesto no era la pieza mala: era TODO. Con el
    #    código de antes el catálogo de la caja tampoco llegaba a la pantalla.
    if antes is not None:
        try:
            viejo = antes["build_entities"](atomos, key_rows=[], owner=USUARIO)
            entidades_antes = len(viejo["entities"])
        except Exception:  # noqa: BLE001
            entidades_antes = 0
        ok("1_negativo_antes_se_perdia_el_catalogo_entero",
           entidades_antes == 0 and len(data["entities"]) > 1,
           {"antes": entidades_antes, "ahora": len(data["entities"])})
    return data


# ══ 2 · LA PIEZA TRAÍDA ES UNA ENTIDAD EQUIPABLE ══════════════════════════════════════
def bloque_2(data: dict, datos: Path) -> None:
    from app.phase1 import connector_entities as CE

    ent = _entidad_de(data, "pieza-traida")
    ok("2_la_pieza_traida_es_entidad",
       bool(ent) and ent.get("tool_count") == 2,
       {"id": (ent or {}).get("id"), "tools": (ent or {}).get("tool_count")})

    # El `belt_ref` que viaja tiene que ser el PORTABLE (relativo al dir de datos), el mismo
    # que ya persiste `conexion.belt_ref`. Una ruta absoluta de esta máquina funciona acá y
    # en ninguna otra — el contrato del repo lo prohíbe por escrito.
    refs = (ent or {}).get("belt_refs") or []
    ok("2_el_belt_ref_es_portable",
       len(refs) == 1 and refs[0].startswith(f"synth_belts/{USUARIO}/")
       and not Path(refs[0]).is_absolute(),
       {"belt_refs": refs})

    # ── NEGATIVO · sin el belt en el dir de datos, la entidad NO existe. Calibra que el
    #    testigo de arriba puede rojear (si no, estaría mirando la nada y saliendo verde).
    sin = CE.build_entities(_atomos(None), key_rows=[], owner=USUARIO)
    ok("2_negativo_sin_el_belt_no_hay_entidad",
       _entidad_de(sin, "pieza-traida") is None,
       {"entidades_sin_datos": len(sin["entities"])})


# ══ 3 · EL BELT TRAÍDO RESUELVE Y SU ORIGEN VIAJA ═════════════════════════════════════
def bloque_3(data: dict, datos: Path) -> None:
    from app.phase1 import connector_entities as CE

    ent = _entidad_de(data, "pieza-traida")
    srv = ((ent or {}).get("servers") or [None])[0]
    origen = (srv or {}).get("origin") or {}

    ok("3_el_origen_viaja_entero",
       origen.get("command") == "python3" and len(origen.get("args") or []) == 2,
       {"command": origen.get("command"), "args": origen.get("args")})

    # La pieza la trajo el usuario por HTTP. El `command` es NUESTRO puente, no su
    # naturaleza: decirle "stdio" al usuario es contarle nuestra implementación como si
    # fuera su decisión. El transporte lo declara el belt; se lo lee donde lo escribe.
    ok("3_el_transporte_es_el_que_el_usuario_trajo",
       (srv or {}).get("transport") == "http" and origen.get("url") == URL_ORIGEN,
       {"transport": (srv or {}).get("transport"), "url": origen.get("url")})

    # ── NEGATIVO 1 · con el resolutor de antes (una sola raíz, la del repo) el cfg salía
    #    vacío para TODA pieza traída.
    ref = (ent or {}).get("belt_refs", [""])[0]
    antes, motivo = _modulo_de_antes()
    if antes is None:
        no_medible("3_negativo_antes_el_cfg_salia_vacio", motivo)
    else:
        ok("3_negativo_antes_el_cfg_salia_vacio",
           antes["_server_cfg"](ref, "pieza-traida", USUARIO) == {}
           and CE._server_cfg(ref, "pieza-traida", USUARIO) != {},
           {"antes": antes["_server_cfg"](ref, "pieza-traida", USUARIO),
            "ahora_claves": sorted(CE._server_cfg(ref, "pieza-traida", USUARIO).keys())})

    # ── NEGATIVO 2 · la puerta sigue cerrada: un `belt_ref` que se escapa de las raíces
    #    conocidas NO resuelve. Abrir la resolución no puede abrir el disco entero.
    ok("3_negativo_un_ref_fugado_no_resuelve",
       CE._server_cfg("../../../etc/passwd", "x", USUARIO) == {}
       and CE._server_cfg("/etc/passwd", "x", USUARIO) == {},
       {"traversal": CE._server_cfg("../../../etc/passwd", "x", USUARIO),
        "absoluto": CE._server_cfg("/etc/passwd", "x", USUARIO)})


# ══ 4 · GUARD · EL CATÁLOGO DE LA CAJA NO SE MOVIÓ ════════════════════════════════════
def bloque_4() -> None:
    """Las piezas que vienen en la caja tienen que salir IDÉNTICAS. El arreglo abre una
    raíz nueva y toca la proyección: si de paso movió un veredicto de las de siempre, es
    una regresión, no un arreglo."""
    from app.phase1 import connector_entities as CE

    caja = _atomos(None)
    data = CE.build_entities(caja, key_rows=[], owner=USUARIO)
    antes, motivo = _modulo_de_antes()
    if antes is None:
        no_medible("4_guard_la_caja_no_se_movio", motivo)
        return
    try:
        viejo = antes["build_entities"](caja, key_rows=[], owner=USUARIO)
    except Exception as e:  # noqa: BLE001
        no_medible("4_guard_la_caja_no_se_movio", f"el código de antes murió con la caja sola: {e}")
        return

    def huella(d: dict) -> dict:
        return {e["id"]: (e["tool_count"], sorted(s["name"] for s in e["servers"]),
                          (e.get("credential") or {}).get("provider"))
                for e in d["entities"]}

    a, b = huella(viejo), huella(data)
    difs = {k: (a.get(k), b.get(k)) for k in set(a) | set(b) if a.get(k) != b.get(k)}
    ok("4_guard_la_caja_no_se_movio", not difs and len(b) > 0,
       {"entidades": len(b), "diferencias": difs})


# ══ 5 · GUARD DE ALCANZABILIDAD · APARECE Y SE EQUIPA POR CLICKS ══════════════════════
def bloque_5(datos: Path) -> None:
    """Que la proyección devuelva la entidad no es que el usuario pueda usarla. Este bloque
    abre El Cuarto de verdad contra un backend que sirve ESTA proyección, busca la pieza
    traída en el catálogo de piezas y la EQUIPA con clicks."""
    front = RAIZ / "qa" / "verify_pieza_en_el_cuarto_front.mjs"
    if not front.exists():
        no_medible("5_guard_alcanzable_por_clicks", "falta qa/verify_pieza_en_el_cuarto_front.mjs")
        return
    if not (RAIZ / "node_modules" / "playwright").exists():
        no_medible("5_guard_alcanzable_por_clicks",
                   "playwright no está instalado en este árbol (node_modules)")
        return
    try:
        p = subprocess.run(["node", str(front)], cwd=str(RAIZ), env=dict(os.environ, ALEPH_DATA_DIR=str(datos)),
                           # 600s, no 300: un sidecar CONGELADO extrae ~200 MB de `_MEI`
                           # antes de atender, y encima levanta el navegador. Con la fuente
                           # sobraba; contra la app instalada, el techo viejo cortaba una
                           # medición que estaba avanzando bien.
                           capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        no_medible("5_guard_alcanzable_por_clicks", "la superficie no respondió en 600s")
        return
    for l in (p.stderr or "").splitlines():
        if l.startswith("[diag]") or l.startswith("[vara]"):
            print("   " + l)
    linea = next((l for l in reversed(p.stdout.splitlines()) if l.startswith("{")), None)
    if linea is None:
        no_medible("5_guard_alcanzable_por_clicks",
                   f"el front no emitió veredicto (rc={p.returncode}): "
                   f"{(p.stderr or p.stdout).strip().splitlines()[-1:] or ['(sin salida)']}")
        return
    for nombre, v in json.loads(linea).items():
        ok(nombre, bool(v.get("ok")), {k: x for k, x in v.items() if k != "ok"})


def main() -> int:
    global USUARIO
    tmp = Path(tempfile.mkdtemp(prefix="aleph-vara-cuarto-"))
    datos = tmp / "datos"
    datos.mkdir(parents=True)
    # El dir de datos del fixture rige TODA la corrida (ver `_atomos`). Jamás el real: esta
    # vara CREA una cuenta, y crearla en la base de alguien sería medir sobre su estado.
    os.environ.update({
        "ALEPH_ROLE": "client",
        "ALEPH_DATA_DIR": str(datos),
        "PUPPET_SQLITE_PATH": str(datos / "aleph.db"),
        "PUPPET_WORKERS": "0",
    })
    try:
        from app.infra import db_boot
        db_boot.asegurar()
        from app.phase1 import repo
        conn = repo.get_conn()
        try:
            duena = repo.register_user(conn, email="vara-cuarto@local.test",
                                       password="vara-2026", display_name="Vara")
        finally:
            conn.close()
        USUARIO = duena["id"]
        os.environ["ALEPH_VARA_TOKEN"] = repo.mint_session(USUARIO)
        _escribir_fixture(datos)
        print("═" * 90)
        print("VARA · LA PIEZA TRAÍDA EN EL CUARTO")
        print(f"  fixture: {datos}")
        print(f"  dueña  : {USUARIO}")
        print("═" * 90)
        data = bloque_1(datos)
        if data:
            bloque_2(data, datos)
            bloque_3(data, datos)
        bloque_4()
        bloque_5(datos)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("─" * 90)
    verdes = sum(1 for v in RESULTADO.values() if v is True)
    total = sum(1 for v in RESULTADO.values() if isinstance(v, bool) or v == "NO_MEDIBLE")
    print(f"{verdes}/{total} verdes" + (f" · FALLOS: {FALLOS}" if FALLOS else " · SIN FALLOS"))
    print(json.dumps(RESULTADO, ensure_ascii=False))
    return 1 if FALLOS else 0


if __name__ == "__main__":
    raise SystemExit(main())
