# -*- mode: python ; coding: utf-8 -*-
# CASA 2 · Fase 4 · 4.4.0 — el backend frozen como SIDECAR de Tauri (uvicorn app.main).
#
# Espeja aleph_freeze_probe.spec (mismos pathex/datas/hiddenimports — los módulos PLANOS
# viajan + belts/catalog/design como datas) PERO el entrypoint es sidecar_serve.py (un
# servidor uvicorn persistente) y agrega el cierre de uvicorn. Esto SÍ está pensado para
# andar: es el artefacto real que Tauri lanza, no una sonda.
import os
import sys
import json

from PyInstaller.utils.hooks import collect_submodules, collect_data_files, copy_metadata

REPO = os.path.abspath(os.path.join(SPECPATH, "..", ".."))

_PATHS = ["product/backend", "platform", "platform/db", "platform/flywheel",
          "platform/gates", "platform/assembler", "platform/connectors", "platform/sanitizer",
          # `platform/inspection` está acá SÓLO para que Analysis pueda RESOLVER los módulos
          # planos que el cliente carga por ruta. Estar en pathex no hace viajar nada: lo que
          # viaja lo deciden `datas` y `hidden`, y el moat sigue en `_EXCLUDES` para
          # public/dev. Sin esta entrada, un `import repair_clasificar` es irresoluble en
          # análisis y el módulo se pierde CALLADO — el caso índice de FIX-P1B.
          "platform/inspection",
          # [TANDA 2 · obra B] `platform/connectors/smithery` — y NO es una entrada de
          # más: es la que faltaba. `_TARGET_MODULES` declara `"connections"` porque
          # `arranque.py:72` lo carga por ruta
          # (`platform/connectors/smithery/connections.py`), pero el directorio es un
          # SUBdirectorio de `platform/connectors`, que sí estaba: el nombre plano
          # `connections` no resolvía y Analysis lo cantaba en cada build —
          # `ERROR: Hidden import 'connections' not found`— desde `5761a165`.
          #
          # MEDIDO antes de tocar nada: de los 19 nombres de `_TARGET_MODULES`, éste es el
          # ÚNICO irresoluble contra el pathex real. Y hoy no rompía nada porque
          # `connections.py` sólo importa stdlib (su única dependencia de la casa,
          # `credential_broker`, es perezosa y ya viaja), así que la cascada que el
          # hiddenimport existe para arrastrar estaba vacía. O sea: un warning permanente
          # y sin consecuencia — que es exactamente cómo se aprende a ignorar los
          # warnings. Se arregla la causa, no se silencia el síntoma: el día que alguien
          # le agregue un `import requests` a ese archivo, ahora sí viaja.
          "platform/connectors/smithery"]
pathex = [os.path.join(REPO, p) for p in _PATHS]
for _p in pathex:
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.environ.setdefault("ALEPH_ROLE", "client")

# Los targets planos cargados por ruta (aleph_paths.load_module_by_path) viajan como datos
# y son visibles a Analysis (dep-closure vía hiddenimports).
_TARGET_DIRS = ["platform/gates", "platform/connectors", "platform/assembler",
                "platform/db", "platform/flywheel", "platform/sanitizer",
                # [Gate 4 · Fase 2] el contrato de artefactos (vocabulario + provenance):
                # import estático desde app.phase1 → Analysis lo resuelve vía pathex, y
                # viaja además como datas (cinturón y tiradores — lección FIX-P1B).
                "platform/artifacts",
                # [Gate 4 · Fase 3] `workspaces` — el censo de fuentes de los stacks
                # heredados (ley 2.ter) y lo que la casa sabe de ellos. Import estático
                # desde el router; viaja también como datas por la misma lección
                # (FIX-P1B: cinturón y tiradores).
                "platform/workspaces"]
# Datos de la vitrina/catálogo + el FRONTEND Capa 0 (serving=C) — los roots son frozen-aware
# (resource_root() → _MEIPASS), así que el discovery los encuentra congelados.
#
# [Gate 4 · F3-ciencia] EL FRONTEND CONSTRUIDO DEL WORKSPACE DE CIENCIA.
#
# Acá viaja el `dist` de un stack heredado, y ahora sí viaja uno: el de OpenScience. Que
# ese directorio exista adentro del congelado es lo que hace `installed: true` en
# `GET /v1/workspaces` y, por lo tanto, lo que hace que la sección Workspaces exista en el
# menú (`_WORKSPACE_STACKS` en el router).
#
# **Su backend NO viaja acá**, y no es un olvido: es un proceso aparte, con su propio
# runtime, y levantarlo es el ciclo de vida del pack (ley 8 escalón 2 + obra 4.1). Lo que
# el spec empaqueta es la prueba de que el workspace ESTÁ; que además CORRA es otro hecho,
# y el registro lo reporta por separado a propósito.
#
# El `dist` se produce con `vite build` en `third_party/openscience/frontend/workspace` —
# el mismo build que el `script/build.ts` del propio stack embebe en su binario. No está en
# git (el `.gitignore` del proyecto de origen ignora `dist`), así que el build de la `.app`
# tiene que generarlo antes de empaquetar.
#
# [Gate 4 · Fase 4 · O6c] EL `dist` SALIÓ DE ACÁ. Desde que el binario del pack viaja (ver
# `_PACK_CIENCIA` más abajo), su UI va adentro de ese binario — llevar las dos era la misma
# interfaz dos veces, 29,1 MiB. `installed` ya acepta binario o dist, así que Ciencia sigue
# apareciendo. El `dist` se sigue construyendo (`vite build`) porque el binario lo embebe.
_DATA_DIRS = ["catalog", "product/belts", "product/app/design", "docs/guia"]
datas = [(os.path.join(REPO, d), d) for d in _TARGET_DIRS + _DATA_DIRS]
# Fail-closed Python execution needs the pinned, signed no-network VM guest.
# Keep these as opaque bytes; `guest_execution` verifies SHA-256 and signature
# after onefile extraction before launching anything model-supplied.
_GUEST_RUNTIME = os.environ.get("ALEPH_GUEST_RUNTIME", os.path.join(REPO, "deploy/guest/runtime"))
_GUEST_MANIFEST = os.path.join(_GUEST_RUNTIME, "guest-manifest.json")
if not os.path.isfile(_GUEST_MANIFEST):
    raise SystemExit("spec: missing generated isolated guest manifest")
for _guest_asset in ("aleph-guest-runner", "Image.arm64", "rootfs.arm64.cpio.gz"):
    _source = os.path.join(_GUEST_RUNTIME, _guest_asset)
    if not os.path.isfile(_source):
        raise SystemExit(f"spec: missing isolated guest asset: {_guest_asset}")
    datas.append((_source, "deploy/guest/runtime"))
datas.append((_GUEST_MANIFEST, "deploy/guest/runtime"))
# Preserve public third-party notices explicitly, independently of compiled vendor code.
with open(os.path.join(REPO, "docs/THIRD-PARTY-MATRIX.json"), encoding="utf-8") as _fh:
    _notices = json.load(_fh)["notice_files"]
for _rel in _notices:
    _notice = os.path.join(REPO, _rel)
    if os.path.isabs(_rel) or ".." in _rel.split("/") or not os.path.isfile(_notice):
        raise SystemExit(f"spec: invalid/missing public third-party notice: {_rel}")
    datas.append((_notice, os.path.join("THIRD-PARTY-NOTICES", os.path.dirname(_rel))))
