#!/usr/bin/env python3
"""base.py — el CONTRATO CliBrainProvider (BYO-CLI · D1).

Una interface, N CLIs. Todo lo que existe para un provider existe para el otro
(regla de simetría del mandato): detect() honesto de 3 estados, invoke() puro
completion in/out con las tools del CLI apagadas, clasificación de errores en
(rate_limit | no_auth | not_installed | timeout | model_error), y model_final
REAL reportado por el CLI.

Fail-closed de seguridad: assert_argv_safe() corre en CADA invoke — si un flag
de bypass de permisos aparece en el argv, el provider REVIENTA antes de spawnear.

Gate 2 · F2d: todo turno tiene FICHA (`TurnoVivo`) y por lo tanto se puede DETENER
(`stop_turn`) y ANOTAR en el registro persistente (`registro.py`). Un spawn sin ficha
es un huérfano en potencia que nadie puede matar.
"""
from __future__ import annotations

import os
import glob
import json
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from typing import Optional

# Estados de detección. La ausencia de una prueba de auth no equivale a logout.
STATE_READY = "ready"                # instalado + autenticado → opción viva
STATE_NO_AUTH = "no_auth"            # el CLI confirmó que no hay sesión
STATE_AUTH_EXPIRED = "auth_expired"    # el CLI confirmó que la sesión venció
STATE_NOT_INSTALLED = "not_installed"  # binario ausente → apagada con razón
STATE_AUTH_UNKNOWN = "auth_unknown"  # el chequeo falló o no dio una respuesta reconocible
STATE_CONFIG_INVALID = "config_invalid"  # ruta manual/override inválida
STATE_ACCESS_DENIED = "access_denied"  # autenticado, pero el proveedor niega acceso

# Clasificación de errores de invoke() (D1/D4).
ERR_RATE_LIMIT = "rate_limit"        # ventana de la suscripción agotada → 429 narrable
ERR_NO_AUTH = "no_auth"              # sesión caída a mitad de vuelo
ERR_AUTH_EXPIRED = "auth_expired"    # sesión vencida, reautenticación necesaria
ERR_AUTH_UNKNOWN = "auth_unknown"    # el sondeo posterior no fue concluyente
ERR_PROVIDER = "provider_error"      # proveedor falló sin evidencia de auth/acceso/modelo
ERR_NOT_INSTALLED = "not_installed"  # binario desapareció / no está
ERR_CONFIG_INVALID = "config_invalid"  # ejecutable manual o override inválido
ERR_ACCESS_DENIED = "access_denied"  # política/entitlement del proveedor (403 probado)
ERR_SERVICE_UNAVAILABLE = "service_unavailable"  # sobrecarga/503/529 del proveedor
ERR_MODEL_UNAVAILABLE = "model_unavailable"  # el proveedor rechaza ese modelo explícito
ERR_TIMEOUT = "timeout"              # el CLI no respondió a tiempo
ERR_MODEL = "model_error"            # el modelo/entitlement rechazó (p.ej. cuenta sin plan)
ERR_DETENIDO = "detenido"            # F2d · alguien pidió parar el turno (stop_turn)
ERR_SESION_PERDIDA = "sesion_perdida"  # F2e · el CLI ya no tiene esa conversación

# Flags PROHIBIDOS en el argv de cualquier provider (anti-fuga del loop).
# El wrapper es pura cognición; un CLI con permisos bypass = anti-Aleph total.
FORBIDDEN_FLAGS = frozenset({
    "--dangerously-skip-permissions",
    "--allow-dangerously-skip-permissions",
    "--dangerously-bypass-approvals-and-sandbox",
    "--full-auto",
})

DEFAULT_TIMEOUT = float(os.environ.get("PUPPET_CLI_BRAIN_TIMEOUT", "180"))
DETECT_TIMEOUT = float(os.environ.get("PUPPET_CLI_BRAIN_DETECT_TIMEOUT", "20"))

# ── ATRIBUCIÓN DE COSTO (review HIGH #0/#15) · ENV ALLOWLIST del spawn ────────────
# El CLI del usuario NO puede heredar el env completo del proceso que lo spawnea:
#   (a) una ANTHROPIC_API_KEY/OPENAI_API_KEY ambiente (dev, sesión de eval) haría que
#       el CLI facture POR TOKEN a esa key en vez de la SUSCRIPCIÓN → cost-event miente
#       $0 y `claude auth status` da READY con authMethod:api_key (false-green PROBADO);
#   (b) los secretos de infra/.env (GROQ/OPENROUTER/GEMINI/LITELLM/PG/TELEGRAM) que el
#       backend carga viajarían al proceso hijo. Allowlist estricta: solo lo que el CLI
#       necesita para encontrar SU auth (OAuth/keychain via HOME) y correr. Cualquier
#       key API queda AFUERA → la cognición cae sí o sí en la suscripción (o falla honesto).
_ENV_ALLOW = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "TERM", "TMPDIR", "TZ",
    "LANG", "LANGUAGE",
    # dirs de config/estado de cada CLI (auth OAuth vive acá; NO son keys)
    "CLAUDE_CONFIG_DIR", "CODEX_HOME", "GROK_HOME",
    "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR",
    # red/TLS/proxy corporativo (para que el CLI llegue a su provider)
    "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS",
    "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy",
    # overrides propios del BYO-CLI (binario/modelo elegidos por Aleph)
    "PUPPET_CLAUDE_BIN", "PUPPET_CODEX_BIN", "PUPPET_GROK_BIN",
    "PUPPET_CLAUDE_CLI_MODEL", "PUPPET_CODEX_CLI_MODEL", "PUPPET_GROK_CLI_MODEL",
})
_ENV_ALLOW_PREFIX = ("LC_",)


def sanitized_env(binary: Optional[str] = None) -> dict:
    """Env MÍNIMO para spawnear el CLI: solo la allowlist (+ LC_*). Jamás keys API ni
    secretos de infra — así la cognición se atribuye a la SUSCRIPCIÓN, no a una key
    ambiente, y ningún secreto del backend fuga al proceso hijo."""
    out = {k: v for k, v in os.environ.items()
           if k in _ENV_ALLOW or k.startswith(_ENV_ALLOW_PREFIX)}
    out.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    # Finder no abre una login shell: su PATH suele omitir Homebrew/NVM. Si encontramos
    # el CLI por una ubicación conocida, anteponemos SU directorio al env saneado para
    # que un launcher con shebang `#!/usr/bin/env node` encuentre el node hermano. No
    # ejecutamos shell profiles (podrían correr código/hooks arbitrarios) ni ampliamos la
    # allowlist de secretos.
    if binary:
        bindir = os.path.dirname(os.path.abspath(os.path.expanduser(binary)))
        parts = [bindir] + [p for p in out["PATH"].split(os.pathsep) if p]
        out["PATH"] = os.pathsep.join(dict.fromkeys(parts))
    return out


def _usable_binary(path: str) -> Optional[str]:
    """Ruta ejecutable absoluta, o None. Los symlinks son válidos (npm/NVM los usa)."""
    p = os.path.abspath(os.path.expanduser(path or ""))
    return p if os.path.isfile(p) and os.access(p, os.X_OK) else None


def _common_binary_candidates(name: str) -> list[str]:
    """Ubicaciones de CLIs instalados por gestores comunes, sin ejecutar shell profiles.

    El orden privilegia shims estables del usuario y luego versiones Node explícitas. Los
    globs se ordenan descendente para elegir la instalación más reciente cuando NVM/FNM
    conserva varias versiones.
    """
    fixed = [
        f"~/.local/bin/{name}",
        f"~/.npm-global/bin/{name}",
        f"~/.volta/bin/{name}",
        f"~/.asdf/shims/{name}",
        f"~/.local/share/mise/shims/{name}",
        f"~/.bun/bin/{name}",
        f"~/bin/{name}",
        f"/opt/homebrew/bin/{name}",
        f"/usr/local/bin/{name}",
    ]
    patterns = [
        f"~/.nvm/versions/node/*/bin/{name}",
        f"~/.local/share/fnm/node-versions/*/installation/bin/{name}",
        f"~/Library/Application Support/fnm/node-versions/*/installation/bin/{name}",
    ]
    versioned: list[str] = []
    for pattern in patterns:
        versioned.extend(glob.glob(os.path.expanduser(pattern)))
    return [os.path.expanduser(p) for p in fixed] + sorted(set(versioned), reverse=True)


# Todos los subprocess de cognición/detección viven en grupos propios y quedan registrados.
# El sidecar los termina al apagarse, incluida la ruta "shell Tauri murió". Esto evita que
# `claude`/`codex` sobrevivan como procesos huérfanos si la app cierra durante un completion.
_ACTIVE_PROCESSES: dict[int, subprocess.Popen] = {}
_ACTIVE_LOCK = threading.Lock()


def _register_process(proc: subprocess.Popen) -> None:
    with _ACTIVE_LOCK:
        _ACTIVE_PROCESSES[proc.pid] = proc


def _unregister_process(proc: subprocess.Popen) -> None:
    with _ACTIVE_LOCK:
        _ACTIVE_PROCESSES.pop(proc.pid, None)


def _terminate_process(proc: subprocess.Popen, *, grace: float = 1.5) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGTERM)
        else:
            proc.terminate()
        proc.wait(timeout=grace)
        return
    except (ProcessLookupError, subprocess.TimeoutExpired, OSError):
        pass
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
        proc.wait(timeout=1.0)
    except (ProcessLookupError, subprocess.TimeoutExpired, OSError):
        pass


def terminate_active_processes() -> int:
    """Termina todos los CLIs propiedad de este sidecar. Devuelve cuántos encontró vivos.

    F2d · además cierra los TURNOS abiertos, lo que borra sus filas del
    `cli_procesos.jsonl`. Un cierre ordenado tiene que dejar el registro vacío: si dejara
    filas, el próximo arranque saldría a barrer procesos que este cierre ya mató, y el pid
    anotado para entonces puede ser de un tercero.
    """
    with _ACTIVE_LOCK:
        procs = list(_ACTIVE_PROCESSES.values())
    alive = [p for p in procs if p.poll() is None]
    for proc in alive:
        _terminate_process(proc)
        _unregister_process(proc)
    for tid in [t.id for t in turnos_vivos()]:
        cerrar_turno(tid)
    return len(alive)


