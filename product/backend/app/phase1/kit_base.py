"""
kit_base.py — EL KIT BASE EQUIPADO DE FÁBRICA (FIX-P4).

LA DECISIÓN (caminata del 26-jul): un cerebro frontier no necesita que le digan que
sabe sumar o qué hora es — necesita los BRAZOS que no tiene. El agente NACE con el kit
equipado: invisible, sin trámite, con los gates de siempre activos. El Cuarto queda para
lo específico del OFICIO (KiCad, FreeCAD, Gmail, SEC-EDGAR), no para lo básico.

LOS 7 BRAZOS (8 servers; el brazo Web son dos: buscar + traer):
    1. Código      → pysandbox.run_python
    2. Archivos    → filesystem (bajo ${PUPPET_WORKDIR})
    3. Datos       → sqlite (${PUPPET_WORKDIR}/datos.db)
    4. Documentos  → markitdown.convert_to_markdown (LEER cualquier documento a markdown)
    5. Web         → duckduckgo.search/fetch_content (BÚSQUEDA GENERAL, motor default,
                     sin key ni trámite) + fetch.fetch (cualquier URL). El upgrade a
                     Exa/Brave con key del usuario es OPCIONAL y se equipa en el Cuarto:
                     jamás el default, porque el default no pide trámite.
    6. Oficina     → officecli (EDITAR un .docx/.xlsx/.pptx que ya existe). Complementa a
                     markitdown (que lee) y a `artifact_export` (que genera desde el
                     contenido del turno): ninguno de los tres hace el trabajo del otro.
    7. Pericias    → skills.list_skills/read_skill/read_skill_file — el formato Anthropic
                     Agent Skills (`SKILL.md`), de cualquier origen y con raíces declaradas.

═══ EL MECANISMO (no hay canal nuevo) ═══════════════════════════════════════════════
El kit viaja por el MISMO carril que cualquier belt del Cuarto: `belt.belt_refs[]` +
`belt.tool_filters{}` de la receta v1 (CONTRACT-RECIPE-v1-FROZEN §1). No se agrega una
top-key, no se toca el validador, no se toca el assembler y no se inventa un gate. Este
módulo es UN normalizador puro que el router aplica en los tres bordes de la receta:

    · POST /v1/puppets            (nace)     → el kit queda EN la config persistida
    · PUT  /v1/puppets/{id}/config (se edita) → el Cuarto no lo puede tirar sin querer
    · GET  /v1/users/{id}/puppets  (se carga) → backfill SILENCIO del agente viejo

IDEMPOTENCIA (la regla dura): si el agente YA tiene un server del kit en su
`tool_filters` — porque el usuario lo equipó a mano desde el catálogo — ese server NO se
toca: su subset curado manda y no se duplica ni se amplía. Y el `belt_ref` del kit se
agrega UNA sola vez (comparación por forma normalizada: path completo, slug, o el .md).
Cargar dos veces ⇒ el segundo `ensure_kit` devuelve `changed=False`.

ORDEN: el kit se APENDA AL FINAL de `belt_refs[]`. En `_merge_belt_cfgs` el PRIMER belt
gana ante colisión de nombre de server, así que los belts que el usuario eligió siempre
ganan sobre el kit.

GATES: cero gate nuevo, cero gate paralelo. Las clases de acción las DECLARA el belt en
`catalog/templates/kit/belt-kit.mcp.json` (`_meta.action_classes` — el mismo canal S16
que ya usa belt-inline-rich), el assembler las pliega y `recipe_enforcer`/`approval_gate`
deciden con sus pisos de siempre:
    · pysandbox.run_python  → piso inmutable `code_exec`: RETENIDA bajo toda autonomía.
      El preview dice honestamente que aún no hay jail de sistema operativo; la card de
      catálogo conserva su gate `exec` de F2a (vive en belt-generalistas; el kit no la toca).
    · filesystem.write_file/edit_file/create_directory/move_file y sqlite.write_query/
      create_table → el PISO de mutación externa los re-clasifica write-world: RETENIDAS
      bajo 'manual' Y bajo 'balanceado' (misma vara que write_xlsx).
    · lecturas (read_*, list_*, search, fetch, convert_to_markdown) → auto, sin gate.

PALANCA DE OPS / CALIBRACIÓN EN ROJO: `PUPPET_KIT_BASE=0` apaga el kit por completo.
Existe para PROBAR que el verde viene del kit y no de teatro: con el kit apagado, el
mismo caso e2e debe FALLAR. No es una perilla de producto.

═══ LOS DOS COSTOS DEL KIT, MEDIDOS — y por qué NO lleva tool search ═══════════════
[T1 · 2026-08-18] Medido con `assembler.MCPServer` (el cliente de PROD), belt del kit,
arranque en frío, los 6 vivos:

    server        arranque   tools        pysandbox es stdlib puro; los otros 5 son
    pysandbox         27ms       1        npx/uvx y se llevan el 99 % del tiempo.
    filesystem      1439ms      14
    sqlite          1207ms       6        SUMA EN SERIE   5.818 ms
    markitdown      1770ms       1        EL CAMINO REAL  1.937 ms  ← el que importa
    duckduckgo       563ms       2        COSTO 2 · TOKENS ~5.053 tokens · 25 tools
    fetch            813ms       1
    SUMA            5818ms      25

⚠️ CORRECCIÓN — LOS 5.818 ms NO SON EL COSTO DEL PISO, y esto se midió después de
   escribirlo mal acá: son la SUMA en serie de mi arnés. El camino de producción del run
   (`restaurador.restaurar_servers`) YA arranca EN PARALELO con un ThreadPoolExecutor
   (`_MAX_PARALELO = 8`), y medido de punta a punta sobre el kit da **1.937 ms con 6/6
   arrancados** — o sea el máximo (markitdown), no la suma. No hay obra de paralelizar
   pendiente para el piso: ya estaba hecha.
   Lo que SÍ sigue en serie es `session.py` (la Sesión viva), que es OTRO consumidor y no
   el camino del piso. Si alguna vez la Sesión pesa, ahí está el mismo arreglo por hacer.

⚠️ LOS ABSOLUTOS SON COTA SUPERIOR: se midieron con otra sesión buildeando (PyInstaller
   disputando CPU) — una segunda pasada dio 12.802 ms, que es contención, no caché fría.
   La FORMA (serie · reparto 27ms vs el resto · 25 tools) no depende de la carga.
   Los tokens son `chars/4` (no había tiktoken en el venv), no un conteo exacto.

**NO SE PONE TOOL SEARCH / `defer_loading`, y esto es el dato para no reabrirlo sin uno
nuevo:** el umbral con que Claude Code difiere tools es 10K tokens de descripciones — el
kit pesa ~5K, la MITAD. Y el break-even del lazy está entre 15 y 30 tools: con 25 el kit
cae DENTRO de la banda, donde el índice más el runtime de búsqueda AGREGAN latencia sin
comprar tokens de vuelta. El problema del piso no son los tokens: es el arranque.

Y para el arranque, lazy es el arreglo CONTRARIO (on-demand paga el spawn en la primera
llamada a cada server). Lo que corresponde es CALENTAR EN BACKGROUND — y el mecanismo ya
existe: `platform/inspection/dueno.py` sostiene las conexiones (ahorro declarado ahí:
274-819 ms por server, ~3 s por agente de 6; costo ~113 MB por conexión, techo 8).
⚠️ Su perilla `ALEPH_DUENO` está en **off por default y no se prende en NINGÚN arranque
real** (medido: cero hits en `deploy/`, `start_caso3_stack.sh`, `main.py`, `infra/`).
Y `/v1/cinturon/calentar` NO sirve al piso tal como está: exige `puppet_id` y
`calentar()` resuelve `piezas_del_agente(conn, puppet_id)` contra el registro por agente
(verificado en las 149 ramas que tienen el archivo: las 149 con el mismo 422).

Stdlib only. `ensure_kit` es PURA: no muta el dict del caller, no toca disco ni red.
"""
from __future__ import annotations

