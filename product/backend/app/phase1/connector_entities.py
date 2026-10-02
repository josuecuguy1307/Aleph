"""Entidad Conector: un servicio humano, uno o más servidores MCP internos.

La fuente histórica de la vitrina eran dos poblaciones:

* MCPs plegados por ``server`` desde ``/v1/atoms/catalog``;
* conectores de cuenta de ``catalog/connectors/onboarding``.

Eso produjo el caso índice FRED: un servidor con 5 tools y, aparte, una fila de
credencial con 0 tools. Esta proyección migra ambas poblaciones por SERVICIO. La
credencial cuelga de la entidad y cada servidor conserva origen, transporte,
tools y estado interno.

La deduplicación jamás usa el nombre desnudo del server. Primero se asigna cada
card a un servicio (``service``/``credential_provider``/``connector``); recién
dentro de esa entidad se pliegan apariciones del mismo server. Así un MCP que
respalda servicios distintos no los mezcla.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Optional

try:
    import aleph_paths as _ap
except ImportError:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "platform"))
    import aleph_paths as _ap

_ROOT = _ap.resource_root()
_ONB = _ROOT / "catalog" / "connectors" / "onboarding"
_CONFIG = _ROOT / "catalog" / "connectors" / "entities.json"
_DIORAMA_CONFIG = _ROOT / "product" / "app" / "design" / "cuarto" / "diorama-symbols.json"
_NATIVE_SERVERS = frozenset({"calc", "time", "sympy", "units"})
_SAFE_TOOL = re.compile(r"[^A-Za-z0-9_-]+")
DIORAMA_SYMBOLS = frozenset({
    "buscar",
    "leer",
    "escribir",
    "datos",
    "codigo",
    "media",
    "comunicacion",
    "almacenamiento",
    "calculo",
    "generico",
})


def _load_config() -> dict:
    try:
        data = json.loads(_CONFIG.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _load_diorama_config() -> dict:
    try:
        data = json.loads(_DIORAMA_CONFIG.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _profiles() -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not _ONB.is_dir():
        return out
    for path in sorted(_ONB.glob("*.json")):
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        provider = str(obj.get("connector") or path.stem).strip().lower()
        if provider:
            out[provider] = obj
    return out


def _title(value: str) -> str:
    words = re.sub(r"[_-]+", " ", value or "").strip().split()
    acronyms = {"api", "cad", "ccxt", "edgar", "fred", "mcp", "orcid", "sec", "sql"}
    brands = {
        "alphavantage": "Alpha Vantage",
        "arxiv": "arXiv",
        "biomcp": "BioMCP",
        "coingecko": "CoinGecko",
        "dicom": "DICOM",
        "duckduckgo": "DuckDuckGo",
        "fem": "FEM",
        "freecad": "FreeCAD",
        "github": "GitHub",
        "globalfishingwatch": "Global Fishing Watch",
        "huggingface": "Hugging Face",
        "kicad": "KiCad",
        "maad": "MAAD",
        "materialsproject": "Materials Project",
        "openalex": "OpenAlex",
        "openfda": "OpenFDA",
        "openfoam": "OpenFOAM",
        "opensanctions": "OpenSanctions",
        "pubmed": "PubMed",
        "pysandbox": "PySandbox",
        "secedgar": "SEC EDGAR",
        "spice": "SPICE",
        "sqlite": "SQLite",
        "yfinance": "yfinance",
    }
    return " ".join(
        brands.get(w.lower(), w.upper() if w.lower() in acronyms else w[:1].upper() + w[1:])
        for w in words
    )


def _canonical(value: Optional[str], aliases: dict[str, str]) -> str:
    current = str(value or "").strip().lower()
    seen: set[str] = set()
    while current and current in aliases and current not in seen:
        seen.add(current)
        current = str(aliases[current]).strip().lower()
    return current


def _diorama_symbol(value: Any) -> str:
    """Enum cerrado para la cara funcional de las piezas del Cuarto."""
    symbol = str(value or "").strip().lower()
    return symbol if symbol in DIORAMA_SYMBOLS else "generico"


def _service_for(atom: dict, aliases: dict[str, str]) -> str:
    explicit = atom.get("service") or atom.get("credential_provider")
    connector = explicit or atom.get("connector") or atom.get("origin_connector")
    return _canonical(connector or atom.get("server") or atom.get("id"), aliases)


def _origen_byo(server_cfg: dict) -> dict:
    """El origen que el usuario TRAJO, tal como el belt forjado lo escribe.

    Una pieza BYO se LANZA por nuestro puente —un proceso stdio— pero no nació ahí: el belt
    guarda su transporte y su URL reales un nivel adentro, bajo ``byo``. Leer sólo el nivel
    de arriba le contaba al usuario NUESTRA implementación («stdio») como si fuera su
    decisión, sobre una pieza que él trajo pegando una URL HTTP.
    """
    byo = server_cfg.get("byo")
    return dict(byo) if isinstance(byo, dict) else {}


def _transport(server_cfg: dict) -> str:
    byo = _origen_byo(server_cfg)
    declared = str(server_cfg.get("transport") or byo.get("transport") or "").lower()
    if server_cfg.get("url") or byo.get("url") or declared in {"http", "sse", "streamable-http"}:
        return "http"
    return "stdio"


def _raices_de_belts(owner: Optional[str] = None) -> list:
    """Las raíces contra las que un ``belt_ref`` puede resolver, importadas de donde SALEN.

    No es una copia: es la misma lista que produjo el ``belt_ref`` en
    ``atoms_router._raices_de_belts`` (el repo/bundle + el ``synth_belts`` del dueño). Dos
    listas separadas se desincronizan a la primera raíz nueva; ésta no puede — y por eso
    ``owner`` viaja hasta acá: desde A1 el walk es POR CUENTA, y una proyección que
    resolviera contra la raíz entera volvería a abrir la fuga por la puerta de atrás,
    leyendo el belt de otra cuenta para completar el origen de una pieza.
    Import perezoso para no atar el orden de carga de los módulos de phase1.
    """
    try:
        from app.phase1.atoms_router import _raices_de_belts as _raices
        return [(d, raiz) for d, raiz in _raices(owner)]
    except Exception:  # noqa: BLE001 — sin el router, queda la raíz histórica
        return [(_ROOT, _ROOT)]


def _server_cfg(belt_ref: str, server: str, owner: Optional[str] = None) -> dict:
    """La config REAL del server que respalda esta card, buscada en TODAS sus raíces.

    ⚠️ ANCLABA SÓLO AL REPO, y un belt del usuario no vive en el repo: vive en
    ``data_root()/synth_belts/<user>/…`` — la forma portable que ya persiste
    ``conexion.belt_ref``. Efecto medido en la app instalada: ``{}`` para TODA pieza
    traída, así que la entidad entraba sin ``command``, sin ``args``, sin origen y
    declarando ``stdio`` sobre algo que el usuario había traído por HTTP. Misma clase de
    bug que la Obra 6d: el dato viaja bien, el código lo busca contra la raíz equivocada.

    LA PUERTA SIGUE CERRADA. Abrir una raíz más no abre el disco: cada candidato tiene que
    caer DENTRO de la raíz que le tocó, así que un ``../..`` o una ruta absoluta no
    resuelven por ninguna de las dos.
    """
    for _dir, raiz in _raices_de_belts(owner):
        try:
            path = (raiz / belt_ref).resolve()
            base = raiz.resolve()
            if base != path and base not in path.parents:
                continue
            obj = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        cfg = dict((obj.get("mcpServers") or {}).get(server) or {})
        if cfg:
            return cfg
    return {}


def _safe_prefix(server: str) -> str:
    value = _SAFE_TOOL.sub("_", str(server or "server")).strip("_")
    return value or "server"


def stable_tool_aliases(servers: Iterable[dict]) -> dict[str, dict[str, str]]:
    """Alias final por ``server/raw_tool``.

    Regla pública y determinista:
      * un nombre que aparece en un solo servidor queda igual;
      * si aparece en dos o más, TODOS los colisionantes se publican como
        ``<servidor>__<tool>``.

    Prefijar a todos evita que el resultado dependa del orden de los belts. Los
    filtros y gates siguen usando el nombre crudo; el alias sólo es la superficie
    expuesta al modelo/usuario.
    """
    rows = list(servers or [])
    counts = Counter(
        str(tool)
        for server in rows
        for tool in (server.get("tools") or [])
    )
    out: dict[str, dict[str, str]] = {}
    used: set[str] = set()
    for server in sorted(rows, key=lambda s: str(s.get("name") or "")):
        name = str(server.get("name") or "")
        mapping: dict[str, str] = {}
        for raw in server.get("tools") or []:
            raw = str(raw)
            final = f"{_safe_prefix(name)}__{raw}" if counts[raw] > 1 else raw
            if final in used:
                raise ValueError(
                    f"colisión de alias final en {name!r}: {final!r}; "
                    "los nombres de servidor de una entidad deben ser únicos"
                )
            mapping[raw] = final
            used.add(final)
        out[name] = mapping
    return out


def assert_unique_logos(entities: Iterable[dict]) -> None:
    """Guarda dura: dos filas visibles no pueden compartir logo."""
    seen: dict[str, str] = {}
    for entity in entities:
        logo = str(entity.get("logo") or "").strip().lower()
        if not logo:
            continue
        previous = seen.get(logo)
        if previous and previous != entity.get("id"):
            raise ValueError(
                f"logo duplicado {logo!r}: entidades {previous!r} y "
                f"{entity.get('id')!r}"
            )
        seen[logo] = str(entity.get("id"))


def _proveedor_por_defecto(providers: set, service: str) -> str:
    """De quién es la credencial cuando la card pide llave y no dice de quién.

    ⚠️ ESTO NO ES UN DEFAULT COSMÉTICO. Era ``sorted(providers)[0]`` sobre un conjunto que
    puede estar VACÍO, y entonces una sola card así mataba la proyección ENTERA:
    ``IndexError`` → 500 en ``/v1/connector-entities`` → El Cuarto sin su catálogo, ni el
    traído ni el de la caja. Medido en la app instalada con los datos reales: 32 piezas
    forjadas lo disparaban. **Una pieza mala no puede tumbar el catálogo** — el resto del
    inventario no es rehén de la peor fila.

    Si nadie declara proveedor, el proveedor ES EL SERVICIO: el nombre canónico que
    ``build_entities`` ya derivó de la propia pieza. No se inventa un tercero ni se le
    cuelga la credencial a un vecino: la llave queda a nombre de quien la pide.
    """
    return sorted(providers)[0] if providers else service


def _description(atoms: list[dict], profile: Optional[dict], override: dict,
                 official_atoms: list[dict]) -> str:
    if official_atoms:
        candidates = [str(a.get("sub") or "").strip() for a in official_atoms]
        return max((s for s in candidates if s), key=len, default="")
    if override.get("description"):
        return str(override["description"]).strip()
    candidates = [str((profile or {}).get("capability_line") or "").strip()]
    candidates.extend(str(a.get("sub") or "").strip() for a in atoms)
    return max((s for s in candidates if s), key=len, default="")


def _entity_name(service: str, atoms: list[dict], override: dict,
                 official_atoms: list[dict]) -> str:
    if official_atoms:
        return str(official_atoms[0].get("label") or _title(service)).strip()
    if override.get("name"):
        return str(override["name"]).strip()
    # El id canónico es el servicio; evita nombres de paquete/ruta/UUID.
    return _title(service)


def _build_servers(service: str, atoms: list[dict], credential: Optional[dict],
                   owner: Optional[str] = None) -> list[dict]:
    by_name: dict[str, dict] = {}
    for atom in atoms:
        name = str(atom.get("server") or "").strip()
        belt_ref = str(atom.get("belt_ref") or "").strip()
        if not name or not belt_ref:
            continue
        row = by_name.get(name)
        if row is None:
            cfg = _server_cfg(belt_ref, name, owner)
            raw_provider = str(
                atom.get("origin_connector") or atom.get("connector") or ""
            ).strip() or None
            row = {
                "id": f"{service}:{name}",
                "name": name,
                "belt_ref": belt_ref,
                "origin": {
                    "belt_ref": belt_ref,
                    "command": cfg.get("command"),
                    "args": list(cfg.get("args") or []),
                    "url": cfg.get("url") or _origen_byo(cfg).get("url"),
                    "cards": [],
                },
                "transport": _transport(cfg),
                "tools": [],
                "connector": raw_provider,
                "credential_provider": (
                    str((credential or {}).get("provider") or "").strip() or None
                ),
                "state": atom.get("state"),
                "runtime": atom.get("runtime"),
                "requires": list(atom.get("requires") or []),
                "runtime_detail": atom.get("runtime_detail"),
                "official": bool(atom.get("official")),
            }
            by_name[name] = row
        for tool in atom.get("tools") or []:
            if tool not in row["tools"]:
                row["tools"].append(tool)
        card_id = atom.get("id")
        if card_id and card_id not in row["origin"]["cards"]:
            row["origin"]["cards"].append(card_id)
        if not row.get("connector"):
            row["connector"] = atom.get("origin_connector") or atom.get("connector")

    servers = sorted(by_name.values(), key=lambda s: s["name"])
    aliases = stable_tool_aliases(servers)
    for server in servers:
        server["tool_aliases"] = aliases.get(server["name"], {})
        server["tools_final"] = [
            server["tool_aliases"].get(raw, raw) for raw in server["tools"]
        ]
        canonical = (credential or {}).get("provider")
        runtime_provider = server.get("connector") or canonical
        server["credential_binding"] = (
            {
                "runtime_provider": runtime_provider,
                "credential_provider": canonical,
            }
            if canonical and runtime_provider
            else None
        )
    return servers


def build_entities(atoms: Iterable[dict], *, key_rows: Optional[Iterable[dict]] = None,
                   owner: Optional[str] = None) -> dict:
    """Proyecta cards+onboarding a entidades visibles y un ledger de migración."""
    cfg = _load_config()
    aliases = {
        str(k).lower(): str(v).lower()
        for k, v in (cfg.get("aliases") or {}).items()
    }
    overrides = cfg.get("services") or {}
    diorama_services = (_load_diorama_config().get("services") or {})
    profiles = _profiles()
    keys = {
        str(row.get("provider") or "").lower(): dict(row)
        for row in (key_rows or [])
        if row and row.get("provider")
    }

    material = [
        dict(atom)
        for atom in (atoms or [])
        if atom and atom.get("server") not in _NATIVE_SERVERS
    ]
    grouped: dict[str, list[dict]] = {}
    for atom in material:
        service = _service_for(atom, aliases)
        if not service:
            continue
        grouped.setdefault(service, []).append(atom)

    entities: list[dict] = []
    used_profiles: set[str] = set()
    merge_rows: list[dict] = []
    for service in sorted(grouped):
        members = grouped[service]
        override = dict(overrides.get(service) or {})
        credential_override = dict(override.get("credential") or {})

        providers = {
            str(a.get("credential_provider") or a.get("connector") or "").strip().lower()
            for a in members
            if a.get("credential_provider") or a.get("connector")
        }
        providers |= {
            p for p in profiles if _canonical(p, aliases) == service
        }
        canonical_provider = str(
            credential_override.get("provider")
            or (service if service in profiles else "")
        ).strip().lower()
        profile = profiles.get(
            str(credential_override.get("connector") or canonical_provider).lower()
        )
        needs_credential = any(
            str(a.get("auth") or "keyless") != "keyless" for a in members
        )
        credential: Optional[dict] = None
        if needs_credential:
            provider = canonical_provider or _proveedor_por_defecto(providers, service)
            connector = str(
                credential_override.get("connector") or provider
            ).strip().lower()
            profile = profiles.get(connector) or profile
            key = keys.get(provider)
            credential = {
                "provider": provider,
                "connector": connector,
                "aliases": sorted(
                    set(credential_override.get("aliases") or [])
                    | {p for p in providers if p and p != provider}
                ),
                "auth_method": (profile or {}).get("auth_method")
                    or max(
                        (str(a.get("auth") or "keyless") for a in members),
                        key=lambda x: {"keyless": 0, "token": 1,
                                       "personal_token": 1, "oauth": 2}.get(x, 1),
                    ),
                "connected": bool(key),
                "last4": (key or {}).get("last4"),
                "connected_at": (key or {}).get("created_at"),
                "verified": (key or {}).get("verified"),
                "needs_base_url": bool((profile or {}).get("needs_base_url")),
            }
            used_profiles.add(connector)
            used_profiles.update(p for p in providers if p in profiles)

        official_atoms = [a for a in members if a.get("official")]
        servers = _build_servers(service, members, credential, owner)
        tool_count = sum(len(server["tools"]) for server in servers)
        tools = [
            {"name": final, "raw_name": raw, "server": server["name"]}
            for server in servers
            for raw, final in server["tool_aliases"].items()
        ]
        entity = {
            "id": service,
            "name": _entity_name(service, members, override, official_atoms),
            "description": _description(members, profile, override, official_atoms),
            "logo": str(override.get("logo") or service).strip().lower(),
            "diorama_symbol": _diorama_symbol(diorama_services.get(service)),
            "official": bool(official_atoms),
            "credential": credential,
            "servers": servers,
            "tools": tools,
            "tool_count": tool_count,
            "belt_refs": sorted({s["belt_ref"] for s in servers}),
            "zone": next((a.get("zone") for a in members if a.get("zone")), "mesa"),
            "armario": next((a.get("armario") for a in members if a.get("armario")), None),
            "criticality": (
                "high" if any(a.get("criticality") == "high" for a in members) else "low"
            ),
            "source_entries": [
                {
                    "kind": "mcp",
                    "id": a.get("id"),
                    "server": a.get("server"),
                    "belt_ref": a.get("belt_ref"),
                    "tools": len(a.get("tools") or []),
                    "migration_source": a.get("migration_source") or "legacy_card",
                }
                for a in members
            ],
        }
        if tool_count:
            entities.append(entity)
        merge_rows.append({
            "entity": service,
            "name": entity["name"],
            "merged": [
                f"mcp:{s['name']}@{s['belt_ref']}" for s in servers
            ],
            "credential": credential and credential["provider"],
            "tools": tool_count,
        })

    assert_unique_logos(entities)

    dormant = sorted(set(profiles) - used_profiles)
    legacy_servers = {
        str(a.get("server"))
        for a in material
        if (a.get("migration_source") or "legacy_card") != "server_declaration"
    }
    legacy_credentials = {
        p for p in profiles
        if p not in {
            str(a.get("origin_connector") or a.get("connector") or "").lower()
            for a in material
            if (a.get("migration_source") or "legacy_card") != "server_declaration"
            if a.get("origin_connector") or a.get("connector")
        }
    }
    legacy_tools = {
        (str(a.get("server")), str(tool))
        for a in material
        if (a.get("migration_source") or "legacy_card") != "server_declaration"
        for tool in (a.get("tools") or [])
    }
    source_tools = {
        (
            _service_for(a, aliases),
            str(a.get("server")),
            str(tool),
        )
        for a in material
        if a.get("server") and a.get("belt_ref")
        for tool in (a.get("tools") or [])
    }
    final_tools = {
        (str(entity["id"]), str(server["name"]), str(tool))
        for entity in entities
        for server in entity["servers"]
        for tool in server["tools"]
    }
    source_servers = {
        (_service_for(a, aliases), str(a.get("server")), str(a.get("belt_ref")))
        for a in material
        if a.get("server") and a.get("belt_ref")
    }
    final_servers = {
        (str(entity["id"]), str(server["name"]), str(server["belt_ref"]))
        for entity in entities
        for server in entity["servers"]
    }
    tools_lost = [
        {"entity": service, "server": server, "tool": tool}
        for service, server, tool in sorted(source_tools - final_tools)
    ]
    orphaned = [
        f"mcp:{server}@{belt_ref} -> service:{service or '<vacío>'}"
        for service, server, belt_ref in sorted(source_servers - final_servers)
    ]
    entity_ids = {str(entity["id"]) for entity in entities}
    credential_conversions = []
    for provider in sorted(legacy_credentials):
        service = _canonical(provider, aliases)
        credential_conversions.append({
            "legacy_entry": f"credential:{provider}",
            "provider": provider,
            "entity": service if service in entity_ids else None,
            "converted_to": (
                f"entity:{service}.credential"
                if service in entity_ids
                else f"credential_profile:{provider}"
            ),
            "visible_piece": False,
        })
    migration = {
        "legacy_entries": len(legacy_servers) + len(legacy_credentials),
        "legacy_mcp_entries": len(legacy_servers),
        "legacy_credential_entries": len(legacy_credentials),
        "server_declarations_promoted": sum(
            1 for a in material
            if a.get("migration_source") == "server_declaration"
        ),
        "entities": len(entities),
        "tools_before_visible": len(legacy_tools),
        "tools_before_declared": len(source_tools),
        "tools_after": len(final_tools),
        "tools_lost": tools_lost,
        "dormant_credentials": dormant,
        "credential_conversions": credential_conversions,
        "orphaned": orphaned,
        "merges": merge_rows,
    }
    if tools_lost or orphaned:
        raise AssertionError(
            "migración incompleta: "
            f"{len(tools_lost)} tools perdidas, {len(orphaned)} entradas huérfanas"
        )
    return {
        "schema_version": "1",
        "entities": entities,
        "total": len(entities),
        "credential_profiles": {
            "attached": sorted(used_profiles),
            "dormant": dormant,
        },
        "migration": migration,
    }


__all__ = [
    "DIORAMA_SYMBOLS",
    "assert_unique_logos",
    "build_entities",
    "stable_tool_aliases",
]
