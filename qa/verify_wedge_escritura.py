#!/usr/bin/env python3
"""verify_wedge_escritura.py — LA VARA del cuelgue de escritura del sidecar.

QUÉ PRUEBA. El sidecar entraba en un estado permanente donde el camino de datos dejaba
de responder para siempre: no era contención de SQLite (no había `database is locked` ni
a los 75 s) sino el mutex de la tabla de inodos del VFS unix de SQLite, trabado entre el
`open()` de un hilo y el `close()` de otro. Diagnóstico y stacks: `platform/db/sqlite_db.py`
§EL DEADLOCK DEL VFS.

CÓMO. Contra un sidecar REAL levantado del árbol (puerto y datadir propios), cada ronda:

  1. escritura de referencia            POST /v1/auth/local responde  → punto de partida sano
  2. CARGA — lo que lo mataba, junto:
       · turnos reales por /v1/puppets/run/stream **cortados a mitad** (el cliente cierra
         el socket con el stream abierto: el generador sigue vivo en su hilo y escribe
         la respuesta parcial en el chat — escritura desde un hilo ya abandonado),
       · escrituras concurrentes desde varios hilos (auth/local + chats),
       · el reaper del worker pool corriendo (`PUPPET_WORKER_RECLAIM_S=2`: escribe
         `jobs.reclaim_stale` DENTRO de la ventana del test, no cada 60 s).
  3. LA PREGUNTA                        ¿la escritura SIGUE respondiendo?  ← el veredicto
  4. /health                            no puede decir "ok" si el camino de datos murió

TRES RONDAS, cada una con sidecar y datadir NUEVOS. El bug es intermitente: una corrida
verde no prueba nada, y por eso el criterio de cierre es 3/3.

Uso:
    python3 qa/verify_wedge_escritura.py                    # este árbol
    WEDGE_ARBOL=/tmp/aleph-baseline python3 qa/…            # otro árbol (contraste)
    WEDGE_PUERTO=8221 WEDGE_RONDAS=3 python3 qa/…
"""
from __future__ import annotations

import http.client
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
ARBOL = Path(os.environ.get("WEDGE_ARBOL") or AQUI.parent)
PUERTO = int(os.environ.get("WEDGE_PUERTO", "8221"))
RONDAS = int(os.environ.get("WEDGE_RONDAS", "3"))
PY = os.environ.get("WEDGE_PY") or sys.executable
BASE = f"127.0.0.1:{PUERTO}"

#: Carga. Calibrada CONTRA EL ÁRBOL ROTO, no a ojo: con 60 escrituras por hilo el bug
#: aparecía en 1 de cada 3 rondas (medido) — o sea que 3 rondas verdes podían ser suerte
#: en un 30% de los casos. Con 200 la ventana es lo bastante ancha para pegarle en cada
#: ronda. La vara tiene que ser capaz de fallar; si no, no mide nada.
HILOS = 16
ESCRITURAS_POR_HILO = 200
TURNOS_CORTADOS = 6

#: El "modelo" callado al que apunta la receta (se levanta en main()).
SUMIDERO = None

#: Plazo de la escritura del veredicto. Generoso a propósito: si tarda MÁS que esto no es
#: lentitud, es el cuelgue (el trabado no vuelve nunca — medido a 120 s).
PLAZO_VEREDICTO = 20.0

#: Receta v1 ANIDADA válida (la de `tests/phase1/conftest.py:valid_recipe`, sin `rag` ni
#: `keys`: apuntan a archivos/BYOK que este harness no monta). Tiene que VALIDAR — con una
#: receta inválida el endpoint corta en 422 y el "corte a mitad de stream" no corta nada.
RECETA = {
    "schema_version": "v1",
    "meta": {"name": "Vara", "nicho": "finanzas", "descripcion": "sonda del cuelgue"},
    "model": {"primary": "gpt-oss-120b", "fallback": "llama-3.3-70b",
              "base_url": "http://127.0.0.1:4000/v1", "temperature": 0,
              "max_tokens": 2048, "max_turns": 8},
    # `tool_filters` NO puede ir vacío (§3.3: sólo el subset curado) — con `{}` el
    # endpoint corta en 422 y el corte a mitad de stream no cortaría nada.
    "belt": {"belt_ref": "catalog/belts/finanzas.md",
             "tool_filters": {"excel": ["apply_formula", "read_data_from_excel"],
                              "secedgar": ["get_cik_by_ticker", "get_financials"]}},
    "framing": {"ref": "framing/finanzas.md", "inline": None},
    "rag": {"enabled": False, "mode": "manual", "dir": None},
    "gates": {"money_touch": "needs_ok", "send": "needs_ok"},
}

