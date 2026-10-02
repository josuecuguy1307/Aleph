"""
atoms_router.py — GET /v1/atoms/catalog : el INVENTARIO de PIEZAS (átomos) del diorama.

Agrega las `_meta.cards` de TODOS los belts que las declaran (en catalog/templates;
fixtures quedaron test-only), valida que cada card tenga server real (cero theater),
le infiere la ZONA (C3: lee=Fuentes · procesa=Mesa · saca/gate=Entrega) reusando el
enforcer, y marca el estado por-usuario (keyless→ready · token/oauth→connected/connectable).

Cada átomo trae su `belt_ref` (portable). La proyección del Cuarto arma `belt.belt_refs[]`
con la UNIÓN de los belt_ref de los átomos colocados → composición dinámica (motor Fase 2.0).
De-dup por (server + tools): la misma pieza en dos belts aparece UNA vez (gana el primer belt).
"""
from __future__ import annotations

import importlib.util as _ilu
import json
import os
import shutil
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, Header

# [Casa 2 · Fase 4 · 4.1] frozen-aware (bundle → _MEIPASS). Import guardado: atoms_router se
# importa antes de que platform/ entre al sys.path (mismo patrón que aleph_paths.is_client).
# En dev, resource_root() == parents[4] (la raíz del repo) → byte-idéntico.
try:
    import aleph_paths as _ap
except ImportError:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "platform"))
    import aleph_paths as _ap
_REPO = _ap.resource_root()
_ONB = _REPO / "catalog" / "connectors" / "onboarding"
# [ledger 2026-07-04] platform/assembler/fixtures EXCLUIDO del walk: sus 12 atomos fueron
# PROMOVIDOS a catalog/templates/{research,generalistas} y fixtures volvio a ser test-only
# (platform/PLATFORM-LEDGER.md, "frontera fixtures→prod del catalogo de atomos").
_BELT_DIRS = [_REPO / "catalog" / "templates"]


def _raices_de_belts(owner: Optional[str] = None) -> list:
    """[(directorio, raíz para el `belt_ref`), …] — de dónde salen las cards.

    ⚠️ [OBRA 6b · #6] LA SEGUNDA RAÍZ ES EL `synth_belts` DEL USUARIO, y su ausencia era un
    agujero medido: una pieza traída del catálogo público forja su belt ahí **con sus cards
    bien declaradas** (7, 5, 2 y 0 en las cuatro medidas) y nadie las leía. Resultado: la
    pieza quedaba en «Tus conectores» pero no existía como átomo, así que no se podía
    equipar en ningún agente — distinguible de las 41 justo en lo único que importa.

    ⚠️ [A1 · LA FUGA ENTRE CUENTAS] Y ES EL `synth_belts` **DE ESE USUARIO**, no la raíz
    entera. Acá se caminaba `synth_belts/` completo, y **Aleph tiene multicuenta local**:
    cuentas distintas en la misma instalación. Efecto medido sobre los datos reales de la
    máquina el 2026-08-07: de 184 átomos traídos, **64 eran de otra cuenta** — El Cuarto
    mostraba las piezas de todas juntas. No es ruido de pruebas: es exposición entre
    cuentas de la misma máquina.

    **SIN DUEÑO NO SE SIRVE EL `synth_belts` DE NADIE**, y es fail-closed a propósito: una
    pieza traída es de alguien, y servirla «por las dudas» cuando no sabemos de quién es la
    pantalla es exactamente la fuga con otro nombre. El catálogo de la caja sí se sirve
    entero — el público no depende de tener cuenta.

    ⚠️ Y CADA DIRECTORIO TRAE SU PROPIA RAÍZ, que no es cosmética. El `belt_ref` de un belt
    del usuario es relativo al dir de DATOS (`synth_belts/<user>/<slug>/belt-….mcp.json`,
    exactamente la forma que ya persiste `conexion.belt_ref`), jamás al repo: una ruta
    absoluta de esta máquina en un `belt_ref` funciona acá y en ninguna otra, y el contrato
    del repo lo prohíbe por escrito. Por eso la raíz sigue siendo `data_root()` aunque el
    directorio que se camina baje un nivel: la ref que se persiste no cambia de forma.

    Se resuelve en cada llamada, no al importar: el dir de datos depende del entorno del
    proceso (`ALEPH_DATA_DIR`), y congelarlo en una constante de import ataría el catálogo
    al valor que hubiera cuando se cargó el módulo.
    """
    raices = [(d, _REPO) for d in _BELT_DIRS]
    if owner:
        try:
            datos = _ap.data_root()
            raices.append((datos / "synth_belts" / str(owner), datos))
        except Exception:  # noqa: BLE001 — sin dir de datos, el catálogo interno sigue entero
            pass
    return raices
