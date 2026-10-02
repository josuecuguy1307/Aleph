#!/usr/bin/env python3
"""verify_biblioteca_filtra_ws.py — ¿LA LISTA DE HILOS DE UNA VISTA ES SÓLO LA SUYA?

[convergencia · superficie 1]

LA PREGUNTA, EN UNA LÍNEA: con hilos de VARIOS workspaces y hilos de La Sala en la misma
tabla, ¿`GET /v1/chats` le da a cada vista los suyos y nada más?

POR QUÉ HACE FALTA — MEDIDO EN LA `aleph.db` REAL ANTES DE ESCRIBIRLO. Un dueño, 82 chats.
Seis de ellos son los hilos de los seis workspaces:

    Ciencia 105 msgs · Diseño 63 · Educación 48 · Oficina 40 · Legal 27 · Finanzas 18

Los crea cada `workspaces/<ws>.html` con `POST /v1/chats`, o sea que caen en la MISMA tabla
`chats` que los de La Sala. Y `GET /v1/chats` los devolvía **los 82 juntos**: la lista de
hilos de La Sala mostraba los seis espacios, y por venir ordenados `updated_at DESC` se le
paraban arriba de todo — al punto de que el `rows[0]` de `sala-v2.js` elegía un hilo de
workspace como hilo por defecto de La Sala.

LA ATRIBUCIÓN NO ES NUEVA: el mapa `(dueño, workspace) → chat_id` está en
`workspaces/memoria.py` desde la obra O5, y su `todos()` **no tenía un solo llamador**.

QUÉ MIDE, CONTRA EL ENDPOINT REAL (FastAPI + `build_chats_router`, con sesión de verdad):

  1 · LA VISTA DE CADA ESPACIO — `?workspace=<ws>` devuelve EXACTAMENTE su hilo. Se prueba
      con los TRES, y para cada uno se exige que los otros dos NO estén: una vista que
      devuelve de más pasa un test que sólo mire «¿está el mío?».
  2 · LA VISTA DE LA SALA — `?workspace=none` devuelve los de La Sala y NINGUNO de los tres.
  3 · LA VISTA GLOBAL NO SE ROMPE — sin el parámetro se siguen viendo los cinco. Es lo que
      `Historial.dc.html` pide, y un arreglo que la filtrara sería una regresión.
  4 · EL CAMPO VIAJA — cada fila sale con `workspace` anotado (el id, o `None` si es de La
      Sala), valga o no el scope: una fila que no dice de qué espacio es obliga a cada
      pantalla a re-derivarlo, y la que se olvide vuelve a mezclar.
  5 · EL RECORTE VA EN EL WHERE, NO DESPUÉS DEL LIMIT — con `limit=2` y los tres hilos de
      workspace arriba (son los más recientes), filtrar la lista ya traída devolvería CERO
      filas de La Sala. Se exige que devuelva 2.
  6 · EL DUEÑO SIGUE MANDANDO — el mapa de otro dueño no recorta ni etiqueta lo de éste.

CÓMO SE PRUEBA CAYENDO (una vara que no puede dar rojo no mide):

    ALEPH_VARA_ROMPER=filtro     el scope se ignora (vuelve la conducta vieja) → rojo por 1 y 2
    ALEPH_VARA_ROMPER=campo      el campo `workspace` no se anota               → rojo por 4
    ALEPH_VARA_ROMPER=global     el filtro se aplica SIEMPRE, aun sin pedirlo   → rojo por 3 (y 4)
    ALEPH_VARA_ROMPER=limite     el recorte se hace después del LIMIT           → rojo por 5

Los cuatro probados cayendo, y ninguno tumba la vara a mitad: cada uno da rojo en SU eje y
los demás se siguen midiendo. `filtro` es el defecto original tal cual estaba.

⚠️ NO ESCRIBE EN EL ESTADO REAL. El `.db` y el `ALEPH_DATA_DIR` se apuntan a un temporal
ANTES de importar nada, y si la ruta resuelta cae en el dir del usuario la vara sale 2 sin
tocar un byte. (Es la quinta vez en este repo que una vara deja datos en el dir real: el
`chat-de-ana` de `qa/verify_destino_y_memoria.py:226` todavía está ahí — lo verifiqué hoy
en `~/Library/Application Support/Aleph/workspaces/memoria/la-instalacion.json`.)

    <venv>/bin/python qa/verify_biblioteca_filtra_ws.py
      0 → cada vista muestra sólo lo suyo y la global sigue viendo todo
      1 → alguna mezcla; se dice cuál y con qué filas
      2 → no se pudo medir (NO cuenta como verde)
"""
from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROMPER = (os.environ.get("ALEPH_VARA_ROMPER") or "").strip().lower()


