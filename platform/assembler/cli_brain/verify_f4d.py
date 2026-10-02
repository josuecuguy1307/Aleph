#!/usr/bin/env python3
"""verify_f4d.py — LA VARA DE F4d (Gate 2 · EL SLUG QUE NO ENCONTRABA SUS SESIONES).

⚠️ **NO ANIDA VARAS** (regla sellada en F4a). El chequeo completo es UNA corrida de
`qa/correr_varas.py`.

EL BUG: `slug_de()` traducía **sólo `/`**; el CLI traduce **todo lo no alfanumérico**. El
workdir de Aleph en macOS —`~/Library/Application Support/Aleph/cli_sesiones`— tiene un
espacio Y un guión bajo, así que el slug calculado NO EXISTÍA en el disco:
`existe_sesion()` decía que no había sesión, el `--resume` no se intentaba nunca, y **cada
turno pagaba el contexto completo**.

Y sobrevivió a su propia vara porque F2e corría con `mkdtemp` bajo `/var/folders/…`:
**el único caso sin espacios ni guiones bajos**, o sea el único donde las dos reglas
coinciden. Por eso la mitad del trabajo de esta fase fue arreglar LA VARA.

    product/backend/.venv/bin/python platform/assembler/cli_brain/verify_f4d.py

`SIN_CLI=1` saltea lo que necesita el binario real.
"""
from __future__ import annotations

