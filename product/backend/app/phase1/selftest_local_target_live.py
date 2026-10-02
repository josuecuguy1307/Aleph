"""
selftest_local_target_live.py — [ssrf-consent] DELTA RE-TEST vivo contra un target self-hosted REAL.

Env-gated (skip si no hay target): prueba, a nivel provider (la MISMA vía que /v1/inspect/forge), que
  [a] con local_target=True el header-provider PASA el guard SSRF y valida VIVO (2xx) contra el target
      loopback/privado declarado — el muro exacto que mató a los casos B1/B4 de la batería;
  [b] sin el opt-in, el guard estricto lo BLOQUEA (regresión del comportamiento de siempre);
  [c] con opt-in pero credencial inválida, la puerta VIVA igual rechaza (cero-teatro: el opt-in
      afloja el SSRF, NO la validación de credencial).

El guard sigue siendo la ÚNICA autoridad: sólo abre el host:port EXACTO declarado y sólo si es
genuinamente local (nunca metadata ni público disfrazado; ver selftest_declared_target_guard.py).

Config por env (default = el Miniflux de la batería 2):
  LOCAL_TARGET_URL          (default http://127.0.0.1:8210)
  LOCAL_TARGET_TOKEN | LOCAL_TARGET_TOKEN_FILE   (la credencial; sin ella → SKIP)
  LOCAL_TARGET_VALIDATE     (default /v1/me)
  LOCAL_TARGET_AUTH_HEADER  (default X-Auth-Token)   LOCAL_TARGET_AUTH_TEMPLATE (default "{token}")

Run:  LOCAL_TARGET_TOKEN_FILE=/path/to/token python selftest_local_target_live.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # backend/


def _token() -> str:
    t = os.environ.get("LOCAL_TARGET_TOKEN", "")
    f = os.environ.get("LOCAL_TARGET_TOKEN_FILE", "")
    if not t and f and Path(f).exists():
        t = Path(f).read_text().strip()
    return t


def main() -> int:
    tok = _token()
    if not tok:
        print("SKIP · sin LOCAL_TARGET_TOKEN(_FILE) — este delta re-test vivo necesita un target real")
        return 0

    from app.phase1 import forge_router as FR
    from inspection import contracts as C

    url = os.environ.get("LOCAL_TARGET_URL", "http://127.0.0.1:8210")
    validate = os.environ.get("LOCAL_TARGET_VALIDATE", "/v1/me")
    auth_header = os.environ.get("LOCAL_TARGET_AUTH_HEADER", "X-Auth-Token")
    auth_template = os.environ.get("LOCAL_TARGET_AUTH_TEMPLATE", "{token}")
    prin = C.Principal(anon_id="ssrf-consent-live-selftest")
    fails = []

    def mk(cred: str, local: bool) -> "FR.ForgeRequest":
        return FR.ForgeRequest(url=url, cred=cred, forma="token", auth_in="header",
                               auth_header=auth_header, auth_template=auth_template,
                               validate_path=validate, local_target=local)

    print("═" * 72)
    print(f"  DELTA RE-TEST VIVO · target self-hosted {url}{validate}")
    print("═" * 72)

    # [a] con opt-in → pasa el guard + valida vivo (2xx)
    try:
        sess = FR._build_header_provider(mk(tok, True), prin, "sh-live-a").acquire()
        st = sess.meta.get("validate_status")
        ok = sess.base_url == url.rstrip("/") and str(st).startswith("2")
        print(f"{'✓' if ok else '✗'} [a] local_target=True → PASA el guard y valida vivo (status={st})")
        if not ok:
            fails.append("a")
    except Exception as e:  # noqa: BLE001
        print(f"✗ [a] con opt-in NO debía fallar: {type(e).__name__}: {e}")
        fails.append("a")

    # [b] sin opt-in → el guard estricto bloquea (el muro de B1/B4)
    try:
        FR._build_header_provider(mk(tok, False), prin, "sh-live-b").acquire()
        print("✗ [b] sin opt-in DEBÍA bloquear y no lo hizo")
        fails.append("b")
    except C.SessionError as e:
        blocked = "guard SSRF" in str(e)
        print(f"{'✓' if blocked else '✗'} [b] local_target=False → BLOQUEADO por el guard estricto")
        if not blocked:
            fails.append("b")

    # [c] con opt-in pero credencial inválida → la puerta viva rechaza igual (cero-teatro)
    try:
        FR._build_header_provider(mk("deadbeef-not-a-token", True), prin, "sh-live-c").acquire()
        print("✗ [c] una credencial inválida NO debía validar")
        fails.append("c")
    except C.SessionError as e:
        rej = "401" in str(e) or "inválid" in str(e).lower() or "inalcanzable" in str(e).lower()
        print(f"{'✓' if rej else '✗'} [c] opt-in con credencial mala → RECHAZADO vivo (no bypassea la validación)")
        if not rej:
            fails.append("c")

    print("\nRESULTADO:", "VERDE — el opt-in remueve el muro SSRF del self-hosted SIN aflojar la validación de credencial"
          if not fails else f"ROJO {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
