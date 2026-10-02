"""
loop/emit.py — Capa 5 · el Emisor · VERIFIED → MCP forjado DESDE CERO.

Entrada: SOLO tools VERIFIED (lo fuerza el tipo). Salida: un MCP real y equipable,
construido enteramente desde la corrida viva — sin partir de ningún config ni
catálogo previo (gap #1). Tres artefactos en la carpeta AISLADA por-principal:

  • `<slug>.forge.json`     — el spec del MCP: base_url + auth_param + cred_ref +
                              las N tools de lectura verificadas (con su sample_call).
  • `belt-<slug>.mcp.json`  — el belt equipable, MISMA forma del catálogo
                              (`_meta.cards` + `mcpServers`) que el assembler ya
                              consume. Lanza `forged_mcp_server.py`.
  • (la credencial)         — ya cifrada por la sesión (Fernet) en `credentials.enc`
                              del mismo dir; el manifest la referencia por
                              PLACEHOLDER (cred_ref), NUNCA en claro (cierra CASO D).

Regla de zona (C3): todo read → Fuentes. No ejecuta nada; empaqueta lo que el
candado dejó pasar.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional, Sequence

_PLATFORM = Path(__file__).resolve().parents[2]
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection import contracts as C  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SERVER = Path(__file__).resolve().parent / "forged_mcp_server.py"


class MCPEmitter:
    """Capa 5. Satisface el Protocol C.Emitter. Forja en la carpeta por-principal."""

    def __init__(
        self,
        principal: C.Principal,
        slug: str,
        base_url: str,
        *,
        auth_param: str = "api_key",
        cred_name: str = "API_KEY",
        auth_spec: Optional[dict] = None,
        cred_root: Path = C.SYNTH_BELTS_DIR,
        niche: str = "synthesized-live",
        min_interval: float = 0.0,
    ):
        self.principal = principal
        self.slug = slug
        self.base_url = base_url.rstrip("/")
        self.auth_param = auth_param
        self.cred_name = cred_name
        # CÓMO se autentica el MCP forjado (Forma 1 query · Forma 2/3 header/cookie).
        # None → Forma 1 (token en query): el bloque queda byte-idéntico al de siempre.
        self.auth_spec = auth_spec
        self.cred_root = cred_root
        self.niche = niche
        self.min_interval = min_interval
        self.out_dir = C.credential_dir(principal, slug, root=cred_root)

    def emit(self, verified: Sequence[C.VerifiedTool]) -> C.ForgedMCP:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        server_name = f"forged-{self.slug}"
        namespace = C.credential_namespace(self.principal)
        cred_file = self.out_dir / "credentials.enc"

        tools_spec = []
        cards: list[C.BeltCard] = []
        tool_names: list[str] = []
        for vt in verified:
            c = vt.candidate
            is_write = c.kind is C.ToolKind.WRITE
            schema = dict(c.input_schema or {})
            sample = schema.pop("x-sample-call", None)   # el sample queda como hint del server
            schema.pop("x-dry-run", None)                # hint del validador, no del server forjado
            tools_spec.append({
                "name": c.name,
                "endpoint": c.endpoint,
                "method": c.method,
                "kind": "write" if is_write else "read",
                # §7: la write toca el mundo → el server forjado la emite GATED (no ejecuta
                # directo; exige el gate humano visible antes de pegar la mutación).
                "gated": is_write,
                "description": c.description or (
                    f"Escritura verificada por forma ({vt.verified_by}) de {c.endpoint} — GATED."
                    if is_write else f"Lectura verificada de {c.endpoint}."),
                "input_schema": schema or {"type": "object", "properties": {}},
                "sample_call": sample or {},
                "verified_by": vt.verified_by,
            })
            tool_names.append(c.name)
            cards.append(C.BeltCard(
                id=c.name, label=_label(c.name), tool=c.name,
                # C3: read → Fuentes; write → Entrega (la zona que toca el mundo, gateada).
                zone="entrega" if is_write else "fuentes",
                backed_by=server_name,
            ))

        # 1 · el spec del MCP forjado (la fuente del server).
        auth_block = self._auth_block(namespace)
        forge_spec = {
            "_forged": True,
            "forged_from": "live-inspection-loop (§3)",
            "base_url": self.base_url,
            "auth": auth_block,
            "tools": tools_spec,
        }
        forge_path = self.out_dir / f"{self.slug}.forge.json"
        forge_path.write_text(json.dumps(forge_spec, ensure_ascii=False, indent=2), encoding="utf-8")

        # 2 · el belt equipable (forma del catálogo; el secreto va por vault, no acá).
        _auth_word = {"query": "token-query", "header": "session-header",
                      "cookie": "session-cookie"}.get(auth_block["in"], "token-query")
        n_write = sum(1 for cd in cards if cd.zone == "entrega")
        n_read = len(tool_names) - n_write
        _que_es = (f"MCP forjado en vivo desde {self.base_url} "
                   f"({n_read} read · {n_write} write GATED)." if n_write
                   else f"MCP de lectura forjado en vivo desde {self.base_url} ({len(tool_names)} tools).")
        belt = {
            "_meta": {
                "belt": self.slug,
                "slug": self.slug,
                "que_es": _que_es,
                "synthesized": True,
                "forged_live": True,
                "source": {"base_url": self.base_url, "tools": len(tool_names),
                           "read": n_read, "write_gated": n_write},
                "cards": [{
                    "id": cd.id, "label": cd.label,
                    # §7: la write se rotula honesta — WRITE · gated. La UI muestra el gate.
                    "sub": (f"forjada en vivo · WRITE · gated · {self.base_url}" if cd.zone == "entrega"
                            else f"forjada en vivo · read · {self.base_url}"),
                    "auth": f"{_auth_word} (vault)", "armario": "apps",
                    "zone": cd.zone, "backed_by": cd.backed_by, "tools": [cd.tool],
                    "gated": cd.zone == "entrega",   # gate humano visible antes de tocar el mundo
                } for cd in cards],
            },
            "mcpServers": {
                server_name: {
                    "command": "python3",
                    "args": [str(_SERVER)],
                    "env": {
                        "FORGE_SPEC": str(forge_path),
                        "FORGE_CRED_FILE": str(cred_file),   # vault Fernet (no plaintext)
                        "FORGE_EXECUTE": "1",                # reads son seguros de ejecutar
                        "FORGE_MIN_INTERVAL": str(self.min_interval),  # pacing (AV=1 req/seg)
                    },
                    "caso": 1,
                    "bucket": "B1",
                    "nichos": [self.niche],
                    "credenciales": f"{_auth_word} (vault Fernet)",
                    "atomica": False,
                    "description": (f"MCP forjado en vivo · {n_read} lectura · {n_write} escritura GATED."
                                    if n_write else f"MCP forjado en vivo · {len(tool_names)} tools de lectura."),
                }
            },
        }
        belt_path = self.out_dir / f"belt-{self.slug}.mcp.json"
        belt_path.write_text(json.dumps(belt, ensure_ascii=False, indent=2), encoding="utf-8")

        belt_ref = _rel_to_repo(belt_path)
        return C.ForgedMCP(
            server_name=server_name,
            belt_ref=belt_ref,
            tools=tuple(tool_names),
            cards=tuple(cards),
        )


    def _auth_block(self, namespace: str) -> dict:
        """El bloque `auth` del forge_spec. Forma 1 (query) → byte-idéntico al de siempre.
        Forma 2/3 → header (con template) o cookie, para que el server forjado inyecte la
        credencial del vault como corresponde (no como query)."""
        cred_ref = f"{namespace}/{self.slug}#{self.cred_name}"
        spec = self.auth_spec or {}
        where = spec.get("in", "query")
        if where == "header":
            return {"in": "header", "name": spec.get("name", "Authorization"),
                    "template": spec.get("template", "Bearer {token}"),
                    "cred_ref": cred_ref, "cred_name": self.cred_name}
        if where == "cookie":
            return {"in": "cookie", "name": spec.get("name", "session"),
                    "cred_ref": cred_ref, "cred_name": self.cred_name}
        # query (Forma 1) — mismo orden de claves que antes del wire.
        return {"param": spec.get("param", self.auth_param), "in": "query",
                "cred_ref": cred_ref, "cred_name": self.cred_name}


def _label(name: str) -> str:
    return name.replace("_", " ").strip().capitalize() or name


def _rel_to_repo(p: Path) -> str:
    try:
        return str(p.relative_to(_REPO_ROOT))
    except ValueError:
        return str(p)


# ══════════════════════════════════════════════════════════════════════════════
# Capa 5 · el camino del AGENTE — PARALELO al de tools (MCPEmitter), NO lo toca.
# ──────────────────────────────────────────────────────────────────────────────
# Donde MCPEmitter forja un MCP (mcpServers{} + belt_refs[]) desde tools VERIFIED,
# AgentEmitter «forja» un sub-agente: deja su receta hija lista para equipar como
# `belt.agent_refs[]` (NUNCA belt_refs[] — regla load-bearing paso 1/5) y escribe el
# belt-agent manifest con `agentServers{}`, el descriptor PARALELO a `mcpServers{}`.
#
# Un agente NO se «descubre» como una tool (no se sondea un endpoint): la receta
# hija YA existe (un agente equipable es una receta-agente que existe). Por eso el
# emisor no sintetiza ni valida vivo — referencia/persiste lo verificado. La
# DISCOVERY del agente (de dónde sale el catálogo de agentes) es un sistema aparte.
# ══════════════════════════════════════════════════════════════════════════════
def _agent_slug(va: "C.VerifiedAgent") -> str:
    """Slug estable del sub-agente: del nombre del archivo del agent_ref, si no del
    meta.name. Paralelo a cómo MCPEmitter recibe su slug."""
    ref = (va.candidate.agent_ref or "").strip()
    name = Path(ref).name if ref else ""
    for suf in (".config.json", ".json"):
        if name.endswith(suf):
            name = name[: -len(suf)]
            break
    if name:
        return name.replace("_", "-")
    meta = va.recipe.get("meta") if isinstance(va.recipe, dict) else None
    raw = (meta or {}).get("name") or "subagente"
    return "".join(ch if ch.isalnum() else "-" for ch in str(raw)).strip("-").lower() or "subagente"


class AgentEmitter:
    """Capa 5 (camino agente). Satisface el Protocol C.AgentEmitter. Equipa
    sub-agentes en la carpeta por-principal: NO forja un MCP — referencia/persiste
    la receta hija y escribe el descriptor `agentServers{}`."""

    def __init__(
        self,
        principal: "C.Principal",
        slug: str,
        *,
        cred_root: Path = C.SYNTH_BELTS_DIR,
    ):
        self.principal = principal
        self.slug = slug
        self.cred_root = cred_root
        self.out_dir = C.credential_dir(principal, slug, root=cred_root)

    def emit_agent(self, verified: Sequence["C.VerifiedAgent"]) -> tuple["C.ForgedAgent", ...]:
        if not verified:
            return ()
        self.out_dir.mkdir(parents=True, exist_ok=True)
        out: list[C.ForgedAgent] = []
        for va in verified:
            child_slug = _agent_slug(va)
            agent_name = f"agent-{child_slug}"
            meta = va.recipe.get("meta") if isinstance(va.recipe, dict) else {}
            meta = meta or {}

            # recipe_ref = lo que aterriza en belt.agent_refs[]. Si la receta YA vive en
            # disco bajo el repo, se referencia tal cual (sin duplicar); si vino inline, se
            # PERSISTE en la carpeta por-principal y se referencia esa copia.
            if va.source_ref:
                recipe_ref = va.source_ref
            else:
                recipe_path = self.out_dir / f"{child_slug}.recipe.json"
                recipe_path.write_text(
                    json.dumps(va.recipe, ensure_ascii=False, indent=2), encoding="utf-8")
                recipe_ref = _rel_to_repo(recipe_path)

            # el belt-agent manifest: `agentServers{}` PARALELO a `mcpServers{}` (descriptor
            # aditivo). El cableado load-bearing es recipe_ref→agent_refs[]; este manifest es
            # el lado «físico» simétrico al belt-<slug>.mcp.json de las tools.
            manifest = {
                "_meta": {
                    "belt": child_slug,
                    "slug": child_slug,
                    "agent": True,
                    "que_es": (f"Sub-agente equipable «{meta.get('name') or child_slug}» — "
                               f"se delega como agent_ref (no inlinea tools)."),
                    "forged_agent": True,
                    "source": {"agent_ref": va.candidate.agent_ref, "recipe_ref": recipe_ref,
                               "verified_by": va.verified_by},
                    "cards": [{
                        "id": agent_name,
                        "label": meta.get("name") or _label(child_slug),
                        "sub": f"sub-agente · delega · {meta.get('nicho') or 'agente'}",
                        "kind": "agent",
                        "armario": "agentes",
                        "agent_ref": recipe_ref,
                    }],
                },
                "agentServers": {
                    agent_name: {
                        "type": "agent",
                        "recipe_ref": recipe_ref,
                        "agent_ref": va.candidate.agent_ref,
                        "nicho": meta.get("nicho") or "",
                        "delegates": True,
                        "description": meta.get("descripcion") or meta.get("description")
                        or f"sub-agente equipado: {meta.get('name') or child_slug}",
                    }
                },
            }
            manifest_path = self.out_dir / f"belt-{child_slug}.agent.json"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

            out.append(C.ForgedAgent(
                agent_name=agent_name,
                recipe_ref=recipe_ref,
                agent_ref=va.candidate.agent_ref,
                manifest_ref=_rel_to_repo(manifest_path),
            ))
        return tuple(out)


# resolución equip-time de un agent_ref → VerifiedAgent. ESPEJA el orden de candidatos de
# `belt_resolver.resolve_agent_ref` (paso 1, el resolver CANÓNICO en run-time) para que el
# recipe_ref que producimos sea re-resolvible por el paso 1/2. El check v1 acá es el mismo
# «check estructural ligero» del paso 1; la validación PROFUNDA es validate_recipe (paso 2).
def _resolve_recipe_file(agent_ref: str, repo_root: Path) -> Path:
    repo_root = Path(repo_root)
    name = Path(agent_ref).name
    child_slug = name
    for suf in (".config.json", ".json"):
        if child_slug.endswith(suf):
            child_slug = child_slug[: -len(suf)]
            break

    def _cand(p: Path) -> Path:
        return p if p.is_absolute() else (repo_root / p)

    candidates: list[Path] = []
    if agent_ref.endswith(".json"):
        candidates.append(_cand(Path(agent_ref)))
    candidates.append(repo_root / "catalog" / "agents" / f"{child_slug}.json")
    candidates.append(repo_root / "catalog" / "agents" / f"{child_slug}.config.json")
    if not agent_ref.endswith(".json"):
        candidates.append(_cand(Path(agent_ref)))

    for cand in candidates:
        if cand.exists() and cand.is_file():
            return cand
    raise ValueError(
        f"agent_ref '{agent_ref}' no resuelve a una receta-agente. Probado: "
        + ", ".join(str(c) for c in candidates))


def verify_agent_ref(agent_ref: str, repo_root: Path, *,
                     name: str = "", description: str = "") -> "C.VerifiedAgent":
    """EQUIP-TIME: resuelve + valida la forma v1 de un agent_ref y devuelve un
    VerifiedAgent listo para AgentEmitter.emit_agent(). Levanta ValueError si no
    resuelve o no es una receta v1 (schema_version=='v1' + meta + belt)."""
    path = _resolve_recipe_file(agent_ref, repo_root)
    try:
        recipe = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"agent_ref '{agent_ref}' no se pudo leer/parsear: {exc}") from exc

    problems: list[str] = []
    if not isinstance(recipe, dict):
        problems.append("la receta-agente debe ser un objeto JSON")
    else:
        if recipe.get("schema_version") != "v1":
            problems.append(f"schema_version debe ser 'v1' (recibido {recipe.get('schema_version')!r})")
        if not isinstance(recipe.get("meta"), dict):
            problems.append("falta `meta`")
        if not isinstance(recipe.get("belt"), dict):
            problems.append("falta `belt`")
    if problems:
        raise ValueError(f"agent_ref '{agent_ref}' no es una receta v1: " + "; ".join(problems))

    return C.VerifiedAgent(
        candidate=C.CandidateAgent(agent_ref=agent_ref, name=name, description=description),
        recipe=recipe,
        source_ref=_rel_to_repo(path),
        verified_by="v1-shape",
    )
