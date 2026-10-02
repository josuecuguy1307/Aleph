"""sidecar_serve.py — CASA 2 · Fase 4 · 4.4.0 · el backend frozen como SIDECAR de Tauri.

Entrypoint del binario PyInstaller que el shell Tauri spawnea: corre uvicorn sirviendo
`app.main` (serving=C — el backend ES el origen: Home + Capa 0 + /v1) en 127.0.0.1:<port>.
Tauri espera a que el puerto responda y navega la webview a http://127.0.0.1:<port>/.

Port:  `--port N` | `--port=N` | env ALEPH_SIDECAR_PORT | default 8080.
Host:  env ALEPH_SIDECAR_HOST | 127.0.0.1 (local-only, jamás 0.0.0.0).
Rol:   ALEPH_ROLE=client por default (fail-closed), como el resto del cliente.

Corre igual congelado (`dist/aleph_sidecar/aleph_sidecar --port 8080`) o suelto
(`python deploy/fase4/sidecar_serve.py --port 8080`) para contrastar dev vs frozen.
"""
import functools
import glob
import os
import re
import subprocess
import sys
import threading
import time

from listener_handoff import inherited_loopback_listener as _inherited_loopback_listener

try:
    import pwd  # POSIX-only; en Windows no existe y el probe de login-shell no aplica
except ImportError:  # pragma: no cover — build no-Unix
    pwd = None  # type: ignore

os.environ.setdefault("ALEPH_ROLE", "client")

# ── EL DUEÑO DEL CICLO DE VIDA, ENCENDIDO (T1 · el piso con cinturón) ────────────────
# `platform/inspection/dueno.py` sostiene las conexiones MCP que el cinturón levanta, en
# vez de matarlas al terminar el run. Existía desde D1-D5, probado, y estaba en `off` por
# default: NINGÚN arranque real lo prendía (medido — cero hits en deploy/,
# start_caso3_stack.sh, main.py, infra/). Se prende ACÁ, que es el boot del producto.
#
# POR QUÉ AHORA: el piso de la Sala abre cinturón en cada conversación raw, y el arranque
# es EN SERIE (`session.py`: un `for` con `srv.start()` bloqueante). Sin sostén, cada turno
# vuelve a pagar el handshake completo.
#
# QUÉ AHORRA DE VERDAD — medido sobre el kit, no estimado. La clave del dueño es
# `(user_id, entity_id, huella)` y la huella incluye args + el env que la RECETA DECLARA
# (§9.2). Sobre los 6 del kit eso parte en dos mitades:
#   · huella ESTABLE, se reusan entre todas las charlas del mismo usuario:
#       markitdown (1.770 ms) · duckduckgo (563 ms) · fetch (813 ms)   → ~3.100 ms
#   · huella POR TURNO, no reusables y NO DEBEN serlo — llevan `${PUPPET_WORKDIR}`, que es
#     un `mkdtemp` por run: filesystem (allow-list en args) · sqlite (--db-path en args) ·
#     pysandbox (lo declara en env). Reusarlos le daría al turno N los archivos del N-1.
#     Que se re-spawneen es AISLAMIENTO, no desperdicio.
# ⇒ el dueño recupera ~54 % del arranque; la otra mitad sólo la arregla el eager spawn.
#
# EL TECHO DE 8: SE COMPORTA BIEN, PERO ESTÁ JUSTO. Esto cierra el [no medible], y la
# medición REFUTÓ la estimación previa («3 estables + 3 en rotación = 6 < 8»). Medido con
# el dueño real, 3 chats raw del mismo usuario sobre el kit:
#     spawns 12 · compartidas 6 · desalojos_lru 4 · sobrecupo 0 · vivas al cierre 8
# O sea: con TRES conversaciones ya se toca el techo y el LRU desaloja 4 veces. No escala
# por chat en las 3 estables (la clave no lleva `chat_id`, se reusaron 1 clave en 3 chats),
# pero las 3 atadas al workdir SÍ se acumulan: cada chat suma 3 que nadie va a reusar y que
# igual sobreviven `OCIOSIDAD_S` (600 s).
#
# POR QUÉ IGUAL SE PRENDE: el desalojo es CORRECTO. `sobrecupo` quedó en 0 y una conexión
# PRESTADA (refcount > 0) no la desaloja el techo (§D2) — un chat viejo NO puede matar el
# cinturón de uno activo, que era el riesgo a descartar. Lo que el techo tira es basura:
# los workdir de chats muertos.
#
# LO QUE QUEDA ABIERTO, con su número: mantener vivas las 3 atadas al workdir es gasto puro
# (~113 MB c/u por 600 s, sin posibilidad de reuso). El arreglo no es subir el techo — es
# que esas tres se cierren al llegar a refcount 0 en vez de esperar la ociosidad. Subir el
# techo a 12 daría 3 chats tibios a ~1,3 GB; cerrarlas temprano da lo mismo por ~0,4 GB.
# ⚠️ Y un turno raw SIN `user_id` rompe el reuso: `session.py` cae a `f"sesión:{id}"` como
# identidad, así que cada sesión anónima suma sus 6 en vez de compartir las 3 estables.
os.environ.setdefault("ALEPH_DUENO", "on")


