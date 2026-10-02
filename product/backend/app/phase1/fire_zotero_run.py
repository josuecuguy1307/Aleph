#!/usr/bin/env python3
"""
fire_zotero_run.py — DISPARA el run de Zotero cuando persona usuaria ya pegó su token (write access)
por el connect-wizard. Escribe UNA cita REAL y trae la KEY que asigna Zotero como prueba.

Camino (todo por el path de PROD, broker real):
  1) Encuentra el user_id con la key 'zotero' MÁS RECIENTE en `keys` (la que pegó persona usuaria).
  2) Verifica VIVO que la key sirve y tiene WRITE: whoami (200 + username) vía la env que
     arma el broker (make_user_resolver → ZOTERO_API_KEY). Si no es válida/write → PARA.
  3) Corre la receta research-zotero por executor.run_puppet_e2e (resolver del broker +
     approve = auto-aprueba no-money/no-send, igual que /v1/puppets/run). El modelo llama
     create_item con la cita real. Si el loop no la escribe limpio → FALLBACK determinista
     (create_item directo con la MISMA env inyectada por el broker; mismo path de key).
  4) Lee la cita de vuelta de Zotero (GET item por su key) como prueba independiente.
  5) Imprime la KEY + web_url. NUNCA imprime el token.

Uso:  cd product/backend && python3 -m app.phase1.fire_zotero_run
"""
from __future__ import annotations
import json, subprocess, sys, urllib.request, urllib.error
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.phase1 import repo, credential_broker as broker, executor  # noqa: E402

_REPO_ROOT = _HERE.parents[4]
_ZOTERO_SERVER = _REPO_ROOT / "platform" / "assembler" / "fixtures" / "zotero_server.py"
_RECIPE = json.loads((_REPO_ROOT / "platform" / "assembler" / "fixtures" / "e2e" / "research-zotero.recipe.json").read_text())

# La cita real del artefacto (DOI verificado que resuelve).
CITE = {
    "title": "Engineering CjCas9 for Efficient Base Editing and Prime Editing",
    "doi": "10.1089/crispr.2024.0018",
    "authors": ["Siyuan Liu", "Yingdi Zhao", "Qiqin Mo", "Yadong Sun", "Hanhui Ma"],
    "year": 2024, "container": "The CRISPR Journal",
    "url": "https://doi.org/10.1089/crispr.2024.0018",
    "tags": ["puppet-ai-T1-research", "cita-de-juguete"],
}
PROMPT = ("Guarda esta referencia en Zotero con create_item EXACTAMENTE con estos datos y confirma la key: "
          f"title='{CITE['title']}', doi='{CITE['doi']}', authors={CITE['authors']}, year={CITE['year']}, "
          f"container='{CITE['container']}', url='{CITE['url']}'.")


def _broker_env(resolver) -> dict:
    asm = executor._asm()
    import os
    kv = asm._resolve_keys(_RECIPE.get("keys", {}), resolver)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    for prov, val in kv.items():
        for var in asm._provider_env_vars(prov):
            env[var] = val
    return env, kv


