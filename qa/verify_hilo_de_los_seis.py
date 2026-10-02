#!/usr/bin/env python3
"""verify_hilo_de_los_seis.py — ¿EL TRABAJO DE LOS SEIS WORKSPACES CAE EN UN SOLO LUGAR?

[convergencia · superficie 1]

LA PREGUNTA, EN UNA LÍNEA: para cada uno de los seis workspaces, ¿un turno deja en el hilo
de la casa **el pedido del humano Y la respuesta del agente**?

POR QUÉ HACE FALTA. Medido en la `aleph.db` real antes de la obra, ninguna de las seis
filas estaba completa salvo una:

    Ciencia 8 user / 4 agent · Oficina 4/0 · Legal 0/1 · Finanzas 1/0 · Diseño 0/0 · Educación 0/0

CÓMO MIDE — LA CADENA ENTERA, EN DOS MITADES, LAS DOS CORRIENDO CÓDIGO DE PRODUCCIÓN:

  A · EL STACK MANDA EL HILO.  No se lee la fuente: se EJECUTA.
      · legal · ciencia · oficina → se corre el plugin de verdad en node, con los dos
        `fetch` interceptados, y se captura el cuerpo que le manda a `brain/close`.
      · educacion · finanzas → se corre `pack.escribir_config()` de verdad contra un dir
        temporal y se lee el archivo que deja.
      · diseno → se corre `write_config()` del launcher de verdad y se lee su `config.toml`.

  B · LA CASA ANOTA.  Contra una `aleph.db` NUEVA en un temporal.
      · con plugin → `POST /v1/workspaces/brain/close`, el endpoint real, con el cuerpo
        LITERAL que capturó A. Si el plugin dejó de mandar `prompt`, esta mitad se entera.
      · sin plugin → `hilo_workspace.turno_de/anotar_pedido/anotar_respuesta`, que son las
        funciones que llama el borde OpenAI, con el `chat_id` que salió del archivo que
        escribió A. Si el config dejó de llevar `X-Aleph-Chat`, no hay a dónde anotar.

  C · Y LA GUARDA DEL DOBLE: para los tres que SÍ tienen plugin, `le_toca_al_borde` tiene
      que decir que no. Sin eso, cada turno de Ciencia se anotaría dos veces.

CÓMO SE PRUEBA CAYENDO (y hay que probarla, porque una vara que no puede dar rojo no mide):

    ALEPH_VARA_ROMPER=educacion   saca `X-Aleph-Chat` del config de Educación
    ALEPH_VARA_ROMPER=diseno      lo saca del `config.toml` de Diseño
    ALEPH_VARA_ROMPER=legal       saca `prompt` del cuerpo del cierre de Legal
    ALEPH_VARA_ROMPER=respuesta   deja la respuesta vacía en los seis

    Cada uno tiene que dar rojo EN SU FILA y sólo en ella (`respuesta` en las seis).

⚠️ NO ESCRIBE EN EL ESTADO REAL, y lo verifica antes de empezar en vez de prometerlo: es la
cuarta vez en este repo que una vara deja datos en el dir del usuario
(`qa/verify_destino_y_memoria.py:226` dejó un `chat-de-ana` que todavía está ahí). Acá el
`.db` y el `ALEPH_DATA_DIR` se apuntan a un temporal ANTES de importar nada, y si la ruta
resuelta cae en el dir del usuario la vara sale 2 sin tocar un byte.

    <venv>/bin/python qa/verify_hilo_de_los_seis.py
      0 → los seis reciben `user` y `agent`
      1 → alguno no; se dice cuál y en qué mitad se cortó
      2 → no se pudo medir (NO cuenta como verde)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROMPER = (os.environ.get("ALEPH_VARA_ROMPER") or "").strip().lower()

#: (workspace, export del plugin | None, cómo se lee su config)
LOS_SEIS = [
    ("legal",     "AlephLegal",     "plugin"),
    ("ciencia",   "AlephWorkspace", "plugin"),
    ("oficina",   "AlephOficina",   "plugin"),
    ("educacion", None,             "json"),
    ("diseno",    None,             "toml"),
    ("finanzas",  None,             "dotenv"),
]

PROMPT = "¿cuánto es 17 por 23?"
RESPUESTA = "391"


def no_medible(motivo: str):
    print(f"[no medible] {motivo}")
    sys.exit(2)


# ── EL AISLAMIENTO, ANTES DE IMPORTAR NADA ───────────────────────────────────────────
TMP = Path(tempfile.mkdtemp(prefix="vara-hilo-seis-"))
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
    from app.phase1 import hilo_workspace as hw             # noqa: E402
    from app.phase1 import repo                             # noqa: E402
    from app.phase1 import router as R                      # noqa: E402
    from workspaces import pack                             # noqa: E402
except Exception as exc:                                    # noqa: BLE001
    no_medible(f"no se pudo importar el árbol: {exc}")

# El guard: si la ruta resuelta NO es la temporal, no se toca nada.
_ruta = Path(sqlite_db.ruta_db()).resolve()
if TMP.resolve() not in _ruta.parents:
    no_medible(f"el .db resuelto no está en el temporal ({_ruta}); no escribo en el real")

DB = str(TMP / "datos" / "aleph.db")


# ── A · EL STACK MANDA EL HILO ───────────────────────────────────────────────────────

def cierre_del_plugin(ws: str, export: str) -> dict:
    """Corre el plugin de verdad y devuelve el cuerpo que le manda a `brain/close`."""
    ruta = ROOT / "platform" / "workspaces" / "plugins" / _archivo_plugin(ws)
    out = subprocess.run(
        ["node", str(ROOT / "qa" / "lib" / "sonda_plugin_cierre.mjs"), str(ruta), export],
        capture_output=True, text=True, cwd=str(ROOT), timeout=90)
    if out.returncode != 0:
        raise RuntimeError(f"la sonda del plugin salió {out.returncode}: {out.stderr[-300:]}")
    datos = json.loads(out.stdout or "{}")
    if not datos.get("ok"):
        raise RuntimeError(datos.get("motivo") or "el plugin no llamó a brain/close")
    return dict(datos["cierre"] or {})


def _archivo_plugin(ws: str) -> str:
    meta = R._WORKSPACE_STACKS.get(ws) or {}
    rel = meta.get("plugin") or ""
    if not rel:
        raise RuntimeError(f"«{ws}» no declara plugin en el registro")
    return Path(rel).name


def chat_id_del_config(ws: str, forma: str, chat_id: str) -> str:
    """Corre el escritor de config REAL y devuelve el `chat_id` que quedó en el header.

    `""` si no quedó ninguno — que es exactamente el estado que tenían Educación y Diseño
    antes de esta obra, y el que devuelve el modo `ALEPH_VARA_ROMPER`.
    """
    meta = R._WORKSPACE_STACKS[ws]
    if forma == "toml":
        import importlib.machinery
        import importlib.util
        ruta = ROOT / "third_party" / "codesign" / "bin" / "aleph-codesign"
        cargador = importlib.machinery.SourceFileLoader("aleph_codesign_vara", str(ruta))
        mod = importlib.util.module_from_spec(
            importlib.util.spec_from_loader("aleph_codesign_vara", cargador))
        cargador.exec_module(mod)
        cfg = {"workspace": ws, "base": "http://127.0.0.1:8150", "token": "t-vara",
               "user_id": "u-vara", "sid": "sid-vara",
               "cerebro_label": meta.get("cerebro_label", "Cerebro de Aleph")}
        if ROMPER != "diseno":
            cfg["chat_id"] = chat_id
        destino, _ = mod.write_config(cfg)
        texto = Path(destino).read_text(encoding="utf-8")
    else:
        destino = pack.escribir_config(
            ws, meta, base_aleph="http://127.0.0.1:8150", token="t-vara",
            user_id="u-vara", puppet_id=None, space_id="space-ws-vara-1", puerto=9999,
            chat_id=(None if ROMPER == ws else chat_id), sid="sid-vara")
        texto = Path(destino).read_text(encoding="utf-8")
    return _chat_del_texto(texto, forma)


def _chat_del_texto(texto: str, forma: str) -> str:
    """UN LECTOR POR FORMATO, y no uno solo «que sirva para los tres».

    Escribí primero el astuto —partir por `X-Aleph-Chat` y adivinar el separador— y dio
    ROJO en Diseño con el header PUESTO: su `httpHeaders` es una tabla inline de TOML, o
    sea las cuatro cabeceras en UNA línea, así que la cola era `= "…" }` y el `}` se venía
    de paseo. Es el instrumento mintiendo antes que el código, otra vez. Tres lectores
    aburridos no se equivocan.
    """
    import re
    if forma == "json":
        cab = json.loads(texto)["services"]["llm"]["profiles"][0].get("extra_headers") or {}
        return str(cab.get("X-Aleph-Chat") or "")
    if forma == "toml":
        m = re.search(r'X-Aleph-Chat\s*=\s*"([^"]*)"', texto)
        return m.group(1) if m else ""
    if forma == "dotenv":
        for linea in texto.splitlines():
            if not linea.startswith("OPENAI_CUSTOM_HEADERS="):
                continue
            for cab in linea.split("=", 1)[1].split("\\n"):
                if cab.strip().startswith("X-Aleph-Chat:"):
                    return cab.split(":", 1)[1].strip()
        return ""
    raise RuntimeError(f"forma de config desconocida: {forma}")


# ── B · LA CASA ANOTA ────────────────────────────────────────────────────────────────

def preparar_db():
    sqlite_db.asegurar_schema(DB)
    conn = sqlite_db.conectar(DB)
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO users (email) VALUES (%s) RETURNING id",
                        ("vara-hilo@local.test",))
            uid = str(cur.fetchone()[0])
        conn.commit()
    finally:
        conn.close()
    return uid


def hilo_nuevo(uid: str, titulo: str) -> str:
    conn = sqlite_db.conectar(DB)
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO chats (user_id, title) VALUES (%s,%s) RETURNING id",
                        (uid, titulo))
            cid = str(cur.fetchone()[0])
        conn.commit()
    finally:
        conn.close()
    return cid


def filas(chat_id: str) -> list[tuple[str, str]]:
    conn = sqlite_db.conectar(DB)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT role, content FROM chat_messages WHERE chat_id=%s "
                        "ORDER BY id", (chat_id,))
            return [(str(r[0]), str(r[1])) for r in cur.fetchall()]
    finally:
        conn.close()


def main() -> int:
    try:
        uid = preparar_db()
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        app.include_router(R.build_phase1_router(
            get_conn=lambda: sqlite_db.conectar(DB),
            events_dir=lambda: TMP / "datos" / "espacios"))
        cliente = TestClient(app)
        cabecera = {"Authorization": "Bearer " + repo.mint_session(uid)}
    except Exception as exc:                                # noqa: BLE001
        no_medible(f"no se pudo montar el borde: {exc}")

    respuesta = "" if ROMPER == "respuesta" else RESPUESTA
    veredictos: list[tuple[str, bool, str]] = []

    for ws, export, forma in LOS_SEIS:
        chat = hilo_nuevo(uid, ws)
        try:
            if export:
                cierre = cierre_del_plugin(ws, export)
                if ROMPER == ws:
                    cierre.pop("prompt", None)
                cierre.update({"chat_id": chat, "workspace": ws, "user_id": uid,
                               "answer": respuesta})
                r = cliente.post("/v1/workspaces/brain/close", headers=cabecera,
                                 json=cierre)
                if r.status_code != 200:
                    veredictos.append((ws, False, f"A→B: close devolvió {r.status_code}"))
                    continue
                # C · la guarda del doble
                if hw.le_toca_al_borde(R._WORKSPACE_STACKS.get(ws)):
                    veredictos.append((ws, False,
                                       "el borde TAMBIÉN lo anotaría: turno duplicado"))
                    continue
            else:
                cid = chat_id_del_config(ws, forma, chat)
                if not cid:
                    veredictos.append((ws, False,
                                       "A: su config no lleva `X-Aleph-Chat` — el borde no "
                                       "tiene a dónde anotar"))
                    continue
                if not hw.le_toca_al_borde(R._WORKSPACE_STACKS.get(ws)):
                    veredictos.append((ws, False, "B: el borde no lo anota y no tiene plugin"))
                    continue
                mensajes = [{"role": "user", "content": PROMPT}]
                turno = hw.turno_de(mensajes)
                if not turno:
                    veredictos.append((ws, False, "B: no se derivó el turno del pedido"))
                    continue
                conn = sqlite_db.conectar(DB)
                try:
                    hw.anotar_pedido(conn, chat_id=cid, turno=turno, space_id="space-ws-vara-1")
                    # Un paso intermedio (sólo tool_calls) no escribe; el final sí.
                    hw.anotar_respuesta(conn, chat_id=cid, turno=turno, texto="",
                                        space_id="space-ws-vara-1")
                    hw.anotar_respuesta(conn, chat_id=cid, turno=turno, texto=respuesta,
                                        space_id="space-ws-vara-1")
                finally:
                    conn.close()
        except Exception as exc:                            # noqa: BLE001
            veredictos.append((ws, False, f"se rompió midiendo: {exc}"))
            continue

        f = filas(chat)
        roles = [r for r, _ in f]
        if roles.count("user") == 1 and roles.count("agent") == 1:
            veredictos.append((ws, True, f"user+agent · {len(f)} filas"))
        else:
            veredictos.append((ws, False,
                               f"llegó {roles.count('user')} user / "
                               f"{roles.count('agent')} agent"))

    ancho = max(len(w) for w, _, _ in veredictos)
    print("¿EL TURNO DE CADA WORKSPACE LLEGA AL HILO DE LA CASA?\n")
    for ws, ok, det in veredictos:
        print(f"  {'✅' if ok else '❌'}  {ws.ljust(ancho)}  {det}")
    malas = [w for w, ok, _ in veredictos if not ok]
    print()
    if malas:
        print(f"ROJO — no llegan: {', '.join(malas)}")
        return 1
    print("VERDE — los seis reciben `user` y `agent`.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:                                # noqa: BLE001
        # Un crash NO es una caída medida: sale 2, jamás 0 ni 1.
        no_medible(f"la vara se rompió: {exc}")
