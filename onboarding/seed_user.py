"""
seed_user.py — COLD-START → PRIMER-VALOR.

Toma a un usuario nuevo y lo deja con un Cuarto poblado (puppets de arranque) y un
primer-valor real en la Sala — para que NADIE caiga en una sala/cuarto vacíos.

Qué hace (todo contra el :8080 real, el path de producto):
  1. registra (o ingresa) un usuario de onboarding   [POST /v1/auth/register|login]
  2. valida cada template starter (recipe_validator)  [no manda recetas inválidas]
  3. crea un puppet por template                       [POST /v1/puppets]
  4. corre el puppet keyless de arranque               [POST /v1/puppets/run] → PRIMER-VALOR
  5. reporta honesto: qué se creó y qué dato real salió (verify-from-environment)

Uso:
    ALEPH_REPO=${ALEPH_REPO_ROOT} \
    ALEPH_API=http://127.0.0.1:8080 \
      ${ALEPH_REPO_ROOT}/product/backend/.venv/bin/python onboarding/seed_user.py \
      --email nuevo@aleph.test --persona average

  --persona average → siembra los keyless de arranque (generico, finanzas) y corre uno.
  --persona dev     → siembra TODOS (incluye electronica/ingenieria/medicina) para bajar a código.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ALEPH_REPO = Path(os.environ.get("ALEPH_REPO") or Path(__file__).resolve().parents[1]).resolve()
API = os.environ.get("ALEPH_API", "http://127.0.0.1:8080").rstrip("/")
TPL = HERE / "templates"

# recipe_validator (no mandamos recetas que no validan)
sys.path.insert(0, str(ALEPH_REPO / "product" / "backend"))
try:
    from app.phase1 import recipe_validator as rv
except Exception:
    rv = None

# qué templates por persona
BY_PERSONA = {
    "average": ["generico.starter.json", "finanzas.starter.json"],
    "dev": ["generico.starter.json", "finanzas.starter.json", "electronica.starter.json",
            "ingenieria.starter.json", "medicina.starter.json"],
}


def _post(path, body, token=None):
    data = json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(API + path, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=200) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {"error": "http", "code": e.code}
    except Exception as e:
        return 0, {"error": f"{type(e).__name__}: {e}"}


def _clean_recipe(tpl: dict) -> dict:
    """quita las claves _onboarding (no son parte del contrato de receta)."""
    return {k: v for k, v in tpl.items() if not k.startswith("_")}


def ensure_user(email, password):
    st, body = _post("/v1/auth/register", {"email": email, "password": password,
                                           "display_name": "Onboarding Demo"})
    if st == 201:
        return body["id"], body["session_token"], "registrado"
    # ya existe → login
    st, body = _post("/v1/auth/login", {"email": email, "password": password})
    if st == 200:
        return body["id"], body["session_token"], "ingresó (ya existía)"
    raise SystemExit(f"no pude crear/ingresar usuario: HTTP {st} {body}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", default="onboarding-demo@aleph.test")
    ap.add_argument("--password", default="aleph-demo-123")
    ap.add_argument("--persona", choices=["average", "dev"], default="average")
    args = ap.parse_args()

    print(f"== COLD-START → PRIMER-VALOR ({args.persona}) · API={API} ==")
    uid, token, how = ensure_user(args.email, args.password)
    print(f"  usuario: {args.email} ({how}) id={uid[:12]}…")

    created, first_value = [], None
    for fname in BY_PERSONA[args.persona]:
        tpl = json.loads((TPL / fname).read_text())
        recipe = _clean_recipe(tpl)
        meta = tpl["meta"]

        # validar antes de mandar
        if rv is not None:
            try:
                rv.validate_recipe(recipe, repo_root=ALEPH_REPO)
            except rv.RecipeValidationError as e:
                print(f"  ⛔ {fname}: receta inválida → NO se crea: {e.errors}")
                continue

        st, body = _post("/v1/puppets", {"owner_id": uid, "name": meta["name"],
                                         "nicho": meta["nicho"], "config": recipe}, token)
        if st in (200, 201):
            pid = body.get("id")
            created.append((meta["name"], meta["nicho"], pid))
            print(f"  ✅ puppet creado: {meta['name']} [{meta['nicho']}] id={str(pid)[:12]}…")
        else:
            print(f"  🔴 falló crear {meta['name']}: HTTP {st} {body}")

    # PRIMER-VALOR: corremos el keyless de arranque (generico) — siempre debería dar valor
    print("\n== PRIMER-RUN GUIADO (primer-valor) ==")
    gen = json.loads((TPL / "generico.starter.json").read_text())
    prompt = gen["_onboarding"]["first_prompt"]
    st, body = _post("/v1/puppets/run",
                     {"recipe": _clean_recipe(gen), "user_id": uid,
                      "space_id": f"onboarding-{uid[:8]}", "prompt": prompt}, token)
    if st in (200, 201) and body.get("ok"):
        ans = (body.get("answer") or "")[:300]
        tools = [tc.get("tool") for tc in (body.get("record") or {}).get("tool_calls", [])]
        first_value = {"prompt": prompt, "answer": ans, "tools": tools, "run_id": body.get("run_id")}
        print(f"  prompt: {prompt}")
        print(f"  tools:  {tools}")
        print(f"  ✅ PRIMER-VALOR: {ans}")
    else:
        print(f"  🔴 primer-run no dio valor: HTTP {st} ok={body.get('ok')} err={body.get('error')}")

    print("\n== RESUMEN ==")
    print(f"  puppets sembrados: {len(created)} (Cuarto poblado, no vacío)")
    print(f"  primer-valor:      {'SÍ' if first_value else 'NO'}")
    out = {"user": {"email": args.email, "id": uid}, "persona": args.persona,
           "puppets": [{"name": n, "nicho": ni, "id": p} for n, ni, p in created],
           "first_value": first_value}
    (HERE / "seed_result.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"  detalle → onboarding/seed_result.json")


if __name__ == "__main__":
    main()