fallas: list[str] = []


def ok(cond: bool, etiqueta: str, extra: str = "") -> bool:
    print(f"  {'✓' if cond else '✗'} {etiqueta}{('  — ' + extra) if extra else ''}", flush=True)
    if not cond:
        fallas.append(etiqueta)
    return cond


# ── HTTP mínimo (stdlib): cada llamada con plazo, ninguna puede colgar el harness ──
def pedir(metodo: str, ruta: str, cuerpo=None, token=None, plazo=10.0):
    """(status, json|texto, ms). status None = no contestó dentro del plazo."""
    t0 = time.monotonic()
    try:
        c = http.client.HTTPConnection("127.0.0.1", PUERTO, timeout=plazo)
        h = {"Content-Type": "application/json"}
        if token:
            h["Authorization"] = f"Bearer {token}"
        c.request(metodo, ruta, json.dumps(cuerpo) if cuerpo is not None else None, h)
        r = c.getresponse()
        crudo = r.read().decode("utf-8", "replace")
        c.close()
        try:
            return r.status, json.loads(crudo), (time.monotonic() - t0) * 1000
        except ValueError:
            return r.status, crudo, (time.monotonic() - t0) * 1000
    except Exception as exc:                       # timeout, socket cerrado, etc.
        return None, f"{type(exc).__name__}: {exc}", (time.monotonic() - t0) * 1000


class Sumidero(threading.Thread):
    """Acepta conexiones y NO contesta por unos segundos, después cierra.

    Es el "modelo" al que apunta la receta. Sirve para que el generador del SSE esté VIVO
    cuando el cliente corta: si el turno fallara al instante (gateway ausente → connection
    refused) el "corte a mitad de stream" no cortaría nada y el test se mentiría solo.
    Retención acotada para no dejar hilos colgados más allá de la ventana del test."""

    def __init__(self, retencion: float = 3.0):
        super().__init__(daemon=True)
        self.retencion = retencion
        self._s = socket.socket()
        self._s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._s.bind(("127.0.0.1", 0))
        self._s.listen(64)
        self.puerto = self._s.getsockname()[1]
        self._parar = threading.Event()

    def run(self):
        self._s.settimeout(0.5)
        pendientes: list[tuple[socket.socket, float]] = []
        while not self._parar.is_set():
            try:
                c, _ = self._s.accept()
                pendientes.append((c, time.monotonic()))
            except (socket.timeout, OSError):
                pass
            ahora = time.monotonic()
            for c, t in list(pendientes):
                if ahora - t > self.retencion:
                    try:
                        c.close()
                    except OSError:
                        pass
                    pendientes.remove((c, t))
        for c, _ in pendientes:
            try:
                c.close()
            except OSError:
                pass

    def cerrar(self):
        self._parar.set()
        try:
            self._s.close()
        except OSError:
            pass


def turno_cortado(token: str, uid: str, chat_id: str, brusco: bool) -> str:
    """Abre /v1/puppets/run/stream y CORTA con el stream vivo.

    A mano con un socket crudo porque hay que cerrar en un punto controlado —
    `brusco` manda RST (SO_LINGER 0, el cable arrancado); si no, FIN (la pestaña que
    se cierra). Los dos dejan al generador del SSE corriendo en su hilo, que después
    escribe en la DB sin nadie del otro lado: el escenario exacto del reporte."""
    receta = json.loads(json.dumps(RECETA))
    if SUMIDERO is not None:                     # el "modelo" que se queda callado
        receta["model"]["base_url"] = f"http://127.0.0.1:{SUMIDERO.puerto}/v1"
    cuerpo = json.dumps({
        "recipe": receta,
        "prompt": "decime un numero",
        "user_id": uid,
        "chat_id": chat_id,
    })
    pedido = (
        f"POST /v1/puppets/run/stream HTTP/1.1\r\nHost: {BASE}\r\n"
        f"Authorization: Bearer {token}\r\nContent-Type: application/json\r\n"
        f"Accept: text/event-stream\r\nContent-Length: {len(cuerpo)}\r\n\r\n{cuerpo}"
    ).encode()
    s = socket.create_connection(("127.0.0.1", PUERTO), timeout=8)
    estado = "sin-respuesta"
    try:
        s.sendall(pedido)
        s.settimeout(6)
        try:
            # Dejamos que el turno ARRANQUE (línea de estado / primer frame) y ahí cortamos.
            # Se devuelve el código real: un corte sobre un stream que nunca abrió no
            # probaría nada, así que la vara lo dice en vez de suponerlo.
            cab = s.recv(256).decode("latin-1", "replace")
            estado = cab.split("\r\n", 1)[0].replace("HTTP/1.1 ", "").strip()[:16] or "vacío"
        except socket.timeout:
            estado = "abierto-sin-frame"
        if brusco:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                         struct.pack("ii", 1, 0))    # close() → RST
    finally:
        s.close()
    return f"{'RST' if brusco else 'FIN'}@{estado}"


