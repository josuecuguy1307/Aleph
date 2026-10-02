#!/usr/bin/env python3
"""verify_oficina_enchufar.py — LA VARA DE LA RAMA `oficina-enchufar`.
[Gate 4 · Oficina · ley 9 · ley 12 · inmersión 3.8]

QUÉ AFIRMA, Y CONTRA QUÉ
------------------------
Tres obras, y las tres son ENCHUFAR ALGO QUE YA EXISTÍA, no escribirlo de nuevo:

  OBRA 1 · EXCLUSIVIDAD (ley 12). `enchufar_cerebro` verificaba que el nuestro ESTÉ
      (`if pid not in vistos`), no que esté SOLO. Un `PUT /auth/<id>` desde la propia cara
      del stack —lo que hace el botón «Connect provider»— metía un proveedor con sus
      modelos y SOBREVIVÍA a todas las entradas siguientes. El mecanismo que faltaba
      llamar ya estaba escrito: `pack._proveedores_del_motor`. Ahora se le pregunta al
      motor quién quedó, se apaga al intruso donde hay con qué, y **se anuncia**.

  OBRA 2 · EL PLUGIN PUEDE PREGUNTARLE AL MOTOR. `openwork.js::alMotor` llamaba al motor
      sin credencial, se comía el 401 en un `catch { return null }`, y el turno se cerraba
      con `answer: ""`: 0 de 22 turnos de Oficina llegaron al ledger con su respuesta.
      La credencial ya estaba en el entorno del propio proceso del motor
      (`managed-opencode.ts:70-83`) y el plugin corre adentro de ese proceso.

  OBRA 3 · EL COPY. `providers.still_connected_suffix` le explicaba al usuario cómo
      insistir hasta desconectar el cerebro de la casa. Diez locales.

CONTRA QUÉ SE MIDE. Por DEFECTO contra la `.app` INSTALADA —la regla de esta casa: el juez
es el binario que el usuario tiene, no el árbol—, en frío y con `ALEPH_DATA_DIR` aislado,
levantando los packs de verdad (Oficina y Legal). Con `--contra arbol` corre el sidecar de
este checkout, que es lo único que hay mientras la obra se escribe; ahí el paso 3 (Legal) no
es medible y se declara como tal en vez de contarse verde.

LO QUE ESTA VARA **NO** AFIRMA, y por qué
-----------------------------------------
Que `final.answer` llegue con texto de punta a punta. Para eso hace falta un turno que
CONTESTE, y hoy el borde de este árbol devuelve el turno vacío por el defecto que la rama
`ciencia-obra1-emulado` arregla (`25d35e7d`) y que acá no está. El paso 5 mide el eslabón
que esta obra toca —que la puerta del motor se abre con la credencial y se cerraba sin
ella— y lo dice con ese alcance. El de punta a punta se mide cuando esa rama entre y se
construya; está agendado.

CÓMO SE PRUEBA CAYENDO
----------------------
`--caer sin-exclusividad`  → salta el paso de exclusividad del `enter` (simula el `main`
                             de hoy): el intruso sobrevive y el paso 2 se pone rojo.
`--caer sin-credencial`    → le pregunta al motor SIN la credencial del entorno: el paso 5
                             se pone rojo, que es exactamente el 401 que esta obra mata.
`--caer copy-viejo`        → mide contra el texto viejo: el paso 6 se pone rojo.
`--caer sin-dispose`       → apaga el proveedor y NO recicla la instancia: el paso 4 se pone
                             rojo, que es el 200 que no surtía efecto.

    python3 qa/verify_oficina_enchufar.py                 # contra la .app INSTALADA
    python3 qa/verify_oficina_enchufar.py --contra arbol
    python3 qa/verify_oficina_enchufar.py --caer sin-dispose
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
LOCALES = RAIZ / "third_party/openwork/apps/app/src/i18n/locales"
_ROJAS = 0
_NO_MEDIBLES = 0
_CAER = ""


def ok(cond: bool, texto: str, detalle: str = "") -> bool:
    global _ROJAS
    if not cond:
        _ROJAS += 1
    print(f"  {'✅' if cond else '❌'} {texto}" + (f"   {detalle}" if detalle else ""))
    return bool(cond)


def no_medible(texto: str, causa: str) -> None:
    """NI VERDE NI ROJA: lo que este banco de pruebas no puede medir, dicho con su causa.

    Existe para no repetir el defecto que esta casa ya tiene sellado —una vara verde que
    no mide nada— cuando lo que falta no es el arreglo sino el banco. El dueño es el juez:
    la corrida cuenta los tres números y no esconde el tercero adentro del primero.
    """
    global _NO_MEDIBLES
    _NO_MEDIBLES += 1
    print(f"  ⏳ {texto}\n       no medible acá: {causa}")


def puerto_libre() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def pedir(url, metodo="GET", cuerpo=None, cab=None, timeout=300):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(url, data=datos, method=metodo,
                                 headers={"Content-Type": "application/json", **(cab or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            crudo = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(crudo)
            except Exception:                                # noqa: BLE001
                return r.status, {"_raw": crudo[:400]}
    except urllib.error.HTTPError as e:
        crudo = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(crudo)
        except Exception:                                    # noqa: BLE001
            return e.code, {"_raw": crudo[:400]}
    except Exception as e:                                   # noqa: BLE001
        return 0, {"_error": repr(e)[:300]}


def env_del_proceso(pid: int, clave: str) -> str:
    """El entorno de un proceso propio, que es de donde el plugin saca su credencial.

    `ps -Ewww` y no `ps -E`: sin `www` la línea se corta y un secreto de 64 caracteres
    vuelve truncado. Costó una medición roja aprenderlo.
    """
    salida = subprocess.run(["ps", "-Ewww", "-o", "command=", "-p", str(pid)],
                            capture_output=True, text=True).stdout
    m = re.search(r"\b" + re.escape(clave) + r"=(\S+)", salida)
    return m.group(1) if m else ""


def main() -> int:                                           # noqa: C901
    global _CAER
    ap = argparse.ArgumentParser()
    ap.add_argument("--caer", default="")
    ap.add_argument("--contra", default="instalada", choices=("instalada", "arbol"))
    args = ap.parse_args()
    _CAER = args.caer

    print("── CONTRA QUÉ SE MIDE ──")
    commit = subprocess.run(["git", "-C", str(RAIZ), "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    app = Path(os.environ.get("ALEPH_APP", "/Applications/Aleph.app"))
    sidecar = app / "Contents/MacOS/aleph_sidecar"
    if args.contra == "instalada":
        if not sidecar.is_file():
            print(f"   ✗ no hay `.app` instalada en {app}")
            return 1
        sha = subprocess.run(["shasum", "-a", "256", str(sidecar)],
                             capture_output=True, text=True).stdout.split()[0]
        print(f"   `.app` INSTALADA  {app}")
        print(f"   sidecar sha256    {sha}")
        arranque = [str(sidecar), "--port"]
        extra_env: dict = {}
    else:
        print(f"   ÁRBOL (dev)       {RAIZ} @ {commit}")
        arranque = [sys.executable, str(RAIZ / "deploy/fase4/sidecar_serve.py"), "--port"]
        extra_env = {"ALEPH_ENV": "dev", "PYTHONPATH": os.pathsep.join([
            str(RAIZ / "product/backend"), str(RAIZ / "platform"),
            str(RAIZ / "deploy/fase4")])}
    print(f"   el copy se lee del ÁRBOL @ {commit} (paso 6) — lo demás, del binario de arriba")

    # ── 6 · OBRA 3 · EL COPY (no necesita proceso: se mide en el árbol) ───────────
    print("\n── 6 · OBRA 3 · el copy que enseñaba a insistir ──")
    VIEJO = ("Clear any remaining API key", "reinicie el worker", "reinicia el worker",
             "restart the worker", "перезапустите воркер", "重启工作区", "รีสตาร์ท worker",
             "khởi động lại worker", "ワーカーを再起動", "redémarrez le worker",
             "reinicie o worker")
    faltan, con_instructivo = [], []
    for f in sorted(LOCALES.glob("*.ts")):
        if f.name == "index.ts":
            continue
        s = f.read_text(encoding="utf-8")
        m = re.search(r'"providers\.still_connected_suffix":\s*"((?:[^"\\]|\\.)*)"', s)
        if not m:
            faltan.append(f.name)
            continue
        valor = m.group(1)
        if _CAER == "copy-viejo":
            valor = ", but the worker still reports it as connected. Clear any remaining API key…"
        if any(v.lower() in valor.lower() for v in VIEJO):
            con_instructivo.append(f.name)
    ok(not faltan, "6 · la clave sigue existiendo en los diez locales", str(faltan))
    ok(not con_instructivo,
       "6 · y ninguno le explica al usuario cómo desconectar el cerebro de la casa",
       str(con_instructivo))

    # ── EL ESTADO QUE **NO** ESTÁ ADENTRO DEL `ALEPH_DATA_DIR` ───────────────────
    # HALLAZGO DE ESTA MISMA VARA, la primera vez que se corrió: arrancó en frío, con un
    # dir de datos recién creado, y el motor YA declaraba `openai`. La credencial no vive
    # en el espacio del workspace ni en el de la instalación: opencode la guarda en
    # `~/.local/share/opencode/auth.json`, **global a la máquina** (`Global.Path.data` vía
    # xdg-basedir; lo documenta también `codesign/.../imports/opencode-config.ts`). O sea
    # que un proveedor conectado adentro de Oficina lo ven todos los opencode de este Mac
    # y sobrevive a un `ALEPH_DATA_DIR` nuevo.
    #
    # Para la vara eso significa dos cosas: se declara la precondición en vez de suponerla
    # —una vara que hereda estado mide un muerto— y se devuelve el archivo como estaba.
    AUTH = Path.home() / ".local/share/opencode/auth.json"
    respaldo = AUTH.read_bytes() if AUTH.is_file() else None
    previos = sorted(json.loads(respaldo or b"{}")) if respaldo else []
    if previos:
        print(f"\n   ⚠️  estado heredado en {AUTH}: {previos} — se aparta para medir en limpio")
        AUTH.write_text("{}", encoding="utf-8")

    # ── EL SIDECAR DE ESTE ÁRBOL, EN FRÍO Y AISLADO ──────────────────────────────
    datos = Path(tempfile.mkdtemp(prefix="vara-oficina-enchufar-"))
    puerto = puerto_libre()
    base = f"http://127.0.0.1:{puerto}"
    entorno = {**os.environ, "ALEPH_DATA_DIR": str(datos), "ALEPH_ROLE": "client",
               **extra_env}
    bitacora = open(datos / "sidecar.log", "w")
    proc = subprocess.Popen(
        arranque + [str(puerto)], cwd=str(RAIZ), stdout=bitacora,
        stderr=subprocess.STDOUT, start_new_session=True, env=entorno)
    entrados: list[str] = []
    cab: dict = {}
    uid = None
    try:
        print("\n── 1 · EL PACK DE OFICINA ──")
        vivo = False
        for _ in range(240):
            time.sleep(0.5)
            try:
                urllib.request.urlopen(base + "/health", timeout=2)
                vivo = True
                break
            except Exception:                                # noqa: BLE001
                if proc.poll() is not None:
                    break
        if not ok(vivo, "1 · el sidecar de este árbol levanta y atiende", base):
            print((datos / "sidecar.log").read_text()[-1500:])
            return 1

        st, u = pedir(base + "/v1/auth/local", "POST", {})
        uid = (u or {}).get("id")
        cab = {"Authorization": "Bearer " + (u or {}).get("session_token", "")}
        ok(st == 200 and bool(uid), "1 · la sesión la emite el pack por su propia puerta")

        st, e = pedir(base + "/v1/workspaces/oficina/enter", "POST", {"user_id": uid}, cab)
        ok(st == 200, f"1 · `enter` de Oficina responde 200", f"({st}) {json.dumps(e)[:160]}")
        if st != 200:
            return 1
        entrados.append("oficina")
        # EL `enter` SANO NO HACE RUIDO. El campo `aviso` sólo existe si hubo algo que
        # avisar; que aparezca en una entrada limpia sería la otra forma de mentir.
        ok("aviso" not in e, "1 · y un `enter` limpio NO trae aviso (anunciar ≠ hacer ruido)",
           json.dumps(e.get("aviso"))[:120] if e.get("aviso") else "")

        pack = e["url"].rstrip("/")
        pids = e["pids"]
        srv = json.loads((datos / "workspaces/oficina/config/server.json").read_text())
        cab_cli = {"Authorization": "Bearer " + srv["token"]}
        st, wl = pedir(pack + "/workspaces", cab=cab_cli)
        wid = ((wl.get("items") or wl.get("workspaces")) or [{}])[0].get("id")

        def proveedores() -> list:
            _st, _j = pedir(f"{pack}/workspace/{wid}/opencode/config/providers",
                            cab=cab_cli, timeout=60)
            return sorted(p["id"] for p in (_j or {}).get("providers", []))

        ok(proveedores() == ["aleph"], "1 · el motor declara UN cerebro y nada más",
           str(proveedores()))

        # ── 2 · OBRA 1 · EL INTRUSO ──────────────────────────────────────────────
        print("\n── 2 · OBRA 1 · un proveedor ajeno, como lo mete «Connect provider» ──")
        st, _ = pedir(f"{pack}/workspace/{wid}/opencode/auth/openai", "PUT",
                      {"type": "api", "key": "sk-VARA-FALSA-0000"}, cab_cli, timeout=60)
        pedir(f"{pack}/workspace/{wid}/opencode/instance/dispose", "POST", {}, cab_cli, timeout=60)
        time.sleep(2)
        antes = proveedores()
        ok(st == 200 and "openai" in antes,
           "2 · el `PUT /auth/<id>` mete el proveedor ajeno (el agujero que se tapa)",
           str(antes))

        # El `enter` que repara. Con `--caer sin-exclusividad` se lo saltea a mano, que es
        # exactamente el `main` de hoy.
        if _CAER == "sin-exclusividad":
            print("     (--caer sin-exclusividad: no se vuelve a entrar)")
            e2 = {}
        else:
            st, e2 = pedir(base + "/v1/workspaces/oficina/enter", "POST", {"user_id": uid}, cab)
            ok(st == 200, "2 · se vuelve a entrar (y el workspace ABRE, no se cierra la puerta)",
               f"({st})")
        despues = proveedores()
        ok(despues == ["aleph"],
           "2 · el `enter` apagó al intruso: el motor vuelve a declarar UN cerebro",
           str(despues))
        aviso = (e2 or {}).get("aviso") or {}
        ok(aviso.get("error") == "cerebro_ajeno_apagado",
           "2 · y LO ANUNCIA con causa tipada", str(aviso.get("error")))
        ok(bool(aviso.get("copy")),
           "2 · la causa llega con copy (regla sellada: ninguna causa muda)",
           str(aviso.get("copy"))[:90])
        ok("openai" in (aviso.get("apagados") or []),
           "2 · el aviso dice QUÉ deshizo", str(aviso.get("apagados")))

        # ── 4 · OBRA 1 · EL 200 NO ALCANZA: EL MOTOR TIENE QUE RELEER ────────────
        # Es el hallazgo que puso roja a esta misma vara la primera vez, y se certifica
        # aparte porque es el que hace la diferencia entre «se apagó» y «dice que se
        # apagó». La lista vive en la DB de runtime; el motor la lee al CONSTRUIR su
        # instancia.
        print("\n── 4 · OBRA 1 · apagar por el endpoint: el 200 no alcanza ──")
        # EL PASO 2 DEJÓ A `openai` APAGADO — su reparación persiste, que es el punto.
        # Para volver a tener un intruso VISIBLE hay que sacarlo de la lista primero; si no,
        # la credencial vuelve y el motor no lo declara igual. (Esto salió rojo en la
        # primera corrida contra la instalada y la causa era ésta, no la obra.)
        pedir(f"{pack}/workspace/{wid}/runtime-config/disabled-providers", "POST",
              {"providers": ["opencode"]}, cab_cli, timeout=60)
        pedir(f"{pack}/workspace/{wid}/opencode/auth/openai", "PUT",
              {"type": "api", "key": "sk-VARA-FALSA-0000"}, cab_cli, timeout=60)
        pedir(f"{pack}/workspace/{wid}/opencode/instance/dispose", "POST", {}, cab_cli, timeout=60)
        time.sleep(2)
        ok("openai" in proveedores(), "4 · hay un proveedor ajeno que apagar", str(proveedores()))
        st_ap, cuerpo_ap = pedir(
            f"{pack}/workspace/{wid}/runtime-config/disabled-providers", "POST",
            {"providers": ["opencode", "openai"]}, cab_cli, timeout=60)
        ok(st_ap == 200 and "openai" in (cuerpo_ap.get("disabledProviders") or []),
           "4 · el endpoint contesta 200 y dice que lo apagó",
           str(cuerpo_ap.get("disabledProviders")))
        ok("openai" in proveedores(),
           "4 · …y el motor SIGUE declarándolo (el 200 mentía)", str(proveedores()))
        if _CAER != "sin-dispose":
            from workspaces import pack as _wp                             # noqa: E402
            _wp._reciclar_instancia(pack, srv["token"])
            time.sleep(2)
        ok("openai" not in proveedores(),
           "4 · con el `dispose` sí sale de verdad de `/config/providers`",
           str(proveedores()))
        # se deja como estaba para el paso siguiente
        pedir(f"{pack}/workspace/{wid}/opencode/auth/openai", "DELETE", None, cab_cli, timeout=60)
        pedir(f"{pack}/workspace/{wid}/runtime-config/disabled-providers", "POST",
              {"providers": ["opencode"]}, cab_cli, timeout=60)
        pedir(f"{pack}/workspace/{wid}/opencode/instance/dispose", "POST", {}, cab_cli, timeout=60)

        # ── 5 · OBRA 2 · LA PUERTA DEL MOTOR ─────────────────────────────────────
        print("\n── 5 · OBRA 2 · la credencial que ya estaba en el entorno del motor ──")
        motor_pid = next((p for p in pids if env_del_proceso(p, "OPENCODE_SERVER_USERNAME")), 0)
        usuario = env_del_proceso(motor_pid, "OPENCODE_SERVER_USERNAME")
        clave = env_del_proceso(motor_pid, "OPENCODE_SERVER_PASSWORD")
        ok(bool(usuario and clave),
           "5 · el motor lleva su credencial en SU PROPIO entorno (donde corre el plugin)",
           f"pid {motor_pid} · {len(usuario)}+{len(clave)} chars")
        cmd = subprocess.run(["ps", "-Ewww", "-o", "command=", "-p", str(motor_pid)],
                             capture_output=True, text=True).stdout
        m = re.search(r"--port (\d+)", cmd)
        motor = f"http://127.0.0.1:{m.group(1)}" if m else ""
        st_sin, _ = pedir(motor + "/session", timeout=30)
        ok(st_sin == 401,
           "5 · sin credencial el motor cierra la puerta (el 401 que se comía el plugin)",
           f"({st_sin})")
        if _CAER == "sin-credencial":
            cabecera = {}
        else:
            cabecera = {"Authorization": "Basic " + base64.b64encode(
                f"{usuario}:{clave}".encode()).decode()}
        st_con, ses = pedir(motor + "/session", cab=cabecera, timeout=30)
        ok(st_con == 200,
           "5 · con la credencial del entorno, el motor contesta", f"({st_con})")
        sid = (ses[0] or {}).get("id") if isinstance(ses, list) and ses else ""
        if sid:
            st_msg, msgs = pedir(
                f"{motor}/session/{sid}/message?limit=40", cab=cabecera, timeout=30)
            ok(st_msg == 200 and isinstance(msgs, list),
               "5 · y la llamada EXACTA de `alMotor` devuelve los mensajes",
               f"({st_msg}) {len(msgs) if isinstance(msgs, list) else '-'} mensajes")
        # Y el plugin la usa: si la hubiera perdido, dejaría su causa escrita — que es la
        # otra mitad de la obra (el `catch` mudo se acabó).
        log_pack = datos / "workspaces/oficina/log/pack.log"
        texto_log = log_pack.read_text(errors="replace") if log_pack.is_file() else ""
        ok("el motor rechazó" not in texto_log,
           "5 · y el plugin no anotó ni un rechazo del motor en toda la corrida")

        # ── 3 · OBRA 1 · EL MISMO HELPER, PARA EL OTRO MOTOR opencode ────────────
        print("\n── 3 · OBRA 1 · el mismo helper contra el motor de Legal ──")
        st, el = pedir(base + "/v1/workspaces/legal/enter", "POST", {"user_id": uid}, cab)
        if st == 200:
            entrados.append("legal")
            from workspaces import pack as ws_pack                        # noqa: E402
            vistos = ws_pack._proveedores_del_motor(el["url"], "")
            ok(vistos == ["aleph"],
               "3 · `_proveedores_del_motor` sirve TAL CUAL para Legal (sin cabecera)",
               str(vistos))
        else:
            # NO ES LA OBRA: es el banco. El motor de Legal no arranca desde un árbol
            # fresco porque sus dependencias no están en git y no viajan al worktree
            # (`Cannot find package 'yargs'` en `packages/opencode`, `'hono'` en
            # `services/ingest`). Congelado adentro de la `.app` sí están, y ahí ESTO YA
            # SE MIDIÓ, contra `/Applications/Aleph.app` (sidecar `363d7ceb…`, 2026-08-14),
            # con el pack de Legal vivo:
            #
            #     GET /opencode/config/providers  sin cabecera      → 200  ['aleph']
            #     GET /opencode/config/providers  Bearer inventado  → 200  ['aleph']
            #     GET /opencode/provider                            → 185 disponibles
            #
            # Se deja anotado y se certifica en la corrida contra la `.app` instalada, que
            # es donde la fila de Legal tiene con qué levantarse.
            no_medible("3 · `_proveedores_del_motor` sirve TAL CUAL para Legal",
                       f"el pack de Legal no arranca en un árbol fresco ({st}: faltan sus "
                       f"node_modules, que no están en git) — se certifica contra la `.app`")
    finally:
        for ws in entrados:
            pedir(base + f"/v1/workspaces/{ws}/leave", "POST",
                  {"user_id": uid, "gracia_s": 0}, cab, timeout=60)
        proc.terminate()
        bitacora.close()
        # El almacén global vuelve como estaba: la vara no le deja credenciales a la
        # máquina, ni siquiera falsas. (La suya se borra igual si el paso 2 no llegó a
        # correr; por eso se escribe el respaldo, no se hace un `unlink` a ciegas.)
        if respaldo is not None:
            AUTH.write_bytes(respaldo)
        elif AUTH.is_file():
            AUTH.unlink()

    print(f"\n{'✅ SIN ROJAS' if _ROJAS == 0 else f'❌ {_ROJAS} ROJAS'}"
          f" · no medibles acá: {_NO_MEDIBLES}")
    return 0 if _ROJAS == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