# ── PATH REAL DEL USUARIO (GAP §Tauri-b · la vitrina no se vacía en Finder) ──────────
# Una .app lanzada desde Finder hereda el PATH mínimo de launchd
# (`/usr/bin:/bin:/usr/sbin:/sbin`). El sidecar hereda ESE PATH del shell Tauri
# (lib.rs::spawn_sidecar no setea env), así que `shutil.which("npx"|"uvx"|"node"|"docker")`
# devuelve None y la vitrina honesta (atoms_router.server_runtime) degrada 31/54 piezas a
# "Corre en tu máquina" — el catálogo se ve VACIADO respecto a dev. (La detección de
# cerebros CLI ya es PATH-inmune y NO se toca; esto sólo arregla la vitrina/catálogo.)
#
# Fix: en el boot del sidecar resolvemos el PATH REAL del usuario UNA vez (cacheado, no por
# request) y lo fundimos en os.environ["PATH"]. Se unen DOS fuentes:
#   (1) el PATH de login-shell (`$SHELL -l -c`), autoritativo y ya bien ordenado; y
#   (2) los directorios estándar (homebrew, /usr/local, ~/.local, shims de nvm/pyenv) —
#       IMPRESCINDIBLES porque `-l` (login, no-interactivo) NO sourcea .zshrc, donde nvm
#       inyecta su bin: sin (2), `npx`/`node` de nvm seguirían perdidos.
# Sólo AGREGA directorios (nunca saca /usr/bin:/bin) → no puede regresionar nada. No toca
# DB, puerto, auth ni brandface.

_STANDARD_PATH_DIRS = (
    "/opt/homebrew/bin", "/opt/homebrew/sbin",   # Homebrew (Apple Silicon)
    "/usr/local/bin", "/usr/local/sbin",         # Homebrew (Intel) · instalaciones manuales · docker
    "~/.local/bin",                              # pipx · pip --user · uv / uvx
    "~/.pyenv/shims",                            # pyenv (python/uvx gestionados)
)
# nvm/asdf no exponen un dir de shims estable → hay que globear el bin de cada versión.
_SHIM_GLOBS = (
    "~/.nvm/versions/node/*/bin",                # nvm → node · npx · npm
    "~/.asdf/shims",                             # asdf, si está instalado
)