# ══ TURNOS DETENIBLES (Gate 2 · F2d) ═══════════════════════════════════════════════
# EL AGUJERO QUE CIERRA: hasta acá, un turno lanzado NO SE PODÍA PARAR. El usuario que
# aprieta «detener» en la Sala se quedaba mirando cómo su suscripción sigue quemándose
# hasta el timeout de 180 s, y el slot de F2b quedaba tomado todo ese tiempo, así que
# tampoco podía mandar otra cosa. `_ACTIVE_PROCESSES` sabía matar TODO (cierre de la app),
# nunca UNO.
#
# LA SECUENCIA es la de `CLITrigger.stopClaude` (`src/server/services/claude-manager.ts`
# :466-505, MIT © 2026 Changjin Lee), reescrita en Python sobre nuestro modelo de procesos:
#
#   1. cerrar stdin      — el CLI ve EOF y puede terminar solo, sin señal
#   2. SIGTERM AL GRUPO  — allá es `tree-kill` (necesario en Windows, donde `shell: true`
#                          envuelve el CLI en cmd.exe); acá cada spawn ya nace en su propia
#                          sesión (`start_new_session=True`), así que el grupo ES el árbol
#                          y `killpg` alcanza — sin dependencia externa
#   3. CONFIRMAR POR POLLING — no se asume que murió porque se mandó la señal
#   4. SIGKILL a los 5 s — el que ignora SIGTERM igual se va
#   5. DEADLINE PROPIO a los 7 s — **resuelve SIEMPRE**. Un `stop` que puede colgarse no
#      es un `stop`: quien lo llamó (el endpoint HTTP) tiene que poder contestar.
#
# El slot de F2b se libera pase lo que pase, y no por algo que hagamos acá: el `finally`
# del server suelta el turno cuando `invoke` vuelve, y `invoke` vuelve porque el proceso
# murió. La vara lo verifica por el único camino que prueba algo: mandando el turno
# siguiente y viendo que entra.
#
#   HUECO CERRADO EN F1c (era el tercero, después de `cli_ocupado` de F2b y de
#   `contexto_excedido`/`politica_de_contenido` de F1). Decía: «falta una causa
#   `turno_detenido` en `motor_verdad`. Un turno que alguien paró NO es un fallo — no es
#   del proveedor, no es de la persona, y `falla_de_aleph` diría que nuestro wrapper se
#   rompió cuando en realidad hizo exactamente lo que se le pidió. Por eso el BrainResult
#   de un turno detenido sale con `error_kind=ERR_DETENIDO` y **sin causa**: inventar una
#   que mienta es peor que declarar el hueco».
#   Ahora la causa existe y el BrainResult la lleva (ver `_detenido`); `error_kind` sigue
#   siendo `ERR_DETENIDO`, byte por byte, porque el server lo mapea a su 409 tipado.

#: A los cuántos segundos escala a SIGKILL (CLITrigger: 5 s).
STOP_KILL_S = float(os.environ.get("PUPPET_CLI_STOP_KILL", "5"))
#: Deadline propio del `stop`: a los cuántos segundos resuelve pase lo que pase (7 s).
STOP_DEADLINE_S = float(os.environ.get("PUPPET_CLI_STOP_DEADLINE", "7"))
#: Cada cuánto se pregunta si murió. CLITrigger usa 200 ms.
STOP_POLL_S = float(os.environ.get("PUPPET_CLI_STOP_POLL", "0.2"))
#: Cuánto se espera a que aparezca el proceso de un turno que todavía estaba naciendo.
STOP_GRACIA_SPAWN_S = 0.5

#: Los dos resultados del `stop`. Vocabulario cerrado, como todo lo demás de Gate 2.
TURNO_DETENIDO = "turno_detenido"
NO_HABIA_TURNO = "no_habia_turno"


class TurnoVivo:
    """UN turno de cognición en vuelo. Sin `@dataclass` a propósito: este módulo se puede
    cargar por ruta (`aleph_paths.load_module_by_path`) y ahí `@dataclass` revienta."""

    __slots__ = ("id", "provider", "abierto_en", "proc", "detener_pedido", "detenido_en")

    def __init__(self, id: str, provider: str, abierto_en: float):
        self.id = id
        self.provider = provider
        self.abierto_en = abierto_en
        self.proc: Optional[subprocess.Popen] = None
        self.detener_pedido = False
        self.detenido_en: Optional[float] = None

    def como_dict(self) -> dict:
        p = self.proc
        return {"turno_id": self.id, "provider": self.provider,
                "edad_s": round(time.time() - self.abierto_en, 1),
                "pid": p.pid if p is not None else None,
                "spawneado": p is not None,
                "detener_pedido": self.detener_pedido}


_TURNOS: dict[str, TurnoVivo] = {}
_TURNOS_LOCK = threading.Lock()


def abrir_turno(turno_id: Optional[str], provider_id: str) -> TurnoVivo:
    """Registra un turno y devuelve su ficha. **El id devuelto manda.**

    Si el id pedido ya está vivo, se le agrega un sufijo en vez de fallar: un id repetido
    es un caso de borde del llamante (dos clientes que eligen el mismo string), y hacer
    fracasar un turno de cognición por eso sería desproporcionado. Quien llama tiene que
    usar `t.id`, no el que pidió — por eso esto devuelve la ficha y no un bool.
    """
    base = _id_limpio(turno_id) or ("turno-" + uuid.uuid4().hex[:12])
    with _TURNOS_LOCK:
        cand, n = base, 1
        while cand in _TURNOS:
            n += 1
            cand = f"{base}#{n}"
        t = TurnoVivo(cand, str(provider_id or "?"), time.time())
        _TURNOS[cand] = t
    return t


def cerrar_turno(turno_id: str) -> None:
    """Idempotente. Saca el turno de la tabla y su fila del registro persistente.

    ⚠️ SALVO QUE LA COLA ESTÉ EN EL COSECHADOR. Si el turno se cerró por evento terminal,
    el CLI todavía está vivo cerrando sus tuberías: su fila es el único rastro que un
    barrido de arranque podría seguir si el sidecar muriera en ese medio segundo. La borra
    el cosechador cuando el pid ya no existe, que es la misma regla de siempre («la muerte
    limpia borra»), aplicada donde ahora ocurre la muerte.
    """
    with _TURNOS_LOCK:
        t = _TURNOS.pop(str(turno_id), None)
    if t is not None:
        with _COSECHANDO_LOCK:
            en_cosecha = t.id in _COSECHANDO
        if not en_cosecha:
            _registro_borrar(t.id)


def turno(turno_id: str) -> Optional[TurnoVivo]:
    with _TURNOS_LOCK:
        return _TURNOS.get(str(turno_id))


def turnos_vivos() -> list:
    with _TURNOS_LOCK:
        return list(_TURNOS.values())


_ID_OK = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-")


def _id_limpio(v) -> str:
    """Un id de turno lo elige el CLIENTE, así que se sanea: viaja a `ps`, a los logs y a
    un archivo en disco. Sólo alfanuméricos y `._:-`, y 80 caracteres."""
    if not isinstance(v, str):
        return ""
    return "".join(c for c in v.strip() if c in _ID_OK)[:80]


def _cerrar_stdin(proc: subprocess.Popen) -> None:
    """Paso 1 de la secuencia. Hoy los spawns usan `stdin=DEVNULL` (el CLI no tiene que
    poder pedirnos nada interactivo), así que `proc.stdin` es None y esto no hace nada.
    Se escribe igual, y no por simetría: el día que un provider abra un stdin de verdad
    —el `stream-json` de entrada del binario ya lo permite— el EOF tiene que ser lo
    PRIMERO que el CLI vea, antes que cualquier señal."""
    pipe = getattr(proc, "stdin", None)
    if pipe is None:
        return
    try:
        pipe.close()
    except (OSError, ValueError):
        pass


def _senal_al_grupo(proc: subprocess.Popen, sig: int) -> bool:
    """La señal al GRUPO del proceso, que en nuestros spawns es su árbol entero.

    Sólo si el pid es líder de su grupo — lo es siempre por `start_new_session=True`, pero
    si alguna vez no lo fuera, ese grupo es de OTRO y mandarle una señal sería un desastre
    mucho peor que no matar un huérfano. Ahí se degrada al pid solo.
    """
    try:
        if os.name == "posix" and os.getpgid(proc.pid) == proc.pid:
            os.killpg(proc.pid, sig)
        else:
            os.kill(proc.pid, sig)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def _atar_proceso(t: Optional[TurnoVivo], proc: subprocess.Popen) -> None:
    """El proceso recién nacido queda atado a su turno.

    Y LA TRAMPA PARA EL FANTASMA: si mientras nacía alguien pidió detenerlo, el `stop` no
    tenía a quién matar y se fue. Sin esto, el turno seguiría corriendo 180 s después de
    que el usuario apretó «detener» — la ventana entre pedir el slot y tener un pid es
    chica pero existe, y es exactamente donde caen las cancelaciones rápidas.
    """
    if t is None:
        return
    t.proc = proc
    if t.detener_pedido:
        _cerrar_stdin(proc)
        _senal_al_grupo(proc, signal.SIGTERM)


def stop_turn(turno_id: str, *, kill_tras_s: Optional[float] = None,
              deadline_s: Optional[float] = None) -> dict:
    """Detiene UN turno. Respuesta TIPADA, y RESUELVE SIEMPRE.

    `{"resultado": "turno_detenido"|"no_habia_turno", ...}` — ver la secuencia arriba.
    Los dos parámetros existen para la vara (probar el deadline con relojes cortos); en
    producción se usan los de arriba, medidos contra CLITrigger.
    """
    t0 = time.monotonic()
    kill_tras = STOP_KILL_S if kill_tras_s is None else max(0.0, float(kill_tras_s))
    deadline = STOP_DEADLINE_S if deadline_s is None else max(0.0, float(deadline_s))
    tid = _id_limpio(turno_id)
    t = turno(tid) if tid else None
    if t is None:
        # NO es un error: pedir detener algo que ya terminó es lo normal cuando el usuario
        # aprieta el botón justo cuando la respuesta llegaba. Se contesta que no había.
        return {"resultado": NO_HABIA_TURNO, "turno_id": tid,
                "esperado_s": round(time.monotonic() - t0, 3)}

    t.detener_pedido = True
    t.detenido_en = time.time()
    proc = t.proc
    if proc is None:
        # Todavía no spawneó. La trampa de `_atar_proceso` ya está armada; se le da una
        # gracia corta por si nace ahora mismo, y si no, se contesta igual — el turno queda
        # marcado y el proceso muere al nacer.
        fin_gracia = t0 + min(STOP_GRACIA_SPAWN_S, deadline)
        while proc is None and time.monotonic() < fin_gracia:
            time.sleep(0.02)
            proc = t.proc
        if proc is None:
            return {"resultado": TURNO_DETENIDO, "turno_id": t.id, "provider": t.provider,
                    "pid": None, "senal": "ninguna", "vivo": False, "rc": None,
                    "deadline_vencido": False,
                    "esperado_s": round(time.monotonic() - t0, 3),
                    "nota": "marcado antes del spawn: el proceso muere al nacer"}

    _cerrar_stdin(proc)                                     # 1
    senal = "SIGTERM" if _senal_al_grupo(proc, signal.SIGTERM) else "ninguna"   # 2
    kill_en, fin = t0 + kill_tras, t0 + deadline
    mandado_kill = False
    while True:                                             # 3
        if proc.poll() is not None:
            vivo = False
            break
        ahora = time.monotonic()
        if ahora >= fin:                                    # 5 · el deadline SIEMPRE resuelve
            vivo = proc.poll() is None
            break
        if not mandado_kill and ahora >= kill_en:           # 4
            if _senal_al_grupo(proc, signal.SIGKILL):
                senal = "SIGKILL"
            mandado_kill = True
        time.sleep(min(STOP_POLL_S, max(0.001, fin - ahora)))

    return {"resultado": TURNO_DETENIDO, "turno_id": t.id, "provider": t.provider,
            "pid": proc.pid, "senal": senal, "vivo": vivo, "rc": proc.returncode,
            # Que el deadline haya vencido con el proceso todavía vivo se DICE. Un `stop`
            # que contesta «listo» sin haber matado nada es un false green.
            "deadline_vencido": bool(vivo),
            "esperado_s": round(time.monotonic() - t0, 3)}


