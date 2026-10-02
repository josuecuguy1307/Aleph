#!/usr/bin/env python3
"""verify_probar_por_familia.py — LA PUERTA DE VERIFICACIÓN SABE DE QUÉ VÍA HABLA.

    python3 qa/verify_probar_por_familia.py

──────────────────────────────────────────────────────────────────────────────────────────
EL DEFECTO, MEDIDO EN LA .APP INSTALADA (sidecar d7906120)

`POST /v1/modelos/probar` llamaba `probar_local(slug)` para TODO slug, sin mirar la familia.
Y `probar_local`, sin `tag` de ollama, sale por:

    estado: roto · causa: sin_runtime · «no hay runtime donde correrlo (no quedó
    registrado en ollama)»

…que para una API o un CLI no significa NADA. Las cuatro vías daban exactamente lo mismo:

    api.groq · api.openrouter · api.anthropic · cli.codex_cli  →  roto · sin_runtime

Y dos de ellas (openrouter, codex_cli) figuran `probado` y `conectado` en el pool, porque
ese estado lo escribe OTRO camino: la única puerta que la UI ofrece para «probar ahora»
contradecía al propio catálogo.

LA CONSECUENCIA NO ERA COSMÉTICA. Una vía de API con llave guardada queda en `detectado`
(«la tengo, no la probé») y **nunca podía pasar a `probado`**. Por eso `api.groq` tenía
llave en el vault y seguía fuera de `conectados`, y `preferencias.default` apuntaba a una
vía que no podía verificar jamás.

──────────────────────────────────────────────────────────────────────────────────────────
LO QUE ESTA VARA NO MIDE: si un proveedor tiene saldo. **Sin créditos, modelo de pago sin
saldo y llave inválida son estados de la CUENTA del usuario, no defectos de Aleph** (acta de
persona usuaria). Acá se mide que la puerta hable el idioma de cada vía; lo que el proveedor conteste
es otra pregunta, y tiene su propio vocabulario ya sellado (`sin_credito`, `key_invalida`).

EL DICCIONARIO NO SE TOCA. `sin_runtime` no está mal: estaba mal APLICADA.

Bloques:
  1 · cada familia se despacha por su camino     (+ el NEGATIVO: local sigue en sin_runtime)
  2 · el DISCRIMINANTE: un CLI responde como CLI, jamás como una API
  3 · sin llave se dice sin llave, no «sin runtime»
  4 · GUARD · ninguna causa fuera del vocabulario sellado, y cero jerga técnica en pantalla
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
sys.path.insert(0, str(RAIZ / "platform"))
sys.path.insert(0, str(RAIZ / "product" / "backend"))
sys.path.insert(0, str(RAIZ / "qa" / "lib"))
import arbol as _ARBOL                                    # noqa: E402

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


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _probar(puerto: int, slug: str, token: str) -> dict:
    req = urllib.request.Request(
        f"http://127.0.0.1:{puerto}/v1/modelos/probar",
        data=json.dumps({"slug": slug}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST")
    with urllib.request.urlopen(req, timeout=260) as r:
        return json.loads(r.read())


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="aleph-probar-"))
    datos = tmp / "datos"
    datos.mkdir(parents=True)
    os.environ.update({
        "ALEPH_ROLE": "client",
        "ALEPH_DATA_DIR": str(datos),
        "PUPPET_SQLITE_PATH": str(datos / "aleph.db"),
        "PUPPET_WORKERS": "0",
    })
    servidor = None
    try:
        from app.infra import db_boot
        db_boot.asegurar()
        from app.phase1 import repo
        conn = repo.get_conn()
        try:
            duena = repo.register_user(conn, email="probar@local.test",
                                       password="vara-2026", display_name="Vara")
            # UNA SOLA LLAVE, y de un proveedor de API. Es el caso índice: llave guardada,
            # vía que antes no podía verificar nunca. El valor es un literal de prueba —
            # jamás una llave real: lo que se mide es POR DÓNDE despacha la puerta, no si el
            # proveedor la acepta (eso es estado de la cuenta del usuario, no nuestro).
            repo.upsert_key(conn, user_id=duena["id"], provider="openrouter",
                            secret="sk-vara-no-sirve-0000")
        finally:
            conn.close()
        token = repo.mint_session(duena["id"])

        puerto = _puerto_libre()
        print("═" * 90)
        print("VARA · LA PUERTA DE VERIFICACIÓN SABE DE QUÉ VÍA HABLA")
        print(f"  fixture: {datos}   ·   puerto: {puerto}")
        print("═" * 90)
        # [H5b] `RAIZ / "product/backend/.venv/…"` afirmaba que la vara corre desde el
        # árbol PRINCIPAL: el venv es local y no viaja a un worktree. Medido el
        # 2026-08-08: verde en aleph-base, `FileNotFoundError` en gate3-higiene.
        servidor = subprocess.Popen(
            [_ARBOL.venv_python(RAIZ),
             str(RAIZ / "deploy/fase4/sidecar_serve.py"), "--port", str(puerto)],
            start_new_session=True, cwd=str(RAIZ),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=dict(os.environ, PYTHONPATH=os.pathsep.join(
                [str(RAIZ / "product/backend"), str(RAIZ / "platform")])))
        for _ in range(90):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/health", timeout=2):
                    break
            except Exception:  # noqa: BLE001
                time.sleep(1)
        else:
            no_medible("todo", "el sidecar no levantó")
            return 1

        from app.phase1 import motor_verdad as MV

        # ══ 1 · CADA FAMILIA POR SU CAMINO ═══════════════════════════════════════════
        r_api = _probar(puerto, "api.openrouter", token)
        ok("1_una_api_no_habla_de_ollama",
           r_api.get("causa") != "sin_runtime"
           and "ollama" not in str(r_api.get("detalle") or "").lower(),
           {"estado": r_api.get("estado"), "causa": r_api.get("causa"),
            "detalle": str(r_api.get("detalle"))[:70]})

        r_cli = _probar(puerto, "cli.claude_cli", token)
        ok("1_un_cli_no_habla_de_ollama",
           r_cli.get("causa") != "sin_runtime"
           and "ollama" not in str(r_cli.get("detalle") or "").lower(),
           {"estado": r_cli.get("estado"), "causa": r_cli.get("causa"),
            "detalle": str(r_cli.get("detalle"))[:70]})

        # ── EL NEGATIVO · un modelo LOCAL sin ollama SIGUE dando `sin_runtime`. Si esto
        #    rojea, el arreglo se llevó puesto el camino que sí estaba bien, y la causa
        #    perdió el único lugar donde es verdadera.
        r_loc = _probar(puerto, "local.ollama:no-existe-jamas", token)
        ok("1_negativo_un_local_sin_ollama_sigue_en_sin_runtime",
           r_loc.get("estado") == "roto" and r_loc.get("causa") == "sin_runtime",
           {"estado": r_loc.get("estado"), "causa": r_loc.get("causa")})

        # ══ 2 · EL DISCRIMINANTE ═════════════════════════════════════════════════════
        # Un CLI tiene que contestar con el vocabulario de un CLI, jamás con el de una API.
        # Sin este testigo, el bloque 1 se cumpliría con una puerta que manda TODO por el
        # carril de API: dejaría de hablar de ollama y seguiría mintiendo, sólo que en otro
        # idioma. Acá no hay CLIs instalados (fixture limpio), así que la respuesta honesta
        # es una causa DE CLI.
        causas_cli = {MV.CLI_NO_INSTALADO, MV.SIN_SESION, MV.CLI_INTERACTIVO_COLGADO}
        causas_api = {MV.KEY_INVALIDA, MV.SIN_CREDITO, MV.RATE_LIMIT, MV.FALTA_KEY}
        c_cli = r_cli.get("causa")
        ok("2_discriminante_un_cli_responde_como_cli",
           r_cli.get("estado") == "probado" or c_cli in causas_cli,
           {"causa": c_cli, "estado": r_cli.get("estado")})
        ok("2_discriminante_un_cli_jamas_responde_como_api",
           c_cli not in causas_api, {"causa": c_cli})

        # ══ 3 · SIN LLAVE SE DICE SIN LLAVE ══════════════════════════════════════════
        r_sin = _probar(puerto, "api.anthropic", token)
        ok("3_sin_llave_lo_dice_y_no_inventa_un_runtime",
           r_sin.get("causa") != "sin_runtime"
           and "llave" in str(r_sin.get("detalle") or "").lower(),
           {"estado": r_sin.get("estado"), "causa": r_sin.get("causa"),
            "detalle": str(r_sin.get("detalle"))[:70]})

        # ══ 4 · GUARD · EL VOCABULARIO Y LA PANTALLA ═════════════════════════════════
        todas = [r_api, r_cli, r_loc, r_sin]
        fuera = [r.get("causa") for r in todas
                 if r.get("causa") is not None and r.get("causa") not in MV.CAUSAS
                 and r.get("causa") != "sin_runtime"]
        ok("4_guard_ninguna_causa_fuera_del_vocabulario", not fuera, {"fuera": fuera})

        # ⚠️ NI UNA CAUSA TÉCNICA CRUDA EN EL DETALLE. El primer intento de este arreglo
        # ponía el `AttributeError` de Python ahí — y el detalle es lo que lee un humano.
        jerga = [str(r.get("detalle") or "") for r in todas
                 if any(p in str(r.get("detalle") or "")
                        for p in ("Traceback", "Error:", "AttributeError", "module '",
                                  "has no attribute", "Exception"))]
        ok("4_guard_cero_jerga_tecnica_en_el_detalle", not jerga, {"jerga": jerga[:2]})

        estados = {r.get("estado") for r in todas}
        ok("4_guard_no_todas_dicen_lo_mismo", len(estados) > 1,
           {"estados": sorted(str(e) for e in estados)})
    finally:
        if servidor is not None:
            try:
                os.killpg(os.getpgid(servidor.pid), 9)
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