def _login_shell() -> str:
    """El shell de login del usuario. En una .app de Finder `$SHELL` suele NO estar en el
    entorno → se cae al shell del /etc/passwd, y de última a un default de macOS."""
    sh = os.environ.get("SHELL")
    if sh and os.path.exists(sh):
        return sh
    if pwd is not None:
        try:
            sh = pwd.getpwuid(os.getuid()).pw_shell
            if sh and os.path.exists(sh):
                return sh
        except Exception:
            pass
    for cand in ("/bin/zsh", "/bin/bash", "/bin/sh"):
        if os.path.exists(cand):
            return cand
    return "/bin/sh"


def _child_env() -> dict:
    """Env para el subproceso del shell. Bajo PyInstaller, DYLD_*/LD_* apuntan a _MEIPASS:
    se RESTAURA el valor original (PyInstaller guarda `*_ORIG`) o se saca, para que el shell
    del sistema cargue sus dylibs de siempre y el probe no falle dentro del .app frozen."""
    env = dict(os.environ)
    for var in ("DYLD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES", "LD_LIBRARY_PATH"):
        orig = env.pop(var + "_ORIG", None)
        if orig is not None:
            env[var] = orig
        else:
            env.pop(var, None)
    return env


def _probe_login_path(timeout: float = 5.0) -> str:
    """`$SHELL -l -c 'echo $PATH'`: el shell de login sourcea los profiles donde se
    construye el PATH real (path_helper + homebrew + ~/.local). Best-effort: si falla o
    tarda, devuelve "" y quedan los dirs estándar. Nunca interactivo (`-i` cuelga / emite ruido)."""
    sh = _login_shell()
    try:
        r = subprocess.run(
            [sh, "-l", "-c", 'printf %s "$PATH"'],
            capture_output=True, text=True, timeout=timeout, env=_child_env(),
        )
        if r.returncode == 0:
            return (r.stdout or "").strip()
    except Exception:
        pass
    return ""


@functools.lru_cache(maxsize=1)
def resolve_user_path() -> str:
    """El PATH REAL del usuario: unión ordenada de (1) login-shell, (2) dirs estándar +
    shims, (3) el PATH heredado (para no perder NUNCA /usr/bin:/bin). Sólo dirs existentes.
    CACHEADO (lru_cache): la resolución —el subproceso al shell— corre UNA vez por boot,
    no por request. Tests: `resolve_user_path.cache_clear()` para re-medir otro entorno."""
    ordered: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        p = os.path.expanduser(raw)
        if p and p not in seen:
            seen.add(p)
            ordered.append(p)

    for p in _probe_login_path().split(os.pathsep):            # (1) autoritativo
        if p:
            add(p)
    for p in _STANDARD_PATH_DIRS:                              # (2) fallback estándar
        add(p)
    for pattern in _SHIM_GLOBS:                                # (2b) shims versionados (nvm/asdf)
        for p in sorted(glob.glob(os.path.expanduser(pattern)), reverse=True):
            add(p)
    for p in os.environ.get("PATH", "").split(os.pathsep):     # (3) heredado, al final
        if p:
            add(p)

    return os.pathsep.join(p for p in ordered if os.path.isdir(p))


def ensure_user_path() -> str:
    """Idempotente: funde el PATH real (cacheado) en os.environ["PATH"] y lo devuelve.
    Llamado en el boot del sidecar, arregla `shutil.which` para TODO el proceso → la
    vitrina clasifica igual que en un shell. Seguro de llamar más de una vez."""
    resolved = resolve_user_path()
    if resolved:
        os.environ["PATH"] = resolved
    return os.environ.get("PATH", "")