# ── el registro persistente (import perezoso: el server puede correr suelto) ────────
def _registro():
    try:
        if __package__:
            from . import registro as _r                    # type: ignore
        else:                                               # pragma: no cover
            import registro as _r                           # type: ignore
        return _r.REGISTRO
    except Exception:                                       # noqa: BLE001 — nunca rompe un turno
        return None


def anotar_evento(evento: str, *, turno_id: str, **datos) -> bool:
    """Escribe la cronología durable sin permitir que su fallo tumbe el turno."""
    try:
        reg = _registro()
        return bool(reg and reg.anotar_evento(evento, turno_id=turno_id, **datos))
    except Exception:                                       # noqa: BLE001 — observabilidad
        return False


def _registro_borrar(turno_id: str) -> None:
    r = _registro()
    if r is not None:
        try:
            r.borrar(turno_id)
        except Exception:                                   # noqa: BLE001
            pass


def _run_managed(argv: list[str], *, timeout: float, cwd: Optional[str] = None,
                 env: Optional[dict] = None) -> subprocess.CompletedProcess:
    """`subprocess.run` equivalente, pero registrable y matable por el lifecycle desktop."""
    kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "stdin": subprocess.DEVNULL,
        "cwd": cwd,
        "env": env,
    }
    if os.name == "posix":
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(argv, **kwargs)
    _register_process(proc)
    try:
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            _terminate_process(proc)
            stdout, stderr = proc.communicate()
            raise subprocess.TimeoutExpired(argv, timeout, output=stdout, stderr=stderr) from exc
        return subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr)
    finally:
        _unregister_process(proc)


def assert_argv_safe(argv: list[str]) -> list[str]:
    """Gate duro: ningún flag de bypass entra al spawn. Devuelve el argv intacto."""
    bad = FORBIDDEN_FLAGS.intersection(argv)
    if bad:
        raise RuntimeError(f"cli_brain: flags prohibidos en argv: {sorted(bad)}")
    return argv


# ══ LECTURA INCREMENTAL (Gate 2 · F2a) ═════════════════════════════════════════════
# `_run_managed` espera a que el proceso TERMINE (`communicate`). Con `-p` eso son
# 60-100 s de silencio y después todo junto: el usuario mira una barra girar y el server
# fabrica un stream de un solo trozo. El CLI, en cambio, ya emite eventos según los
# produce — contrato medido del binario 2.1.220:
#     -p --verbose --output-format stream-json --include-partial-messages
# Esto lee ESO, línea a línea, sin esperar el final.
#
# El parser de línea sigue el patrón de CLITrigger (`src/server/services/log-streamer.ts`
# :255-274, MIT © 2026 Changjin Lee): acumular en un buffer, cortar por '\n', devolver
# la ÚLTIMA porción al buffer (es la línea parcial del próximo chunk), y hacer flush de
# lo que quede cuando el stream cierra. stderr pasa por el MISMO parser: si la línea es
# JSON se trata como evento, y si no, cae a texto crudo — el ruido de terminal no se
# descarta, se marca. Reescrito en Python sobre ese diseño, no traducido a ciegas: acá
# el buffer es de bytes (una línea multibyte cortada a la mitad rompía el decode), el
# techo de línea es propio, y el flujo va a una cola porque son dos tuberías, no una.
#
# El watchdog POR CHUNK es idea de shannon-mcp (`streaming/processor.py`), que no declara
# licencia: se reescribió desde cero. La forma importa más que el código — un deadline de
# INACTIVIDAD separado del total distingue «lento» de «muerto»: un turno largo es legítimo,
# un turno mudo no. `DEFAULT_TIMEOUT` sigue siendo el techo absoluto.

# F2a · EL TRADUCTOR DE GATE 2 (F1) ENTRA ACÁ, y éste es su primer consumidor real.
# Import defensivo: `platform/assembler` está en sys.path cuando el server corre suelto y
# cuando el assembler importa el paquete, pero si por lo que fuera no estuviera, el wrapper
# sigue funcionando exactamente como antes — sólo sin la causa tipada.
try:
    import errores_modelo as _traductor            # type: ignore
except ImportError:                                 # pragma: no cover - camino de rescate
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        import errores_modelo as _traductor        # type: ignore
    except ImportError:
        _traductor = None                           # type: ignore


def _causa_tipada(stderr: str, rc, result_event: Optional[dict] = None,
                  stdout: str = "") -> Optional[dict]:
    """Fallo del CLI → `CausaModelo` serializada. `None` si el traductor no está.

    Todo lo forense que el traductor necesita va acá: el `result_event` MANDA cuando
    existe (`is_error`/`api_error_status`/`terminal_reason` son el contrato medido del
    binario), y si no, se clasifica por texto. La salida ya viene redactada: ni el cuerpo
    del proveedor ni una key pueden viajar en ella.
    """
    if _traductor is None:
        return None
    try:
        return _traductor.desde_cli(stderr, rc, result_event, stdout=stdout).como_dict()
    except Exception:                               # noqa: BLE001 — jamás rompe el invoke
        return None


def _causa_detenido(nombre: str, turno_id: str) -> Optional[dict]:
    """`turno_detenido` (F1c) — la causa de un turno que alguien paró.

    Se construye A MANO y no por el traductor: el traductor clasifica FALLOS, y esto no lo
    es. No hay stderr que leer ni status que mirar — hay una decisión del usuario, y la
    única forma de que el traductor la produjera sería inventarle un texto de error que
    después él re-clasificara. Eso sería fabricar la evidencia.
    """
    if _traductor is None:
        return None
    try:
        return _traductor.CausaModelo(
            causa=_traductor.TURNO_DETENIDO, estado=_traductor.ROTO,
            detalle=f"Paraste el turno de {nombre}. No falló nada."[:200],
            fuente=_traductor.FUENTE_CLI,
            evidencia={"detenido_por": "usuario", "turno_id": str(turno_id or "")[:64]},
            reintentable=False).como_dict()
    except Exception:                               # noqa: BLE001 — jamás rompe el invoke
        return None


# ══ USAGE HONESTO (Gate 2 · F2c) ══════════════════════════════════════════════════
# EL CERO INVENTADO (auditoría 2 §P3.c): `u.get("input_tokens", 0)` convertía «el CLI no
# reportó» en «el CLI reportó cero». Río abajo, `_accumulate_usage` recibía un dict con
# campos no-None y contaba la llamada como MEDIDA — el único contador de honestidad que
# teníamos (`calls_no_usage`) nunca se disparaba para esta vía.
#
# La forma correcta es la de CLITrigger (`src/server/services/log-streamer.ts`:244-250 y
# :378-388, MIT © 2026 Changjin Lee): inicializar TODO en null y asignar con guarda de
# tipo — `typeof x === 'number' ? x : null`. Nunca un `?? 0`. Acá es lo mismo en Python,
# con una diferencia: además de los campos devolvemos si SE MIDIÓ, porque el consumidor
# de arriba (el annex, y de ahí el ledger) tiene que poder decirlo sin re-adivinar.
#
# UN SOLO ORIGEN DE VERDAD: el evento `result`. Los deltas del stream traen `usage` y
# MIENTE — medido sobre el binario 2.1.220 el 2026-08-03: `message_start` declara
# `output_tokens: 4` para una respuesta que termina en 39. El `message_delta` ya trae el
# valor bueno, pero preferir siempre el `result` evita depender de en qué punto del stream
# se cortó la lectura.

def tokens_o_none(valor) -> Optional[int]:
    """Guarda de tipo. Un entero es un entero; CUALQUIER otra cosa es ausencia, no cero.

    `True`/`False` quedan afuera a propósito: en Python son `int`, y un bool en un contador
    de tokens es un dato corrupto, no un 1.
    """
    if isinstance(valor, bool) or valor is None:
        return None
    if isinstance(valor, int):
        return valor if valor >= 0 else None
    if isinstance(valor, float) and valor.is_integer():
        return int(valor) if valor >= 0 else None
    if isinstance(valor, str):
        try:
            n = int(valor.strip())
            return n if n >= 0 else None
        except (TypeError, ValueError):
            return None
    return None


def usage_del_cli(bruto, *, medido: bool = True) -> tuple[dict, bool]:
    """`usage` crudo del CLI → (dict con None donde no hay dato, se_midio).

    `medido=False` fuerza la ausencia: es el caso del `result` con `is_error`, donde los
    ceros existen PORQUE NO CORRIÓ (contrato medido, reporte 3 §0.3). Reportar esos ceros
    como medidos sería exactamente la mentira que esta fase viene a borrar.
    """
    pt = ct = cw = cr = rz = None
    if medido and isinstance(bruto, dict):
        pt = tokens_o_none(bruto.get("input_tokens"))
        ct = tokens_o_none(bruto.get("output_tokens"))
        # ── EL LEDGER HONESTO: LO CACHEADO TAMBIÉN ES GASTO ────────────────────────
        # Esto leía SÓLO `input_tokens`/`output_tokens`, y por eso la casa reportaba
        # **2 tokens** para un turno de Claude que en realidad mandaba **3.705**: el resto
        # viajaba en `cache_creation_input_tokens` y se tiraba acá. No es un decimal: son
        # tres precios distintos —escribir caché cuesta MÁS que input normal, leerlo cuesta
        # MENOS— y sin estos campos no se puede comparar una lane contra otra ni saber si
        # una sesión reusada sirvió de algo.
        #
        # Los nombres NO son los mismos en los dos CLIs, y están medidos, no supuestos:
        #   · Claude → `cache_creation_input_tokens` / `cache_read_input_tokens`
        #     (visto crudo el 2026-08-13: input 2 · cache_creation 3703 · cache_read 0)
        #   · Codex  → `cached_input_tokens` — 18 apariciones en su binario nativo
        #     (`codex-cli 0.147.0`), contra 3 de `cached_tokens`. La forma OpenAI
        #     (`prompt_tokens_details.cached_tokens`) se acepta como respaldo por si un
        #     día emite el sobre estándar, pero la que usa hoy es la primera.
        cw = tokens_o_none(bruto.get("cache_creation_input_tokens"))
        cr = tokens_o_none(bruto.get("cache_read_input_tokens"))
        if cr is None:
            cr = tokens_o_none(bruto.get("cached_input_tokens"))
        if cr is None:
            _det = bruto.get("prompt_tokens_details")
            if isinstance(_det, dict):
                cr = tokens_o_none(_det.get("cached_tokens"))
        rz = tokens_o_none(bruto.get("reasoning_output_tokens"))
        if rz is None:
            rz = tokens_o_none(bruto.get("reasoning_tokens"))
    out = {"prompt_tokens": pt, "completion_tokens": ct,
           "cache_write_tokens": cw, "cache_read_tokens": cr}
    if rz is not None:
        out["reasoning_tokens"] = rz
    # `se_midio` se deja atado a pt/ct A PROPÓSITO: es la señal que gobierna
    # `tokens_medidos` y el contador de honestidad río abajo, y cambiarle el criterio de
    # paso sería mover una vara mientras se mide con ella. Los campos nuevos son ADITIVOS.
    return out, (pt is not None or ct is not None)