_GATES_DIR = _REPO / "platform" / "gates"

_READ_PREFIXES = ("get_", "read_", "search_", "list_", "fetch_", "lookup_", "find_", "query_")

_enf_mod = None
def _enf():
    global _enf_mod
    if _enf_mod is None:
        import aleph_paths
        _enf_mod = aleph_paths.load_module_by_path("puppet_enf_atoms", _GATES_DIR / "recipe_enforcer.py")
    return _enf_mod


def _zone_for(card: dict) -> str:
    """Regla C3: override curado (card.zone) > send/money=Entrega > todo-lectura=Fuentes > Mesa."""
    z = card.get("zone")
    if z in ("fuentes", "mesa", "entrega"):
        return z
    tools = card.get("tools") or []
    enf = _enf()
    try:
        if any(enf.suggests_send(t) or enf.suggests_money_touch(t) for t in tools):
            return "entrega"
    except Exception:
        pass
    if tools and all(any(t.startswith(p) for p in _READ_PREFIXES) for t in tools):
        return "fuentes"
    return "mesa"


def _onb_exists(connector: Optional[str]) -> bool:
    return bool(connector) and (_ONB / f"{connector}.json").exists()


def _gate_for(tools: list, card: Optional[dict] = None, auth: str = "keyless") -> dict:
    """¿El átomo TOCA EL MUNDO con efecto persistente? Delega en la fuente autoritativa
    (recipe_enforcer.gate_for_card): override DECLARADO por la card > alcance real de las tools
    (money/send/exec/write-externo), NUNCA la zona. El motor FUERZA money/send igual
    (recipe_enforcer §3.5); acá lo surfaceamos para que el panel de Opciones lo muestre."""
    enf = _enf()
    try:
        return enf.gate_for_card(card, tools or [], auth)
    except Exception:
        return {"gated": False, "level": None}


# ── DÓNDE CORRE CADA PIEZA ─────────────────────────────────────────────────────────
# El servidor de Aleph NO ejecuta MCPs de paquete (node/uv/docker arbitrarios): es la
# decisión de producto del Dockerfile ("el cliente sigue siendo local") y además ejecutar
# paquetes del registro público server-side sería superficie de ataque nueva.
#
# Pero eso NO recorta el catálogo. La vitrina no miente ni limita: GUÍA. Una pieza que el
# contenedor no puede lanzar sigue ofrecida, con su camino claro ("corre en tu máquina ·
# requiere X"). Lo único inaceptable era el falso verde: "Ya funciona · sin llave" sobre
# algo que server-side no arranca nunca.
#
# ⚠️ ESTO SE EVALÚA CONTRA EL ENTORNO QUE ESTÁ CORRIENDO, a propósito. El mismo código
# dice la verdad en los dos lados: en el contenedor `npx` no existe → "corre en tu
# máquina"; en el backend local del usuario, si tiene node → "listo". La honestidad no es
# una constante, es una medición.
_PKG_RUNNERS = {
    "npx": "Node.js",  "node": "Node.js",  "bunx": "Bun",  "deno": "Deno",
    "uvx": "uv (Python)", "uv": "uv (Python)", "docker": "Docker",
}


def _belts_root() -> Path:
    """BELTS-ROOT ÚNICO (decisión T7). Un export del operador gana; si no, el default."""
    return Path(os.environ.get("PUPPET_BELTS") or (_REPO / "product" / "belts"))