# ── STORE DE CAs (TLS Python-side en el .app) ───────────────────────────────────────
# El sidecar CONGELADO no arrastra el store de CAs del sistema (PyInstaller no incluye los
# paths de OpenSSL del SO), así que TODA HTTPS Python-side muere en la .app: el registro MCP
# (`/v1/catalog/search` → urllib) da "unreachable", y el puente premium cliente→control
# tampoco valida. Medido: con `SSL_CERT_FILE=/etc/ssl/cert.pem` el MISMO binario funciona.
# Fix: se empaqueta `certifi` en el .spec (cacert.pem) y acá, en el boot, se apunta
# SSL_CERT_FILE + REQUESTS_CA_BUNDLE a ese bundle. `setdefault` → un override explícito del
# operador gana. Robusto en frozen (bundle en _MEIPASS) y en dev (certifi.where()).
def ensure_ca_bundle() -> str:
    ca = ""
    try:
        import certifi
        ca = certifi.where()
    except Exception:
        ca = ""
    if not ca or not os.path.exists(ca):
        # frozen: si certifi.where() no resolvió, buscar el cacert.pem empaquetado en _MEIPASS.
        cand = os.path.join(getattr(sys, "_MEIPASS", ""), "certifi", "cacert.pem")
        if cand and os.path.exists(cand):
            ca = cand
    if ca and os.path.exists(ca):
        os.environ.setdefault("SSL_CERT_FILE", ca)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", ca)
    return os.environ.get("SSL_CERT_FILE", "")


# ══════════════════════════════════════════════════════════════════════════════════
# BARRIDO DE _MEI HUÉRFANOS  (ver reports/mei-huerfanos-debt.md)
# ══════════════════════════════════════════════════════════════════════════════════
# El sidecar es un onefile de PyInstaller: al arrancar se descomprime a un `_MEIxxxxxx`
# en $TMPDIR y el bootloader lo borra al salir. MEDIDO 2026-07-31 contra el binario
# instalado: con SIGTERM el directorio desaparece; con SIGKILL queda, 214 MB.
#
# Y el shell manda SIGKILL — `c.kill()` de Rust ES SIGKILL, no se puede atajar
# (`aleph-shell/src-tauri/src/lib.rs`, RunEvent::Exit). O sea que la fuga no es del
# «cierre sucio»: es de TODOS los cierres. Por eso van las dos cosas —el SIGTERM en el
# shell ataca la causa, y esto barre lo que igual va a quedar cuando haya un crash real,
# un force-quit o un OOM. En esta máquina se acumularon 9 GB y frenaron un build.
#
# LOS TRES CUIDADOS, cada uno con un mecanismo POSITIVO y no con una heurística:
#
#   no borrar el propio       se excluye `sys._MEIPASS` explícitamente.
#   no borrar el de otra app  cualquier binario onefile usa el mismo prefijo, así que
#                             la marca sale de MIRAR ADENTRO. Y las marcas se derivan de
#                             NUESTRO PROPIO directorio en tiempo de ejecución, no de una
#                             lista escrita a mano: si el .spec cambia lo que empaqueta,
#                             la huella cambia sola y no se desincroniza.
#   no borrar uno VIVO        `lsof` sobre los PID de procesos cuyo ejecutable es el
#                             nuestro devuelve los _MEI que alguien tiene abiertos.
#                             MEDIDO: 26 ms, y distingue exacto. Sin lock files ni
#                             contabilidad que pueda quedar rancia.
#
# FALLA CERRADO, siempre. Si no podemos confirmar nuestra propia huella, o si `lsof` no
# está o falla, NO SE BORRA NADA. El costo de no barrer es disco; el de borrar el
# directorio equivocado es matar un proceso vivo o romper otra aplicación.

#: Archivos que el .spec hace viajar como `datas` y que identifican al bundle de Aleph.
#: Se VERIFICAN contra el propio `_MEIPASS` antes de usarse como huella.
_MARCAS_ALEPH = ("platform/db/schema_sqlite.sql", "catalog/brand_domains.json")


def _mei_propio() -> str:
    """Nuestro directorio de extracción, o `""` si no estamos congelados."""
    return getattr(sys, "_MEIPASS", "") or ""


def _es_de_aleph(d: str) -> bool:
    """¿Este `_MEI` lo extrajo un bundle de Aleph? Se mira ADENTRO, no el nombre."""
    return all(os.path.exists(os.path.join(d, m)) for m in _MARCAS_ALEPH)


