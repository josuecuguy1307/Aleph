#!/usr/bin/env python3
"""
verify_catalog_batch.py — PASS-gate por-server del CATALOGO (ola de expansion).

"Verificado, no decorativo": cada server nuevo del catalogo solo cuenta si pasa
TODOS los pasos duros, en orden (cualquier FAIL => ese server FALLA):

  (a) STATIC   manifest carga · server existe en mcpServers · card con
               backed_by==server (salvo card_required:false) · si auth!=keyless
               => onboarding JSON existe · la dedup key (backed_by+sorted tools)
               NO esta tragada por un belt anterior (re-camina collect_atoms).
  (b) ENV GATE toda ${VAR} de la config del server (command/args/env) + el
               env_required de la probe debe estar en os.environ; si falta
               => SKIP(BYOK) ruidoso, NUNCA PASS, exit-code neutral.
  (c) LAUNCH   resolve_belt_ref -> assembler.MCPServer (el cliente de PROD,
               mismo patron que verify_ingenieria_belt) con PUPPET_WORKDIR
               tmpdir; initialize OK; tools/list SUPERSET de expect_tools
               (y de card.tools si hay card).
  (d) CALL     tools/call REAL con los args de la probe; asercion del expect
               (contains|regex|json_key) sobre el output REAL; excerpt <=500
               chars con secretos de env redactados.
  (e) CATALOG  collect_atoms() importado in-process; si hay card, un atomo con
               server==name debe surfacear con zone/auth (se loguea la zone).
  (f) EVIDENCE reports/catalog-wave-a/evidence-<batch|timestamp>.json.
               Exit 0 SOLO si todo lo no-skipped PASA.

Uso:
    product/backend/.venv/bin/python platform/assembler/verify_catalog_batch.py
    ... [--only <server>] [--batch <name>] [--live http://127.0.0.1:8080]

Spec de probes: catalog/evals/catalog-probes/probes.json (declarativa; una
entrada por server). Stdlib only + modulos del repo (belt_resolver/assembler).
"""

from __future__ import annotations

import argparse
import importlib.util as _ilu
import json
import os
import re
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
from assembler import MCPServer            # noqa: E402  el MCPServer real del runtime
from belt_resolver import resolve_belt_ref  # noqa: E402
from tool_result import es_error_de_tool     # noqa: E402

_REPO = _HERE.parent.parent
_PROBES = _REPO / "catalog" / "evals" / "catalog-probes" / "probes.json"
_ONB = _REPO / "catalog" / "connectors" / "onboarding"
# MISMO walk que atoms_router._BELT_DIRS (collect_atoms): el orden define quien
# es dueño de cada dedup key (backed_by + sorted tools) — el primero gana.
# [ledger 2026-07-04] fixtures excluido, espejo de atoms_router (promocion → test-only).
_BELT_DIRS = [_REPO / "catalog" / "templates"]
_ATOMS_ROUTER = _REPO / "product" / "backend" / "app" / "phase1" / "atoms_router.py"
# [H2] LA VARA NO ESCRIBE EN EL ÁRBOL. Medido sobre main @ 1242dba: el `git status` traía
# 5 `reports/catalog-wave-a/evidence-*.json` sin trackear, uno por corrida. Como el nombre
# lleva timestamp, nunca pisaban nada — sólo se acumulaban como basura indistinguible de
# trabajo sin commitear. La evidencia va a un temporal salvo que se la pida explícitamente.
_EVIDENCIA_AL_ARBOL = "--evidencia-al-arbol" in sys.argv
_EVIDENCE_DIR = (_REPO / "reports" / "catalog-wave-a") if _EVIDENCIA_AL_ARBOL \
    else Path(tempfile.gettempdir()) / "aleph-catalog-wave-a"

_VAR_RE = re.compile(r"\$\{([A-Za-z0-9_]+)\}")
# vars que el PROPIO runner provee (no son BYOK del usuario)
_RUNNER_VARS = {"PUPPET_WORKDIR", "PUPPET_BELTS"}
_SECRETISH = re.compile(r"(KEY|TOKEN|SECRET|PASS|PWD|CRED)", re.IGNORECASE)
_EXCERPT_MAX = 500

_atoms_cache = None


# ── helpers compartidos (patron verify_ingenieria_belt) ─────────────────────

