#!/usr/bin/env python3
"""verify_preferencias_con_dueno.py — LA VARA DE LOS AJUSTES DE LA CASA.
[Convergencia · superficie 3 · fase 2]

    <venv>/bin/python qa/verify_preferencias_con_dueno.py

──────────────────────────────────────────────────────────────────────────────────────────
QUÉ MIDE, Y POR QUÉ CADA COSA

No mide «el endpoint responde 200». Un 200 no prueba que el estado cambió, y un no-200 no
prueba que no cambió: **cada aserción vuelve a LEER el almacén** después de escribir.

  1 · SIN DUEÑO NO HAY AJUSTES        GET y PUT sin sesión → 401 tipado, con copy.
  2 · UN DUEÑO NO VE AL OTRO          A guarda, B lee y ve su default. Es la fuga entre
                                      cuentas de Gate 2.5 pagada por adelantado: esta casa
                                      es multicuenta LOCAL, dos personas en la misma Mac.
  3 · VOCABULARIO CERRADO             un ajuste que no existe → 400 `ajuste_desconocido`,
                                      Y NO QUEDA GUARDADO. Sin la segunda mitad, un
                                      almacén puede rechazar y persistir igual.
  4 · VALOR CERRADO                   un valor fuera de la lista → 400 `valor_invalido`,
                                      y el valor viejo sigue en pie.
  5 · MERGE, NO REEMPLAZO             guardar uno NO borra el otro. Es el contrato que
                                      `recordar` ya tenía y que se hereda.
  6 · PRECEDENCIA espacio > casa      el espacio pisa a la casa; sacar el del espacio
                                      DEVUELVE el de la casa (no el default).
  7 · `None` VUELVE AL DEFAULT        borrar es explícito; omitir no toca nada.
  8 · EL DISCO                        archivo 0600 y `schema_version` ADENTRO del dato.
  9 · CONVIVE CON LA MEMORIA          escribir ajustes no le pisa la memoria de workspaces
                                      a nadie: comparten archivo, y ese es el riesgo.

CÓMO SE PROBÓ CAYENDO — cinco mutaciones, una por familia de defecto:

    · el vocabulario se abre (acepta cualquier clave)     → cae 3
    · la precedencia se invierte (casa pisa espacio)      → cae 6
    · `ajustar` reemplaza en vez de mergear               → cae 5
    · el 401 se afloja (sin dueño devuelve defaults)      → cae 1
    · el dueño se ignora (un solo archivo global)         → cae 2

Correr con `--probar-cayendo` aplica las cinco EN MEMORIA (sobre una copia del módulo, sin
tocar el árbol) y verifica que cada una rojea la aserción que le toca. Sin eso, esta vara
sería una que no puede dar rojo.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "platform"))

FALLOS: list[str] = []
OK: list[str] = []


def chequear(nombre: str, cond: bool, detalle: str = "") -> None:
    (OK if cond else FALLOS).append(f"{nombre}{(' — ' + detalle) if detalle and not cond else ''}")


def _aislar() -> Path:
    """Un `user_data_dir` propio. La vara NO escribe en el almacén real —la casa ya se
    quemó una vez con una suite que escribía en la aleph.db de producción."""
    d = Path(tempfile.mkdtemp(prefix="vara-pref-"))
    os.environ["ALEPH_DATA_DIR"] = str(d)
    import aleph_paths
    if hasattr(aleph_paths, "_CACHE"):
        try: aleph_paths._CACHE.clear()
        except Exception: pass
    return d


def medir_almacen(memoria) -> None:
    A, B = "usuario-a", "usuario-b"
    defaults = {k: v["default"] for k, v in memoria.AJUSTES.items()}

    # 1 · sin dueño no se ESCRIBE. Leer sin dueño devuelve defaults a propósito (una
    # pantalla sin sesión no tiene ajustes y eso no es un error que mostrar); escribir
    # sin dueño es otra cosa —no hay a nombre de quién— y tiene que levantar.
    try:
        memoria.ajustar(None, None, {"tamano_texto": "grande"})
        chequear("1 · escribir sin dueño levanta", False, "no levantó: guardó a nombre de nadie")
    except memoria.MemoriaError as e:
        chequear("1 · escribir sin dueño levanta", e.causa == "sin_dueno", e.causa)
    chequear("1 · leer sin dueño da los defaults",
             memoria.ajustes(None) == defaults, str(memoria.ajustes(None)))

    # 2 · un dueño no ve al otro
    memoria.ajustar(A, None, {"tamano_texto": "grande"})
    chequear("2 · A guarda y lo relee",
             memoria.ajustes(A)["tamano_texto"] == "grande")
    chequear("2 · B NO ve lo de A",
             memoria.ajustes(B)["tamano_texto"] == defaults["tamano_texto"],
             f"B vio {memoria.ajustes(B)['tamano_texto']}")

    # 3 · vocabulario cerrado, Y no persiste
    antes = memoria.ajustes(A)
    try:
        memoria.ajustar(A, None, {"tamanio_texto": "grande"})
        chequear("3 · ajuste desconocido levanta", False, "no levantó")
    except memoria.MemoriaError as e:
        chequear("3 · ajuste desconocido levanta", e.causa == "ajuste_desconocido", e.causa)
    crudo = json.loads((memoria._ruta(A)).read_text("utf-8"))
    guardado = (crudo.get("ajustes") or {}).get(memoria.CASA) or {}
    chequear("3 · y NO quedó guardado", "tamanio_texto" not in guardado, str(guardado))
    chequear("3 · y no tocó lo que había", memoria.ajustes(A) == antes)

    # 4 · valor cerrado
    try:
        memoria.ajustar(A, None, {"tamano_texto": "gigante"})
        chequear("4 · valor inválido levanta", False, "no levantó")
    except memoria.MemoriaError as e:
        chequear("4 · valor inválido levanta", e.causa == "valor_invalido", e.causa)
    chequear("4 · el valor viejo sigue en pie",
             memoria.ajustes(A)["tamano_texto"] == "grande")

    # 5 · merge, no reemplazo
    memoria.ajustar(A, None, {"tema_codigo": "dark"})
    got = memoria.ajustes(A)
    chequear("5 · merge: el nuevo entró", got["tema_codigo"] == "dark")
    chequear("5 · merge: el viejo sobrevivió", got["tamano_texto"] == "grande",
             f"quedó {got['tamano_texto']}")

    # 6 · precedencia espacio > casa
    memoria.ajustar(A, "ciencia", {"tamano_texto": "compacto"})
    chequear("6 · el espacio pisa a la casa",
             memoria.ajustes(A, "ciencia")["tamano_texto"] == "compacto",
             memoria.ajustes(A, "ciencia")["tamano_texto"])
    chequear("6 · y la casa no se movió",
             memoria.ajustes(A)["tamano_texto"] == "grande")
    chequear("6 · el espacio hereda lo que no pisó",
             memoria.ajustes(A, "ciencia")["tema_codigo"] == "dark")

    # 7 · None vuelve al valor de abajo, no al default
    memoria.ajustar(A, "ciencia", {"tamano_texto": None})
    chequear("7 · sacar el del espacio devuelve el de la casa",
             memoria.ajustes(A, "ciencia")["tamano_texto"] == "grande",
             memoria.ajustes(A, "ciencia")["tamano_texto"])
    memoria.ajustar(A, None, {"tamano_texto": None})
    chequear("7 · sacar el de la casa devuelve el default",
             memoria.ajustes(A)["tamano_texto"] == defaults["tamano_texto"])

    # 8 · el disco
    p = memoria._ruta(A)
    chequear("8 · el archivo es 0600", (p.stat().st_mode & 0o777) == 0o600,
             oct(p.stat().st_mode & 0o777))
    chequear("8 · schema_version viaja adentro",
             int(json.loads(p.read_text('utf-8')).get("schema_version") or 0) == memoria.SCHEMA_VERSION)

    # 9 · convive con la memoria de workspaces (comparten archivo)
    memoria.recordar(A, "ciencia", chat_id="chat-42")
    chequear("9 · el ajuste sobrevive a un recordar()",
             memoria.ajustes(A)["tema_codigo"] == "dark")
    memoria.ajustar(A, None, {"idioma_salida": "en"})
    chequear("9 · la memoria sobrevive a un ajustar()",
             memoria.como_quedo(A, "ciencia").get("chat_id") == "chat-42",
             str(memoria.como_quedo(A, "ciencia")))


def medir_modelos() -> None:
    """[fase 1] `preferencias-v2.json` era UNO para toda la instalación. Hallazgo A.3, en
    rojo: dos cuentas en la misma Mac compartían elección de cerebro."""
    sys.path.insert(0, str(RAIZ / "product" / "backend"))
    try:
        from app.phase1 import centro_modelos as cm
    except Exception as e:                                   # noqa: BLE001
        chequear("10 · centro_modelos se pudo importar", False, f"{type(e).__name__}: {e}")
        return
    base = cm.modelos_dir()
    base.mkdir(parents=True, exist_ok=True)

    # 10 · ADOPCIÓN: el archivo viejo se copia una vez, y NO se borra
    legado = base / cm._PREF_LEGADO
    legado.write_text(json.dumps({"version": 2, "default": "api.groq", "modelos": {},
                                  "contextos": {}, "conectados": []}), "utf-8")
    ruta_a = cm._preferencias_path("cuenta-a")
    chequear("10 · el primer dueño adopta lo heredado",
             json.loads(ruta_a.read_text("utf-8")).get("default") == "api.groq")
    chequear("10 · y el archivo viejo NO se borra", legado.is_file())

    # 11 · DOS DUEÑOS, DOS ARCHIVOS
    ruta_b = cm._preferencias_path("cuenta-b")
    chequear("11 · cada dueño tiene su archivo", ruta_a != ruta_b, f"{ruta_a} == {ruta_b}")
    cm._guardar_json(ruta_a, {"version": 2, "default": "api.openai", "modelos": {},
                              "contextos": {}, "conectados": []})
    chequear("11 · escribir en A no toca a B",
             json.loads(ruta_b.read_text("utf-8")).get("default") == "api.groq",
             json.loads(ruta_b.read_text("utf-8")).get("default"))
    chequear("11 · y A quedó con lo suyo",
             json.loads(ruta_a.read_text("utf-8")).get("default") == "api.openai")

    # 12 · EL ID NO ARMA RUTAS. Un dueño con `/` o `..` escribiría fuera del directorio.
    for veneno in ("../../fuera", "a/b", "..", "x" * 200, ""):
        r = cm._preferencias_path(veneno)
        chequear(f"12 · `{veneno[:14]}` no escapa del directorio",
                 r == base / cm._PREF_LEGADO,
                 f"resolvió a {r}")

    # 13 · el lector del modelo elegido respeta al dueño
    cm._guardar_json(cm._preferencias_path("cuenta-a"),
                     {"version": 2, "default": "api.groq", "contextos": {}, "conectados": [],
                      "modelos": {"api.groq": "llama-3.3-70b"}})
    chequear("13 · A lee su modelo",
             cm.modelo_elegido_de("api.groq", owner="cuenta-a") == "llama-3.3-70b",
             str(cm.modelo_elegido_de("api.groq", owner="cuenta-a")))
    chequear("13 · B NO lee el de A",
             cm.modelo_elegido_de("api.groq", owner="cuenta-b") is None,
             str(cm.modelo_elegido_de("api.groq", owner="cuenta-b")))


def medir_borde() -> None:
    """El borde HTTP real, con el router montado. Sin sesión no hay ajustes."""
    sys.path.insert(0, str(RAIZ / "product" / "backend"))
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.phase1.preferencias_router import build_preferencias_router
    except Exception as e:                                   # noqa: BLE001
        chequear("1 · el borde se pudo montar", False, f"{type(e).__name__}: {e}")
        return
    app = FastAPI()
    app.include_router(build_preferencias_router())
    c = TestClient(app, raise_server_exceptions=False)

    r = c.get("/v1/preferencias")
    chequear("1 · GET sin sesión → 401", r.status_code == 401, f"dio {r.status_code}")
    cuerpo = (r.json() or {}).get("detail") or {}
    chequear("1 · el 401 dice su causa", cuerpo.get("error") == "no_session", str(cuerpo)[:80])
    chequear("1 · y trae copy", bool(cuerpo.get("copy")), str(cuerpo)[:80])

    r = c.put("/v1/preferencias", json={"cambios": {"tamano_texto": "grande"}})
    chequear("1 · PUT sin sesión → 401", r.status_code == 401, f"dio {r.status_code}")


# ── LA PRUEBA DE QUE LA VARA PUEDE DAR ROJO ─────────────────────────────────────────
# Cada mutación es una sola sustitución de texto sobre una COPIA del módulo en un temp.
# El árbol no se toca. `cae` nombra la aserción que tiene que rojear: si una mutación deja
# todo verde, la vara no está midiendo esa familia y hay que arreglarla a ELLA.
MUTACIONES = [
    ("el vocabulario se abre",     "if k not in AJUSTES:", "if False:",                    "3 ·"),
    ("la precedencia se invierte", "for capa in (CASA, amb) if amb != CASA else (CASA,):",
                                   "for capa in (amb, CASA) if amb != CASA else (CASA,):", "6 ·"),
    ("ajustar reemplaza",          "capa = dict(todos_amb.get(amb) or {})", "capa = {}",   "5 ·"),
    ("el 401 se afloja",           'raise MemoriaError("sin_dueno", "un ajuste es de alguien")',
                                   "return ajustes(None, ambito)",                         "1 ·"),
    ("el dueño se ignora",         'return d / f"{user_id}.json"', 'return d / "todos.json"',
                                                                                           "2 ·"),
]


def probar_cayendo() -> int:
    import importlib.util
    global FALLOS, OK
    fuente = (RAIZ / "platform" / "workspaces" / "memoria.py").read_text("utf-8")
    malas = 0
    print("— probando la vara cayendo: 5 mutaciones —\n")
    for nombre, viejo, nuevo_txt, espera in MUTACIONES:
        if viejo not in fuente:
            print(f"   ⚠ «{nombre}»: el ancla ya no existe en memoria.py — mutación NO APLICADA")
            malas += 1
            continue
        d = Path(tempfile.mkdtemp(prefix="mut-"))
        os.environ["ALEPH_DATA_DIR"] = str(d / "datos")
        mod_path = d / "memoria_mutada.py"
        mod_path.write_text(fuente.replace(viejo, nuevo_txt), "utf-8")
        spec = importlib.util.spec_from_file_location("memoria_mutada", mod_path)
        mod = importlib.util.module_from_spec(spec)
        FALLOS, OK = [], []
        try:
            spec.loader.exec_module(mod)
            medir_almacen(mod)
        except Exception as e:                               # noqa: BLE001
            FALLOS.append(f"{espera} la mutación reventó: {type(e).__name__}")
        cayo = [f for f in FALLOS if f.startswith(espera)]
        if cayo:
            print(f"   ✓ «{nombre}» → rojea {espera} ({len(cayo)} aserción/es)")
        else:
            print(f"   ✗ «{nombre}» → NO rojeó nada de {espera}. La vara no mide esa familia.")
            malas += 1
    FALLOS, OK = [], []
    print()
    if malas:
        print(f"✗ la vara NO está probada: {malas} de {len(MUTACIONES)} mutaciones pasaron impunes")
        return 1
    print(f"✓ la vara cae con las {len(MUTACIONES)} mutaciones — puede dar rojo")
    return 0


def main() -> int:
    if "--probar-cayendo" in sys.argv:
        return probar_cayendo()
    _aislar()
    from workspaces import memoria
    medir_almacen(memoria)
    medir_modelos()
    medir_borde()
    print(f"— {len(OK) + len(FALLOS)} aserciones —")
    if FALLOS:
        print(f"\n✗ ROJO · {len(FALLOS)} de {len(OK) + len(FALLOS)}:\n")
        for f in FALLOS:
            print(f"   ✗ {f}")
        return 1
    for o in OK:
        print(f"   ✓ {o}")
    print(f"\n✓ VERDE · {len(OK)}/{len(OK)} — los ajustes tienen dueño, ámbito y vocabulario")
    return 0


if __name__ == "__main__":
    sys.exit(main())
