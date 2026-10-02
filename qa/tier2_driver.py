#!/usr/bin/env python3
"""
Tier 2 — driver Playwright (usuario sintético, sesión aislada) del flujo REAL de la SPA:
  Auth (login) → Cuarto (armar agente Finanzas → Darle vida) → Sala (run) → Biblioteca (obra).
Captura evidencia honesta en cada pantalla + el belt que el puppet creado realmente tiene.
"""
import json, sys, time, urllib.request
from playwright.sync_api import sync_playwright

BASE = "http://localhost:8091"
EMAIL = f"tier2-finanzas-{int(time.time())}@demo.ai"
OUT = "/tmp/tier2"
import os; os.makedirs(OUT, exist_ok=True)

steps = []
def log(screen, ok, detail=""):
    steps.append({"screen": screen, "ok": ok, "detail": detail})
    print(f"  [{'OK ' if ok else 'RED'}] {screen}: {detail}")


def puppet_config_from_db(puppet_id):
    import psycopg2, psycopg2.extras
    c = psycopg2.connect(dbname="puppet_ai", host="localhost")
    cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("select config from puppets where id=%s", (puppet_id,))
    row = cur.fetchone(); c.close()
    return row["config"] if row else None


with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context()  # sesión aislada
    pg = ctx.new_page()
    errors = []
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

    # ── 1) AUTH ──
    print(f"\n══ usuario sintético: {EMAIL} ══")
    pg.goto(f"{BASE}/Auth.dc.html", wait_until="networkidle", timeout=20000)
    pg.wait_for_timeout(800)
    pg.fill("input[type=email]", EMAIL)
    pg.fill("input[type=password]", "Finanzas123!")
    # modo 'register' por default; el SUBMIT es el 2º botón "Crear cuenta" (el 1º es la pestaña).
    # register con email+pass → POST /v1/auth/login (idempotente) → Cuarto.
    pg.get_by_role("button", name="Crear cuenta").last.click()
    pg.wait_for_url("**/Cuarto.dc.html", timeout=20000)
    sess = pg.evaluate("sessionStorage.getItem('puppet_user')")
    user = json.loads(sess) if sess else {}
    log("Auth", bool(user.get("id")), f"login → user {str(user.get('id'))[:8]}… sesión={'sí' if user.get('session_token') else 'no'}")
    pg.screenshot(path=f"{OUT}/1_auth_done.png")

    # ── 2) CUARTO: armar agente Finanzas ──
    pg.wait_for_timeout(1200)
    pg.fill("input[placeholder*='nombre']", "Analista Finanzas")
    pg.fill("textarea[placeholder*='palabras']",
            "Armá un Excel con el PIB de Ecuador del Banco Mundial y la tabla de derivados "
            "del Banco Central del Ecuador, con la fuente de cada dato.")
    pg.wait_for_timeout(600)
    pg.screenshot(path=f"{OUT}/2_cuarto_filled.png")
    # "Darle vida →" dispara launch() → POST /v1/puppets → Sala?puppet=<id>
    pg.get_by_text("Darle vida").first.click()
    try:
        pg.wait_for_url("**/Sala.dc.html?*puppet=*", timeout=20000)
        puppet_id = pg.url.split("puppet=")[-1].split("&")[0]
        log("Cuarto", True, f"agente creado → puppet {puppet_id[:8]}… → navega a Sala")
    except Exception as e:
        log("Cuarto", False, f"no navegó a Sala: {e}; url={pg.url}")
        puppet_id = None

    # PRUEBA del belt: ¿qué cableó el Cuarto en la receta del puppet?
    if puppet_id:
        cfg = puppet_config_from_db(puppet_id)
        belt_ref = (cfg or {}).get("belt", {}).get("belt_ref")
        tf = (cfg or {}).get("belt", {}).get("tool_filters")
        nicho = (cfg or {}).get("meta", {}).get("nicho")
        has_data_tools = any(t in json.dumps(tf or {}) for t in ("worldbank_series", "bce_pdf_ingest", "build_workbook"))
        log("Cuarto/belt", has_data_tools,
            f"nicho={nicho} belt_ref={belt_ref} tools={tf} | ¿cablea belt de procedencia (WB+BCE)? {has_data_tools}")

    # ── 3) SALA: el run real (on-mount) ──
    pg.wait_for_timeout(1000)
    # esperar a que el run termine (la sala pinta bitácora/resultado). Damos margen al loop OSS.
    deadline = time.time() + 180
    ran = False
    while time.time() < deadline:
        body_txt = pg.inner_text("body")
        if any(k in body_txt.lower() for k in ("planilla", "xlsx", "finanzas_ecuador", "celdas", "error", "no pude")):
            ran = True
            break
        pg.wait_for_timeout(2500)
    pg.screenshot(path=f"{OUT}/3_sala_run.png", full_page=True)
    log("Sala", ran, "el run on-mount pintó resultado" if ran else "no se vio resultado en 180s")

    # ── 4) BIBLIOTECA: la obra descargable ──
    uid = user.get("id")
    outs = []
    if uid:
        req = urllib.request.Request(f"http://localhost:8080/v1/users/{uid}/outputs",
                                     headers={"Authorization": "Bearer " + user.get("session_token", "")})
        try:
            outs = json.loads(urllib.request.urlopen(req, timeout=15).read()).get("outputs", [])
        except Exception as e:
            log("Biblioteca/api", False, f"outputs API falló: {e}")
    files = [o for o in outs if o.get("kind") == "file"]
    xlsx = [o for o in files if "spreadsheet" in (o.get("mime") or "")]
    pg.goto(f"{BASE}/Biblioteca.dc.html", wait_until="networkidle", timeout=20000)
    pg.wait_for_timeout(1500)
    pg.screenshot(path=f"{OUT}/4_biblioteca.png", full_page=True)
    log("Biblioteca", bool(xlsx),
        f"outputs={len(outs)} archivos={len(files)} xlsx={len(xlsx)}" +
        (f" → {xlsx[0].get('uri','').split('/')[-1]}" if xlsx else " → SIN xlsx descargable"))

    # descarga real (si hay)
    if xlsx:
        oid = xlsx[0]["id"]
        dreq = urllib.request.Request(f"http://localhost:8080/v1/outputs/{oid}/download",
                                      headers={"Authorization": "Bearer " + user.get("session_token", "")})
        try:
            data = urllib.request.urlopen(dreq, timeout=15).read()
            ok = data[:2] == b"PK"  # xlsx = zip
            log("Biblioteca/download", ok, f"descargó {len(data)} bytes, xlsx-válido={ok}")
        except Exception as e:
            log("Biblioteca/download", False, f"descarga falló: {e}")

    print(f"\nconsola-errores (no-404): {[e for e in errors if '404' not in e][:5]}")
    b.close()

# veredicto
print("\n=== TIER 2 — VEREDICTO POR PANTALLA ===")
for s in steps:
    print(f"  {'✅' if s['ok'] else '❌'} {s['screen']}: {s['detail']}")
green = all(s["ok"] for s in steps)
print(f"\n{'✅ TIER 2 VERDE' if green else '❌ TIER 2 ROJO — ver pantalla(s) ❌ arriba'}")
json.dump(steps, open(f"{OUT}/verdict.json", "w"), indent=2, ensure_ascii=False)
sys.exit(0 if green else 1)