def server_runtime(cfg: dict, card: Optional[dict] = None) -> tuple[str, list[str], str]:
    """¿Este entorno puede LANZAR este server? → (runtime, requires, detalle).

    `requires` es LO QUE EL USUARIO TIENE QUE INSTALAR y sale en el badge — va en su
    idioma ("Node.js", "FreeCAD"), nunca en el nuestro. `detalle` es diagnóstico técnico
    (rutas, vars sin expandir): útil en el panel y en logs, jamás en la vitrina. Mezclarlos
    hacía que la card dijera "requiere handler ausente: ${PUPPET_REPO}/platform/assem…",
    que para quien mira el catálogo no significa absolutamente nada.

    Reemplaza al chequeo viejo, que sólo miraba que la card nombrara un server DECLARADO
    en el belt — no que el handler EXISTIERA. Por eso el catálogo ofrecía 40 piezas en
    verde de las que el contenedor podía correr 2.
    """
    # `requiere_app` es el BELT declarando que este server necesita software de escritorio
    # (FreeCAD, CalculiX, ngspice, un venv con pydicom…). Vive en el server, no en la card.
    # Se respeta antes que cualquier chequeo de rutas: que el .py exista no significa nada
    # si el binario que va a invocar no está. Sin esto, cad-headless / cad-fem /
    # simulacion-drc se pintaban verdes igual — el proceso levanta y la tool falla, que es
    # el mismo falso verde con un paso más de distancia.
    req_app = cfg.get("requiere_app") or (card or {}).get("requiere_app")
    if req_app:
        return "local", [str(req_app).split("(")[0].split("—")[0].strip()], str(req_app)

    cmd = (cfg.get("command") or "").strip()
    args = [a for a in (cfg.get("args") or []) if isinstance(a, str)]
    if not cmd:
        return "local", [], "el belt no declara `command` para este server"

    base = cmd.rsplit("/", 1)[-1]
    if base in _PKG_RUNNERS:
        # Gestor de paquetes: alcanza con que el binario exista en el PATH de este entorno.
        return (("server", [], "") if shutil.which(base)
                else ("local", [_PKG_RUNNERS[base]], f"`{base}` no está en el PATH de este entorno"))

    # Intérprete declarado COMO RUTA (absoluta, relativa, o con un placeholder tipo
    # `<mcp-install>/…`): hay que validar LA RUTA, no el nombre del binario del final.
    # Mirar sólo el último segmento daba un falso verde real: `kicad-sch` declara
    # `<mcp-install>/mcp-kicad-sch-api/.venv/bin/python` y, como el basename es "python"
    # y python SÍ existe en la imagen, se pintaba "Listo · server" — sobre un venv que no
    # existe en ningún lado. Lo cazó comparar prod (12 ready) contra la simulación (11).
    if "/" in cmd:
        ruta_cmd = Path(cmd.replace("${PUPPET_BELTS}", str(_belts_root()))
                           .replace("${PUPPET_REPO}", os.environ.get("PUPPET_REPO") or str(_REPO)))
        if not ruta_cmd.is_absolute():
            ruta_cmd = _REPO / ruta_cmd
        if "<" in str(ruta_cmd) or not ruta_cmd.is_file():
            return "local", [], f"intérprete no encontrado: {cmd}"
    elif not shutil.which(base):
        return "local", [base], f"`{base}` no está en el PATH de este entorno"

    # Intérprete presente → el script que va a ejecutar TIENE que existir.
    script = next((a for a in args if a.endswith(".py")), None)
    if script is None:
        return "server", [], ""      # -m módulo u otra forma: no se puede afirmar que falte
    ruta = Path(script.replace("${PUPPET_BELTS}", str(_belts_root()))
                      .replace("${PUPPET_REPO}", os.environ.get("PUPPET_REPO") or str(_REPO)))
    if not ruta.is_absolute():
        ruta = _REPO / ruta
    if "${" in str(ruta):
        return "server", [], ""      # otra var sin expandir: no inventamos un veredicto
    # Handler que no viaja al servidor: para el usuario esto NO es "falta un archivo",
    # es "esta pieza corre en tu máquina". El path va al detalle, no al badge.
    return (("server", [], "") if ruta.is_file()
            else ("local", [], f"el handler no viaja al servidor: {script}"))


def estado_honesto(cfg: dict, card: dict, *, auth: str, connector: Optional[str],
                   connected: set, partial: set) -> dict:
    """Estado de UNA pieza: dónde corre + state + badge. **LA ÚNICA fuente de verdad.**

    Existe porque esto estaba DUPLICADO: `atoms_router.collect_atoms` y
    `belts_router.belt_cards` calculaban el estado por su cuenta, con las mismas reglas
    escritas dos veces. Cuando se arregló el falso verde en uno, el otro siguió diciendo
    "Ya funciona · sin llave" — y el otro es justamente el que consume El Cuarto
    (`GET /v1/belts/cards`), o sea el fix no llegaba a la pantalla. Dos copias de una
    regla son una regla y un bug esperando.
    """
    runtime, falta, detalle = server_runtime(cfg, card)
    out: dict = {"runtime": runtime, "requires": falta}
    if detalle:
        out["runtime_detail"] = detalle          # diagnóstico, NUNCA al badge
    if card.get("requiere_app"):
        out["requiere_app"] = card["requiere_app"]   # prosa del belt, para la capa de guía

    if runtime == "local":
        # No se oculta ni se saca: se ofrece con su camino. La capa de guía (cómo
        # instalarlo / que lo instale tu CLI) es onboarding de Casa 2; acá va el ESTADO.
        out["state"] = "local"
        out["badge"] = (f"Corre en tu máquina · requiere {falta[0]}" if falta
                        else "Corre en tu máquina")
        if auth != "keyless":
            out["connectable"] = _onb_exists(connector)   # además pide credencial
    elif auth == "keyless":
        out["state"] = "ready"; out["badge"] = "Listo · server"
    elif connector in partial:
        # STEP 2·A3 · PARCIAL antes que conectado: un OAuth que pidió offline pero no trajo
        # refresh tiene access token (está en `connected`) pero caduca ~1h → NO es verde.
        out["state"] = "partial"; out["badge"] = "Parcial · caduca pronto"
        out["connectable"] = _onb_exists(connector)
    else:
        is_conn = connector in connected
        out["state"] = "connected" if is_conn else "connectable"
        # "solo tu API key" = el segundo estado honesto: no hay NADA que instalar, la pieza
        # corre server-side en cuanto pongas la llave.
        out["badge"] = "Listo · solo tu API key" if is_conn else "Conectar"
        out["connectable"] = _onb_exists(connector)
    return out


