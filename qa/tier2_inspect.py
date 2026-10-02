#!/usr/bin/env python3
"""Inspecciona el DOM renderizado real de las pantallas de la SPA (de-risk del driver)."""
import sys
from playwright.sync_api import sync_playwright

BASE = "http://localhost:8091"
PAGES = ["Auth.dc.html", "Cuarto.dc.html"]


def dump(page, name):
    print(f"\n===== {name} =====")
    print("title:", page.title())
    for sel, label in [("button", "BUTTONS"), ("input", "INPUTS"), ("textarea", "TEXTAREAS"), ("a", "LINKS")]:
        els = page.query_selector_all(sel)
        print(f"  {label} ({len(els)}):")
        for e in els[:18]:
            txt = (e.inner_text() or "").strip().replace("\n", " ")[:40] if sel != "input" else ""
            ph = e.get_attribute("placeholder") or ""
            typ = e.get_attribute("type") or ""
            href = e.get_attribute("href") or "" if sel == "a" else ""
            print(f"    - [{sel}] type={typ!r} text={txt!r} ph={ph!r} href={href[:30]!r}")


with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page()
    pg.on("console", lambda m: None)
    pg.goto(f"{BASE}/{PAGES[0]}", wait_until="networkidle", timeout=20000)
    pg.wait_for_timeout(1200)
    dump(pg, PAGES[0])
    # Cuarto requiere sesión; seteamos una mínima para que renderice
    pg.goto(f"{BASE}/{PAGES[1]}", wait_until="networkidle", timeout=20000)
    pg.wait_for_timeout(1200)
    dump(pg, PAGES[1])
    b.close()
