"""
recipe_validator.py — valida la RECETA v1 ANIDADA contra el contrato taller↔assembler.

Fuente del contrato: platform/assembler/RECIPE-SCHEMA.md (APROBADO A+A+C, 2026-06-15):
  - forma ANIDADA v1 (meta / model / belt / framing / rag / keys / gates)
  - belt por `belt_ref` de catálogo (portable; el runtime resuelve al .mcp.json)
  - gates DECLARADOS en la receta + INVARIANTE §3.5 (la receta declara, Security hace cumplir)

Qué hace el Workshop con esto (microtask b):
  el taller VALIDA los params del usuario contra ESTE schema y RECHAZA lo que rompe el
  contrato taller↔assembler, ANTES de escribir puppets.config. Una receta inválida nunca
  llega a la DB ni al assembler.

QUÉ valida (rechaza = error; no-fatal = warning):
  1. Requeridos por §3.1: schema_version, meta.{name,nicho},
     model.{primary,base_url,temperature,max_tokens,max_turns},
     belt.{belt_ref,tool_filters}; rag.enabled; rag.mode si enabled.
  2. Tipos/rangos: temperature∈[0,2], max_tokens entero>0, max_turns entero>0,
     belt_ref string no vacío, tool_filters dict con valores lista[str].
  3. Nicho-agnóstico (§3.2): prohibido inventar claves de nivel-tope fuera del schema.
  4. belt_ref (§3.3, decisión B): es un SLUG/ref de catálogo, NO un path absoluto del host
     (eso rompe la portabilidad). Si el repo_root resuelve el belt, se valida que los
     servers de tool_filters existan en el belt (cuando hay forma de resolverlo); si no se
     puede resolver, warning 'no-resoluble' (NO error: belt_ref es portable por diseño).
  5. BYOK por referencia (§3.4): keys.<prov>.byok_ref con prefijo 'keys:' y NUNCA un valor
     en claro. Una key con valor literal (api_key / value / token / secret) => ERROR duro.
  6. INVARIANTE DE SEGURIDAD §3.5 (NO-NEGOCIABLE):
     - los gates mandatorios (money_touch, send) SIEMPRE se reportan como efectivos,
       aunque la receta los omita o los ponga 'off'. La omisión NO desactiva un mandatorio.
     - la receta puede AGREGAR gates (más estrictos), NUNCA quitar un mandatorio.
     - effective_gates() devuelve los gates EFECTIVOS (lo que Security hará cumplir),
       que es lo que el taller debe MOSTRAR (los mandatorios siempre).

Devuelve warnings en éxito; lanza RecipeValidationError(errors, warnings) si inválido.

Stdlib + json. Cero dependencias de framework (se puede usar fuera de FastAPI).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional


def _brain_providers_validos() -> frozenset[str]:
    """Enum de brain_provider: registry CLI + byok/managed."""
    try:
        asm = str(Path(__file__).resolve().parents[4] / "platform" / "assembler")
        if asm not in sys.path:
            sys.path.insert(0, asm)
        from cli_brain.registry import brain_provider_enum
        return brain_provider_enum()
    except Exception:
        return frozenset(("claude_cli", "codex_cli", "byok", "managed"))  # E1-FALLBACK


def _ref_escapes(ref: str) -> bool:
    """Un ref portable (belt/agent/method) NO puede ser absoluto NI trepar con '..':
    un '../../../etc/foo' resuelto contra repo_root escapa el árbol → oráculo de
    existencia de archivos del host desde un .aleph ajeno. Rechazamos ambos."""
    try:
        p = Path(ref)
    except (TypeError, ValueError):
        return True
    return p.is_absolute() or ".." in p.parts

SCHEMA_VERSION = "v1"

# Claves de nivel-tope permitidas en la receta v1 anidada (§3.2 nicho-agnóstico).
# `canvas` = PRESENTACIÓN pura del diorama del Cuarto (posiciones/zonas/links). El motor
# la IGNORA por completo; vive en config para rehidratar el diorama (decisión 2 del plan,
# "bloques = proyección de la receta"). No es clave de nicho → no rompe §3.2.
_ALLOWED_TOP_KEYS = frozenset(
    {"schema_version", "meta", "model", "model_use", "belt", "framing", "rag", "keys", "gates", "canvas",
     # MEMORIA COMPARTIDA (primera clase, decisión de persona usuaria): sección top-level opcional
     # {shared: bool, ref: str} — el runtime compone el belt de memoria y comparte UN
     # archivo entre el agente y sus sub-agentes. No es clave de nicho → no rompe §3.2.
     "memory",
     # AUTONOMÍA (Step 2 · A2): perilla agent-level 'manual'|'balanceado'|'autonomo' que
     # el runtime aplica en el gate (candado). Nicho-agnóstica (el valor es el dato) → §3.2 ok.
     "autonomy",
     # MULTIAGENTE F1 (docs/multiagente.md §1.4): `modo` = el CONTRATO DE EJECUCIÓN de un
     # globo — cadena|orquesta|oficina|abanico|null. Nicho-agnóstica (el valor es el dato)
     # → §3.2 ok. Mismo patrón aditivo que `autonomy`/`memory`: ausente o null ⇒ una receta
     # v1 valida y corre EXACTAMENTE como antes, byte por byte.
     "modo"}
)

# Valores válidos de la perilla de Autonomía (§A2). Ausente = default de producto
# ('balanceado') resuelto por el runtime; un valor fuera de esta lista es ERROR.
_AUTONOMY_VALUES = frozenset({"manual", "balanceado", "autonomo"})

# Gates MANDATORIOS (§3.5). La receta no puede quitarlos; el motor los fuerza.
# Valor efectivo mínimo = 'needs_ok' (la receta puede subir a más estricto, nunca a 'off').
MANDATORY_GATES = ("money_touch", "send")
_GATE_VALUES = frozenset({"off", "needs_ok"})

# Campos que delatan una key EN CLARO dentro de la receta (PROHIBIDO §3.4).
_PLAINTEXT_KEY_FIELDS = frozenset({"value", "api_key", "token", "secret", "key"})


def _data_root_or_none() -> Optional[Path]:
    """Raíz durable para validar refs ``synth_belts/...`` sin hacerla obligatoria."""
    try:
        import aleph_paths  # type: ignore
    except ImportError:
        import sys
        platform_dir = str(Path(__file__).resolve().parents[4] / "platform")
        if platform_dir not in sys.path:
            sys.path.insert(0, platform_dir)
        try:
            import aleph_paths  # type: ignore
        except Exception:  # noqa: BLE001
            return None
    except Exception:  # noqa: BLE001
        return None
    try:
        return Path(aleph_paths.data_root())
    except Exception:  # noqa: BLE001
        return None


# ── MULTIAGENTE F1 · el módulo del motor es la ÚNICA implementación ────────────
# `platform/assembler/multiagente.py` es stdlib-only (sin red, sin DB, sin framework) a
# propósito: eso es lo que permite que el VALIDADOR lo llame sin acoplarse al motor, y que
# el motor y el validador rechacen EXACTAMENTE lo mismo. Una prohibición que viviera sólo
# en la UI no sería una prohibición: sería un consejo que un POST directo saltea.
_MULTIAGENTE = None
_MULTIAGENTE_FALLO: Optional[str] = None


def _assembler_dir(repo_root: Optional[Path]) -> Optional[Path]:
    """El dir del motor, frozen-aware. Bajo PyInstaller `__file__` no es un path real, así
    que el orden empieza por lo que el caller ya resolvió y sigue por `aleph_paths`."""
    for cand in (
        (Path(repo_root) / "platform" / "assembler") if repo_root else None,
        _resource_assembler_dir(),
        _file_relative_assembler_dir(),
    ):
        if cand is not None and cand.is_dir():
            return cand
    return None


def _resource_assembler_dir() -> Optional[Path]:
    try:
        import aleph_paths as _ap  # type: ignore
        return Path(_ap.resource_root()) / "platform" / "assembler"
    except Exception:  # noqa: BLE001
        return None


def _file_relative_assembler_dir() -> Optional[Path]:
    try:
        return Path(__file__).resolve().parents[4] / "platform" / "assembler"
    except Exception:  # noqa: BLE001
        return None


def _multiagente(repo_root: Optional[Path] = None):
    """El módulo del motor, o None si no se pudo cargar (con el motivo en _MULTIAGENTE_FALLO).

    NO se falla-abierto en silencio: el caller convierte "no cargó" en ERROR **sólo si la
    receta declara `modo`/`agent_links`. Una receta que no los declara no puede verse
    afectada por un módulo que no cargó — y son el 100% de las recetas existentes."""
    global _MULTIAGENTE, _MULTIAGENTE_FALLO
    if _MULTIAGENTE is not None:
        return _MULTIAGENTE
    try:
        import multiagente as _m  # ya está en sys.path (el executor inserta el dir)
        _MULTIAGENTE = _m
        return _m
    except ImportError:
        pass
    d = _assembler_dir(repo_root)
    if d is None:
        _MULTIAGENTE_FALLO = "no se encontró platform/assembler/ desde el validador"
        return None
    try:
        import sys
        if str(d) not in sys.path:
            sys.path.insert(0, str(d))
        import multiagente as _m  # noqa: PLC0415
        _MULTIAGENTE = _m
        return _m
    except Exception as exc:  # noqa: BLE001
        _MULTIAGENTE_FALLO = f"{type(exc).__name__}: {exc}"
        return None


def _declara_multiagente(recipe: dict) -> bool:
    """¿Esta receta usa algo del multiagente? (si no, el módulo es irrelevante para ella)."""
    if recipe.get("modo") is not None:
        return True
    belt = recipe.get("belt")
    return isinstance(belt, dict) and belt.get("agent_links") is not None


class RecipeValidationError(Exception):
    """La receta viola el contrato. `errors` lista los motivos; `warnings` los no-fatales."""

    def __init__(self, errors: list[str], warnings: list[str] | None = None):
        self.errors = errors
        self.warnings = warnings or []
        super().__init__("Receta inválida:\n" + "\n".join(f"  • {e}" for e in errors))


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _is_int(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def effective_gates(recipe: dict[str, Any]) -> dict[str, str]:
    """
    Gates EFECTIVOS = lo que Security HARÁ CUMPLIR (§3.5), no lo que la receta DECLARA.

    - Cada gate mandatorio (money_touch, send) es 'needs_ok' como piso, aunque la receta
      lo omita o lo ponga 'off'. La omisión NO lo desactiva. La receta solo puede subir
      la estrictez, nunca bajarla por debajo de 'needs_ok'.
    - Gates extra declarados por la receta (más estrictos) se conservan tal cual.

    Esto es lo que el taller debe MOSTRAR al usuario (los mandatorios SIEMPRE visibles).
    """
    declared = recipe.get("gates") or {}
    if not isinstance(declared, dict):
        declared = {}
    eff: dict[str, str] = {}
    # mandatorios: piso 'needs_ok' aunque la receta diga 'off' u omita
    for g in MANDATORY_GATES:
        decl = declared.get(g)
        if decl in (None, "off", ""):
            eff[g] = "needs_ok"
        else:
            eff[g] = str(decl)
    # extras declarados por la receta (la receta SÍ puede agregar gates)
    for g, v in declared.items():
        if g not in MANDATORY_GATES:
            eff[g] = str(v)
    return eff


def _resolve_belt_path(belt_ref: str, repo_root: Optional[Path]) -> Optional[Path]:
    """
    Intenta resolver un belt_ref (slug de catálogo, decisión B) a un .mcp.json EXISTENTE.
    belt_ref es PORTABLE por diseño: si no resuelve, NO es error (se devuelve None y el
    caller emite warning 'no-resoluble'). Estrategias, en orden:
      1. belt_ref tal cual relativo a repo_root (p.ej. 'catalog/belts/finanzas.md' .json)
      2. el mismo pero cambiando extensión a .mcp.json
      3. catalog/templates/<slug>/belt-<slug>.mcp.json  (layout de templates existente)
    """
    if not repo_root:
        return None
    candidates: list[Path] = []
    raw = Path(belt_ref)
    if not raw.is_absolute():
        data_root = _data_root_or_none()
        if data_root is not None:
            candidates.append(data_root / raw)
    candidates.append(repo_root / raw)
    # cambiar sufijo a .mcp.json
    if raw.suffix and raw.suffix != ".json":
        candidates.append(repo_root / raw.with_suffix(".mcp.json"))
    # slug -> layout de templates
    slug = raw.stem if raw.suffix else belt_ref
    candidates.append(repo_root / "catalog" / "templates" / slug / f"belt-{slug}.mcp.json")
    candidates.append(repo_root / "catalog" / "belts" / f"{slug}.mcp.json")
    for c in candidates:
        if c.exists() and c.is_file() and c.suffix == ".json":
            return c
    # un .md no es resoluble como belt JSON: portable pero no verificable acá
    return None


def validate_recipe(
    recipe: dict[str, Any],
    repo_root: Path | None = None,
) -> list[str]:
    """
    Valida una receta v1 ANIDADA contra RECIPE-SCHEMA.md. Lanza RecipeValidationError si
    es inválida; devuelve lista de warnings (posiblemente vacía) si es válida.

    repo_root: para intentar resolver belt_ref → .mcp.json y validar tool_filters.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(recipe, dict):
        raise RecipeValidationError(["la receta debe ser un objeto JSON (dict)"])

    # ── schema_version ────────────────────────────────────────────────────────
    sv = recipe.get("schema_version")
    if sv != SCHEMA_VERSION:
        errors.append(
            f"schema_version debe ser '{SCHEMA_VERSION}' (recibido: {sv!r}); "
            f"cambios incompatibles ⇒ v2 + migración (§3.6)"
        )

    # ── nicho-agnóstico §3.2: no inventar claves de nivel-tope ─────────────────
    for k in recipe.keys():
        if k not in _ALLOWED_TOP_KEYS:
            errors.append(
                f"clave de nivel-tope no permitida: '{k}' "
                f"(la forma es nicho-agnóstica; lo específico vive en los VALORES, §3.2)"
            )

    # ── meta ───────────────────────────────────────────────────────────────────
    meta = recipe.get("meta")
    if not isinstance(meta, dict):
        errors.append("meta requerido y debe ser objeto (meta.name, meta.nicho)")
    else:
        if not meta.get("name") or not isinstance(meta.get("name"), str):
            errors.append("meta.name requerido (string no vacío)")
        if not meta.get("nicho") or not isinstance(meta.get("nicho"), str):
            errors.append("meta.nicho requerido (string no vacío)")

    # ── model ────────────────────────────────────────────────────────────────────
    model = recipe.get("model")
    if not isinstance(model, dict):
        errors.append(
            "model requerido y debe ser objeto "
            "(primary, base_url, temperature, max_tokens, max_turns)"
        )
    else:
        if not model.get("primary") or not isinstance(model.get("primary"), str):
            errors.append("model.primary requerido (alias LiteLLM o id, string no vacío)")
        if not model.get("base_url") or not isinstance(model.get("base_url"), str):
            errors.append("model.base_url requerido (string no vacío — el gateway)")
        temp = model.get("temperature")
        if temp is None or not _is_number(temp):
            errors.append("model.temperature requerido (número en [0.0, 2.0])")
        elif not (0.0 <= float(temp) <= 2.0):
            errors.append(f"model.temperature fuera de rango [0.0, 2.0]: {temp}")
        mt = model.get("max_tokens")
        if not _is_int(mt) or mt <= 0:
            errors.append(f"model.max_tokens requerido (entero positivo); recibido {mt!r}")
        mtu = model.get("max_turns")
        if not _is_int(mtu) or mtu <= 0:
            errors.append(f"model.max_turns requerido (entero positivo); recibido {mtu!r}")
        # BYO-CLI (aditivo, patrón `autonomy`): brain_provider es OPCIONAL; ausente →
        # comportamiento histórico byte-idéntico. Presente → enum cerrado (basura = 422).
        bp = model.get("brain_provider")
        if bp is not None and bp not in _brain_providers_validos():
            validos = " | ".join(sorted(_brain_providers_validos()))
            errors.append(
                "model.brain_provider inválido: "
                f"{bp!r} (válidos: {validos})"
            )
        # TICKET 27·3 · DIAL DE ESFUERZO (aditivo, patrón `brain_provider`): OPCIONAL; ausente →
        # byte-idéntico a hoy. Presente → enum cerrado (basura = 422). 'auto' = la plataforma decide.
        eff = model.get("effort")
        if eff is not None and eff not in ("low", "medium", "high", "max", "auto"):
            errors.append(
                f"model.effort inválido: {eff!r} (válidos: low | medium | high | max | auto)"
            )

    # ── model-use/v1 (extensión auditable, sin infraestructura) ───────────────
    # La Recipe v1 sigue llevando `model` materializado para rollback de ejecutores
    # heredados. Esta sección sólo conserva la identidad canónica que el backend volverá
    # a resolver al ejecutar; jamás acepta provider, URL, credenciales ni fallbacks.
    model_use = recipe.get("model_use")
    if model_use is not None:
        if not isinstance(model_use, dict):
            errors.append("model_use debe ser objeto")
        else:
            allowed_model_use = {"schema_version", "selection_ref", "selection_scope"}
            extras = sorted(set(model_use) - allowed_model_use)
            if extras:
                errors.append(
                    "model_use contiene claves no permitidas: " + ", ".join(extras)
                )
            if model_use.get("schema_version") != "model-use/v1":
                errors.append("model_use.schema_version debe ser 'model-use/v1'")
            selection_ref = model_use.get("selection_ref")
            if not isinstance(selection_ref, str) or not selection_ref.strip():
                errors.append("model_use.selection_ref requerido (id canónico no vacío)")
            selection_scope = model_use.get("selection_scope")
            if selection_scope not in {
                "default", "workspace", "agent", "partner", "session", "task", "service"
            }:
                errors.append("model_use.selection_scope inválido")

    # ── belt ───────────────────────────────────────────────────────────────────
    belt = recipe.get("belt")
    belt_ref: Optional[str] = None
    belt_refs_lista: list[str] = []
    tool_filters: dict[str, Any] = {}
    if not isinstance(belt, dict):
        errors.append("belt requerido y debe ser objeto (belt_ref, tool_filters)")
    else:
        belt_ref = belt.get("belt_ref")
        belt_refs = belt.get("belt_refs")
        # COMPOSICIÓN DINÁMICA: la receta puede traer belt.belt_refs (lista de slugs) para
        # componer varias apps/belts en un cuarto. Back-compat: belt_ref (string) sigue válido.
        if isinstance(belt_refs, list) and belt_refs:
            belt_refs_lista = [b for b in belt_refs if isinstance(b, str) and b.strip()]
            for i, br in enumerate(belt_refs):
                if not br or not isinstance(br, str):
                    errors.append(f"belt.belt_refs[{i}] debe ser un slug de catálogo (string no vacío)")
                elif _ref_escapes(br):
                    errors.append(
                        f"belt.belt_refs[{i}] no puede ser un path absoluto del host "
                        f"('{br}'): rompe la portabilidad (decisión B). Usa un slug de catálogo."
                    )
        elif not belt_ref or not isinstance(belt_ref, str):
            # SÓLO-DELEGA (amendment §6, regla 3): un padre SIN tools propias es legal —
            # el contrato congelado ya lo dice para `tool_filters` ({} si hay agent_refs),
            # pero `belt_ref` se había quedado afuera de esa misma relajación. El hueco lo
            # destapó el globo del multiagente F1 (docs/multiagente.md §1.1): un globo cuyas
            # piezas son SÓLO alephs no tiene belt que declarar, y sin esto no se puede ni
            # guardar. Se relaja EXACTAMENTE igual y con el mismo disparador (agent_refs
            # presente), no un milímetro más: sin agent_refs, la regla v1 queda intacta.
            if not (isinstance(belt.get("agent_refs"), list) and belt.get("agent_refs")):
                errors.append(
                    "belt.belt_ref (o belt.belt_refs[]) requerido (slug de catálogo, string "
                    "no vacío) — o ausente SÓLO si belt.agent_refs[] está presente (el agente "
                    "sólo delega, §6.3)")
        elif _ref_escapes(belt_ref):
            # decisión B: belt_ref es PORTABLE; un path absoluto del host lo rompe
            errors.append(
                f"belt.belt_ref no puede ser un path absoluto del host "
                f"('{belt_ref}'): rompe la portabilidad (decisión B). Usa un slug de catálogo."
            )

        # ── AGENTE ANIDADO · belt.agent_refs[] (amendment ADITIVA-v1, 2026-06-26) ──
        # Además de belt_refs[] (tools), la receta PUEDE traer belt.agent_refs[] = refs a
        # OTRAS RECETAS (sub-agentes con su propio Núcleo). REGLA LOAD-BEARING: un agente
        # va SIEMPRE en agent_refs, NUNCA en belt_refs[] (tipar un belt_refs[i] string→objeto
        # HARD-FALLA arriba, a propósito). MISMO TIPO que belt_refs: lista de slugs STRING
        # (no objetos), portables (no paths absolutos). El RESOLVER carga la receta hija; la
        # EJECUCIÓN/delegación es el paso 2 — acá sólo se valida la forma. Opcional y aditivo:
        # una receta v1 SIN agent_refs valida EXACTAMENTE igual que antes (cero cambio).
        agent_refs = belt.get("agent_refs")
        has_agent_refs = isinstance(agent_refs, list) and len(agent_refs) > 0
        if agent_refs is not None:
            if not isinstance(agent_refs, list):
                errors.append("belt.agent_refs, si está presente, debe ser una lista de slugs (string)")
            else:
                for i, ar in enumerate(agent_refs):
                    if not ar or not isinstance(ar, str):
                        errors.append(f"belt.agent_refs[{i}] debe ser un slug de receta-agente (string no vacío)")
                    elif _ref_escapes(ar):
                        errors.append(
                            f"belt.agent_refs[{i}] no puede ser un path absoluto del host "
                            f"('{ar}'): rompe la portabilidad (decisión B). Usa un slug de catálogo."
                        )

        # ── MÉTODO EQUIPADO · belt.method_refs[] (amendment ADITIVA-v1, pieza MÉTODO) ──
        # La receta PUEDE traer belt.method_refs[] = ids de la BIBLIOTECA de métodos
        # (referencia, no copia — editar el método actualiza a todos los equipados).
        # MISMO TIPO que agent_refs: lista de strings no vacíos, portables. El OBJETO
        # Method vive en la tabla `methods` (el executor lo resuelve owner-gated); acá
        # sólo se valida la forma. Sin esta validación explícita, basura entraría a la
        # DB en silencio (belt no tiene allowlist de sub-claves). Opcional y aditivo:
        # una receta SIN method_refs valida EXACTAMENTE igual que antes.
        method_refs = belt.get("method_refs")
        if method_refs is not None:
            if not isinstance(method_refs, list):
                errors.append("belt.method_refs, si está presente, debe ser una lista de ids (string)")
            else:
                for i, mref in enumerate(method_refs):
                    if not mref or not isinstance(mref, str):
                        errors.append(f"belt.method_refs[{i}] debe ser un id de método (string no vacío)")
                    elif _ref_escapes(mref):
                        errors.append(
                            f"belt.method_refs[{i}] no puede ser un path absoluto del host "
                            f"('{mref}'): rompe la portabilidad (decisión B). Usa el id de la biblioteca."
                        )

        # ── agent_policy (opcional) · política del padre sobre sus hijos ──────────
        # Aditivo: recetas sin agent_policy validan byte-idéntico. Si está presente:
        #   - debe ser objeto (basura no-dict se rechaza);
        #   - child_models (decisión 6-bis, override de modelo POR-HIJO) si está presente
        #     debe ser dict { <slug de agent_ref> : <model cfg PLANO> }, donde cada valor
        #     es un dict con al menos 'primary' o 'model' (string no vacío) — la misma
        #     forma plana que recipe.model / compileModel del Cuarto.
        agent_policy = belt.get("agent_policy")
        if agent_policy is not None:
            if not isinstance(agent_policy, dict):
                errors.append(
                    "belt.agent_policy, si está presente, debe ser objeto "
                    "(child_model / child_models / child_guardrails)"
                )
            else:
                child_models = agent_policy.get("child_models")
                if child_models is not None:
                    if not isinstance(child_models, dict):
                        errors.append(
                            "belt.agent_policy.child_models, si está presente, debe ser objeto "
                            "{<slug>: <model cfg plano>} (dict, no lista ni string)"
                        )
                    else:
                        for slug, mcfg in child_models.items():
                            if not isinstance(mcfg, dict):
                                errors.append(
                                    f"belt.agent_policy.child_models['{slug}'] debe ser objeto "
                                    f"(la forma PLANA de recipe.model); recibido {type(mcfg).__name__}"
                                )
                                continue
                            has_primary = isinstance(mcfg.get("primary"), str) and mcfg.get("primary")
                            has_model = isinstance(mcfg.get("model"), str) and mcfg.get("model")
                            if not has_primary and not has_model:
                                errors.append(
                                    f"belt.agent_policy.child_models['{slug}'] debe traer al menos "
                                    f"'primary' o 'model' (string no vacío) — misma forma que recipe.model"
                                )

        tf = belt.get("tool_filters")
        # tool_filters sigue REQUERIDO no-vacío... SALVO que la receta SÓLO delegue: si hay
        # belt.agent_refs[], un padre sin tools propias (tool_filters vacío) es VÁLIDO. Sin
        # agent_refs, la regla es idéntica a v1 (no-vacío) — cero cambio para recetas viejas.
        if not isinstance(tf, dict):
            errors.append(
                "belt.tool_filters requerido (dict no vacío: SOLO el subset curado, §3.3)"
            )
        elif not tf and not has_agent_refs:
            errors.append(
                "belt.tool_filters requerido (dict no vacío: SOLO el subset curado, §3.3) "
                "— o vacío SÓLO si belt.agent_refs[] está presente (el agente sólo delega)"
            )
        else:
            tool_filters = tf  # puede ser {} si la receta sólo delega (agent_refs presente)
            for server_name, tool_list in tf.items():
                if not isinstance(tool_list, list) or not all(
                    isinstance(t, str) for t in tool_list
                ):
                    errors.append(
                        f"belt.tool_filters['{server_name}'] debe ser lista de strings "
                        f"(nombres de tools del subset curado)"
                    )

        # Entidad Conector · aliases de superficie. Opcional y aditivo:
        # {server: {raw_name: exposed_name}}. Los filtros/gates siguen crudos.
        aliases = belt.get("tool_aliases")
        if aliases is not None:
            if not isinstance(aliases, dict):
                errors.append("belt.tool_aliases, si está presente, debe ser objeto")
            else:
                exposed: dict[str, str] = {}
                for server_name, mapping in aliases.items():
                    if not isinstance(server_name, str) or not isinstance(mapping, dict):
                        errors.append(
                            "belt.tool_aliases debe tener forma {server: {tool_cruda: tool_final}}"
                        )
                        continue
                    for raw_name, final_name in mapping.items():
                        if not isinstance(raw_name, str) or not raw_name or \
                           not isinstance(final_name, str) or not final_name:
                            errors.append(
                                f"belt.tool_aliases['{server_name}'] requiere strings no vacíos"
                            )
                            continue
                        previous = exposed.get(final_name)
                        if previous and previous != f"{server_name}:{raw_name}":
                            errors.append(
                                f"belt.tool_aliases colisión final '{final_name}': "
                                f"{previous} / {server_name}:{raw_name}"
                            )
                        exposed[final_name] = f"{server_name}:{raw_name}"

    # ── rag ────────────────────────────────────────────────────────────────────
    rag = recipe.get("rag")
    if not isinstance(rag, dict):
        errors.append("rag requerido y debe ser objeto (al menos rag.enabled)")
    else:
        enabled = rag.get("enabled")
        if not isinstance(enabled, bool):
            errors.append("rag.enabled requerido (bool)")
        elif enabled:
            mode = rag.get("mode")
            if mode not in ("manual", "auto"):
                errors.append(
                    f"rag.mode requerido si rag.enabled=true (manual|auto); recibido {mode!r}"
                )

    # ── framing (opcional; si está, validar forma) ─────────────────────────────
    framing = recipe.get("framing")
    if framing is not None and not isinstance(framing, dict):
        errors.append("framing, si está presente, debe ser objeto (ref / inline)")

    # ── keys §3.4: BYOK por REFERENCIA, jamás un valor en claro ────────────────
    keys = recipe.get("keys")
    if keys is not None:
        if not isinstance(keys, dict):
            errors.append("keys, si está presente, debe ser objeto {provider: {byok_ref}}")
        else:
            for prov, spec in keys.items():
                if not isinstance(spec, dict):
                    errors.append(f"keys['{prov}'] debe ser objeto con 'byok_ref'")
                    continue
                # PROHIBIDO: un valor en claro dentro de la receta (§3.4)
                leaked = sorted(set(spec.keys()) & _PLAINTEXT_KEY_FIELDS)
                if leaked:
                    errors.append(
                        f"keys['{prov}'] contiene una credencial EN CLARO ({leaked}): "
                        f"PROHIBIDO (§3.4). La key viva en la tabla `keys` (cifrada); la "
                        f"receta solo apunta con byok_ref."
                    )
                ref = spec.get("byok_ref")
                if not ref or not isinstance(ref, str):
                    errors.append(f"keys['{prov}'].byok_ref requerido (string 'keys:<provider>')")
                elif not ref.startswith("keys:"):
                    errors.append(
                        f"keys['{prov}'].byok_ref debe tener prefijo 'keys:' "
                        f"(apunta a la tabla keys); recibido '{ref}'"
                    )

    # ── gates §3.5: la receta DECLARA; validamos forma. El motor hace cumplir. ──
    gates = recipe.get("gates")
    if gates is not None:
        if not isinstance(gates, dict):
            errors.append("gates, si está presente, debe ser objeto {gate: off|needs_ok}")
        else:
            for g, v in gates.items():
                if v not in _GATE_VALUES:
                    errors.append(
                        f"gates['{g}'] debe ser 'off' o 'needs_ok'; recibido {v!r}"
                    )
            # §3.5: avisar (no error) si la receta intenta apagar un mandatorio — el
            # motor lo IGNORA y lo fuerza igual; el taller debe saberlo para mostrarlo.
            for g in MANDATORY_GATES:
                if gates.get(g) == "off":
                    warnings.append(
                        f"gates['{g}']='off' en la receta se IGNORA: '{g}' es mandatorio "
                        f"(§3.5) y el motor lo fuerza a 'needs_ok'. La receta no puede quitarlo."
                    )

    # ── autonomy (opcional) · perilla agent-level (Step 2 · A2) ────────────────
    # Aditivo: recetas SIN autonomy validan byte-idéntico. Si está, debe ser uno de
    # los tres valores; el runtime la aplica en el gate (el piso money no baja jamás).
    autonomy = recipe.get("autonomy")
    if autonomy is not None:
        if not isinstance(autonomy, str) or autonomy not in _AUTONOMY_VALUES:
            errors.append(
                f"autonomy debe ser uno de {sorted(_AUTONOMY_VALUES)}; recibido {autonomy!r}"
            )

    # ── MULTIAGENTE F1 (docs/multiagente.md §3) · `modo` + `belt.agent_links[]` ─────
    # La validación NO se escribe acá: se DELEGA al módulo del motor
    # (platform/assembler/multiagente.py), que es quien también la aplica al correr. Una
    # sola implementación ⇒ el validador y el motor rechazan exactamente lo mismo, con la
    # misma causa. Aditivo: una receta sin `modo` ni `agent_links` no pasa por acá.
    if _declara_multiagente(recipe):
        _ma = _multiagente(repo_root)
        if _ma is None:
            # FALLO VISIBLE, JAMÁS MUDO: no se puede validar un contrato de ejecución con el
            # módulo que lo define ausente. Dejar pasar sería guardar en la DB una receta
            # que después el motor rechaza — el peor de los dos mundos.
            errors.append(
                f"la receta declara multiagente (`modo`/`belt.agent_links`) pero el motor "
                f"multiagente no se pudo cargar ({_MULTIAGENTE_FALLO}): no se puede validar "
                f"el contrato de ejecución."
            )
        else:
            for _e in _ma.validar_forma(recipe):
                errors.append(f"[{_e['causa']}] {_e['detalle']}")

    # ── memory (opcional) · DOS sub-bloques independientes ─────────────────────
    #  (a) BUS COMPARTIDO: memory = { "shared": true, "ref": "product/belts/…mcp.json" }.
    #  (b) HERENCIA (orden 6): memory = { "inherit": "skill_only" | {projects|entries:[…]} | null }.
    # Cada uno es opcional y pueden coexistir. Aditivo: recetas SIN sección memory validan
    # byte-idéntico. El bus (shared+ref) se exige SÓLO si se está declarando un bus (uno de los dos
    # presente ⇒ ambos requeridos + coherentes). `inherit` es la POLÍTICA que el executor ya lee en
    # el A3-read (orden 4) — el validador la acepta acá para que el selector del panel (orden 6) pueda
    # producir una receta VÁLIDA que la lleve (el cabo LOW: read-path existía, faltaba dejarla pasar).
    memory = recipe.get("memory")
    if memory is not None:
        if not isinstance(memory, dict):
            errors.append("memory, si está presente, debe ser objeto "
                          "{shared: bool, ref: str} y/o {inherit: …}")
        else:
            _has_bus = ("shared" in memory) or ("ref" in memory)
            if _has_bus:
                if not isinstance(memory.get("shared"), bool):
                    errors.append("memory.shared requerido (bool) si declaras memoria compartida")
                mref = memory.get("ref")
                if not mref or not isinstance(mref, str):
                    errors.append("memory.ref requerido (string: ruta repo-relativa al belt de memoria)")
                elif Path(mref).is_absolute():
                    errors.append(
                        f"memory.ref no puede ser un path absoluto del host ('{mref}'): "
                        f"rompe la portabilidad (decisión B). Usa una ruta repo-relativa."
                    )
            if "inherit" in memory:
                inh = memory.get("inherit")
                # None (continuación) | str ('skill_only') | dict ({projects|entries:[…]}) — el mismo
                # dominio que apply_inheritance acepta; una forma ajena a esto es error de contrato.
                if not (inh is None or isinstance(inh, str) or isinstance(inh, dict)):
                    errors.append("memory.inherit, si está, debe ser null, string ('skill_only') "
                                  "u objeto ({projects|entries: [ids]})")
                elif isinstance(inh, dict):
                    for _sel in ("projects", "entries"):
                        if _sel in inh and not isinstance(inh[_sel], list):
                            errors.append(f"memory.inherit.{_sel} debe ser lista de ids")
            #  (c) TOGGLE "conoce tu cuenta" (ticket 4): memory = { "account_read": bool }.
            # Ausente ⇒ default TRUE (el executor inyecta la memoria de cuenta como hoy). Sólo
            # False literal la apaga. Enmienda aditiva v1: una receta sin la llave valida
            # byte-idéntico. Puede quedar SOLA (memory={account_read:false}) — no exige bus ni inherit.
            _has_acct = "account_read" in memory
            if _has_acct and not isinstance(memory.get("account_read"), bool):
                errors.append("memory.account_read, si está, debe ser bool "
                              "(true = tus agentes conocen tu cuenta; false = no)")
            if not _has_bus and "inherit" not in memory and not _has_acct:
                errors.append("memory, si está presente, debe declarar memoria compartida "
                              "(shared+ref), herencia (inherit) y/o account_read — no puede quedar vacía")

    # Si ya hay errores estructurales, cortamos antes de tocar el filesystem.
    if errors:
        raise RecipeValidationError(errors, warnings)

    # ── memory.ref debe existir en disco (relativo al repo root) ───────────────
    if isinstance(memory, dict):
        mref = memory.get("ref")
        if mref and isinstance(mref, str) and not Path(mref).is_absolute():
            if repo_root is not None:
                mpath = Path(repo_root) / mref
                if not (mpath.exists() and mpath.is_file()):
                    errors.append(
                        f"memory.ref '{mref}' no existe en disco relativo al repo root "
                        f"({repo_root}); el belt de memoria tiene que estar presente"
                    )
            else:
                warnings.append(
                    f"memory.ref '{mref}' no verificado en disco (sin repo_root); "
                    f"el runtime lo resolverá"
                )

    # ── §3.3: resolver LOS belts y validar que los servers existan en la UNIÓN ─
    #
    # ⚠ Esto medía SÓLO `belt_ref` (singular). Con `belt_refs[]` presente además del
    # singular, la unión real de servidores es más grande que la del singular, y todo
    # server que viniera del segundo belt se rechazaba como «fantasma».
    #
    # Lo destapó la integración de la tanda P: `ensure_kit` (FIX-P4) PRESERVA el
    # `belt_ref` singular y además siembra `belt_refs[]` con el kit — exactamente la
    # forma que este bloque no contemplaba. Resultado: `POST /v1/puppets` devolvía 422
    # `recipe_invalid` («sqlite/markitdown/duckduckgo no existen en belt-research») para
    # CUALQUIER receta con belt_ref singular. Cazado por qa/verify_sesion_total_frozen.
    #
    # El assembler ya componía la unión (`_merge_belt_cfgs`) y el README del Cuarto ya
    # declaraba la regla («composition across belts is allowed»): el validador era el que
    # estaba desincronizado. Se alinea acá.
    _refs = belt_refs_lista or ([belt_ref] if belt_ref else [])
    if _refs and tool_filters:
        known_servers: set[str] = set()
        sin_resolver: list[str] = []
        resueltos: list[str] = []
        for _ref in _refs:
            _path = _resolve_belt_path(_ref, repo_root)
            if _path is None:
                sin_resolver.append(_ref)
                continue
            try:
                _data = json.loads(_path.read_text(encoding="utf-8"))
                known_servers |= set(_data.get("mcpServers", {}).keys())
                resueltos.append(_path.name)
            except (json.JSONDecodeError, OSError) as exc:
                warnings.append(
                    f"no se pudo leer el belt resuelto '{_path}' para verificar "
                    f"tool_filters: {exc}"
                )
                sin_resolver.append(_ref)
        if sin_resolver:
            warnings.append(
                f"belt {sin_resolver} no se pudo resolver a un .mcp.json desde repo_root "
                f"(es PORTABLE por diseño, decisión B): tool_filters NO se verificó contra "
                f"el belt. El runtime lo resolverá."
            )
        # Sólo se acusa «fantasma» cuando TODOS los belts resolvieron: si uno quedó sin
        # resolver, el server podría vivir ahí y el error sería una calumnia.
        if resueltos and not sin_resolver:
            for server_name in tool_filters:
                if server_name not in known_servers:
                    errors.append(
                        f"belt.tool_filters server fantasma: '{server_name}' no existe "
                        f"en el/los belt(s) resuelto(s) {resueltos} "
                        f"(servidores: {sorted(known_servers)})"
                    )

    if errors:
        raise RecipeValidationError(errors, warnings)

    return warnings


__all__ = [
    "validate_recipe",
    "effective_gates",
    "RecipeValidationError",
    "MANDATORY_GATES",
    "SCHEMA_VERSION",
]
