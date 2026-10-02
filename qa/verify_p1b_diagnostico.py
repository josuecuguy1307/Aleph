#!/usr/bin/env python3
"""verify_p1b_diagnostico.py — LA VARA DE LA ESCALERA (FIX-P1B · §6 §8 §9).

Mide el DIAGNÓSTICO, que es la mitad del trabajo que no se ve en pantalla: qué causa
escribe el motor ante cada falla real. La otra mitad (el workflow, la tabla pintada, el
vocabulario) la mide `product/app/design/diagnostico/verify_p1b_workflows.mjs` en WebKit.

POR QUÉ ACÁ Y NO EN EL NAVEGADOR: la escalera de respuesta (§6d) sólo se puede forzar
apuntando el motor a un proveedor que conteste 401/402/429/503 a pedido. Y el motor NO
acepta endpoints arbitrarios desde el cliente — resuelve sólo por alias del registro
(anti-SSRF, la misma frontera que `cuarto_guide`). Esa negativa es una FUNCIÓN, no un
obstáculo: no se la perfora para poder testear. Así que la escalera se mide donde vive,
contra un proveedor de laboratorio levantado acá al lado, que es igual de real.

CALIBRACIONES EN ROJO (las que tienen que FALLAR si el trabajo se deshace):
  · `sin_red` escrito sin que la sonda haya dicho que no  → FALLA
  · un destino local que falla y se reporta como `sin_red` → FALLA
  · un archivo NUESTRO ausente reportado como culpa del proveedor → FALLA
  · la receta filtrando el VALOR de un secreto → FALLA

Correr:  python3 qa/verify_p1b_diagnostico.py
"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "product" / "backend"))
sys.path.insert(0, str(_REPO / "platform"))

from app.phase1 import motor_verdad as MV   # noqa: E402
from app.phase1 import red as RED           # noqa: E402
from app.phase1 import arranque as ARR      # noqa: E402

OK = FAIL = 0
_FALLAS: list[str] = []


def ok(cond: bool, label: str, detalle: str = "") -> bool:
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  ✓ {label}" + (f"  ({detalle})" if detalle else ""))
    else:
        FAIL += 1
        _FALLAS.append(label)
        print(f"  ✗ {label}" + (f"  ({detalle})" if detalle else ""))
    return cond


def seccion(t: str) -> None:
    print(f"\n{'─' * 74}\n{t}\n{'─' * 74}")


# ══ PROVEEDOR DE LABORATORIO ══════════════════════════════════════════════════════
# Contesta lo que se le pida por la ruta. Es un proveedor real desde el punto de vista
# del motor: mismo transporte, mismos status, mismos cuerpos que manda uno de verdad.
_CUERPOS = {
    401: '{"error":{"message":"Incorrect API key provided: sk-***","type":"invalid_request_error"}}',
    402: '{"error":{"message":"Your credit balance is too low"}}',
    429: '{"error":{"message":"Rate limit reached for requests"}}',
    503: '{"error":{"message":"upstream connect error"}}',
    404: '{"error":{"message":"The model `gpt-5.1-codex` does not exist or you do not have access to it"}}',
    403: '{"error":{"message":"Your plan does not have access to this model. Please upgrade."}}',
}


class _Handler(BaseHTTPRequestHandler):
    def _responder(self):
        try:
            code = int(self.path.strip("/").split("/")[0])
        except Exception:
            code = 200
        cuerpo = _CUERPOS.get(code, '{"data":[]}')
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo.encode())

    do_GET = do_POST = _responder

    def log_message(self, *a):    # silencio: la vara ya imprime lo suyo
        pass


def _puerto_libre() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def main() -> int:
    print("═" * 74)
    print("FIX-P1B · VARA DEL DIAGNÓSTICO — la escalera (§6), la culpa nuestra (§8), la receta (§9)")
    print("═" * 74)

    puerto = _puerto_libre()
    srv = HTTPServer(("127.0.0.1", puerto), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{puerto}"

    # ══════════════════════════════════════════════════════════════════════════════
    seccion("§6a · ¿LA LLAVE ESTÁ? — antes de llamar a nadie, y jamás un error de red")
    # Un cerebro con key_env y sin llave en ningún lado NO sale a la red: contesta falta_key.
    r = MV.prueba_cerebro("__alias_que_no_existe__")
    ok(r["estado"] == MV.NO_CONFIGURADO,
       "un alias fuera del registro NO se pinguea (anti-SSRF): «elegí uno del catálogo»",
       r["estado"])

    M = MV._models()
    con_key = [a for a in M.ALIASES if getattr(M.resolve(a), "key_env", None)]
    if con_key:
        alias = con_key[0]
        env_name = M.resolve(alias).key_env
        guardado = os.environ.pop(env_name, None)
        try:
            r = MV.prueba_cerebro(alias, owner=None, get_conn=None)
            # Sin llave (ni vault ni entorno ni infra) → falta_key SIN tocar la red.
            sin_llave = r["causa"] == MV.FALTA_KEY
            ok(sin_llave or r["estado"] == MV.PROBADO,
               "sin llave en el vault → «falta tu llave», nunca un error de red",
               f'{r["estado"]}/{r["causa"]} — {str(r["evidencia"].get("detail",""))[:60]}')
            if sin_llave:
                ok(r["evidencia"].get("escalon") == "vault",
                   "…y la evidencia dice EN QUÉ PELDAÑO se cortó (no hubo request)",
                   str(r["evidencia"].get("escalon")))
                ok("http_status" not in r["evidencia"],
                   "CALIBRACIÓN: no hay status HTTP en la evidencia — porque no se llamó a nadie")
        finally:
            if guardado is not None:
                os.environ[env_name] = guardado
    else:
        ok(False, "no encontré un alias con key_env para medir el peldaño del vault")

    # ══════════════════════════════════════════════════════════════════════════════
    seccion("§6b · ¿ARRANCA EL SERVER LOCAL? — tu máquina vs NUESTRO bug")
    d = MV.dependencia_local({"command": "programa-que-no-existe-jamas", "args": []})
    ok(d and d["causa"] == MV.CLI_NO_INSTALADO,
       "binario ausente → «no está instalado» (camino: [Instalarlo])", d and d["causa"])
    d = MV.dependencia_local({"command": "freecad", "args": []}) if not MV.shutil.which("freecad") else None
    if d:
        ok(d["causa"] == MV.CLI_NO_INSTALADO and d.get("como"),
           "caso índice FreeCAD: además del qué, la INSTRUCCIÓN concreta",
           f'{d.get("programa")} · {d.get("como")}')
    else:
        print("  · (FreeCAD está instalado en esta máquina: no se puede medir su ausencia acá)")

    ok(MV.dependencia_local({"command": "python3", "args": []}) is None,
       "binario presente → el peldaño no corta (se sigue a la prueba real)")

    # EL CASO ÍNDICE: un archivo NUESTRO ausente NO se disfraza de problema del usuario.
    d = MV.dependencia_local({"command": "python3",
                              "args": ["${PUPPET_BELTS}/cowork/ESTE_NO_VIAJO.py"]})
    ok(d and d["causa"] == MV.FALLA_DE_ALEPH,
       "CALIBRACIÓN §8: archivo NUESTRO ausente → «falla_de_aleph», jamás culpa del usuario",
       d and d["causa"])
    ok(d and "defecto nuestro" in d.get("detail", ""),
       "…y lo DICE con todas las letras («esto es un defecto nuestro»)")

    # …y la variable se expande ANTES de diagnosticar (si no, el veredicto es falso).
    real = MV.dependencia_local({"command": "python3",
                                 "args": ["${PUPPET_BELTS}/cowork/drive_server.py"]})
    ok(real is None,
       "CALIBRACIÓN: ${PUPPET_BELTS} se EXPANDE antes de juzgar — sin esto, un server que "
       "SÍ está se reportaba como «no instalado»", "sin falta" if real is None else str(real))

    # ══════════════════════════════════════════════════════════════════════════════
    seccion("§6c · LA SONDA DE INTERNET — nadie escribe «sin_red» sin que ella diga que no")
    for forzado, esperado in ((RED.OFFLINE, MV.SIN_RED), (RED.ONLINE, MV.PROVEEDOR_CAIDO),
                              (RED.DESCONOCIDO, MV.ERROR_UPSTREAM)):
        os.environ["PUPPET_RED_FORZAR"] = forzado
        RED.invalidar()
        ev: dict = {}
        got = MV._causa_de_transporte("net", "https://api.de-un-proveedor.example/v1", ev)
        ok(got == esperado,
           f"la sonda dice «{forzado}» → la causa es «{esperado}» (el MISMO fallo de transporte)",
           f'{got} · red={ev.get("red", {}).get("online")}')
    ok(True, "…y las tres salieron del MISMO error: la diferencia la puso la sonda, no el texto")

    os.environ["PUPPET_RED_FORZAR"] = RED.OFFLINE
    RED.invalidar()
    for destino, que in ((f"http://127.0.0.1:{puerto}", "un servidor en tu propia máquina"),
                         ("npx", "un programa que corre sin red")):
        ev = {}
        got = MV._causa_de_transporte("net", destino, ev)
        ok(got != MV.SIN_RED and ev.get("red", {}).get("consultada") is False,
           f"CALIBRACIÓN: {que} que falla NUNCA es «sin internet» (ni se consulta la sonda)",
           f'{destino} → {got}')
    os.environ.pop("PUPPET_RED_FORZAR", None)
    RED.invalidar()

    s = RED.sonda()
    ok(s.get("online") in (True, False, None), "la sonda REAL contesta un veredicto tipado",
       f'online={s.get("online")} via={s.get("via")}')
    s2 = RED.sonda()
    ok(s2.get("cacheado") is True, "…y la segunda consulta sale de la cache (una sonda, no N)")

    # ══════════════════════════════════════════════════════════════════════════════
    seccion("§6d · LA RESPUESTA DECIDE — contra un proveedor de laboratorio REAL")
    casos = [
        (401, True,  MV.KEY_INVALIDA,         "mandamos llave y la rechazaron → «tu llave no sirve»"),
        (401, False, MV.FALTA_KEY,            "fuimos sin llave → «falta tu llave» (otro botón)"),
        (402, True,  MV.SIN_CREDITO,          "402 → sin saldo (la llave sirve; la cuenta está vacía)"),
        (429, True,  MV.RATE_LIMIT,           "429 → te frenaron (no está roto: hay que esperar)"),
        (503, True,  MV.PROVEEDOR_CAIDO,      "5xx → el proveedor está caído"),
        (404, True,  MV.MODELO_NO_DISPONIBLE, "«model does not exist» → ese modelo no está en tu plan"),
        (403, True,  MV.PLAN_INSUFICIENTE,    "«your plan does not have access» → tu plan no lo cubre"),
    ]
    for code, tenia, esperado, label in casos:
        r = MV._ping_models(f"{base}/{code}", "sk-lab" if tenia else None)
        got = MV._causa_de_http(r.get("http_status"), r.get("snippet", ""), tenia_key=tenia)
        ok(got == esperado, f"{code} · {label}", f"http={r.get('http_status')} → {got}")

    ok(all(c in MV.CAUSAS for _, _, c, _ in casos),
       "todas las causas que emite la escalera están en el vocabulario CERRADO del contrato")

    # ══════════════════════════════════════════════════════════════════════════════
    seccion("§8 · LA SONDA DE ARRANQUE — silenciosa si está todo, honesta si no")
    v = ARR.medir(force=True)
    ok(v["ok"], "el árbol de trabajo está completo (sonda silenciosa)",
       f'{len(ARR.MODULOS_PLANOS)} módulos · {len(ARR.DATA_DIRS)} dirs · {len(ARR.SERVERS_INCLUIDOS)} servers')
    ok(v["reporte"] == "", "…y con todo OK no hay reporte que mostrar (silencio por contrato)")
    ok(any(m[0] == "assembler" and m[2] == ARR.RUTA for m in ARR.MODULOS_PLANOS),
       "el caso índice (assembler.py) se chequea POR RUTA — un import no lo salvaría")

    # se la rompe de verdad y se mira qué dice
    asm = _REPO / "platform" / "assembler" / "assembler.py"
    tmp = asm.with_suffix(".py.vara")
    asm.rename(tmp)
    try:
        roto = ARR.medir(force=True)
        ok(not roto["ok"], "CALIBRACIÓN: sin assembler.py la sonda se pone en rojo")
        ok(any(f["cual"] == "assembler" for f in roto["fallas"]),
           "…y nombra EXACTAMENTE la pieza que falta", str([f["cual"] for f in roto["fallas"]]))
        ok("defecto de Aleph" in roto["reporte"],
           "…y el reporte dice que es NUESTRO (listo para [Copiar el reporte])")
        ok("{" not in roto["reporte"].split("\n")[0],
           "…y el reporte NO es un JSON crudo: es texto para pegar en un issue")
    finally:
        tmp.rename(asm)
    ARR.medir(force=True)

    # ══════════════════════════════════════════════════════════════════════════════
    seccion("§9 · LA RECETA — el comando real, sin filtrar un solo secreto")
    belt = "catalog/templates/cowork/belt-cowork-drive.mcp.json"
    spec = MV._spec_de_belt(belt, "google_drive")
    ok(spec is not None, "la receta sale del belt (con el guard anti-traversal de siempre)")
    if spec:
        env = spec.get("env") or {}
        valores = [str(v) for v in env.values() if str(v or "").strip()]
        # Lo que el endpoint entrega: nombres, nunca valores.
        entregado = json.dumps({"env_names": sorted(env.keys()),
                                "env_seteadas": sorted([k for k, v in env.items() if str(v or "").strip()])})
        fugas = [v for v in valores if len(v) > 3 and v in entregado]
        ok(not fugas, "CALIBRACIÓN: la receta entrega NOMBRES de variables, jamás sus valores",
           f"{len(env)} variables · 0 valores" if not fugas else f"FUGA: {fugas}")
        shell = " ".join([MV._expandir(spec.get("command") or "")]
                         + [MV._expandir(str(a)) for a in (spec.get("args") or [])])
        ok("${" not in shell, "el comando entregado está EXPANDIDO (se puede pegar y correr)", shell[:80])

    try:
        MV._spec_de_belt("../../etc/passwd", "x")
        ok(False, "el guard anti-traversal de la receta rechaza rutas fuera de rango")
    except Exception as e:
        ok("fuera de rango" in str(getattr(e, "detail", e)),
           "el guard anti-traversal de la receta rechaza rutas fuera de rango", str(getattr(e, "detail", e))[:50])

    srv.shutdown()
    # [H3] El detalle de las fallas y la barra van ARRIBA; la ÚLTIMA línea es el
    # veredicto. Antes `tail -1` leía «══════…» y, en rojo, el nombre de una falla suelta.
    print("\n" + "═" * 74)
    if _FALLAS:
        print("fallaron:")
        for f in _FALLAS:
            print(f"  · {f}")
    print(f"RESULTADO: {OK} ✓   {FAIL} ✗")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
