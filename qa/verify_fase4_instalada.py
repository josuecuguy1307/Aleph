#!/usr/bin/env python3
"""verify_fase4_instalada.py — LA VARA DE CIERRE DE LA FASE 4, CONTRA LA `.app` INSTALADA.
[Gate 4 · Fase 4 · O1 · O2 · O3 · O4 · O5 · O6 · LEY 15]

QUÉ AFIRMA
----------
Las siete obras de la fase, sobre el artefacto que se distribuye — no sobre el árbol:

  O1 · el pack de Ciencia VIAJÓ y Aleph puede levantarlo solo (`autoarranca`), entrar lo
       levanta, salir lo apaga y **no queda un solo pid vivo**
  O2 · el plugin de la casa viaja adentro del congelado y el pack lo declara por `file://`
  O3 · la inmersión: el pack sirve su propia UI **sin el `dist` al lado** (que salió del
       empaquetado por redundante), y el marco manda su tema
  O4 · el morph persistido tiene sus seams en el congelado
  O5 · el aplicador único y la memoria por dueño contestan
  O6 · la tarjeta y el canvas emergente viajaron
  LEY 15 · un turno **sin agente** entra por el borde y **no escribe ni una fila en `puppets`**

SE LE PREGUNTA AL BINARIO, NO AL TOC — lección sellada de `bundle_datos.py`: el TOC dice lo
que se pidió empaquetar; el binario dice lo que de verdad viajó. Acá se levanta el sidecar
de la `.app` instalada y se le pregunta a él.

    python3 qa/verify_fase4_instalada.py
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

APP = Path("/Applications/Aleph.app")
SIDECAR = APP / "Contents/MacOS/aleph_sidecar"

fallos: list[str] = []


def ok(cond: bool, etiqueta: str, extra: str = "") -> None:
    print(f"{'✓' if cond else '✗'} {etiqueta}{('  ' + extra) if extra else ''}", flush=True)
    if not cond:
        fallos.append(etiqueta)


def puerto_libre() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = int(s.getsockname()[1])
    s.close()
    return p


def pedir(url, metodo="GET", cuerpo=None, cab=None, timeout=45.0):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    cabeceras = {"Content-Type": "application/json", **(cab or {})}
    req = urllib.request.Request(url, data=datos, method=metodo, headers=cabeceras)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            crudo = r.read()
            try:
                return r.status, json.loads(crudo or b"null")
            except Exception:                               # noqa: BLE001
                return r.status, crudo.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        cuerpo_err = (e.read() or b"").decode("utf-8", "replace")
        try:
            return e.code, json.loads(cuerpo_err or "null")
        except Exception:                                   # noqa: BLE001
            return e.code, cuerpo_err
    except Exception as e:                                  # noqa: BLE001
        return 0, str(e)[:160]


def vive(pid: int) -> bool:
    return subprocess.run(["kill", "-0", str(pid)], capture_output=True).returncode == 0


def main() -> int:
    print(f"── la .app INSTALADA ──")
    ok(SIDECAR.is_file(), "hay un sidecar instalado", str(SIDECAR))
    if not SIDECAR.is_file():
        return 1
    sha = subprocess.run(["shasum", "-a", "256", str(SIDECAR)],
                         capture_output=True, text=True).stdout.split()[0]
    print(f"   sidecar sha256 {sha[:24]}…")
    print(f"   .app           {subprocess.run(['du','-sh',str(APP)],capture_output=True,text=True).stdout.split()[0]}")

    datos = Path(tempfile.mkdtemp(prefix="f4-cierre-"))
    puerto = puerto_libre()
    base = f"http://127.0.0.1:{puerto}"
    proc = subprocess.Popen(
        [str(SIDECAR), "--port", str(puerto)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        env={**os.environ, "ALEPH_DATA_DIR": str(datos), "ALEPH_ROLE": "client",
             "PUPPET_ALLOW_PASSWORD_AUTH": "1"})
    pids_pack: list[int] = []
    try:
        vivo = False
        for _ in range(90):
            time.sleep(1)
            try:
                urllib.request.urlopen(base + "/health", timeout=2)
                vivo = True
                break
            except Exception:                               # noqa: BLE001
                if proc.poll() is not None:
                    break
        ok(vivo, "el sidecar del congelado levanta y atiende", base)
        if not vivo:
            return 1

        # ── O1 · EL PACK VIAJÓ ──────────────────────────────────────────────────────
        st, j = pedir(base + "/v1/workspaces")
        fila = next((w for w in (j or {}).get("workspaces", []) if w["id"] == "ciencia"), None)
        ok(fila is not None, "O1 · Ciencia está en el registro del congelado")
        if fila is None:
            print(json.dumps(j)[:300])
            return 1
        ok(fila["stack"]["installed"] is True,
           "O1 · `installed` — y ahora lo dice el BINARIO del pack, no el `dist`")
        ok(fila["stack"].get("autoarranca") is True,
           "O1 · `autoarranca`: Aleph puede levantarlo solo")
        ok(fila["stack"]["running"] is False,
           "O1 · y todavía no corre: instalado y corriendo son dos hechos distintos")
        ok(len(fila.get("sources") or []) >= 40,
           "O1 · el censo 2.ter viajó con la fila", f"{len(fila.get('sources') or [])} fuentes")

        # La cuenta va PRIMERO: el congelado exige sesión para escribir en `/v1` —en dev eso
        # lo aflojaba `PUPPET_ALLOW_ANON_V1`— y entrar a un workspace es una escritura. Lo
        # cazó esta misma vara con un 401 honesto.
        st, u = pedir(base + "/v1/auth/register", "POST", {
            "email": f"cierre-{uuid.uuid4().hex[:8]}@puppet.local",
            "password": "vara-cierre-f4", "display_name": "Cierre"})
        ok(st == 201 and u.get("session_token"), "hay una cuenta para las pruebas de dueño")
        cab = {"Authorization": "Bearer " + u["session_token"]}

        st, e = pedir(base + "/v1/workspaces/ciencia/enter", "POST",
                      {"user_id": u["id"]}, cab)
        ok(st == 200, "O1 · ENTRAR levanta el pack desde el congelado", f"({st})")
        if st != 200:
            print(json.dumps(e)[:300])
        else:
            pids_pack = list(e.get("pids") or [])
            ok(bool(pids_pack) and all(vive(p) for p in pids_pack),
               "O1 · el proceso está vivo", str(pids_pack))
            st, j2 = pedir(base + "/v1/workspaces", cab=cab)
            f2 = next(w for w in j2["workspaces"] if w["id"] == "ciencia")
            ok(f2["stack"]["running"] is True and f2["stack"]["url"] == e["url"],
               "O1 · el registro dice la verdad, con la URL del pack VIVO", f2["stack"]["url"])

            # ── O3 · SU UI SALE DEL BINARIO, SIN `dist` AL LADO ─────────────────────
            try:
                with urllib.request.urlopen(e["url"] + "/", timeout=10) as r:
                    tipo, largo = r.headers.get("Content-Type", ""), len(r.read())
            except Exception as ex:                         # noqa: BLE001
                tipo, largo = str(ex)[:40], 0
            ok("text/html" in tipo and largo > 500,
               "O3 · el pack sirve su UI DESDE EL BINARIO (el `dist` salió del empaquetado)",
               f"{tipo} · {largo} b")

            # ── O2 · EL PLUGIN VIAJÓ Y ESTÁ DECLARADO ──────────────────────────────
            cfg = json.loads((datos / "workspaces/ciencia/config/openscience.json").read_text())
            plugin = (cfg.get("plugin") or [""])[0]
            ok(plugin.startswith("file://") and plugin.endswith("openscience.js"),
               "O2 · el pack declara el plugin de la casa por `file://`", plugin[-52:])
            ruta = plugin.replace("file://", "")
            ok(os.path.isfile(ruta),
               "O2 · y el archivo EXISTE adentro del congelado (no es una ruta a la nada)")
            ok((datos / "workspaces/ciencia/config/aleph-pack.json").exists(),
               "O2 · sus ajustes (0600) están escritos")

            # ── O1 · SALIR APAGA, CERO HUÉRFANOS ───────────────────────────────────
            st, l = pedir(base + "/v1/workspaces/ciencia/leave", "POST",
                          {"gracia_s": 0, "user_id": u["id"]}, cab)
            time.sleep(2.0)
            vivos = [p for p in pids_pack if vive(p)]
            ok(st == 200 and not vivos,
               "O1 · SALIR APAGA y no queda un solo pid del pack", f"vivos={vivos}")

        # ── O5 · EL APLICADOR Y LA MEMORIA ──────────────────────────────────────────
        st, d = pedir(base + "/v1/workspaces/destino?tipo=informe")
        ok(st == 200 and d.get("destino") == "ciencia" and d.get("motivo") == "artefacto",
           "O5 · el aplicador único resuelve el destino de un informe",
           json.dumps({k: d.get(k) for k in ("destino", "motivo")}))
        st, d2 = pedir(base + "/v1/workspaces/destino?tipo=cad")
        ok(st == 200 and d2.get("destino") is None and d2.get("motivo") == "nadie_lo_reclama",
           "O5 · y lo que nadie reclama cae al suelo, con su copy", d2.get("copy") or "")

        st, m = pedir(f"{base}/v1/workspaces/ciencia/memoria", "PUT",
                      {"user_id": u["id"], "chat_id": "chat-cierre"}, cab)
        ok(st == 200 and m["memoria"]["chat_id"] == "chat-cierre",
           "O5 · la memoria por (dueño, workspace) guarda")
        st, m2 = pedir(f"{base}/v1/workspaces/ciencia/memoria?user_id={u['id']}", cab=cab)
        ok(m2["memoria"].get("chat_id") == "chat-cierre",
           "O5 · y devuelve el workspace como quedó")
        st, _ = pedir(f"{base}/v1/workspaces/ciencia/memoria?user_id={u['id']}")
        ok(st == 401, "O5 · sin sesión, la memoria de nadie se lee", f"({st})")

        # ── LEY 15 · EL TURNO SIN AGENTE ────────────────────────────────────────────
        def agentes() -> int:
            db = next((p for p in datos.rglob("aleph.db")), None)
            if db is None:
                return -1
            con = sqlite3.connect(str(db))
            try:
                return int(con.execute("SELECT COUNT(*) FROM puppets").fetchone()[0])
            finally:
                con.close()

        antes = agentes()
        st, r = pedir(base + "/v1/workspaces/brain/complete", "POST",
                      {"messages": [{"role": "user", "content": "hola"}],
                       "user_id": u["id"], "model": "opus", "workspace": "ciencia"}, cab)
        det = (r or {}).get("detail") if isinstance(r, dict) else {}
        causa = det.get("error") if isinstance(det, dict) else None
        ok(causa != "missing_recipe",
           "LEY 15 · sin agente y sin receta, el borde del CONGELADO ya no exige agente",
           f"({st}) {causa or ''}")
        ok(st == 424 and causa == "modelo_no_conectado",
           "LEY 15 · y frena con causa tipada: el modelo elegido no tiene llave",
           f"({st}) {causa}")
        ok(agentes() == antes,
           "LEY 15.b · el turno raw NO escribió ni una fila en `puppets`",
           f"{antes} → {agentes()}")

        # ── O4 · O6 · LO QUE TIENE QUE ESTAR EN LA CARA ─────────────────────────────
        def sirve(ruta: str, marca: str) -> tuple:
            try:
                with urllib.request.urlopen(base + ruta, timeout=10) as r:
                    cuerpo = r.read().decode("utf-8", "replace")
                return r.status, (marca in cuerpo)
            except Exception as e:                          # noqa: BLE001
                return 0, False

        st, hay = sirve("/cuarto/cuarto.pixi.html", "__cuartoRestaurarMorph")
        ok(st == 200 and hay, "O4 · el morph persistido viajó en el congelado", f"({st})")
        st, hay = sirve("/sala-v2/ui/tarjeta-obra.js", "sv-tarjeta-obra")
        ok(st == 200 and hay, "O6 · la tarjeta de la obra viajó", f"({st})")
        st, hay = sirve("/sala-v2/sala-v2.css", 'data-canvas="abierto"')
        ok(st == 200 and hay, "O6 · el canvas emergente viajó (B10)", f"({st})")
        st, hay = sirve("/workspaces/ciencia.html", "aleph_scheme")
        ok(st == 200 and hay, "O3 · la piel del workspace manda el tema de la casa", f"({st})")
    finally:
        for p in pids_pack:
            if vive(p):
                subprocess.run(["kill", "-9", str(p)], capture_output=True)
        try:
            os.killpg(os.getpgid(proc.pid), 15)
            proc.wait(timeout=10)
        except Exception:                                   # noqa: BLE001
            try:
                os.killpg(os.getpgid(proc.pid), 9)
            except Exception:                               # noqa: BLE001
                pass
        shutil.rmtree(datos, ignore_errors=True)

    print(f"\n{'VERDE' if not fallos else 'ROJAS: ' + ', '.join(fallos)}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
