#!/usr/bin/env python3
"""preflight_browser_build.py — TODAS las precondiciones del build de §6.a, de una vez.

POR QUÉ EXISTE: cinco intentos de build, cuatro perdidos por cosas previsibles — artefactos
gitignoreados que un worktree fresco nunca tiene, y un módulo que mi propio código importa y
que no estaba declarado para viajar. Cada uno se descubrió CORRIENDO el build y esperando
minutos. Todos eran verificables en segundos.

La regla que esto implementa: **si el build no puede probar lo que se quiere probar, no se
lanza.** Verde acá no garantiza que el build salga; rojo garantiza que NO vale la pena.
"""
import ast, os, subprocess, sys, shutil, re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
os.chdir(RAIZ)
fallos, avisos = [], []
def ok(c, d, extra=""):
    print(("  ✓ " if c else "  ✗ ") + d + (f"\n      {extra}" if extra and not c else ""))
    if not c: fallos.append(d)
def warn(d): print("  ~ " + d); avisos.append(d)

print("PREFLIGHT DEL BUILD §6.a\n")

# ── 1 · disco y concurrencia ───────────────────────────────────────────────────────────
libre = shutil.disk_usage("/System/Volumes/Data").free / 2**30
# EL UMBRAL SALE DE UNA MEDICIÓN, NO DE UN NÚMERO REDONDO. El build 5 arrancó con 18 GiB
# y tocó fondo en 10 durante el PKG del onefile: consume **8 GiB de pico**. 12 deja ~4 de
# margen sobre eso. El 14 que había acá era una estimación mía y rechazaba corridas sanas —
# mover la vara con el dato es distinto de moverla porque molesta.
ok(libre >= 12, f"[1] disco: {libre:.1f} GiB (medido: el build consume 8 GiB de pico)")
ps = subprocess.run(["ps", "ax", "-o", "command="], capture_output=True, text=True).stdout
otros = [l for l in ps.splitlines()
         if re.search(r"pyinstaller|cargo build|tauri build|build_app\.sh", l, re.I)
         and "preflight" not in l]
ok(not otros, f"[2] nadie más buildeando", "\n      ".join(otros[:3]))

# ── 2 · las rutas que el spec exige (aborta si falta alguna) ───────────────────────────
spec = (RAIZ / "deploy/fase4/aleph_sidecar.spec").read_text()
faltan = sorted({r for r in re.findall(r'os\.path\.join\(REPO,\s*"([^"]+)"', spec)
                 if not (RAIZ / r).exists()})
ok(not faltan, f"[3] las {len(set(re.findall(chr(39)+'x'+chr(39), 'x')) or [])+len(set(re.findall(r'os.path.join.REPO,\s*.([^\"]+).', spec)))} rutas literales del spec existen",
   "faltan: " + ", ".join(faltan))

# ── 3 · los datos sueltos declarados, y que el GUARD los conozca ───────────────────────
sys.path.insert(0, str(RAIZ / "deploy/fase4"))
from bundle_datos import DATOS_REQUERIDOS                                  # noqa: E402
sin = [r for r in DATOS_REQUERIDOS if not (RAIZ / r).is_file()]
ok(not sin, f"[4] los {len(DATOS_REQUERIDOS)} DATOS_REQUERIDOS existen en el repo", str(sin))
guard = (RAIZ / "qa/gate_bundle_aleph.py").read_text()
ok("DATOS_REQUERIDOS" in guard, "[5] el guard del bundle LEE esa misma lista")

# ── 4 · EL QUE ME MORDIÓ: todo lo que mi código importa, ¿viaja? ───────────────────────
# Se leen los imports REALES del árbol de §6.a y se comprueba que cada módulo propio esté
# o en un directorio que el spec lleva entero, o declarado suelto en DATOS_REQUERIDOS.
dirs_enteros = [m for m in re.findall(r'os\.path\.join\(REPO,\s*"([^"]+)"\),\s*"[^"]+"\)', spec)]
dirs_enteros += ["platform/browser", "third_party/browser-use/browser_use"]
def viaja(rel: str) -> bool:
    return rel in DATOS_REQUERIDOS or any(rel.startswith(d.rstrip("/") + "/") for d in dirs_enteros)

propios, huerfanos = set(), []
for py in sorted((RAIZ / "platform/browser").glob("*.py")):
    arbol = ast.parse(py.read_text())
    for n in ast.walk(arbol):
        nombres = ([a.name for a in n.names] if isinstance(n, ast.Import)
                   else [n.module] if isinstance(n, ast.ImportFrom) and n.module else [])
        for nm in nombres:
            top = nm.split(".")[0]
            # ⚠️ TRES FORMAS, y la segunda es la que faltaba: `from browser import cerebro`
            # deja nm="browser" y el símbolo en n.names — sin esto el chequeo decía «1
            # módulo» y pasaba en verde midiendo casi nada.
            cands = [f"platform/{nm.replace('.', '/')}.py", f"platform/{top}.py"]
            if isinstance(n, ast.ImportFrom):
                cands = [f"platform/{nm.replace('.', '/')}/{a.name}.py" for a in n.names] + cands
            for cand in cands:
                if (RAIZ / cand).is_file():
                    propios.add(cand)
                    if not viaja(cand):
                        huerfanos.append(f"{py.name} importa {nm} → {cand} NO viaja")
                    break
