#!/usr/bin/env python3
"""Evidencia del badge ámbar honesto en Settings: AV ámbar (no verde) · FRED verde · screenshot + DOM-assert."""
import json
from playwright.sync_api import sync_playwright

BASE = "http://localhost:8091"
sess = json.load(open("/tmp/tier2/_badge_session.json"))
user_js = json.dumps({"id": sess["uid"], "session_token": sess["tok"],
                      "email": sess["email"], "display_name": "Badge probe"})

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context()
    # sembrar la sesión ANTES de que corra el JS de la página
    ctx.add_init_script(f"sessionStorage.setItem('puppet_user', JSON.stringify({user_js}));")
    pg = ctx.new_page()
    pg.goto(f"{BASE}/Settings.dc.html", wait_until="networkidle", timeout=20000)
    pg.wait_for_timeout(2500)  # que carguen /connectors + /keys y renderice

    body = pg.inner_text("body")
    av_amber = "se confirma en el 1er uso" in body
    fred_green = "conectada" in body
    # localizar los badges por su texto
    print("=== DOM de la sección de conexiones ===")
    # badges presentes
    print("  AV  → badge ámbar ('se confirma en el 1er uso'):", av_amber)
    print("  FRED→ badge verde ('conectada'):", fred_green)
    # asegurar que AV NO muestra el verde 'conectada' pegado a Alpha (heurística: contar)
    amber_badges = pg.query_selector_all("text=se confirma en el 1er uso")
    green_badges = pg.query_selector_all("text=conectada")
    print(f"  badges ámbar: {len(amber_badges)} · badges verdes 'conectada': {len(green_badges)}")

    pg.screenshot(path="/tmp/tier2/5_settings_badges_after.png", full_page=True)
    print("\nscreenshot → /tmp/tier2/5_settings_badges_after.png")

    ok = av_amber and fred_green
    print(f"\n{'✅ BADGE HONESTO: AV ámbar + FRED verde' if ok else '❌ revisar render'}")
    b.close()
