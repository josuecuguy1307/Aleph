#!/usr/bin/env python3
"""correr_varas.py — CORRER LAS ~100 VARAS EN PARALELO SIN QUE SE PISEN.

    product/backend/.venv/bin/python qa/correr_varas.py            # paralelo, auto
    product/backend/.venv/bin/python qa/correr_varas.py --serie    # una por vez (la base)
    product/backend/.venv/bin/python qa/correr_varas.py -n 6       # workers explícitos
    product/backend/.venv/bin/python qa/correr_varas.py --salida X # a dónde escribir

El problema medido: la vara tardaba ~2 h por sesión, **en un núcleo, con ocho disponibles**.
La vara costaba más que la obra, y una vara cara se corre menos veces — que es la peor forma
de perderla.

──────────────────────────────────────────────────────────────────────────────────────
EL RIESGO NO ES LA VELOCIDAD, ES LA COLISIÓN.

Las varas no son funciones puras: **bindean puertos y tocan la misma `aleph.db`**. Correrlas
todas a la vez no las hace más rápidas, las hace mentir — dos varas peleando por `:8080`
producen un rojo que no es de nadie.

Y esa `aleph.db` era LA DEL USUARIO hasta el 2026-08-06. El aislamiento por recurso las
protegía entre ellas y no protegía nada más: una corrida completa sembraba +25 users, +13
keys y +41 puppets en el datadir de verdad. Ahora todas corren contra una COPIA — ver
`_datadir_de_trabajo`, que también dice qué se copia y por qué. Los cerrojos siguen
haciendo falta: la copia es una sola y compartida.

Medido sobre el árbol, y por eso el aislamiento es POR RECURSO y no un `-n auto` a ciegas:

    :8923  → 4 varas        :8080  → 3        :11434 (Ollama) → 3
    :8926 · :8090 · :8097 · :8155 · :4000 · :8765 → 2 cada uno
    el datadir/`aleph.db` real → 6 varas

**Dos varas que comparten un recurso NUNCA corren a la vez; dos que no comparten nada, sí.**
Es un pool con locks por recurso, no una partición estática: una vara de `:8080` puede correr
junto a una de `:8923`, y sólo espera a las otras dos de `:8080`.

⚠️ **PROHIBIDO ABLANDAR UNA VARA PARA QUE PASE EN PARALELO.** Si una falla en paralelo y no
en serie, es estado compartido que este mapa no declaró: se agrega el recurso acá, con su
motivo. Bajar una aserción para ganar tiempo convierte la suite en decoración.

LOS RECURSOS SE DETECTAN Y ADEMÁS SE DECLARAN. La detección automática (los puertos que el
archivo nombra) atrapa lo que se escribe mañana; la tabla `_EXTRA` cubre lo que no se ve
leyendo —un binario que abre un puerto por su cuenta, un lock de sistema— y lleva el motivo
escrito. Sólo-detección envejece mal; sólo-tabla no ve lo nuevo.

──────────────────────────────────────────────────────────────────────────────────────
DECISIÓN · `pytest-xdist` SE DESCARTA, Y NO POR PEREZA.

El plan original era también paralelizar la regresión con `pytest-xdist -n auto`. **Se mide
y no da.** Cronometrado en esta máquina, sobre `main @ 6810613`, con la máquina libre:

    regresión venv 3.14        458 s
    regresión miniconda 3.13   564 s        →  ~17 min las dos
    las 101 varas, en serie    el resto del reloj

Las ~2 h que motivaron la sesión no eran de la regresión: eran de **cuatro pasadas
solapadas** compitiendo entre sí y con el resto del trabajo en la misma máquina. Con la
medición real, el grueso está en las varas —cada una levanta un intérprete entero y muchas
esperan red o timeouts— y no en pytest.

Y del otro lado del balance está el riesgo: esta suite **pasa por archivo a propósito**
(`test_*.py` uno por uno) porque tiene contaminación cruzada conocida entre módulos. Meter
`-n auto` es reordenar 140 archivos y 1110 tests contra un estado compartido que nadie
mapeó, para ganar minutos sobre 17. **17 minutos no compran ese riesgo.**

Queda anotado como decisión con su número, no como algo que no se hizo: si mañana la
regresión crece hasta doler, se retoma — y lo primero será mapear el estado compartido, que
es el trabajo real que xdist esconde detrás de una bandera.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Techo por vara. El mismo que usaba el arnés en serie, para que la comparación valga.
TIMEOUT_S = 120

#: RECURSOS QUE NO SE VEN LEYENDO EL ARCHIVO. Cada entrada con su motivo: una excepción sin
#: motivo escrito es un olvido disfrazado de decisión.
_EXTRA: dict = {
    # Las que tocan el datadir / `aleph.db`. No nombran un puerto, pero comparten un
    # archivo — y dos escrituras concurrentes sobre la misma SQLite dan un rojo aleatorio.
    # (Desde el 2026-08-06 la `aleph.db` que comparten es la COPIA, no la del usuario; el
    # cerrojo sigue siendo necesario porque la copia es una sola.)
    "platform/db/verify_multiagente_saltos.py": ("datadir",),
    "platform/inspection/verify_repair_e2e.py": ("datadir",),
    "qa/verify_catalogos_frozen.py": ("datadir",),
    "qa/verify_onshape_lectura_real.py": ("datadir",),
    "qa/verify_wedge_escritura.py": ("datadir",),
    # `verify_byo_headers` aísla su datadir con ALEPH_DATA_DIR (lo hace a propósito), pero
    # el forjado escribe bajo `synth_belts/` y el nombre del slug es fijo: dos corridas
    # simultáneas se pisarían el mismo manifest.
    "qa/verify_byo_headers.py": ("datadir",),
    # El libro de procesos del dueño es un archivo único del sistema.
    "platform/inspection/verify_run_dueno.py": ("procesos",),
    "platform/inspection/verify_calentador_restore_sdk.py": ("procesos",),
    # [F4a] EL ESTADO DEL BYO-CLI, que no se ve leyendo el archivo. Dos recursos distintos:
    #
    #   `cli_store`    — `~/.claude/projects/`, el store de sesiones del BINARIO. No es
    #     nuestro y no se puede aislar con una env var: F2e midió que `CLAUDE_CONFIG_DIR`
    #     lo mueve pero PIERDE EL AUTH, así que el `claude` real escribe ahí sí o sí.
    #     MEDIDO al escribir F4a: dos corridas simultáneas de `verify_cli_sesiones` —una
    #     por worktree— se pisaron el índice y la segunda leyó la sesión de la primera
    #     («el índice la encuentra en su store» en rojo, ids cruzados). En serie, TODO
    #     VERDE las dos veces. Sólo esta vara lo toca.
    #
    #   `cli_registro` — el registro PERSISTENTE de turnos del cli_brain. Lo escribe
    #     cualquier vara que spawnee un turno, y `verify_cli_stopturn` afirma sobre él
    #     («el registro persistente quedó limpio»), así que un turno ajeno en vuelo la
    #     pone roja sin que nada esté mal.
    "platform/assembler/cli_brain/verify_cli_sesiones.py": ("cli_store", "cli_registro"),
    "platform/assembler/cli_brain/verify_cli_stopturn.py": ("cli_registro",),
    # [Gate 3 · obra 4] Esta vara NO toca el store leyendo el archivo —su propio store es
    # falso (`CLAUDE_CONFIG_DIR` a un tmp)— pero SPAWNEA a `verify_cli_sesiones` y a
    # `verify_f4d` con el entorno limpio, y ésas sí escriben en el store real y en el
    # registro. La detección automática no puede verlo: los recursos son de las HIJAS.
    "platform/assembler/verify_costura_obra4.py": ("cli_store", "cli_registro"),
}

#: Puertos que el archivo nombra. Se busca la FORMA de un endpoint, no cualquier número:
#: un `timeout=8080` no es un puerto y un guard que lo tome enseña a ignorarlo.
_PUERTO = re.compile(
    r"(?:127\.0\.0\.1|localhost)[:,]\s*(\d{4,5})"
    r"|PUERTO[A-Z_]*\s*=\s*(\d{4,5})"
    r"|--port[= ]+(\d{4,5})")


def _varas() -> list:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True)
    return sorted(l for l in out.stdout.splitlines()
                  if re.search(r"(^|/)verify_[^/]*\.py$", l))


def recursos_de(rel: str) -> frozenset:
    """Los recursos que esta vara puede pelear con otra."""
    fuera = set(_EXTRA.get(rel, ()))
    try:
        txt = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return frozenset(fuera)
    for m in _PUERTO.finditer(txt):
        p = next(g for g in m.groups() if g)
        fuera.add(f"puerto:{p}")
    return frozenset(fuera)


class Cerrojos:
    """Un lock por recurso, tomados SIEMPRE en orden alfabético.

    El orden no es cosmético: dos varas que piden `{:8080, datadir}` y `{datadir, :8080}`
    en órdenes distintos se abrazan y el arnés se cuelga para siempre — un deadlock en la
    suite es peor que la suite lenta, porque no se nota hasta que alguien espera dos horas
    a que termine algo que no va a terminar.
    """

    def __init__(self):
        self._m = threading.Lock()
        self._locks: dict = {}

    def _lock(self, r):
        with self._m:
            return self._locks.setdefault(r, threading.Lock())

    def tomar(self, recursos):
        for r in sorted(recursos):
            self._lock(r).acquire()

    def soltar(self, recursos):
        for r in sorted(recursos, reverse=True):
            self._lock(r).release()


#: Lo que se copia del datadir real a la copia de trabajo. Mismo criterio y mismo motivo
#: que `qa/suite_instalada.mjs`: las CREDENCIALES y las sesiones de verdad tienen que
#: viajar —si no, las varas miden una app vacía— y los WAL/SHM van con el `.db` porque
#: copiar sólo el `.db` deja afuera lo que todavía no hizo checkpoint y la copia arranca con
#: una foto vieja. `run_outputs/` NO viaja: son 1.500 carpetas de salidas históricas que
#: ninguna vara lee para decidir.
_COPIAR_ARCHIVOS = ("aleph.db", "aleph.db-wal", "aleph.db-shm", "motor_estado.json")
_COPIAR_DIRS = ("secrets", "modelos", "espacios", "catalog", "safety")


def _datadir_de_trabajo() -> tuple:
    """(ruta de la copia, ruta del real). O `(None, real)` si ya venía redirigido.

    ⚠️ ESTE ARNÉS ESCRIBÍA EN LA `aleph.db` DE VERDAD. Las varas que tocan el datadir están
    DECLARADAS acá abajo (`_EXTRA`, seis entradas), pero declararlas sólo las serializaba
    entre ellas: seguían escribiendo en el datadir del usuario.

    MEDIDO el 2026-08-06, UNA corrida completa de este arnés sobre la DB real:

        users 1.458 → 1.483 (+25)   ·  keys 431 → 444 (+13)
        puppets 1.315 → 1.356 (+41) ·  runs 1.939 → 1.991 (+52)

    Las llaves nuevas con la MISMA firma de fixture de siempre (`openai`/…ings ·
    `gemini`/…line · `prueba-fusion`/…3456). Es exactamente el mismo delta que
    `qa/suite_instalada.mjs` dejaba antes de su arreglo del 2026-08-06 (`d68bc7d`): aquél
    cerró UNA puerta, y ésta —la que corre 114 varas— quedó abierta.

    Si el llamante ya puso `ALEPH_DATA_DIR`, se respeta y no se copia nada: hay varas que
    aíslan su propio datadir a propósito (`verify_byo_headers`) y el arnés no las pisa.
    """
    if os.environ.get("ALEPH_DATA_DIR"):
        return None, os.environ["ALEPH_DATA_DIR"]
    real = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "Aleph")
    copia = tempfile.mkdtemp(prefix="aleph-varas-")
    if os.path.isdir(real):
        for f in _COPIAR_ARCHIVOS:
            try:
                shutil.copy2(os.path.join(real, f), os.path.join(copia, f))
            except OSError:
                pass                                  # opcional: no todos existen siempre
        for d in _COPIAR_DIRS:
            try:
                shutil.copytree(os.path.join(real, d), os.path.join(copia, d),
                                dirs_exist_ok=True)
            except OSError:
                pass
    return copia, real


def _correr(py: str, rel: str, cerrojos: Cerrojos, recursos: frozenset,
            datadir: str = "") -> tuple:
    cerrojos.tomar(recursos)
    t0 = time.time()
    entorno = {**os.environ, "ALEPH_DATA_DIR": datadir} if datadir else None
    try:
        p = subprocess.run([py, rel], cwd=ROOT, capture_output=True, text=True,
                           timeout=TIMEOUT_S, env=entorno)
        rc = p.returncode
    except subprocess.TimeoutExpired:
        rc = 124
        _barrer_mutantes(t0)
    except Exception:                                      # noqa: BLE001
        rc = 125
    finally:
        cerrojos.soltar(recursos)
    return rel, rc, time.time() - t0


#: MEDIDO el 2026-09-11: el disco pasó de 7,3 GiB libres a CERO en dos corridas de este
#: arnés. Las varas de mutantes (`verify_*_mutantes.py`) copian el árbol ENTERO a un
#: `mkdtemp(prefix="mut-…")` (≈1,2 GiB cada copia) y lo borran al terminar — pero el timeout
#: de 120 s las mata con SIGKILL y el `rmtree` del final nunca corre. Doce copias de un
#: solo día (tres corridas) = 9,2 GiB. El hijo no puede limpiar lo que no le dejan terminar:
#: limpia el padre, y SÓLO lo que nació durante esa vara (mtime ≥ t0), nunca lo ajeno.
def _barrer_mutantes(t0: float) -> None:
    raiz = tempfile.gettempdir()
    try:
        nombres = os.listdir(raiz)
    except OSError:
        return
    for n in nombres:
        if not n.startswith("mut-"):
            continue
        d = os.path.join(raiz, n)
        try:
            if os.path.isdir(d) and os.stat(d).st_mtime >= t0 - 1:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--serie", action="store_true", help="una por vez (la base de comparación)")
    ap.add_argument("-n", type=int, default=0, help="workers (0 = auto)")
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--salida", default="")
    ap.add_argument("--comparar", default="",
                    help="archivo de una corrida previa: compara veredicto POR NOMBRE")
    a = ap.parse_args()

    # [H5] 140 varas `.mjs` importan playwright, y `node_modules` no está en git: en un
    # worktree recién creado todas morían con ERR_MODULE_NOT_FOUND —un stack de Node, que
    # no es un rojo ni un verde. Se enlaza al del árbol principal antes de correr nada.
    sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
    import deps_node  # noqa: E402
    _listo, _motivo = deps_node.asegurar_node_modules()
    print(("  ✓ node_modules · " if _listo else "  ⚠ node_modules · ") + _motivo)

    varas = _varas()
    # ⚠️ 4 performance + 4 efficiency en esta máquina. `auto` deja UNO libre a propósito:
    # con los 8 tomados, el propio arnés compite con las varas por CPU y los timeouts de
    # 120 s empiezan a dispararse por contención — un rojo que no es del código.
    workers = 1 if a.serie else (a.n or max(2, (os.cpu_count() or 4) - 1))

    cerrojos = Cerrojos()
    mapa = {v: recursos_de(v) for v in varas}
    compartidos = {}
    for v, rs in mapa.items():
        for r in rs:
            compartidos.setdefault(r, []).append(v)
    en_conflicto = {r: vs for r, vs in compartidos.items() if len(vs) > 1}

    copia, real = _datadir_de_trabajo()

    print(f"══ {len(varas)} varas · {workers} worker(s) "
          f"({'SERIE' if a.serie else 'PARALELO'}) ══")
    if copia:
        print(f"  datadir: COPIA en {copia}")
        print(f"           (el real, {real}, NO se toca)")
    else:
        print(f"  datadir: {real}  ← heredado, ALEPH_DATA_DIR ya venía puesto")
    print(f"  recursos compartidos por 2+ varas: {len(en_conflicto)}")
    for r, vs in sorted(en_conflicto.items(), key=lambda kv: -len(kv[1]))[:6]:
        print(f"    {r:16} ← {len(vs)} varas")

    t0 = time.time()
    filas = []
    if workers == 1:
        for v in varas:
            filas.append(_correr(a.python, v, cerrojos, mapa[v], copia or ""))
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(_correr, a.python, v, cerrojos, mapa[v], copia or "")
                    for v in varas]
            for f in futs:
                filas.append(f.result())
    total = time.time() - t0

    filas.sort(key=lambda x: x[0])
    verdes = sum(1 for _r, rc, _t in filas if rc == 0)
    lineas = [f"exit={rc} {rel}" for rel, rc, _t in filas]
    lineas.append(f"== {'serie' if a.serie else 'paralelo'} :: {len(filas)} varas · "
                  f"verdes={verdes} · {total:.1f}s ==")
    texto = "\n".join(lineas) + "\n"
    if a.salida:
        Path(a.salida).write_text(texto, encoding="utf-8")
    print(f"\n  {len(filas)} varas · verdes={verdes} · {total:.1f}s")
    lentas = sorted(filas, key=lambda x: -x[2])[:5]
    print("  las 5 más lentas: " + ", ".join(f"{Path(r).name}={t:.0f}s" for r, _c, t in lentas))

    if copia:
        shutil.rmtree(copia, ignore_errors=True)               # la copia de trabajo no se acumula

    if a.comparar:
        # ⚠️ POR NOMBRE, JAMÁS POR POSICIÓN. Un diff línea a línea se desalinea en cuanto un
        # árbol tiene una vara que el otro no —ya pasó en esta serie— y entonces "difieren
        # todas" a partir de ahí, que es ruido disfrazado de hallazgo.
        previo = {}
        for linea in Path(a.comparar).read_text(encoding="utf-8").splitlines():
            if linea.startswith("exit="):
                rc, _sp, rel = linea.partition(" ")
                previo[rel.strip()] = int(rc[len("exit="):])
        ahora = {rel: rc for rel, rc, _t in filas}
        comunes = sorted(set(previo) & set(ahora))
        distintas = [(r, previo[r], ahora[r]) for r in comunes if previo[r] != ahora[r]]
        print(f"\n══ COMPARACIÓN contra {a.comparar} ══")
        print(f"  varas en las dos corridas: {len(comunes)}"
              f" · sólo antes: {len(set(previo)-set(ahora))}"
              f" · sólo ahora: {len(set(ahora)-set(previo))}")
        if distintas:
            print(f"  ❌ {len(distintas)} VEREDICTO(S) DISTINTO(S) — hay estado compartido "
                  f"que el mapa no declara:")
            for r, antes, despues in distintas:
                print(f"     {r}: serie={antes} → paralelo={despues}")
            print("  NO se adopta el paralelo hasta explicar cada uno. Aislamiento sí, "
                  "ablandamiento no.")
            return 1
        print(f"  ✅ los {len(comunes)} veredictos son IDÉNTICOS")

    # [H1] EL CINTURÓN. Cada vara que spawnea turnos ya llama a `higiene_store.vigilar()`,
    # (el enganche de `deps_node` va arriba, ANTES de correr nada — ver `main()`)
    # pero una vara que muera de una señal no corre su `atexit`. Acá se barre lo que haya
    # quedado, con los mismos dos candados: nacido en un temporal Y sin un solo `.jsonl`.
    sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
    import higiene_store  # noqa: E402  (tarde a propósito: sólo la invocación única lo usa)
    higiene_store.barrer()
    return 0


if __name__ == "__main__":
    sys.exit(main())