import copy
import json
import os
from typing import Any, Optional

# ── El belt del kit (ref PORTABLE, misma forma que emite atoms_router) ────────────────
KIT_BELT_REF = "catalog/templates/kit/belt-kit.mcp.json"

#: Formas equivalentes del mismo ref — belt_resolver acepta las tres (path, slug, spec .md).
#: Se comparan normalizadas para que el backfill JAMÁS duplique el belt de un agente que ya
#: lo trae escrito de otra manera.
_KIT_REF_ALIASES = frozenset({
    KIT_BELT_REF.lower(),
    "kit",
    "belt-kit.mcp.json",
    "catalog/belts/kit.md",
    "catalog/templates/kit/belt-kit.mcp.json",
})

#: server → subset CURADO de tools que el kit cablea. No es la superficie completa de cada
#: server: es lo que el brazo necesita (§3.3 "SOLO the curated subset").
KIT_TOOL_FILTERS: dict[str, list[str]] = {
    # 1 · CÓDIGO
    "pysandbox": ["run_python"],
    # 2 · ARCHIVOS (allow-list = ${PUPPET_WORKDIR})
    "filesystem": [
        "read_text_file", "read_multiple_files", "list_directory", "directory_tree",
        "search_files", "get_file_info", "list_allowed_directories",
        "write_file", "edit_file", "create_directory", "move_file",
    ],
    # 3 · DATOS
    # `describe_table` queda FUERA del subset a propósito: el hint castellano "escrib" de
    # EXTERNAL_WRITE_HINTS es SUBSTRING de "d-escrib-e", así que el piso del gate la
    # re-clasifica write-world y una LECTURA quedaría pidiendo permiso cada vez. Falso
    # positivo PREEXISTENTE del enforcer (conservador hacia gatear, ver FIX-P4-KIT.md
    # §hallazgos) que no se toca desde acá; `list_tables` + `read_query` sobre sqlite_master
    # cubren lo mismo sin un candado fantasma.
    "sqlite": ["read_query", "write_query", "create_table", "list_tables"],
    # 4 · DOCUMENTOS
    "markitdown": ["convert_to_markdown"],
    # 5a · WEB · búsqueda general (motor default, sin key)
    "duckduckgo": ["search", "fetch_content"],
    # 5b · WEB · traer cualquier URL
    "fetch": ["fetch"],
    # 6 · DOCUMENTOS DE OFICINA, EDITABLES. Una sola tool que recibe una línea de comando
    # de officecli. Complementa a `markitdown` (que LEE a markdown) y a `artifact_export`
    # (que GENERA desde el contenido del turno): esto abre un .docx/.xlsx/.pptx que ya
    # existe y lo modifica conservando todo lo demás.
    "officecli": ["officecli"],
    # 7 · PERICIAS. El formato Anthropic Agent Skills, cargado por la casa desde raíces
    # DECLARADAS. Divulgación progresiva: el índice es barato, el cuerpo se pide.
    "skills": ["list_skills", "read_skill", "read_skill_file"],
}