def _causa_del_wrapper(detalle: str, acciones: int = 0) -> Optional[dict]:
    """`falla_de_aleph` construida a mano: es la única causa que no nace de una entrada
    externa sino de nuestro propio guard rechazando un resultado.

    ⚠️ `acciones` NO es decoración: es lo que hace que el descarte deje de ser MUDO del
    otro lado del cable. La `evidencia` de una `CausaModelo` cruza entera —el server la
    publica en `error.causa`, `assembler._causa_del_cuerpo` la reconstruye y
    `recipe_assembler` la deja en `route_log`— así que quien anota el paso puede DECIR
    cuántas acciones se tiraron sin parsear una sola frase. Medido el defecto que cierra:
    un turno de Oficina volvía con `ok: true` y una excusa inventada, y las únicas dos
    huellas de los 46,3 s descartados eran una línea de stderr y `guard: wrapper_puro`
    —que dice QUE pasó, no CUÁNTO—."""
    if _traductor is None:
        return None
    try:
        _ev = {"guard": "wrapper_puro"}
        if acciones:
            _ev["acciones"] = int(acciones)
        return _traductor.CausaModelo(
            causa=_traductor.FALLA_DE_ALEPH, estado=_traductor.ROTO,
            detalle=detalle[:200], fuente=_traductor.FUENTE_CLI,
            evidencia=_ev, reintentable=False).como_dict()
    except Exception:                               # noqa: BLE001 — jamás rompe el invoke
        return None


#: Intervalo sin líneas que se registra como señal de silencio. NO mata el proceso:
#: algunos CLI piensan legítimamente más de ocho segundos sin emitir un evento. La muerte
#: la declara el proceso; el techo absoluto la declara el deadline compartido.
#: [Aleph] Era 45 s, y ése resultó ser el techo REAL del peor caso de la casa: medido en
#: Oficina el 2026-08-13, con el botón «Stop» apretado en dos momentos distintos de dos
#: turnos, el CLI vivió 45,4 s y 45,1 s — la misma vida las dos veces, o sea que quien lo
#: mataba era este watchdog y no el botón. Mientras la otra mitad del puente de parada no
#: esté, este número ES el daño máximo por click, y bajarlo de 45 a 8 lo corta más de cinco
#: veces sin tocar una línea de ningún stack. Esa inferencia resultó falsa en Finanzas:
#: silencio no prueba muerte y desde esta obra sólo queda como evidencia durable.
STREAM_CHUNK_TIMEOUT = float(os.environ.get("PUPPET_CLI_BRAIN_CHUNK_TIMEOUT", "8"))
#: Techo por línea. Una línea patológica se descarta contando, no se acumula en RAM.
MAX_LINE_BYTES = int(os.environ.get("PUPPET_CLI_BRAIN_MAX_LINE", str(1024 * 1024)))


def _timing_summary(timing: dict, timeout_layer: str = "") -> dict:
    """Relative monotonic milestones only; no prompt, account, or binary path."""
    origin = timing.get("request_received_mono") or timing.get("invoke_started_mono")
    if not origin:
        return {"timeout_layer": timeout_layer or timing.get("timeout_layer") or None}
    names = ("invoke_started", "binary_resolved", "model_resolved",
             "process_started", "first_output", "completion")
    summary = {"request_received_s": 0.0}
    summary.update({
        name + "_s": round(timing[name + "_mono"] - origin, 3)
        for name in names if name + "_mono" in timing
    })
    summary["timeout_layer"] = timeout_layer or timing.get("timeout_layer") or None
    return summary


@dataclass
class StreamStats:
    """Lo que pasó mientras se leía. Sale en `meta` para que nada quede mudo."""
    lineas: int = 0            # líneas completas entregadas
    overflow: int = 0          # líneas que superaron MAX_LINE_BYTES y se descartaron
    bytes_descartados: int = 0
    no_json: int = 0           # líneas que no parsearon como JSON (stderr, ruido)
    primer_byte_s: Optional[float] = None   # cuánto tardó la PRIMERA línea
    silencios: int = 0         # intervalos de chunk_timeout sin una línea
    #: LA COLA · cómo terminó de leerse el turno. `eof` = se esperó a que el CLI cerrara sus
    #: tuberías (lo de siempre). `evento_terminal` = el CLI ya dijo que terminó bien y se
    #: cortó ahí, dejando la agonía al cosechador. Viaja en `meta` porque un turno que se
    #: cerró de otra manera tiene que poder decirlo.
    cierre: str = "eof"
    #: Cuánto duró la agonía DE VERDAD, que sólo se sabe cuando el proceso murió — o sea
    #: DESPUÉS de que la respuesta salió. Por eso NO viaja en `meta`: un campo que en la
    #: respuesta siempre vale `null` es una promesa que no se puede cumplir. El número
    #: aterriza en el ledger, en el `cola_ms` del evento `process_exited` del cosechador.
    cola_evitada_ms: Optional[float] = None

    def como_dict(self) -> dict:
        d = {"lineas": self.lineas, "overflow": self.overflow,
             "bytes_descartados": self.bytes_descartados, "no_json": self.no_json,
             "silencios": self.silencios, "cierre": self.cierre}
        if self.primer_byte_s is not None:
            d["primer_byte_s"] = round(self.primer_byte_s, 3)
        return d


class _BufferDeLineas:
    """Acumula bytes y devuelve líneas COMPLETAS. La parcial queda para el próximo chunk.

    El techo (`max_bytes`) no es una optimización: sin él, un CLI que emite una línea de
    500 MB —o que nunca emite '\\n'— se come la RAM del sidecar antes de que nadie note
    nada. Al pasarse, la línea en curso se DESCARTA contando bytes y se sigue leyendo
    desde el próximo '\\n'; el contador sube y viaja en `meta`.
    """

    def __init__(self, max_bytes: int = MAX_LINE_BYTES):
        self.max_bytes = max(1024, int(max_bytes))
        self._buf = bytearray()
        self._descartando = False
        self.overflow = 0
        self.bytes_descartados = 0

    def alimentar(self, trozo: bytes) -> list[str]:
        salida: list[str] = []
        self._buf.extend(trozo)
        while True:
            corte = self._buf.find(b"\n")
            if corte < 0:
                break
            cruda = bytes(self._buf[:corte])
            del self._buf[:corte + 1]
            if self._descartando:            # el resto de una línea ya descartada
                self._descartando = False
                self.bytes_descartados += len(cruda)
                continue
            salida.append(cruda.decode("utf-8", "replace"))
        if len(self._buf) > self.max_bytes:  # sin '\n' a la vista y ya se pasó del techo
            self.overflow += 1
            self.bytes_descartados += len(self._buf)
            self._buf.clear()
            self._descartando = True         # lo que venga hasta el próximo '\n' también se tira
        return salida

    def flush(self) -> list[str]:
        """El cierre del stream: lo que quedó sin '\\n' es una línea igual."""
        if self._descartando:
            self.bytes_descartados += len(self._buf)
            self._buf.clear()
            self._descartando = False
            return []
        if not self._buf:
            return []
        cruda = bytes(self._buf)
        self._buf.clear()
        return [cruda.decode("utf-8", "replace")]


class StreamMuerto(RuntimeError):
    """Compatibilidad de import: el silencio ya no levanta esta excepción."""


def _bombear(pipe, canal: str, cola, buf: "_BufferDeLineas") -> None:
    """Hilo lector de UNA tubería. Empuja líneas a la cola y avisa cuando cierra."""
    try:
        while True:
            trozo = pipe.read(65536)
            if not trozo:
                break
            for linea in buf.alimentar(trozo):
                cola.put((canal, linea))
    except Exception:                                       # noqa: BLE001 — la tubería murió
        pass
    finally:
        try:
            for linea in buf.flush():                       # flush en end (patrón CLITrigger)
                cola.put((canal, linea))
        except Exception:                                   # noqa: BLE001
            pass
        cola.put((canal, None))                             # centinela de cierre
        try:
            pipe.close()
        except Exception:                                   # noqa: BLE001
            pass


#: Turnos cuya cola está en manos del cosechador. `cerrar_turno` NO les borra la fila del
#: registro: mientras el proceso siga vivo, su fila es el ÚNICO rastro que un barrido de
#: arranque podría seguir si el sidecar se cayera en ese medio segundo. La borra el
#: cosechador, cuando el pid ya no existe.
_COSECHANDO: set = set()
_COSECHANDO_LOCK = threading.Lock()


def _cosechar(proc, hilos, cola, abiertos, _reg, turno, al_cosechar, t_corte, stats) -> None:
    """La agonía del CLI, fuera del camino del turno.

    Espera el EOF de las dos tuberías y la muerte del proceso, y recién ahí suelta lo que
    NO se puede soltar antes: la fila del registro y el workdir. Es un hilo daemon: si el
    sidecar se cierra, no lo retiene — y para eso mismo el proceso sigue en
    `_ACTIVE_PROCESSES` hasta acá, que es lo que `terminate_active_processes()` mira al
    apagar.

    ⚠️ NO MATA NADA. La diferencia con `_terminate_process` es toda: acá el CLI terminó
    bien y sólo le falta cerrarse. Matarlo sería convertir una salida limpia en un
    SIGTERM, y el `returncode` que anotamos dejaría de significar lo que dice.
    """
    tid = turno.id if turno is not None else None
    if tid is not None:
        with _COSECHANDO_LOCK:
            _COSECHANDO.add(tid)

    def _correr():
        tardias = 0
        try:
            # Se sigue vaciando la cola: los hilos lectores todavía empujan, y un centinela
            # sin nadie que lo saque deja `_BufferDeLineas` con su último flush colgado.
            pendientes = set(abiertos)
            fin_espera = time.monotonic() + 30.0
            while pendientes and time.monotonic() < fin_espera:
                try:
                    canal, linea = cola.get(timeout=max(0.05, fin_espera - time.monotonic()))
                except Exception:                           # noqa: BLE001 — queue.Empty
                    break
                if linea is None:
                    pendientes.discard(canal)
                else:
                    tardias += 1
            try:
                proc.wait(timeout=30.0)
            except Exception:                               # noqa: BLE001
                _terminate_process(proc)
            for h in hilos:
                h.join(timeout=1.0)
            _unregister_process(proc)
            rc = proc.returncode
            cola_real_ms = round((time.monotonic() - t_corte) * 1000, 1)
            stats.cola_evitada_ms = cola_real_ms
            if _reg is not None and turno is not None:
                try:
                    _reg.anotar_evento("process_exited", turno_id=turno.id,
                                       provider=turno.provider, pid=proc.pid,
                                       returncode=rc, reason="cosecha",
                                       cola_ms=cola_real_ms,
                                       lineas_tardias=(tardias or None))
                    # LA SUPOSICIÓN, FALSABLE. Cortamos porque el evento terminal dijo que
                    # el turno terminó bien; si el proceso igual se murió mal, queda
                    # escrito con nombre propio en vez de desaparecer.
                    if rc not in (0, None):
                        _reg.anotar_evento("cola_desacuerdo", turno_id=turno.id,
                                           provider=turno.provider, pid=proc.pid,
                                           returncode=rc,
                                           detalle="el evento terminal dijo fin limpio y el "
                                                   "proceso salió con returncode != 0")
                        print(f"[cli_brain] ⚠ cola_desacuerdo {turno.id}: evento terminal "
                              f"limpio pero returncode={rc}", file=_log, flush=True)
                    if tardias:
                        _reg.anotar_evento("cola_lineas_tardias", turno_id=turno.id,
                                           provider=turno.provider, pid=proc.pid,
                                           lineas=tardias,
                                           detalle="llegaron líneas DESPUÉS del evento "
                                                   "terminal; el turno ya se había cerrado")
                    _reg.borrar(turno.id)
                except Exception:                           # noqa: BLE001
                    pass
        finally:
            if tid is not None:
                with _COSECHANDO_LOCK:
                    _COSECHANDO.discard(tid)
            if al_cosechar is not None:
                try:
                    al_cosechar()
                except Exception:                           # noqa: BLE001
                    pass

    threading.Thread(target=_correr, name="cli-brain-cosecha", daemon=True).start()


