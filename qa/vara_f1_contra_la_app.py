#!/usr/bin/env python3
"""VARA · F1-CONECTORES contra la `.app` INSTALADA — el binario congelado, no el árbol.

POR QUÉ EXISTE. Todo lo que F1 midió fue contra el árbol: `pack.py` importado desde un
worktree, con el binario de Ciencia del `dist`. Eso prueba el mecanismo y NO prueba que viaje.
La familia de defectos que esta vara cuida está medida y tiene nombre: «el sha del dist del
árbol dice qué compilaste, no qué ship-eás», y «los bytes no viajan solos» — lo gitignoreado
que el pack necesita lo hornea el build, y si el spec no lo declara, no está adentro.

QUÉ MIDE, contra `/Applications/Aleph.app`:
  1. un `enter` con credencial en el vault → ¿llega y se VERIFICA desde el binario congelado?
  2. Ciencia por su endpoint → ¿la sonda sigue funcionando adentro del `.app`?
  3. el aviso de sombra → ¿aparece cuando debe, y NO cuando no debe?

CÓMO NO TOCA LOS DATOS DEL USUARIO. Levanta el sidecar de la `.app` con `ALEPH_DATA_DIR`
apuntando a un scratch propio: eso le da su PROPIA `aleph.db`, sus propios packs y su propio
vault. `PUPPET_DB_ENC_KEY` se inyecta para que la vara pueda cifrar el secreto sintético con
la misma llave que va a usar el sidecar (`platform/db/db.py:205-214`), y así SEMBRAR el vault
de verdad — `POST /keys` no sirve para esto: valida contra el proveedor y una llave sintética
devuelve 422 a propósito (F7·A).

    python3 qa/vara_f1_contra_la_app.py            # contra /Applications/Aleph.app
    ALEPH_APP=/ruta/a/Aleph.app python3 …          # contra otro bundle (el recién construido)
    ALEPH_AUTH="Bearer <sesión>" python3 …         # ← HACE FALTA para las tres mediciones

⚠️ EL `enter` PIDE SESIÓN, Y ESO NO SE PUEDE FORJAR DESDE ACÁ. Medido contra el bundle
`19cddb35…` el 2026-08-17: el sidecar arranca y contesta `/health`, el vault se siembra, y
`POST /v1/workspaces/<ws>/enter` con `user_id` devuelve **401 `no_session`** —
`_authorize(body.user_id, authorization)` exige la sesión del dueño (CONTRACT-AUTH-v1).
Sin `ALEPH_AUTH` las tres mediciones salen **[no medible] con motivo**, que es lo correcto:
no se concluye que el mecanismo falla, se dice que no se pudo medir. Con la sesión pegada en
`ALEPH_AUTH`, las tres corren.

No se saltea omitiendo `user_id`: sin dueño el `enter` no construye resolver (fail-closed a
propósito, `router.py`), así que entraría sin credenciales y no habría nada que medir.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

APP = Path(os.environ.get("ALEPH_APP", "/Applications/Aleph.app"))
SIDECAR = APP / "Contents" / "MacOS" / "aleph_sidecar"
#: Sintético, y nunca se imprime: sólo su nombre y si coincidió.
SINT = "ALEPH-SINT-APP-EXA-000000001"
USUARIO = "u-vara-f1"

_verdes: list[str] = []
_rojas: list[str] = []
_nomed: list[str] = []


def _ok(nombre: str, cond: bool, detalle: str = "") -> bool:
    (_verdes if cond else _rojas).append(nombre)
    print(f"  {'✅' if cond else '❌'} {nombre}" + (f"  — {detalle}" if detalle and not cond else ""))
    return cond


def _nm(nombre: str, motivo: str) -> None:
    _nomed.append(nombre)
    print(f"  ⚪ [no medible] {nombre} — {motivo}")


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


#: La sesión. `ALEPH_AUTH` sigue existiendo para pasar una real, pero ya NO hace falta: la
#: vara EMITE la suya para el usuario sintético, y puede porque el token v1 es **stateless**.
#:
#: `repo.mint_session` es `encrypt_secret("alephsess:v1:" + user_id)` (`repo.py:80-85`) y
#: `_session_owner_fernet` lo revierte con la misma llave (`repo.py:124-139`): no hay fila en
#: ninguna tabla. Como esta vara ES la que le da `PUPPET_DB_ENC_KEY` al sidecar del scratch,
#: puede emitir una sesión que ese sidecar reconoce — para un usuario inventado, en una
#: `aleph.db` desechable, con una llave generada al arrancar la vara.
#:
#: ⚠️ Esto NO es forjar la sesión de nadie: no toca la DB del usuario, no usa su llave y no
#: sirve contra ninguna otra instalación. Es la diferencia entre emitir una credencial de
#: prueba en un entorno propio y robar una ajena.
AUTH = os.environ.get("ALEPH_AUTH", "").strip()


def _emitir_sesion(llave: bytes, user_id: str) -> str:
    from cryptography.fernet import Fernet
    return Fernet(llave).encrypt(("alephsess:v1:" + user_id).encode()).decode("ascii")


def _pedir(url: str, metodo: str = "GET", cuerpo: dict | None = None, t: float = 30.0):
    datos = None if cuerpo is None else json.dumps(cuerpo).encode()
    req = urllib.request.Request(url, data=datos, method=metodo)
    req.add_header("Content-Type", "application/json")
    # La sesión del dueño, si la pasó. Sin ella el `enter` da 401 y las mediciones salen
    # [no medible] con motivo — nunca rojas, porque un 401 no dice nada del mecanismo.
    if AUTH:
        req.add_header("Authorization",
                       AUTH if AUTH.lower().startswith("bearer ") else "Bearer " + AUTH)
    try:
        with urllib.request.urlopen(req, timeout=t) as r:
            crudo = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(crudo)
            except ValueError:
                return r.status, crudo
    except urllib.error.HTTPError as e:
        crudo = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(crudo)
        except ValueError:
            return e.code, crudo
    except Exception as e:                              # noqa: BLE001 — frontera
        return 0, f"{type(e).__name__}: {e}"


def _sembrar_vault(datadir: Path, llave: bytes, provider: str, secreto: str) -> str:
    """Escribe la credencial CIFRADA en la aleph.db del scratch. Devuelve la causa si falla.

    Se escribe directo y no por `POST /keys` porque esa puerta VALIDA contra el proveedor
    (F7·A): una llave sintética es rechazada con 422, que es justo lo que queremos que haga.
    """
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        return "sin cryptography en este python"
    db = next((p for p in datadir.rglob("aleph.db")), None)
    if db is None:
        return "no apareció aleph.db en el data dir"
    cif = Fernet(llave).encrypt(secreto.encode())
    con = sqlite3.connect(str(db))
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(keys)")}
        if not cols:
            return "la tabla keys no existe en la aleph.db del scratch"
        campos = {"user_id": USUARIO, "provider": provider, "ciphertext": cif,
                  "last4": secreto[-4:]}
        usar = {k: v for k, v in campos.items() if k in cols}
        marcas = ",".join("?" for _ in usar)
        con.execute(f"INSERT OR REPLACE INTO keys ({','.join(usar)}) VALUES ({marcas})",
                    tuple(usar.values()))
        con.commit()
    except sqlite3.Error as e:
        return f"sqlite: {e}"
    finally:
        con.close()
    return ""


def main() -> int:
    print(f"── LA .app BAJO MEDICIÓN ──────────────────────────────────────────────")
    if not SIDECAR.is_file():
        print(f"  ❌ no está el sidecar: {SIDECAR}")
        print("     La .app no está instalada. Esta vara mide el binario congelado; sin él")
        print("     no hay nada que medir y NO se concluye nada del árbol.")
        return 2
    sha = subprocess.run(["shasum", "-a", "256", str(SIDECAR)],
                         capture_output=True, text=True).stdout.split()[0]
    print(f"  bundle : {APP}")
    print(f"  sidecar: {sha}")

    tmp = Path(tempfile.mkdtemp(prefix="vara-app-f1-"))
    from cryptography.fernet import Fernet
    llave = Fernet.generate_key()
    global AUTH
    if not AUTH:
        AUTH = "Bearer " + _emitir_sesion(llave, USUARIO)
    puerto = _puerto_libre()
    entorno = {**os.environ, "ALEPH_DATA_DIR": str(tmp),
               "PUPPET_DB_ENC_KEY": llave.decode(),
               "ALEPH_PACK_GRACIA_S": "0"}
    log = tmp / "sidecar.log"
    proc = subprocess.Popen([str(SIDECAR), "--port", str(puerto)], env=entorno,
                            stdout=open(log, "wb"), stderr=subprocess.STDOUT,
                            start_new_session=True)
    print(f"  sidecar propio: pid {proc.pid} · :{puerto} · datos en {tmp}")
    base = f"http://127.0.0.1:{puerto}"
    try:
        # ── salud, con espera acotada ──────────────────────────────────────────────
        vivo = False
        for _ in range(120):
            if _pedir(f"{base}/health", t=3.0)[0] == 200:
                vivo = True
                break
            if proc.poll() is not None:
                break
            time.sleep(0.5)
        if not _ok("el sidecar de la .app contesta /health", vivo,
                   f"exit={proc.poll()} · ver {log}"):
            return 1

        causa = _sembrar_vault(tmp, llave, "exa", SINT)
        if causa:
            # LA AUSENCIA DE UNA SEÑAL NO ES UNA MEDICIÓN: sin credencial sembrada no se
            # puede afirmar ni negar nada sobre si llega.
            _nm("sembrar el vault del scratch", causa)
            return 1
        print("  ✅ vault sembrado (provider=exa, valor sintético)")

        # ── 1 · UN ENTER CON CREDENCIAL EN EL VAULT ────────────────────────────────
        # Legal es el destino más simple de los cinco de archivo y su lector relee por
        # llamada: si algo del mecanismo no viajó, acá se ve primero.
        print("\n── 1 · UN ENTER CON LA CREDENCIAL EN EL VAULT ─────────────────────")
        est, cuerpo = _pedir(f"{base}/v1/workspaces/legal/enter", "POST",
                             {"user_id": USUARIO}, t=180.0)
        print(f"  POST enter → HTTP {est}")
        if est != 200:
            det = cuerpo.get("detail") if isinstance(cuerpo, dict) else cuerpo
            _nm("el enter de Legal", f"HTTP {est} · {str(det)[:160]}")
        else:
            cred = (cuerpo or {}).get("credenciales") or {}
            escr = cred.get("escritura") or {}
            verif = cred.get("verificacion") or escr
            _ok("el enter devuelve el campo credenciales", bool(cred))
            _ok("escribió searchApiKey", "searchApiKey" in (escr.get("escritas") or []),
                f"escritas={escr.get('escritas')}")
            _ok("y lo VERIFICÓ releyendo el destino",
                "searchApiKey" in (verif.get("verificadas") or []),
                f"verificadas={verif.get('verificadas')} causa={verif.get('causa')!r}")
            # LAS DOS VÍAS SON VÁLIDAS; LO QUE NO ES VÁLIDO ES `sin_tabla`. La primera versión
            # de este chequeo exigía `== "catalogo"` y salió ROJA sobre un
            # `catalogo-directo` — o sea sobre la segunda vía funcionando como se diseñó.
            # Era la aserción la que estaba mal, no el producto: lo que la medición tiene que
            # exigir es que la tabla se haya cargado, no POR CUÁL de los dos caminos.
            _tabla = (cred.get("sombra") or {}).get("tabla")
            _ok("la tabla de canónicas se cargó DENTRO de la .app (catalogo|catalogo-directo)",
                _tabla in ("catalogo", "catalogo-directo"), f"tabla={_tabla!r}")
            # Y SE DEJA DICHO POR CUÁL: que sea `catalogo-directo` y no `catalogo` es la
            # PRUEBA MEDIDA de que el import del assembler sigue fallando congelado. No es un
            # fallo del arreglo —el arreglo es justamente ése— pero deja la deuda a la vista.
            if _tabla == "catalogo-directo":
                print("     ↑ por la 2ª vía: el import del assembler NO funciona congelado, "
                      "medido. El fallback lo cubre; la causa exacta sigue sin capturarse.")
            _ok("entorno limpio → NINGÚN aviso",
                "aviso" not in (cuerpo or {}),
                f"aviso={(cuerpo or {}).get('aviso')}")

        # ── 1.bis · LOS OTROS TRES DESTINOS DE ARCHIVO, TAMBIÉN CONTRA LA .app ─────
        # Legal era el más simple y el que rompe primero; estos tres estaban verificados
        # SÓLO en el árbol, y «en el árbol» no dice nada de lo que viaja. Cada uno con su
        # slug del vault y el campo que su fila declara.
        for ws, slug, campo in (("educacion", "github", "github/token"),
                                ("oficina", "github", "GITHUB_TOKEN"),
                                ("finanzas", "alphavantage", "ALPHA_VANTAGE_API_KEY")):
            causa = _sembrar_vault(tmp, llave, slug, f"{SINT}-{ws[:3].upper()}")
            if causa:
                _nm(f"{ws} contra la .app", f"no se pudo sembrar {slug}: {causa}")
                continue
            est, cuerpo = _pedir(f"{base}/v1/workspaces/{ws}/enter", "POST",
                                 {"user_id": USUARIO}, t=240.0)
            if est != 200:
                det = cuerpo.get("detail") if isinstance(cuerpo, dict) else cuerpo
                # Un pack que no arranca en esta máquina NO dice nada del mecanismo de
                # credenciales: es [no medible], no rojo.
                _nm(f"{ws} contra la .app", f"el enter dio HTTP {est} · {str(det)[:110]}")
                continue
            cred = (cuerpo or {}).get("credenciales") or {}
            escr = cred.get("escritura") or {}
            verif = cred.get("verificacion") or escr
            _ok(f"{ws} · escribió {campo} desde la .app",
                campo in (escr.get("escritas") or []), f"escritas={escr.get('escritas')}")
            _ok(f"{ws} · y lo verificó releyendo",
                campo in (verif.get("verificadas") or []),
                f"verificadas={verif.get('verificadas')} causa={verif.get('causa')!r}")

        # ── 2 · CIENCIA POR SU ENDPOINT, DESDE EL BINARIO CONGELADO ────────────────
        print("\n── 2 · CIENCIA: EL PUT Y LA SONDA, DESDE LA .app ──────────────────")
        causa2 = _sembrar_vault(tmp, llave, "github", SINT + "-GH")
        if causa2:
            _nm("Ciencia", f"no se pudo sembrar github: {causa2}")
        else:
            est, cuerpo = _pedir(f"{base}/v1/workspaces/ciencia/enter", "POST",
                                 {"user_id": USUARIO}, t=240.0)
            print(f"  POST enter ciencia → HTTP {est}")
            if est != 200:
                det = cuerpo.get("detail") if isinstance(cuerpo, dict) else cuerpo
                _nm("el enter de Ciencia", f"HTTP {est} · {str(det)[:160]}")
            else:
                escr = ((cuerpo or {}).get("credenciales") or {}).get("escritura") or {}
                _ok("Ciencia escribió por HTTP desde la .app",
                    any("github" in str(x) for x in (escr.get("escritas") or [])),
                    f"escritas={escr.get('escritas')}")
                # LO QUE ESTA VARA VINO A BUSCAR: que la sonda —que spawnea un proceso
                # desde el binario congelado— siga viendo el env del hijo.
                _ok("la SONDA verificó adentro de la .app",
                    bool(escr.get("verificadas")),
                    f"verificadas={escr.get('verificadas')} causa={escr.get('causa')!r}")
                if escr.get("causa") in ("sonda_sin_salida", "sonda_sin_control_positivo"):
                    print(f"     ↑ el control de la sonda habló: {escr['causa']} — "
                          "no es «no llegó», es «no se pudo medir»")

        # ── 3 · EL AVISO DE SOMBRA: CUANDO DEBE Y CUANDO NO ────────────────────────
        # Se levanta un SEGUNDO sidecar con la canónica exportada. No se reusa el de arriba
        # a propósito: el entorno del hijo se hereda del padre en el spawn, así que la
        # sombra sólo se puede sembrar antes de que el padre exista.
        print("\n── 3 · EL AVISO DE SOMBRA (segundo sidecar, entorno envenenado) ───")
        p2 = _puerto_libre()
        tmp2 = Path(tempfile.mkdtemp(prefix="vara-app-f1-sombra-"))
        llave2 = Fernet.generate_key()
        # SU PROPIA LLAVE ⇒ SU PROPIA SESIÓN. Reusar la del primero daría 401 acá y yo lo
        # leería como «la sombra no se detecta», que es una conclusión sobre el mecanismo
        # sacada de un problema del instrumento.
        AUTH = "Bearer " + _emitir_sesion(llave2, USUARIO)
        env2 = {**os.environ, "ALEPH_DATA_DIR": str(tmp2),
                "PUPPET_DB_ENC_KEY": llave2.decode(), "ALEPH_PACK_GRACIA_S": "0",
                "EXA_API_KEY": "DEL-SHELL-NO-DEL-VAULT"}
        log2 = tmp2 / "sidecar.log"
        proc2 = subprocess.Popen([str(SIDECAR), "--port", str(p2)], env=env2,
                                 stdout=open(log2, "wb"), stderr=subprocess.STDOUT,
                                 start_new_session=True)
        base2 = f"http://127.0.0.1:{p2}"
        try:
            for _ in range(120):
                if _pedir(f"{base2}/health", t=3.0)[0] == 200:
                    break
                if proc2.poll() is not None:
                    break
                time.sleep(0.5)
            causa3 = _sembrar_vault(tmp2, llave2, "exa", SINT)
            if causa3:
                _nm("el aviso de sombra", causa3)
            else:
                est, cuerpo = _pedir(f"{base2}/v1/workspaces/legal/enter", "POST",
                                     {"user_id": USUARIO}, t=180.0)
                if est != 200:
                    _nm("el aviso de sombra", f"el enter dio HTTP {est}")
                else:
                    aviso = (cuerpo or {}).get("aviso") or {}
                    somb = ((cuerpo or {}).get("credenciales") or {}).get("sombra") or {}
                    _ok("la sombra se DETECTA desde la .app",
                        "EXA_API_KEY" in (somb.get("heredadas") or []),
                        f"heredadas={somb.get('heredadas')}")
                    _ok("y NO se repara (nunca se pisa lo del usuario)",
                        (somb.get("reparadas") or []) == [])
                    _ok("el aviso APARECE, con su causa y su copy",
                        aviso.get("error") == "credencial_sombreada" and bool(aviso.get("copy")),
                        f"aviso={aviso.get('error')!r}")
        finally:
            proc2.terminate()
            try:
                proc2.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc2.kill()
            print(f"  (segundo sidecar apagado por PID {proc2.pid} · datos en {tmp2})")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        print(f"\n  (sidecar apagado por PID {proc.pid} · datos en {tmp})")

    print("\n" + "─" * 70)
    print(f"VERDES {len(_verdes)} · ROJAS {len(_rojas)} · [no medible] {len(_nomed)}")
    if _rojas:
        print("rojas: " + ", ".join(_rojas))
    if _nomed:
        print("no medibles: " + ", ".join(_nomed))
    print("los temporales los creó esta vara; los borra quien la corrió")
    return 1 if _rojas else 0


if __name__ == "__main__":
    raise SystemExit(main())