def carga_concurrente(token: str, uid: str) -> dict:
    """Escrituras REALES desde varios hilos a la vez — el churn de conexiones que
    disparaba el deadlock. Cuenta las que contestaron y las que se colgaron."""
    hechas = {"ok": 0, "colgadas": 0, "otras": 0}
    cerrojo = threading.Lock()

    def rutina(i: int):
        loc = {"ok": 0, "colgadas": 0, "otras": 0}
        seguidas = 0
        for n in range(ESCRITURAS_POR_HILO):
            if i % 2 == 0:
                st, _, _ = pedir("POST", "/v1/auth/local", plazo=8)
            else:
                st, _, _ = pedir("POST", "/v1/chats",
                                 {"user_id": uid, "title": f"carga-{i}-{n}"},
                                 token=token, plazo=8)
            if st is None:
                loc["colgadas"] += 1
                seguidas += 1
                # Tres seguidas sin respuesta = el proceso ya está trabado y no vuelve
                # (medido: 120 s sin contestar). Seguir golpeando sólo alarga el test.
                if seguidas >= 3:
                    break
            else:
                seguidas = 0
                if 200 <= st < 300:
                    loc["ok"] += 1
                else:
                    loc["otras"] += 1
        with cerrojo:
            for k in hechas:
                hechas[k] += loc[k]

    hs = [threading.Thread(target=rutina, args=(i,), daemon=True) for i in range(HILOS)]
    for h in hs:
        h.start()
    for h in hs:
        h.join(timeout=180)
    return hechas


# ── el sidecar bajo prueba ────────────────────────────────────────────────────────
def levantar(datadir: str) -> subprocess.Popen:
    env = dict(os.environ)
    env.update({
        "ALEPH_ROLE": "client",
        "ALEPH_DATA_DIR": datadir,
        "PYTHONUNBUFFERED": "1",
        # El reaper ESCRIBE (jobs.reclaim_stale). A 60 s no entra en la ventana del test;
        # a 2 s corre muchas veces y suma su churn de conexiones, que es lo que se prueba.
        "PUPPET_WORKER_RECLAIM_S": "2",
        "PUPPET_WORKER_STALE_S": "2",
        "PYTHONPATH": os.pathsep.join(str(ARBOL / p) for p in (
            "product/backend", "platform", "platform/db", "platform/flywheel",
            "platform/gates", "platform/assembler", "platform/connectors",
            "platform/sanitizer")),
    })
    return subprocess.Popen(
        [PY, str(ARBOL / "deploy" / "fase4" / "sidecar_serve.py"), "--port", str(PUERTO)],
        cwd=str(ARBOL / "product" / "backend"), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def esperar_sano(intentos: int = 60) -> bool:
    for _ in range(intentos):
        st, _, _ = pedir("GET", "/health", plazo=2)
        if st == 200:
            return True
        time.sleep(1)
    return False


def matar(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), 9)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    try:
        proc.wait(timeout=10)
    except Exception:
        pass