def _requirements_for(card: dict, atom: dict) -> dict:
    """C2 · lo que el panel de Opciones debe RENDERIZAR para ESTE átomo, DECLARADO por el
    catálogo (no un form fijo). Forma acordada con Stream A (ver FASE1-C3-BYO-NOTES.md):

      connection — si el átomo necesita activarse/credencial (una Conexión token/OAuth/BYOK):
                   el panel muestra el botón activar + campo de llave/OAuth. keyless → no.
      params     — params propios de la tool (subset del inputSchema, curado por la card);
                   [] si no declara ninguno (una Fuente read-only no pide nada).
      gate       — si toca el mundo (send/money) el motor lo fuerza; el panel lo MUESTRA.

    Las 3 perillas universales (Autonomía→gate · Detalle→prompt · Pasos→loop) las arma el
    panel SIEMPRE; `requirements` son los campos EXTRA que cada átomo suma encima."""
    auth = atom["auth"]
    needs_conn = auth != "keyless"
    return {
        "connection": {
            "needed": needs_conn,
            "auth": auth,                       # keyless | token | oauth | byok
            "connector": atom.get("connector"),
            "connectable": bool(atom.get("connectable")) if needs_conn else False,
            "state": atom["state"],             # ready | connectable | connected
        },
        "params": card.get("params") or [],     # passthrough de params declarados por la card
        "gate": _gate_for(atom.get("tools") or [], card, atom.get("auth", "keyless")),
    }


def collect_atoms(connected: Optional[set] = None, partial: Optional[set] = None,
                  *, owner: Optional[str] = None) -> list[dict]:
    """Agrega las cards (átomos) de todos los belts con _meta.cards, zonadas (C3) y con
    estado por-usuario. Reutilizable: lo usan el endpoint /v1/atoms/catalog y la FORJA.
    `partial` (STEP 2·A3) = conectores OAuth incompletos (offline sin refresh) → estado 'partial'.

    ⚠️ `owner` NO ES OPCIONAL EN EL SENTIDO DE «DA IGUAL». Es el dueño de la sesión, y sin él
    NO se sirve ninguna pieza traída — sólo el catálogo de la caja (ver `_raices_de_belts`).
    Va como keyword-only para que nadie lo pase de posición por accidente donde antes iban
    `connected`/`partial`: confundir un set de conectores con un id de usuario serviría el
    `synth_belts` de una carpeta que no existe, en silencio y en verde."""
    connected = connected or set()
    partial = partial or set()
    atoms: list[dict] = []
    seen: set = set()   # de-dup por (backed_by + tools)
    for d, raiz in _raices_de_belts(owner):
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*.mcp.json")):
            try:
                belt = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            servers = belt.get("mcpServers", {}) or {}
            cards = (belt.get("_meta") or {}).get("cards") or []
            if not cards:
                continue
            # RELATIVO A **SU** RAÍZ. Ver `_raices_de_belts`: un belt del usuario se referencia
            # contra el dir de datos, uno del catálogo contra el repo. Si algún día un belt
            # cae fuera de la raíz que le tocó, se lo salta en vez de persistir una ruta
            # absoluta de esta máquina.
            try:
                belt_ref = str(p.relative_to(raiz))
            except ValueError:
                continue
            for c in cards:
                backed = c.get("backed_by")
                if backed not in servers:
                    continue   # cero theater
                tools = c.get("tools") or []
                key = backed + "::" + ",".join(sorted(tools))
                if key in seen:
                    continue   # misma pieza en otro belt → una vez (gana el primero)
                seen.add(key)
                auth = c.get("auth", "keyless")
                # La credencial pertenece al SERVICIO, no necesariamente al proveedor
                # técnico que transporta un server. FRED/FeedOracle es el caso índice:
                # `origin_connector=feedoracle`, pero la puerta humana y el vault son FRED.
                origin_connector = c.get("connector")
                connector = c.get("credential_provider") or origin_connector
                atom = {
                    "id": c.get("id"), "label": c.get("label"), "sub": c.get("sub"),
                    "atom": "conexion" if auth != "keyless" else "tool",
                    "zone": _zone_for(c),
                    "server": backed, "tools": tools,
                    "belt_ref": belt_ref, "auth": auth, "connector": connector,
                    "origin_connector": origin_connector,
                    "credential_provider": c.get("credential_provider") or connector,
                    "service": c.get("service"),
                    "official": bool(c.get("official")),
                    "migration_source": c.get("migration_source") or "legacy_card",
                    "armario": c.get("armario"),
                    # criticality de la card (default "low"): el frontend pide confirmación al SACAR
                    # una pieza "high" mientras el agente está trabajando (evita cortar la tarea en curso).
                    "criticality": c.get("criticality", "low"),
                }
                # DÓNDE CORRE + ESTADO — una sola llamada, una sola fuente de verdad.
                atom.update(estado_honesto(servers[backed], c, auth=auth,
                                           connector=connector,
                                           connected=connected, partial=partial))
                # C2: lo que el panel de Opciones debe pedir POR ESTE átomo (no fijo)
                atom["requirements"] = _requirements_for(c, atom)
                atoms.append(atom)
    return atoms