def _run_streaming(argv: list[str], *, timeout: float, cwd: Optional[str] = None,
                   env: Optional[dict] = None,
                   chunk_timeout: float = STREAM_CHUNK_TIMEOUT,
                   max_line_bytes: int = MAX_LINE_BYTES,
                   on_linea=None,
                   turno: "Optional[TurnoVivo]" = None,
                   binario: str = "",
                   deadline_mono: Optional[float] = None,
                   corta_ya=None,
                   al_cosechar=None,
                   stdin_payload: Optional[bytes] = None,
                   timing: Optional[dict] = None
                   ) -> tuple[subprocess.CompletedProcess, StreamStats]:
    """`_run_managed` pero SIN esperar el final: entrega cada línea según llega.

    ── LA COLA (`corta_ya` / `al_cosechar`) ──────────────────────────────────────
    `corta_ya()` se consulta DESPUÉS de cada línea entregada. Si dice que sí, se deja de
    leer y se devuelve: la agonía del CLI —cerrar tuberías y morirse— pasa a un hilo
    cosechador que no bloquea al turno.

    MEDIDO, y por eso existe (2026-08-24, argv de producción, 3 corridas por CLI):

        última línea → EOF de ambas tuberías   claude 529 · codex 453-567 · grok 286-314 ms
        EOF → muerte del proceso               0,0-0,1 ms en los tres

    O sea que **`proc.wait()` no costaba nada**: la cola entera era el CLI reteniendo sus
    tuberías medio segundo DESPUÉS de haber escrito su evento terminal. Y en ese medio
    segundo **no llega ni una línea más** — el evento terminal ES la última, en los tres.

    `al_cosechar()` corre cuando el proceso murió de verdad. Es donde va lo que NO se puede
    hacer antes: borrar el workdir. Medido: **codex escribe `last-message.txt` 252 ms
    DESPUÉS de su `turn.completed`**, y ese archivo es el respaldo del texto del agente
    (`codex_cli.parse_result`). Borrarle el cwd al cortar sería sacárselo de abajo.
    

    `on_linea(canal, linea)` se llama por cada línea completa, con `canal ∈ {stdout, stderr}`.
    Devuelve el CompletedProcess equivalente (stdout/stderr crudos reensamblados, para que
    los `parse_result` existentes sigan viendo lo mismo) más las estadísticas de lectura.

    Un solo reloj mata: ``deadline_mono``. ``chunk_timeout`` sólo hace persistente la
    señal de silencio; mientras el proceso siga vivo y quede presupuesto, se continúa.
    Si no se recibe deadline, se deriva uno de ``timeout`` por compatibilidad del API.
    """
    import queue

    if deadline_mono is not None and time.monotonic() >= float(deadline_mono):
        # No crear un proceso que ya nació fuera de presupuesto.
        raise subprocess.TimeoutExpired(argv, 0.0)

    kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        # `stdin_payload` es el carril de las IMÁGENES (`--input-format stream-json`): el
        # único caso en que el CLI tiene algo que LEER de nosotros. Sin él, stdin sigue
        # siendo DEVNULL —el CLI no puede pedirnos nada interactivo— byte por byte igual.
        "stdin": (subprocess.PIPE if stdin_payload is not None else subprocess.DEVNULL),
        "cwd": cwd,
        "env": env,
        "bufsize": 0,          # sin buffering de Python: el chunk llega cuando el CLI lo escribe
    }
    if os.name == "posix":
        kwargs["start_new_session"] = True
    # F2d · EL REGISTRO PERSISTENTE, EN DOS FASES. La fila `naciendo` va ANTES del spawn
    # con `fsync`: si escribiéramos después, un crash del sidecar en esos milisegundos
    # dejaría un `claude -p` vivo del que no queda rastro en ningún lado. Ni el registro
    # ni sus fallos pueden tumbar un turno — todo esto es best-effort declarado.
    _reg = _registro() if turno is not None else None
    if _reg is not None:
        try:
            _reg.anotar_naciendo(turno_id=turno.id, provider=turno.provider,
                                 binario=binario or (argv[0] if argv else ""), argv=argv)
        except Exception:                                   # noqa: BLE001
            _reg = None
    proc = subprocess.Popen(argv, **kwargs)
    if timing is not None:
        timing["process_started_mono"] = time.monotonic()
    _register_process(proc)
    if stdin_payload is not None:
        # Se escribe Y SE CIERRA de inmediato: el CLI espera el EOF de stdin para saber que
        # la conversación de entrada terminó, y sin ese cierre el turno cuelga hasta el
        # deadline. Un pipe roto acá no es un crash: el proceso ya murió por su cuenta y el
        # camino de error de abajo (returncode + stderr) lo cuenta mejor que una excepción.
        try:
            proc.stdin.write(stdin_payload)
            proc.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass
    _atar_proceso(turno, proc)          # y la trampa del fantasma, si ya pidieron detenerlo
    if _reg is not None:
        try:
            _reg.anotar_pid(turno.id, proc.pid, pgid=proc.pid)
            _reg.anotar_evento("spawned", turno_id=turno.id, provider=turno.provider,
                                pid=proc.pid)
        except Exception:                                   # noqa: BLE001
            pass

    stats = StreamStats()
    cola: "queue.Queue" = queue.Queue()
    bufs = {"stdout": _BufferDeLineas(max_line_bytes), "stderr": _BufferDeLineas(max_line_bytes)}
    hilos = []
    for canal, pipe in (("stdout", proc.stdout), ("stderr", proc.stderr)):
        h = threading.Thread(target=_bombear, args=(pipe, canal, cola, bufs[canal]), daemon=True)
        h.start()
        hilos.append(h)

    acumulado = {"stdout": [], "stderr": []}
    abiertos = {"stdout", "stderr"}
    t0 = time.monotonic()
    fin = float(deadline_mono) if deadline_mono is not None else t0 + float(timeout)
    motivo_corte: Optional[str] = None
    cerrado_temprano = False
    t_corte: Optional[float] = None
    try:
        while abiertos:
            # EL RELOJ CORRE SIEMPRE, EMITA O NO. Esta resta va acá arriba, no adentro del
            # `except queue.Empty`: una línea que llega evita el evento de silencio, NO
            # repone presupuesto. Medido (`qa/verify_deadline_muerde.py`): un hijo que
            # escribe cada 0,05 s y uno mudo del todo mueren los dos a los 3,01 s con un
            # deadline de 3 s.
            #
            # ⚠️ Y EL RELOJ ES MONOTÓNICO A PROPÓSITO: no avanza mientras la máquina
            # duerme. Del registro real: un turno consumió 180,4 s de monotónico repartidos
            # en 10.151 s de PARED, y otros dos «de 15 minutos» eran turnos de 5-6 s con
            # una siesta en el medio. El presupuesto mide cuánto TRABAJÓ el CLI; un proceso
            # suspendido no consume cuota ni produce nada, y matarlo por una siesta de la
            # laptop sería cobrarle al usuario un tiempo que nadie usó. Si un número no
            # cierra, comparar `ts` contra `mono` en `cli_eventos.jsonl` ANTES de acusar a
            # este código: los dos relojes ya están en cada evento justamente para eso.
            restante_total = fin - time.monotonic()
            if restante_total <= 0:
                motivo_corte = "deadline"
                break
            try:
                canal, linea = cola.get(timeout=min(chunk_timeout, restante_total))
            except queue.Empty:
                # Una ausencia de líneas es una SEÑAL, no una sentencia de muerte. El
                # proceso puede estar pensando. Se persiste para diagnóstico y se sigue
                # hasta que cierre sus pipes o venza el único deadline.
                stats.silencios += 1
                if _reg is not None:
                    try:
                        _reg.anotar_evento(
                            "stream_silence", turno_id=turno.id,
                            provider=turno.provider, pid=proc.pid,
                            silence_s=float(chunk_timeout),
                            remaining_s=max(0.0, fin - time.monotonic()),
                        )
                    except Exception:                       # noqa: BLE001
                        pass
                continue
            if linea is None:
                abiertos.discard(canal)
                continue
            if stats.primer_byte_s is None:
                stats.primer_byte_s = time.monotonic() - t0
                if timing is not None:
                    timing["first_output_mono"] = time.monotonic()
            stats.lineas += 1
            acumulado[canal].append(linea)
            if on_linea is not None:
                try:
                    on_linea(canal, linea)
                except Exception:                           # noqa: BLE001 — un consumidor
                    pass                                    # que explota no mata la lectura
            # ── EL CORTE ──────────────────────────────────────────────────────────
            # Se pregunta DESPUÉS de entregar, nunca antes: la línea que dispara el corte
            # es la que trae el usage, y tiene que haber pasado por `on_linea` (y por el
            # ledger) antes de que dejemos de leer.
            if corta_ya is not None:
                try:
                    cortar = bool(corta_ya())
                except Exception:                           # noqa: BLE001 — fail-closed:
                    cortar = False                          # si el juez explota, se espera el EOF
                if cortar:
                    cerrado_temprano = True
                    t_corte = time.monotonic()
                    break
    finally:
        for b in bufs.values():
            stats.overflow += b.overflow
            stats.bytes_descartados += b.bytes_descartados
        if motivo_corte is not None:
            if timing is not None:
                timing["timeout_layer"] = "cli_deadline" if motivo_corte == "deadline" else motivo_corte
            if _reg is not None:
                try:
                    _reg.anotar_evento("stream_killed", turno_id=turno.id,
                                       provider=turno.provider, pid=proc.pid,
                                       reason=motivo_corte)
                except Exception:                           # noqa: BLE001
                    pass
            _terminate_process(proc)
        if cerrado_temprano:
            # LA COLA SE VA A UN HILO. Nadie mata nada acá: el CLI ya dijo que terminó
            # bien, y lo único que le queda es cerrar sus tuberías. El cosechador espera
            # ESO, no al turno.
            stats.cierre = "evento_terminal"
            _cosechar(proc, hilos, cola, abiertos, _reg, turno, al_cosechar,
                      t_corte or time.monotonic(), stats)
        else:
            try:
                proc.wait(timeout=2.0)
            except Exception:                               # noqa: BLE001
                _terminate_process(proc)
            for h in hilos:
                h.join(timeout=1.0)
            _unregister_process(proc)
            # LA MUERTE LIMPIA BORRA. El proceso terminó y nosotros seguimos vivos para
            # contarlo: la fila se va acá y no cuando cierre el turno, para que el registro no
            # tenga ni un instante una fila `vivo` con un pid que ya no existe.
            if _reg is not None:
                try:
                    _reg.anotar_evento("process_exited", turno_id=turno.id,
                                       provider=turno.provider, pid=proc.pid,
                                       returncode=proc.returncode,
                                       reason=motivo_corte or "process_exit")
                    _reg.borrar(turno.id)
                except Exception:                           # noqa: BLE001
                    pass
            # ⚠️ `al_cosechar` NO se llama acá. En el camino de EOF el workdir tiene que
            # sobrevivir hasta DESPUÉS de `parse_result` — codex lee su `last-message.txt`
            # de ahí adentro. Lo borra el `finally` de `invoke`, como siempre.

    out = "\n".join(acumulado["stdout"])
    err = "\n".join(acumulado["stderr"])
    if motivo_corte == "deadline":
        if timing is not None:
            timing["completion_mono"] = time.monotonic()
        raise subprocess.TimeoutExpired(argv, max(0.0, fin - t0), output=out, stderr=err)
    # EL RETURNCODE CUANDO SE CORTÓ TEMPRANO. El proceso sigue vivo, así que `poll()` da
    # `None` — y `None != 0` mandaría a los tres `parse_result` por el camino de ERROR.
    # Se declara 0 porque **el evento terminal ya dijo que terminó bien, y en esta casa el
    # evento manda sobre el returncode** (es el mismo principio que `_causa_tipada`, donde
    # «el result_event manda si lo hay»). No es un cero inventado: es el canal autoritativo
    # en vez del redundante — y el cosechador VERIFICA el returncode real cuando llega y
    # anota `cola_desacuerdo` si no era 0, así la suposición es falsable en producción.
    if timing is not None:
        timing["completion_mono"] = time.monotonic()
    rc = 0 if cerrado_temprano else proc.returncode
    return subprocess.CompletedProcess(argv, rc, out, err), stats