ok(not huerfanos, f"[6] los {len(propios)} módulos propios que §6.a importa viajan todos",
   "\n      ".join(huerfanos))

# ── 4.bis · EL CHEQUEO QUE FALTABA: las dependencias DE TERCEROS ───────────────────────
# El build 5 salió con todos MIS módulos adentro y el pack igual no levantaba: browser_use
# importaba y `Agent` moría en `No module named bubus`. Mi preflight verificaba que viajara
# lo MÍO y no que estuvieran las 36 dependencias del árbol importado — que es la mitad que
# de verdad hace correr el loop.
#
# No se comprueba leyendo el pyproject: se IMPORTA, con el intérprete y el PYTHONPATH que
# el pack va a usar. Un paquete a medio instalar pasa cualquier chequeo de presencia.
_RT = RAIZ / "platform/sala/research/runtime/bin/python3"
_LIB = RAIZ / "platform/sala/research/lib"
if not _RT.is_file():
    ok(False, "[6.bis] las dependencias de browser-use importan", "falta el runtime compartido")
else:
    _prueba = (
        "import sys\n"
        "faltan=[]\n"
        "for m in ('bubus','cdp_use','uuid_extensions','mcp','groq','pyotp','cloudpickle',"
        "'markdownify','reportlab','dotenv','pydantic','openai','httpx'):\n"
        "    try: __import__(m)\n"
        "    except Exception: faltan.append(m)\n"
        "from browser_use import Agent, BrowserProfile\n"
        "from browser_use.llm.openai.chat import ChatOpenAI\n"
        "print('FALTAN:'+','.join(faltan) if faltan else 'OK')\n")
    _env = dict(os.environ,
                PYTHONPATH=f"{_LIB}:{RAIZ / 'third_party/browser-use'}",
                ANONYMIZED_TELEMETRY="false", BROWSER_USE_CLOUD_SYNC="false")
    _r = subprocess.run([str(_RT), "-c", _prueba], capture_output=True, text=True, env=_env)
    _sale = (_r.stdout or "").strip().splitlines()[-1] if _r.stdout.strip() else ""
    ok(_r.returncode == 0 and _sale == "OK",
       "[6.bis] las dependencias de terceros importan Y `Agent` se construye",
       (_sale or _r.stderr.strip().splitlines()[-1] if _r.stderr.strip() else "sin salida")
       + f"\n      (se produce con: bash deploy/fase6/producir_browser.sh)")

# ── 5 · lo que el arranque.sh necesita en runtime ──────────────────────────────────────
sh = (RAIZ / "platform/browser/arranque.sh").read_text()
ok((RAIZ / "platform/sala/research/runtime/bin/python3").is_file(),
   "[7] el runtime compartido está (arranque.sh cuelga de él)")
ok(bool(list((RAIZ / "third_party/vane/.playwright").rglob("chrome-headless-shell"))),
   "[8] el chrome-headless-shell está donde arranque.sh lo busca")
ok((RAIZ / "third_party/browser-use/browser_use/agent/service.py").is_file(),
   "[9] el loop de browser-use está en el PYTHONPATH que arranque.sh arma")

# ── 6 · el cableado: sin esto el build instala algo inalcanzable ───────────────────────
main = (RAIZ / "product/backend/app/main.py").read_text()
ok("build_sala_browser_router" in main, "[10] el router está MONTADO en main.py")
router = (RAIZ / "product/backend/app/phase1/router.py").read_text()
ok('"sala_browser"' in router, "[11] la fila sala_browser está en el registro")
ok("sala_browser" in (RAIZ / "platform/artifacts/bridge.py").read_text(),
   "[12] sala_browser está en SOLO_PRODUCEN (o la vara del puente lo llama olvido)")