datas.append((os.path.join(REPO, "docs/THIRD-PARTY-MATRIX.json"), "THIRD-PARTY-NOTICES"))

# ── [Gate 4 · Fase 6 · Legal · O1] EL PACK ENTERO, MÁS SU RUNTIME ──────────
#
# doc.haus se ejecuta como tres procesos Bun (motor, ingest y web). No puede depender del
# Bun del PATH de la Mac receptora: el árbol materializado y el ejecutable Bun viajan dentro
# del mismo sidecar que `pack.py` entrega a `dueno.py`. `start.sh` se agrega como BINARY —no
# DATA— porque el pack debe poder ejecutarlo tras la extracción onefile.
_PACK_LEGAL = os.path.join(REPO, "third_party", "dochaus")
_PACK_LEGAL_LAUNCHER = os.path.join(_PACK_LEGAL, "start.sh")
_PACK_LEGAL_NODE_MODULES = os.path.join(_PACK_LEGAL, "node_modules")
_PACK_LEGAL_BUN = os.environ.get("ALEPH_DOCHAUS_BUN", "")
_PACK_LEGAL_EXCLUSIONS = os.environ.get("ALEPH_DOCHAUS_REDISTRIBUTION_EXCLUSIONS", "")
if not os.path.isfile(_PACK_LEGAL_LAUNCHER):
    raise SystemExit("spec: falta el launcher del pack Legal: third_party/dochaus/start.sh")
if not os.path.isdir(_PACK_LEGAL_NODE_MODULES):
    raise SystemExit("spec: Legal no tiene node_modules materializado; build_app.sh debe correr bun install --frozen-lockfile")
if not _PACK_LEGAL_BUN or not os.path.isfile(_PACK_LEGAL_BUN) or not os.access(_PACK_LEGAL_BUN, os.X_OK):
    raise SystemExit("spec: falta ALEPH_DOCHAUS_BUN ejecutable para embebir el runtime Legal")
_legal_exclusion_prefixes = []
if _PACK_LEGAL_EXCLUSIONS:
    if not os.path.isfile(_PACK_LEGAL_EXCLUSIONS):
        raise SystemExit(f"spec: manifiesto Legal de exclusión ausente: {_PACK_LEGAL_EXCLUSIONS}")
    with open(_PACK_LEGAL_EXCLUSIONS, encoding="utf-8") as _exclusions_file:
        for _line in _exclusions_file:
            _entry = _line.strip().strip("/")
            if not _entry or _entry.startswith("#"):
                continue
            if _entry.startswith("../") or "/../" in _entry:
                raise SystemExit(f"spec: ruta inválida en manifiesto Legal: {_entry!r}")
            _legal_exclusion_prefixes.append(_entry)
# `Analysis(datas=…)` acepta pares (fuente, directorio destino), mientras que `Tree` ya
# materializa triples de TOC y sólo sirve en `COLLECT`.
#
# QUÉ `node_modules` VIAJA, Y POR QUÉ SON DOS Y NO UNO
# ----------------------------------------------------
# La versión anterior de este bloque daba por sentado que el árbol de runtime tiene UN
# solo `node_modules` (el raíz, cerrado por `--filter ./packages/opencode`) y que todos
# los demás son tooling de compilación. La primera mitad es cierta; la segunda es falsa,
# y costó los dos únicos muertos de la vara de fase de Legal:
#
#   · LA RAÍZ — el cierre del motor. Viaja HOISTED a propósito: el linker `isolated` de
#     Bun deja un store en `node_modules/.bun/<pkg>@<ver>/` y resuelve todo lo demás con
#     symlinks relativos (2.366 medidos en este árbol). PyInstaller no preserva symlinks
#     de directorio y su `os.walk` tampoco los sigue, así que viajaban los BYTES de cada
#     paquete y no el MAPA que los encuentra. Ver el bloque [0/3] de `build_app.sh`.
#
#   · `services/ingest` — que **no es workspace del monorepo** (los `workspaces` del
#     `package.json` raíz son `packages/*`, `packages/console/*`, `packages/stats/*`,
#     `packages/sdk/js` y `packages/slack`), así que Bun le da un `node_modules` propio y
#     autónomo que ningún `--filter` del raíz alcanza. Ahí viven `docx`, `mammoth`,
#     `docxodus` y el runtime ONNX del ingest: 4 de sus 6 dependencias no existen en el
#     cierre del motor. Sin esto, el SEGUNDO de los tres procesos muere al arrancar.
#     Medido preguntándole al binario instalado, no al TOC: no viajaba, y no se había
#     notado nunca porque el motor moría primero y el launcher se lleva a los tres.
#
# Los de `apps/web` y los de cada workspace de `packages/` sí son tooling de compilación
# (la web viaja horneada como `dist`) y no participan de los tres procesos: ésos se podan,
# y no se los puede dejar entrar por accidente en el onefile.
#   · `dochaus` — LA CAPA DE OFICIO, y es el tercero. Tampoco es workspace del monorepo:
#     tiene su propio `package.json` y su `bun.lock`, y de ahí salen `fflate`, `docxodus`,
#     `mammoth`, `unpdf` y `@huggingface/transformers`, que las 37 tools legales importan
#     por `dochaus/lib/*.ts`. Hasta esta obra el dir ni siquiera se alcanzaba —la capa
#     entera estaba fuera de la lista de config dirs del motor— así que la falta no se veía.
#     Con la capa enchufada se ve entera y de una: `Cannot find package 'fflate'` mata el
#     registro de tools COMPLETO, y `/experimental/tool/ids` devuelve 500 en vez de 52.
#     Medido contra la .app instalada `59b9f71f…`: 19 agentes cargados y CERO tools.
_LEGAL_NM_DUENOS = ("", "services/ingest", "dochaus")

# ── CONFIG DE CONTRIBUTOR, QUE NO ES OFICIO ─────────────────────────────────────────────
# Esto NO es la frontera de redistribución: aquélla es de PROCEDENCIA (quién escribió el
# contenido jurídico y bajo qué licencia) y quedó auditada y abierta. Esto es de ALCANCE: el
# `.opencode/` de la raíz es el config con el que se DESARROLLA doc.haus, no con el que se
# ejerce el oficio legal. Tres archivos: dos agentes de CI (`duplicate-pr`, `triage`) y una
# skill para trabajar el código de Effect.
#
# NO HACEN FALTA PARA NADA, verificado antes de cortar: su único llamador es
# `script/duplicate-pr.ts`, un script de CI del repo de origen, y los dos agentes están
# pineados a `model: opencode/…` — el proveedor que la config de Legal ya apaga, así que ni
# siquiera podrían correr.
#
# Y ADEMÁS ENSUCIABAN LA MEDICIÓN, que es lo que los delató: son la razón de que una sonda
# al motor SIN `x-opencode-directory` devolviera 5 agentes y 16 tools en vez de 3 y 14 —
# `config/paths.ts:26-31` sube desde el cwd del motor y encuentra este `.opencode`. Dos
# sesiones midieron contra eso creyendo que medían la capa de oficio.
#
# Se poda el DIRECTORIO, no los archivos: `.opencode/` completo. El `tool/` de adentro
# (`github-pr-search`, `github-triage`) es de la misma clase y por el mismo motivo.
_LEGAL_CONTRIBUTOR = (".opencode",)