#: Los 6 servers, en orden de brazo (para el reporte/evidencia y las sondas).
KIT_SERVERS: tuple[str, ...] = tuple(KIT_TOOL_FILTERS.keys())

_OFF_VALUES = ("0", "false", "no", "off", "")


def kit_enabled() -> bool:
    """¿El kit está activo? `PUPPET_KIT_BASE=0` lo apaga (palanca de calibración en rojo).
    Ausente / cualquier otro valor ⇒ ACTIVO (el kit es el default, no un opt-in)."""
    raw = os.environ.get("PUPPET_KIT_BASE")
    if raw is None:
        return True
    return str(raw).strip().lower() not in _OFF_VALUES


def _norm_ref(ref: Any) -> str:
    return str(ref or "").strip().strip("/").lower()


def _as_config(config: Any) -> Optional[dict]:
    """Acepta el dict de la receta o su JSON crudo (defensa: psycopg2 devuelve JSONB ya
    decodificado y el shim SQLite también, pero un caller viejo puede pasar el texto)."""
    if isinstance(config, dict):
        return config
    if isinstance(config, str) and config.strip():
        try:
            parsed = json.loads(config)
        except (ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def has_kit_ref(config: Any) -> bool:
    """¿La receta ya declara el belt del kit (en cualquiera de sus formas)?"""
    cfg = _as_config(config)
    if cfg is None:
        return False
    belt = cfg.get("belt")
    if not isinstance(belt, dict):
        return False
    refs = [belt.get("belt_ref")] + list(belt.get("belt_refs") or [])
    return any(_norm_ref(r) in _KIT_REF_ALIASES for r in refs if r)


def kit_state(config: Any) -> dict:
    """Diagnóstico legible del kit en una receta (lo consumen las sondas y el reporte):
    {"ref": bool, "servers": {server: "kit"|"propio"|"ausente"}, "completo": bool}."""
    cfg = _as_config(config) or {}
    belt = cfg.get("belt") if isinstance(cfg.get("belt"), dict) else {}
    tf = belt.get("tool_filters") if isinstance(belt.get("tool_filters"), dict) else {}
    servers = {}
    for srv, tools in KIT_TOOL_FILTERS.items():
        if srv not in tf:
            servers[srv] = "ausente"
        elif list(tf.get(srv) or []) == list(tools):
            servers[srv] = "kit"
        else:
            servers[srv] = "propio"   # el usuario lo equipó a mano: su subset manda
    return {"ref": has_kit_ref(cfg),
            "servers": servers,
            "completo": has_kit_ref(cfg) and all(v != "ausente" for v in servers.values())}


def ensure_kit(config: Any) -> tuple[Any, bool]:
    """Completa el kit en una receta v1. Devuelve `(config, cambió)`.

    · PURA — devuelve una COPIA si hay algo que cambiar; si no hay nada que hacer devuelve
      el MISMO objeto y `False` (así el caller no reescribe la DB sin motivo).
    · IDEMPOTENTE — un server ya presente en `tool_filters` NO se toca (ni se amplía ni se
      duplica); el belt_ref se agrega una sola vez.
    · CONSERVADORA — si `config` no es una receta con `belt` dict, no toca nada. Un
      `belt_ref` singular preexistente se PRESERVA y además se siembra en `belt_refs[]`
      (el assembler prefiere `belt_refs` cuando está: sin sembrarlo, agregar el kit
      habría dejado al agente sin su belt original).
    """
    if not kit_enabled():
        return config, False
    cfg = _as_config(config)
    if cfg is None:
        return config, False
    belt = cfg.get("belt")
    if not isinstance(belt, dict):
        return config, False

    tf = belt.get("tool_filters")
    tf = tf if isinstance(tf, dict) else {}
    faltan = [s for s in KIT_TOOL_FILTERS if s not in tf]
    falta_ref = not has_kit_ref(cfg)
    if not faltan and not falta_ref:
        return config, False        # ya completo → cero escritura, cero duplicado

    out = copy.deepcopy(cfg)
    out_belt = out["belt"]

    if falta_ref:
        refs = out_belt.get("belt_refs")
        refs = [r for r in refs if r] if isinstance(refs, list) else []
        if not refs and out_belt.get("belt_ref"):
            # el belt singular se conserva Y se siembra en la lista: el assembler
            # prefiere belt_refs[] y sin esta línea el agente perdería su belt propio.
            refs = [out_belt["belt_ref"]]
        refs.append(KIT_BELT_REF)   # AL FINAL: el belt del usuario gana la colisión
        out_belt["belt_refs"] = refs

    if faltan:
        out_tf = dict(out_belt.get("tool_filters") or {})
        for srv in faltan:
            out_tf[srv] = list(KIT_TOOL_FILTERS[srv])
        out_belt["tool_filters"] = out_tf

    return out, True


__all__ = ["KIT_BELT_REF", "KIT_TOOL_FILTERS", "KIT_SERVERS",
           "kit_enabled", "has_kit_ref", "kit_state", "ensure_kit"]