def _mei_abiertos_por(pids) -> set:
    """Los `_MEI` que estos PID tienen abiertos, según `lsof`. MEDIDO: 26 ms.

    Está separado de `_mei_vivos` para poder MEDIRLO: la autoverificación de allá abajo
    hace que, desde afuera del binario congelado, `_mei_vivos` siempre conteste «no sé» —
    lo cual es correcto, pero deja el camino positivo sin forma de probarse. Un barrido
    que contestara «no sé» SIEMPRE pasaría todos los tests negativos y no barrería nunca.
    """
    if not pids:
        return set()
    out = subprocess.run(["lsof", "-p", ",".join(str(p) for p in pids), "-Fn"],
                         capture_output=True, text=True, timeout=20)
    return {m.group(0) for m in re.finditer(r"/[^\s]*?/_MEI\w+", out.stdout)}


def _mei_vivos():
    """Los `_MEI` que un proceso tiene ABIERTOS ahora mismo, o `None` si no se pudo saber.

    Se consulta `lsof` acotado a los PID cuyo ejecutable es el nuestro — no un `lsof +D`
    sobre todo el árbol, que sería lento. MEDIDO: 26 ms.

    ⚠️ SE AUTOVERIFICA, y no es paranoia — es el fallo que ya pasó una vez. La detección
    depende de que `sys.executable` sea el binario del onefile, que es cierto congelado y
    NO es cierto corriendo suelto. Cuando no lo es, `ps` no matchea a nadie, la función
    devolvía un conjunto VACÍO, y vacío significa «no hay nada vivo» — o sea barra libre
    para borrar el directorio de un proceso que está andando. Medido en la vara: borró un
    `_MEI` que un proceso tenía abierto.

    La cura es que la función se busque a SÍ MISMA. Estamos corriendo: si el barrido no
    encuentra nuestro propio PID entre los procesos que cree nuestros, entonces no está
    mirando lo que cree, y la respuesta honesta es `None` — «no sé» — que hace que no se
    borre nada. Un conjunto vacío ahora significa de verdad «los vi a todos y ninguno
    tiene nada abierto».
    """
    try:
        # Se compara por BASENAME, no por ruta. MEDIDO: `ps -axo comm=` devuelve la ruta
        # completa para unos procesos («/Applications/Aleph.app/…/aleph_sidecar») y el
        # nombre pelado para otros («python3»), así que matchear por ruta pierde la mitad
        # — y perder procesos es justo lo que hace que un directorio vivo parezca muerto.
        # Congelado el basename es `aleph_sidecar`, que ya es específico; y si por un
        # homónimo entrara un proceso ajeno, el efecto sería NO borrar un directorio, que
        # es el lado seguro del error.
        yo = os.path.basename(os.path.realpath(sys.executable))
        ps = subprocess.run(["ps", "-axo", "pid=,comm="], capture_output=True,
                            text=True, timeout=5)
        pids = []
        for ln in ps.stdout.splitlines():
            partes = ln.strip().split(None, 1)
            if len(partes) == 2 and os.path.basename(partes[1].strip()) == yo:
                pids.append(partes[0])
        if str(os.getpid()) not in pids:
            return None                      # no me veo a mí mismo ⇒ no estoy viendo bien
        return _mei_abiertos_por(pids)
    except Exception:                                # noqa: BLE001 — falla CERRADO
        return None


