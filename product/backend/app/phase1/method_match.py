"""Match de Método: `requires[]` × capacidades clasificadas por 5a.

La identidad de una pieza (id/server/conector) NO participa del match. Este módulo
consume el vocabulario que publica 5a en
``catalog/connectors/onboarding/*.json::permissions[]`` y compara
capacidad↔capacidad. La unión con una pieza se hace únicamente mediante el
``connector`` declarado por su card. No mantiene taxonomía, aliases ni nombres de
marcas propios.

Se conserva además el contrato aditivo de E1 para declaraciones explícitas:

    card = {
      "backed_by": "server-id",
      "capabilities": [
        "una fuente de filings SEC",
        {"name": "envío de correo", "resolution": "inline_key"}
      ]
    }

También se acepta `_meta.capabilities` con la misma lista para piezas sin card.
`resolution == inline_key`/`solo_llave` elige trámite inline; todo lo demás cae
en [Traer] → registro. Las capacidades de 5a caen en [Traer]: si la pieza no está
en el belt hay que equiparla antes de configurar su credencial. Si 5a todavía no
declaró una capacidad, queda faltante.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Optional

try:
    import aleph_paths
except ImportError:
    _PLATFORM = Path(__file__).resolve().parents[4] / "platform"
    if str(_PLATFORM) not in sys.path:
        sys.path.insert(0, str(_PLATFORM))
    import aleph_paths

REPO_ROOT = aleph_paths.resource_root()


def _declaration(value: Any) -> Optional[dict]:
    if isinstance(value, str):
        name = value.strip()
        return {"name": name, "resolution": "registro"} if name else None
    if not isinstance(value, dict):
        return None
    name = str(value.get("name") or value.get("capability") or "").strip()
    if not name:
        return None
    resolution = str(value.get("resolution") or value.get("resolver") or "registro").strip()
    out = {"name": name, "resolution": resolution or "registro"}
    target = str(value.get("target") or value.get("connector") or "").strip()
    if target:
        out["target"] = target
    return out


def _onboarding_declarations(repo_root: Path = REPO_ROOT) -> list[dict]:
    """Vocabulario publicado por 5a, sin inferir prosa ni identidades.

    ``permissions[]`` es la clasificación funcional sellada por 5a. El nombre
    del archivo sólo aporta el ``connector`` estable necesario para unir esa
    clasificación con la card que lo declara.
    """
    base = repo_root / "catalog" / "connectors" / "onboarding"
    out: list[dict] = []
    if not base.is_dir():
        return out
    for path in sorted(base.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        values = raw.get("permissions") if isinstance(raw, dict) else None
        if not isinstance(values, list):
            continue
        connector = path.stem
        for value in values:
            name = str(value or "").strip()
            if name:
                out.append({
                    "name": name,
                    "resolution": "registro",
                    "target": connector,
                    "source": "catalogo_5a",
                })
    return out


def _declared_in_belt(
    raw: dict,
    *,
    active_servers: Optional[set[str]] = None,
    repo_root: Path = REPO_ROOT,
) -> list[dict]:
    """Lee 5a por ``card.connector``; jamás desde ids/server/tools/labels."""
    meta = raw.get("_meta") if isinstance(raw.get("_meta"), dict) else {}
    by_connector: dict[str, list[dict]] = {}
    for decl in _onboarding_declarations(repo_root):
        connector = str(decl.get("target") or "")
        by_connector.setdefault(connector, []).append(decl)
    out: list[dict] = []
    for card in meta.get("cards") or []:
        if not isinstance(card, dict):
            continue
        backed = str(card.get("backed_by") or "")
        if active_servers is not None and backed and backed not in active_servers:
            continue
        connector = str(card.get("connector") or "").strip()
        if connector:
            out.extend(by_connector.get(connector, ()))
        values = card.get("capabilities") or []
        for value in values if isinstance(values, list) else [values]:
            decl = _declaration(value)
            if decl:
                out.append(decl)
    # Piezas que 5a clasifica a nivel belt/server y no tienen fila visual.
    raw_meta_caps = meta.get("capabilities") or []
    if isinstance(raw_meta_caps, dict):
        for server, values in raw_meta_caps.items():
            if active_servers is not None and str(server) not in active_servers:
                continue
            for value in values if isinstance(values, list) else [values]:
                decl = _declaration(value)
                if decl:
                    out.append(decl)
    elif isinstance(raw_meta_caps, list):
        for value in raw_meta_caps:
            decl = _declaration(value)
            if decl:
                out.append(decl)
    return out


def _belt_files(repo_root: Path = REPO_ROOT) -> Iterable[Path]:
    seen: set[Path] = set()
    for base in (repo_root / "catalog", repo_root / "product" / "belts"):
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.mcp.json")):
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                yield resolved


def capability_declarations(repo_root: Path = REPO_ROOT) -> list[dict]:
    """Vocabulario ÚNICO publicado por 5a en sus artefactos, con camino de arreglo."""
    by_fold: dict[str, dict] = {}
    for path in _belt_files(repo_root):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for decl in _declared_in_belt(raw, repo_root=repo_root):
            by_fold.setdefault(decl["name"].casefold(), decl)
    for decl in _onboarding_declarations(repo_root):
        by_fold.setdefault(decl["name"].casefold(), decl)
    return list(by_fold.values())


def capability_vocabulary(repo_root: Path = REPO_ROOT) -> list[str]:
    return [d["name"] for d in capability_declarations(repo_root)]


def _resolved_belt_paths(config: dict, repo_root: Path) -> list[Path]:
    belt = config.get("belt") if isinstance(config.get("belt"), dict) else {}
    refs = belt.get("belt_refs")
    refs = refs if isinstance(refs, list) else (
        [belt.get("belt_ref")] if belt.get("belt_ref") else [])
    if not refs:
        return []
    out: list[Path] = []
    pending: list[Any] = []
    for ref in refs:
        declared = Path(str(ref))
        # Los belt_refs portables son relativos al resource_root tanto en dev
        # como dentro de _MEIPASS. Resolver primero esa ruta declarada evita
        # depender del import dinámico de belt_resolver en el frozen.
        direct = declared if declared.is_absolute() else repo_root / declared
        if direct.is_file() and str(direct).endswith(".mcp.json"):
            out.append(direct.resolve())
        else:
            pending.append(ref)
    if not pending:
        return out
    asm = str(repo_root / "platform" / "assembler")
    if asm not in sys.path:
        sys.path.insert(0, asm)
    try:
        import belt_resolver
    except Exception:
        # Los paths directos ya resueltos siguen siendo válidos aunque el
        # resolver de referencias no esté importable (p. ej. un frozen mínimo).
        return out
    for ref in pending:
        try:
            out.append(belt_resolver.resolve_belt_ref(str(ref), repo_root).mcp_json_path)
        except Exception:
            # Un belt no resoluble no cubre nada: fail-closed.
            continue
    return out


def belt_capability_declarations(config: dict, repo_root: Path = REPO_ROOT) -> list[dict]:
    belt = config.get("belt") if isinstance(config.get("belt"), dict) else {}
    filters = belt.get("tool_filters")
    active = set(str(k) for k in filters) if isinstance(filters, dict) else None
    by_fold: dict[str, dict] = {}
    for path in _resolved_belt_paths(config, repo_root):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        servers = set((raw.get("mcpServers") or {}).keys())
        enabled = servers & active if active is not None else servers
        for decl in _declared_in_belt(
            raw, active_servers=enabled, repo_root=repo_root
        ):
            by_fold.setdefault(decl["name"].casefold(), decl)
    return list(by_fold.values())


def match_requires(requires: Any, available: Any) -> dict[str, list[str]]:
    """Match exacto case-insensitive. Una capacidad inventada queda faltante."""
    req = [str(v).strip() for v in requires] if isinstance(requires, list) else []
    av = [str(v).strip() for v in available] if isinstance(available, list) else []
    by_fold = {v.casefold(): v for v in av if v}
    covered: list[str] = []
    missing: list[str] = []
    for capability in req:
        if not capability:
            continue
        target = covered if capability.casefold() in by_fold else missing
        if capability not in target:
            target.append(capability)
    return {"cubiertas": covered, "faltantes": missing}


def _missing_paths(missing: list[str], declarations: list[dict]) -> list[dict]:
    known = {d["name"].casefold(): d for d in declarations}
    out = []
    for capability in missing:
        decl = known.get(capability.casefold()) or {}
        inline = str(decl.get("resolution") or "").casefold() in {
            "inline_key", "solo_llave", "key", "llave",
        }
        out.append({
            "capacidad": capability,
            "accion": "Configurar llave" if inline else "Traer",
            "camino": "inline_key" if inline else "registro",
            **({"target": decl["target"]} if decl.get("target") else {}),
        })
    return out


def method_state(method: dict, config: dict, repo_root: Path = REPO_ROOT) -> dict:
    # Null/ausente es legado pendiente de extractor, jamás equivalente a [].
    if not isinstance(method.get("requires"), list):
        return {
            "cubiertas": [],
            "faltantes": ["clasificación de capacidades pendiente"],
            "estado": "huecos",
            "semaforo": "detectado",
            "detail": "le falta clasificar requires[]",
            "resoluciones": [],
        }
    declarations = belt_capability_declarations(config, repo_root)
    result = match_requires(method.get("requires"), [d["name"] for d in declarations])
    missing = result["faltantes"]
    return {
        **result,
        "estado": "huecos" if missing else "completo",
        "semaforo": "detectado" if missing else "probado",
        "detail": (
            f"le faltan {len(missing)} capacidades" if missing
            else "todas las capacidades están cubiertas"
        ),
        "resoluciones": _missing_paths(missing, capability_declarations(repo_root)),
    }


def state_fingerprint(method: dict, config: dict) -> str:
    payload = {
        "requires": method.get("requires"),
        "belt": (config or {}).get("belt"),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]


def _method_refs(config: dict) -> list[str]:
    belt = config.get("belt") if isinstance(config.get("belt"), dict) else {}
    refs = belt.get("method_refs")
    return [str(v) for v in refs if isinstance(v, str)] if isinstance(refs, list) else []


def recalculate(conn, puppet: dict, *, owner: str,
                repo_root: Path = REPO_ROOT) -> list[dict]:
    """Recalcula y persiste el semáforo P11 para el belt ACTUAL del agente."""
    from app.phase1 import methods_repo as mr
    from app.phase1 import motor_verdad

    config = puppet.get("config") if isinstance(puppet.get("config"), dict) else {}
    refs = _method_refs(config)
    enriched: list[dict] = []
    keep: set[str] = set()
    for ref in refs:
        method = mr.get_method(conn, ref, owner)
        if not method:
            continue
        state = method_state(method, config, repo_root)
        motor_verdad.guardar_estado_metodo(
            str(puppet.get("id") or ""), str(method["id"]), owner=owner,
            estado_metodo=state, huella=state_fingerprint(method, config),
        )
        keep.add(str(method["id"]))
        enriched.append({**method, "equipment": state})
    motor_verdad.olvidar_estados_metodo(
        str(puppet.get("id") or ""), owner=owner, conservar=keep)
    return enriched


def eligible_for_sala(methods: list[dict]) -> list[dict]:
    """El semáforo ES gate: sólo completos pueden llegar al matcher contextual."""
    return [
        method for method in methods
        if (method.get("equipment") or {}).get("estado") == "completo"
    ]