def ronda(n: int) -> None:
    print(f"\n══ RONDA {n}/{RONDAS} ══", flush=True)
    datadir = tempfile.mkdtemp(prefix=f"wedge-{n}-")
    proc = levantar(datadir)
    try:
        if not ok(esperar_sano(), "el sidecar arranca y contesta /health"):
            return

        # 1 · punto de partida: la escritura anda
        st, cuerpo, ms = pedir("POST", "/v1/auth/local", plazo=15)
        if not ok(st == 200, "escritura de referencia (POST /v1/auth/local)",
                  f"{st} en {ms:.0f} ms"):
            return
        token, uid = cuerpo.get("session_token"), cuerpo.get("id")
        st, chat, _ = pedir("POST", "/v1/chats", {"user_id": uid, "title": "vara"},
                            token=token, plazo=15)
        chat_id = (chat or {}).get("chat", {}).get("id") if isinstance(chat, dict) else None
        if isinstance(chat, dict) and not chat_id:
            chat_id = chat.get("id")

        # 2 · CARGA: turnos cortados a mitad + escrituras concurrentes + reaper corriendo
        cortes = []
        for i in range(TURNOS_CORTADOS):
            try:
                cortes.append(turno_cortado(token, uid, chat_id or "", brusco=i % 2 == 1))
            except Exception as exc:                      # noqa: BLE001
                cortes.append(f"err:{type(exc).__name__}")
        print(f"  · {len(cortes)} turnos cortados a mitad de stream ({' '.join(cortes)})",
              flush=True)
        t0 = time.monotonic()
        hechas = carga_concurrente(token, uid)
        print(f"  · carga: {hechas['ok']} escrituras OK · {hechas['otras']} con error · "
              f"{hechas['colgadas']} COLGADAS  ({time.monotonic()-t0:.0f}s)", flush=True)
        ok(hechas["colgadas"] == 0, "ninguna escritura de la carga se colgó",
           f"{hechas['colgadas']} sin respuesta")
        time.sleep(3)                                     # que el reaper corra otra vez

        # 3 · EL VEREDICTO: después de todo eso, ¿la escritura sigue viva?
        st, _, ms = pedir("POST", "/v1/auth/local", plazo=PLAZO_VEREDICTO)
        ok(st == 200, "DESPUÉS de la carga la ESCRITURA sigue respondiendo",
           f"{st if st is not None else 'SIN RESPUESTA'} en {ms:.0f} ms")
        st, _, ms = pedir("GET", f"/v1/chats?user_id={uid}", token=token, plazo=PLAZO_VEREDICTO)
        ok(st == 200, "…y la LECTURA también (mueren juntas o viven juntas)",
           f"{st if st is not None else 'SIN RESPUESTA'} en {ms:.0f} ms")

        # 4 · /health no puede decir "ok" si el camino de datos murió
        st, salud, _ = pedir("GET", "/health", plazo=10)
        datos = (salud or {}).get("datos") if isinstance(salud, dict) else None
        ok(isinstance(datos, dict), "/health REPORTA el estado del camino de datos",
           json.dumps(datos) if datos else "sin campo `datos`")
        if isinstance(datos, dict):
            ok(datos.get("estado") == "ok", "…y ese estado es sano",
               json.dumps(datos))
        proceso = (salud or {}).get("proceso") if isinstance(salud, dict) else None
        ok(isinstance(proceso, dict) and "build" in proceso,
           "/health identifica el build del proceso (anti proceso-fantasma)",
           json.dumps(proceso) if proceso else "sin campo `proceso`")
    finally:
        matar(proc)
        shutil.rmtree(datadir, ignore_errors=True)


def main() -> int:
    print(f"══ VARA · cuelgue de ESCRITURA del sidecar ══\n"
          f"   árbol   {ARBOL}\n   puerto  {PUERTO}   rondas {RONDAS}\n"
          f"   carga   {HILOS} hilos × {ESCRITURAS_POR_HILO} escrituras + "
          f"{TURNOS_CORTADOS} turnos cortados + reaper cada 2 s", flush=True)
    libre = socket.socket()
    try:
        libre.bind(("127.0.0.1", PUERTO))
    except OSError:
        print(f"✗ el puerto {PUERTO} está ocupado — no piso a nadie. Salgo.")
        return 2
    finally:
        libre.close()

    global SUMIDERO
    SUMIDERO = Sumidero()
    SUMIDERO.start()
    try:
        for n in range(1, RONDAS + 1):
            ronda(n)
    finally:
        SUMIDERO.cerrar()
    print(f"\n══ {'FALLARON ' + str(len(fallas)) if fallas else 'TODO VERDE'} "
          f"({RONDAS} rondas) ══")
    for f in fallas:
        print("  ✗ " + f)
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main())