def barrer_mei_huerfanos(*, dry_run: bool = False) -> dict:
    """Borra los `_MEI` de Aleph que no tiene abiertos nadie. Devuelve el censo.

    Nunca levanta: un fallo del barrido no puede impedir que la app arranque. Lo que no
    se pudo hacer vuelve en el reporte, que el caller loguea.
    """
    censo = {"propio": "", "candidatos": 0, "de_aleph": 0, "vivos": 0,
             "borrados": [], "bytes": 0, "omitido": None}
    propio = _mei_propio()
    censo["propio"] = propio
    if not propio:
        censo["omitido"] = "no estamos congelados: no hay nada que barrer"
        return censo
    if not _es_de_aleph(propio):
        # No podemos confirmar nuestra propia huella ⇒ no podemos reconocer la ajena.
        censo["omitido"] = f"el _MEI propio no tiene las marcas {_MARCAS_ALEPH}"
        return censo

    padre = os.path.dirname(propio)
    try:
        candidatos = [os.path.join(padre, n) for n in os.listdir(padre)
                      if n.startswith("_MEI") and os.path.isdir(os.path.join(padre, n))]
    except OSError as e:
        censo["omitido"] = f"no se pudo listar {padre}: {e}"
        return censo
    censo["candidatos"] = len(candidatos)

    de_aleph = [d for d in candidatos
                if os.path.realpath(d) != os.path.realpath(propio) and _es_de_aleph(d)]
    censo["de_aleph"] = len(de_aleph)

    vivos = _mei_vivos()
    if vivos is None:
        censo["omitido"] = "no se pudo determinar qué está vivo (lsof): no se borra nada"
        return censo
    vivos = {os.path.realpath(v) for v in vivos}
    censo["vivos"] = len(vivos)

    import shutil
    for d in de_aleph:
        if os.path.realpath(d) in vivos:
            continue
        try:
            n = sum(os.path.getsize(os.path.join(r, f))
                    for r, _, fs in os.walk(d) for f in fs
                    if os.path.exists(os.path.join(r, f)))
        except OSError:
            n = 0
        if dry_run:
            censo["borrados"].append(d)
            censo["bytes"] += n
            continue
        try:
            shutil.rmtree(d, ignore_errors=True)
            if not os.path.exists(d):
                censo["borrados"].append(d)
                censo["bytes"] += n
        except Exception:                            # noqa: BLE001 — nunca tumba el boot
            pass
    return censo


def _argval(name: str):
    """Lee `--name V` o `--name=V` de argv; None si no está."""
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == name and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None


def _port() -> int:
    v = _argval("--port")
    if v is not None:
        return int(v)
    return int(os.environ.get("ALEPH_SIDECAR_PORT", "8080"))


def _watch_parent(parent_pid: int, on_parent_exit=None) -> None:
    """CERO HUÉRFANOS: bajo onefile de PyInstaller el bootloader forkea este proceso, así
    que un kill del bootloader por parte del shell Tauri deja a ESTE uvicorn huérfano. Este
    watchdog vigila el PID del shell (el proceso Rust) DIRECTAMENTE —inmune al doble-proceso—
    y se apaga cuando el padre desaparece (cierre normal, crash o SIGKILL). `kill(pid,0)`
    no envía señal: solo comprueba existencia. El cierre es GRACIOSO para que el
    lifecycle termine cualquier `claude`/`codex` activo antes de salir."""
    while True:
        try:
            os.kill(parent_pid, 0)
        except (ProcessLookupError, OSError):
            print(f"[sidecar] el shell (pid {parent_pid}) murió — cerrando (anti-huérfano)", flush=True)
            if on_parent_exit:
                on_parent_exit()
            return
        time.sleep(0.25)


def _check_forge() -> int:
    """[4.4.3] Sonda de PRESENCIA del moat EN EL ARTEFACTO (no en la config): intenta importar
    el Motor B (forge). En public/dev el `.spec` lo excluye → ImportError → ABSENT; en founder
    viaja → PRESENT. Imprime el veredicto y sale. Verifica el criterio en el binario, no en flags."""
    try:
        import app.phase1.forge_router  # noqa: F401
        from inspection.loop import engine  # noqa: F401  (una pieza FORGE núcleo)
        print("FORGE: PRESENT", flush=True)
        return 0
    except Exception as e:
        print(f"FORGE: ABSENT ({type(e).__name__})", flush=True)
        return 1