@dataclass
class BrainStatus:
    """Resultado de detect() — SOLO estado, jamás tokens/credenciales."""
    provider: str                    # 'claude_cli' | 'codex_cli'
    state: str                       # READY | NO_AUTH | NOT_INSTALLED | AUTH_UNKNOWN | CONFIG_INVALID
    detail: str = ""                 # razón honesta legible ("sin login", "no instalado", ...)
    binary: Optional[str] = None     # path del binario si se encontró
    checked_at: float = 0.0          # epoch del chequeo
    extra: dict = field(default_factory=dict)  # metadatos NO sensibles (p.ej. subscriptionType)

    def to_dict(self, *, public: bool = False) -> dict:
        """`public=True` = la forma que sale por HTTP (GET /v1/brains/status): SIN el path
        del binario (fingerprinting del host/usuario, review LOW #2/#23), con `installed`
        booleano en su lugar. `public=False` (default) = uso interno, con binary."""
        d = {
            "provider": self.provider, "state": self.state, "detail": self.detail,
            "checked_at": self.checked_at, "extra": dict(self.extra),
            "binary_found": self.binary is not None,
            "auth_state": ("authenticated" if self.state == STATE_READY else
                           "expired" if self.state == STATE_AUTH_EXPIRED else
                           "not_authenticated" if self.state == STATE_NO_AUTH else "unknown"),
            "last_auth_verified_at": self.checked_at if self.state in
                (STATE_READY, STATE_NO_AUTH, STATE_AUTH_EXPIRED) else None,
            "last_auth_result": ("authenticated" if self.state == STATE_READY else
                                 "expired" if self.state == STATE_AUTH_EXPIRED else
                                 "not_authenticated" if self.state == STATE_NO_AUTH else "unknown"),
            "configuration_state": ("invalid" if self.state == STATE_CONFIG_INVALID else "valid"),
            "access_state": "unknown",
            "service_state": "unknown",
            "last_test_state": "not_run",
        }
        if public:
            d["installed"] = self.binary is not None
        else:
            d["binary"] = self.binary
        return d


@dataclass
class BrainResult:
    """Resultado de invoke() — puro completion out."""
    ok: bool
    text: str = ""
    model_final: Optional[str] = None      # el modelo REAL reportado por el CLI
    model_final_source: str = ""           # 'cli-reported' | 'requested-validated' | ''
    resolved_model: Optional[str] = None   # valor explícito enviado al binario
    usage: dict = field(default_factory=dict)  # {prompt_tokens, completion_tokens}
    error_kind: Optional[str] = None       # ERR_* si ok=False
    error_detail: str = ""                 # mensaje honesto (recortado, sin secretos)
    reset_hint: str = ""                   # "resetea a las X" si el CLI lo informó
    exec_events: int = 0                   # eventos de ejecución del CLI detectados (DEBE ser 0)
    meta: dict = field(default_factory=dict)
    #: F2a · la causa TIPADA del fallo, ya redactada, del traductor de Gate 2 (`errores_modelo`).
    #: `None` cuando ok=True. Aditivo: `error_kind`/`error_detail`/`reset_hint` siguen igual.
    causa: Optional[dict] = None
    #: F2c · ¿los tokens de `usage` los REPORTÓ el CLI, o no hay dato? `False` significa
    #: «no medible», que no es lo mismo que «cero». Los valores de `usage` son `None`
    #: cuando esto es False — jamás 0, que era el cero inventado del §P3.c.
    tokens_medidos: bool = False


