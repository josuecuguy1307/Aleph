#!/usr/bin/env python3
"""verify_un_dueno_por_catalogo.py — LA VARA DE LA FUGA ENTRE CUENTAS. Una sola invocación.

    python3 qa/verify_un_dueno_por_catalogo.py

──────────────────────────────────────────────────────────────────────────────────────────
QUÉ MIDE

**Aleph tiene multicuenta LOCAL**: cuentas distintas en la misma instalación. Y
`atoms_router._raices_de_belts()` camina `data_root()/synth_belts` **entero**, sin filtrar
por dueño. O sea El Cuarto muestra los átomos de TODAS las cuentas juntas.

Medido el 2026-08-07 sobre los datos reales de la máquina: **64 de 184 átomos traídos** no
eran de la cuenta de la sesión. Eso no es ruido de pruebas — es exposición entre cuentas.

LA VARA (dictada por persona usuaria):

    la cuenta A trae una pieza  →  la cuenta B NO la ve, ni en El Cuarto ni en su catálogo
    local. Sin el arreglo, rojea. Y la misma pieza SIGUE viéndose para su dueño.

Ese último medio renglón es el que impide el arreglo perezoso: esconderle la pieza a todo
el mundo también haría desaparecer la fuga, y sería un producto roto.

──────────────────────────────────────────────────────────────────────────────────────────
PREDICCIÓN SELLADA, antes de tocar una línea de código:

  · hoy `collect_atoms()` devuelve los átomos de A **y** los de B, pregunte quien pregunte
  · hoy `/v1/connector-entities` con la sesión de B trae la pieza de A como entidad
  · hoy El Cuarto de B pinta la pieza de A en su catálogo
  · después: A ve la suya, B no ve la de A, y el catálogo de la caja no se mueve para nadie

Bloques:
  1 · el walk respeta al dueño                       (+ negativo: el código de antes no)
  2 · sin dueño no se sirve el `synth_belts` de nadie (fail-closed)
  3 · HTTP · `/v1/connector-entities` por sesión      (A la ve · B no)
  4 · EL CUARTO · el catálogo de B no tiene la pieza de A, y el de A sí
  5 · GUARD · el catálogo de la caja no se movió para ninguno de los dos
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


# ── EL WALK DE ANTES ───────────────────────────────────────────────────────────────────
# El negativo no es un mock: es `_raices_de_belts` con su cuerpo VIEJO —la raíz entera, sin
# dueño— sobre el MISMO fixture. Tiene que ver las dos piezas, que es el defecto.
def _raices_de_antes():
    import aleph_paths as _ap
    from app.phase1 import atoms_router as AR

    def viejo(*_a, **_k):
        raices = [(d, AR._REPO) for d in AR._BELT_DIRS]
        try:
            datos = _ap.data_root()
            raices.append((datos / "synth_belts", datos))
        except Exception:  # noqa: BLE001
            pass
        return raices
    return viejo


URL_ORIGEN = "https://example.com/mcp"     # constante neutra (contrato del repo §1)


def _belt(slug: str, tool: str) -> dict:
    """La forma EXACTA que forja `byo_mcp.py` para una pieza traída por HTTP."""
    return {
        "_meta": {"belt": slug, "slug": slug, "byo": True,
                  "que_es": f"MCP propio del usuario: {slug}",
                  "source": {"transport": "http", "ref": URL_ORIGEN},
                  "cards": [{"id": f"{slug}.{tool}", "label": tool.replace("_", " "),
                             "backed_by": slug, "auth": "keyless", "tools": [tool]}]},
        "mcpServers": {slug: {
            "command": "python3",
            "args": ["${PUPPET_REPO}/platform/inspection/byo_mcp_server.py",
                     f"/x/{slug}/manifest.json"],
            "description": f"MCP propio (HTTP): {slug}",
            "byo": {"transport": "http", "url": URL_ORIGEN},
        }},
    }


def _escribir(datos: Path, dueno: str, slug: str, tool: str) -> None:
    d = datos / "synth_belts" / dueno / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / f"belt-{slug}.mcp.json").write_text(json.dumps(_belt(slug, tool)), encoding="utf-8")


def _servers(atoms) -> set:
    return {a["server"] for a in atoms}


# ══ 1 · EL WALK RESPETA AL DUEÑO ══════════════════════════════════════════════════════
def bloque_1(datos: Path, ua: str, ub: str) -> None:
    from app.phase1 import atoms_router as AR

    de_a = _servers(AR.collect_atoms(set(), set(), owner=ua))
    de_b = _servers(AR.collect_atoms(set(), set(), owner=ub))

    ok("1_el_dueno_ve_la_suya", "pieza-de-a" in de_a and "pieza-de-b" in de_b,
       {"A_ve": sorted(x for x in de_a if x.startswith("pieza-")),
        "B_ve": sorted(x for x in de_b if x.startswith("pieza-"))})

    # ⚠️ EL TESTIGO QUE DECIDE LA OBRA.
    ok("1_la_otra_cuenta_no_la_ve",
       "pieza-de-a" not in de_b and "pieza-de-b" not in de_a,
       {"B_ve_la_de_A": "pieza-de-a" in de_b, "A_ve_la_de_B": "pieza-de-b" in de_a})

    # ── NEGATIVO · el walk de ANTES, sobre el MISMO fixture: ve las dos.
    viejo = _raices_de_antes()
    original = AR._raices_de_belts
    try:
        AR._raices_de_belts = viejo
        antes_a = _servers(AR.collect_atoms(set(), set(), owner=ua))
    finally:
        AR._raices_de_belts = original
    ok("1_negativo_el_walk_de_antes_veia_las_dos",
       "pieza-de-a" in antes_a and "pieza-de-b" in antes_a,
       {"antes_A_veia": sorted(x for x in antes_a if x.startswith("pieza-"))})


# ══ 2 · SIN DUEÑO NO SE SIRVE EL `synth_belts` DE NADIE ═══════════════════════════════
def bloque_2(datos: Path) -> None:
    """FAIL-CLOSED. Sin sesión no se sabe de quién es la pantalla, y una pieza traída es de
    alguien: servirlas «por las dudas» es exactamente la fuga, con otro nombre."""
    from app.phase1 import atoms_router as AR

    sin_dueno = AR.collect_atoms(set(), set())
    traidos = [a for a in sin_dueno if str(a.get("belt_ref", "")).startswith("synth_belts/")]
    ok("2_sin_dueno_no_hay_piezas_traidas", not traidos,
       {"traidos": sorted(_servers(traidos))})
    # …pero el catálogo de la caja SÍ se sirve: el público no depende de tener cuenta.
    ok("2_pero_la_caja_sigue_entera", len(sin_dueno) > 0, {"atomos_de_la_caja": len(sin_dueno)})


# ══ 3 · HTTP · POR SESIÓN ═════════════════════════════════════════════════════════════
def bloque_3(datos: Path, tok_a: str, tok_b: str, puerto: int) -> None:
    import urllib.error
    import urllib.request

    def entidades(token):
        req = urllib.request.Request(f"http://127.0.0.1:{puerto}/v1/connector-entities",
                                     headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
        return {e["id"] for e in data.get("entities") or []}

    try:
        ent_a, ent_b = entidades(tok_a), entidades(tok_b)
    except (urllib.error.URLError, OSError) as e:
        no_medible("3_http_por_sesion", f"el backend no atendió: {e}")
        return

    ok("3_http_el_dueno_la_ve", "pieza-de-a" in ent_a, {"A": sorted(x for x in ent_a if x.startswith("pieza-"))})
    ok("3_http_la_otra_cuenta_no", "pieza-de-a" not in ent_b,
       {"B": sorted(x for x in ent_b if x.startswith("pieza-"))})
    ok("3_http_y_B_sigue_viendo_la_suya", "pieza-de-b" in ent_b)
    # GUARD · la caja llega igual a los dos. Si una cuenta viera menos piezas públicas que
    # otra, el filtro se habría llevado puesto el catálogo común.
    caja_a = {e for e in ent_a if not e.startswith("pieza-")}
    caja_b = {e for e in ent_b if not e.startswith("pieza-")}
    ok("3_http_la_caja_es_la_misma_para_los_dos", caja_a == caja_b,
       {"solo_A": sorted(caja_a - caja_b), "solo_B": sorted(caja_b - caja_a)})


# ══ 4 y 5 · EL CUARTO ═════════════════════════════════════════════════════════════════
def bloque_4(datos: Path, tok_a: str, tok_b: str, puerto: int) -> None:
    front = RAIZ / "qa" / "verify_un_dueno_por_catalogo_front.mjs"
    if not front.exists():
        no_medible("4_el_cuarto_por_sesion", "falta qa/verify_un_dueno_por_catalogo_front.mjs")
        return
    if not (RAIZ / "node_modules" / "playwright").exists():
        no_medible("4_el_cuarto_por_sesion", "playwright no está instalado en este árbol")
        return
    try:
        p = subprocess.run(
            ["node", str(front)], cwd=str(RAIZ), capture_output=True, text=True, timeout=300,
            env=dict(os.environ, ALEPH_VARA_URL=f"http://127.0.0.1:{puerto}",
                     ALEPH_VARA_TOKEN_A=tok_a, ALEPH_VARA_TOKEN_B=tok_b))
    except subprocess.TimeoutExpired:
        no_medible("4_el_cuarto_por_sesion", "la superficie no respondió en 300s")
        return
    linea = next((l for l in reversed(p.stdout.splitlines()) if l.startswith("{")), None)
    if linea is None:
        no_medible("4_el_cuarto_por_sesion",
                   f"el front no emitió veredicto (rc={p.returncode}): "
                   f"{(p.stderr or p.stdout).strip()[-220:]}")
        return
    for nombre, v in json.loads(linea).items():
        ok(nombre, bool(v.get("ok")), {k: x for k, x in v.items() if k != "ok"})


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="aleph-un-dueno-"))
    datos = tmp / "datos"
    datos.mkdir(parents=True)
    # El fixture rige TODA la corrida. Jamás el dir real: esta vara CREA cuentas, y crearlas
    # en la base de alguien sería exactamente lo que el repo ya pagó una vez.
    # Mismo entorno que el resto de las varas de conexiones: cliente, base propia, sin
    # workers. `PUPPET_SQLITE_PATH` es explícito para que el proceso de la vara y el sidecar
    # que se levanta después apunten al MISMO archivo — si difirieran, las cuentas que crea
    # una no existirían para el otro y el testigo mediría dos mundos distintos.
    os.environ.update({
        "ALEPH_ROLE": "client",
        "ALEPH_DATA_DIR": str(datos),
        "PUPPET_SQLITE_PATH": str(datos / "aleph.db"),
        "PUPPET_WORKERS": "0",
    })
    servidor = None
    try:
        # LA MISMA PUERTA QUE USA LA APP AL ARRANCAR. Una base nueva no trae schema, y
        # crearlo a mano acá sería una segunda definición del esquema viviendo en una vara.
        from app.infra import db_boot
        db_boot.asegurar()
        from app.phase1 import repo
        conn = repo.get_conn()
        try:
            a = repo.register_user(conn, email="cuenta-a@local.test", password="vara-2026",
                                   display_name="Cuenta A")
            b = repo.register_user(conn, email="cuenta-b@local.test", password="vara-2026",
                                   display_name="Cuenta B")
        finally:
            conn.close()
        tok_a, tok_b = repo.mint_session(a["id"]), repo.mint_session(b["id"])
        _escribir(datos, a["id"], "pieza-de-a", "buscar_a")
        _escribir(datos, b["id"], "pieza-de-b", "buscar_b")

        print("═" * 90)
        print("VARA · UN DUEÑO POR CATÁLOGO")
        print(f"  fixture: {datos}")
        print(f"  cuenta A: {a['id']}   ·   cuenta B: {b['id']}")
        print("═" * 90)

        bloque_1(datos, a["id"], b["id"])
        bloque_2(datos)

        # UN PUERTO LIBRE, PEDIDO AL SISTEMA (ver la nota en verify_pieza_en_el_cuarto_front):
        # con un número fijo, un sidecar sobreviviente de otra corrida contesta el `/health`
        # y la vara mide un proceso cuyo fixture ya no existe — verde por hablarle al muerto.
        import socket as _socket
        with _socket.socket() as _s:
            _s.bind(("127.0.0.1", 0))
            puerto = int(os.environ.get("ALEPH_VARA_PORT_DUENO") or _s.getsockname()[1])
        # ⚠️ LA MISMA VARA CERTIFICA FUENTE O BINARIO. Con `ALEPH_VARA_SIDECAR` apuntando a un
        # sidecar CONGELADO, la fuga se mide sobre el artefacto que se va a instalar y no
        # sobre el árbol — que es la única forma de saber que el arreglo VIAJÓ. Sin la
        # variable corre el `sidecar_serve.py` del repo, como siempre.
        congelado = (os.environ.get("ALEPH_VARA_SIDECAR") or "").strip()
        arranque = ([congelado, "--port", str(puerto)] if congelado else
                    [str(RAIZ / "product/backend/.venv/bin/python"),
                     str(RAIZ / "deploy/fase4/sidecar_serve.py"), "--port", str(puerto)])
        print(f"  backend : {'CONGELADO ' + congelado if congelado else 'fuente (sidecar_serve.py)'}")
        servidor = subprocess.Popen(
            arranque,
            # Grupo propio: un binario PyInstaller *onefile* lanza un HIJO, y matar sólo el
            # padre deja al hijo atendiendo el puerto. Ese huérfano le contesta el `/health`
            # a la corrida siguiente, que mide un servidor cuyo fixture ya no existe.
            start_new_session=True,
            cwd=str(RAIZ), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=dict(os.environ, ALEPH_DATA_DIR=str(datos),
                     PYTHONPATH=os.pathsep.join([str(RAIZ / "product/backend"),
                                                 str(RAIZ / "platform")])))
        import time
        import urllib.request
        for _ in range(90):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/health", timeout=2):
                    break
            except Exception:  # noqa: BLE001
                time.sleep(1)
        bloque_3(datos, tok_a, tok_b, puerto)
        bloque_4(datos, tok_a, tok_b, puerto)
    finally:
        if servidor is not None:
            try:
                os.killpg(os.getpgid(servidor.pid), 9)   # el GRUPO, no el pid
            except (ProcessLookupError, PermissionError):
                pass
            servidor.kill()
        shutil.rmtree(tmp, ignore_errors=True)

    print("─" * 90)
    verdes = sum(1 for v in RESULTADO.values() if v is True)
    print(f"{verdes}/{len(RESULTADO)} verdes" + (f" · FALLOS: {FALLOS}" if FALLOS else " · SIN FALLOS"))
    print(json.dumps(RESULTADO, ensure_ascii=False))
    return 1 if FALLOS else 0


if __name__ == "__main__":
    raise SystemExit(main())
