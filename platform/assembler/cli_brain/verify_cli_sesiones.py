#!/usr/bin/env python3
"""verify_cli_sesiones.py — LA VARA DE F2e (Gate 2 · sesiones del BYO-CLI).

Lo que esta vara exige que quede verde:

    dos turnos con `--resume` contra el CLI REAL → el segundo RECUERDA el primero, y lo
    prueba una pregunta cuya respuesta sólo existe en el turno anterior ·
    el segundo turno manda SÓLO lo nuevo (el ahorro, medido en caracteres) ·
    `--resume` de un id inexistente → causa TIPADA y vuelta rápida, jamás un cuelgue ·
    el índice encuentra una sesión recién creada SIN leer el transcript entero, y los
    bytes leídos se miden ·
    con la perilla apagada el argv vuelve a ser el de hoy, byte por byte ·
    las seis varas previas de Gate 2 siguen verdes.

POR QUÉ HAY UN STUB Y ADEMÁS EL CLI REAL: el stub sirve para lo que con el binario de
verdad no se puede forzar barato —un transcript de 2 MB para medir la lectura acotada, un
id que no existe— y el CLI real es el único que puede probar que el resume CONSERVA
CONTEXTO, que es la afirmación entera de la fase. Lo primero sin lo segundo no prueba nada.

La vara escribe sus sesiones en un temporal (`PUPPET_CLI_SESIONES_DIR`) y, al terminar,
borra los directorios que ELLA hizo aparecer en el store del CLI. No toca nada más de ahí:
el store es del CLI.

    product/backend/.venv/bin/python platform/assembler/cli_brain/verify_cli_sesiones.py
"""
from __future__ import annotations