def _base_env(server: str) -> dict:
    env = dict(os.environ)
    env["PUPPET_WORKDIR"] = tempfile.mkdtemp(prefix=f"verify-cat-{server}-")
    env["PUPPET_BELTS"] = str(_REPO / "product" / "belts")
    return env


def _expand(s: str, env: dict) -> str:
    out = s
    for k, v in env.items():
        out = out.replace("${" + k + "}", v)
    return out


def _mk_server(name: str, scfg: dict, base_env: dict) -> MCPServer:
    command = _expand(scfg.get("command", ""), base_env)
    args = [_expand(a, base_env) for a in (scfg.get("args", []) or [])]
    child_env = dict(base_env)
    for k, v in (scfg.get("env", {}) or {}).items():
        child_env[k] = _expand(v, base_env)
    return MCPServer(name, command, args, env=child_env)


def _vars_of(scfg: dict) -> set:
    """Todas las ${VAR} referenciadas por la config del server (command/args/env)."""
    blob = " ".join(
        [scfg.get("command", "")]
        + [str(a) for a in (scfg.get("args", []) or [])]
        + [str(v) for v in (scfg.get("env", {}) or {}).values()]
    )
    return set(_VAR_RE.findall(blob)) - _RUNNER_VARS


def _dedup_key(card: dict) -> str:
    # identico a collect_atoms: backed_by + "::" + ",".join(sorted(tools))
    return (card.get("backed_by") or "") + "::" + ",".join(sorted(card.get("tools") or []))


def _dedup_owners() -> dict:
    """Re-camina los belts en el MISMO orden que collect_atoms y devuelve
    {dedup_key: belt_ref del PRIMER belt que la reclama}."""
    owners: dict = {}
    for d in _BELT_DIRS:
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
            ref = str(p.relative_to(_REPO))
            for c in cards:
                if c.get("backed_by") not in servers:
                    continue  # cero theater — igual que collect_atoms
                owners.setdefault(_dedup_key(c), ref)
    return owners


def _collect_atoms() -> list:
    """Importa collect_atoms() in-process desde atoms_router (resuelve su repo
    root desde su propio __file__, o sea ESTE arbol)."""
    global _atoms_cache
    if _atoms_cache is None:
        spec = _ilu.spec_from_file_location("puppet_atoms_router_gate", _ATOMS_ROUTER)
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _atoms_cache = mod.collect_atoms()
    return _atoms_cache


def _redact(text: str, referenced_vars: set) -> str:
    """Redacta valores de secretos de env que aparezcan en el texto: las vars
    referenciadas por el server + cualquier var de nombre secretoso."""
    out = text
    for name, val in os.environ.items():
        if not val or len(val) < 6:
            continue
        if name in referenced_vars or _SECRETISH.search(name):
            if val in out:
                out = out.replace(val, f"«REDACTED:{name}»")
    return out


def _expect_ok(expect: dict, out: str):
    """Evalua la asercion declarada sobre el output REAL. -> (ok, descripcion)."""
    if "contains" in expect:
        needle = expect["contains"]
        return needle in out, f"contains {needle!r}"
    if "regex" in expect:
        pat = expect["regex"]
        return re.search(pat, out) is not None, f"regex /{pat}/"
    if "json_key" in expect:
        path = str(expect["json_key"])
        try:
            node = json.loads(out)
        except json.JSONDecodeError:
            return False, f"json_key {path!r} (output no es JSON)"
        for seg in path.split("."):
            if isinstance(node, dict) and seg in node:
                node = node[seg]
            elif isinstance(node, list) and seg.lstrip("-").isdigit():
                try:
                    node = node[int(seg)]
                except IndexError:
                    return False, f"json_key {path!r} (indice fuera de rango)"
            else:
                return False, f"json_key {path!r} (clave ausente)"
        return True, f"json_key {path!r}"
    return False, f"expect invalido: {sorted(expect.keys())}"


# ── el gate por server ───────────────────────────────────────────────────────