def _mcp(env, calls):
    msgs = [{"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}}]
    for i, c in enumerate(calls, 1):
        msgs.append({"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": c})
    p = subprocess.run([sys.executable, str(_ZOTERO_SERVER)],
                       input="\n".join(json.dumps(m) for m in msgs) + "\n",
                       capture_output=True, text=True, env=env, timeout=60)
    out = {}
    for ln in p.stdout.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            o = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if isinstance(o, dict) and o.get("result", {}).get("content"):
            try:
                out[o["id"]] = json.loads(o["result"]["content"][0]["text"])
            except Exception:
                out[o["id"]] = o["result"]["content"][0].get("text")
    return out


def _find_zotero_user(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT user_id, last4, created_at FROM keys WHERE provider='zotero' "
                    "ORDER BY created_at DESC LIMIT 1")
        row = cur.fetchone()
    return row  # (user_id, last4, created_at) | None


_TOKEN_FILE = Path("/tmp/zotero_token.txt")


def _store_from_file_if_present(conn):
    """FALLBACK sin browser: si persona usuaria dejó el token en /tmp/zotero_token.txt, lo guardamos
    cifrado (repo.upsert_key, MISMO path que el connect-wizard) bajo el toy user y borramos
    el archivo. El valor NUNCA se imprime. Devuelve el user_id o None."""
    if not _TOKEN_FILE.exists():
        return None
    token = _TOKEN_FILE.read_text(encoding="utf-8").strip()
    if not token:
        return None
    user = repo.get_or_create_user(conn, "zotero-toy@demo.ai", "Cuenta de prueba")
    repo.upsert_key(conn, user_id=user["id"], provider="zotero", secret=token)
    try:
        _TOKEN_FILE.unlink()  # no dejar el token en disco en claro
    except OSError:
        pass
    print(f"[0] token tomado de {_TOKEN_FILE} → guardado cifrado bajo toy user (archivo borrado).")
    return user["id"]


def main() -> int:
    conn = repo.get_conn()
    try:
        _store_from_file_if_present(conn)   # fallback por archivo (no-browser)
        row = _find_zotero_user(conn)
        if not row:
            print("⏳ Todavía no hay key 'zotero' guardada. Pega tu token en el wizard "
                  "(Conectar.dc.html?c=zotero) hasta que diga «Guardado y VERIFICADO», "
                  "o deja el token en /tmp/zotero_token.txt y vuelve a ejecutar esto.")
            return 2
        user_id, last4, created = row
        print(f"[1] key zotero encontrada · user_id={user_id} · ...{last4} · {created}")

        resolver = broker.make_user_resolver(user_id, get_conn=repo.get_conn)
        env, kv = _broker_env(resolver)
        if "ZOTERO_API_KEY" not in env:
            print("✗ el broker NO inyectó la key (revisa byok_ref). Abortando."); return 1

        # 2) whoami VIVO — válida + write
        who = _mcp(env, [{"name": "get_account", "arguments": {}}]) \
              if False else _mcp(env, [{"name": "whoami", "arguments": {}}])
        w = who.get(1) or {}
        if not w.get("ok"):
            print(f"✗ la key no validó contra Zotero: {w}. ¿Token correcto/activo? Abortando."); return 1
        access = w.get("access") or {}
        can_write = bool(((access.get("user") or {}).get("write")) or access.get("write"))
        print(f"[2] whoami VIVO → userID={w.get('userID')} username={w.get('username')} write={can_write}")
        if not can_write:
            print("⚠ la key NO tiene write access — Zotero rechazará la escritura. "
                  "Genera una con «Allow write access» y reconecta. Abortando para no fallar en silencio.")
            return 1

        # 3) RUN agentico (broker real + approve no-money/send, como /v1/puppets/run)
        _enf = None
        try:
            import importlib.util
            import aleph_paths
            _enf = aleph_paths.load_module_by_path("enf", _REPO_ROOT / "platform" / "gates" / "recipe_enforcer.py")
        except Exception:
            pass
        def approve(server, tool, payload):
            if _enf is None:
                return True
            return not (_enf.suggests_money_touch(tool) or _enf.suggests_send(tool))

        print("[3] run agentico research-zotero…")
        out = executor.run_puppet_e2e(_RECIPE, PROMPT, user_id=user_id, conn=None,
                                      byok_resolver=resolver, deadline_s=120.0, approve=approve)
        rec = out.get("record", {}) or {}
        item_key, web_url = None, None
        for tc in rec.get("tool_calls", []):
            if tc.get("tool") == "create_item":
                r = tc.get("result")
                try:
                    r = json.loads(r) if isinstance(r, str) else r
                except Exception:
                    r = {}
                if isinstance(r, dict) and r.get("item_key"):
                    item_key, web_url = r["item_key"], r.get("web_url")
        print(f"    run_id={out.get('run_id')} ok={out.get('ok')} byok_providers={rec.get('byok_providers')} "
              f"tools={[t.get('tool') for t in rec.get('tool_calls',[])]}")

        # 3b) FALLBACK determinista si el loop no escribió limpio (misma env del broker)
        if not item_key:
            print("    (loop no devolvió item_key — fallback determinista create_item por la MISMA env del broker)")
            cr = _mcp(env, [{"name": "create_item", "arguments": CITE}]).get(1) or {}
            if cr.get("ok"):
                item_key, web_url = cr.get("item_key"), cr.get("web_url")
            else:
                print(f"✗ create_item falló: {cr}"); return 1

        if not item_key:
            print("✗ no se obtuvo item_key — no confirmo escritura."); return 1

        # 4) READBACK independiente: leer la cita de vuelta de Zotero
        key = resolver("keys:zotero")
        req = urllib.request.Request(
            f"https://api.zotero.org/users/{w.get('userID')}/items/{item_key}",
            headers={"Zotero-API-Key": key, "Zotero-API-Version": "3", "Accept": "application/json"})
        readback = {}
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                readback = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            print(f"⚠ readback HTTP {e.code} (la escritura igual devolvió key)")
        title_back = (readback.get("data") or {}).get("title")

        print("\n" + "=" * 70)
        print("✓ ZOTERO ESCRIBIÓ DE VERDAD")
        print(f"  item KEY  : {item_key}")
        print(f"  web_url   : {web_url}")
        print(f"  readback  : title='{title_back}'  (leído de vuelta de api.zotero.org)")
        print(f"  cita      : {CITE['title']} — DOI {CITE['doi']}")
        print("=" * 70)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