def _owner_from_session(authorization: Optional[str]) -> Optional[str]:
    """El dueño de la request, SIEMPRE desde la sesión.

    [Step 5 · P8 · T-S5-03] `_connected_for` recibía un `user_id` de QUERY STRING y
    con él leía las claves de esa cuenta. O sea:

        GET /v1/atoms/catalog?user_id=<uuid-ajeno>

    devolvía, SIN NINGUNA SESIÓN, qué conectores tenía conectados esa persona
    (verificado en vivo: 'GitHub' aparecía como `connected`). No filtraba secretos —
    el contrato BYOK garantiza que `list_keys` sólo devuelve provider/last4 — pero sí
    el inventario privado de integraciones de una cuenta ajena.

    Misma causa raíz que T-S5-01: identidad puesta por el cliente. Mismo cierre: sale
    de la sesión y el parámetro deja de existir.
    """
    tok = (authorization or "").strip()
    if tok.lower().startswith("bearer "):
        tok = tok[7:].strip()
    if not tok:
        return None
    try:
        from app.phase1 import repo
        return repo.session_owner(tok)
    except Exception:
        return None


def _connected_for(user_id: Optional[str], get_conn) -> tuple[set, set]:
    """(connected, partial) del usuario. STEP 2·A3: clasifica con repo.classify_key_providers
    (fuente única) → excluye las filas companion __oauth* y marca los parciales; así El Cuarto NO
    pinta verde un conector que caduca a la hora."""
    if user_id and get_conn is not None:
        try:
            from app.phase1 import repo
            conn = get_conn()
            try:
                provs = [k.get("provider") for k in repo.list_keys(conn, user_id)]
            finally:
                conn.close()
            return repo.classify_key_providers(provs)
        except Exception:
            pass
    return set(), set()


def build_atoms_router(*, get_conn: Optional[Callable[[], Any]] = None) -> APIRouter:
    router = APIRouter(prefix="/v1/atoms", tags=["atoms"])

    @router.get("/catalog")
    def atoms_catalog(authorization: Optional[str] = Header(default=None)):
        # T-S5-03: el dueño sale de la SESIÓN. El viejo ?user_id= ya no existe.
        _dueno = _owner_from_session(authorization)
        _connected, _partial = _connected_for(_dueno, get_conn)
        atoms = collect_atoms(_connected, _partial, owner=_dueno)
        by_zone = {"fuentes": 0, "mesa": 0, "entrega": 0}
        for a in atoms:
            by_zone[a["zone"]] = by_zone.get(a["zone"], 0) + 1
        return {"atoms": atoms, "total": len(atoms),
                "by_zone": {z: by_zone.get(z, 0) for z in ("fuentes", "mesa", "entrega")}}

    return router


__all__ = ["build_atoms_router"]