# ── 6.ter · EL CONTRATO ENTRE LAS PIEZAS, no sólo que los archivos viajen ──────────────
# Los cuatro defectos que costaron los builds 5 y 6 NO eran de empaquetado: todo viajaba.
# Eran de CONTRATO — el servidor leía una variable que nadie exporta, no usaba la función
# escrita para la forma del archivo, el pack no recibía las capacidades, y el router no
# acuñaba el espacio. Un preflight que sólo mira que los archivos estén los deja pasar a
# todos. Estos chequeos EJERCEN el contrato con datos reales, no lo leen.
import json as _json, tempfile as _tmp                                    # noqa: E402
sys.path.insert(0, str(RAIZ / "platform"))
try:
    from browser import cerebro as _C, servidor as _S, perfil as _P
    _reg = re.search(r'"sala_browser":\s*\{(.*?)\n    \},', router, re.S)
    _cuerpo = _reg.group(1) if _reg else ""
    _env = (re.search(r'"config_env":\s*"([^"]+)"', _cuerpo) or [None, ""])[1]
    _file = (re.search(r'"config_file":\s*"([^"]+)"', _cuerpo) or [None, ""])[1]

    # C1 · la variable que el servidor LEE es la que el registro DECLARA, y el nombre del
    #      archivo también. Se comprueba poniéndolas y viendo si encuentra el archivo.
    _d = _tmp.mkdtemp(prefix="preflight-cfg-")
    _borde = "http://127.0.0.1:9/v1/workspaces/brain/openai"
    open(os.path.join(_d, _file), "w").write(_json.dumps(
        {"provider": {"aleph": {"options": {
            "baseURL": _borde + "/", "apiKey": "sess",
            "headers": {"X-Aleph-Workspace": "sala", "X-Aleph-User": "u"}}}}}))
    _viejo = os.environ.get(_env)
    os.environ[_env] = _d
    _hallada = _S._ruta_config()
    ok(_hallada is not None and os.path.basename(str(_hallada)) == _file,
       f"[C1] el servidor lee {_env} + {_file}, que es lo que el registro declara",
       f"no encontró el archivo con {_env}={_d}")

    # C2 · y con ESE archivo, la costura produce el borde y NO pierde las cabeceras.
    if _hallada is not None:
        _kw = _C.desde_pack(_hallada, space_id="space-preflight")
        _h = _kw.get("default_headers") or {}
        ok(_kw.get("base_url") == _borde, "[C2] la costura arma el borde desde ese archivo",
           str(_kw.get("base_url")))
        ok(_h.get("X-Aleph-Space") == "space-preflight" and _h.get("X-Aleph-User"),
           "[C2b] y las cabeceras viajan (sin X-Aleph-Space, S8 queda ciego)", str(_h))
    else:
        ok(False, "[C2] la costura arma el borde desde ese archivo", "sin archivo que leer")
    if _viejo is None: os.environ.pop(_env, None)
    else: os.environ[_env] = _viejo

    # C3 · el router le manda al pack lo que el pack NO puede saber solo.
    _rt = (RAIZ / "product/backend/app/phase1/sala_browser_router.py").read_text()
    ok('"capacidades"' in _rt,
       "[C3] el router manda las capacidades (el pack no ve el selector de modelos)")
    ok('"space_id": espacio' in _rt and "space-browser-" in _rt,
       "[C3b] el router ACUÑA el espacio por turno (sin él no hay events.jsonl y S8 no ve nada)")

    # C4 · un error que sabe su causa tiene que pasarla.
    ok("HTTPError" in _rt and "e.read()" in _rt,
       "[C4] el router lee el CUERPO del HTTPError en vez de tirarlo",
       "un error que sabe su causa y no la pasa hace creer que no hay nada más que mirar")

    # C5 · las perillas siguen derivando del cerebro, no de una constante.
    ok(_P.perillas({"model_use_capabilities": ["text", "vision"]})["use_vision"] is True
       and _P.perillas({"model_use_capabilities": ["text"]})["use_vision"] is False,
       "[C5] use_vision sigue derivando del cerebro (no volvió a ser constante)")
except Exception as _e:                                                    # noqa: BLE001
    ok(False, "[C1-C5] el contrato entre las piezas se puede ejercer",
       f"{type(_e).__name__}: {_e}")

# ── 7 · sintaxis de todo lo que toqué ──────────────────────────────────────────────────
malos = []
for p in list((RAIZ / "platform/browser").glob("*.py")) + [
        RAIZ / "platform/ndjson_http.py", RAIZ / "product/backend/app/phase1/sala_browser_router.py",
        RAIZ / "product/backend/app/main.py", RAIZ / "product/backend/app/phase1/router.py",
        RAIZ / "deploy/fase4/bundle_datos.py"]:
    try: ast.parse(p.read_text())
    except SyntaxError as e: malos.append(f"{p.name}: {e}")
ok(not malos, "[13] todo lo tocado parsea", "\n      ".join(malos))
r = subprocess.run(["bash", "-n", "platform/browser/arranque.sh"], capture_output=True, text=True)
ok(r.returncode == 0, "[14] arranque.sh parsea", r.stderr[:200])

print("\n" + ("LANZAR" if not fallos else "NO LANZAR — " + " · ".join(fallos)))
sys.exit(1 if fallos else 0)
