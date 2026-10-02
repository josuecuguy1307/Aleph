"""verify_step5_p6_offline.py — LLAVE VIVA de P6: el local-first, contra un servidor real.

Los unit tests prueban la política con dobles. Esto la prueba con HTTP de verdad y un
servidor que se APAGA de verdad — que es el escenario que importa y el que un doble
nunca reproduce del todo (timeouts reales, conexión rechazada, respuestas a medias).

    ./product/backend/.venv/bin/python qa/verify_step5_p6_offline.py

Requiere el backend en :8155 (arranca y lo apaga solo si le pasás --gestiona-stack).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "product" / "backend"))
sys.path.insert(0, str(ROOT / "platform"))

os.environ["ALEPH_TIER_CACHE_DIR"] = tempfile.mkdtemp(prefix="p6-live-")
BACKEND = os.environ.get("P6_BACKEND", "http://127.0.0.1:8155")

ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✓ {label}")
    else:
        fail += 1
        print(f"  ✗ {label}  {detail}")


def _get_tier(token):
    """El `consultar_remoto` real: pega al endpoint y devuelve el tier, o LANZA."""
    req = urllib.request.Request(f"{BACKEND}/v1/payments/me/tier",
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())["tier"]


def main():
    from app.phase1 import repo
    from payments import tier_cache as tc

    conn = repo.get_conn()
    u = repo.get_or_create_user(conn, f"p6-{uuid.uuid4().hex[:8]}@probe.local", "Sonda P6")
    uid = u["id"]
    token = repo.mint_session(uid)

    try:
        # ── 1 · el endpoint responde la verdad de la cuenta ────────────────────
        print("── SERVIDOR ARRIBA ──")
        v = tc.resolver_tier(uid, lambda: _get_tier(token))
        check("cuenta nueva → el endpoint dice free", v.tier == "free", f"dio {v.tier!r}")
        check("  → fuente remota (consultó de verdad)", v.fuente == "remoto")

        # la asciende un pago (simulado en DB: el camino de pago ya está probado en P3)
        repo.upsert_subscription(
            conn, account_id=uid, processor="dodo", external_id=f"sub_p6_{uuid.uuid4().hex[:8]}",
            plan="lifetime", status="alta", current_period_end=None)
        repo.resync_account_tier(conn, uid, reason="test:p6")

        v = tc.resolver_tier(uid, lambda: _get_tier(token), forzar_remoto=True)
        check("tras el ascenso → el endpoint dice basico", v.tier == "basico", f"dio {v.tier!r}")
        check("  → y quedó cacheado", (tc.leer(uid) or {}).get("tier") == "basico")

        # ── 2 · EL ESCENARIO QUE IMPORTA: el servidor se cae de verdad ─────────
        print("\n── SERVIDOR CAÍDO (apagado real) ──")
        subprocess.run(["pkill", "-f", "uvicorn app.main:app.*8155"], capture_output=True)
        time.sleep(3)

        # confirmamos que de verdad no hay nadie escuchando
        caido = False
        try:
            _get_tier(token)
        except Exception:
            caido = True
        check("el servidor está efectivamente caído", caido)

        v = tc.resolver_tier(uid, lambda: _get_tier(token), forzar_remoto=True)
        check("SIN SERVIDOR → el cliente SIGUE premium", v.tier == "basico",
              f"dio {v.tier!r} — le cerró la puerta a alguien que pagó")
        check("  → marcado degraded (honesto)", v.degraded is True)
        check("  → fuente cache_offline", v.fuente == "cache_offline")
        check("  → con mensaje que la UI puede mostrar", bool(v.mensaje))
        print(f"      «{v.mensaje}»")

        # y un cliente NUEVO en la misma máquina sin servidor → free (no hereda)
        otro = f"cuenta-nueva-{uuid.uuid4().hex[:8]}"
        v2 = tc.resolver_tier(otro, lambda: _get_tier(token))
        check("una cuenta NUEVA sin servidor → free (no hereda ni inventa)",
              v2.tier == "free" and v2.fuente == "sin_dato")

        # ── 3 · vuelve la red: se revalida solo ───────────────────────────────
        print("\n── SERVIDOR DE VUELTA ──")
        env = dict(os.environ)
        for line in (ROOT / ".env").read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, val = line.split("=", 1)
                env[k.strip()] = val.strip()
        env["PUPPET_ENFORCE_MCP_CONSTRUCTION"] = "1"
        env["PUPPET_ENFORCE_METHOD_EXPORT"] = "1"
        proc = subprocess.Popen(
            [str(ROOT / "product/backend/.venv/bin/python"), "-m", "uvicorn",
             "app.main:app", "--app-dir", str(ROOT / "product/backend"),
             "--host", "127.0.0.1", "--port", "8155"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        for _ in range(40):
            time.sleep(1)
            try:
                _get_tier(token)
                break
            except Exception:
                continue

        v = tc.resolver_tier(uid, lambda: _get_tier(token), forzar_remoto=True)
        check("vuelta la red → revalida y sale del modo degradado",
              v.fuente == "remoto" and v.degraded is False, f"fuente={v.fuente}")
        check("  → y sigue premium", v.tier == "basico")

        # ── 4 · el servidor degrada y el cliente OBEDECE ──────────────────────
        with conn.cursor() as cur:
            cur.execute("DELETE FROM subscriptions WHERE account_id = %s::uuid", (uid,))
        conn.commit()
        repo.resync_account_tier(conn, uid, reason="test:baja-p6")

        v = tc.resolver_tier(uid, lambda: _get_tier(token), forzar_remoto=True)
        check("el servidor dice free → el cliente degrada EN EL ACTO", v.tier == "free",
              f"dio {v.tier!r}")

        # y ahora, caído el servidor, NO vuelve a premium
        proc.terminate()
        time.sleep(2)
        v = tc.resolver_tier(uid, lambda: _get_tier(token), forzar_remoto=True)
        check("tras degradar, el offline NO lo resucita a premium", v.tier == "free",
              f"dio {v.tier!r}")

        # ── 5 · sesión inválida ≠ "sos free" ──────────────────────────────────
        # Un 401 significa "no sé quién sos" (token vencido, JWT rotado, reloj
        # desfasado), NO "tu plan es gratuito". Si el cliente lo tratara como free,
        # un token expirado le cerraría el producto a alguien que pagó — que es
        # exactamente lo que el local-first prohíbe. Se prueba de verdad, con el
        # servidor VIVO y un token basura.
        print("\n── SESIÓN INVÁLIDA, SERVIDOR VIVO ──")
        proc2 = subprocess.Popen(
            [str(ROOT / "product/backend/.venv/bin/python"), "-m", "uvicorn",
             "app.main:app", "--app-dir", str(ROOT / "product/backend"),
             "--host", "127.0.0.1", "--port", "8155"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        for _ in range(40):
            time.sleep(1)
            try:
                _get_tier(token)
                break
            except urllib.error.HTTPError:
                break            # responde (aunque sea 401): está vivo
            except Exception:
                continue

        # dejamos a la cuenta como premium otra vez y luego usamos un token inválido
        repo.upsert_subscription(
            conn, account_id=uid, processor="dodo",
            external_id=f"sub_p6b_{uuid.uuid4().hex[:8]}",
            plan="lifetime", status="alta", current_period_end=None)
        repo.resync_account_tier(conn, uid, reason="test:p6-reascenso")
        tc.resolver_tier(uid, lambda: _get_tier(token), forzar_remoto=True)

        da_401 = False
        try:
            _get_tier("token-vencido-o-basura")
        except urllib.error.HTTPError as e:
            da_401 = (e.code == 401)
        except Exception:
            pass
        check("el endpoint responde 401 a un token inválido", da_401)

        v = tc.resolver_tier(uid, lambda: _get_tier("token-vencido-o-basura"),
                             forzar_remoto=True)
        check("401 (sesión vencida) → NO degrada a free, preserva lo conocido",
              v.tier == "basico",
              f"dio {v.tier!r} — un token vencido le cerró la puerta a alguien que pagó")
        check("  → y lo marca degraded (no finge haber confirmado)", v.degraded is True)
        proc2.terminate()

    finally:
        subprocess.run(["pkill", "-f", "uvicorn app.main:app.*8155"], capture_output=True)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE id = %s::uuid", (uid,))
        conn.commit()
        conn.close()
        print("\n[cuenta de sonda eliminada]")

    print(f"\n{ok}/{ok + fail} verdes")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