import http.client
import json
import os
import re
import shutil
import sys
import tempfile
import threading
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
_ASM = _AQUI.parent
_RAIZ = _ASM.parents[1]
for _p in (str(_ASM), str(_RAIZ / "platform"), str(_RAIZ / "product" / "backend")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# El workdir de la vara CALCA el de producción: espacio Y guión bajo. Es el punto entero.
_TMP = Path(tempfile.mkdtemp(prefix="vara-f4d-"))
os.environ["PUPPET_CLI_SESIONES_DIR"] = str(_TMP / "Application Support" / "Aleph" / "cli_sesiones")
os.environ["PUPPET_CLI_PROCESOS"] = str(_TMP / "cli_procesos.jsonl")

from cli_brain import sesiones as S                      # noqa: E402
from cli_brain.claude_cli import ClaudeCliProvider       # noqa: E402
from cli_brain.server import create_server               # noqa: E402

sys.path.insert(0, str(_RAIZ / "qa" / "lib"))
import higiene_store as _HIG                             # noqa: E402

# [H1] `_ENSUCIADOS` cubre los slugs que ESTA vara conoce (los workdir de sus sesiones).
# El que no conocía nadie es el `mkdtemp` que `base.invoke` abre cuando NO hay sesión:
# ése no pasa por acá y su espejo quedaba huérfano. `vigilar()` lo cubre.
_HIG.vigilar()

_fallos = 0
_salteados = 0
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


print("=" * 80)
print("VARA F4d · EL SLUG QUE NO ENCONTRABA SUS SESIONES")
print("=" * 80)

#: La regla VIEJA, para poder demostrar que la nueva no es un capricho.
_vieja = lambda p: os.path.realpath(os.path.expanduser(p)).replace("/", "-")  # noqa: E731


# ══════════════════════════════════════════════════════════════════════════════════
# 1 · LA REGLA, CONTRA EL STORE REAL DEL USUARIO
# ══════════════════════════════════════════════════════════════════════════════════
seccion("1 · la regla del CLI, medida contra el store REAL (no contra una suposición)")

_store = S.raiz_del_store()
_dirs = []
if os.path.isdir(_store):
    _dirs = [d for d in os.listdir(_store) if os.path.isdir(os.path.join(_store, d))]

if not _dirs:
    saltear("la regla contra el store real", "no hay store del CLI en esta máquina")
else:
    # (a) NINGÚN slug puede tener un carácter fuera de [A-Za-z0-9-]. Si el CLI conservara
    #     algo —un espacio, un punto, un guión bajo— acá se vería, y la regla sería otra.
    _fuera = [d for d in _dirs if re.search(r"[^A-Za-z0-9-]", d)]
    ok(not _fuera,
       f"los {len(_dirs)} directorios del store usan SÓLO [A-Za-z0-9-] → todo lo no "
       f"alfanumérico se traduce", str(_fuera[:3]))

    # (b) NO se colapsan separadores consecutivos. Los `--` salen de los `mkdtemp` cuyo
    #     sufijo aleatorio empieza con `_`. Si colapsáramos, esos directorios no se
    #     encontrarían nunca — o sea que la regla simple es la correcta, no la "prolija".
    _dobles = [d for d in _dirs if "--" in d]
    ok(bool(_dobles),
       f"hay {len(_dobles)} directorios con `--`: el CLI NO colapsa separadores "
       f"consecutivos, y por eso la regla es un `sub` carácter a carácter",
       str(_dobles[:1]))

    # (c) LA PRUEBA FUERTE: paths que EXISTEN hoy → la regla predice un dir que está.
    _cands = []
    for _base in (os.path.expanduser("~"), os.path.expanduser("~/Desktop")):
        try:
            _cands += [os.path.join(_base, n) for n in os.listdir(_base)
                       if os.path.isdir(os.path.join(_base, n))]
        except OSError:
            pass
    _set = set(_dirs)
    _hits = [p for p in _cands if S.slug_de(p) in _set]
    ok(bool(_hits),
       f"de {len(_cands)} paths reales del disco, {len(_hits)} tienen sesión y la regla "
       f"NUEVA acierta el directorio de todos")
    # …y de esos, los que tienen caracteres que la regla VIEJA no traducía
    _rotos_antes = [p for p in _hits if _vieja(p) != S.slug_de(p)]
    ok(bool(_rotos_antes),
       f"y {len(_rotos_antes)} de ellos FALLABAN con la regla vieja (tienen espacio u otro "
       f"carácter no alfanumérico)",
       str([os.path.basename(p) for p in _rotos_antes[:3]]))
    for _p in _rotos_antes[:3]:
        ok(S.slug_de(_p) in _set and _vieja(_p) not in _set,
           f"    · {os.path.basename(_p)}: la nueva acierta, la vieja apunta a un "
           f"directorio que no existe")


# ══════════════════════════════════════════════════════════════════════════════════
# 2 · EL WORKDIR DE PRODUCCIÓN — el caso que rompía
# ══════════════════════════════════════════════════════════════════════════════════
seccion("2 · el workdir REAL de producción (espacio Y guión bajo)")

_PROD = "/Users/x/Library/Application Support/Aleph/cli_sesiones/abc123"
ok(S.slug_de(_PROD).endswith("-Application-Support-Aleph-cli-sesiones-abc123"),
   "el workdir de macOS se traduce entero: «Application Support» → `-Application-Support-` "
   "y `cli_sesiones` → `cli-sesiones`", S.slug_de(_PROD)[-52:])
ok(" " not in S.slug_de(_PROD) and "_" not in S.slug_de(_PROD),
   "…sin dejar NI un espacio NI un guión bajo — que era el bug entero")
ok(_vieja(_PROD) != S.slug_de(_PROD),
   "y la regla vieja daba OTRA cosa (por eso `existe_sesion` no encontraba nada)",
   _vieja(_PROD)[-52:])

# el workdir que esta vara usa es el calcado: si alguien lo "limpia", esto se pone rojo
_raiz_vara = S.SESIONES.raiz
ok(" " in _raiz_vara and "_" in _raiz_vara,
   "★ el workdir DE ESTA VARA tiene espacio Y guión bajo — es lo que F2e no tenía, y por "
   "eso su vara salía verde sobre el único caso que funcionaba", _raiz_vara[-46:])


# ══════════════════════════════════════════════════════════════════════════════════
# 3 · LOS CONSUMIDORES — una sola regla, un solo lugar
# ══════════════════════════════════════════════════════════════════════════════════
seccion("3 · los consumidores heredan la regla, y la copia de F4b se unificó")

_wd = os.path.join(S.SESIONES.raiz, "deadbeef")
ok(S.slug_de(_wd) in S.ruta_de_sesion("S1", _wd),
   "`ruta_de_sesion` usa la regla nueva")
ok(S.slug_de(_wd) in str(S.ruta_de_sesion("S1", _wd)),
   "`existe_sesion` busca en el directorio correcto (mismo `ruta_de_sesion`)")

_fuente = (_AQUI / "sesiones.py").read_text(encoding="utf-8")
# La regla vieja SIGUE apareciendo en el archivo — dentro del docstring que documenta
# el bug. Eso es memoria; lo que no puede haber es una línea EJECUTABLE con ella.
_vivas = [l for l in _fuente.splitlines()
          if '.replace("/", "-")' in l and not l.lstrip().startswith("#")
          and not l.lstrip().startswith('"""') and "return" in l]
ok('_NO_ALFANUM.sub("-"' in _fuente and not _vivas,
   "la regla nueva es la que corre, y la vieja quedó SÓLO citada en el docstring",
   str(_vivas[:1]))

# la copia que F4b tuvo que hacer en el backend ahora consume ésta
from app.phase1 import transcripts_cli as T             # noqa: E402
ok(T._slug_real(_PROD) == S.slug_de(_PROD),
   "★ la derivación propia que F4b declaró en el backend quedó UNIFICADA contra ésta: "
   "una sola regla, un solo lugar", f"{T._slug_real(_PROD)[-40:]} vs {S.slug_de(_PROD)[-40:]}")
_tfuente = (_RAIZ / "product/backend/app/phase1/transcripts_cli.py").read_text(encoding="utf-8")
ok("_NO_ALFANUM" not in _tfuente,
   "…y la copia de la regex desapareció del backend (no quedaron dos reglas)")


# ══════════════════════════════════════════════════════════════════════════════════
# 4 · END-TO-END CON EL CLI REAL + EL AHORRO MEDIDO
# ══════════════════════════════════════════════════════════════════════════════════
seccion("4 · CLI real: el turno 2 RECUERDA, y cuánto se deja de mandar")

_prov = ClaudeCliProvider()
if os.environ.get("SIN_CLI"):
    saltear("el end-to-end contra el CLI real", "SIN_CLI=1")
elif not _prov.binary():
    saltear("el end-to-end contra el CLI real", "no hay binario `claude` en esta máquina")
else:
    _srv = create_server(0)
    _P = _srv.server_port
    threading.Thread(target=_srv.serve_forever, daemon=True).start()

    def _post(cuerpo, timeout=300):
        c = http.client.HTTPConnection("127.0.0.1", _P, timeout=timeout)
        c.request("POST", "/v1/chat/completions", json.dumps(cuerpo),
                  {"Content-Type": "application/json", "Host": f"127.0.0.1:{_P}"})
        r = c.getresponse()
        d = r.read().decode("utf-8", "replace")
        c.close()
        return r.status, (json.loads(d) if d.strip().startswith("{") else d)

    # Historial REALISTA. Con tres mensajes cortos el ahorro no se ve (F2e lo midió sobre
    # 5.362 chars): una conversación de verdad tiene volumen, y es ahí donde el `--resume`
    # deja de re-pagar.
    _PAR = ("Necesito un informe sobre el consumo energético de los centros de datos, "
            "con foco en refrigeración por inmersión y su impacto en el PUE. ")
    _HIST = []
    for _i in range(3):
        _HIST.append({"role": "user", "content": _PAR * 4 + f"(punto {_i + 1})"})
        _HIST.append({"role": "assistant", "content": "Anotado. " + _PAR * 3 + f"[r{_i + 1}]"})
    _SEC = "ZORZAL-F4D-8842"
    _HIST.append({"role": "user",
                  "content": f"Guardá este código exactamente: {_SEC}. Respondé sólo: OK"})
    _CLAVE = "vara-f4d"

    _st1, _c1 = _post({"model": "claude-code-cli", "sesion": _CLAVE, "messages": _HIST})
    ok(_st1 == 200, f"turno 1 sale bien (dio {_st1})", str(_c1)[:140])
    _ax1 = ((_c1 or {}).get("aleph_cli_brain") or {}).get("sesion") or {}
    ok(_ax1.get("turno") == 1 and _ax1.get("incremental") is False,
       "el annex dice: turno 1, contexto COMPLETO", str(_ax1))
    _sid = _ax1.get("id")

    _ses = S.SESIONES.obtener(_CLAVE, "claude_cli")
    if _ses:
        _ENSUCIADOS.add(S.slug_de(_ses.workdir))
    # ★ LA ASERCIÓN QUE FALLABA ANTES DEL FIX
    ok(bool(_sid) and _ses is not None and S.existe_sesion(_sid, _ses.workdir),
       "★ EL CLI GUARDÓ la conversación Y LA ENCONTRAMOS — con la regla vieja este "
       "`existe_sesion` daba False y el resume no se intentaba nunca",
       str(S.ruta_de_sesion(_sid or "", _ses.workdir if _ses else ""))[-70:])

    _t1 = ((_c1.get("choices") or [{}])[0].get("message") or {}).get("content", "")
    _h2 = _HIST + [{"role": "assistant", "content": _t1},
                   {"role": "user", "content": "¿Cuál era el código? Respondé sólo el código."}]
    _st2, _c2 = _post({"model": "claude-code-cli", "sesion": _CLAVE, "messages": _h2})
    _ax2 = ((_c2 or {}).get("aleph_cli_brain") or {}).get("sesion") or {}
    _t2 = ((_c2.get("choices") or [{}])[0].get("message") or {}).get("content", "")

    ok(_ax2.get("turno") == 2 and _ax2.get("incremental") is True,
       "el turno 2 va INCREMENTAL (o sea: resumió, no arrancó de cero)", str(_ax2))
    ok(_ax2.get("rehecha") is False or not _ax2.get("rehecha"),
       "…y NO tuvo que rehacerse: la sesión estaba donde dijimos que estaría")
    ok(_SEC in (_t2 or ""),
       f"★ EL TALADRO: el turno 2 RECUERDA el código del turno 1 ({_SEC})",
       (_t2 or "")[:70].replace("\n", " "))

    # ── EL AHORRO, MEDIDO ─────────────────────────────────────────────────────────
    # ⚠️ DOS NOTAS QUE COSTARON UNA MEDICIÓN MAL HECHA CADA UNA:
    #
    # 1. **NO se ve en `usage.prompt_tokens`.** Medido: el CLI reporta `2` en los DOS
    #    turnos, porque el grueso del input entra por su cache. Buscar el ahorro ahí es
    #    buscarlo donde no está.
    # 2. **`mensajes_enviados` del annex es el ACUMULADO** (cuántos vio el CLI en total),
    #    no cuántos se mandaron en este turno. Derivar los chars de ahí da el historial
    #    entero y un ahorro de 0,0% — que fue exactamente el rojo que esta vara dio antes.
    #
    # Lo que SÍ mide el ahorro es lo que se le manda al binario, y eso lo produce
    # `prompt_bridge`. Se mide sobre la sesión REAL —la que existe sólo porque el resume
    # funcionó— comparando el render incremental contra el completo.
    from cli_brain import prompt_bridge as _pb          # noqa: E402
    _ses2 = S.SESIONES.obtener(_CLAVE, "claude_cli")
    if _ses2 is None or not _ses2.enviados:
        saltear("la medición del ahorro", "no quedó sesión viva para medir")
    else:
        _completo = _pb.render_prompt(_h2, [])
        _nuevos = _h2[_ses2.enviados:] or _h2[-1:]
        _incr = _pb.render_prompt_incremental(_nuevos, [])
        _ahorro = 100.0 * (1 - len(_incr) / max(1, len(_completo)))
        ok(_ahorro > 50,
           f"★ EL AHORRO EXISTE Y ES GRANDE: el turno 2 manda {len(_incr)} chars en vez "
           f"de {len(_completo)} → {_ahorro:.1f}% menos",
           f"{_ahorro:.1f}%")
        ok(_ses2.enviados >= len(_HIST),
           "…y el CLI YA VIO el historial viejo (por eso no hace falta re-mandarlo)",
           f"enviados={_ses2.enviados} de {len(_h2)}")
        print(f"     [medido] completo={len(_completo)} chars · incremental={len(_incr)} "
              f"chars · ahorro={_ahorro:.1f}%")

    _srv.shutdown()

# limpieza del store del usuario: SÓLO lo que ensució esta vara
for _slug in _ENSUCIADOS:
    _d = os.path.join(S.raiz_del_store(), _slug)
    if os.path.isdir(_d):
        shutil.rmtree(_d, ignore_errors=True)
if _ENSUCIADOS:
    print(f"\n[limpieza] {len(_ENSUCIADOS)} directorio(s) de esta vara borrados del store")
shutil.rmtree(_TMP, ignore_errors=True)

# [H4a] El cierre pasa por `qa/lib/veredicto.py`: con salteos declarados la última
# línea ya NO es el string pelado `TODO VERDE`. La regla vive en un solo lugar.
sys.path.insert(0, str(_RAIZ / "qa" / "lib"))
import veredicto as _V  # noqa: E402

# [H3] La nota al pie va ARRIBA: la ÚLTIMA línea de una vara es su veredicto. Un `tail -1`
# que lee «invocación única» no sabe si el merge puede pasar — casi abortó uno sano.
print("     [invocación única del chequeo completo]  "
      "product/backend/.venv/bin/python qa/correr_varas.py")
print(f"\n{_V.texto(_fallos, _salteados)}")
sys.exit(0 if _fallos == 0 else 1)
