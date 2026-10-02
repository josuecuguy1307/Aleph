"""
registry.py — FASE 5: la tool sintetizada → REGISTRADA en el puppet del usuario.

Cierra el tramo "nace tool → queda en su puppet" del loop usuario→agente:

  1. PERSISTE el belt sintetizado en una ubicación DURABLE y POR-USUARIO dentro del
     repo (product/backend/data/synth_belts/<user>/<slug>/). Queda como ref RELATIVA:
     el validador de receta rechaza paths absolutos del host (decisión B), así que el
     belt vive bajo el repo y se referencia relativo → portable y scopeado al user.

  2. lo AGREGA a `recipe.belt.belt_refs` del puppet (la composición dinámica de belts
     que el assembler ya soporta) + su `tool_filters`, SIN pisar lo que el puppet ya
     tenía (additivo, idempotente: si el belt_ref ya está, no duplica). Antes de
     guardar RE-VALIDA la receta resultante (verify-before-trust: nunca dejamos un
     puppet con una receta que no corre — si nuestro cambio la rompe, hacemos rollback).

Decoupled del paquete `app`: carga repo.py / recipe_validator.py por RUTA (importlib),
igual que bridge.py carga el event-store. NO toca el assembler de T5 (contrato §4.1:
nosotros ESCRIBIMOS belt_refs; la forma se coordina, no se redefine acá).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, Optional

# [Casa 2 · Fase 4 · carve] synthesize_belt (observe.emit_belt = FORGE) se importa LAZY en
# persist_belt (abajo): sólo la forja (inspect_run) llama persist_belt; el equip/curado no.

# platform/inspection/registry.py → repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]
_REPO_PY = _REPO_ROOT / "product" / "backend" / "app" / "phase1" / "repo.py"
_VALIDATOR_PY = _REPO_ROOT / "product" / "backend" / "app" / "phase1" / "recipe_validator.py"
# raíz DURABLE y por-usuario de los belts sintetizados (bajo el repo → ref relativa)
def _dir_datos(nombre: str) -> Path:
    """`<data_root>/<nombre>` — el dir de datos del USUARIO, no el árbol.
    ⚠️ EL BUNDLE ES SÓLO LECTURA (CLAUDE.md · clase ya pagada en synth_belts, el pin
    del sello y la caché del resolver). Bajo PyInstaller `_REPO_ROOT` cae dentro de
    `_MEIPASS`, el temp que se borra al cerrar: lo que se escriba ahí NO existe en el
    arranque siguiente. Todo lo que se ESCRIBE va al dir de datos del usuario.
    Cae al árbol sólo si `aleph_paths` no se puede importar (dev suelto): en frozen siempre
    resuelve, porque `aleph_paths` viaja en el bundle.
    """
    try:
        import aleph_paths
        return aleph_paths.data_root() / nombre
    except Exception:                    # noqa: BLE001
        return _REPO_ROOT / "product" / "backend" / "data" / nombre

SYNTH_BELTS_DIR = _dir_datos("synth_belts")


def durable_belt_ref(path: Path) -> str:
    """Ref portable de un belt escrito en ``data_root()/synth_belts``.

    La ref conserva ``synth_belts/...`` y cambia sólo el ancla de resolución: el
    assembler/validador la prueban contra ``data_root`` antes de conservar el camino
    histórico contra el repo. Nunca persiste la ruta absoluta del host o de ``_MEIPASS``.
    """
    belt_path = Path(path).resolve()
    data_root = SYNTH_BELTS_DIR.resolve().parent
    try:
        return str(belt_path.relative_to(data_root))
    except ValueError as exc:
        raise ValueError(f"belt sintetizado fuera de data_root: {belt_path}") from exc


def _load_module(path: Path, mod_name: str):
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"no se pudo cargar {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_repo_mod = None
_val_mod = None


def repo():
    """Carga perezosa de repo.py (el repositorio fino sobre Postgres puppet_ai)."""
    global _repo_mod
    if _repo_mod is None:
        _repo_mod = _load_module(_REPO_PY, "puppet_repo_inspection")
    return _repo_mod


def validator():
    """Carga perezosa del recipe_validator (el contrato de receta v1)."""
    global _val_mod
    if _val_mod is None:
        _val_mod = _load_module(_VALIDATOR_PY, "puppet_recipe_validator_inspection")
    return _val_mod


# ── 1) persistir el belt en su lugar durable por-usuario ────────────────────────

def belt_dir_for(user_id: Optional[str], slug: str) -> Path:
    uid = (user_id or "anon").strip() or "anon"
    return SYNTH_BELTS_DIR / uid / slug


def persist_belt(spec: dict[str, Any], *, user_id: Optional[str],
                 niche: str = "synthesized") -> dict[str, Any]:
    """
    Escribe (belt.mcp.json + spec.json) en la carpeta durable del user y devuelve la
    info de registro, con `belt_ref` ya como string RELATIVO al repo (lo que va a la
    receta). Reusa synthesize_belt (FASE 4) — misma forma de belt del catálogo.
    """
    from inspection.observe.emit_belt import synthesize_belt   # [carve] FORGE, lazy
    slug = (spec.get("mcp_tool", {}).get("name") or "tool").replace("_", "-")
    out_dir = belt_dir_for(user_id, slug)
    art = synthesize_belt(spec, out_dir=out_dir, niche=niche)
    belt_path = Path(art["belt_path"]).resolve()
    belt_ref = durable_belt_ref(belt_path)
    return {
        "belt_ref": belt_ref,
        "belt_path": str(belt_path),
        "spec_path": str(art["spec_path"]),
        "server_name": art["server_name"],
        "tool_name": art["tool_name"],
        "belt": art["belt"],
        "slug": slug,
    }


# ── 2) registrar el belt_ref en la receta del puppet (additivo + validado) ──────

def _merge_belt_into_config(config: dict[str, Any], belt_ref: str,
                            server_name: str, tool_name: str) -> tuple[dict, bool]:
    """
    Devuelve (nuevo_config, ya_estaba). Additivo: no pisa belt/tool_filters previos.

    Usa la COMPOSICIÓN DINÁMICA `belt.belt_refs[]` (el assembler resuelve y UNE todos —
    recipe_assembler §817) y PROMUEVE el `belt_ref` único previo a la lista para no perder
    el belt original. DROPEA el `belt_ref` único: el validador sólo chequea servers-fantasma
    contra el belt único (recipe_validator §320), así que con varios belts compuestos hay
    que ir por belt_refs[] — si no, marca como fantasma la tool del belt sintetizado.
    """
    belt = dict(config.get("belt") or {})
    refs = list(belt.get("belt_refs") or [])
    single = belt.get("belt_ref")
    if not refs and single:
        refs = [single]
    already = belt_ref in refs
    if not already:
        refs.append(belt_ref)
    belt["belt_refs"] = refs
    belt.pop("belt_ref", None)   # composición → belt_refs[]; ver docstring
    # tool_filters: agregá la tool del server sintetizado al subset curado
    tf = dict(belt.get("tool_filters") or {})
    tools = set(tf.get(server_name) or [])
    tools.add(tool_name)
    tf[server_name] = sorted(tools)
    belt["tool_filters"] = tf
    new_config = {**config, "belt": belt}
    return new_config, already


# ── 2b) registrar un AGENT_REF en la receta (paralelo a belt_refs[], aditivo) ───
# [forja-agentes] El camino del AGENTE, EN PARALELO al de tools. Un agente equipado va a
# `belt.agent_refs[]` (NUNCA `belt_refs[]` / `mcpServers` — regla load-bearing paso 1/5).
# NO toca belt_refs/tool_filters: tool y agente CONVIVEN en la misma belt.

def _merge_agent_into_config(config: dict[str, Any], agent_ref: str) -> tuple[dict, bool]:
    """
    Devuelve (nuevo_config, ya_estaba). Additivo: agrega `agent_ref` a `belt.agent_refs[]`
    sin pisar belt_refs/tool_filters/agent_refs previos. `tool_filters` queda como está: el
    paso 1 permite {} SÓLO si hay agent_refs (un padre que sólo delega), pero acá no lo
    forzamos — si la belt ya traía tools, las conserva.
    """
    belt = dict(config.get("belt") or {})
    refs = list(belt.get("agent_refs") or [])
    already = agent_ref in refs
    if not already:
        refs.append(agent_ref)
    belt["agent_refs"] = refs
    new_config = {**config, "belt": belt}
    return new_config, already


def register_agent_into_puppet(puppet_id: str, agent_ref: str, *, conn=None,
                               repo_root: Path = _REPO_ROOT) -> dict[str, Any]:
    """
    Agrega un sub-agente equipado (`agent_ref` = ref a su receta hija) a la receta del puppet
    y la persiste (puppets.config). PARALELO a register_into_puppet (tools): idempotente,
    re-valida antes de guardar (verify-before-trust) y hace rollback si NUESTRO cambio rompe
    una receta antes válida. El agente cae SIEMPRE en `belt.agent_refs[]`, jamás en belt_refs[].
    """
    r = repo()
    own_conn = conn is None
    conn = conn or r.get_conn()
    try:
        puppet = r.get_puppet(conn, puppet_id)
        if puppet is None:
            raise ValueError(f"puppet '{puppet_id}' no existe")
        config = puppet["config"] if isinstance(puppet.get("config"), dict) else {}
        new_config, already = _merge_agent_into_config(config, agent_ref)

        validation = _validate_change(config, new_config, repo_root)
        updated = r.update_config(conn, puppet_id, new_config)
        belt = (updated or {}).get("config", {}).get("belt", {}) if updated else new_config.get("belt", {})
        return {
            "registered": True,
            "already_present": already,
            "puppet_id": puppet_id,
            "agent_ref": agent_ref,
            "agent_refs": belt.get("agent_refs", []),
            "belt_refs": belt.get("belt_refs", []),   # intactos — tool y agente conviven
            "validation": validation,
        }
    finally:
        if own_conn:
            conn.close()


def register_into_puppet(puppet_id: str, belt_ref: str, server_name: str,
                         tool_name: str, *, conn=None,
                         repo_root: Path = _REPO_ROOT) -> dict[str, Any]:
    """
    Agrega el belt sintetizado a la receta del puppet y la persiste (puppets.config).
    Idempotente. Re-valida antes de guardar; si NUESTRO cambio rompe una receta que
    antes era válida, hace rollback y levanta (no corrompemos el puppet).
    """
    r = repo()
    own_conn = conn is None
    conn = conn or r.get_conn()
    try:
        puppet = r.get_puppet(conn, puppet_id)
        if puppet is None:
            raise ValueError(f"puppet '{puppet_id}' no existe")
        config = puppet["config"] if isinstance(puppet.get("config"), dict) else {}
        new_config, already = _merge_belt_into_config(config, belt_ref, server_name, tool_name)

        validation = _validate_change(config, new_config, repo_root)
        if already:
            # belt_ref ya estaba: igual re-persistimos por si cambió tool_filters,
            # pero marcamos already para el caller (re-inspección/idempotencia).
            pass
        updated = r.update_config(conn, puppet_id, new_config)
        belt = (updated or {}).get("config", {}).get("belt", {}) if updated else new_config.get("belt", {})
        return {
            "registered": True,
            "already_present": already,
            "puppet_id": puppet_id,
            "belt_ref": belt_ref,
            "belt_refs": belt.get("belt_refs", []),
            "tool_filters": belt.get("tool_filters", {}),
            "validation": validation,
        }
    finally:
        if own_conn:
            conn.close()


def _validate_change(old_config: dict, new_config: dict, repo_root: Path) -> dict:
    """Valida la receta nueva. Si rompe algo que antes andaba → es nuestro → re-raise."""
    val = validator()
    try:
        val.validate_recipe(new_config, repo_root=repo_root)
        return {"validated": True, "ok": True}
    except val.RecipeValidationError as exc:
        old_ok = True
        try:
            val.validate_recipe(old_config, repo_root=repo_root)
        except Exception:
            old_ok = False
        if old_ok:
            raise  # nuestro cambio rompió una receta válida → no persistir
        # la receta YA era inválida antes (deuda pre-existente, no nuestra) → seguimos,
        # pero lo reportamos honesto para que no se lea como verde falso.
        return {"validated": True, "ok": False, "preexisting_invalid": True,
                "errors": getattr(exc, "errors", [])}


# ── 3) marcar un belt sintetizado como stale / versionado (drift) ───────────────

def _abs_belt_path(belt_ref_or_path: str) -> Path:
    p = Path(belt_ref_or_path)
    return p if p.is_absolute() else (_REPO_ROOT / p)


def mark_belt(belt_ref_or_path: str, *, stale: Optional[bool] = None,
              reason: str = "", version: Optional[int] = None) -> dict[str, Any]:
    """
    Sella el estado de salud en el belt.mcp.json (_meta.stale / _meta.health). El
    assembler ignora `_meta` para correr, así que es seguro; sirve para que la UI y la
    re-inspección sepan que la tool derivó y necesita re-forja.
    """
    path = _abs_belt_path(belt_ref_or_path)
    belt = json.loads(path.read_text(encoding="utf-8"))
    meta = belt.setdefault("_meta", {})
    health = dict(meta.get("health") or {})
    if stale is not None:
        meta["stale"] = bool(stale)
        health["stale"] = bool(stale)
    if reason:
        health["reason"] = reason
    if version is not None:
        meta["version"] = int(version)
        health["version"] = int(version)
    meta["health"] = health
    path.write_text(json.dumps(belt, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"belt_path": str(path), "stale": meta.get("stale"), "version": meta.get("version")}


__all__ = ["persist_belt", "register_into_puppet", "register_agent_into_puppet",
           "belt_dir_for", "durable_belt_ref", "mark_belt", "repo", "validator",
           "SYNTH_BELTS_DIR"]