for _dir, _subdirs, _files in os.walk(_PACK_LEGAL):
    _rel_dir = os.path.relpath(_dir, _PACK_LEGAL)
    _rel_posix = "" if _rel_dir == "." else _rel_dir.replace(os.sep, "/")
    if any(_rel_posix == _p or _rel_posix.startswith(_p + "/") for _p in _LEGAL_CONTRIBUTOR):
        _subdirs[:] = []
        continue
    if any(_rel_posix == _prefix or _rel_posix.startswith(_prefix + "/") for _prefix in _legal_exclusion_prefixes):
        _subdirs[:] = []
        continue
    # Ya estamos ADENTRO de un `node_modules` que viaja: no se poda nada, porque los
    # anidados de un paquete son parte de su propio cierre.
    _adentro_de_nm = any(
        _rel_posix == ((_d + "/node_modules") if _d else "node_modules")
        or _rel_posix.startswith((_d + "/node_modules/") if _d else "node_modules/")
        for _d in _LEGAL_NM_DUENOS
    )
    if _rel_posix not in _LEGAL_NM_DUENOS and not _adentro_de_nm:
        _subdirs[:] = [d for d in _subdirs if d != "node_modules"]
    _dest_dir = os.path.normpath(os.path.join("third_party/dochaus", _rel_dir))
    for _name in _files:
        _source = os.path.join(_dir, _name)
        if os.path.normpath(_source) == os.path.normpath(_PACK_LEGAL_LAUNCHER):
            continue
        if os.path.isfile(_source):
            datas.append((_source, _dest_dir))
if _legal_exclusion_prefixes:
    print("spec: pack Legal → exclusiones de redistribución:", ", ".join(_legal_exclusion_prefixes))

# ── [Gate 4 · Fase 6 · Diseño · O1] EL RUNTIME ELECTRON VIAJA COMO ZIP OPACO ─────────────
#
# Diseño no corre desde su árbol como Legal: su motor es un `.app` Electron compilado
# (electron-vite + electron-builder), y ADENTRO de ese `.app` ya viajan su main headless y su
# renderer — `files: out/**` de `electron-builder.yml`, y `main/index.ts:292` resuelve el
# renderer con `join(__dirname, '../renderer')`, o sea desde el bundle y jamás desde este árbol.
#
# POR QUÉ ZIP Y NO EL `.app`: PyInstaller RE-FIRMA los Mach-O que encuentra en un directorio
# de datos, y un `.app` Electron anidado deja de ser un dato — falla al re-firmar sus
# frameworks (`Mantle.framework`, medido en el primer intento de esta fase). Como ZIP es un
# dato opaco: viaja intacto y `bin/aleph-codesign` lo expande con `ditto` en el dato privado
# del dueño, indexado por su sha256.
#
# Y POR ESO EL ÁRBOL VIAJA PODADO. Medido: 969 MiB enteros, de los cuales 906 son
# `node_modules` —con el propio Electron adentro, que es la bomba de firma— y 15 el `out/`
# que ya viaja dentro del `.app`. Los tres son de tiempo de compilación. Queda la fuente
# (~48 MiB, 879 archivos) más el ZIP del runtime.
#
# El launcher va como BINARY, no como DATA, por la misma razón que `start.sh` de Legal: tras
# la extracción onefile el pack tiene que poder EJECUTARLO (`pack.py:168` verifica X_OK), y un
# data no conserva el bit.
_PACK_DISENO = os.path.join(REPO, "third_party", "codesign")
_PACK_DISENO_LAUNCHER = os.path.join(_PACK_DISENO, "bin", "aleph-codesign")
_PACK_DISENO_ZIP = os.path.join(
    _PACK_DISENO, "apps", "desktop", "release", "aleph-diseno-mac-arm64.zip")
if not os.path.isfile(_PACK_DISENO_LAUNCHER):
    raise SystemExit("spec: falta el launcher del pack Diseño: third_party/codesign/bin/aleph-codesign")
if not os.path.isfile(_PACK_DISENO_ZIP):
    raise SystemExit(
        "spec: Diseño no tiene runtime materializado; build_app.sh debe hornear "
        "third_party/codesign/apps/desktop/release/aleph-diseno-mac-arm64.zip")
_DISENO_PODA = ("apps/desktop/out", "apps/desktop/release/mac-arm64")

for _dir, _subdirs, _files in os.walk(_PACK_DISENO):
    _rel_dir = os.path.relpath(_dir, _PACK_DISENO)
    _rel_posix = "" if _rel_dir == "." else _rel_dir.replace(os.sep, "/")
    if any(_rel_posix == _p or _rel_posix.startswith(_p + "/") for _p in _DISENO_PODA):
        _subdirs[:] = []
        continue
    _subdirs[:] = [d for d in _subdirs if d != "node_modules"]
    _dest_dir = os.path.normpath(os.path.join("third_party/codesign", _rel_dir))
    for _name in _files:
        _source = os.path.join(_dir, _name)
        if os.path.normpath(_source) == os.path.normpath(_PACK_DISENO_LAUNCHER):
            continue
        if os.path.isfile(_source):
            datas.append((_source, _dest_dir))

# ── [OBRA 6a] DATOS SUELTOS, DECLARADOS POR NOMBRE ──────────────────────────────────────
# Los de arriba son DIRECTORIOS. Éstos son archivos sueltos de `platform/inspection`, que
# NO es un `_DATA_DIR`: viaja entero sólo en founder (ver `_FORGE_TRAVELS`, más abajo). En
# `public` —el artefacto que se distribuye— se estaban perdiendo MUDOS, y el build founder
# los tenía, así que nadie lo notó hasta medir la `.app` instalada.
#
# La lista vive en `bundle_datos.py` porque `qa/gate_bundle_aleph.py` LEE LA MISMA y exige
# que cada entrada exista dentro del binario compilado. Sumar un archivo acá es sumarlo al
# guard: por construcción, el próximo no se puede perder igual. El porqué de cada uno, con
# lo que costó medido en la instalada, está en ese archivo.
sys.path.insert(0, SPECPATH)
from bundle_datos import DATOS_DE_PAQUETE, DATOS_REQUERIDOS  # noqa: E402

for _rel in DATOS_REQUERIDOS:
    _src = os.path.join(REPO, _rel)
    if not os.path.isfile(_src):
        raise SystemExit(f"spec: falta en el repo un dato declarado como requerido: {_rel}")
    datas.append((_src, os.path.dirname(_rel)))
print(f"spec: {len(DATOS_REQUERIDOS)} datos sueltos declarados → viajan en TODOS los builds")

# ── DATOS DE PAQUETES INSTALADOS ────────────────────────────────────────────────────────
# `Analysis` mete los `.py` de un paquete y NO sus datos. litellm abre su mapa de precios con
# `importlib.resources.files("litellm")`, así que el import resolvía perfecto y el archivo no
# estaba: medido en la instalada, TODO run con herramientas por una vía de API que no fuera
# Groq moría con `FileNotFoundError` antes del primer token. El porqué completo está en
# `bundle_datos.py`; acá sólo se lee la lista y se mete.
from bundle_datos import rutas_de_paquete  # noqa: E402

_de_paquete = rutas_de_paquete()
for _paq, _rel, _abs in _de_paquete:
    # El destino conserva la estructura DENTRO del paquete: `litellm_core_utils/tokenizers/x`
    # tiene que aterrizar en `litellm/litellm_core_utils/tokenizers/`, que es donde
    # `resources.files("litellm").joinpath(...)` lo va a buscar. Aplanarlo lo esconde.
    datas.append((_abs, os.path.join(_paq, os.path.dirname(_rel))))
