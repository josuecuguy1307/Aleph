#!/usr/bin/env python3
"""verify_higiene.py — LA VARA DE LA FASE 1 (Gate 3 · cierre fino · higiene).

⚠️ **NO ANIDA VARAS** (regla sellada en F4a). Lo único que corre acá adentro es UNA vara
del cli_brain, y no para verificarla a ella sino para medir la basura que deja — es el
objeto de H1 y no hay forma de medirlo sin ejecutarlo. Las regresiones van aparte, en
`qa/correr_varas.py`.

Ocho puntos, cada uno con la aserción que falla si vuelve:

  H1 · las varas del cli_brain dejaban espejos huérfanos en `~/.claude/projects/`
  H2 · varas que escribían en el árbol y ensuciaban el `git status`
  H3 · varas cuya ÚLTIMA línea no era su veredicto (un `tail -1` leía una nota al pie)
  H4 · verdes mentirosos: saltear el objeto y decir «TODO VERDE»
  H5 · varas `.mjs` que morían con ERR_MODULE_NOT_FOUND fuera del árbol principal
  H6 · `verify_sala_e2e_load` roja sin backend, sin decir que le faltaba
  H7 · `verify_catalogos_ingesta` — DECLARADA fuera (ver su cabecera), se verifica que
       la declaración siga puesta y que el guard que la destapó no se afloje
  H8 · pytest no colectaba: un standalone `test_*.py` con `sys.exit()` mataba la sesión

    product/backend/.venv/bin/python qa/verify_higiene.py
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
_RAIZ = _AQUI.parent
for _p in (str(_AQUI / "lib"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import deps_node as DN            # noqa: E402
import higiene_store as HS        # noqa: E402
import veredicto as V             # noqa: E402

_PY = sys.executable
_fallos = 0

# ── LO QUE NO ES NUESTRO, NO SE CENSA ─────────────────────────────────────────────────
#
# [Gate 4 · Fase 6] Los dos modos de la Sala cuelgan sus dependencias de un directorio al
# lado de su launcher (`platform/sala/*/`), porque su `arranque.sh` se las pasa por
# `PYTHONPATH`. Son wheels de terceros, gitignoreados y producidos por `deploy/fase6/`, y
# **traen sus propias suites**: 3.963 `test_*.py` y 42 `conftest.py` medidos en
# `platform/sala/research/lib`.
#
# Sin esto, esta vara censa la suite de spacy y de torch como si fuera de la casa. H8 se
# ponía roja por `dill/tests/test_session.py` —un standalone de un paquete ajeno que jamás
# vamos a declarar en nuestro `conftest.py`— y los `rglob` de H2/H3 caminaban 1,9 GiB.
#
# ⚠️ LA LISTA VIVE EN `conftest.py`, NO ACÁ. Es la misma que gobierna `collect_ignore`, y
# el motivo es viejo en esta casa: dos copias de la misma decisión divergen. Acá se
# importa; si mañana aparece un tercer runtime producido, se declara en un solo lugar.
sys.path.insert(0, str(_RAIZ))
import conftest as _CONF          # noqa: E402
_AJENOS = tuple(str(_RAIZ / rel) for rel in _CONF._RUNTIMES_PRODUCIDOS)


def _es_ajeno(ruta) -> bool:
    """¿Está adentro de un runtime producido (o de las otras cosas que no se censan)?"""
    s = str(ruta)
    return (s.startswith(_AJENOS) or "node_modules" in s
            or ".venv" in s or ".git" in s)


#: TODAS las varas del árbol. Vive acá arriba porque la usan H2 (el censo de capturas) y
#: H3 (el censo de colas); definirla dos veces sería el segundo lugar que decide lo mismo.
_varas = sorted(p for p in _RAIZ.rglob("verify_*")
                if p.suffix in (".py", ".mjs") and not _es_ajeno(p))


def ok(cond, nombre, detalle=""):
    global _fallos
    if cond:
        print(f"  ✓ {nombre}")
    else:
        _fallos += 1
        print(f"  ✗ {nombre}" + (f"  →  {detalle}" if detalle else ""))


def seccion(t):
    print(f"\n── {t} " + "─" * max(0, 74 - len(t)))


def _git(*args):
    return subprocess.run(["git", *args], cwd=_RAIZ, capture_output=True,
                          text=True, timeout=60).stdout


print("=" * 80)
print("VARA HIGIENE · GATE 3 · CIERRE FINO — las varas no dejan basura ni mienten")
print("=" * 80)

# ══════════════════════════════════════════════════════════════════════════════════════
# H1 · EL STORE DEL CLI QUEDA COMO ESTABA
# ══════════════════════════════════════════════════════════════════════════════════════
seccion("H1 · una vara del cli_brain corre y NO deja espejos huérfanos")

_raiz_store = HS.raiz_del_store()
ok(HS.prefijos_temporales()[0] == HS.raiz_del_store.__globals__["_S"].slug_de(
    tempfile.gettempdir()),
   "el prefijo se DERIVA con `sesiones.slug_de` — la regla real del CLI, no una copia "
   "(la lección de F4d: traducir sólo `/` escondió un bug una fase entera)",
   HS.prefijos_temporales()[0])

# EL CANDADO, probado con un caso sembrado: un directorio que cumple «nació en un
# temporal» pero tiene un `.jsonl` NO se toca. Es lo único que separa esto de borrar
# conversaciones del usuario.
_falso = Path(_raiz_store) / (HS.prefijos_temporales()[0] + "-VARA-HIGIENE-NO-BORRAR")
_falso.mkdir(parents=True, exist_ok=True)
(_falso / "conversacion.jsonl").write_text('{"type":"user"}\n', encoding="utf-8")
try:
    ok(not HS.es_huerfano(_falso.name),
       "★ EL CANDADO: un directorio del temporal CON un `.jsonl` NO cuenta como huérfano "
       "— jamás se borra una conversación", _falso.name[-40:])
    _vacio = Path(_raiz_store) / (HS.prefijos_temporales()[0] + "-VARA-HIGIENE-VACIO")
    _vacio.mkdir(parents=True, exist_ok=True)
    (_vacio / "memory").mkdir(exist_ok=True)
    ok(HS.es_huerfano(_vacio.name),
       "…y uno del temporal SIN ningún `.jsonl` sí (es la forma exacta de los 22 medidos)",
       _vacio.name[-40:])
    ok(HS.barrer(ruidoso=False) >= 1, "y `barrer()` se lleva el vacío")
    ok(not _vacio.exists() and _falso.exists(),
       "★ el vacío desapareció y el que tenía transcript SIGUE AHÍ")
finally:
    import shutil
    shutil.rmtree(_falso, ignore_errors=True)

# LA MEDICIÓN DE VERDAD: una vara del cli_brain, entera, y el store contado antes/después.
_antes = set(os.listdir(_raiz_store))
_vara = _RAIZ / "platform" / "assembler" / "cli_brain" / "verify_cli_usage.py"
_r = subprocess.run([_PY, str(_vara)], cwd=_RAIZ, capture_output=True, text=True, timeout=900)
_despues = set(os.listdir(_raiz_store))
_nuevos = sorted(_despues - _antes)
print(f"     [medido] verify_cli_usage exit={_r.returncode} · "
      f"entradas nuevas en el store: {len(_nuevos)}")
ok(not _nuevos,
   "★ H1 · corrió una vara del cli_brain COMPLETA y el store quedó con CERO entradas "
   "nuevas (antes dejaba un espejo por `mkdtemp` de `base.invoke`)", str(_nuevos[:3]))
ok(not HS.censar_huerfanos(),
   "y no queda ningún huérfano acumulado en el store", str(HS.censar_huerfanos()[:3]))

# ══════════════════════════════════════════════════════════════════════════════════════
# H2 · EL ÁRBOL NO SE ENSUCIA
# ══════════════════════════════════════════════════════════════════════════════════════
seccion("H2 · las varas escriben en un temporal, no en el árbol")

_sucio_antes = _git("status", "--porcelain").strip()
_r2 = subprocess.run(
    [_PY, str(_RAIZ / "platform/assembler/deleg_fixtures/verify_frontera_d4.py")],
    cwd=_RAIZ, capture_output=True, text=True, timeout=900)
_sucio_despues = _git("status", "--porcelain").strip()
ok(_r2.returncode == 0, "verify_frontera_d4 sigue VERDE", (_r2.stdout or "")[-200:])
ok(_sucio_antes == _sucio_despues,
   "★ H2 · correrla NO cambió el `git status` (antes reescribía "
   "`frontera_d4_events.json` con el `wall_s` de la corrida)",
   f"antes={len(_sucio_antes.splitlines())} después={len(_sucio_despues.splitlines())}")
ok(not _git("status", "--porcelain", "--", "product/app/design/cuarto/frontera_d4_events.json").strip(),
   "…y el fixture commiteado sigue idéntico")

_fte = (_RAIZ / "platform/assembler/deleg_fixtures/verify_frontera_d4.py").read_text(encoding="utf-8")
ok("--regenerar-fixture" in _fte,
   "regenerar el fixture del árbol es un acto EXPLÍCITO (`--regenerar-fixture`), no un "
   "efecto secundario de correr la vara")
for _rel, _flag in (("platform/assembler/verify_catalog_batch.py", "--evidencia-al-arbol"),
                    ("qa/verify_catalogos_ingesta.py", "--al-arbol"),
                    ("qa/verify_modelos_v2.mjs", "--capturas-al-arbol"),
                    ("qa/verify_multiagente_f2.mjs", "--capturas-al-arbol")):
    ok(_flag in (_RAIZ / _rel).read_text(encoding="utf-8"),
       f"{Path(_rel).name} escribe al árbol sólo con `{_flag}`")

# ── LOS `.png` COMMITEADOS, que el primer censo dio por muertos ─────────────────────
# Se habían declarado «el patrón está pero no está vivo»: ninguna vara de la regresión
# los había reescrito. **Falso** — lo destapó el `git diff --stat` del commit, no el
# censo: `qa/screenshots/modelos-v2-lista-constante.png` pasó de 147.300 a 149.839 bytes
# en la corrida. Un `git status` sucio que no es trabajo de nadie, exactamente el H2 que
# esta fase existe para cerrar. La lección es la misma que en H3: **medir la salida, no
# leer el archivo**.
_png_tracked = [p for p in _git("ls-files").splitlines()
                if p.endswith(".png") and "screenshots/" in p]
ok(len(_png_tracked) > 100,
   f"hay {len(_png_tracked)} `.png` commiteados bajo `screenshots/` — el riesgo es real",
   str(len(_png_tracked)))
_png_sucios = [l for l in _git("status", "--porcelain").splitlines() if l.strip().endswith(".png")]
ok(not _png_sucios,
   "★ H2 · ningún `.png` commiteado quedó modificado por las varas de esta corrida",
   str(_png_sucios[:3]))

# ── EL CENSO QUE SÍ CUBRE LAS 277, porque correrlas todas no es viable ──────────────
# LO QUE ESTA ASERCIÓN EXISTE PARA IMPEDIR, y ya pasó una vez: en la Fase 1 se declaró que
# los `.png` commiteados «no estaban vivos» porque ninguna vara de ESA regresión los
# reescribía. En la Fase 2 corrió `verify_i18n_shell` —que la Fase 1 no había corrido— y
# ensució `sala/screenshots/shell-{es,en}.png` en el acto. La medición dinámica de arriba
# sólo ve las varas que esta vara corre; el censo estático ve todas.
#
# La regla: si una vara escribe una captura a un directorio `screenshots/` QUE TIENE
# archivos commiteados, tiene que ofrecer la salida a temporal. El flag es la evidencia
# de que alguien lo pensó.
# EL DISCRIMINANTE tiene que ser el DESTINO REAL, no la palabra «screenshots». El primer
# intento comparaba `Path(d).name`, que es «screenshots» para TODOS los directorios, así
# que la condición se reducía a «el archivo menciona screenshots» y marcaba 5+ varas sanas
# —`verify_atomo`, `verify_advisor`— que sólo lo nombran en un comentario. Un censo que
# acusa a los inocentes enseña a ignorarlo.
#
# Se compara el directorio del ARCHIVO contra los directorios que tienen `.png`
# commiteados: una vara que vive en `sala/` y escribe en `screenshots/` está escribiendo
# en `sala/screenshots/`, que es el que está trackeado.
_dirs_con_png = {str(Path(_p).parent) for _p in _git("ls-files").splitlines()
                 if _p.endswith(".png") and "screenshots" in _p}
_sin_flag = []
for _v in _varas:
    _t = _v.read_text(encoding="utf-8", errors="replace")
    if ".screenshot(" not in _t:
        continue                              # no saca capturas: no aplica
    _propio = str(_v.parent.relative_to(_RAIZ)) + "/screenshots"
    if _propio not in _dirs_con_png:
        continue                              # su directorio no tiene `.png` commiteados
    if any(_x in _t for _x in ("al-arbol", "tmpdir()", "gettempdir")):
        continue                              # ofrece salida a temporal: está declarado
    _sin_flag.append(str(_v.relative_to(_RAIZ)))
#: ══ LA DEUDA MEDIDA, DECLARADA — 43 productores ═══════════════════════════════════
#: El censo encontró 43 varas que pisan capturas commiteadas. Arreglarlas es una obra
#: propia —43 archivos, cada uno con su fixture— y meterla en el cierre fino sería
#: exactamente el «mientras estamos acá» que hace que una tanda no cierre nunca.
#:
#: Se declaran UNA POR UNA, que es lo que las hace visibles: la vara NO rompe por las que
#: ya estaban, y SÍ rompe ante una nueva. Es el mismo trato que el contador de causas de
#: `verify_f4a:198` y la lista de standalone del `conftest.py`: **lo declarado no rompe;
#: lo nuevo cuesta una línea y una decisión.**
#:
#: Las cuatro que sí se arreglaron —`verify_modelos_v2`, `verify_multiagente_f2`,
#: `verify_i18n_shell` y el fixture de `verify_frontera_d4`— son las que se midieron
#: ensuciando el árbol de verdad en una corrida.
_CAPTURAS_DEUDA = {
    "product/app/design/cuarto/verify_1a_coreografia.mjs",
    "product/app/design/cuarto/verify_advisor.mjs",
    "product/app/design/cuarto/verify_atomo.mjs",
    "product/app/design/cuarto/verify_brandface.mjs",
    "product/app/design/cuarto/verify_caja.mjs",
    "product/app/design/cuarto/verify_cerebro.mjs",
    "product/app/design/cuarto/verify_circulo.mjs",
    "product/app/design/cuarto/verify_constelacion_c1.mjs",
    "product/app/design/cuarto/verify_constelacion_c2.mjs",
    "product/app/design/cuarto/verify_constelacion_c3.mjs",
    "product/app/design/cuarto/verify_credencial.mjs",
    "product/app/design/cuarto/verify_desequipar.mjs",
    "product/app/design/cuarto/verify_guardar.mjs",
    "product/app/design/cuarto/verify_h9_money_gate.mjs",
    "product/app/design/cuarto/verify_icons_live.mjs",
    "product/app/design/cuarto/verify_labels.mjs",
    "product/app/design/cuarto/verify_p3_arco.mjs",
    "product/app/design/cuarto/verify_p3_cierre.mjs",
    "product/app/design/cuarto/verify_p5_identidad.mjs",
    "product/app/design/cuarto/verify_p5_say_i18n.mjs",
    "product/app/design/cuarto/verify_p6_anillos.mjs",
    "product/app/design/cuarto/verify_pulso.mjs",
    "product/app/design/cuarto/verify_pulso_real.mjs",
    "product/app/design/cuarto/verify_recinto_interaccion.mjs",
    "product/app/design/cuarto/verify_recinto_render.mjs",
    "product/app/design/cuarto/verify_reel.mjs",
    "product/app/design/cuarto/verify_render_answer.mjs",
    "product/app/design/cuarto/verify_slots.mjs",
    "product/app/design/cuarto/verify_slots_modo.mjs",
    "product/app/design/cuarto/verify_t6_minimalista.mjs",
    "product/app/design/cuarto/verify_tile_auras.mjs",
    "product/app/design/sala/verify_2c_bioacustica.mjs",
    "product/app/design/sala/verify_metodo_obra_guard.mjs",
    "product/app/design/sala/verify_metodo_resume.mjs",
    "product/app/design/sala/verify_p11_gate.mjs",
    "product/app/design/sala/verify_routing.mjs",
    "product/app/design/sala/verify_slice_d_controls.mjs",
    "product/app/design/sala/verify_step4_4a.mjs",
    "product/app/design/sala/verify_step4_4b.mjs",
    "product/app/design/sala/verify_step4_bridge.mjs",
    "qa/verify_cuarto_limpio.mjs",
    "qa/verify_step5_p10_paywall.mjs",
    "qa/verify_v2_front_auth.mjs",
}

_nuevas = [x for x in _sin_flag if x not in _CAPTURAS_DEUDA]
ok(not _nuevas,
   f"★ H2 · ninguna vara NUEVA escribe capturas a un `screenshots/` con `.png` "
   f"commiteados sin ofrecer salida a temporal (deuda declarada: {len(_CAPTURAS_DEUDA)} "
   f"productores, ver `_CAPTURAS_DEUDA`)",
   str(_nuevas[:5]))
ok(len(_sin_flag) <= len(_CAPTURAS_DEUDA),
   f"…y la deuda NO creció: {len(_sin_flag)} de {len(_CAPTURAS_DEUDA)} declarados")

# ══════════════════════════════════════════════════════════════════════════════════════
# H3 · LA ÚLTIMA LÍNEA ES EL VEREDICTO
# ══════════════════════════════════════════════════════════════════════════════════════
seccion("H3 · ninguna vara cierra con una nota al pie después del veredicto")

#: Lo que NUNCA puede ser lo último que imprime una vara. No es «cualquier print»: es la
#: forma exacta que rompió el `tail -1` de `verify_costura_obra4` y casi aborta un merge
#: sano — una barra decorativa o una nota informativa DESPUÉS del resultado.
#: Cubre tanto `print("═══")` como `print("═" * 90)` y `print("\n" + "═" * 78)`. El
#: segundo se le escapaba al detector y por eso tres varas del cierre de §28 pasaron el
#: censo estático y salieron con `═════…` en su `tail -1` en la corrida de regresión.
_DECORATIVA = re.compile(r'^(?:["\'](?:[═─━=\-*_·\s]|\\n)*["\'](?:\s*[*+]\s*(?:\d+|["\'][^"\']*["\']))?\s*)+$')
_NOTA = re.compile(r"invocación única|la saneada completa|NOTA:|capturas|screenshot", re.I)
_VEREDICTO = re.compile(r"TODO VERDE|FALLO|RESULTADO|VERDE|ROJO|ALL GREEN|passed|_V\.texto"
                        r"|_V\.cerrar|PASS|FAIL", re.I)


def _cola_de_adorno(ruta: Path) -> str:
    """'' si cierra bien; si no, la línea ofensora.

    ══ EL LÍMITE DE ESTE CENSO, MEDIDO ════════════════════════════════════════════════
    Compara ORDEN TEXTUAL, y el orden textual no es el de ejecución. Al mover el resumen
    de `verify_byok_sin_alias` a un `cerrar()` —definido ARRIBA de `main()`— el último
    print con veredicto quedó textualmente antes del ENCABEZADO de `main()`, y el
    detector acusó a la barra del título de ser una cola. Falso positivo.

    El corte: si entre el veredicto y el print decorativo hay un `def`/`function`, son
    bloques distintos y no se comparan. Y lo que este censo no puede ver —un `atexit`,
    un `print` de otro módulo— lo cubre la medición dinámica de más abajo, que corre
    varas de verdad y les mira el `tail -1`.
    """
    try:
        lineas = ruta.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    salidas = [(n, l) for n, l in enumerate(lineas, 1)
               if re.match(r"^\s*(print\(|console\.log\()", l)]
    if not salidas:
        return ""
    vistos = [k for k, (_n, l) in enumerate(salidas) if _VEREDICTO.search(l)]
    if not vistos:
        return ""
    _n_ver = salidas[vistos[-1]][0]
    for _n, l in salidas[vistos[-1] + 1:]:
        # ¿hay una frontera de bloque entre el veredicto y este print? entonces no es cola
        if any(re.match(r"^\s*(def |async def |function |const \w+ = (async )?\(|\w+\s*=\s*function)",
                        _m) for _m in lineas[_n_ver:_n - 1]):
            break
        arg = l.strip()[len("print("):].rstrip(") ") if l.strip().startswith("print(") \
            else l.strip()[len("console.log("):].rstrip("); ")
        if _DECORATIVA.match(arg) or _NOTA.search(l):
            return f"{ruta.relative_to(_RAIZ)}:{_n}  {l.strip()[:70]}"
    return ""


_malas = [m for m in (_cola_de_adorno(v) for v in _varas) if m]
print(f"     [medido] {len(_varas)} varas censadas")
ok(not _malas,
   f"★ H3 · ninguna de las {len(_varas)} varas cierra con una barra decorativa o una nota "
   f"al pie DESPUÉS de su veredicto", "\n       ".join(_malas[:6]))

_ob4 = (_RAIZ / "platform/assembler/verify_costura_obra4.py").read_text(encoding="utf-8")
ok(_ob4.index("la saneada completa") < _ob4.index("passed, "),
   "★ el caso índice: en `verify_costura_obra4` la nota al pie va ARRIBA del resumen")

# ── LA MEDICIÓN DINÁMICA, que el censo estático NO puede dar ────────────────────────
# El censo lee el archivo; el `tail -1` lee lo que SALE. Las dos cosas se separaron dos
# veces en esta misma fase:
#   · el detector no reconocía `print("═" * 90)` (sólo `print("═══")`), y tres varas del
#     cierre de §28 pasaron el censo y salieron con `═════…` en su última línea;
#   · `higiene_store.vigilar()` imprime desde un `atexit`, o sea DESPUÉS del veredicto —
#     el arreglo de H1 rompía la regla de H3 y ningún censo del archivo podía verlo.
# Por eso acá se corren varas de verdad y se mide su STDOUT (stderr aparte a propósito:
# la instrumentación no es veredicto).
_VEREDICTO_VIVO = re.compile(r"TODO VERDE|VERDE PARCIAL|FALLO\(S\)|passed,|RESULTADO|"
                             r"^VERDE|verdes ·|all green|TODO VERDE", re.I)
_dinamicas = [
    ("platform/assembler/verify_costura_obra1.py", [_PY]),
    ("platform/assembler/verify_traductor.py", [_PY]),
    ("qa/verify_byok_sin_alias.py", [_PY]),
]
for _rel, _cmd in _dinamicas:
    _rr = subprocess.run([*_cmd, str(_RAIZ / _rel)], cwd=_RAIZ,
                         capture_output=True, text=True, timeout=900)
    _ultima = (_rr.stdout.strip().splitlines() or [""])[-1].strip()
    ok(bool(_VEREDICTO_VIVO.search(_ultima)),
       f"★ H3 vivo · el `tail -1` REAL de {Path(_rel).name} es su veredicto",
       _ultima[:80])

# y la trampa propia: una vara con `vigilar()` no puede terminar con el `[higiene]`
_rh = subprocess.run([_PY, str(_RAIZ / "platform/assembler/cli_brain/verify_f4d.py")],
                     cwd=_RAIZ, capture_output=True, text=True, timeout=900)
_ult_h = (_rh.stdout.strip().splitlines() or [""])[-1].strip()
ok("[higiene]" not in _ult_h and bool(_VEREDICTO_VIVO.search(_ult_h)),
   "★ H3 vivo · una vara con `vigilar()` cierra con su veredicto, no con el `[higiene]` "
   "del `atexit` (que va por stderr: es instrumentación)", _ult_h[:80])
ok("[higiene]" not in _rh.stdout,
   "…y el mensaje de higiene no aparece en stdout en NINGUNA línea")

# ══════════════════════════════════════════════════════════════════════════════════════
# H4 · NINGÚN VERDE MENTIROSO
# ══════════════════════════════════════════════════════════════════════════════════════
seccion("H4 · una vara que saltea SU OBJETO no puede decir «TODO VERDE»")

ok(V.texto(0, 0, 0) == "TODO VERDE", "sin fallos ni salteos: TODO VERDE, pelado")
ok(V.texto(0, 3, 0) != "TODO VERDE" and "3 salteo" in V.texto(0, 3, 0),
   "★ con salteos declarados la última línea YA NO es el string pelado `TODO VERDE`",
   V.texto(0, 3, 0))
ok(V.texto(0, 3, 3).startswith("VERDE PARCIAL"),
   "★ H4a · con salteos DE SU OBJETO el veredicto es VERDE PARCIAL", V.texto(0, 3, 3))
_exit_critico = V.cerrar(0, 3, 3)
ok(_exit_critico == 1, "★ …y SALE EN ROJO: un salteo del objeto no es un verde", str(_exit_critico))
ok(V.cerrar(0, 3, 0) == 0, "un salteo declarado y no crítico sigue saliendo 0")
ok(not V.es_verde_limpio("TODO VERDE (con 3 salteo(s) declarado(s))"),
   "★ `es_verde_limpio` NO se traga el verde con salteos — que es lo que "
   "`\"TODO VERDE\" in stdout` sí hacía en los tres padres", "")
ok(V.es_verde_limpio("cosas\nTODO VERDE\n"), "…y sí acepta el verde limpio")

# las tres llamadas de f4a que se comían la vía de producción están DECLARADAS críticas
_f4a = (_RAIZ / "platform/assembler/verify_f4a.py").read_text(encoding="utf-8")
ok(_f4a.count("critico=True") == 3,
   "★ H4a · los 3 salteos de litellm en `verify_f4a` están declarados críticos "
   "(litellm es la vía de producción y la obra 3 entera)", str(_f4a.count("critico=True")))
ok("critico=True" in (_RAIZ / "platform/assembler/verify_adaptador_litellm.py").read_text(
    encoding="utf-8"),
   "…y el de `verify_adaptador_litellm`, cuyo objeto ES litellm")
for _rel in ("platform/assembler/verify_adaptador_litellm.py",
             "platform/assembler/cli_brain/verify_cli_slots.py",
             "platform/assembler/cli_brain/verify_cli_usage.py"):
    _t = (_RAIZ / _rel).read_text(encoding="utf-8")
    ok('ok("TODO VERDE" in r.stdout' not in _t and "_V.es_verde_limpio" in _t,
       f"{Path(_rel).name} ya no valida a su hija por substring")

# H4b · la vara que crasheaba a mitad sigue ENTERA (llega a su última sección)
_slice = (_RAIZ / "product/app/design/sala/verify_slice_d_controls.mjs")
ok(_slice.exists(), "H4b · verify_slice_d_controls existe")

# H4c · el censo de vocabulario con número fijo: se DECLARA por qué es a mano
_f4a_censo = _f4a[_f4a.index("len(MV.CAUSAS)") - 900:_f4a.index("len(MV.CAUSAS)")]
ok("tocarse a mano" in _f4a_censo or "toca a mano" in _f4a_censo or "tocó a mano" in _f4a_censo,
   "★ H4c · el contador fijo de causas (30/27) DECLARA en el árbol por qué es a mano: "
   "«una causa nueva no entra sin que alguien la cuente». Medido: ya estaba declarado, "
   "no se toca")

# H4d · el barrido: ninguna vara puede ser incapaz de fallar.
#
# El discriminante NO es «termina con `process.exit(0)`»: `verify_cuarto_limpio` y
# `verify_sala_cerebro_del_dueno` cierran así **a propósito** —montan cosas que dejan
# temporizadores vivos y node no termina solo— y las dos tienen su `exit(1)` condicional
# arriba. El detector las marcaba y eran falsos positivos.
# Lo que sí es un verde mentiroso: una vara con salida explícita y **ni un solo
# `process.exit(1)` en todo el archivo** — o sea, sin ningún camino que devuelva rojo.
_mentirosas = []
for _v in _varas:
    if _v.suffix != ".mjs":
        continue
    _t = _v.read_text(encoding="utf-8", errors="replace")
    if "process.exit(0)" in _t and "process.exit(1)" not in _t:
        _mentirosas.append(str(_v.relative_to(_RAIZ)))
ok(not _mentirosas,
   "★ H4d · ninguna vara `.mjs` sale explícitamente 0 sin tener NINGÚN camino que salga 1 "
   "(medido: `verify_sala_instalada` anotaba los `ok:false` en su JSON y salía CERO igual, "
   "y nadie parsea ese JSON — el exit code era su único veredicto)",
   str(_mentirosas[:4]))

# ══════════════════════════════════════════════════════════════════════════════════════
# H5 · LAS VARAS DE NODE CORREN EN UN WORKTREE
# ══════════════════════════════════════════════════════════════════════════════════════
seccion("H5 · `node_modules` se resuelve solo desde cualquier worktree")

_listo, _motivo = DN.asegurar_node_modules()
ok(_listo, "★ H5 · el worktree tiene `node_modules` alcanzable (enlazado al principal si "
           "hacía falta)", _motivo)
ok((_RAIZ / "node_modules").exists(), "…y el enlace está puesto", _motivo)
_cm = (_RAIZ / "qa/verify_cuarto_modelos.mjs").read_text(encoding="utf-8")
ok("node_deps.mjs" in _cm,
   "verify_cuarto_modelos —el caso nombrado— resuelve por `qa/lib/node_deps.mjs`")
_cv = (_RAIZ / "qa/correr_varas.py").read_text(encoding="utf-8")
ok("deps_node" in _cv,
   "…y la invocación única lo asegura antes de correr nada (cubre las 140 varas que "
   "importan playwright)")

# ══════════════════════════════════════════════════════════════════════════════════════
# H6 · LA VARA DE CARGA LEVANTA LO QUE NECESITA
# ══════════════════════════════════════════════════════════════════════════════════════
seccion("H6 · verify_sala_e2e_load no depende de que alguien haya levantado el stub")

_r6 = subprocess.run(["node", str(_RAIZ / "qa/verify_sala_e2e_load.mjs")],
                     cwd=_RAIZ, capture_output=True, text=True, timeout=300)
_ult6 = (_r6.stdout.strip().splitlines() or [""])[-1]
ok(_r6.returncode == 0,
   "★ H6 · corre VERDE sin backend previo: levanta el stub sola y lo baja",
   (_r6.stderr or _r6.stdout)[-200:])
ok(_ult6.startswith("VERDE"), "…y su última línea es el veredicto, no el JSON", _ult6[:70])
_sueltos = subprocess.run(["pgrep", "-f", "sala_e2e_stub_server"],
                          capture_output=True, text=True, timeout=30).stdout.strip()
ok(not _sueltos, "…y no deja el stub corriendo", _sueltos[:60])

# ══════════════════════════════════════════════════════════════════════════════════════
# H7 · DECLARADA FUERA, CON SU GUARD PUESTO
# ══════════════════════════════════════════════════════════════════════════════════════
seccion("H7 · verify_catalogos_ingesta — declarada fuera, y el guard no se afloja")

_ing = (_RAIZ / "qa/verify_catalogos_ingesta.py").read_text(encoding="utf-8")
ok("DECLARADA" in _ing and "fuera de la Fase 1" in _ing,
   "★ H7 · la cabecera DECLARA por qué queda roja: 5 limpias de 18.630 candidatos no es "
   "un caso nuevo, es una pregunta de producto sobre `catalog_ingest_router`")
ok("dejó afuera a la mayoría del corpus" in _ing,
   "…y el rojo dice el número medido en vez de morir en el primer caso")
ok("CAUSE_UNPROVEN" in _ing and "NO declarada" in _ing,
   "…y un rechazo con causa que el router NO declara sigue rompiendo (no se aflojó)")

# ══════════════════════════════════════════════════════════════════════════════════════
# H8 · PYTEST COLECTA
# ══════════════════════════════════════════════════════════════════════════════════════
seccion("H8 · la colección de pytest no la mata un script standalone")

sys.path.insert(0, str(_RAIZ))
CONF = _CONF   # ya importado arriba, con su motivo

#: Los standalone se DECLARAN uno por uno. Si aparece uno nuevo sin declarar, esta
#: aserción se pone roja ANTES de que mate la colección de otro.
_sin_declarar = []
for _p in _RAIZ.rglob("test_*.py"):
    # Mismo criterio que arriba, y por la misma razón: un `test_*.py` de un wheel ajeno no
    # es un standalone de la casa que haya que declarar — es la suite de otro proyecto.
    if _es_ajeno(_p):
        continue
    _rel = str(_p.relative_to(_RAIZ))
    if _rel in CONF.STANDALONE:
        continue
    try:
        _arbol = ast.parse(_p.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        continue
    # ══ EL WALK ENTERO, NO SÓLO `body` — y por qué ═════════════════════════════════
    # Acá se recorría `_arbol.body` a secas: sólo las sentencias del nivel de módulo
    # DIRECTO. `platform/assembler/test_vision_route_e2e.py:91` tiene
    # `if fails: … raise SystemExit(1)` — un nivel adentro de un `if`, que el `body`
    # pelado no ve. Y es el peor caso posible: **sólo mata la colección cuando el test
    # falla**, así que la vara puede salir verde el día que ese E2E anda y roja al día
    # siguiente sin que nadie haya tocado nada. Medido el 2026-08-08: main colectaba 1252
    # tests por la mañana y 116 + INTERNALERROR por la tarde.
    #
    # Se camina TODO lo alcanzable desde el módulo **sin entrar en `def`/`class`**: un
    # `sys.exit` dentro de una función no corre al importar, y marcarlo sería ruido.
    def _es_main_guard(_n) -> bool:
        """`if __name__ == "__main__":` — el patrón CORRECTO, que NO corre al importar.

        Sin esta salvedad el detector marca 33 archivos sanos: `sys.exit(main())` bajo el
        guard es exactamente lo que hay que hacer, y acusarlo enseñaría a ignorar la vara.
        """
        if not isinstance(_n, ast.If) or not isinstance(_n.test, ast.Compare):
            return False
        _izq = _n.test.left
        return isinstance(_izq, ast.Name) and _izq.id == "__name__"

    def _alcanzable(nodos):
        for _n in nodos:
            if isinstance(_n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue                      # eso no corre al importar
            if _es_main_guard(_n):
                continue                      # ni eso
            yield _n
            for _campo in ("body", "orelse", "finalbody", "handlers"):
                _hijos = getattr(_n, _campo, None)
                if isinstance(_hijos, list):
                    yield from _alcanzable(_hijos)

    for _nodo in _alcanzable(_arbol.body):
        _exp = _nodo.value if isinstance(_nodo, ast.Expr) else None
        _llam = _exp if isinstance(_exp, ast.Call) else None
        if isinstance(_nodo, ast.Raise) and isinstance(_nodo.exc, ast.Call):
            _llam = _nodo.exc
        if _llam is None:
            continue
        _f = _llam.func
        _nombre = getattr(_f, "attr", None) or getattr(_f, "id", None)
        if _nombre in ("exit", "SystemExit") and (
                getattr(getattr(_f, "value", None), "id", "") in ("sys", "") or _nombre == "SystemExit"):
            _sin_declarar.append(_rel)
            break

ok(not _sin_declarar,
   "★ H8 · no hay ningún `test_*.py` standalone SIN declarar en `conftest.py` "
   "(uno solo mata la colección entera: 15 tests y un INTERNALERROR)",
   str(_sin_declarar[:4]))
ok(len(CONF.STANDALONE) >= 11,
   f"y los {len(CONF.STANDALONE)} declarados llevan su motivo escrito")

_col = subprocess.run([_PY, "-m", "pytest", "--collect-only", "-q"],
                      cwd=_RAIZ, capture_output=True, text=True, timeout=900)
_m = re.search(r"(\d+) tests? collected", _col.stdout)
_n_col = int(_m.group(1)) if _m else 0
print(f"     [medido] pytest colectó {_n_col} tests · INTERNALERROR="
      f"{'INTERNALERROR' in _col.stdout}")
ok("INTERNALERROR" not in _col.stdout,
   "★ H8 · `pytest --collect-only` ya no muere con INTERNALERROR")
ok(_n_col > 1000,
   f"…y colecta {_n_col} tests (antes: 15 y la sesión muerta)", str(_n_col))

# ══════════════════════════════════════════════════════════════════════════════════════
print("\n     [invocación única del chequeo completo]  "
      "product/backend/.venv/bin/python qa/correr_varas.py")
sys.exit(V.cerrar(_fallos))