class CliBrainProvider(ABC):
    """Contrato común de los cerebros por CLI. Implementaciones: claude_cli, codex_cli."""

    provider_id: str = ""        # 'claude_cli' | 'codex_cli'
    display_name: str = ""       # 'Claude Code' | 'Codex'
    response_model_id: str = ""  # id OpenAI-compat que sirve el server (:8926)

    # ── binario ──────────────────────────────────────────────────────────────
    @abstractmethod
    def _bin_env_var(self) -> str: ...

    @abstractmethod
    def _bin_name(self) -> str: ...

    def _bin_fallbacks(self) -> list[str]:
        return []

    def _resolve_binary(self) -> tuple[Optional[str], str, str]:
        """(path, source, error). Manual choice takes precedence over operator env."""
        try:
            from . import config as cli_config
            choice = cli_config.get(self.provider_id)
            if choice["mode"] == "manual":
                try:
                    checked = cli_config.verify_executable(self.provider_id, choice["path"])
                    return checked["path"], "manual", ""
                except cli_config.ConfigError as exc:
                    return None, "manual", str(exc)
        except Exception as exc:
            return None, "configuration", f"no pude leer la configuración CLI ({type(exc).__name__})"
        override = os.environ.get(self._bin_env_var())
        if override:
            path = _usable_binary(override)
            return path, "environment", "" if path else "la ruta del override no es ejecutable"
        found = shutil.which(self._bin_name())
        if found and _usable_binary(found):
            return _usable_binary(found), "path", ""
        for cand in self._bin_fallbacks() + _common_binary_candidates(self._bin_name()):
            p = _usable_binary(cand)
            if p:
                return p, "known_location", ""
        return None, "auto", ""

    def binary(self) -> Optional[str]:
        """Resolved executable used for both authentication and execution."""
        return self._resolve_binary()[0]

    # ── contrato ─────────────────────────────────────────────────────────────
    @abstractmethod
    def default_model(self) -> str:
        """Modelo que el wrapper pide por default (SIEMPRE explícito en el argv)."""

    @abstractmethod
    def build_detect_argv(self, binary: str) -> list[str]:
        """argv del chequeo de auth (la ÚNICA interacción con el auth del CLI)."""

    @abstractmethod
    def parse_detect(self, returncode: int, stdout: str, stderr: str) -> tuple[str, str, dict]:
        """(state, detail, extra) desde la salida del chequeo de auth."""

    # ── streaming (F2a) ──────────────────────────────────────────────────────
    def usa_stream_json(self) -> bool:
        """¿Este provider emite eventos incrementales parseables mientras corre?

        `False` (default) = la lectura sigue siendo incremental, pero `parse_result`
        recibe el stdout crudo tal como lo daba `communicate` — byte-idéntico al de antes.
        `True` = el provider sabe leer sus propios eventos y `parse_result` recibirá el
        evento `result` serializado, que trae los mismos campos que `--output-format json`.
        """
        return False

    def fin_limpio(self, obj: dict) -> bool:
        """¿Este evento es el CLI diciendo «terminé, y terminé BIEN»?

        Es el permiso para dejar de leer y mandarle la agonía al cosechador (ver la cola en
        `_run_streaming`). Se pregunta por CADA línea JSON, tenga el provider `stream-json`
        o no — codex no lo tiene y su cola es de las más caras.

        **FAIL-CLOSED, y el default es no.** Un provider que no lo implemente sigue
        esperando el EOF, que es el comportamiento de siempre. Y «bien» es literal: si el
        evento terminal dice error, esto devuelve False y el turno se cierra por EOF con el
        `returncode` REAL, que es lo que los tres `parse_result` consultan en su camino de
        error. Un `True` de más ahí haría que un fallo dejara de decirse.
        """
        return False

    def parse_stream_line(self, obj: dict) -> tuple[Optional[str], object]:
        """UN evento del stream → (clase, carga). Clases:

            'texto'     → str, un delta de la respuesta (lo que el usuario ve aparecer)
            'pensando'  → str, un delta de razonamiento REAL (jamás fabricado)
            'resultado' → dict, el evento final con usage/model/is_error
            'sistema'   → dict, init/status/límites (forense, no se muestra como texto)
            None        → no aporta

        Default: no aporta nada. Un provider sin streaming no rompe: sólo no adelanta.
        """
        return None, None

    # ── las imágenes (verificación visual) ───────────────────────────────────
    def soporta_imagenes(self) -> bool:
        """¿Este CLI puede recibir una imagen DE VERDAD (no un base64 en el texto)?

        Default `False`, y es fail-closed a propósito: un provider que no lo declare no
        recibe imágenes, y la fila del catálogo que lo representa no declara `vision`, así
        que `model-use/v1` rechaza el pedido ANTES con causa legible. Declararlo acá sin
        implementar `build_stdin` sería prometer un transporte que no existe."""
        return False

    def build_stdin(self, prompt: str, imagenes: list) -> Optional[bytes]:
        """Lo que se le escribe al CLI por stdin, o `None` para no abrirlo (el default).

        Sólo lo implementa el provider que sabe llevar imágenes; el que devuelve `None`
        corre con `stdin=DEVNULL`, byte-idéntico a siempre."""
        return None

    @abstractmethod
    def build_argv(self, binary: str, prompt: str, model: str, workdir: str,
                   effort: Optional[str] = None, stream: bool = False,
                   sesion=None) -> list[str]:
        """argv COMPLETO del completion (tools OFF horneadas acá). Sin side-effects.

        `stream=True` pide la variante incremental del provider (F2a). Sin ese flag el
        argv es el de siempre, byte por byte.
        `effort` (27·3): el provider que lo soporte agrega su flag; el que no, lo ignora.
        `sesion` (F2e): `None` = el argv de siempre, con `--no-session-persistence`. Con
        una `Sesion`, el provider que la soporte fija el id (`--session-id`) o continúa
        (`--resume`); el que no la soporte la ignora y queda byte-idéntico."""

    @abstractmethod
    def parse_result(self, returncode: int, stdout: str, stderr: str, workdir: str,
                     model: str) -> BrainResult:
        """Salida del CLI → BrainResult (incluye clasificación si falló)."""

    @abstractmethod
    def classify_error(self, blob: str, returncode: Optional[int] = None) -> tuple[str, str]:
        """(error_kind, reset_hint) desde el texto de error crudo del CLI."""

    # ── implementación común ─────────────────────────────────────────────────
    def detect(self) -> BrainStatus:
        """Detecta binario y auth por separado; JAMÁS lee credenciales."""
        b, source, config_error = self._resolve_binary()
        now = time.time()
        if config_error:
            return BrainStatus(self.provider_id, STATE_CONFIG_INVALID,
                               detail=config_error, checked_at=now,
                               extra={"detection_source": source})
        if not b:
            return BrainStatus(self.provider_id, STATE_NOT_INSTALLED,
                               detail=f"no encontré el comando `{self._bin_name()}` en esta máquina",
                               checked_at=now, extra={"detection_source": source})
        try:
            r = _run_managed(self.build_detect_argv(b), timeout=DETECT_TIMEOUT,
                             env=sanitized_env(b))  # sin keys ambiente: la suscripción decide READY
        except FileNotFoundError:
            return BrainStatus(self.provider_id, STATE_AUTH_UNKNOWN,
                               detail="el ejecutable desapareció durante la verificación",
                               checked_at=now, extra={"detection_source": source})
        except subprocess.TimeoutExpired:
            return BrainStatus(self.provider_id, STATE_AUTH_UNKNOWN, binary=b,
                               detail="el chequeo de sesión no respondió a tiempo", checked_at=now,
                               extra={"detection_source": source})
        except OSError as exc:
            return BrainStatus(self.provider_id, STATE_AUTH_UNKNOWN, binary=b,
                               detail=f"no pude ejecutar el chequeo de sesión ({type(exc).__name__})",
                               checked_at=now, extra={"detection_source": source})
        state, detail, extra = self.parse_detect(r.returncode, r.stdout or "", r.stderr or "")
        extra = {**extra, "detection_source": source}
        return BrainStatus(self.provider_id, state, detail=detail, binary=b,
                           checked_at=now, extra=extra)

    def invoke(self, prompt: str, model: Optional[str] = None,
               timeout: Optional[float] = None, effort: Optional[str] = None,
               on_evento=None, chunk_timeout: Optional[float] = None,
               turno_id: Optional[str] = None, sesion=None,
               deadline_mono: Optional[float] = None,
               clave_conversacion: str = "",
               imagenes: Optional[list] = None,
               request_received_mono: Optional[float] = None) -> BrainResult:
        """UN completion: spawn del CLI del usuario en un dir vacío efímero, stdin cerrado,
        tools OFF, timeout sano. Devuelve texto + model_final real, o el error clasificado.
        TICKET 27·3 · `effort` (low/medium/high/max) → el CLI corre con ese esfuerzo (build_argv).

        F2a · YA NO ESPERA AL FINAL. La lectura es incremental (`_run_streaming`) y, si el
        provider sabe leer sus eventos (`usa_stream_json`), `on_evento(clase, carga)` se
        llama por cada delta MIENTRAS el CLI corre. El BrainResult devuelto es el mismo de
        siempre: quien no pase `on_evento` no nota diferencia salvo que ahora hay un
        watchdog de inactividad además del techo total.

        F2d · `turno_id` hace el turno DETENIBLE (`stop_turn`) y lo anota en el registro
        persistente. Si el llamante ya abrió el turno (el server lo hace, porque necesita
        el id definitivo para la respuesta), se usa ése y **no se cierra acá** — lo cierra
        quien lo abrió. Si no, se abre uno propio y se cierra en el `finally`. Sin
        `turno_id` también se abre uno: un spawn sin ficha es un huérfano en potencia que
        nadie puede matar, y ése es justamente el agujero de esta fase.

        IMÁGENES · `imagenes` son las que `prompt_bridge` sacó del contenido multimodal.
        Sólo llegan al CLI si el provider las declara (`soporta_imagenes`) y sabe armar su
        stdin (`build_stdin`); si no, el prompt ya trae sus MARCAS (`⟦imagen 1⟧`) y las
        imágenes se descartan con un aviso — jamás se pegan como base64 en el texto, que
        es exactamente el bug que este carril vino a cerrar.

        F2e · `sesion` hace el turno CONTINUABLE. Cambia dos cosas: el argv (`--session-id`
        / `--resume`, lo decide el provider) y el WORKDIR — el de la sesión, ESTABLE y que
        NO se borra. Sin `sesion`, todo queda como antes: dir efímero y borrado.
        """
        _timing = {"invoke_started_mono": time.monotonic()}
        if request_received_mono is not None:
            _timing["request_received_mono"] = request_received_mono
        b, _source, config_error = self._resolve_binary()
        _timing["binary_resolved_mono"] = time.monotonic()
        if config_error:
            return BrainResult(ok=False, error_kind=ERR_CONFIG_INVALID,
                               error_detail=config_error)
        if not b:
            return BrainResult(ok=False, error_kind=ERR_NOT_INSTALLED,
                               error_detail=f"`{self._bin_name()}` no está instalado",
                               causa=_causa_tipada(f"{self._bin_name()}: command not found", 127))
        _t = turno(turno_id) if turno_id else None
        _turno_propio = _t is None
        if _t is None:
            _t = abrir_turno(turno_id, self.provider_id)
        mdl = (model or "").strip() or self.default_model()
        if not mdl:
            if _turno_propio:
                cerrar_turno(_t.id)
            return BrainResult(ok=False, error_kind=ERR_MODEL,
                               error_detail="no pude determinar un modelo disponible para esta cuenta CLI")
        _timing["model_resolved_mono"] = time.monotonic()
        # F2e · EL WORKDIR ES LA SESIÓN. Medido: `--resume` está scopeado por cwd, así que
        # el `mkdtemp` de siempre —distinto por turno y borrado al final— hace que resumir
        # sea imposible. Con sesión, el dir es de ella; sin sesión, efímero como siempre.
        workdir = getattr(sesion, "workdir", None) or tempfile.mkdtemp(prefix="aleph-cli-brain-")
        _workdir_propio = sesion is None
        stream = self.usa_stream_json()
        evento_resultado: dict = {}
        eventos_parciales = 0
        no_json = 0
        #: LA COLA · ¿el CLI ya dijo que terminó BIEN? Lo pone `_linea` y lo lee el corte.
        fin_limpio_visto = False
        _workdir_borrado = threading.Event()

        def _borrar_workdir() -> None:
            """Idempotente y sin dueño doble: lo llama el cosechador (camino normal) o el
            `finally` de abajo (cuando ni se llegó a spawnear)."""
            if not _workdir_propio or _workdir_borrado.is_set():
                return
            _workdir_borrado.set()
            shutil.rmtree(workdir, ignore_errors=True)

        def _linea(canal: str, linea: str) -> None:
            """Cada línea, según llega. stderr pasa por el MISMO parser (patrón CLITrigger):
            si es JSON se trata como evento; si no, es texto crudo y se marca como tal."""
            nonlocal eventos_parciales, no_json, fin_limpio_visto
            texto = linea.strip()
            if not texto:
                return
            obj = None
            if texto[0] in "{[":
                try:
                    obj = json.loads(texto)
                except (json.JSONDecodeError, ValueError):
                    obj = None
            if obj is None or not isinstance(obj, dict):
                # fallback a texto: NO se descarta. El ruido de terminal que anuncia un
                # límite o un fallo de red es señal, y el traductor F1 sabe leerlo.
                no_json += 1
                if on_evento is not None:
                    on_evento("ruido", {"canal": canal, "texto": texto[:2000]})
                return
            # LA COLA · el fin limpio se reconoce ANTES del `return` de los providers sin
            # stream-json, porque codex es uno de ellos y su cola es de las más caras.
            # Va acá abajo, después de que `on_evento` vio la línea: el evento terminal
            # trae el usage y tiene que llegar al ledger antes de que dejemos de leer.
            if not fin_limpio_visto:
                try:
                    if self.fin_limpio(obj):
                        fin_limpio_visto = True
                except Exception:                            # noqa: BLE001 — fail-closed
                    pass
            if not stream:
                return
            clase, carga = self.parse_stream_line(obj)
            if clase == "resultado" and isinstance(carga, dict):
                evento_resultado.clear()
                evento_resultado.update(carga)
            if clase in ("texto", "pensando"):
                eventos_parciales += 1
            if clase is not None and on_evento is not None:
                on_evento(clase, carga)

        def _detenido() -> BrainResult:
            """El turno lo paró alguien. NO es un fallo del CLI y no se narra como tal.

            Sin esto, un turno detenido volvía como `model_error` con «Claude Code rechazó
            la solicitud (status exit -15)» — el CLI no rechazó nada: lo matamos nosotros.

            F1c · CAMBIO DE VEREDICTO DECLARADO. Salía **SIN causa**, porque el vocabulario
            sellado no tenía `turno_detenido` y ninguna de las que había lo decía sin
            mentir. Ahora la tiene, así que sale CON causa — y eso no contradice a F2d: el
            motivo de salir sin causa era no mentir, no quedarse mudo. Un `causa=None` le
            deja a la UI un rojo sin explicación, que es la otra forma del fallo mudo.

            `reintentable=False` **explícito**, y es la aserción que más importa de las
            seis: reintentar un turno que alguien paró es deshacer su decisión. Por eso la
            causa no está en `_ESCALABLES` (no cascadea) ni en `_REINTENTABLES` (repair no
            la toca)."""
            return BrainResult(ok=False, error_kind=ERR_DETENIDO,
                               error_detail=f"{self.display_name}: el turno se detuvo a pedido",
                               causa=_causa_detenido(self.display_name, _t.id),
                               meta={"detenido": True, "turno_id": _t.id})

        # ══ EL BROKER, DETRÁS DE SU PERILLA (paso 3) ═══════════════════════════
        # Va ACÁ y no antes: el turno ya está abierto, el workdir resuelto y el binario
        # encontrado, así que si el broker no puede, lo de abajo sigue como si no existiera.
        # `intentar_turno` devuelve `None` para TODO lo que no sea un turno completo —
        # perilla apagada, provider sin adaptador, pool lleno, handshake caído, proceso
        # muerto a mitad. **El respaldo es el camino de hoy, no un error.**
        try:
            from .broker import capa as _broker
            # EL ATAJO NO LLEVA IMÁGENES. `intentar_turno` recibe un `prompt` y nada más;
            # dejarlo atender un turno con imágenes las tiraría EN SILENCIO, que es la
            # forma más cara de este mismo bug. El respaldo es el camino de hoy, y el
            # camino de hoy sí las lleva.
            if imagenes and _broker.encendido():
                print("[broker] turno con imágenes: va por el camino directo "
                      "(el adaptador no transporta imágenes todavía)",
                      file=sys.stderr, flush=True)
            elif _broker.encendido():
                # ── EL REGISTRO TAMBIÉN VE LOS TURNOS DEL BROKER ──────────────────
                # MEDIDO el 2026-08-26 con la perilla prendida: `PUPPET_CLI_EVENTOS`
                # sólo recibía `slot_requested` y `slot_granted`. Ni `spawned`, ni
                # `process_exited`, ni `stream_silence` — porque el proceso lo levanta
                # el POOL y no `_run_streaming`, que es quien anota. O sea: **con el
                # broker en producción, la casa se queda sin su propia telemetría de
                # latencia**, y el desglose del wall no puede ver la franja de modelo.
                # No da rojo: da silencio, que es la trampa que esta casa ya pagó.
                # Se anota acá —y no adentro del broker— porque `turno` y `_registro()`
                # ya están en mano y el paquete del broker no tiene por qué conocerlos.
                # ⚠️ LA VARIABLE ES `_t`, NO `turno`. En `invoke`, `turno` es la FUNCIÓN
                # que busca el turno por id (línea 1318) — siempre truthy — así que
                # `turno.id` lanzaba AttributeError y **mi propio `except: pass` se lo
                # tragaba**. Los eventos nunca llegaban y el grabador seguía ciego, ahora
                # por mi arreglo en vez de por el original. Mismo fallo mudo, otro autor.
                _reg_br = _registro() if _t is not None else None
                _t_br = time.monotonic()
                _rb = _broker.intentar_turno(
                    self, prompt=prompt, modelo=mdl, effort=effort or "",
                    sesion=sesion, workdir=workdir,
                    clave_conversacion=clave_conversacion,
                    env=sanitized_env(b), binario=b,
                    on_evento=(lambda clase, carga: on_evento(clase, carga))
                              if on_evento is not None else None,
                    plazo=float(timeout if timeout is not None else DEFAULT_TIMEOUT))
                if _rb is not None and _reg_br is not None:
                    # `via="broker"` es obligatorio: un turno servido por un proceso
                    # REUSADO no es lo mismo que un spawn fresco, y confundirlos haría
                    # que el desglose atribuya al modelo un arranque que no ocurrió.
                    # UN SOLO EVENTO, CON SU DURACIÓN ADENTRO. Emitir también un
                    # `spawned` acá le pondría el timestamp del FINAL —los dos saldrían
                    # con la misma hora— y el desglose leería un intervalo de cero. El
                    # `dur_ms` es el dato real y el lector reconstruye [fin−dur, fin].
                    try:
                        _mb = dict(getattr(_rb, "meta", None) or {})
                        _reg_br.anotar_evento("process_exited", turno_id=_t.id,
                                              provider=_t.provider,
                                              pid=_mb.get("pid"), via="broker",
                                              returncode=0, reason="broker",
                                              cola_ms=0.0,
                                              reusado=bool(_mb.get("reusado")),
                                              dur_ms=round((time.monotonic() - _t_br) * 1000.0, 1))
                    except Exception:                       # noqa: BLE001 — anotar jamás
                        pass                                # tumba un turno
                if _rb is not None:
                    _res = _broker.a_brain_result(_rb, self, mdl)
                    _m = dict(_res.meta or {})
                    _m["stream"] = {"cierre": "broker", "stream_json": stream,
                                    "lineas": 0, "no_json": 0}
                    _m["timing"] = {"provider": "broker", "model_resolution_s": round(
                        _timing["model_resolved_mono"] - _timing["invoke_started_mono"], 3),
                        "execution_s": round(time.monotonic() - _t_br, 3)}
                    _res = replace(_res, meta=_m, resolved_model=mdl)
                    # ⚠️ EL FAIL-CLOSED DEL WRAPPER TAMBIÉN ACÁ. Es la misma regla de abajo
                    # (review HIGH #4) y **no se puede perder por tomar otro camino**: si
                    # el CLI ejecutó algo por su cuenta, el resultado se descarta. Un
                    # broker que se saltea el gate sería una optimización que hace que algo
                    # deje de decirse.
                    if _res.ok and _res.exec_events > 0:
                        return BrainResult(
                            ok=False, error_kind=ERR_MODEL,
                            exec_events=_res.exec_events,
                            error_detail=(f"{self.display_name} ejecutó {_res.exec_events} "
                                          "acción(es) por su cuenta durante la cognición "
                                          "(el wrapper debe ser puro in/out) — resultado "
                                          "descartado por seguridad. Las herramientas del "
                                          "harness se llaman igual que las suyas: tenía "
                                          "que PEDIRLAS con <function=…>, no usar las "
                                          "propias"),
                            meta=_res.meta,
                            causa=_causa_del_wrapper(
                                f"{self.display_name} ejecutó acciones por su cuenta "
                                f"durante la cognición — resultado descartado",
                                acciones=_res.exec_events))
                    return _res
        except Exception as _e:                             # noqa: BLE001 — el broker JAMÁS
            import sys as _s
            print(f"[broker] descartado ({type(_e).__name__}: {_e}); "      # rompe un turno
                  f"sigue el camino de hoy", file=_s.stderr, flush=True)

        try:
            # Las imágenes cambian el argv (otro formato de entrada) y abren stdin. Sólo
            # se le pasan al provider que las declara: los otros no conocen el kwarg y
            # su argv queda byte-idéntico.
            _imgs = list(imagenes or []) if self.soporta_imagenes() else []
            if imagenes and not _imgs:
                print(f"[cli_brain] ⚠ {self.provider_id} no transporta imágenes: "
                      f"{len(imagenes)} descartada(s); el prompt lleva sus marcas",
                      file=sys.stderr, flush=True)
            _extra = {"imagenes": _imgs} if self.soporta_imagenes() else {}
            argv = assert_argv_safe(self.build_argv(b, prompt, mdl, workdir,
                                                    effort=effort, stream=stream,
                                                    sesion=sesion, **_extra))
            _stdin = self.build_stdin(prompt, _imgs) if _imgs else None
            try:
                r, stats = _run_streaming(
                    argv, cwd=workdir,
                    env=sanitized_env(b),  # cognición atribuida a la SUSCRIPCIÓN, sin fuga de secretos
                    timeout=timeout if timeout is not None else DEFAULT_TIMEOUT,
                    chunk_timeout=(chunk_timeout if chunk_timeout is not None
                                   else STREAM_CHUNK_TIMEOUT),
                    on_linea=_linea, turno=_t, binario=b,
                    deadline_mono=deadline_mono,
                    corta_ya=(lambda: fin_limpio_visto),
                    al_cosechar=_borrar_workdir,
                    stdin_payload=_stdin,
                    timing=_timing,
                )
            except FileNotFoundError:
                return BrainResult(ok=False, error_kind=ERR_NOT_INSTALLED,
                                   error_detail=f"`{b}` desapareció del disco",
                                   causa=_causa_tipada("command not found", 127))
            except subprocess.TimeoutExpired:
                if _t.detener_pedido:
                    return _detenido()
                return BrainResult(ok=False, error_kind=ERR_TIMEOUT,
                                   error_detail=f"{self.display_name} agotó el deadline "
                                                "compartido del turno",
                                   meta={"timing": _timing_summary(_timing, "cli_deadline")},
                                   causa=_causa_tipada("", None,
                                                       {"is_error": True,
                                                        "terminal_reason": "timeout"}))
            if _t.detener_pedido:
                return _detenido()
            # Los `parse_result` existentes esperan la forma de `--output-format json`. El
            # evento `result` del stream-json trae los MISMOS campos, así que se le pasa
            # serializado y el parser no cambia una línea. Sin evento (o provider sin
            # streaming) → stdout crudo, byte-idéntico a lo que daba `communicate`.
            salida = json.dumps(evento_resultado) if (stream and evento_resultado) else (r.stdout or "")
            res = self.parse_result(r.returncode, salida, r.stderr or "", workdir, mdl)
            _meta = dict(res.meta or {})
            _meta["stream"] = {**stats.como_dict(), "eventos_parciales": eventos_parciales,
                               "no_json": no_json, "stream_json": stream}
            _meta["timing"] = _timing_summary(_timing)
            # F2a · la causa TIPADA del traductor F1. El `result_event` manda si lo hay.
            _causa = res.causa
            if not res.ok and _causa is None:
                _causa = _causa_tipada(r.stderr or "", r.returncode,
                                       evento_resultado or None, stdout=salida)
            res = replace(res, meta=_meta, causa=_causa, resolved_model=mdl)
            # FAIL-CLOSED (review HIGH #4): el wrapper es pura cognición. Si el CLI EJECUTÓ
            # algo por su cuenta (comando/patch/mcp/web — exec_events>0), el contrato se violó:
            # NO devolvemos ese resultado como bueno (podría traer datos que el CLI leyó del
            # disco/red sin pasar por el gate de Aleph). Se degrada a error honesto.
            if res.ok and res.exec_events > 0:
                return BrainResult(
                    ok=False, error_kind=ERR_MODEL, exec_events=res.exec_events,
                    error_detail=(f"{self.display_name} ejecutó {res.exec_events} acción(es) por "
                                  "su cuenta durante la cognición (el wrapper debe ser puro in/out) "
                                  "— resultado descartado por seguridad. Las herramientas del "
                                  "harness se llaman igual que las suyas: tenía que PEDIRLAS con "
                                  "<function=…>, no usar las propias"),
                    meta=res.meta,
                    # Este fallo no es del proveedor ni de la persona: nuestro wrapper no logró
                    # mantener puro al CLI. `falla_de_aleph` es exactamente esa causa, y su
                    # camino en la UI es [Copiar el reporte], no «revisá tu configuración».
                    causa=_causa_del_wrapper(
                        f"{self.display_name} ejecutó acciones por su cuenta durante la "
                        f"cognición — resultado descartado",
                        acciones=res.exec_events))
            return res
        finally:
            # El workdir de una SESIÓN no se borra: borrarlo es perder la conversación
            # (medido: el store del CLI se indexa por cwd). Lo poda `Sesiones`, que es
            # quien sabe cuándo la charla terminó.
            #
            # ⚠️ Y EL EFÍMERO YA NO SE BORRA ACÁ: lo borra `_borrar_workdir`, que
            # `_run_streaming` llama cuando el proceso murió DE VERDAD. Con la cola cortada
            # el CLI sigue vivo medio segundo después de que este `finally` corre, y codex
            # todavía está escribiendo su `last-message.txt` adentro (medido: +252 ms).
            # Este `finally` sigue cubriendo los caminos que NO llegan a `_run_streaming`
            # (binario ausente, argv rechazado), donde el borrado tiene que ocurrir igual.
            _cosecha_manda = False
            try:
                _cosecha_manda = (stats.cierre == "evento_terminal")
            except (NameError, UnboundLocalError, AttributeError):
                # `stats` no llegó a existir (binario ausente, argv rechazado, deadline):
                # no hay cosechador, así que el borrado es de acá. Fail-closed hacia
                # BORRAR: un workdir que nadie borra es una fuga de disco por turno.
                _cosecha_manda = False
            if not _cosecha_manda:
                _borrar_workdir()
            # El turno que abrimos acá lo cerramos acá. El que nos prestaron NO: lo cierra
            # quien lo abrió (el server, en su propio `finally`), porque hasta que él no
            # termine de escribir la respuesta el turno todavía existe para el `stop`.
            if _turno_propio:
                cerrar_turno(_t.id)
