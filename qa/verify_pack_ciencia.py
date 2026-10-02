#!/usr/bin/env python3
"""verify_pack_ciencia.py — LA VARA DEL CICLO DE VIDA DEL PACK.
[Gate 4 · Fase 4 · obra O1 · deudas D-STACK-PROC · D-ARRANQUE-CEREBRO]

QUÉ AFIRMA, y contra qué
------------------------
Contra un backend REAL (uvicorn, dir de datos aislado, puerto libre) y el binario REAL del
stack. Nada de stubs: el pack levanta un proceso de verdad, se le pregunta a él si está
sano, y se le mira el pid para saber si murió.

  1. el registro dice `autoarranca` cuando el binario viajó, y NO lo confunde con `running`
  2. entrar LEVANTA el proceso, y el registro pasa a decir la verdad
  3. **el puerto horneado murió**: la URL que el registro reporta es la del pack vivo, no
     `url_default`, y el `baseURL` de la config generada lleva el puerto del backend de
     ESTA corrida — que es lo que estaba escrito a mano en un archivo del usuario
  4. entrar dos veces NO levanta dos packs (una sola fila en la tabla del dueño)
  5. salir con gracia 0 apaga en el acto y **no deja un solo pid vivo**
  6. la gracia corta existe y sirve: dentro de la ventana el proceso sigue vivo (un F5 no
     mata un kernel), y volver a entrar la cancela
  7. las causas del pack llegan con su copy (regla sellada), y sin binario el estado es
     honesto en vez de un botón que no hace nada

CÓMO SE PROBÓ CAYENDO
---------------------
`--caer horneado`  → afirma la URL de `url_default` en vez de la del pack vivo: el paso 3
                     se pone rojo, que es exactamente el defecto que esta obra mata.
`--caer sin-apagar`→ se salta el `leave`: el paso 5 encuentra el pid vivo y cae.

    python3 qa/verify_pack_ciencia.py            # la corrida normal
    python3 qa/verify_pack_ciencia.py --caer horneado
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CAER = ""
for i, a in enumerate(sys.argv):
    if a == "--caer" and i + 1 < len(sys.argv):
        CAER = sys.argv[i + 1]

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


def python_del_backend() -> str:
    """El venv del backend. Se prueban los candidatos EN ORDEN y se usa el primero que
    existe: el de este worktree y el de los árboles hermanos. Correr esta vara con el
    `python3` del sistema es la trampa que el repo ya pagó dos veces (falta `litellm`)."""
    for c in [RAIZ / "product/backend/.venv/bin/python"]:
        if c.is_file():
            return str(c)
    print("✗ no encontré el venv del backend", file=sys.stderr)
    sys.exit(2)


def pedir(url: str, metodo: str = "GET", cuerpo: dict | None = None, timeout: float = 30.0):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(url, data=datos, method=metodo,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:                                   # noqa: BLE001
            return e.code, None


def vive(pid: int) -> bool:
    return subprocess.run(["kill", "-0", str(pid)], capture_output=True).returncode == 0


def main() -> int:
    datos = Path(tempfile.mkdtemp(prefix="f4-pack-"))
    puerto = puerto_libre()
    base = f"http://127.0.0.1:{puerto}"
    env = {**os.environ,
           "ALEPH_DATA_DIR": str(datos), "ALEPH_ROLE": "client", "ALEPH_ENV": "dev",
           "PUPPET_ALLOW_ANON_V1": "1",
           # La gracia por defecto la fija el producto; la vara la mueve donde la mide.
           "ALEPH_PACK_GRACIA_S": "20"}
    proc = subprocess.Popen(
        [python_del_backend(), "-m", "uvicorn", "app.main:app",
         "--app-dir", str(RAIZ / "product/backend"),
         "--host", "127.0.0.1", "--port", str(puerto)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
        start_new_session=True)
    pids_pack: list[int] = []
    try:
        vivo_backend = False
        for _ in range(60):
            time.sleep(1)
            try:
                urllib.request.urlopen(base + "/health", timeout=2)
                vivo_backend = True
                break
            except Exception:                               # noqa: BLE001
                if proc.poll() is not None:
                    break
        ok(vivo_backend, "el backend de la vara está en pie", base)
        if not vivo_backend:
            return 1

        # ── 1 · EL REGISTRO, ANTES DE ENTRAR ────────────────────────────────────────
        st, j = pedir(base + "/v1/workspaces")
        fila = next((w for w in (j or {}).get("workspaces", []) if w["id"] == "ciencia"), None)
        ok(fila is not None, "el registro trae la fila de Ciencia")
        if fila is None:
            return 1
        ok(fila["stack"].get("autoarranca") is True,
           "el binario viajó ⇒ `autoarranca` verdadero")
        ok(fila["stack"]["running"] is False,
           "y `running` sigue en falso: instalado y corriendo son dos hechos distintos")
        url_horneada = fila["stack"]["url"]

        # ── 2 · ENTRAR LEVANTA ──────────────────────────────────────────────────────
        t0 = time.time()
        st, j = pedir(base + "/v1/workspaces/ciencia/enter", "POST", {})
        arranque = time.time() - t0
        ok(st == 200, "POST /enter contesta 200", f"({st}) en {arranque:.2f}s")
        if st != 200:
            print(json.dumps(j, ensure_ascii=False)[:400])
            return 1
        url_viva, pids_pack = j["url"], list(j["pids"])
        ok(bool(pids_pack) and all(vive(p) for p in pids_pack),
           "el proceso del pack está vivo", str(pids_pack))

        # ── 3 · EL PUERTO HORNEADO MURIÓ ────────────────────────────────────────────
        st, j2 = pedir(base + "/v1/workspaces")
        fila2 = next(w for w in j2["workspaces"] if w["id"] == "ciencia")
        reportada = url_horneada if CAER == "horneado" else fila2["stack"]["url"]
        ok(fila2["stack"]["running"] is True, "ahora el registro dice `running`")
        ok(reportada == url_viva,
           "la URL del registro es la del pack VIVO, no la horneada",
           f"registro={reportada} · pack={url_viva} · default={url_horneada}")
        cfg = json.loads((datos / "workspaces/ciencia/config/openscience.json").read_text())
        base_url = cfg["provider"]["aleph"]["options"]["baseURL"]
        ok(base_url.startswith(base),
           "el cerebro del stack apunta al puerto REAL de ESTE sidecar", base_url)
        ok(cfg["provider"]["aleph"]["options"]["headers"].get("X-Aleph-Workspace") == "ciencia",
           "la config generada declara de qué workspace viene el turno")
        modo = oct((datos / "workspaces/ciencia/config/openscience.json").stat().st_mode)[-3:]
        ok(modo == "600", "la config con el secreto adentro es 0600", modo)

        # ── 4 · IDEMPOTENTE ─────────────────────────────────────────────────────────
        st, j3 = pedir(base + "/v1/workspaces/ciencia/enter", "POST", {})
        ok(st == 200 and j3["url"] == url_viva,
           "entrar dos veces comparte el proceso, no levanta otro", j3.get("url", ""))
        ok(sorted(j3["pids"]) == sorted(pids_pack),
           "y son los MISMOS pids: no hay un segundo pack escondido")

        # ── 5 · LA GRACIA (el F5 no mata el kernel) ─────────────────────────────────
        st, jg = pedir(base + "/v1/workspaces/ciencia/leave", "POST", {})
        ok(st == 200 and jg["apagado"] is False and jg["gracia_s"] > 0,
           "salir sin pedir apagado literal arma la gracia", str(jg))
        time.sleep(1.0)
        ok(all(vive(p) for p in pids_pack),
           "dentro de la ventana el pack sigue vivo (una recarga no lo mata)")
        st, jv = pedir(base + "/v1/workspaces/ciencia/enter", "POST", {})
        ok(st == 200 and sorted(jv["pids"]) == sorted(pids_pack),
           "volver dentro de la ventana reusa el proceso caliente")

        # ── 6 · SALIR APAGA ─────────────────────────────────────────────────────────
        if CAER != "sin-apagar":
            st, jl = pedir(base + "/v1/workspaces/ciencia/leave", "POST", {"gracia_s": 0})
            ok(st == 200 and jl["apagado"] is True, "salir con gracia 0 apaga en el acto")
        time.sleep(1.5)
        vivos = [p for p in pids_pack if vive(p)]
        ok(not vivos, "CERO HUÉRFANOS: no queda un solo pid del pack", f"vivos={vivos}")
        st, j4 = pedir(base + "/v1/workspaces")
        fila4 = next(w for w in j4["workspaces"] if w["id"] == "ciencia")
        ok(fila4["stack"]["running"] is False, "y el registro vuelve a decir la verdad")

        # ── 7 · LAS CAUSAS, CON COPY ────────────────────────────────────────────────
        st, jx = pedir(base + "/v1/workspaces/no-existe/enter", "POST", {})
        ok(st == 404 and (jx or {}).get("detail", {}).get("error") == "workspace_desconocido",
           "un workspace que no existe da 404 tipado, no un 500 mudo")
        sys.path.insert(0, str(RAIZ / "platform"))
        sys.path.insert(0, str(RAIZ / "platform/inspection"))
        from workspaces import pack as ws_pack                # noqa: E402
        ok(ws_pack.binario_de({"bin": ["no/existe/nada"]}) is None,
           "sin binario declarado presente, `binario_de` dice None (no inventa una ruta)")
        try:
            ws_pack.levantar("ciencia", {"bin": ["no/existe/nada"]}, base_aleph=base)
            ok(False, "levantar sin binario tiene que fallar con causa")
        except ws_pack.PackError as e:
            ok(e.causa == "pack_no_instalado",
               "sin binario, la causa es `pack_no_instalado` (tipada, no un texto suelto)",
               e.causa)
    finally:
        for p in pids_pack:
            if vive(p):
                subprocess.run(["kill", "-9", str(p)], capture_output=True)
        try:
            os.killpg(os.getpgid(proc.pid), 15)
        except Exception:                                    # noqa: BLE001
            pass
        try:
            proc.wait(timeout=8)
        except Exception:                                    # noqa: BLE001
            try:
                os.killpg(os.getpgid(proc.pid), 9)
            except Exception:                                # noqa: BLE001
                pass
        shutil.rmtree(datos, ignore_errors=True)

    print(f"\n{'VERDE' if not fallos else 'ROJAS: ' + ', '.join(fallos)}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