print(f"spec: {len(DATOS_DE_PAQUETE)} entradas de paquete declaradas → "
      f"{len(_de_paquete)} archivos ({', '.join(f'{p}/{a}' for p, a in DATOS_DE_PAQUETE)})")

# LA REGLA, no la lista de excepciones: TODO módulo que alguien cargue con
# `aleph_paths.load_module_by_path` va acá, siempre. `Analysis` descubre por import
# estático y una carga por ruta le es invisible, así que sin la entrada el bundle SE ARMA
# BIEN y el fallo aparece recién en runtime, en la máquina del usuario. `_TARGET_DIRS` ya
# hace viajar el `.py` como dato — esto es lo otro que falta: su cascada de dependencias.
# Ya pasó tres veces (FIX-P1B con `assembler`, después `multiagente`, después
# `restaurador`); las tres se vieron como «Error del proveedor» sin una línea de log.
# El contrapunto está escrito en `aleph_paths.load_module_by_path` (regla 2).
_TARGET_MODULES = [
    "connect_engine", "oauth_flow", "oauth_loopback", "connections", "approval_gate", "recipe_enforcer",
    "recipe_assembler", "assembler", "session", "vault", "db", "events_replay",
    "sanitizer", "tier_gate", "scrubber", "runtime_integration",
    "build_id",
    # MULTIAGENTE F1: lo cargan el router (`import multiagente` tras insertar el dir del
    # assembler) y el validador de recetas. Sin esta entrada Analysis no lo ve —
    # `recipe_assembler` no lo importa — y se perdería CALLADO, que es el caso índice de
    # FIX-P1B (`assembler.py` fuera del .app → «Error del proveedor»).
    "multiagente",
    # RESTAURACIÓN (CONTRACT-CONEXION-v1 §1): `recipe_assembler` lo carga con
    # `load_module_by_path`, así que Analysis NO lo ve por import. Sin esta entrada se
    # pierde CALLADO en el bundle y `_load_restaurador()` revienta al importar
    # recipe_assembler → ningún run arranca. Mismo caso índice que FIX-P1B.
    "restaurador",
    # LA CLASIFICACIÓN TEMPORAL/PERMANENTE (`GET /v1/conexiones/fuentes`). El adaptador de
    # la superficie le pregunta a repair si un rojo se re-mide solo o manda a alguien a
    # arreglar algo, y lo carga por ruta — o sea, invisible a Analysis. Sin esta entrada el
    # .app se arma bien, la superficie no recibe `clasificacion`, la regla de lo temporal no
    # aplica NUNCA y **los rojos falsos vuelven en la app instalada** mientras el censo en
    # desarrollo sigue verde. Es el mismo modo de fallo que ya costó tres veces.
    # Es seguro para public: `repair_clasificar` no importa nada del proyecto (sólo stdlib),
    # así que no arrastra el moat.
    "repair_clasificar",
    # [Gate 4 · F5] LAS DOS PIEZAS DE LA FASE 5, con cinturón Y tiradores.
    #
    # `recipe_assembler` y `assembler` las importan a secas y `platform/assembler` está en
    # `pathex`, así que en teoría Analysis las resuelve sola. Van nombradas igual porque
    # este modo de fallo YA COSTÓ TRES VECES (multiagente, restaurador, repair_clasificar)
    # y siempre de la misma forma: el .app se arma SIN error, el árbol en desarrollo sigue
    # verde, y el defecto aparece recién en la máquina del usuario.
    #
    # En `recipe_assembler` las dos son imports DUROS: si faltan, el módulo no carga y
    # ningún run arranca — feo, pero visible. El que da miedo es el otro: en
    # `assembler.py` `turnos_obra` entra por un import BLANDO (tiene que poder correr
    # suelto), así que si viajara a medias caería a su clase muda y **el botón de parar
    # volvería a ser decorativo, sin un solo error en ningún log**.
    "tool_budget", "turnos_obra",
]

try:
    hidden = collect_submodules("app") + ["role", "aleph_paths"] + _TARGET_MODULES
except Exception as e:  # noqa: BLE001
    print("spec: collect_submodules('app') falló:", e)
    hidden = ["role", "aleph_paths"] + _TARGET_MODULES
# Diagnóstico de conectores: se nombran además de collect_submodules para que una futura
# poda del paquete `app` no deje al frozen sin el productor único ni sin su cascada.
hidden += [
    "app.phase1.diagnostico_conectores",
    "app.phase1.remedios_conectores",
]
# EL PUENTE BYO, ADENTRO DEL SIDECAR. `byo_mcp_server` es un SCRIPT: nadie lo importa, así
# que `Analysis` no lo ve y no entraría al PYZ — y sin él en el PYZ, `--byo-mcp` no puede
# servir nada. `puente_sidecar` es quien traduce la receta al lanzar; lo importan el
# ejecutor viejo y el del SDK, pero se nombra igual porque perderlo dejaría a TODA pieza
# HTTP del usuario lanzándose con un python3 que no puede leer este bundle (Obra 5/6a).
hidden += [
    "puente_sidecar",
    "inspection.byo_mcp_server",
]
# uvicorn carga loops/protocols/lifespan por import dinámico → cerrarlos a mano.
hidden += collect_submodules("uvicorn")
# Slice C · :8926 ahora vive dentro del sidecar. `router.py` y el entrypoint lo cargan
# dinámicamente desde platform/assembler; cerramos el paquete entero para que detección,
# providers y lifecycle existan también bajo PyInstaller onefile.
hidden += collect_submodules("cli_brain")
# E2 · perfil aleph-zero (markdown). collect_submodules no lleva .md.
datas.append((os.path.join(REPO, "platform/assembler/cli_brain/agents"),
              "cli_brain/agents"))
# [TLS] El sidecar congelado no trae store de CAs del SO → toda HTTPS Python-side (registro
# MCP en /v1/catalog/search vía urllib, puente premium cliente→control) muere. Se empaqueta
# certifi (cacert.pem → _MEIPASS/certifi/) y el boot apunta SSL_CERT_FILE/REQUESTS_CA_BUNDLE
# ahí (sidecar_serve.ensure_ca_bundle). Sin esto: "unreachable" contra todo HTTPS.
datas += collect_data_files("certifi")
hidden += ["certifi"]

# [litellm] EL PAQUETE DE TOKENIZERS TIENE QUE SER **IMPORTABLE**, no sólo estar en disco.
# Sus archivos viajan por `bundle_datos.DATOS_DE_PAQUETE` (ver el porqué ahí), pero
# `litellm/utils.py` los pide con `resources.files("litellm.litellm_core_utils.tokenizers")`
# —POR NOMBRE DE MÓDULO, string—, y su `__init__.py` está VACÍO: nadie lo importa, así que
# `Analysis` no lo mete en el PYZ y `resources.files` levanta `No module named …`.
# MEDIDO: con los datos ya adentro y sin esta línea, el binario seguía diciendo
# «[litellm] NO se selló (litellm no está instalado: No module named
# 'litellm.litellm_core_utils.tokenizers')». Los datos sin el módulo no alcanzan.
hidden += ["litellm.litellm_core_utils.tokenizers"]

