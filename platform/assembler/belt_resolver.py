#!/usr/bin/env python3
"""
belt_resolver.py — Resolves a recipe's `belt_ref` (catalog slug, decision B) to a
runnable `.mcp.json` belt file.

WHY THIS EXISTS (RECIPE-SCHEMA.md §2, decision B):
    The approved v1 recipe points at the belt by a PORTABLE catalog reference
    (`belt.belt_ref`), e.g. "catalog/belts/finanzas.md" or "finanzas" — it does NOT
    hard-code the host path of the `.mcp.json`. Hard-coding the path would couple the
    recipe to one machine and break "agregar nicho = escribir receta, no recodear".
    The runtime (this module) is the single place that maps belt_ref → .mcp.json.

RESOLUTION ORDER (first match wins), all relative to repo_root:
    1. belt_ref already IS a path to an existing `.mcp.json`     → use it directly.
    2. belt_ref is a catalog SPEC markdown (catalog/belts/<slug>.md) → derive slug,
       then look up the template belt:  catalog/templates/<slug>/belt-<slug>.mcp.json
    3. belt_ref is a bare slug ("finanzas")                       → same template path.
    4. belt_ref is any path to an existing file (e.g. a custom .mcp.json)  → use it.

The resolver NEVER guesses silently: if nothing resolves it raises BeltResolutionError
with every candidate path it tried, so the failure is debuggable.

No third-party deps (stdlib only). Pure function — no side effects, no network.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


class BeltResolutionError(Exception):
    """Raised when belt_ref cannot be resolved to an existing .mcp.json."""

    def __init__(self, belt_ref: str, tried: list[str]):
        self.belt_ref = belt_ref
        self.tried = tried
        super().__init__(
            f"belt_ref '{belt_ref}' no resuelve a ningún .mcp.json. "
            f"Candidatos probados:\n  - " + "\n  - ".join(tried)
        )


class BeltRefInvalid(BeltResolutionError):
    """Raised when belt_ref is not a portable path inside a supported root."""


class AgentResolutionError(Exception):
    """Raised when an agent_ref cannot be resolved to a v1 child recipe.

    AGENTE ANIDADO (amendment aditiva-v1): separado de BeltResolutionError porque un
    agent_ref apunta a OTRA RECETA, no a un .mcp.json. La resolución es el paso 1; la
    EJECUCIÓN/delegación es el paso 2 (no vive en este módulo)."""

    def __init__(self, agent_ref: str, tried: list[str]):
        self.agent_ref = agent_ref
        self.tried = tried
        super().__init__(
            f"agent_ref '{agent_ref}' no resuelve a una receta-agente v1. "
            f"Probado:\n  - " + "\n  - ".join(tried)
        )


def _data_root_or_none() -> Path | None:
    """Raíz durable del usuario, disponible tanto en dev como en el bundle."""
    try:
        import aleph_paths  # type: ignore
    except ImportError:
        import sys
        platform_dir = str(Path(__file__).resolve().parents[1])
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


@dataclass
class ResolvedBelt:
    """The outcome of resolving a belt_ref (una capacidad de tipo TOOL)."""
    belt_ref: str
    mcp_json_path: Path
    slug: str
    servers: list[str] = field(default_factory=list)
    type: str = "tool"   # discriminador tool|agent (aditivo; el paso 2 ramifica por esto)

    def as_dict(self) -> dict:
        return {
            "type": self.type,
            "belt_ref": self.belt_ref,
            "mcp_json_path": str(self.mcp_json_path),
            "slug": self.slug,
            "servers": self.servers,
        }


@dataclass
class ResolvedAgent:
    """El resultado de resolver un agent_ref → una RECETA HIJA (sub-agente).

    AGENTE ANIDADO (amendment aditiva-v1, 2026-06-26). Acá NO se ejecuta ni se delega
    nada (eso es el paso 2): sólo se CARGA la receta hija y se hace un check estructural
    ligero. Lleva `type='agent'` para que el ejecutor (paso 2) ramifique a DELEGAR en vez
    de cablear un MCP. Contrapartida simétrica de ResolvedBelt (type='tool')."""
    agent_ref: str
    recipe_path: Path
    recipe: dict
    slug: str
    type: str = "agent"

    def as_dict(self) -> dict:
        return {
            "type": self.type,
            "agent_ref": self.agent_ref,
            "recipe_path": str(self.recipe_path),
            "slug": self.slug,
            # NO volcamos la receta entera; sólo su identidad (el paso 2 tiene .recipe)
            "recipe_meta": (self.recipe.get("meta") or {}) if isinstance(self.recipe, dict) else {},
        }


def _slug_from_ref(belt_ref: str) -> str:
    """Extract the niche slug from a belt_ref.

    'catalog/belts/finanzas.md' -> 'finanzas'
    'finanzas'                  -> 'finanzas'
    'catalog/templates/demo-test/belt-demo.mcp.json' -> 'demo' (best-effort)
    """
    name = Path(belt_ref).name
    if name.endswith(".md"):
        return name[: -len(".md")]
    if name.endswith(".mcp.json"):
        # belt-<slug>.mcp.json -> <slug>
        stem = name[: -len(".mcp.json")]
        if stem.startswith("belt-"):
            return stem[len("belt-"):]
        return stem
    # bare slug
    return name


def resolve_belt_ref(belt_ref: str, repo_root: Path, *, portable_only: bool = False) -> ResolvedBelt:
    """Resolve belt_ref to a runnable .mcp.json. See module docstring for the order.

    Args:
        belt_ref:  the recipe's belt.belt_ref string.
        repo_root: absolute path to the repository root (recipe paths are relative to it).
        portable_only: reject absolute refs and traversal; for persisted/user-facing refs.

    Returns:
        ResolvedBelt with the absolute .mcp.json path and the list of server names.

    Raises:
        BeltResolutionError if nothing resolves.
    """
    if not belt_ref or not isinstance(belt_ref, str):
        raise BeltResolutionError(str(belt_ref), ["(belt_ref vacío o no-string)"])

    repo_root = Path(repo_root)
    ref_path = Path(belt_ref)
    if portable_only and (ref_path.is_absolute() or ".." in ref_path.parts):
        raise BeltRefInvalid(belt_ref, ["(belt_ref absoluto o fuera de rango)"])
    slug = _slug_from_ref(belt_ref)
    tried: list[str] = []

    def _candidate(p: Path) -> Path:
        return p if p.is_absolute() else (repo_root / p)

    candidates: list[Path] = []

    # Los belts creados por el usuario son datos durables. Su ref sigue siendo
    # relativa/portable (``synth_belts/...``), pero se ancla a data_root. Se prueba
    # antes del orden histórico sin alterar cómo resuelven los belts del repo.
    if belt_ref.endswith(".mcp.json") and not Path(belt_ref).is_absolute():
        data_root = _data_root_or_none()
        if data_root is not None:
            candidates.append(data_root / belt_ref)

    # 1. belt_ref is a path that already ends in .mcp.json
    if belt_ref.endswith(".mcp.json"):
        candidates.append(_candidate(Path(belt_ref)))

    # 2 & 3. derive the template belt from the slug (strict name first)
    template_dir = repo_root / "catalog" / "templates" / slug
    candidates.append(template_dir / f"belt-{slug}.mcp.json")

    # 4. any path to an existing file (custom belt outside the template tree)
    if not belt_ref.endswith(".mcp.json"):
        candidates.append(_candidate(Path(belt_ref)))

    for cand in candidates:
        tried.append(str(cand))
        if cand.exists() and cand.is_file():
            servers = _read_server_names(cand)
            return ResolvedBelt(
                belt_ref=belt_ref,
                mcp_json_path=cand.resolve(),
                slug=slug,
                servers=servers,
            )

    # 5. fallback: the template dir exists but its belt file isn't named
    #    strictly belt-<slug>.mcp.json. Scan the dir for a single .mcp.json.
    #    (catalog naming isn't always belt-<slug>; e.g. demo-test ships belt-demo.mcp.json.)
    if template_dir.is_dir():
        tried.append(str(template_dir / "<scan *.mcp.json>"))
        mcp_files = sorted(template_dir.glob("*.mcp.json"))
        if len(mcp_files) == 1:
            cand = mcp_files[0]
            return ResolvedBelt(
                belt_ref=belt_ref,
                mcp_json_path=cand.resolve(),
                slug=slug,
                servers=_read_server_names(cand),
            )
        if len(mcp_files) > 1:
            tried.append(
                f"(ambiguo: {len(mcp_files)} .mcp.json en {template_dir} — "
                "renombra a belt-<slug>.mcp.json o apunta belt_ref al archivo)"
            )

    raise BeltResolutionError(belt_ref, tried)


def resolve_belt_refs(belt_refs: list, repo_root: Path) -> list:
    """Composición dinámica: resuelve una LISTA de belt_refs → [ResolvedBelt].

    Mantiene el ORDEN de la lista (el primer belt gana en una colisión de nombre de
    server, aguas arriba al mergear). De-dup por archivo .mcp.json (un belt repetido
    se resuelve una sola vez). Lanza BeltResolutionError en el primer ref que no resuelva.
    """
    out: list = []
    seen: set = set()
    for ref in (belt_refs or []):
        r = resolve_belt_ref(ref, repo_root)
        key = str(r.mcp_json_path)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    if not out:
        raise BeltResolutionError(str(belt_refs), ["(belt_refs vacío)"])
    return out


# ── MEMORIA COMPARTIDA · resolución de recipe.memory.ref (primera clase) ────────
# La receta puede declarar un bloque TOP-LEVEL `memory = {shared: true, ref: "..."}`.
# El ref se resuelve por el MISMO camino que los belt_refs (resolve_belt_ref): es un
# belt .mcp.json más (el del server de memoria), sólo que lo compone el RUNTIME cuando
# la memoria compartida está activa — no viaja en belt_refs[].

DEFAULT_MEMORY_REF = "product/belts/memoria-compartida.mcp.json"


def resolve_memory_ref(recipe: dict, repo_root: Path) -> ResolvedBelt | None:
    """Resuelve `recipe.memory.ref` → el belt de memoria compartida, con la MISMA
    resolución de paths que belt_refs (reusa resolve_belt_ref; devuelve la MISMA
    estructura ResolvedBelt). Devuelve None si la receta no trae sección `memory`
    (o la trae con shared=false — memoria no activa). Si la sección está activa pero
    el ref no resuelve, propaga BeltResolutionError (fail honesto, no silencioso)."""
    mem = recipe.get("memory") if isinstance(recipe, dict) else None
    if not isinstance(mem, dict) or not mem.get("shared"):
        return None
    ref = mem.get("ref") or DEFAULT_MEMORY_REF
    return resolve_belt_ref(ref, Path(repo_root))


def _read_server_names(mcp_json_path: Path) -> list[str]:
    try:
        data = json.loads(mcp_json_path.read_text(encoding="utf-8"))
        return sorted(data.get("mcpServers", {}).keys())
    except (json.JSONDecodeError, OSError):
        return []


# ── AGENTE ANIDADO · resolución de agent_refs (amendment aditiva-v1) ─────────────
# SEPARADO de resolve_belt_ref a propósito: el camino de belt_refs[] (tools) queda
# byte-idéntico. Un agent_ref apunta a OTRA RECETA (sub-agente), no a un .mcp.json.
# Acá SÓLO se carga + se chequea la forma; NO hay ejecución/delegación (paso 2).

def _slug_from_agent_ref(agent_ref: str) -> str:
    """'catalog/agents/research.config.json' -> 'research'; 'research' -> 'research'."""
    name = Path(agent_ref).name
    for suf in (".config.json", ".json"):
        if name.endswith(suf):
            return name[: -len(suf)]
    return name


def _load_recipe_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise AgentResolutionError(str(path), [f"(no se pudo leer/parsear: {exc})"])


def _assert_child_recipe_shape(recipe, path: Path) -> None:
    """Check ESTRUCTURAL ligero de que el ref apunta a una receta v1 (no a un belt ni a
    basura). La validación PROFUNDA es validate_recipe (paso 2) — no acoplamos este módulo
    stdlib-only al validador del backend."""
    problems: list[str] = []
    if not isinstance(recipe, dict):
        problems.append("la receta-agente debe ser un objeto JSON (dict)")
    else:
        if recipe.get("schema_version") != "v1":
            problems.append(
                f"schema_version debe ser 'v1' (recibido {recipe.get('schema_version')!r}) "
                f"— un agent_ref apunta a una RECETA, no a un .mcp.json")
        if not isinstance(recipe.get("meta"), dict):
            problems.append("falta `meta` (un sub-agente es una receta COMPLETA con su Núcleo)")
        if not isinstance(recipe.get("belt"), dict):
            problems.append("falta `belt`")
    if problems:
        raise AgentResolutionError(str(path), problems)


def resolve_agent_ref(agent_ref: str, repo_root: Path) -> ResolvedAgent:
    """Resuelve un agent_ref (slug/path de catálogo) a su RECETA HIJA (v1) cargada.

    NO ejecuta ni delega (paso 2). Orden (relativo a repo_root, primero gana):
      1. agent_ref ya es un path a un .json existente.
      2. catalog/agents/<slug>.json  ·  catalog/agents/<slug>.config.json
      3. cualquier path a un archivo existente.

    Raises:
        AgentResolutionError si no resuelve o si el destino no es una receta v1.
    """
    if not agent_ref or not isinstance(agent_ref, str):
        raise AgentResolutionError(str(agent_ref), ["(agent_ref vacío o no-string)"])

    repo_root = Path(repo_root)
    slug = _slug_from_agent_ref(agent_ref)
    tried: list[str] = []

    def _candidate(p: Path) -> Path:
        return p if p.is_absolute() else (repo_root / p)

    candidates: list[Path] = []
    if agent_ref.endswith(".json"):
        candidates.append(_candidate(Path(agent_ref)))
    candidates.append(repo_root / "catalog" / "agents" / f"{slug}.json")
    candidates.append(repo_root / "catalog" / "agents" / f"{slug}.config.json")
    if not agent_ref.endswith(".json"):
        candidates.append(_candidate(Path(agent_ref)))

    for cand in candidates:
        tried.append(str(cand))
        if cand.exists() and cand.is_file():
            recipe = _load_recipe_json(cand)
            _assert_child_recipe_shape(recipe, cand)   # check estructural ligero
            return ResolvedAgent(
                agent_ref=agent_ref,
                recipe_path=cand.resolve(),
                recipe=recipe,
                slug=slug,
            )

    raise AgentResolutionError(agent_ref, tried)


def resolve_agent_refs(agent_refs: list, repo_root: Path) -> list:
    """Resuelve una LISTA de agent_refs → [ResolvedAgent]. De-dup por archivo de receta.
    Lista vacía/ausente → [] (agent_refs es OPCIONAL, a diferencia de belt_refs). ADITIVO."""
    out: list = []
    seen: set = set()
    for ref in (agent_refs or []):
        r = resolve_agent_ref(ref, repo_root)
        key = str(r.recipe_path)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


# ── CLI smoke ──────────────────────────────────────────────────────────────────

def _main() -> None:
    import sys

    if len(sys.argv) < 2:
        print("Uso: python belt_resolver.py <belt_ref> [repo_root]", file=sys.stderr)
        sys.exit(1)
    belt_ref = sys.argv[1]
    repo_root = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parents[2]
    try:
        resolved = resolve_belt_ref(belt_ref, repo_root)
        print(json.dumps(resolved.as_dict(), ensure_ascii=False, indent=2))
    except BeltResolutionError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    _main()