def main() -> None:
    # ── EL PUENTE BYO, ANTES QUE NADA ────────────────────────────────────────────────
    # Toda pieza HTTP del usuario se levanta como un server MCP stdio, y congelado ese
    # server lo sirve ESTE binario (`--byo-mcp <manifest>`): el python3 del sistema no
    # puede leer el PYZ, así que hacerlo viajar como script nunca iba a alcanzar — medido
    # en la Obra 6a, el archivo llegaba y moría en `from inspection import transporte`.
    #
    # ⚠️ VA PRIMERO, ANTES DE CUALQUIER `print`. El puente habla JSON-RPC por **stdout**;
    # una sola línea nuestra ahí adentro (el `[sidecar] PATH del usuario resuelto: …` de
    # veinte líneas más abajo, sin ir más lejos) corrompe el protocolo y el server queda
    # «sin saludo» — el mismo síntoma de siempre, con otra causa y más difícil de ver.
    if not getattr(sys, "frozen", False):
        _plat = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "platform")
        if _plat not in sys.path:
            sys.path.insert(0, _plat)
    import puente_sidecar
    if puente_sidecar.atender_si_es_puente():
        return

    if "--check-forge" in sys.argv[1:]:
        raise SystemExit(_check_forge())

    # GAP §Tauri-b: recuperar el PATH real del usuario ANTES de importar la app y de
    # arrancar el cli_brain, para que la vitrina (server_runtime → shutil.which) clasifique
    # igual que en shell y no degrade 31/54 piezas a "corre en tu máquina" bajo Finder.
    applied = ensure_user_path()
    print(f"[sidecar] PATH del usuario resuelto: "
          f"{len([p for p in applied.split(os.pathsep) if p])} dirs", flush=True)

    # TLS: apuntar el store de CAs al bundle de certifi ANTES de cualquier HTTPS (registro
    # MCP, puente premium) — si no, el sidecar congelado da "unreachable" contra todo HTTPS.
    ca = ensure_ca_bundle()
    print(f"[sidecar] CA bundle: {ca or '(no encontrado — HTTPS puede fallar)'}", flush=True)

    # Barrido de _MEI huérfanos. En un hilo: borrar 200 MB tarda, y no hay razón para que
    # el usuario espere por basura del arranque anterior. Daemon a propósito — si la app
    # se cierra a mitad del borrado queda un directorio comido por la mitad, que sigue
    # siendo basura y lo termina el barrido siguiente.
    def _barrer():
        c = barrer_mei_huerfanos()
        if c["omitido"]:
            print(f"[sidecar] barrido _MEI omitido: {c['omitido']}", flush=True)
        elif c["borrados"]:
            print(f"[sidecar] barrido _MEI: {len(c['borrados'])} huérfanos borrados, "
                  f"{c['bytes'] / 1e6:.0f} MB liberados "
                  f"({c['de_aleph']} de Aleph, {c['vivos']} vivos intactos)", flush=True)
        else:
            print(f"[sidecar] barrido _MEI: nada que borrar "
                  f"({c['candidatos']} candidatos, {c['vivos']} vivos)", flush=True)
    threading.Thread(target=_barrer, name="aleph-mei-sweep", daemon=True).start()

    # La capability es efímera por launch y permanece sólo en memoria del backend.
    host = os.environ.get("ALEPH_SIDECAR_HOST", "127.0.0.1")
    port = _port()
    fd_arg = _argval("--listen-fd")
    if _argval("--launch-cap-stdin") is not None and fd_arg is None:
        raise RuntimeError("desktop sidecar requires inherited loopback listener")
    inherited_socket = _inherited_loopback_listener(port, fd_arg)
    if inherited_socket is not None:
        host = "127.0.0.1"
    os.environ["ALEPH_SIDECAR_PORT"] = str(port)
    # La capability no viaja en argv (visible a procesos del mismo usuario). El shell
    # entrega una sola línea por un pipe heredado y cierra el descriptor enseguida.
    launch_cap = ""
    if _argval("--launch-cap-stdin") is not None:
        try:
            candidate = sys.stdin.readline(256).strip()
            if re.fullmatch(r"[0-9a-f]{64}", candidate):
                launch_cap = candidate
        except Exception:
            launch_cap = ""
    os.environ.pop("ALEPH_LAUNCH_CAP", None)
    from app.launch_cap import install as install_launch_cap
    install_launch_cap(launch_cap)

    import uvicorn
    from app.main import app  # frozen: pathex/hiddenimports del .spec cierran el import
    from cli_brain.lifecycle import (start_managed_service, stop_managed_service,
                                     stop_managed_service_detallado)

    cli_state = start_managed_service()
    print(f"[sidecar] cli_brain state={cli_state.get('state')} mode={cli_state.get('mode')} "
          f"detail={cli_state.get('detail')}", flush=True)
    print(f"[sidecar] uvicorn {host}:{port} (ALEPH_ROLE={os.environ.get('ALEPH_ROLE')}, "
          f"frozen={getattr(sys, 'frozen', False)})", flush=True)
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)

    def _request_shutdown() -> None:
        server.should_exit = True
        # No esperar a que uvicorn drene una request que está bloqueada en el CLI: cortar
        # primero el listener y el grupo `claude`/`codex`; la request vuelve con error y
        # el server puede completar su cierre.
        stop_managed_service()

    # Anti-huérfano: si el shell Tauri muere, pedir salida al server (no os._exit) para
    # ejecutar el finally que cierra :8926 y mata procesos CLI registrados.
    pp = _argval("--parent-pid")
    if pp:
        threading.Thread(
            target=_watch_parent,
            args=(int(pp), _request_shutdown),
            name="aleph-parent-watch",
            daemon=True,
        ).start()

    try:
        try:
            server.run(sockets=[inherited_socket] if inherited_socket is not None else None)
        except KeyboardInterrupt:
            pass
    finally:
        # F2d, cable 3 de 3 · FORCE-EXIT. `stop_detallado()` acota la fase crítica y NOMBRA
        # el paso que quedó colgado, pero no mata el proceso: eso es una biblioteca y el
        # proceso es de otro. **Acá sí somos el dueño del proceso.**
        #
        # `os._exit` y no `sys.exit` a propósito: si un paso quedó colgado hay un hilo
        # no-daemon o un handler bloqueado, y una salida limpia ESPERARÍA por ellos — que es
        # exactamente lo que este cable viene a impedir. Un ⌘Q que tarda medio minuto lo
        # termina matando el usuario a la fuerza, y ahí sí quedan huérfanos.
        parte = stop_managed_service_detallado()
        print(f"[sidecar] cli_brain detenido; procesos CLI terminados={parte['matados']}",
              flush=True)
        if parte.get("colgado"):
            print(f"[sidecar] cierre colgado en «{parte['colgado']}» — salida forzada",
                  flush=True)
            os._exit(0)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--inspect-watchdog":
        import signal
        seconds = int(os.environ["ALEPH_INSPECT_HARD_TIMEOUT_S"])
        if seconds < 1 or os.getpgrp() <= 1:
            raise SystemExit("inspection watchdog requires a valid process group")
        print("READY", flush=True)
        time.sleep(seconds)
        os.killpg(os.getpgrp(), signal.SIGKILL)
    elif len(sys.argv) > 1 and sys.argv[1] == "--inspect-runner":
        import runpy
        from pathlib import Path
        sys.argv = [sys.argv[0], *sys.argv[2:]]
        root = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
        runpy.run_path(str(root / "platform" / "inspection" / "inspect_run.py"), run_name="__main__")
    else:
        main()