# [tiktoken] EL REGISTRO DE ENCODINGS SE DESCUBRE ESCANEANDO, y bajo PyInstaller no hay nada
# que escanear. `tiktoken/registry.py` hace `pkgutil.iter_modules(tiktoken_ext.__path__)`
# sobre un NAMESPACE PACKAGE: congelado, ese `__path__` no lista nada y `cl100k_base` —el
# encoding que litellm pide para contar tokens— no existe.
# MEDIDO, tercera capa de la misma pérdida: con los datos Y el módulo de tokenizers adentro,
# el binario todavía decía «[litellm] NO se selló (Unknown encoding cl100k_base)».
# Nombrar el submódulo es lo único que lo mete en el PYZ; el escaneo lo encuentra desde ahí.
hidden += ["tiktoken_ext", "tiktoken_ext.openai_public"]

# [4.4.4] PODA — excludes de módulos que NO viajan. EDITAR ACÁ (un solo lugar; vale para
# onedir y onefile). Verificar tras CADA exclude que el .app arranca y las 5/5 obras rinden;
# si un exclude rompe algo, revertirlo. Verificado tras CADA batch: boot + 5/5 obras.
_EXCLUDES = [
    # magika (detección de tipo de archivo de Google) + su runtime ONNX (63M): NO se usa en el
    # código (0 imports) — peso muerto transitivo. El mayor win de la poda.
    "onnxruntime", "magika",
    # cruft de build/dev, jamás en runtime de un server. (markitdown+pandas+pdfminer+PIL NO se
    # podan: son la ingesta rica de docs — feature real con fail honesto, no peso muerto.)
    "setuptools", "pip", "pydoc", "lib2to3", "test",
]

# [4.4.3] LOS 3 BUILDS por ALEPH_BUILD. El MOAT (Motor B = zones.FORGE) viaja SÓLO en founder.
#   public/dev → ships() (RESOLVE|SHARED): el forge se EXCLUYE del artefacto (seguridad por AUSENCIA).
#   founder    → ships()+stays(): el forge VIAJA y forja LOCAL (main.py abre el gate con is_founder()).
# La lista de módulos FORGE se DERIVA de zones.FORGE (no a mano), igual que preparar_cliente.sh.
_ALEPH_BUILD = (os.environ.get("ALEPH_BUILD") or "public").strip().lower()
if _ALEPH_BUILD not in ("public", "founder", "dev"):
    raise SystemExit(f"spec: ALEPH_BUILD inválido: {_ALEPH_BUILD!r} (public|founder|dev)")
_FORGE_TRAVELS = (_ALEPH_BUILD == "founder")

# BAKE la identidad de build EN el bundle (self-identifying; baked GANA sobre la env). Igual que
# preparar_cliente.sh: build_id.is_founder() lee `aleph_build_id.ALEPH_BUILD`. Sin esto, el sidecar
# founder no sabría que es founder (is_founder()→env/dev) y NO montaría el forge que sí lleva.
import tempfile as _tf
_bake_dir = _tf.mkdtemp(prefix=f"aleph_bake_{_ALEPH_BUILD}_")
with open(os.path.join(_bake_dir, "aleph_build_id.py"), "w") as _bf:
    _bf.write(f'# HORNEADO por aleph_sidecar.spec — NO editar.\nALEPH_BUILD = "{_ALEPH_BUILD}"\n')
pathex.insert(0, _bake_dir)
hidden.append("aleph_build_id")
_forge_mods = {"app.phase1.forge_router", "app.phase1.inspect_router"}
try:
    from inspection import zones as _zones
    for _m in _zones.FORGE:
        _mod = "inspection." + _m.replace("/", ".")
        if _mod.endswith(".__init__"):
            _mod = _mod[: -len(".__init__")]
        _forge_mods.add(_mod)
except Exception as _e:  # noqa: BLE001
    print("spec: no pude derivar zones.FORGE:", _e)

if _FORGE_TRAVELS:
    # FOUNDER: el moat viaja. inspection entera como datos (RESOLVE+SHARED+FORGE) + forge en el PYZ.
    datas += [(os.path.join(REPO, "platform/inspection"), "platform/inspection")]
    # The BYO-only supervised SDK adapter refuses an unverified MCP version.
    # importlib.metadata must therefore work inside the frozen sidecar too.
    datas += copy_metadata("mcp")
    hidden += sorted(_forge_mods)
    try:
        hidden += collect_submodules("inspection")
    except Exception:  # noqa: BLE001
        pass
    print(f"spec: ALEPH_BUILD={_ALEPH_BUILD} → FORGE VIAJA ({len(_forge_mods)} módulos núcleo)")
else:
    # PUBLIC/DEV: el moat NO viaja. Excluir el forge del bundle + sacarlo de hidden.
    _EXCLUDES += sorted(_forge_mods)
    hidden = [h for h in hidden if h not in _forge_mods]
    print(f"spec: ALEPH_BUILD={_ALEPH_BUILD} → FORGE EXCLUIDO ({len(_forge_mods)} módulos)")

# ── [Gate 4 · Fase 4 · O6c] EL BINARIO DEL PACK DE CIENCIA ──────────────────────────────
#
# Va por `binaries` y NO por `datas`, y la diferencia importa: PyInstaller no preserva el bit
# de ejecución de un `datas`, así que el pack no podría lanzarlo. Por `binaries` sale
# ejecutable, que es lo único que este archivo necesita ser.
#
# **Y SALE EL `dist`.** El binario embebe su propia UI y sus 294 skills — medido corriéndolo
# solo, sin `dist` al lado: `/` → 200 text/html, `/skill` → 174.818 b de JSON. Empaquetar los
# dos sería llevar la misma interfaz dos veces (29,1 MiB de más). El registro ya lo contempla:
# `installed` acepta *dist* **o** *binario* (`router.py::workspaces_list`), así que sacarlo no
# vuelve invisible a Ciencia.
#
#   binario  +121,7 MiB   ·   dist  −29,1 MiB   ⇒   +92,6 MiB netos, medidos.
#
# Se produce con `bun run build` en `third_party/openscience/backend/cli` y NO está en git
# (como el `dist`): el build de la `.app` tiene que generarlo antes de empaquetar. Si falta,
# el spec FALLA acá en vez de producir una `.app` que dice tener Ciencia y no puede levantarla.
_PACK_CIENCIA = os.path.join(
    REPO, "third_party/openscience/backend/cli/dist/@synsci/openscience-darwin-arm64/bin/openscience")
_binarios = []
_binarios.append((_PACK_LEGAL_LAUNCHER, "third_party/dochaus"))
_binarios.append((_PACK_LEGAL_BUN, "third_party/dochaus/runtime"))
_binarios.append((_PACK_DISENO_LAUNCHER, "third_party/codesign/bin"))
_FINANZAS_LAUNCHER = os.path.join(REPO, "platform/workspaces/launchers/finanzas-serve")
if not os.path.isfile(_FINANZAS_LAUNCHER):
    raise SystemExit("spec: falta el launcher del pack Finanzas: platform/workspaces/launchers/finanzas-serve")
_binarios.append((_FINANZAS_LAUNCHER, "platform/workspaces/launchers"))
print(f"spec: pack Legal → árbol Bun materializado + runtime {os.path.getsize(_PACK_LEGAL_BUN) / 1048576:.1f} MiB")
if os.path.isfile(_PACK_CIENCIA):
    _binarios.append((_PACK_CIENCIA, "third_party/openscience/bin"))
    print(f"spec: pack de Ciencia → {os.path.getsize(_PACK_CIENCIA) / 1048576:.1f} MiB")