def no_medible(motivo: str):
    print(f"[no medible] {motivo}")
    sys.exit(2)


# ── EL AISLAMIENTO, ANTES DE IMPORTAR NADA ───────────────────────────────────────────
TMP = Path(tempfile.mkdtemp(prefix="vara-biblio-ws-"))
os.environ["ALEPH_ROLE"] = "client"
os.environ["ALEPH_DATA_DIR"] = str(TMP / "datos")
os.environ["XDG_DATA_HOME"] = str(TMP / "datos")
os.environ["XDG_CONFIG_HOME"] = str(TMP / "config")
os.environ["PUPPET_SQLITE_PATH"] = str(TMP / "datos" / "aleph.db")
(TMP / "datos").mkdir(parents=True, exist_ok=True)

for _p in (ROOT / "product" / "backend", ROOT / "platform" / "db", ROOT / "platform"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

try:
    import sqlite_db                                        # noqa: E402
    from app.phase1 import chats_repo                       # noqa: E402
    from app.phase1 import chats_router as CR               # noqa: E402
    from app.phase1 import repo                             # noqa: E402
    from workspaces import memoria as ws_memoria            # noqa: E402
except Exception as exc:                                    # noqa: BLE001
    no_medible(f"no se pudo importar el árbol: {exc}")

# El guard: si la ruta resuelta NO es la temporal, no se toca nada.
_ruta = Path(sqlite_db.ruta_db()).resolve()
if TMP.resolve() not in _ruta.parents:
    no_medible(f"el .db resuelto no está en el temporal ({_ruta}); no escribo en el real")
_mem = Path(ws_memoria._ruta("guard-xxxx")).resolve()       # noqa: SLF001
if TMP.resolve() not in _mem.parents:
    no_medible(f"la memoria resuelta no está en el temporal ({_mem}); no escribo en el real")


# ── LOS MUTANTES ─────────────────────────────────────────────────────────────────────
# Se aplican sobre el código de PRODUCCIÓN ya importado, que es lo que la vara mide.
if ROMPER == "filtro":
    _orig = chats_repo.list_chats
    def _sin_scope(conn, user_id, **kw):                    # noqa: ANN001
        kw["workspace_scope"] = "all"
        return _orig(conn, user_id, **kw)
    chats_repo.list_chats = _sin_scope
elif ROMPER == "campo":
    _orig = chats_repo.list_chats
    def _sin_campo(conn, user_id, **kw):                    # noqa: ANN001
        filas = _orig(conn, user_id, **kw)
        for f in filas:
            f.pop("workspace", None)
        return filas
    chats_repo.list_chats = _sin_campo
elif ROMPER == "global":
    _orig_scope = CR._workspace_scope                       # noqa: SLF001
    CR._workspace_scope = lambda w: ("casa", None) if not w else _orig_scope(w)
elif ROMPER == "limite":
    _orig = chats_repo.list_chats
    def _tarde(conn, user_id, **kw):                        # noqa: ANN001
        scope = kw.pop("workspace_scope", "all")
        ws = kw.pop("workspace", None)
        mapa = kw.get("ws_por_chat") or {}
        filas = _orig(conn, user_id, workspace_scope="all", workspace=None, **kw)
        if scope == "casa":
            filas = [f for f in filas if str(f.get("id")) not in mapa]
        elif scope == "ws":
            filas = [f for f in filas if mapa.get(str(f.get("id"))) == ws]
        return filas
    chats_repo.list_chats = _tarde


# ── EL ARNÉS ─────────────────────────────────────────────────────────────────────────
FALLAS: list[str] = []
LOS_TRES = ["ciencia", "diseno", "educacion"]


def ok(cond, linea: str, detalle: str = ""):
    print(("  ✅ " if cond else "  ❌ ") + linea + (f"   → {detalle}" if (detalle and not cond) else ""))
    if not cond:
        FALLAS.append(linea)


def _hr(t):
    print(f"\n── {t} " + "─" * max(0, 74 - len(t)))


def main() -> int:
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
    except Exception as exc:                                # noqa: BLE001
        no_medible(f"sin fastapi/testclient: {exc}")

    conn = repo.get_conn()
    try:
        sqlite_db.crear_schema(conn)
    except Exception:                                       # noqa: BLE001
        pass                                                # ya creado por el import

    dueno = repo.get_or_create_user(conn, email=f"biblio-{uuid.uuid4().hex[:8]}@toy.local",
                                    tier="free")["id"]
    ajeno = repo.get_or_create_user(conn, email=f"biblio-{uuid.uuid4().hex[:8]}@toy.local",
                                    tier="free")["id"]

    # EL STORE: tres hilos de workspace + dos de La Sala, del MISMO dueño y en la MISMA
    # tabla — que es exactamente la forma que tiene la `aleph.db` real.
    # EL ORDEN DE CREACIÓN ES PARTE DE LA MEDICIÓN, no un detalle. Los de La Sala van
    # PRIMERO y los de workspace DESPUÉS, para que los tres queden arriba en
    # `updated_at DESC` — que es la forma real (un workspace recién usado es lo más
    # reciente que hay, y en la `aleph.db` medida «Ciencia» era el segundo de 82). Al revés
    # el eje 5 no puede distinguir un WHERE de un post-filtro: con los de La Sala arriba,
    # `limit=2` los trae igual y el mutante `limite` pasa en verde. Me pasó.
    sala = [str(chats_repo.create_chat(conn, user_id=dueno, title=f"hilo sala {i}")["id"])
            for i in range(2)]
    de_ws = {}
    for ws in LOS_TRES:
        cid = chats_repo.create_chat(conn, user_id=dueno, title=ws.capitalize())["id"]
        de_ws[ws] = str(cid)
        ws_memoria.recordar(dueno, ws, chat_id=str(cid))
    # Un hilo del OTRO dueño, con su propia memoria: el eje 6.
    ajeno_cid = str(chats_repo.create_chat(conn, user_id=ajeno, title="Ciencia del otro")["id"])
    ws_memoria.recordar(ajeno, "ciencia", chat_id=ajeno_cid)

    app = FastAPI()
    app.include_router(CR.build_chats_router(get_conn=repo.get_conn))
    client = TestClient(app)
    tok = {"Authorization": f"Bearer {repo.mint_session(dueno)}"}

    def pedir(qs: str = "") -> list[dict]:
        r = client.get("/v1/chats" + qs, headers=tok)
        if r.status_code != 200:
            no_medible(f"GET /v1/chats{qs} → {r.status_code}: {r.text[:200]}")
        return r.json().get("chats") or []

    ids = lambda filas: {str(f.get("id")) for f in filas}   # noqa: E731

    # 1 · LA VISTA DE CADA ESPACIO
    _hr("1 · la vista de cada espacio muestra SÓLO su hilo")
    for ws in LOS_TRES:
        filas = pedir(f"?workspace={ws}")
        vistos = ids(filas)
        ajenos = sorted(vistos - {de_ws[ws]})
        ok(vistos == {de_ws[ws]},
           f"{ws}: exactamente su hilo, y ninguno de los otros",
           f"vio {len(vistos)} filas; de más: {ajenos}")

    # 2 · LA VISTA DE LA SALA
    _hr("2 · la vista de La Sala no muestra ningún hilo de workspace")
    filas = pedir("?workspace=none")
    vistos = ids(filas)
    colados = sorted(vistos & set(de_ws.values()))
    ok(not colados, "ningún hilo de workspace en la lista de La Sala",
       f"se colaron {len(colados)}: " + ", ".join(
           f"{c[:8]}={[w for w, i in de_ws.items() if i == c][0]}" for c in colados))
    ok(vistos == set(sala), "y están los dos de La Sala",
       f"esperaba {sorted(sala)}, vio {sorted(vistos)}")

    # 3 · LA VISTA GLOBAL NO SE ROMPE
    _hr("3 · sin el parámetro se sigue viendo TODO (Historial.dc.html)")
    todos = ids(pedir())
    ok(todos == set(sala) | set(de_ws.values()),
       "la vista global ve los cinco hilos del dueño",
       f"esperaba 5, vio {len(todos)}: {sorted(todos)}")

    # 4 · EL CAMPO VIAJA
    _hr("4 · cada fila dice de qué espacio es")
    # `.get(c) or {}` y no `por_id[c]`: si un eje anterior ya rompió y la fila no vino, esto
    # tiene que contarlo como ROJO y seguir midiendo los ejes 5 y 6. Una vara que se cae a
    # mitad deja invisibles los defectos que venían después — ya nos costó tres.
    filas = pedir()
    por_id = {str(f.get("id")): f for f in filas}
    faltan = [c[:8] for c in por_id if "workspace" not in por_id[c]]
    ok(not faltan, "toda fila trae el campo `workspace`", f"sin campo: {faltan}")
    mal = [f"{c[:8]} dice {(por_id.get(c) or {}).get('workspace')!r}"
           for ws, c in de_ws.items() if (por_id.get(c) or {}).get("workspace") != ws]
    ok(not mal, "el hilo de cada espacio se declara con su id", "; ".join(mal))
    mal_sala = [f"{c[:8]} dice {(por_id.get(c) or {}).get('workspace')!r}"
                for c in sala if (por_id.get(c) or {}).get("workspace") is not None]
    ok(not mal_sala, "el hilo de La Sala se declara sin espacio (`None`)", "; ".join(mal_sala))

    # 5 · EL RECORTE VA EN EL WHERE
    _hr("5 · el recorte va en el WHERE y no después del LIMIT")
    filas = pedir("?workspace=none&limit=2")
    ok(len(filas) == 2,
       "con limit=2 la vista de La Sala devuelve 2 filas, no las que sobren",
       f"devolvió {len(filas)} — el recorte se está haciendo sobre la lista ya traída")

    # 6 · EL DUEÑO SIGUE MANDANDO
    _hr("6 · el mapa de un dueño no toca lo del otro")
    tok_ajeno = {"Authorization": f"Bearer {repo.mint_session(ajeno)}"}
    r = client.get("/v1/chats?workspace=ciencia", headers=tok_ajeno)
    suyo = {str(f.get("id")) for f in (r.json().get("chats") or [])} if r.status_code == 200 else set()
    ok(suyo == {ajeno_cid}, "el otro dueño ve SU hilo de ciencia y sólo ése",
       f"vio {sorted(suyo)}")
    mios = ids(pedir("?workspace=ciencia"))
    ok(ajeno_cid not in mios, "y su hilo no aparece en la vista del primero", f"vio {sorted(mios)}")

    conn.close()

    print("\n" + "=" * 78)
    if FALLAS:
        print(f"ROJO — {len(FALLAS)} de los ejes fallaron:")
        for f in FALLAS:
            print(f"  · {f}")
        return 1
    print("VERDE — cada vista muestra sólo lo suyo y la global sigue viendo todo.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:                                # noqa: BLE001
        import traceback
        traceback.print_exc()
        no_medible(f"la vara se cayó: {exc}")
