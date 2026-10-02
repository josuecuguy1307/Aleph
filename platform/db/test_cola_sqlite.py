"""test_cola_sqlite.py — LA COLA en SQLite, con el worker pool REAL. [Casa 2 · Fase 2 · 2.3]

Por qué este archivo existe aparte: el spike que autorizó el paso 2.3 era sintético —8
hilos sobre una tabla mínima— y el plan lo admite en su §7 ("lo que no verifiqué"). Un
verde ahí no dice nada sobre el pool real, que además del claim tiene heartbeat por job
en curso y un reaper periódico: ~9 hilos escritores contra el único write lock de SQLite.
Así que acá se corre el `WorkerPool` de `app/infra/worker.py` tal cual, con los 4 workers
que trae `bootstrap.py` por default, contra el SCHEMA REAL (`schema_sqlite.sql`, 20
tablas), y se mide el EFECTO: que cada job se ejecute exactamente una vez y que su
payload llegue al handler como un dict.

Esa última parte es la que separa "la cola arranca" de "la cola sirve". `payload` es
JSONB en Postgres —psycopg2 lo decodifica— y TEXT en SQLite. Sin decodificarlo, el claim
funciona perfecto y después `run_handler` hace `payload.get('recipe')` sobre un str y
muere con AttributeError en cada job. La cola estaría "verde" y el producto roto.

⚠️ LOS RITMOS DE ESTE ARCHIVO SON PARTE DE LO QUE PRUEBA — no los bajes "para que corra
más rápido". La primera versión usaba `poll_interval_s=0.01` y **deadlockeaba la suite
entera**. No era un bug de la cola: en el cliente `pooled_conn()` no poolea, así que cada
vuelta del poll abre y cierra una conexión, y a 0.01 s × 4 workers eso es ~400 aperturas
por segundo. A ese ritmo el `open()` y el `close()` se traban entre sí en el mutex del VFS
unix de SQLite —global al PROCESO, no el write lock del archivo— y el proceso queda
bloqueado en C, con el GIL tomado, donde ningún timeout de Python corre.

Medido (`reports/step5/CASA2-FASE2-PLAN.md` §3b): traba a poll=0.01 (400 conn/s), sano de
poll=0.02 (200 conn/s) para arriba. **Producción usa 1.0 s = 4 conn/s** (`bootstrap.py:47`),
o sea 100× del otro lado del umbral: el deadlock era artefacto del test, no un defecto del
cliente. Por eso acá se usa el poll REAL de producción, y el heartbeat y el reaper —que
también abren conexión por tick— se dejan rápidos pero lejos del umbral.

Y eso NO hace lento al test: el worker sólo duerme `poll_interval_s` cuando la cola está
VACÍA (`worker.py:117-119`). Con los jobs ya encolados los drena espalda contra espalda.

Correr:  pytest platform/db/test_cola_sqlite.py -v
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import threading
import time
from collections import Counter

import pytest

_AQUI = os.path.dirname(os.path.abspath(__file__))
_PLATFORM = os.path.dirname(_AQUI)
_RAIZ = os.path.dirname(_PLATFORM)
_BACKEND = os.path.join(_RAIZ, "product", "backend")
for _p in (_AQUI, _PLATFORM, _BACKEND):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ── andamio ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _entorno():
    """Deja el entorno como estaba: estos tests mueven ALEPH_ROLE y PUPPET_SQLITE_PATH,
    y el resto de la suite (y el rol por default) no tienen por qué enterarse."""
    previo = {k: os.environ.get(k) for k in ("ALEPH_ROLE", "PUPPET_SQLITE_PATH")}
    yield
    for k, v in previo.items():
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def _cliente(tmp_path, nombre="cola.db"):
    """Pone el proceso en rol cliente apuntando a un .db limpio, con el schema real."""
    ruta = str(tmp_path / nombre)
    os.environ["ALEPH_ROLE"] = "client"
    os.environ["PUPPET_SQLITE_PATH"] = ruta
    for mod in ("role", "db", "pool"):
        if mod in sys.modules:
            importlib.reload(sys.modules[mod])
    import sqlite_db
    c = sqlite_db.conectar(ruta)
    sqlite_db.crear_schema(c)
    c.commit()
    c.close()
    return ruta


def _conn(ruta):
    import sqlite_db
    return sqlite_db.conectar(ruta)


def _contar(ruta, sql, params=()):
    c = _conn(ruta)
    try:
        return c.raw.execute(sql, params).fetchone()[0]
    finally:
        c.close()


# ── 1. EL EFECTO REAL: el pool de bootstrap drenando la cola ──────────────────

def test_los_4_workers_reales_drenan_la_cola_sin_doble_claim(tmp_path):
    """El `WorkerPool` de verdad —4 workers + heartbeat por job + reaper— contra el
    schema real. Se mide lo que importa: cada job UNA vez, el payload como dict,
    cero perdidos.

    El reaper corre de verdad para que contienda por el write lock, pero con un umbral
    de 300 s para que NUNCA reclame un job sano: si reclamara, el re-claim sería
    CORRECTO y este test lo leería como doble-claim. La contención es parte del
    escenario; el reclamo espurio sería un bug del test.

    N es chico A PROPÓSITO: esto prueba CORRECTITUD (cada job una vez, payload como
    dict), no volumen. 16 jobs contra 4 workers ya fuerza la carrera del claim; subirlo
    a 120 no agrega un modo de falla, sólo alarga el test. El volumen bajo presión lo
    cubren `test_el_claim_de_una_sentencia_no_doble_claimea` (300 jobs · 8 hilos) y el
    par rojo/verde del guard (200 jobs · 8 hilos), que usan UNA conexión por hilo y por
    lo tanto no generan churn.
    """
    ruta = _cliente(tmp_path)
    from app.infra import jobs
    from app.infra.worker import WorkerPool

    N = 16
    conn = _conn(ruta)
    esperados = {}
    for i in range(N):
        row = jobs.enqueue(conn, "puppet_run", {"recipe": f"r{i}", "prompt": f"p{i}"})
        esperados[row["id"]] = i
        assert isinstance(row["payload"], dict), "enqueue ya debe devolver el payload decodificado"
    conn.close()
    assert _contar(ruta, "SELECT count(*) FROM job_queue WHERE status='queued'") == N

    vistos, malformados = [], []
    lock = threading.Lock()

    def handler(job):
        # EL EFECTO: esto es lo que hace run_handler.handle con el payload.
        p = job.get("payload") or {}
        if not isinstance(p, dict) or not p.get("recipe"):
            with lock:
                malformados.append((job["id"], type(p).__name__, repr(p)[:60]))
            return {}
        with lock:
            vistos.append(job["id"])
        time.sleep(0.12)           # dura lo suficiente para que el heartbeat lata 2 veces
        return {"eco": p["recipe"]}

    pool = WorkerPool(
        {"puppet_run": handler},
        n_workers=4,               # el default de bootstrap.py
        poll_interval_s=1.0,       # el de PRODUCCIÓN (bootstrap.py:47) — ver cabecera
        heartbeat_s=0.05,          # un escritor más por job en curso…
        reclaim_every_s=0.2,       # …y el reaper contiende…
        reclaim_older_than_s=300,  # …pero no reclama nada sano
    )
    pool.start()
    try:
        # Tope de ITERACIONES, no sólo de reloj: este loop abre una conexión por vuelta
        # (`_contar`) desde el hilo principal, que es justo el que se cuelga si el churn
        # se dispara. 200 × 50 ms = 10 s de techo, ~30× lo que tarda de verdad.
        for _ in range(200):
            if _contar(ruta, "SELECT count(*) FROM job_queue WHERE status='done'") >= N:
                break
            time.sleep(0.05)
    finally:
        pool.stop(timeout_s=15)

    repetidos = {j: n for j, n in Counter(vistos).items() if n > 1}
    assert not malformados, f"el payload no llegó como dict al handler: {malformados[:3]}"
    assert not repetidos, f"DOBLE-CLAIM: {len(repetidos)} jobs corridos más de una vez"
    assert len(vistos) == N, f"se ejecutaron {len(vistos)} de {N} jobs"
    assert set(vistos) == set(esperados), "algún job se ejecutó que no se había encolado"

    # 0 escrituras perdidas: todo cerrado, un solo intento por job, resultado persistido.
    assert _contar(ruta, "SELECT count(*) FROM job_queue WHERE status='done'") == N
    assert _contar(ruta, "SELECT count(*) FROM job_queue WHERE status<>'done'") == 0
    assert _contar(ruta, "SELECT max(attempts) FROM job_queue") == 1, \
        "attempts>1 significa que un job se reclamó dos veces"
    assert _contar(ruta, "SELECT count(*) FROM job_queue WHERE locked_by IS NOT NULL") == 0

    conn = _conn(ruta)
    try:
        for jid, i in esperados.items():
            row = jobs.get(conn, jid)
            assert isinstance(row["result"], dict), f"result volvió {type(row['result']).__name__}"
            assert row["result"]["eco"] == f"r{i}"
            assert row["payload"]["prompt"] == f"p{i}"
    finally:
        conn.close()


# ── 2. EL ROJO: sin el guard hay doble-claim, y se ve ─────────────────────────

def _claim_crudo(ruta, *, guard: bool, hilos: int, n_jobs: int) -> int:
    """Corre el claim partido en dos sentencias (SELECT id → UPDATE id), que es la
    traducción INGENUA a la que se llega al sacar `SKIP LOCKED`. Devuelve cuántos jobs
    fueron reclamados por más de un worker."""
    import sqlite_db
    ahora = "strftime('%Y-%m-%dT%H:%M:%f','now')"
    sel = (f"SELECT id FROM job_queue WHERE status='queued' AND available_at <= {ahora} "
           f"ORDER BY priority DESC, available_at ASC LIMIT 1")
    upd = ("UPDATE job_queue SET status='running', locked_by=?, attempts=attempts+1 "
           "WHERE id=?" + (" AND status='queued'" if guard else "") + " RETURNING id")

    reclamos = []
    lock = threading.Lock()
    barrera = threading.Barrier(hilos)

    def worker(w):
        c = sqlite_db.conectar(ruta)
        mios, vacios = [], 0
        barrera.wait()
        # Tope duro: en el peor caso un hilo se lleva todos los jobs y después ve 5
        # vacíos. Cualquier cosa por encima de eso es un loop que no termina, y este
        # archivo NO puede colgar la suite (ver cabecera).
        for _ in range(n_jobs + 50):
            if vacios >= 5:
                break
            fila = c.raw.execute(sel).fetchone()
            if fila is None:
                vacios += 1
                time.sleep(0.001)
                continue
            # Ensancha la ventana SELECT→UPDATE a propósito: la carrera existe igual,
            # esto sólo la hace determinista en vez de dependiente del scheduler.
            time.sleep(0.0005)
            got = c.raw.execute(upd, (f"w{w}", fila["id"])).fetchone()
            c.commit()
            if got is not None:
                vacios = 0
                mios.append(got["id"])
        c.close()
        with lock:
            reclamos.extend(mios)

    hs = [threading.Thread(target=worker, args=(w,)) for w in range(hilos)]
    for h in hs:
        h.start()
    for h in hs:
        h.join(timeout=60)
    return sum(1 for _, n in Counter(reclamos).items() if n > 1)


def test_sin_el_guard_hay_doble_claim_y_con_el_guard_no(tmp_path):
    """EL ROJO. `AND status='queued'` es lo único que separa una cola correcta de una
    que corre el mismo job en dos workers.

    ⚠️ MEDIDO, y el resultado corrige al plan: el guard es load-bearing cuando el claim
    se parte en DOS sentencias (lo que hace cualquiera al sacar `SKIP LOCKED`). En la
    forma de una sola sentencia que ship-eamos, sacarlo NO produce doble-claim —el
    subquery ya filtra por status y SQLite serializa escritores— así que ahí es
    redundante. Se conserva igual porque cuesta cero y ancla la garantía en la
    sentencia en vez de en el orden de evaluación de SQLite; pero decir que "el guard
    es lo que evita el doble-claim en la sentencia única" sería falso, y este test
    existe para fijar dónde SÍ lo evita.
    """
    ruta = _cliente(tmp_path, "rojo.db")
    from app.infra import jobs

    N, HILOS = 200, 8

    def recargar():
        c = _conn(ruta)
        c.raw.execute("DELETE FROM job_queue")
        c.commit()
        for i in range(N):
            jobs.enqueue(c, "puppet_run", {"recipe": f"r{i}"})
        c.close()

    recargar()
    sin_guard = _claim_crudo(ruta, guard=False, hilos=HILOS, n_jobs=N)
    recargar()
    con_guard = _claim_crudo(ruta, guard=True, hilos=HILOS, n_jobs=N)

    assert sin_guard > 0, (
        "sin el guard NO apareció doble-claim: el test dejó de ser rojo y ya no prueba nada")
    assert con_guard == 0, f"con el guard hubo {con_guard} jobs doble-claimeados"


def test_el_claim_de_una_sentencia_no_doble_claimea(tmp_path):
    """La forma que efectivamente corre en producción, bajo la misma presión: 8 hilos
    llamando al `jobs.claim_one` REAL. Cada job, un claim."""
    ruta = _cliente(tmp_path, "unica.db")
    from app.infra import jobs

    N, HILOS = 300, 8
    c = _conn(ruta)
    for i in range(N):
        jobs.enqueue(c, "puppet_run", {"recipe": f"r{i}"})
    c.close()

    reclamos, errores = [], []
    lock = threading.Lock()
    barrera = threading.Barrier(HILOS)

    def worker(w):
        conn = _conn(ruta)
        mios, errs = [], []
        barrera.wait()
        # Tope duro: un hilo no puede reclamar más de N jobs. Si llegara al tope, el
        # assert de abajo lo delata en vez de colgar la suite (ver cabecera).
        for _ in range(N + 50):
            try:
                job = jobs.claim_one(conn, f"w{w}")
            except Exception as exc:          # ni un `database is locked`
                errs.append(f"{type(exc).__name__}: {exc}")
                break
            if job is None:
                break
            mios.append(job["id"])
        conn.close()
        with lock:
            reclamos.extend(mios)
            errores.extend(errs)

    hs = [threading.Thread(target=worker, args=(w,)) for w in range(HILOS)]
    for h in hs:
        h.start()
    for h in hs:
        h.join(timeout=60)

    repetidos = {j: n for j, n in Counter(reclamos).items() if n > 1}
    assert not errores, f"el claim levantó excepciones: {errores[:3]}"
    assert not repetidos, f"DOBLE-CLAIM en {len(repetidos)} jobs"
    assert len(reclamos) == N, f"se reclamaron {len(reclamos)} de {N} (trabajo perdido)"


# ── 3. Lo que NO puede cambiar del lado de Postgres ───────────────────────────

def test_postgres_conserva_skip_locked():
    """El plano de control NO se unifica con el cliente, y esto lo fija.

    Con el guard solo, bajo READ COMMITTED el worker B se bloquea en el lock de fila de
    A, re-evalúa el WHERE cuando A commitea, falla el guard y devuelve 0 filas — o sea
    B no toma NADA aunque la cola esté llena. `SKIP LOCKED` existe para eso. Si alguien
    "simplifica" borrando la rama de Postgres, este test se pone rojo antes que la
    latencia de la cola en prod."""
    from app.infra import jobs
    assert "FOR UPDATE" in jobs._SQL_CLAIM_CONTROL
    assert "SKIP LOCKED" in jobs._SQL_CLAIM_CONTROL
    assert "FOR UPDATE" not in jobs._SQL_CLAIM_CLIENTE
    assert "AND status = 'queued'" in jobs._SQL_CLAIM_CLIENTE


def test_el_dialecto_sigue_rechazando_skip_locked():
    """La capa de dialecto NO aprendió a traducir `SKIP LOCKED` en 2.3, y no debe: el
    reemplazo correcto necesita un reintento del lado del caller (`claim_one`), que
    una traducción de SQL no puede inventar. Rechazar sigue siendo lo honesto."""
    from dialect import DialectoNoSoportado, traducir
    with pytest.raises(DialectoNoSoportado):
        traducir("SELECT id FROM job_queue FOR UPDATE SKIP LOCKED", ())


# ── 4. WAL y los pragmas: la cola no arranca sin ellos ────────────────────────

def test_la_cola_corre_en_wal_con_los_pragmas_puestos(tmp_path):
    """WAL no es opcional para la cola (lo dice el plan §4). Se verifica sobre una
    conexión NUEVA, que es el caso que importa: `foreign_keys` es propiedad de la
    conexión y no viaja en el archivo; WAL sí."""
    ruta = _cliente(tmp_path, "wal.db")
    c = _conn(ruta)
    try:
        assert c.raw.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert c.raw.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert c.raw.execute("PRAGMA busy_timeout").fetchone()[0] > 0
    finally:
        c.close()


def test_available_at_respeta_el_delay(tmp_path):
    """El scheduling de la cola (delay y backoff de retry) viaja por el traductor de
    intervalos. Un job con delay no se reclama antes de tiempo; uno sin delay, sí."""
    ruta = _cliente(tmp_path, "delay.db")
    from app.infra import jobs

    conn = _conn(ruta)
    try:
        tarde = jobs.enqueue(conn, "puppet_run", {"recipe": "tarde"}, delay_s=3600)
        ya = jobs.enqueue(conn, "puppet_run", {"recipe": "ya"})
        assert tarde["available_at"] > ya["available_at"]

        primero = jobs.claim_one(conn, "w0")
        assert primero is not None and primero["id"] == ya["id"]
        assert jobs.claim_one(conn, "w0") is None, "reclamó un job que aún no está disponible"
    finally:
        conn.close()


# ── 5. El segundo FOR UPDATE del árbol: methods_repo.pop_control ──────────────

def _sembrar_method_run(ruta, run_id, control):
    """Siembra respetando la cadena de FKs real (users → runs → method_runs). Con
    `foreign_keys=ON` no hay atajo, y está bien que no lo haya: es el schema del 2.1."""
    c = _conn(ruta)
    try:
        c.raw.execute("INSERT OR IGNORE INTO users (id, email) VALUES ('u-1','u1@test')")
        c.raw.execute("INSERT INTO runs (id, user_id) VALUES (?, 'u-1')", (run_id,))
        c.raw.execute(
            "INSERT INTO method_runs (run_id, user_id, state, control) VALUES (?,?,?,?)",
            (run_id, "u-1", "{}", json.dumps(control)))
        c.commit()
    finally:
        c.close()


def test_pop_control_lee_y_limpia_en_sqlite(tmp_path):
    """El otro `FOR UPDATE` del árbol. Devuelve el control VIEJO como dict y lo deja
    limpio — hoy, contra SQLite, esta llamada moría en `DialectoNoSoportado`."""
    ruta = _cliente(tmp_path, "pop.db")
    from app.phase1 import methods_repo as mr

    _sembrar_method_run(ruta, "run-1", {"remedy": {"action": "retry"}, "pause": True})
    conn = _conn(ruta)
    try:
        viejo = mr.pop_control(conn, "run-1")
        assert isinstance(viejo, dict), f"volvió {type(viejo).__name__}, no un dict"
        assert viejo["remedy"]["action"] == "retry"
        assert viejo["pause"] is True
        assert mr.read_control(conn, "run-1") == {}, "el pop no limpió"
        assert mr.pop_control(conn, "run-1") == {}, "el segundo pop debe venir vacío"
    finally:
        conn.close()


def test_pop_control_no_entrega_el_mismo_remedy_dos_veces(tmp_path):
    """La carrera que el `FOR UPDATE` cierra en Postgres: dos pops concurrentes sobre
    el mismo run. El remedy lo tiene que ver UNO solo — si lo vieran los dos, el
    executor aplicaría el mismo remedy dos veces."""
    ruta = _cliente(tmp_path, "pop_race.db")
    from app.phase1 import methods_repo as mr

    ganadores = []
    lock = threading.Lock()
    RUNS = 60
    for i in range(RUNS):
        _sembrar_method_run(ruta, f"run-{i}", {"remedy": {"n": i}})

    def pop_todos(w):
        conn = _conn(ruta)
        mios = []
        for i in range(RUNS):
            try:
                ctl = mr.pop_control(conn, f"run-{i}")
            except Exception as exc:
                mios.append(("ERROR", f"{type(exc).__name__}: {exc}"))
                continue
            if ctl:
                mios.append(("ok", i))
        conn.close()
        with lock:
            ganadores.extend(mios)

    hs = [threading.Thread(target=pop_todos, args=(w,)) for w in range(6)]
    for h in hs:
        h.start()
    for h in hs:
        h.join(timeout=60)

    errores = [g for g in ganadores if g[0] == "ERROR"]
    vistos = Counter(i for tipo, i in ganadores if tipo == "ok")
    assert not errores, f"pop_control falló bajo concurrencia: {errores[:3]}"
    repetidos = {i: n for i, n in vistos.items() if n > 1}
    assert not repetidos, f"el mismo remedy se entregó dos veces en {len(repetidos)} runs"
    assert len(vistos) == RUNS, f"se perdieron remedies: {len(vistos)} de {RUNS}"