import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
_ASM = _AQUI.parent
_RAIZ = _ASM.parents[1]
for _p in (str(_ASM), str(_RAIZ / "platform")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_TMP = Path(tempfile.mkdtemp(prefix="vara-f2e-"))
# ══ [F4d] EL WORKDIR DE LA VARA CALCA EL DE PRODUCCIÓN ═════════════════════════════
# Acá decía `_TMP / "sesiones"`, y ese descuido escondió un bug de producción una fase
# entera. `mkdtemp` da `/var/folders/…/vara-f2e-XXXX`: **sin espacios ni guiones bajos**,
# o sea el ÚNICO caso donde el `slug_de` viejo (que traducía sólo `/`) coincidía con lo
# que el CLI escribe de verdad. La vara salía verde midiendo el caso que funcionaba.
#
# El workdir REAL en macOS es `~/Library/Application Support/Aleph/cli_sesiones`, que
# tiene los DOS caracteres que rompían. Se calca acá:
#
#     "Application Support"  → el ESPACIO
#     "cli_sesiones"         → el GUIÓN BAJO
#
# Con esto, la vara vuelve a fallar si alguien revierte el fix — que es el único motivo
# por el que una vara existe.
_RAIZ_SESIONES = _TMP / "Application Support" / "Aleph" / "cli_sesiones"
os.environ["PUPPET_CLI_SESIONES_DIR"] = str(_RAIZ_SESIONES)
os.environ["PUPPET_CLI_PROCESOS"] = str(_TMP / "cli_procesos.jsonl")   # F2d, fuera del real

from cli_brain import base as B                       # noqa: E402
from cli_brain import detect as _detect               # noqa: E402
from cli_brain import sesiones as S                   # noqa: E402
from cli_brain import slots as SL                     # noqa: E402
from cli_brain.claude_cli import ClaudeCliProvider    # noqa: E402
from cli_brain.codex_cli import CodexCliProvider      # noqa: E402
from cli_brain.prompt_bridge import (render_prompt,   # noqa: E402
                                     render_prompt_incremental)
from cli_brain.server import create_server            # noqa: E402

sys.path.insert(0, str(_RAIZ / "qa" / "lib"))
import higiene_store as _HIG                          # noqa: E402

# [H1] El barrido por prefijo de `_TMP` (abajo, en el `finally`) cubre los workdir que
# esta vara elige. El que no cubría nadie es el `mkdtemp` que `base.invoke` abre cuando
# NO hay sesión: ése nace con OTRO prefijo y su espejo quedaba huérfano.
_HIG.vigilar()

_fallos = 0
_salteados = 0
#: slugs que ESTA vara hizo aparecer en el store del CLI; se limpian al final.
_ENSUCIADOS: set = set()


def ok(cond, nombre, detalle=""):
    global _fallos
    if cond:
        print(f"  ✓ {nombre}")
    else:
        _fallos += 1
        print(f"  ✗ {nombre}" + (f"  →  {detalle}" if detalle else ""))


def saltear(nombre, motivo):
    global _salteados
    _salteados += 1
    print(f"  ⊘ {nombre}  →  SALTEADO: {motivo}")


def seccion(t):
    print(f"\n── {t} " + "─" * max(0, 74 - len(t)))


def post(puerto, ruta, cuerpo, *, timeout=300):
    conn = http.client.HTTPConnection("127.0.0.1", puerto, timeout=timeout)
    conn.request("POST", ruta, json.dumps(cuerpo),
                 {"Content-Type": "application/json", "Host": f"127.0.0.1:{puerto}"})
    r = conn.getresponse()
    crudo = r.read().decode("utf-8", "replace")
    conn.close()
    try:
        return r.status, json.loads(crudo)
    except (json.JSONDecodeError, ValueError):
        return r.status, {"_crudo": crudo[:300]}


print("=" * 80)
print("VARA F2e · SESIONES DEL BYO-CLI · el multi-turno deja de re-pagar contexto")
print("=" * 80)

prov = ClaudeCliProvider()

try:
    # ══ 1 · EL ARGV ════════════════════════════════════════════════════════════════
    seccion("1 · el argv — `--session-id` la primera vez, `--resume` después")
    S.SESIONES.reiniciar()
    ses = S.SESIONES.obtener("charla-A", "claude_cli")
    ok(ses is not None and ses.fresca, "la primera vez la sesión nace FRESCA", str(ses))
    a1 = prov.build_argv("/bin/claude", "hola", "opus", ses.workdir, stream=True, sesion=ses)
    ok("--session-id" in a1 and a1[a1.index("--session-id") + 1] == ses.id,
       "turno 1 → `--session-id <uuid NUESTRO>` (el id lo elegimos nosotros)", str(a1[-8:]))
    ok("--no-session-persistence" not in a1,
       "y SIN `--no-session-persistence`: medido, con esa flag el resume siguiente falla")
    ses.turnos = 1
    a2 = prov.build_argv("/bin/claude", "hola", "opus", ses.workdir, stream=True, sesion=ses)
    ok("--resume" in a2 and a2[a2.index("--resume") + 1] == ses.id,
       "turno 2 → `--resume <el mismo uuid>`", str(a2[-8:]))
    ok("--session-id" not in a2, "y ya no `--session-id` (repetirlo da «already in use»)")

    a0 = prov.build_argv("/bin/claude", "hola", "opus", "/wd", stream=True, sesion=None)
    base_main = prov.build_argv("/bin/claude", "hola", "opus", "/wd", stream=True)
    ok(a0 == base_main and "--no-session-persistence" in a0,
       "SIN sesión el argv es el de hoy, byte por byte", str(a0 == base_main))

    ok(ses.renovar_id() != a1[a1.index("--session-id") + 1],
       "`renovar_id` da un uuid NUEVO (reciclar el viejo da «already in use»)")
    ok(ses.turnos == 0 and ses.enviados == 0,
       "y deja la sesión como recién nacida: el CLI nuevo no vio nada")

    # ══ 2 · EL AHORRO ══════════════════════════════════════════════════════════════
    seccion("2 · el prompt incremental — lo que se deja de re-pagar")
    msgs = [{"role": "system", "content": "Sos un agente útil."}]
    for i in range(6):
        msgs.append({"role": "user", "content": f"Pregunta número {i}: " + "x" * 400})
        msgs.append({"role": "assistant", "content": f"Respuesta número {i}: " + "y" * 400})
    msgs.append({"role": "user", "content": "Y ahora la última pregunta."})
    completo = render_prompt(msgs, [])
    incremental = render_prompt_incremental(msgs[-1:], [])
    ok(len(incremental) < len(completo) / 5,
       f"el incremental es {len(incremental)} chars contra {len(completo)} del completo "
       f"({100 - 100 * len(incremental) // len(completo)}% menos)",
       f"{len(incremental)} vs {len(completo)}")
    ok("Pregunta número 0" not in incremental,
       "y NO lleva la historia vieja: eso es lo que el CLI ya tiene")
    ok("Pregunta número 0" in completo, "que el completo sí lleva (si no, no probaría nada)")
    ok("<function=" in render_prompt_incremental(msgs[-1:], [
        {"function": {"name": "buscar", "description": "d", "parameters": {}}}]),
       "el catálogo de TOOLS sí se re-manda: no es historia, es la instrucción vigente")

    # ══ 3 · EL ÍNDICE ══════════════════════════════════════════════════════════════
    seccion("3 · índice, no copia — metadata sin leer el transcript entero")
    store = _TMP / "store-falso"
    cwd_falso = _TMP / "un-cwd"
    cwd_falso.mkdir(parents=True, exist_ok=True)
    slug = store / "projects" / S.slug_de(str(cwd_falso))
    slug.mkdir(parents=True, exist_ok=True)
    SID = str(uuid.uuid4())
    transcripto = slug / f"{SID}.jsonl"
    with open(transcripto, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "mode", "sessionId": SID}) + "\n")
        for i in range(4000):                       # ~2 MB de conversación
            fh.write(json.dumps({"type": "assistant", "sessionId": SID,
                                 "cwd": str(cwd_falso),
                                 "timestamp": "2026-08-03T18:00:00.000Z",
                                 "relleno": "z" * 480}) + "\n")
        fh.write(json.dumps({"type": "system", "sessionId": SID, "cwd": str(cwd_falso),
                             "timestamp": "2026-08-03T19:30:00.000Z"}) + "\n")
    tam = transcripto.stat().st_size
    ok(tam > 1_000_000, f"el transcript de prueba pesa {tam / 1e6:.1f} MB", str(tam))

    t0 = time.monotonic()
    filas = S.indice(cwd=str(cwd_falso), config_dir=str(store))
    dt = time.monotonic() - t0
    ok(len(filas) == 1 and filas[0]["sesion_id"] == SID,
       "el índice ENCUENTRA la sesión", str(filas)[:150])
    f = filas[0]
    ok(f["cwd"] == str(cwd_falso), "con el cwd que el CLI grabó", str(f["cwd"]))
    ok(f["ultimo_evento"] == "2026-08-03T19:30:00.000Z",
       "y el timestamp del ÚLTIMO evento", str(f["ultimo_evento"]))
    ok(f["bytes"] == tam, "reportando el tamaño real del archivo", str(f["bytes"]))
    ok(f["bytes_leidos"] <= S.COLA_BYTES,
       f"LEYENDO SÓLO {f['bytes_leidos']} bytes de {tam} ({100 * f['bytes_leidos'] // tam}% "
       f"del archivo) — índice, no copia", f"{f['bytes_leidos']} de {tam}")
    ok(dt < 1.0, f"y tardó {dt * 1000:.0f} ms", f"{dt:.3f}s")

    sin_mirar = S.indice(cwd=str(cwd_falso), config_dir=str(store), mirar_adentro=False)
    ok(sin_mirar[0]["bytes_leidos"] == 0 and sin_mirar[0]["sesion_id"] == SID,
       "con `mirar_adentro=False` son CERO bytes: el id y el cwd salen de las RUTAS",
       str(sin_mirar[0]))
    ok(S.sesion_mas_reciente(str(cwd_falso), config_dir=str(store)) == SID,
       "`sesion_mas_reciente` da el id sin abrir un archivo")

    ok(S.existe_sesion(SID, str(cwd_falso), config_dir=str(store)) is True,
       "`existe_sesion` dice que sí cuando está")
    ok(S.existe_sesion(str(uuid.uuid4()), str(cwd_falso), config_dir=str(store)) is False,
       "y que no cuando no — un `isfile`, sin spawnear nada para enterarse")

    # el realpath: sin él, el índice busca en un directorio que no existe
    enlace = _TMP / "enlace-al-cwd"
    if not enlace.exists():
        os.symlink(str(cwd_falso), str(enlace))
    ok(S.slug_de(str(enlace)) == S.slug_de(str(cwd_falso)),
       "`slug_de` RESUELVE el path: un symlink da el mismo slug (medido en macOS con "
       "/var → /private/var)", f"{S.slug_de(str(enlace))} vs {S.slug_de(str(cwd_falso))}")

    # ══ 4 · LA CAUSA TIPADA DEL RESUME PERDIDO ═════════════════════════════════════
    seccion("4 · resume de un id inexistente → causa tipada, sin cuelgue")
    c = S.causa_de_resume("id-que-no-esta")
    # F1c · CAMBIO DE VEREDICTO DECLARADO. Era `falla_de_aleph`, que es **la única causa
    # cuyo camino no es un arreglo del usuario sino [Copiar el reporte]**: le pedíamos un
    # reporte de bug por algo que se arregla solo. Y con él, `reintentable=False` — cuando
    # el reintento no es una esperanza sino lo que el server YA está haciendo.
    ok(c and c["causa"] == "sesion_perdida" and c["estado"] == "roto",
       "la causa es del vocabulario cerrado (`sesion_perdida`, F1c)", str(c)[:120])
    ok(c and c["causa"] != "falla_de_aleph",
       "y NO `falla_de_aleph`: esto no se arregla con [Copiar el reporte], se arregla solo")
    ok(c and c["evidencia"]["guard"] == "sesion_perdida",
       "y la evidencia dice EXACTAMENTE qué pasó (el `guard` se CONSERVA)",
       str(c and c["evidencia"]))
    ok(c and c["reintentable"] is True,
       "y ES reintentable: el server rehace el turno con contexto completo — reintentar "
       "no es una esperanza, es lo que ya está pasando")

    r = prov.parse_result(1, "", "No conversation found with session ID: abc-123", "/w", "opus")
    ok(r.ok is False and r.error_kind == B.ERR_SESION_PERDIDA,
       "el stderr medido del binario se clasifica como `sesion_perdida`…", str(r.error_kind))
    ok("rechazó" not in (r.error_detail or ""),
       "…y NO como «el CLI rechazó la solicitud», que era la mentira de antes",
       str(r.error_detail))
    ok((r.causa or {}).get("evidencia", {}).get("guard") == "sesion_perdida",
       "con la causa tipada adentro", str(r.causa)[:120])
    r2 = prov.parse_result(1, "", "Error: Session ID abc is already in use.", "/w", "opus")
    ok(r2.error_kind == B.ERR_SESION_PERDIDA,
       "y el otro mensaje medido («already in use») cae en el mismo lugar", str(r2.error_kind))

    # ══ 5 · LA PERILLA ═════════════════════════════════════════════════════════════
    seccion("5 · PUPPET_CLI_SESIONES=0 — el comportamiento de hoy, byte por byte")
    os.environ["PUPPET_CLI_SESIONES"] = "0"
    ok(S.activo() is False, "la perilla se lee en cada llamada")
    ok(S.SESIONES.obtener("charla-B", "claude_cli") is None,
       "con la perilla apagada NO se crea sesión, aunque venga la clave")
    os.environ["PUPPET_CLI_SESIONES"] = "1"
    ok(S.SESIONES.obtener("charla-B", "claude_cli") is not None,
       "y prendida vuelve a crearla")
    S.SESIONES.cerrar("charla-B")
    ok(S.SESIONES.obtener("", "claude_cli") is None,
       "sin CLAVE tampoco hay sesión: adivinar cuál es la charla sería contestar con el "
       "contexto de otra")

    # ══ 6 · codex — byte-idéntico, deuda declarada ═════════════════════════════════
    seccion("6 · codex — acepta `sesion` y la IGNORA (argv byte-idéntico)")
    cod = CodexCliProvider()
    s_cod = S.SESIONES.obtener("charla-codex", "codex_cli")
    c1 = cod.build_argv("/bin/codex", "hola", "m", "/wd", sesion=s_cod)
    c0 = cod.build_argv("/bin/codex", "hola", "m", "/wd")
    ok(c1 == c0, "el argv de codex no cambia ni un byte con sesión", str(c1 == c0))
    ok("--ephemeral" in c1, "y sigue con `--ephemeral` (su `--no-session-persistence`)")
    S.SESIONES.cerrar("charla-codex")

    # ══ 7 · EL CLI REAL: DOS TURNOS, Y EL SEGUNDO RECUERDA ═════════════════════════
    seccion("7 · CLI REAL — dos turnos con resume: el segundo RECUERDA el primero")
    srv = create_server(0)
    PUERTO = srv.server_port
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _guardado = dict(_detect._BY_MODEL_ID)
    try:
        if os.environ.get("SIN_CLI"):
            saltear("los dos turnos contra el CLI real", "SIN_CLI=1")
        elif not prov.binary():
            saltear("los dos turnos contra el CLI real", "`claude` no está instalado")
        elif prov.detect().state != B.STATE_READY:
            saltear("los dos turnos contra el CLI real", f"detect() = {prov.detect().state}")
        else:
            _detect._BY_MODEL_ID["claude-code-cli"] = prov
            os.environ["PUPPET_CLAUDE_CLI_MODEL"] = os.environ.get("VARA_CLI_MODELO", "haiku")
            SL.SLOTS.reiniciar()
            S.SESIONES.reiniciar()
            CLAVE = "vara-f2e-" + uuid.uuid4().hex[:8]
            CODIGO = "TALADRO-" + uuid.uuid4().hex[:6].upper()

            m1 = [{"role": "user",
                   "content": f"Guardá este código para después: {CODIGO}. "
                              f"Respondé solamente: OK"}]
            st1, c1r = post(PUERTO, "/v1/chat/completions",
                            {"model": "claude-code-cli", "sesion": CLAVE, "messages": m1})
            ok(st1 == 200, f"turno 1 sale bien (dio {st1})", str(c1r)[:180])
            ax1 = (c1r.get("aleph_cli_brain") or {}).get("sesion") or {}
            ok(ax1.get("turno") == 1 and ax1.get("incremental") is False,
               "el annex dice: turno 1, contexto COMPLETO", str(ax1))
            sid = ax1.get("id")
            ok(bool(sid), "y publica el id de sesión", str(sid))

            ses_viva = S.SESIONES.obtener(CLAVE, "claude_cli")
            _ENSUCIADOS.add(S.slug_de(ses_viva.workdir))
            ok(S.existe_sesion(sid, ses_viva.workdir),
               "EL CLI GUARDÓ la conversación: el índice la encuentra en su store",
               str(S.ruta_de_sesion(sid, ses_viva.workdir)))
            meta = S.indice(cwd=ses_viva.workdir)
            ok(meta and meta[0]["sesion_id"] == sid,
               "y el índice devuelve su metadata…", str(meta)[:160])
            if meta:
                ok(meta[0]["bytes_leidos"] <= S.COLA_BYTES,
                   f"…leyendo {meta[0]['bytes_leidos']} bytes de {meta[0]['bytes']}",
                   str(meta[0]["bytes_leidos"]))

            m2 = m1 + [{"role": "assistant", "content": "OK"},
                       {"role": "user",
                        "content": "¿Cuál era el código que te di? Respondé sólo el código."}]
            st2, c2r = post(PUERTO, "/v1/chat/completions",
                            {"model": "claude-code-cli", "sesion": CLAVE, "messages": m2})
            ok(st2 == 200, f"turno 2 sale bien (dio {st2})", str(c2r)[:180])
            texto = ((c2r.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            ax2 = (c2r.get("aleph_cli_brain") or {}).get("sesion") or {}
            ok(ax2.get("incremental") is True,
               "el annex dice que se mandó SÓLO lo nuevo", str(ax2))
            ok(ax2.get("id") == sid, "sobre la MISMA sesión", f"{ax2.get('id')} vs {sid}")
            ok(ax2.get("turno") == 2, "y que es el turno 2", str(ax2.get("turno")))
            ok(CODIGO in texto,
               f"→ EL SEGUNDO TURNO RECUERDA EL PRIMERO: contestó «{texto.strip()[:40]}» "
               f"y el código sólo existía en el turno 1",
               f"esperaba {CODIGO}, dijo {texto[:120]!r}")

            # ── el store borrado a mitad: se rehace, no se falla ──────────────────
            seccion("7b · si la conversación desaparece del store, el turno NO falla")
            ruta = S.ruta_de_sesion(ax2.get("id"), ses_viva.workdir)
            try:
                os.remove(ruta)
            except OSError:
                pass
            ok(not S.existe_sesion(ax2.get("id"), ses_viva.workdir),
               "se borró el transcript (es lo que pasa si el usuario limpia su store)")
            m3 = m2 + [{"role": "assistant", "content": CODIGO},
                       {"role": "user", "content": "Respondé solamente: LISTO"}]
            st3, c3r = post(PUERTO, "/v1/chat/completions",
                            {"model": "claude-code-cli", "sesion": CLAVE, "messages": m3})
            ok(st3 == 200, f"el turno SIGUIENTE igual sale bien (dio {st3})", str(c3r)[:200])
            ax3 = (c3r.get("aleph_cli_brain") or {}).get("sesion") or {}
            ok(ax3.get("id") != sid,
               "con una sesión NUEVA (la vieja ya no estaba)", f"{ax3.get('id')} vs {sid}")
            ok(ax3.get("incremental") is False,
               "y mandando el contexto COMPLETO — el ahorro se pierde, el turno no",
               str(ax3))
            _ENSUCIADOS.add(S.slug_de(ses_viva.workdir))

            # ── el resume perdido de verdad, contra el CLI ────────────────────────
            seccion("7c · `--resume` de un id inexistente contra el CLI real")
            falsa = S.SESIONES.obtener("vara-f2e-falsa-" + uuid.uuid4().hex[:6], "claude_cli")
            falsa.turnos = 1                    # miente: dice que ya hubo un turno
            _ENSUCIADOS.add(S.slug_de(falsa.workdir))
            t0 = time.monotonic()
            rr = prov.invoke("¿Hola?", sesion=falsa, timeout=120)
            dt = time.monotonic() - t0
            ok(rr.ok is False and rr.error_kind == B.ERR_SESION_PERDIDA,
               "el CLI real dice que esa conversación no está, y sale TIPADO",
               f"{rr.error_kind} · {rr.error_detail}")
            ok((rr.causa or {}).get("evidencia", {}).get("guard") == "sesion_perdida",
               "con la causa tipada", str(rr.causa)[:140])
            ok(dt < 30, f"y vuelve en {dt:.1f}s — no cuelga", f"{dt:.2f}s")

            # ── perilla apagada, de punta a punta ─────────────────────────────────
            seccion("7d · con la perilla apagada, el turno es el de hoy")
            os.environ["PUPPET_CLI_SESIONES"] = "0"
            S.SESIONES.reiniciar()
            st4, c4r = post(PUERTO, "/v1/chat/completions",
                            {"model": "claude-code-cli", "sesion": "no-importa",
                             "messages": [{"role": "user", "content":
                                           "Respondé solamente: OK"}]})
            ok(st4 == 200, f"el turno sale bien igual (dio {st4})", str(c4r)[:150])
            ok((c4r.get("aleph_cli_brain") or {}).get("sesion") is None,
               "y el annex dice que NO hubo sesión", str(c4r.get("aleph_cli_brain")))
            os.environ["PUPPET_CLI_SESIONES"] = "1"
    finally:
        _detect._BY_MODEL_ID.clear()
        _detect._BY_MODEL_ID.update(_guardado)
        SL.SLOTS.reiniciar()
        srv.shutdown()
        srv.server_close()
finally:
    os.environ["PUPPET_CLI_SESIONES"] = "1"
    S.SESIONES.reiniciar()
    # Lo que ESTA vara hizo aparecer en el store del CLI se limpia, y NADA MÁS: el criterio
    # es el prefijo del temporal propio, así que no hay forma de que se lleve puesta una
    # conversación del usuario. El store es del CLI y este módulo declara que sólo lo lee;
    # limpiar la basura que uno mismo generó es otra cosa que escribir en él.
    _PREFIJO = S.slug_de(str(_TMP))
    _raiz_store = S.raiz_del_store()
    try:
        _hay = os.listdir(_raiz_store)
    except OSError:
        _hay = []
    _limpiados = 0
    for _n in _hay:
        if _n.startswith(_PREFIJO):
            shutil.rmtree(os.path.join(_raiz_store, _n), ignore_errors=True)
            _limpiados += 1
    shutil.rmtree(_TMP, ignore_errors=True)
    print(f"\n[limpieza] {_limpiados} directorio(s) de esta vara borrados del store del CLI")

# ══ 8 · LAS VARAS PREVIAS SIGUEN VERDES ════════════════════════════════════════════
# `verify_tres_cables` entró a main mientras esta fase se escribía (los tres cables que
# F2d dejó propuestos). Se suma acá y no se ignora: cablear el barrido y el cierre al
# lifespan toca el mismo camino de `invoke` que F2e le cambió el workdir.
seccion("8 · las siete varas previas de Gate 2 siguen verdes")
for nombre, ruta in (("verify_traductor", _ASM / "verify_traductor.py"),
                     ("verify_cli_streaming", _AQUI / "verify_cli_streaming.py"),
                     ("verify_cli_slots", _AQUI / "verify_cli_slots.py"),
                     ("verify_cli_usage", _AQUI / "verify_cli_usage.py"),
                     ("verify_adaptador_litellm", _ASM / "verify_adaptador_litellm.py"),
                     ("verify_cli_stopturn", _AQUI / "verify_cli_stopturn.py"),
                     ("verify_tres_cables", _AQUI / "verify_tres_cables.py")):
    env = dict(os.environ)
    env.pop("PUPPET_CLAUDE_BIN", None)
    env.pop("PUPPET_CLI_SESIONES_DIR", None)
    env.pop("PUPPET_CLI_PROCESOS", None)
    if os.environ.get("SIN_CLI"):
        env["SIN_CLI"] = "1"
    r = subprocess.run([sys.executable, str(ruta)], capture_output=True, text=True,
                       timeout=3600, env=env)
    ok(r.returncode == 0, f"{nombre}.py sale con exit 0",
       (r.stdout or r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr) else "")

# [H4a] El cierre pasa por `qa/lib/veredicto.py`: con salteos declarados la última
# línea ya NO es el string pelado `TODO VERDE`. La regla vive en un solo lugar.
sys.path.insert(0, str(_RAIZ / "qa" / "lib"))
import veredicto as _V  # noqa: E402

print(f"\n{_V.texto(_fallos, _salteados)}")
sys.exit(0 if _fallos == 0 else 1)
