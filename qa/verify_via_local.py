#!/usr/bin/env python3
"""verify_via_local.py — LA VARA DE F5 (Gate 2 · la vía local · Ollama).

Lo que esta vara exige que quede verde:

    2+ pedidos SIMULTÁNEOS contra el runtime REAL → ninguno recibe `None` desnudo: el que
    corre termina bien y el que espera lo sabe, con causa TIPADA · runtime apagado →
    `sin_runtime` (no timeout, no None) · runtime VIVO pero ocupado → `timeout` con
    `runtime_ocupado`, **JAMÁS `sin_runtime`** (la distinción que motivó la fase) ·
    versión por debajo de la mínima → detectada y DICHA con el comando · perilla apagada =
    el comportamiento de antes de F5 · las ocho varas previas verdes.

QUÉ TOCA DEL OLLAMA DEL USUARIO, declarado: **sólo el modelo más chico YA INSTALADO**, y
sólo para inferir. Cero `pull`, cero `delete`, cero cambio de config. Si no hay ningún
modelo instalado, las secciones que necesitan uno se SALTEAN — no se baja nada.

El «runtime apagado» no se prueba apagando el Ollama del usuario (sería dejarle el sistema
distinto de como estaba): se apunta `_OLLAMA_URL` a un puerto muerto, que es el mismo
síntoma —connection refused— sin tocar su daemon.

    product/backend/.venv/bin/python qa/verify_via_local.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
_RAIZ = _AQUI.parent
for _p in (str(_RAIZ / "product" / "backend"), str(_RAIZ / "platform"),
           str(_RAIZ / "platform" / "assembler")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

sys.path.insert(0, str(_AQUI / "lib"))

import cola_local as C                                   # noqa: E402
import errores_modelo as E                               # noqa: E402
import higiene_store as _HIG                             # noqa: E402
from app.phase1 import centro_modelos as CM              # noqa: E402

# [H1] El `mkdtemp` de `base.invoke` se borra solo; el ESPEJO que el CLI crea en
# `~/.claude/projects/` no. Barrido al salir, y sólo de lo que apareció acá.
_HIG.vigilar()

_fallos = 0
_salteados = 0


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
print("VARA F5 · LA VÍA LOCAL — apagado no es ocupado, y la espera se ve")
print("=" * 80)

_URL_REAL = CM._OLLAMA_URL
_MUERTO = "http://127.0.0.1:1"


def vivo_real() -> tuple:
    try:
        with urllib.request.urlopen(_URL_REAL + "/api/version", timeout=3) as r:
            return True, json.loads(r.read().decode() or "{}").get("version", "")
    except Exception:
        return False, ""


def modelo_mas_chico():
    """El más chico YA INSTALADO. `None` si no hay ninguno — no se baja nada."""
    try:
        with urllib.request.urlopen(_URL_REAL + "/api/tags", timeout=6) as r:
            ms = json.loads(r.read().decode() or "{}").get("models") or []
    except Exception:
        return None
    if not ms:
        return None
    m = sorted(ms, key=lambda x: x.get("size", 0))[0]
    return m.get("name"), m.get("size", 0), ((m.get("details") or {}).get("family") or "")


VIVO, VER = vivo_real()
INST = modelo_mas_chico() if VIVO else None
print(f"\nOllama: {'vivo v' + VER if VIVO else 'NO responde'}"
      + (f" · modelo de prueba: {INST[0]} ({INST[1] / 1e9:.2f} GB, {INST[2]})" if INST else ""))

try:
    # ══ 1 · LA DISTINCIÓN (obra 1) ═════════════════════════════════════════════════
    seccion("1 · apagado ≠ ocupado — la distinción que motivó la fase")
    c_apagado = E.desde_ollama(TimeoutError("timed out"), url=_URL_REAL, runtime_vivo=False)
    ok(c_apagado.causa == E.SIN_RUNTIME,
       "timeout con el runtime CONFIRMADO apagado → sin_runtime", c_apagado.causa)
    c_ocupado = E.desde_ollama(TimeoutError("timed out"), url=_URL_REAL, runtime_vivo=True)
    # F1c · el hueco #6 de F5, CERRADO: era `timeout` con el motivo en la evidencia.
    ok(c_ocupado.causa == E.RUNTIME_OCUPADO,
       "timeout con el runtime CONFIRMADO vivo → runtime_ocupado, NO sin_runtime",
       c_ocupado.causa)
    ok(c_ocupado.causa != E.SIN_RUNTIME,
       "→ y ésta es la fase entera: el runtime que contesta jamás se narra como ausente")
    ok(c_ocupado.causa != E.TIMEOUT,
       "→ y tampoco `timeout`, que en repair es un GRIS que se desempata por `murio`: acá "
       "no hay nada que desempatar, se MIDIÓ que el runtime está vivo y encolando")
    ok(c_ocupado.evidencia.get("motivo") == "runtime_ocupado",
       "con `motivo: runtime_ocupado` en la evidencia (se CONSERVA: hay quien ya lo lee)",
       str(c_ocupado.evidencia))
    ok(c_ocupado.reintentable is True, "y reintentable: esperar SÍ sirve")
    c_sinsaber = E.desde_ollama(TimeoutError("timed out"), url=_URL_REAL)
    ok(c_sinsaber.causa == E.SIN_RUNTIME,
       "sin saber (None) el veredicto es el de F1b, byte por byte", c_sinsaber.causa)

    seccion("1b · centro_modelos ya NO se arma las causas a mano")
    fuente = (Path(_RAIZ) / "product/backend/app/phase1/centro_modelos.py").read_text()
    ok("_causa_ollama" in fuente and "desde_ollama" in fuente,
       "consume `errores_modelo.desde_ollama` (hereda F1b entero)")
    ok("causa = MV.TIMEOUT if isinstance(ex, TimeoutError) else MV.ERROR_UPSTREAM" not in
       fuente.split("if c is None:")[0],
       "y el armado a mano dejó de ser el camino principal (queda sólo de rescate)")
    # los 7 casos finos, ahora disponibles desde el Centro de Modelos
    for payload, esperada, etq in (
            ({"status": 404, "error": "model not found"}, E.MODELO_NO_DISPONIBLE, "404"),
            # F1c · CAMBIO DE VEREDICTO DECLARADO: era `error_upstream` con el `motivo` en
            # la evidencia. La pantalla donde el usuario elige modelos hereda la causa
            # nueva sin tocar una línea de `centro_modelos` — que es el punto de que
            # consuma el traductor en vez de armarse las causas a mano.
            ({"status": 400, "error": "the input length exceeds the context length"},
             E.CONTEXTO_EXCEDIDO, "contexto excedido"),
            ({"status": 400, "error": "unexpected EOF"}, E.ERROR_UPSTREAM, "400 otro"),
            ({"status": 503, "error": "server busy, maximum pending requests exceeded"},
             E.RATE_LIMIT, "503 saturado"),
            ({"status": 500, "error": "cudaMalloc failed: out of memory"}, E.SIN_RUNTIME, "OOM"),
            ({"status": 500, "error": "llama runner terminated"}, E.SIN_RUNTIME, "500 otro")):
        c = CM._causa_ollama(payload)
        ok(c and c["causa"] == esperada,
           f"el Centro de Modelos ahora distingue «{etq}» → {esperada}",
           str(c and c["causa"]))

    # ══ 2 · RUNTIME APAGADO (sin tocar el del usuario) ═════════════════════════════
    seccion("2 · runtime apagado → sin_runtime · nunca None, nunca timeout")
    _guardado = CM._OLLAMA_URL
    CM._OLLAMA_URL = _MUERTO
    try:
        vivo, det = CM._ollama_vivo()
        ok(vivo is False, "contra un puerto muerto, `_ollama_vivo` dice False", str(vivo))
        r = CM.probar_local("no-existe-slug-de-prueba", tag="x", categoria="chat")
        ok(r is not None, "y `probar_local` NO devuelve None desnudo", str(r))
        ok(r.get("causa") == CM.SIN_RUNTIME,
           "sino `sin_runtime` tipado", f"{r.get('causa')} · {r.get('detalle')}")
        ok(r.get("estado") == CM.ROTO, "con estado roto")
        ok(CM._OLLAMA_URL in r.get("detalle", "") or "ollama" in r.get("detalle", "").lower(),
           "y un detalle que dice dónde miró", r.get("detalle", "")[:90])
    finally:
        CM._OLLAMA_URL = _guardado

    # ══ 3 · LA COLA (obra 2) ═══════════════════════════════════════════════════════
    seccion("3 · la cola — el N+1 recibe causa tipada, no espera mudo")
    C.COLA.reiniciar()
    ok(C.MAX_LOCAL == 1,
       "el techo default es 1, coherente con OLLAMA_NUM_PARALLEL=1 del runtime "
       "(subirlo multiplica el KV cache — medido)", str(C.MAX_LOCAL))
    C.COLA.pedir()
    ok(C.COLA.estado()["activos"] == 1, "el primer turno toma el lugar")
    try:
        C.COLA.pedir()
        ok(False, "el SEGUNDO turno se rechaza, no espera para siempre")
    except C.SinTurnoLocal as ex:
        ok(ex.motivo == C.COLA_OCUPADA,
           "el SEGUNDO turno se rechaza tipado, no espera para siempre", ex.motivo)
        cz = C.causa_de(ex)
        # F1c · era `rate_limit`. La cola local no es una cuota que se agota: es un
        # semáforo de peso 1 con otro pedido adelante. `rate_limit` queda reservado para
        # la ventana de un PROVEEDOR, y así significa UNA sola cosa en todo el producto.
        ok(cz and cz["causa"] == E.RUNTIME_OCUPADO and cz["causa"] in E.CAUSAS,
           "con una causa del vocabulario cerrado (`runtime_ocupado` = «hay cola local»)",
           str(cz and cz["causa"]))
        ok(cz and cz["causa"] != E.RATE_LIMIT,
           "y NO `rate_limit`: acá no hay ventana del proveedor que se haya agotado")
        ok(cz and cz["evidencia"]["origen"] == "aleph",
           "y `origen: aleph` — el que frenó fue NUESTRO techo; el runtime habría encolado "
           "y contestado 200 (medido). Confundir quién frenó con por qué es el defecto de "
           "LiteLLM que F2b se negó a repetir", str(cz and cz["evidencia"]))
        ok(cz and "NUM_PARALLEL" in str(cz["evidencia"].get("porque", "")),
           "…con el porqué del runtime en la evidencia, no en el origen",
           str(cz and cz["evidencia"].get("porque")))
        ok(cz and cz["reintentable"] is True, "reintentable: esperar sirve")
    C.COLA.soltar()
    ok(C.COLA.estado()["activos"] == 0, "soltar libera el lugar")
    with C.COLA.turno():
        ok(C.COLA.estado()["activos"] == 1, "el context manager toma el turno")
    ok(C.COLA.estado()["activos"] == 0, "y lo suelta al salir")
    try:
        with C.COLA.turno():
            raise ValueError("bum")
    except ValueError:
        pass
    ok(C.COLA.estado()["activos"] == 0, "lo suelta TAMBIÉN si el turno revienta")

    seccion("3b · la perilla — PUPPET_OLLAMA_COLA=0 vuelve al comportamiento de hoy")
    C.COLA.reiniciar()
    os.environ["PUPPET_OLLAMA_COLA"] = "0"
    ok(C.activa() is False, "la perilla se lee en cada llamada")
    C.COLA.pedir(); C.COLA.pedir(); C.COLA.pedir()
    ok(C.COLA.estado()["activos"] == 0,
       "con la cola apagada NADIE toma turno: los pedidos salen directo, como antes de F5",
       str(C.COLA.estado()))
    os.environ["PUPPET_OLLAMA_COLA"] = "1"
    C.COLA.reiniciar()
    ok(C.activa() is True, "y prendida vuelve a contar")

    # ══ 4 · VERSIÓN MÍNIMA (obra 3) ════════════════════════════════════════════════
    seccion("4 · versión mínima — detectada y DICHA, no un error mudo")
    ok(CM.OLLAMA_MINIMA == "0.3.4", f"el piso declarado es {CM.OLLAMA_MINIMA}", CM.OLLAMA_MINIMA)
    ok("api/embed" in CM.OLLAMA_MINIMA_PORQUE,
       "con CRITERIO escrito (el endpoint que lo fija), no un número de folclore",
       CM.OLLAMA_MINIMA_PORQUE[:80])
    baja = CM.ollama_version_ok("0.3.3")
    ok(baja["ok"] is False and baja["sabido"] is True, "0.3.3 → por debajo, detectado")
    ok("actualiza" in baja["detalle"].lower(),
       "y el mensaje es ACCIONABLE («actualizalo»), no «error»", baja["detalle"][:80])
    ok(baja.get("mano", {}).get("comando"), "con el comando exacto", str(baja.get("mano")))
    ok(CM.ollama_version_ok("0.3.4")["ok"] is True, "0.3.4 exacto → cumple (es un piso, no un >)")
    ok(CM.ollama_version_ok("0.24.0")["ok"] is True, "0.24.0 (la instalada) → cumple")
    rara = CM.ollama_version_ok("no-parseable")
    ok(rara["ok"] is True and rara["sabido"] is False,
       "una versión que no parsea NO se trata como incumplimiento: se declara desconocida "
       "(bloquear por no entender un número es peor que no chequear)", str(rara))
    maq = CM._maquina_medida()
    oll = (maq.get("runtimes") or {}).get("ollama") or {}
    if VIVO:
        ok(oll.get("version_ok") is not None,
           "y la CARD lo lleva: `runtimes.ollama.version_ok`", str(oll.get("version_ok"))[:90])
        ok(oll["version_ok"]["ok"] is True,
           f"(en esta máquina, v{VER} cumple)", str(oll.get("version_ok")))
    else:
        ok(oll.get("version_ok") is None,
           "con el runtime caído no se inventa un veredicto de versión")

    # ══ 5 · MEMORIA — OBRA 4, CONFIRMACIÓN ═════════════════════════════════════════
    seccion("5 · la memoria de Ollama NO se consulta (obra 4 · verificación)")
    hits = subprocess.run(["grep", "-rn", "size_vram", "--include=*.py", "--include=*.js",
                           "--include=*.html", str(_RAIZ)], capture_output=True, text=True)
    lineas = [l for l in hits.stdout.splitlines()
              if "node_modules" not in l and "/qa/verify_via_local.py" not in l
              and "gate2-auditorias" not in l]
    ok(not lineas,
       "`size_vram` NO aparece en NINGÚN archivo del árbol — ningún camino decide "
       "«cabe/no cabe» con la contabilidad de Ollama (sellado: en Apple Silicon da 0)",
       "\n".join(lineas[:4]))
    ok("hw.memsize" in fuente and "vm_stat" in fuente,
       "las decisiones de memoria usan la RAM REAL de la máquina (`hw.memsize` + `vm_stat`), "
       "que es otra cosa y sí sirve")
    ok("/api/ps" not in fuente,
       "y `/api/ps` no se consulta desde el Centro de Modelos", "aparece /api/ps")

    # ══ 6 · EL RUNTIME REAL — 2 SIMULTÁNEOS ════════════════════════════════════════
    seccion("6 · RUNTIME REAL — 2 pedidos simultáneos, evidencia del comportamiento")
    if not VIVO:
        saltear("los 2 simultáneos contra el Ollama real", "Ollama no responde en esta máquina")
    elif not INST:
        saltear("los 2 simultáneos contra el Ollama real",
                "no hay ningún modelo instalado (esta vara NO baja modelos)")
    else:
        TAG, _sz, FAM = INST
        es_embed = "embed" in (FAM or "").lower() or "embed" in TAG.lower()
        C.COLA.reiniciar()
        res: dict = {}

        def _tirar(k):
            t0 = time.monotonic()
            try:
                if es_embed:
                    d = CM._ollama_embed(TAG, "prueba de contención de la vara F5 " * 40)
                    bien = bool((d.get("embeddings") or [[]])[0])
                else:
                    d = CM._ollama_chat(TAG, [{"role": "user", "content": "Decí sólo: OK"}])
                    bien = bool(((d.get("choices") or [{}])[0].get("message") or {}).get("content"))
                res[k] = ("ok", bien, round(time.monotonic() - t0, 2), None)
            except Exception as ex:                        # noqa: BLE001
                res[k] = ("excepcion", False, round(time.monotonic() - t0, 2), ex)

        def _tirar2(k, destino):
            """Igual que `_tirar` pero contra el dict que se le pase — se reusa en 6c."""
            t0 = time.monotonic()
            try:
                if es_embed:
                    d = CM._ollama_embed(TAG, "prueba de contención de la vara F5 " * 40)
                    bien = bool((d.get("embeddings") or [[]])[0])
                else:
                    d = CM._ollama_chat(TAG, [{"role": "user", "content": "Decí sólo: OK"}])
                    bien = bool(((d.get("choices") or [{}])[0].get("message") or {}).get("content"))
                destino[k] = ("ok", bien, round(time.monotonic() - t0, 2), None)
            except Exception as ex:                        # noqa: BLE001
                destino[k] = ("excepcion", False, round(time.monotonic() - t0, 2), ex)

        h1 = threading.Thread(target=_tirar, args=("a",))
        h2 = threading.Thread(target=_tirar, args=("b",))
        h1.start()
        time.sleep(0.15)                                   # el segundo entra con el primero en vuelo
        h2.start()
        h1.join(timeout=300); h2.join(timeout=300)

        ok(len(res) == 2, "los dos pedidos volvieron (ninguno quedó colgado)", str(list(res)))
        ok(all(v[3] is None or not isinstance(v[3], type(None)) for v in res.values()),
           "y NINGUNO devolvió `None` desnudo — todos volvieron con algo que se puede leer",
           str(res))
        buenos = [k for k, v in res.items() if v[0] == "ok" and v[1]]
        rechazados = [k for k, v in res.items() if v[0] == "excepcion"
                      and isinstance(v[3], (C.SinTurnoLocal, CM._ColaLlena))]
        ok(len(buenos) >= 1, f"al menos uno corrió y terminó BIEN ({buenos})", str(res))
        ok(len(buenos) + len(rechazados) == 2,
           "y el otro o corrió bien también, o fue rechazado TIPADO por la cola — "
           "ninguno de los dos falló de una forma que el llamante no pueda narrar",
           str({k: (v[0], v[1], v[2], type(v[3]).__name__) for k, v in res.items()}))
        if rechazados:
            ex = res[rechazados[0]][3]
            cz = C.causa_de(ex) if isinstance(ex, C.SinTurnoLocal) else CM._causa_cola(ex)
            ok(cz and cz["causa"] in E.CAUSAS,
               "EL QUE ESPERA LO SABE: causa tipada del vocabulario cerrado",
               str(cz and cz["causa"]))
            ok(cz and cz["evidencia"]["origen"] == "aleph",
               "diciendo quién frenó", str(cz and cz["evidencia"]))
        print(f"     [evidencia] tiempos: "
              f"{ {k: v[2] for k, v in res.items()} } · pico de la cola: {C.COLA.estado()['pico']}")
        ok(C.COLA.estado()["activos"] == 0, "y no quedó ningún turno colgado",
           str(C.COLA.estado()))

        seccion("6c · con la cola APAGADA, el runtime encola y contesta — §3.1 reproducida")
        # Esto es lo que la auditoría 4 §3.1 midió (3 simultáneos → 3× HTTP 200, 7,9→15→23 s)
        # y lo que justifica TODA la fase: el servidor NUNCA devuelve `None` ni rechaza; la
        # concurrencia se vuelve LATENCIA. Con la perilla en 0 el comportamiento es ése,
        # byte por byte, y se comprueba acá contra el runtime de esta máquina.
        os.environ["PUPPET_OLLAMA_COLA"] = "0"
        C.COLA.reiniciar()
        res2: dict = {}
        try:
            g1 = threading.Thread(target=_tirar2, args=("a", res2))
            g2 = threading.Thread(target=_tirar2, args=("b", res2))
            g1.start()
            time.sleep(0.15)
            g2.start()
            g1.join(timeout=300); g2.join(timeout=300)
        finally:
            os.environ["PUPPET_OLLAMA_COLA"] = "1"
        vivos = {k: v for k, v in res2.items() if v}
        ok(len(vivos) == 2 and all(v[0] == "ok" for v in vivos.values()),
           "con la cola apagada los DOS pedidos vuelven con 200 — el runtime encola, no "
           "rechaza (§3.1 reproducida en esta máquina)",
           str({k: (v[0], v[2]) for k, v in vivos.items()}))
        ok(all(v[1] for v in vivos.values()),
           "y los dos traen respuesta usable: cero `None`, cero rechazo del servidor")
        if len(vivos) == 2:
            ts = sorted(v[2] for v in vivos.values())
            ok(ts[1] >= ts[0],
               f"la latencia se ACUMULA ({ts[0]}s → {ts[1]}s): la concurrencia local es "
               f"espera, y por eso la cola la hace visible en vez de dejarla muda",
               str(ts))
        ok(C.COLA.estado()["rechazos"] == 0,
           "y con la perilla apagada la cola no rechazó a nadie", str(C.COLA.estado()))

        seccion("6b · el runtime VIVO nunca se narra como ausente")
        c = CM._causa_ollama(TimeoutError("timed out"), consultar_vivo=True)
        ok(c is not None and c["causa"] != CM.SIN_RUNTIME,
           f"un timeout con el Ollama de esta máquina corriendo → {c and c['causa']}, "
           f"NO sin_runtime", str(c and c["causa"]))
        ok(c and c["evidencia"].get("runtime_vivo") is True,
           "y la liveness quedó CONSULTADA en la evidencia, no supuesta",
           str(c and c["evidencia"]))
finally:
    os.environ.pop("PUPPET_OLLAMA_COLA", None)
    C.COLA.reiniciar()

# ══ 7 · LAS OCHO VARAS PREVIAS SIGUEN VERDES ═══════════════════════════════════════
seccion("7 · las ocho varas previas de Gate 2 siguen verdes")
_ASM = _RAIZ / "platform" / "assembler"
_CB = _ASM / "cli_brain"
for nombre, ruta in (("verify_traductor", _ASM / "verify_traductor.py"),
                     ("verify_cli_streaming", _CB / "verify_cli_streaming.py"),
                     ("verify_cli_slots", _CB / "verify_cli_slots.py"),
                     ("verify_cli_usage", _CB / "verify_cli_usage.py"),
                     ("verify_adaptador_litellm", _ASM / "verify_adaptador_litellm.py"),
                     ("verify_cli_stopturn", _CB / "verify_cli_stopturn.py"),
                     ("verify_tres_cables", _CB / "verify_tres_cables.py"),
                     ("verify_cli_sesiones", _CB / "verify_cli_sesiones.py")):
    env = dict(os.environ)
    env.pop("PUPPET_OLLAMA_COLA", None)
    if os.environ.get("SIN_CLI"):
        env["SIN_CLI"] = "1"
    r = subprocess.run([sys.executable, str(ruta)], capture_output=True, text=True,
                       timeout=5400, env=env)
    ok(r.returncode == 0, f"{nombre}.py sale con exit 0",
       (r.stdout or r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr) else "")

# [H4a] El cierre pasa por `qa/lib/veredicto.py`: con salteos declarados la última
# línea ya NO es el string pelado `TODO VERDE`. La regla vive en un solo lugar.
sys.path.insert(0, str(_RAIZ / "qa" / "lib"))
import veredicto as _V  # noqa: E402

print(f"\n{_V.texto(_fallos, _salteados)}")
sys.exit(0 if _fallos == 0 else 1)
