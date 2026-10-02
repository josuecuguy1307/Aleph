"""
preflight.py — probe the REAL environment and report what each capability can do.

Drives the matrix's honest BLOCKED reasons: a cell whose `requires` capability is not
ok is BLOCKED with the probe's detail (never silently green, never fabricated).

Stdlib only. Fast, side-effect-free probes (no agent runs here).
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

ALEPH_REPO = Path(os.environ.get("ALEPH_REPO") or Path(__file__).resolve().parents[1]).resolve()


def _http(url: str, timeout=4, headers=None) -> tuple[int, str]:
    try:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(2000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


def _port(host: str, port: int, timeout=2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def _docker_up() -> bool:
    try:
        return subprocess.run(["/usr/local/bin/docker", "info"],
                              capture_output=True, timeout=8).returncode == 0
    except Exception:
        return False


def _docker_images() -> list[str]:
    try:
        r = subprocess.run(["/usr/local/bin/docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
                           capture_output=True, timeout=8)
        return r.stdout.decode("utf-8", "replace").splitlines() if r.returncode == 0 else []
    except Exception:
        return []


def _img_present(imgs, *needles) -> bool:
    return any(any(n in i.lower() for n in needles) for i in imgs)


def _env_from_infra() -> dict:
    out = {}
    f = ALEPH_REPO / "infra" / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def probe() -> dict:
    caps: dict[str, dict] = {}
    infra = _env_from_infra()

    # ── ollama (local OSS) ────────────────────────────────────
    st, _ = _http("http://127.0.0.1:11434/api/tags", timeout=3)
    caps["ollama"] = {
        "ok": st == 200,
        "detail": "ollama :11434 up (qwen3:8b)" if st == 200 else f"ollama down (HTTP {st})",
    }
    caps["model:ollama"] = dict(caps["ollama"])

    # ── finanzas_data (local keyless server + WB network) ─────
    fin_script = ALEPH_REPO / "platform" / "connectors" / "finanzas" / "finanzas_data_server.py"
    wb_st, _ = _http("https://api.worldbank.org/v2/country/EC/indicator/NY.GDP.MKTP.CD?format=json&per_page=1", timeout=6)
    caps["finanzas_data"] = {
        "ok": fin_script.exists() and wb_st == 200,
        "detail": (f"server present + World Bank API HTTP {wb_st}" if fin_script.exists()
                   else "finanzas_data_server.py MISSING"),
    }

    # ── kicad sch-api (pure python, no GUI) ───────────────────
    kpy = Path(os.environ.get("KICAD_SCH_API_PY") or sys.executable)
    if kpy.exists():
        try:
            r = subprocess.run([str(kpy), "-c", "import mcp_kicad_sch_api"],
                               capture_output=True, timeout=20)
            ok = r.returncode == 0
            detail = "kicad sch-api module imports (pure-python, keyless)" if ok else \
                     f"kicad import fail: {r.stderr.decode('utf-8','replace')[:120]}"
        except Exception as e:
            ok, detail = False, f"kicad probe error: {e}"
    else:
        ok, detail = False, "kicad sch-api venv missing"
    caps["kicad"] = {"ok": ok, "detail": detail}

    # ── engine_ingenieria: docker (openfoam/MP) OR freecad RPC ─
    # engine_reason ∈ {running, not_started, absent} — la columna que pide el ask:
    #   running     = el motor está arriba ahora
    #   not_started = el motor está INSTALADO (app/imagen) pero no arrancado
    #   absent      = no hay binario/app/imagen → no cableado
    docker_ok = _docker_up()
    imgs = _docker_images() if docker_ok else []
    freecad_ok = _port("127.0.0.1", 9875)
    freecad_installed = Path("/Applications/FreeCAD.app").exists()
    docker_installed = Path("/Applications/Docker.app").exists()
    openfoam_img = _img_present(imgs, "openfoam") if docker_ok else None
    if freecad_ok or (docker_ok and openfoam_img):
        ing_reason = "running"
    elif freecad_installed or docker_installed:
        ing_reason = "not_started"
    else:
        ing_reason = "absent"
    caps["engine_ingenieria"] = {
        "ok": freecad_ok or (docker_ok and bool(openfoam_img)),
        "engine_reason": ing_reason,
        "detail": (f"freecad-rpc:9875={'up' if freecad_ok else 'down'} (app "
                   f"{'instalada' if freecad_installed else 'AUSENTE'}); "
                   f"docker={'up' if docker_ok else 'down'} (app "
                   f"{'instalada' if docker_installed else 'AUSENTE'}), "
                   f"openfoam-img={'sí' if openfoam_img else ('no' if docker_ok else '?')}"),
    }

    # ── orthanc PACS (medicina) ───────────────────────────────
    orthanc_ok = _port("127.0.0.1", 8042) or _port("127.0.0.1", 4242)
    orthanc_img = _img_present(imgs, "orthanc") if docker_ok else False
    if orthanc_ok:
        orth_reason = "running"
    elif orthanc_img:
        orth_reason = "not_started"   # imagen presente, contenedor no arrancado
    else:
        orth_reason = "absent"        # ni binario ni imagen → no cableado
    caps["orthanc"] = {
        "ok": orthanc_ok,
        "engine_reason": orth_reason,
        "detail": ("Orthanc PACS up (:8042/:4242)" if orthanc_ok else
                   ("Orthanc image presente pero contenedor no arrancado" if orthanc_img else
                    "Orthanc ausente: ni binario ni imagen docker (era dev-test)")),
    }

    # ── cloud models (informational; OSS-direct safety net covers runs) ──
    or_key = infra.get("OPENROUTER_API_KEY", "")
    if or_key:
        st, body = _http("https://openrouter.ai/api/v1/auth/key", timeout=8,
                         headers={"Authorization": f"Bearer {or_key}"})
        free = '"is_free_tier":true' in body.replace(" ", "")
        caps["model:openrouter"] = {
            "ok": st == 200,
            "detail": (f"key valid (HTTP {st}{', free-tier' if free else ''}); "
                       "paid models (gpt-4o-mini/deepseek) pueden dar 402 si no hay créditos"
                       if st == 200 else f"OpenRouter HTTP {st}"),
        }
    else:
        caps["model:openrouter"] = {"ok": False, "detail": "no OPENROUTER_API_KEY"}

    # ── model:opus — el cerebro pedido. Probe REAL (no el de 20 tokens que sí pasa) ──
    if or_key:
        body = json.dumps({
            "model": "anthropic/claude-opus-4.8",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 100,
        }).encode()
        try:
            req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions",
                                         data=body, method="POST",
                                         headers={"Authorization": f"Bearer {or_key}",
                                                  "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                ok_opus = r.status == 200
                detail = "Opus 4.8 responde vía OpenRouter (hay crédito)"
        except urllib.error.HTTPError as e:
            ok_opus = False
            msg = ""
            try:
                msg = json.loads(e.read().decode()).get("error", {}).get("message", "")[:120]
            except Exception:
                pass
            detail = (f"Opus 4.8 ⛔ HTTP {e.code}"
                      + (f": {msg}" if msg else "")
                      + " · NO hay Anthropic key en infra/.env; única ruta = OpenRouter")
        except Exception as e:
            ok_opus, detail = False, f"Opus probe error: {type(e).__name__}: {e}"
    else:
        ok_opus, detail = False, "no OPENROUTER_API_KEY y no Anthropic key → sin ruta a Opus"
    caps["model:opus"] = {"ok": ok_opus, "detail": detail}

    caps["model:groq"] = {
        "ok": bool(infra.get("GROQ_API_KEY") or os.environ.get("GROQ_API_KEY")),
        "detail": "key present pero free-tier TPM-limited para runs agénticos multi-turno (R6)",
    }

    # ── platform serving path (:8080) + Postgres ──────────────
    st8080, _ = _http("http://127.0.0.1:8080/v1/atoms/catalog", timeout=3)
    caps["platform:8080"] = {"ok": st8080 == 200,
                             "detail": f":8080 atoms/catalog HTTP {st8080}" if st8080 else ":8080 down (usar in-process)"}
    caps["postgres"] = {"ok": _port("127.0.0.1", 5432), "detail": "postgres :5432 " + ("up" if _port("127.0.0.1", 5432) else "down")}

    return caps


if __name__ == "__main__":
    caps = probe()
    print(json.dumps(caps, ensure_ascii=False, indent=2))
    n_ok = sum(1 for c in caps.values() if c["ok"])
    print(f"\n{n_ok}/{len(caps)} capacidades OK")