else:
    raise SystemExit(
        "spec: falta el binario del pack de Ciencia. Los TRES pasos, en orden:\n"
        "      1) cd third_party/openscience && bun install\n"
        "         ⚠️ es un workspace de Bun y sus deps NO están en git: sin este paso el\n"
        "            build muere con `Cannot find module '@synsci/script'`. Costó un build\n"
        "            entero el 2026-08-16.\n"
        "      2) cd backend/cli && \\\n"
        "         MODELS_DEV_API_JSON=deploy/fase4/datos/models-dev-snapshot.json bun run build\n"
        "      3) PODAR LAS PLATAFORMAS DE MÁS, enseguida:\n"
        "         cd dist/@synsci && ls -d openscience-* | grep -v darwin-arm64 | xargs rm -rf\n"
        "         ⚠️ `bun run build` compila ONCE plataformas y este spec usa UNA: son\n"
        "            1,6 GiB de desperdicio. Y un `internal error in Code Signing\n"
        "            subsystem` más adelante es el DISFRAZ DEL DISCO LLENO, no un problema\n"
        "            de firma.\n"
        "      (sin el binario, la .app diría tener el workspace y no podría levantarlo)")

# ── [Gate 4 · Fase 6] PACK EDUCACIÓN: backend congelado + web standalone ───────────
# El tutor NO usa el Python del host. `build_app.sh` produce primero este backend
# onefile y lo entrega por env; el sidecar lo lleva como binario secundario dentro de
# su propio onefile. Next y sus assets viajan como datos y el launcher los agrupa bajo
# la lápida F4. Si falta cualquiera, se aborta ANTES de fabricar una app mentirosa.
_PACK_EDUCACION = os.environ.get("ALEPH_DEEPTUTOR_BACKEND", "")
_WEB_EDUCACION = os.path.join(REPO, "third_party", "deeptutor", "web", ".next", "standalone")
_NODE_EDUCACION = os.environ.get("ALEPH_DEEPTUTOR_NODE", "")
_LAUNCHER_EDUCACION = os.path.join(REPO, "platform", "workspaces", "launchers", "deeptutor")
if not _PACK_EDUCACION or not os.path.isfile(
        os.path.join(_PACK_EDUCACION, "deeptutor_backend")):
    raise SystemExit(
        "spec: falta el backend onedir del pack Educación: "
        f"{_PACK_EDUCACION or '(sin declarar)'}")
for _ruta, _nombre in ((_NODE_EDUCACION, "Node"),
                        (_LAUNCHER_EDUCACION, "launcher")):
    if not _ruta or not os.path.isfile(_ruta):
        raise SystemExit(f"spec: falta { _nombre } del pack Educación: {_ruta or '(sin declarar)'}")
if not os.path.isfile(os.path.join(_WEB_EDUCACION, "server.js")):
    raise SystemExit("spec: falta third_party/deeptutor/web/.next/standalone/server.js")
_binarios += [
    (_NODE_EDUCACION, "third_party/deeptutor/bin"),
    (_LAUNCHER_EDUCACION, "platform/workspaces/launchers"),
]
# El sidecar exterior ya es onefile y extrae todos sus datos al abrir Aleph. Llevar el
# backend como onedir evita una segunda extracción completa al entrar a Educación.
_OPAQUE_PACK_DIRS = [
    (_PACK_EDUCACION, "third_party/deeptutor/bin/deeptutor_backend"),
]

# ── [Gate 4 · Fase 6 · §6.a.bis] LA BÚSQUEDA WEB DE LA SALA ────────────────────────────
# Los artefactos locales de Vane se producen con `deploy/fase6/producir_busqueda.sh`.
# Si falta alguna, el spec FALLA acá en vez de producir una `.app` que dice tener búsqueda
# y no puede levantarla — el mismo criterio que Ciencia y Finanzas.
#
# SearXNG es un proveedor externo opcional. Ni su servidor, ni su configuración
# de distribución, ni sus dependencias pueden entrar al bundle propietario.
_VANE = os.path.join(REPO, "third_party", "vane")
_SALA_BUSQUEDA = os.path.join(REPO, "platform", "sala", "busqueda")
_SALA_RUNTIME = os.path.join(REPO, "platform", "sala", "research", "runtime")

_VANE_STANDALONE = os.path.join(_VANE, ".next", "standalone")
if not os.path.isfile(os.path.join(_VANE_STANDALONE, "server.js")):
    raise SystemExit(
        "spec: falta el build de Vane (.next/standalone/server.js). "
        "Se produce con: bash deploy/fase6/producir_busqueda.sh")

# LOS PESOS DEL EMBEDDING, DENTRO DEL STANDALONE. Se chequea la ruta REAL que el motor
# lee en runtime, no la del árbol de build: Next copia la librería pero **no su `.cache`**
# (traza código, no cachés), así que las dos rutas existen por separado y la que importa
# es ésta. Sin esto la primera búsqueda de una instalación nueva sale a Hugging Face.
if not os.path.isdir(os.path.join(_VANE_STANDALONE, "node_modules",
                                  "@huggingface", "transformers", ".cache")):
    raise SystemExit(
        "spec: el standalone de Vane no trae los pesos del embedding. "
        "La primera búsqueda saldría a Hugging Face. Corré producir_busqueda.sh")

# ── [Gate 4 · Fase 6 · §6.a] BROWSER USE ──────────────────────────────────────────────
# El árbol importado viaja como DATOS (es Python puro: `browser_use/` son .py, y el
# `arranque.sh` le pone su ruta en PYTHONPATH). NO se congela con PyInstaller: su loop
# importa por nombre en runtime y un análisis estático se pierde la mitad.
# El chromium NO se agrega acá: ya viaja el de Vane, y MEDIDO el 2026-08-18 habla CDP 1.3,
# que es todo lo que browser-use necesita (lo maneja con `cdp-use`, no con Playwright).
_BROWSER_USE = os.path.join(REPO, "third_party/browser-use/browser_use")
if not os.path.isdir(_BROWSER_USE):
    raise SystemExit("spec: falta third_party/browser-use (§6.a)")
datas += [(_BROWSER_USE, "third_party/browser-use/browser_use"),
          (os.path.join(REPO, "platform/browser"), "platform/browser")]
print("spec: browser use → árbol importado + la casa")

_VANE_PLAYWRIGHT = os.path.join(_VANE, ".playwright")
if not os.path.isdir(_VANE_PLAYWRIGHT):
    raise SystemExit("spec: falta chromium-headless-shell (third_party/vane/.playwright)")

if not os.path.isfile(os.path.join(_SALA_RUNTIME, "bin", "python3")):
    raise SystemExit(
        "spec: falta el runtime de Python de la Sala (platform/sala/research/runtime). "
        "Lo usan LOS DOS modos —búsqueda y research— y lo produce producir_busqueda.sh")

# Los tres van OPACOS: llevan Mach-O adentro (el `node` del standalone, el chromium de
# Playwright, los `.so` de las dependencias, el intérprete de Python) que el PyInstaller
# exterior no puede re-firmar ni relocalizar. Es el mismo tratamiento que Educación y
# Finanzas, y el motivo está escrito en su comentario.
_OPAQUE_PACK_DIRS += [
    (_VANE_STANDALONE, "third_party/vane/.next/standalone"),
    (_VANE_PLAYWRIGHT, "third_party/vane/.playwright"),
    (_SALA_RUNTIME, "platform/sala/research/runtime"),
]
# Las migraciones de Vane se siembran en el DATA_DIR del usuario.
datas.append((os.path.join(_VANE, "drizzle"), "third_party/vane/drizzle"))
print("spec: búsqueda web → standalone + chromium + runtime Python; SearXNG externo")