def run_entry(entry: dict, live_base: str | None) -> dict:
    name = entry["server"]
    belt_ref = entry["belt_ref"]
    steps: dict = {}
    rec = {"server": name, "belt_ref": belt_ref, "steps": steps,
           "tool_called": None, "excerpt": None, "verdict": "FAIL"}
    checks_ok = True

    def check(step: str, ok: bool, detail: str = "") -> bool:
        nonlocal checks_ok
        mark = "✓" if ok else "✗"
        print(f"  {mark} [{step}] {detail}" if detail else f"  {mark} [{step}]")
        prev = steps.get(step)
        line = ("PASS" if ok else "FAIL") + (f": {detail}" if detail else "")
        steps[step] = line if prev is None else prev + " · " + line
        if not ok:
            checks_ok = False
        return ok

    print(f"\n=== {name}  (belt_ref={belt_ref}) ===")

    # (a) STATIC ---------------------------------------------------------------
    try:
        resolved = resolve_belt_ref(belt_ref, _REPO)
        belt = json.loads(Path(resolved.mcp_json_path).read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        check("static", False, f"belt_ref no resuelve/carga: {e}")
        return rec
    belt_rel = str(Path(resolved.mcp_json_path).relative_to(_REPO))
    check("static", True, f"manifest carga: {belt_rel}")

    servers = belt.get("mcpServers", {}) or {}
    if not check("static", name in servers, f"server '{name}' ∈ mcpServers"):
        return rec
    scfg = servers[name]

    cards = (belt.get("_meta") or {}).get("cards") or []
    card = next((c for c in cards if c.get("backed_by") == name), None)
    card_required = entry.get("card_required", True)
    if card is None:
        if card_required:
            check("static", False, f"sin card backed_by=='{name}' en _meta.cards (card_required)")
            return rec
        check("static", True, f"sin card backed_by=='{name}' — tolerado (card_required:false)")
    else:
        check("static", True, f"card '{card.get('id')}' backed_by=='{name}'")
        auth = card.get("auth", "keyless")
        if auth != "keyless":
            connector = card.get("connector")
            onb = _ONB / f"{connector}.json" if connector else None
            ok = bool(connector) and onb.exists()
            if not check("static", ok,
                         f"auth={auth} → onboarding {connector or '(sin connector)'}.json "
                         f"{'existe' if ok else 'NO existe'}"):
                return rec
        # dedup: la key de ESTA card debe pertenecer a ESTE belt (collect_atoms walk)
        owners = _dedup_owners()
        key = _dedup_key(card)
        owner = owners.get(key)
        if not check("static", owner == belt_rel,
                     f"dedup key '{key}' → dueño {owner!r}"
                     + ("" if owner == belt_rel else f" ≠ {belt_rel!r} (card TRAGADA)")):
            return rec

    # (b) ENV GATE ---------------------------------------------------------------
    need = sorted(_vars_of(scfg) | set(entry.get("env_required") or []))
    missing = [v for v in need if not os.environ.get(v)]
    if missing:
        print(f"  ⤳ [env_gate] SKIP(BYOK) — faltan credenciales: {missing} → NO se marca PASS")
        steps["env_gate"] = f"SKIP(BYOK): faltan {missing}"
        rec["verdict"] = "SKIP"
        return rec
    check("env_gate", True, f"env completo ({need or 'sin ${VAR}'})")

    # (c) LAUNCH -----------------------------------------------------------------
    base_env = _base_env(name)
    srv = _mk_server(name, scfg, base_env)
    if not check("launch", srv.start(), "initialize handshake (assembler.MCPServer, cliente de PROD)"):
        return rec
    try:
        tools = [t.get("name") for t in srv.list_tools()]
        want = set(entry.get("expect_tools") or [])
        if not check("launch", want.issubset(set(tools)),
                     f"tools/list ({len(tools)}) ⊇ expect_tools; faltan={sorted(want - set(tools)) or 'ninguna'}"):
            return rec
        if card is not None and card.get("tools"):
            cwant = set(card["tools"])
            if not check("launch", cwant.issubset(set(tools)),
                         f"tools/list ⊇ card.tools; faltan={sorted(cwant - set(tools)) or 'ninguna'}"):
                return rec

        # (d) CALL -----------------------------------------------------------------
        probe = entry["probe"]
        tool = probe["tool"]
        rec["tool_called"] = tool
        from recipe_assembler import _expand_str
        args = {k: _expand_str(v, {**base_env, "PUPPET_REPO": str(_REPO)})
                if isinstance(v, str) else v for k, v in (probe.get("args") or {}).items()}
        out = srv.call_tool(tool, args)
        excerpt = _redact(out, set(need))[:_EXCERPT_MAX]
        rec["excerpt"] = excerpt
        ok, desc = _expect_ok(probe.get("expect") or {}, out)
        hard_err = es_error_de_tool(out)
        if not check("call", ok and not hard_err,
                     f"tools/call {tool} → {desc}" + (" · ERROR del server" if hard_err else "")):
            print(f"      output: {excerpt[:200]!r}")
            return rec
        print(f"      excerpt: {excerpt[:160]!r}")
    finally:
        srv.stop()

    # (e) CATALOG ----------------------------------------------------------------
    if card is None:
        steps["catalog"] = "N/A (sin card — card_required:false)"
        print("  ⤳ [catalog] N/A — sin card, el atomo aun no existe en el catalogo")
    else:
        try:
            atoms = _collect_atoms()
        except Exception as e:  # noqa: BLE001
            check("catalog", False, f"collect_atoms() no importo/corrio: {e}")
            return rec
        mine = [a for a in atoms if a.get("server") == name]
        atom = next((a for a in mine
                     if ",".join(sorted(a.get("tools") or [])) == ",".join(sorted(card.get("tools") or []))),
                    mine[0] if mine else None)
        if not check("catalog", atom is not None, f"atomo con server=='{name}' surfacea en collect_atoms()"):
            return rec
        ok_shape = atom.get("zone") in ("fuentes", "mesa", "entrega") and bool(atom.get("auth"))
        if not check("catalog", ok_shape,
                     f"zone={atom.get('zone')!r} auth={atom.get('auth')!r} belt_ref={atom.get('belt_ref')!r}"):
            return rec
        if live_base:
            url = live_base.rstrip("/") + "/v1/atoms/catalog"
            try:
                with urllib.request.urlopen(url, timeout=15) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                live_hit = any(a.get("server") == name for a in data.get("atoms", []))
                if not check("catalog", live_hit, f"LIVE {url} → atomo server=='{name}' presente"):
                    return rec
            except Exception as e:  # noqa: BLE001
                check("catalog", False, f"LIVE {url} inaccesible: {e}")
                return rec

    rec["verdict"] = "PASS" if checks_ok else "FAIL"
    return rec


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="PASS-gate por-server del catalogo")
    ap.add_argument("--only", help="filtrar por nombre de server")
    ap.add_argument("--batch", help="filtrar por campo 'batch' de la probe")
    ap.add_argument("--live", metavar="BASE_URL", default=None,
                    help="ADEMAS validar el atomo via GET <base>/v1/atoms/catalog (default off)")
    args = ap.parse_args()

    spec = json.loads(_PROBES.read_text(encoding="utf-8"))
    entries = spec.get("probes", [])
    if args.only:
        entries = [e for e in entries if e.get("server") == args.only]
    if args.batch:
        entries = [e for e in entries if e.get("batch") == args.batch]
    if not entries:
        print(f"✗ ninguna probe matchea (only={args.only!r}, batch={args.batch!r}) — nada que verificar")
        return 1

    print(f"PASS-gate del catalogo — {len(entries)} probe(s) · spec={_PROBES.relative_to(_REPO)}")
    results = [run_entry(e, args.live) for e in entries]

    passed = [r for r in results if r["verdict"] == "PASS"]
    failed = [r for r in results if r["verdict"] == "FAIL"]
    skipped = [r for r in results if r["verdict"] == "SKIP"]

    # (f) EVIDENCE
    _EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = args.batch or time.strftime("%Y%m%d-%H%M%S")
    evidence_path = _EVIDENCE_DIR / f"evidence-{stamp}.json"
    evidence_path.write_text(json.dumps({
        "gate": "verify_catalog_batch",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "probes_spec": str(_PROBES.relative_to(_REPO)),
        "filters": {"only": args.only, "batch": args.batch, "live": args.live},
        "summary": {"pass": len(passed), "fail": len(failed), "skip": len(skipped)},
        "servers": results,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("\n================ RESUMEN ================")
    for r in results:
        mark = {"PASS": "✓", "FAIL": "✗", "SKIP": "⤳"}[r["verdict"]]
        print(f"  {mark} {r['verdict']:4}  {r['server']}  ({r['belt_ref']})")
    print(f"\nEvidencia: {evidence_path.relative_to(_REPO)}")
    if failed:
        print(f"\n=== RESULTADO: ROJO — {len(failed)} FAIL / {len(passed)} PASS / {len(skipped)} SKIP ===")
        return 1
    print(f"\n=== RESULTADO: VERDE — {len(passed)} PASS / {len(skipped)} SKIP(BYOK) ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
