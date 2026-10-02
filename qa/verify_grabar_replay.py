#!/usr/bin/env python3
"""verify_grabar_replay.py — LA VARA DE S1 (`DISEÑO-SUITE-v1.md` §7).

Las cuatro que cierran la sesión, y ninguna se apoya en la palabra del código:

  A · grabar una pieza y replayarla **sin red y sin llaves** da el MISMO veredicto;
  B · una receta cambiada pone la grabación en **rojo** y dice cómo regrabar;
  C · **ninguna grabación contiene un secreto** — y se prueba con un server que imprime uno;
  D · las calibraciones ROJAS: sin perilla el grabador no existe · un paso no grabado falla
      cerrado en vez de inventar · replay no spawnea aunque el binario no exista.

    product/backend/.venv/bin/python qa/verify_grabar_replay.py

──────────────────────────────────────────────────────────────────────────────────────
POR QUÉ UN SERVER DE PRUEBA Y NO `fred` DIRECTAMENTE.

El §7 dice «grabar `fred` y replayarlo». `fred` es `npx -y mcp-remote https://…`: necesita
red, npx y el proveedor arriba. Grabarlo es exactamente para lo que sirve el grabador, y su
grabación va al repo aparte — pero una VARA que necesite todo eso no se corre en CI, que es
justamente el problema que S1 existe para resolver.

Así que la vara usa un server propio, determinista y con la MISMA forma de protocolo
(línea-JSON sobre stdio, el mismo molde que `product/belts/ingenieria/onshape_server.py`,
que ya se midió compatible con el puente al SDK real). Lo que se está certificando es el
MECANISMO —envolver, escribir, releer, comparar huellas, scrubbear—, y ese mecanismo no
distingue de quién es el server. La grabación de `fred` es el fixture; esto es la vara.

**SIN RED SE PRUEBA, NO SE PROMETE:** antes de replayar, el archivo del server se BORRA. Si
el replay tocara el camino vivo, no habría nada que ejecutar y reventaría. La receta no
cambia (la huella es sobre el comando y el env, no sobre el contenido del archivo), así que
el replay tiene que dar exactamente lo mismo.

**SIN LLAVES** tampoco es una promesa: se graba con la llave-basura que el verificador ya
usa (`BASURA`, `conexiones_verificador.py:45`). Ninguna credencial real entra en juego.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "platform"))
sys.path.insert(0, str(ROOT / "platform" / "inspection"))

import grabador as G                                       # noqa: E402
from inspection import transporte as TP                    # noqa: E402

#: La misma que el verificador manda cuando la llave no importa. NUNCA toca el llavero.
BASURA = "clave-falsa-de-prueba-0000"

#: Lo que el server de prueba va a imprimir por stderr y devolver en una tool. Si algo de
#: esto sobrevive en una grabación, la aserción C es roja — que es de lo que se trata.
SECRETO = "sk-live-AAAABBBBCCCCDDDDEEEEFFFF00001111"

FALLOS: list = []


def ok(cond, etiqueta, detalle=""):
    print(("  ✅ " if cond else "  ❌ ") + etiqueta + (f" · {detalle}" if detalle else ""))
    if not cond:
        FALLOS.append(etiqueta)
    return cond


# ── el server de prueba ─────────────────────────────────────────────────────────────────
_STUB = r'''#!/usr/bin/env python3
"""Server MCP mínimo y DETERMINISTA para la vara de S1. Imprime un secreto a propósito."""
import json, sys, os
SECRETO = os.environ.get("STUB_SECRETO", "")
# Un server que escupe su token al arrancar EXISTE, y es el caso que la aserción C cubre.
print("arrancando con token=" + SECRETO, file=sys.stderr, flush=True)
# Y el valor del env, TAL CUAL — es lo que `mcp-remote` hace con `--header` y lo que
# destapó que el scrubber solo no alcanza (la llave-basura no PARECE un secreto).
print("Using custom headers: {\"X-API-Key\":\"" + os.environ.get("PUPPET_FAKE_API_KEY","") + "\"}",
      file=sys.stderr, flush=True)
_TOOLS = [{"name": "eco", "description": "Devuelve lo que le mandan. Sólo lectura.",
           "inputSchema": {"type": "object", "properties": {"txt": {"type": "string"}},
                           "required": []}}]
def send(v):
    sys.stdout.write(json.dumps(v) + "\n"); sys.stdout.flush()
for raw in sys.stdin:
    try: req = json.loads(raw)
    except json.JSONDecodeError: continue
    if not isinstance(req, dict): continue
    m, i, p = req.get("method", ""), req.get("id"), req.get("params") or {}
    if m == "initialize":
        send({"jsonrpc": "2.0", "id": i, "result": {
            "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
            "serverInfo": {"name": "stub-s1", "version": "1.0.0"}}})
    elif m == "notifications/initialized":
        pass
    elif m == "tools/list":
        send({"jsonrpc": "2.0", "id": i, "result": {"tools": _TOOLS}})
    elif m == "tools/call":
        txt = (p.get("arguments") or {}).get("txt", "")
        # Devuelve el secreto TAMBIÉN en la respuesta: no alcanza con limpiar el stderr.
        send({"jsonrpc": "2.0", "id": i, "result": {
            "content": [{"type": "text",
                         "text": json.dumps({"ok": True, "eco": txt, "token": SECRETO})}],
            "isError": False}})
    elif i is not None:
        send({"jsonrpc": "2.0", "id": i,
              "error": {"code": -32601, "message": "Method not found: " + m}})
'''


def _veredicto(cls, command, args, env, cwd=None) -> dict:
    """Lo observable de una conexión: es la materia prima de un veredicto.

    (S2 es la que compara veredictos del diagnosticador sobre los 9 pasos; acá se compara
    lo que el transporte entrega, que es de donde salen.)
    """
    srv = cls("stub", command, args, env=env, cwd=cwd)
    try:
        arranco = bool(srv.start())
        tools = sorted(t.get("name") for t in (srv.list_tools() or []))
        r = srv.call_tool("eco", {"txt": "hola"})
        diag = srv.diagnostico() or {}
        return {"arranco": arranco, "tools": tools, "respuesta": r,
                "murio": bool(diag.get("murio")),
                "server_info": (diag.get("server_info") or {}).get("name")}
    finally:
        try:
            srv.stop()
        except Exception:                                  # noqa: BLE001
            pass


def _limpiar_perillas():
    for k in ("ALEPH_GRABAR", "ALEPH_REPLAY"):
        os.environ.pop(k, None)


def main() -> int:
    print("══ S1 · GRABAR / REPLAYAR ══")
    tmp = Path(tempfile.mkdtemp(prefix="aleph-s1-"))
    stub = tmp / "stub_server.py"
    stub.write_text(_STUB, encoding="utf-8")
    grabaciones = Path(G.__file__).resolve().parent / "grabaciones"
    slug = "vara-s1"
    destino = grabaciones / slug
    if destino.exists():
        shutil.rmtree(destino)

    command, args = sys.executable, [str(stub)]
    # La llave-basura y el secreto viajan en el env del hijo y mueren con él.
    env = {**os.environ, "PUPPET_FAKE_API_KEY": BASURA, "STUB_SECRETO": SECRETO}
    _limpiar_perillas()

    # ── D1 · sin perilla, el grabador no existe ───────────────────────────────────────
    print("\nD · calibraciones ROJAS")
    cls_pelada = TP.servidor_stdio()
    ok(not hasattr(cls_pelada, "envuelve"),
       "sin perilla la clase es la real, sin envoltorio", cls_pelada.__name__)

    # ── A · grabar ────────────────────────────────────────────────────────────────────
    print("\nA · grabar y replayar")
    os.environ["ALEPH_GRABAR"] = slug
    cls_grab = TP.servidor_stdio()
    ok(getattr(cls_grab, "envuelve", None) is not None,
       "con ALEPH_GRABAR la clase queda envuelta", cls_grab.__name__)
    vivo = _veredicto(cls_grab, command, args, env)
    _limpiar_perillas()
    archivos = sorted(p.name for p in destino.glob("*.json")) if destino.exists() else []
    ok(len(archivos) >= 3, "se escribió un JSON por paso", str(archivos))
    ok(vivo["tools"] == ["eco"], "el server vivo publicó su tool", str(vivo["tools"]))

    # ── SIN RED: se borra el server antes de replayar ─────────────────────────────────
    stub.unlink()
    ok(not stub.exists(), "el server de prueba fue BORRADO antes del replay")
    _limpiar_perillas()
    # El camino vivo NO lanza cuando falta el binario: DEGRADA, y lo dice
    # (`arranco=False · murio=True · "[MCP error: no response…]"`). Eso es mejor evidencia
    # que una excepción, porque da un veredicto ROTO comparable contra el sano del replay.
    roto = _veredicto(TP.servidor_stdio(), command, args, env)
    ok(roto["arranco"] is False and roto["murio"] is True and roto["tools"] == [],
       "sin el archivo, el camino VIVO da un veredicto ROTO",
       f"arranco={roto['arranco']} murio={roto['murio']}")

    os.environ["ALEPH_REPLAY"] = slug
    replay = _veredicto(TP.servidor_stdio(), command, args, env)
    _limpiar_perillas()

    ok(replay["arranco"] is True and replay["murio"] is False,
       "…y el REPLAY, con el binario igual de ausente, da el veredicto SANO",
       "prueba de que no está tocando el camino vivo")

    # ⚠️ «EL MISMO VEREDICTO» ES MÁS FUERTE QUE «LA MISMA RESPUESTA», y hay que decirlo con
    # precisión: la respuesta grabada NO puede ser byte-idéntica a la viva, porque la viva
    # traía el token del server y el scrubber lo neutralizó al grabar. Eso es lo correcto —
    # una grabación byte-idéntica sería una grabación con el secreto adentro. Lo que se
    # exige entonces es: todo lo que decide el veredicto, igual; el payload, intacto salvo
    # el secreto; y el secreto, neutralizado y no simplemente borrado (borrarlo dejaría un
    # JSON que ya no se parece a lo que el server contestó).
    ok(replay["tools"] == vivo["tools"]
       and replay["arranco"] == vivo["arranco"]
       and replay["murio"] == vivo["murio"]
       and replay["server_info"] == vivo["server_info"],
       "el replay da el MISMO veredicto, sin red y sin llaves",
       f"tools={replay['tools']} server_info={replay['server_info']}")
    ok(SECRETO in vivo["respuesta"] and SECRETO not in replay["respuesta"],
       "lo ÚNICO que cambia es el secreto: estaba en la respuesta viva y no en la grabada")
    ok("[valor-del-env-redactado]" in replay["respuesta"]
       or "[secreto removido]" in replay["respuesta"],
       "y fue NEUTRALIZADO, no borrado: la forma de la respuesta sobrevive",
       "gana la redacción por VALOR (determinista) sobre la del scrubber (heurística)")
    ok('"ok": true' in replay["respuesta"] and '"eco": "hola"' in replay["respuesta"],
       "el resto del payload llegó intacto al replay")

    # ── A2 · LA HUELLA TIENE QUE SOBREVIVIR AL CAMBIO DE PROCESO ──────────────────────
    # Esta es la aserción que faltaba y que costó dos grabaciones de `fred`. Una grabación
    # se compara SIEMPRE entre procesos distintos; si la huella incluye el env ambiente, el
    # `PATH` que `ensure_user_path()` muta en el primer spawn la parte y la grabación nace
    # inservible — con un rojo que además culpa a la receta, que no cambió.
    # Se simula el cambio de proceso moviendo justo lo que muta de verdad.
    print("\nA2 · la huella sobrevive al cambio de proceso")
    path_previo = os.environ.get("PATH", "")
    os.environ["PATH"] = "/un/directorio/que-no-estaba:" + path_previo
    os.environ["ALEPH_REPLAY"] = slug
    sobrevivio, motivo = True, ""
    try:
        _veredicto(TP.servidor_stdio(), command, args, {**env, "PATH": os.environ["PATH"]})
    except G.GrabacionVieja as e:
        sobrevivio, motivo = False, str(e).splitlines()[0]
    except Exception as e:                                 # noqa: BLE001
        sobrevivio, motivo = False, f"{type(e).__name__}: {e}"
    finally:
        os.environ["PATH"] = path_previo
        _limpiar_perillas()
    ok(sobrevivio, "cambiar el PATH del proceso NO invalida la grabación", motivo)

    # ── B · receta cambiada → rojo con el comando de regrabar ─────────────────────────
    # ⚠️ QUÉ ES «LA RECETA» Y QUÉ NO. La primera versión de esta aserción cambiaba una
    # env-var cualquiera y esperaba rojo. Estaba mal, y el arreglo de A2 lo destapó: el env
    # AMBIENTE no es la receta —si lo fuera, cambiar el PATH invalidaría toda grabación— y
    # por eso la huella se calcula sobre command+args+cwd más el env DECLARADO (§9.2).
    # Así que se prueban las dos formas legítimas de cambiar una receta.
    print("\nB · una receta cambiada pone la grabación en ROJO")

    def _rojo_por(etiqueta, **kw):
        os.environ["ALEPH_REPLAY"] = slug
        err = None
        try:
            _veredicto(TP.servidor_stdio(), kw.get("command", command),
                       kw.get("args", args), kw.get("env", env))
        except G.GrabacionVieja as e:
            err = str(e)
        except Exception as e:                             # noqa: BLE001
            err = f"(otra excepción) {type(e).__name__}: {e}"
        _limpiar_perillas()
        return err

    err = _rojo_por("args", args=args + ["--un-flag-nuevo"])
    ok(err is not None and "huella" in err,
       "cambiar los ARGS levanta GrabacionVieja")
    ok(err is not None and "ALEPH_GRABAR=" in err,
       "y dice el comando exacto para regrabar",
       (err or "").splitlines()[-1].strip() if err else "")

    # …y con el env DECLARADO (la marca `EnvDelHijo` que pone producción), cambiar una
    # variable de la receta también tiene que invalidar. Sin esto, S1 quedaría certificando
    # sólo la mitad del contrato de la huella.
    import dueno as _D
    env_decl = _D.EnvDelHijo(env, declaradas=("PUPPET_FAKE_API_KEY",))
    os.environ["ALEPH_GRABAR"] = slug + "-decl"
    _veredicto(TP.servidor_stdio(), command, args, env_decl)
    _limpiar_perillas()
    os.environ["ALEPH_REPLAY"] = slug + "-decl"
    err2 = None
    try:
        otro = _D.EnvDelHijo({**env, "PUPPET_FAKE_API_KEY": "otra-llave-distinta"},
                             declaradas=("PUPPET_FAKE_API_KEY",))
        _veredicto(TP.servidor_stdio(), command, args, otro)
    except G.GrabacionVieja as e:
        err2 = str(e)
    except Exception as e:                                 # noqa: BLE001
        err2 = f"(otra excepción) {type(e).__name__}: {e}"
    _limpiar_perillas()
    ok(err2 is not None and "huella" in err2,
       "con el env DECLARADO, cambiar una variable de la receta también invalida")
    shutil.rmtree(grabaciones / (slug + "-decl"), ignore_errors=True)

    # ── C · ninguna grabación contiene un secreto ─────────────────────────────────────
    print("\nC · el secreto NO viaja en la grabación")
    crudo = "\n".join(p.read_text(encoding="utf-8") for p in sorted(destino.glob("*.json")))
    ok(SECRETO not in crudo, "el secreto no aparece en ningún JSON grabado")
    ok(BASURA not in crudo,
       "el VALOR del env no viaja, aunque el server lo imprima por stderr",
       "el stub lo echa como hace mcp-remote con --header; lo caza la redacción por "
       "igualdad, no el scrubber")
    ok('"huella_receta"' in crudo, "pero la huella SÍ está (digest, no valor)")
    # Una grabación es un FIXTURE VERSIONADO: no puede llevar la disposición de la máquina
    # de quien la grabó. `diagnostico()["entorno"]` traía el PATH completo —home, miniconda,
    # macports— y eso iba al repo y ensuciaba el diff en cada regrabación.
    ok(all(json.loads(p.read_text(encoding="utf-8"))["diagnostico"].get("entorno", {})
           .get("omitido") for p in destino.glob("*.json")),
       "el ambiente de la máquina se omite, y se dice que se omitió")
    ok(str(Path.home()) not in crudo,
       "ninguna ruta del home del que grabó viaja en el fixture")

    hallazgos = sum(json.loads(p.read_text(encoding="utf-8"))
                    .get("scrubber", {}).get("hallazgos_neutralizados", 0)
                    for p in destino.glob("*.json"))
    ok(hallazgos > 0, "el scrubber neutralizó algo de verdad", f"{hallazgos} hallazgo(s)")

    # ── D2 · un paso no grabado falla CERRADO ────────────────────────────────────────
    print("\nD · (sigue)")
    os.environ["ALEPH_REPLAY"] = slug
    cerro = False
    try:
        srv = TP.servidor_stdio()("stub", command, args, env=env)
        srv.call_tool("una_tool_que_no_se_grabo", {})
    except G.GrabacionAusente:
        cerro = True
    except Exception:                                      # noqa: BLE001
        cerro = False
    _limpiar_perillas()
    ok(cerro, "un paso no grabado levanta GrabacionAusente en vez de inventar una respuesta")

    os.environ["ALEPH_REPLAY"] = "un-slug-que-no-existe"
    sin_carpeta = False
    try:
        TP.servidor_stdio()("stub", command, args, env=env)
    except G.GrabacionAusente:
        sin_carpeta = True
    except Exception:                                      # noqa: BLE001
        pass
    _limpiar_perillas()
    ok(sin_carpeta, "un slug sin grabaciones también falla cerrado")

    # limpieza: la grabación de la vara es efímera, no un fixture del repo
    shutil.rmtree(destino, ignore_errors=True)
    shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + ("══ ✅ S1 · GRABAR/REPLAYAR: TODO VERDE ══" if not FALLOS
                  else f"══ ❌ {len(FALLOS)} FALLO(S): {FALLOS} ══"))
    return 1 if FALLOS else 0


if __name__ == "__main__":
    sys.exit(main())