# ── [Gate 4 · Fase 6 · §6.f] EL MODO LARGO DE LA SALA — Deep Research ──────────────────
# Mismo criterio que su hermano: si falta una pieza el spec FALLA acá, en vez de producir
# una `.app` que dice tener investigación a fondo y muere en la primera obra.
#
# ⚠️ LOS DOS MODOS COMPARTEN EL INTÉRPRETE. `_SALA_RUNTIME` ya viajó arriba (§6.a.bis lo
# declaró primero); no se repite, se reusa. Lo de este modo son sus 279 dependencias.
_SALA_RESEARCH = os.path.join(REPO, "platform", "sala", "research")
_LDR = os.path.join(REPO, "third_party", "ldr")

# EL MOTOR. Se chequea EL ARCHIVO que `servidor.py:325` importa, no el directorio: un
# `third_party/ldr/src` que existe pero llegó vacío pasaría un `isdir` y moriría en runtime
# con `motor_no_instalado`. Es la lección de la caché de Vane —verificar la ruta que el
# motor LEE, no la que el build produce— aplicada al caso de acá.
_LDR_SRC = os.path.join(_LDR, "src")
if not os.path.isfile(os.path.join(_LDR_SRC, "local_deep_research", "api",
                                   "research_functions.py")):
    raise SystemExit(
        "spec: falta el motor de Deep Research (third_party/ldr/src/local_deep_research/"
        "api/research_functions.py). Es código en git: si no está, el árbol está roto.")

# SUS DEPENDENCIAS. 279 paquetes / 1,9 GiB al lado del launcher, que es donde
# `arranque.sh` las pone en `PYTHONPATH` (`$AQUI/lib`). NO están en git.
#
# Se chequea `langchain_openai` y no la carpeta a secas, y tiene nombre propio: es el
# ÚNICO import de `cerebro.py`, o sea el que decide si el cerebro de la casa se puede
# construir. Sin él el modo levanta, contesta `/health` en verde y falla en la primera
# obra con `cerebro_sin_sdk` — un pack sano por fuera y muerto por dentro.
_RESEARCH_LIB = os.path.join(_SALA_RESEARCH, "lib")
if not os.path.isdir(os.path.join(_RESEARCH_LIB, "langchain_openai")):
    raise SystemExit(
        "spec: faltan las dependencias del motor de Deep Research "
        "(platform/sala/research/lib/langchain_openai). "
        "Se producen con: bash deploy/fase6/producir_research.sh")

# EL LANZADOR VA POR `_binarios`, NO POR `datas`, y no es un detalle de estilo: `datas` no
# preserva el bit de ejecución, y `pack.binario_de` resuelve `meta["bin"]` contra
# `resource_root()` y lo EJECUTA. Un `arranque.sh` sin `+x` adentro del bundle es un
# workspace que dice estar instalado y no abre. Es como viajan Legal y Finanzas.
_RESEARCH_LAUNCHER = os.path.join(_SALA_RESEARCH, "arranque.sh")
if not os.path.isfile(_RESEARCH_LAUNCHER):
    raise SystemExit("spec: falta el launcher del modo largo: platform/sala/research/arranque.sh")
_binarios.append((_RESEARCH_LAUNCHER, "platform/sala/research"))

# ⚠️ Y LOS DE SU HERMANO, QUE NO VIAJABAN. `platform/` NO es un `_DATA_DIR` (viaja entero
# sólo en founder, y ni ahí: founder sólo suma `platform/inspection`), así que ni el
# launcher ni los `.py` de §6.a.bis entraban en el bundle. El modo tenía su SearXNG, su
# runtime y su standalone adentro, y no tenía con qué arrancarlos. Se cierra acá porque es
# el mismo hecho y la misma línea; el síntoma habría sido `pack_no_instalado` sobre 1,5 GB
# de piezas presentes.
_BUSQUEDA_LAUNCHER = os.path.join(_SALA_BUSQUEDA, "arranque.sh")
if not os.path.isfile(_BUSQUEDA_LAUNCHER):
    raise SystemExit("spec: falta el launcher de la búsqueda: platform/sala/busqueda/arranque.sh")
_binarios.append((_BUSQUEDA_LAUNCHER, "platform/sala/busqueda"))

# LOS MÓDULOS DE LOS DOS PACKS, como datos. Son código nuestro que corre en el intérprete
# DEL PACK (no en el del sidecar), así que no puede ir al PYZ: `arranque.sh` se lo pasa a
# su python por ruta.
for _dir_pack, _dest_pack in ((_SALA_RESEARCH, "platform/sala/research"),
                              (_SALA_BUSQUEDA, "platform/sala/busqueda")):
    for _f in sorted(os.listdir(_dir_pack)):
        if _f.endswith(".py") and not _f.startswith("verify_"):
            datas.append((os.path.join(_dir_pack, _f), _dest_pack))

# El motor como datos: es una librería que se importa por `PYTHONPATH`, no un paquete
# instalado, así que Analysis no lo ve y tiene que viajar declarado.
datas.append((_LDR_SRC, "third_party/ldr/src"))

# Y las dependencias, OPACAS: `torch`, `faiss` y compañía traen Mach-O (`.so`, `.dylib`)
# que el PyInstaller exterior no puede re-firmar ni relocalizar. Mismo tratamiento que
# Educación, Finanzas y las cuatro piezas de §6.a.bis, y por el mismo motivo.
_OPAQUE_PACK_DIRS += [
    (_RESEARCH_LIB, "platform/sala/research/lib"),
]
print("spec: deep research → motor LDR + 279 deps + launcher (runtime Python compartido)")

datas.append((_WEB_EDUCACION, "third_party/deeptutor/web/.next/standalone"))

# ── [Gate 4 · F6-finanzas] BACKEND PYTHON CONGELADO + CARA DEL WORKSPACE ───────────────
# Finanzas tiene un backend Python propio. El launcher se versiona con Aleph, pero el
# runtime no puede quedar en un `.venv` de la máquina que construyó la `.app`: en la
# instalación limpia ese era el archivo que faltaba y el pack moría antes de abrir el puerto.
# El onedir va como DATA opaco (igual que Educación): sus Mach-O internos no se pueden
# re-firmar ni relocalizar desde el PyInstaller exterior.
_PACK_FINANZAS = os.environ.get("ALEPH_VIBETRADING_BACKEND", "")
_FINANZAS_UI = os.path.join(REPO, "third_party/vibetrading/frontend/dist")
if not _PACK_FINANZAS or not os.path.isfile(
        os.path.join(_PACK_FINANZAS, "vibe_trading_backend")):
    raise SystemExit(
        "spec: falta el backend congelado de Finanzas; build_app.sh debe producir "
        "vibe_trading_backend")
if not os.path.isdir(_FINANZAS_UI):
    raise SystemExit(
        "spec: falta la UI construida de Finanzas: third_party/vibetrading/frontend/dist")
_OPAQUE_PACK_DIRS.append(
    (_PACK_FINANZAS, "third_party/vibetrading/bin/vibe_trading_backend"))
datas.append((_FINANZAS_UI, "third_party/vibetrading/frontend/dist"))

