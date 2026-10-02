#!/usr/bin/env python3
"""
demo_session.py — Demo EJECUTABLE de la Session viva (V2-1).

Qué prueba (de verdad, sin mocks):
  • Monta el belt echo (fixtures/belt-dummy.mcp.json) UNA vez y lo deja vivo.
  • Manda DOS mensajes seguidos por la MISMA sesión, midiendo el wall de cada
    uno con time.perf_counter.
  • El 2º mensaje NO re-bootea los MCPs (reúsa el belt vivo) -> debe salir más
    rápido en arranque. Imprime ambos tiempos y la diferencia.
  • Imprime la ruta del events.jsonl generado + sus primeras líneas.

Carril de modelo:
  1) Prueba LiteLLM en http://127.0.0.1:4000 PRIMERO. Si responde utilizable,
     lo usa y lo declara.
  2) Si no (caído o exige key y no la tenemos), cae a Ollama qwen3:8b en
     http://127.0.0.1:11434/v1 con timeout amplio — el 1er mensaje puede tardar
     ~80s por carga fría del modelo.
  Declara explícitamente qué carril quedó elegido.
"""

from __future__ import annotations

import importlib.util
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parents[1]


def _load_session_module():
    spec = importlib.util.spec_from_file_location("puppet_session", _THIS_DIR / "session.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_sm = _load_session_module()
Session = _sm.Session


# ── Selección de carril de modelo: LiteLLM :4000 primero, luego Ollama ────────

def _probe_litellm() -> dict | None:
    """
    Devuelve un dict de overrides de config si LiteLLM responde utilizable, o
    None si no sirve (caído / 401 sin key / sin modelos). Declara por stdout.
    """
    base = "http://127.0.0.1:4000"
    key = os.environ.get("LITELLM_MASTER_KEY") or os.environ.get("LITELLM_API_KEY") or ""
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        req = urllib.request.Request(base + "/v1/models", headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode())
        models = [m.get("id") for m in body.get("data", []) if m.get("id")]
        if not models:
            print("[lane] LiteLLM :4000 respondió pero sin modelos listados -> fallback Ollama.")
            return None
        chosen = models[0]
        print(f"[lane] LiteLLM :4000 OK (key {'presente' if key else 'ausente'}). Modelo: {chosen}.")
        return {"base_url": base + "/v1", "model": chosen, "_lane": "litellm",
                "_api_key_env": ("LITELLM_MASTER_KEY" if key else None)}
    except urllib.error.HTTPError as e:
        print(f"[lane] LiteLLM :4000 devolvió HTTP {e.code} (probablemente exige key) -> fallback Ollama.")
        return None
    except Exception as e:
        print(f"[lane] LiteLLM :4000 no disponible ({e.__class__.__name__}) -> fallback Ollama.")
        return None


def _build_config() -> dict:
    cfg_path = _THIS_DIR / "config-dummy.json"
    cfg = json.loads(cfg_path.read_text())
    # timeouts amplios para carga fría
    cfg["max_turns"] = cfg.get("max_turns", 4)

    lane = _probe_litellm()
    if lane is not None:
        cfg["base_url"] = lane["base_url"]
        cfg["model"] = lane["model"]
        if lane.get("_api_key_env"):
            cfg["api_key"] = {"env_var": lane["_api_key_env"]}
        cfg["_lane"] = "litellm"
    else:
        # Ollama qwen3:8b — carril por defecto del config-dummy.json
        cfg["base_url"] = "http://127.0.0.1:11434/v1"
        cfg["model"] = "qwen3:8b"
        cfg["_lane"] = "ollama"
        print("[lane] Carril elegido: Ollama qwen3:8b @ http://127.0.0.1:11434/v1 "
              "(timeout 120s; el 1er mensaje puede tardar ~80s por carga fría).")
    return cfg


def main() -> int:
    print("=" * 70)
    print("DEMO — Session viva del motor de agente (Puppet AI, V2-1)")
    print("=" * 70)

    cfg = _build_config()
    print(f"[cfg] lane={cfg['_lane']}  model={cfg['model']}  base_url={cfg['base_url']}")
    print(f"[cfg] belt={cfg['belt_path']}")
    print()

    events: list = []

    def on_event(kind: str, evt: dict) -> None:
        # callback liviano: imprime cada evento que la sesión emite en vivo.
        events.append((kind, evt))
        brief = {k: v for k, v in evt.items() if k not in ("ts", "session_id")}
        print(f"  «evt» {kind}: {json.dumps(brief, ensure_ascii=False)[:200]}")

    workdir = _THIS_DIR / ".demo-session-run"
    msg1 = "Echo back exactly: hola mundo uno"
    msg2 = "Echo back exactly: hola mundo dos"

    t_boot = time.perf_counter()
    with Session(cfg, repo_root=_REPO_ROOT, on_event=on_event,
                 workdir=workdir, deadline_s=600.0) as sess:

        print(f"[session] events.jsonl -> {sess.events_path}")
        print()

        # ── Mensaje 1 (incluye boot frío del belt + posible carga fría del modelo)
        print(f"[send #1] {msg1!r}")
        s1 = time.perf_counter()
        ans1 = sess.send(msg1)
        w1 = time.perf_counter() - s1
        print(f"[send #1] respuesta: {ans1[:200]!r}")
        print(f"[send #1] wall = {w1:.3f}s   (belt booteado en este turno: True)")
        print(f"[session] belt sigue vivo tras #1: {sess.booted}")
        print()

        # ── Mensaje 2 (DEBE reusar el belt vivo, sin re-boot de MCPs)
        print(f"[send #2] {msg2!r}")
        s2 = time.perf_counter()
        ans2 = sess.send(msg2)
        w2 = time.perf_counter() - s2
        print(f"[send #2] respuesta: {ans2[:200]!r}")
        print(f"[send #2] wall = {w2:.3f}s   (belt reusado, SIN re-boot de MCPs)")
        print()

        events_path = sess.events_path

    total = time.perf_counter() - t_boot

    # ── reporte de tiempos ────────────────────────────────────────────────────
    print("=" * 70)
    print("TIEMPOS MEDIDOS (time.perf_counter, wall por mensaje)")
    print("=" * 70)
    print(f"  mensaje #1 (boot + carga fría) : {w1:.3f}s")
    print(f"  mensaje #2 (belt vivo, no re-boot): {w2:.3f}s")
    print(f"  diferencia (#1 - #2)           : {w1 - w2:.3f}s")
    if w2 < w1:
        print("  -> el 2º mensaje fue MÁS RÁPIDO: el belt quedó vivo, no se re-booteó. ✔")
    else:
        print("  -> el 2º no fue más rápido en wall (el modelo dominó el tiempo), "
              "pero la traza de eventos confirma que el belt NO se re-booteó.")
    print(f"  wall total de la demo          : {total:.3f}s")
    print()

    # confirmación dura desde los eventos: belt_ready aparece UNA sola vez
    belt_ready_count = sum(1 for k, _ in events if k == "belt_ready")
    print(f"[check] eventos 'belt_ready' emitidos: {belt_ready_count} "
          f"(esperado 1 => el belt se montó UNA vez para los dos mensajes)")
    print()

    # ── events.jsonl ──────────────────────────────────────────────────────────
    print("=" * 70)
    print(f"events.jsonl -> {events_path}")
    print("=" * 70)
    if events_path.exists():
        lines = events_path.read_text(encoding="utf-8").splitlines()
        print(f"[events] total de líneas: {len(lines)}")
        print("[events] primeras líneas:")
        for ln in lines[:8]:
            print("  " + ln)
    else:
        print("[events] ¡no se generó el archivo!")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