# ── [Gate 4 · F6-oficina] LAS CUATRO PIEZAS DE OFICINA ──────────────────────────────────
#
# Oficina viaja distinto a Ciencia, y la diferencia importa: el binario de OpenScience
# EMBEBE su UI, así que su `dist` se pudo sacar. **El de OpenWork no.** Su server sirve la
# interfaz desde el disco, por `OPENWORK_WEB_ROOT` (`static-ui.ts`), y la fila del registro
# apunta a `third_party/openwork/apps/app/dist`. Si ese dir no viaja, la `.app` levanta un
# server que contesta la API y no tiene cara.
#
# Y son CUATRO porque un vertical de oficina no es sólo su pantalla:
#   · el CUERPO   — `openwork-server`, compilado con `bun build --compile` (no está en git)
#   · el MOTOR    — `opencode`, el harness que corre el agente (commiteado y verificado:
#                   ver `third_party/opencode/IMPORT.md`; sin él el cuerpo no corre un turno)
#   · las MANOS   — `gws` (cloud) y `officecli` (local), los dos commiteados
# Cada una se declara con su ruta de DESTINO igual a la que la fila espera, porque
# `pack.binario_de` y `entorno_de` resuelven contra `resource_root()` y en el congelado eso
# es `_MEIPASS`: una ruta distinta acá sería un workspace que dice estar instalado y no abre.
_OFICINA_UI = os.path.join(REPO, "third_party/openwork/apps/app/dist")
if os.path.isdir(os.path.join(_OFICINA_UI)):
    datas.append((_OFICINA_UI, "third_party/openwork/apps/app/dist"))
else:
    raise SystemExit(
        "spec: falta la UI construida de Oficina.\n"
        "      cd third_party/openwork && pnpm run build\n"
        "      (su server la sirve desde el disco: sin esto la .app no tiene cara)")

_PACK_OFICINA = os.path.join(REPO, "third_party/openwork/apps/server/dist/bin/openwork-server")
if os.path.isfile(_PACK_OFICINA):
    _binarios.append((_PACK_OFICINA, "third_party/openwork/bin"))
    print(f"spec: pack de Oficina → {os.path.getsize(_PACK_OFICINA) / 1048576:.1f} MiB")
else:
    raise SystemExit(
        "spec: falta el binario del cuerpo de Oficina.\n"
        "      cd third_party/openwork/apps/server && \\\n"
        "      bun run build:bin (incluye el addon nativo safe-fs)\n"
        "      (sin él, la .app diría tener Oficina y no podría levantarla)")

# El motor y las manos SÍ están en git — pinneados y con su SHA en sus IMPORT.md — así que
# si faltan es que alguien los borró, y eso se dice en vez de producir una .app coja.
for _rel, _destino, _que in (
        ("third_party/opencode/bin/opencode-darwin-arm64", "third_party/opencode/bin", "el motor"),
        ("third_party/gws/bin/gws-macos-arm64", "third_party/gws/bin", "la mano cloud (gws)"),
        ("third_party/officecli/bin/officecli-macos-arm64", "third_party/officecli/bin",
         "la mano local (OfficeCLI)")):
    _ruta = os.path.join(REPO, _rel)
    if not os.path.isfile(_ruta):
        raise SystemExit(f"spec: falta {_que}: {_rel}")
    _binarios.append((_ruta, _destino))
    print(f"spec: {_que} → {os.path.getsize(_ruta) / 1048576:.1f} MiB")

# Las skills de las manos son DATOS, no binarios: el CLI las lee del disco.
for _rel in ("third_party/gws/skills", "third_party/officecli/skills"):
    _ruta = os.path.join(REPO, _rel)
    if os.path.isdir(_ruta):
        datas.append((_ruta, _rel))

a = Analysis(
    [os.path.join(REPO, "deploy", "fase4", "sidecar_serve.py")],
    pathex=pathex,
    binaries=_binarios,
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_EXCLUDES,
    noarchive=False,
)
# Estos dos árboles ya son aplicaciones PyInstaller completas. Se agregan DESPUÉS de
# Analysis para que la reclasificación automática binario/dato no vuelva a procesar sus
# Mach-O ni reescriba sus RPATH según la profundidad del sidecar exterior. EXE conserva
# además sus symlinks relativos; los bytes interiores quedan exactamente como los produjo
# su propio build.
def _arbol_opaco(_origen, _destino):
    """Expand an inner onedir without dereferencing its relative symlinks."""
    _toc = []
    for _actual, _directorios, _archivos in os.walk(_origen, followlinks=False):
        _rel = os.path.relpath(_actual, _origen)
        _base = _destino if _rel == "." else os.path.join(_destino, _rel)
        if _origen == _VANE_PLAYWRIGHT and _rel == ".":
            # Playwright's install bookkeeping stores the builder's absolute
            # node_modules path. Chromium never reads .links at runtime.
            _directorios[:] = [name for name in _directorios if name != ".links"]
        # os.walk lists symlinked directories in dirnames but does not yield them as
        # files. Emit the link and remove it from traversal explicitly.
        for _nombre in list(_directorios):
            _fuente = os.path.join(_actual, _nombre)
            if os.path.islink(_fuente):
                _toc.append((os.path.join(_base, _nombre), os.readlink(_fuente), "SYMLINK"))
                _directorios.remove(_nombre)
        for _nombre in _archivos:
            _fuente = os.path.join(_actual, _nombre)
            _nombre_destino = os.path.join(_base, _nombre)
            if os.path.islink(_fuente):
                _toc.append((_nombre_destino, os.readlink(_fuente), "SYMLINK"))
            else:
                _toc.append((_nombre_destino, _fuente, "DATA"))
    return _toc


for _origen, _destino in _OPAQUE_PACK_DIRS:
    a.datas += _arbol_opaco(_origen, _destino)
pyz = PYZ(a.pure)

# [4.4.2] TOGGLE onefile: externalBin de Tauri espera UN archivo, no un dir. Con
# ALEPH_SIDECAR_ONEFILE=1 el sidecar sale como binario único (para el bundle); si no,
# onedir (arranque rápido, para el harness de dev). Misma Analysis en ambos.
if os.environ.get("ALEPH_SIDECAR_ONEFILE") == "1":
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name="aleph_sidecar",
        # Incluye otro onefile PyInstaller como dato. `strip` alcanza también
        # ese payload en macOS y le corta el PKG final; debe viajar intacto.
        debug=False, strip=False, upx=False, console=True,
    )
else:
    # ⚠️ `strip=False`, POR EL MISMO MOTIVO QUE LA RAMA DE ARRIBA — y acá estaba en `True`.
    # [TANDA 3] MEDIDO el 2026-08-22 sobre el primer onedir real: `strip` reescribe los
    # Mach-O de terceros y los tres binarios pinneados salieron DISTINTOS de su origen.
    # Dos sobrevivieron (`opencode 1.17.11`, `gws 0.22.5`) y uno NO:
    #
    #     officecli-macos-arm64 → "Failure processing application bundle; possible file
    #                              corruption. Arithmetic overflow while reading bundle."
    #
    # O sea: la mano local de Oficina quedaba muerta en el bundle, sin que nada fallara al
    # construir. La rama onefile ya lo sabía y lo dice en su comentario; la onedir sólo se
    # usaba para el harness de dev, donde nadie corre officecli, así que el defecto nunca
    # se vio. Los bytes de un binario ajeno viajan INTACTOS.
    exe = EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name="aleph_sidecar",
        debug=False, strip=False, upx=False, console=True,
    )
    coll = COLLECT(
        exe, a.binaries, a.datas,
        strip=False, upx=False,
        name="aleph_sidecar",
    )
