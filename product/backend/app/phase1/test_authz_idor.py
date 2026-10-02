#!/usr/bin/env python3
"""
test_authz_idor.py — EVIDENCIA REAL del fix de IDOR (authz por sesión, no por id-cliente).

Contexto: antes, GET /v1/users/{id}/{runs,outputs,puppets,keys} autorizaba por el id que
mandaba el cliente — cualquiera leía la data (y a un paso, las creds BYOK) de otro user.
El fix: token de sesión tamper-proof (Fernet, stateless) que liga al owner; cada endpoint
verifica session.owner == el id pedido. Sin token → 401, token de otro → 403.

Qué prueba (capa de token, pura, contra el crypto real del org):
  1. ROUND-TRIP: mint_session(uid) → session_owner(token) == uid.
  2. FORJADO: un token basura/manipulado → session_owner == None (→ el endpoint da 401).
  3. AISLAMIENTO: el token de A nunca resuelve al uid de B (→ cross-user da 403).

La matriz HTTP completa (200/401/403 por endpoint) se verifica contra el server vivo
(ver reports/ y el walk adversarial); este script bloquea la invariante del token.

    python3 -m app.phase1.test_authz_idor      (desde product/backend)
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.phase1 import repo  # noqa: E402

UID_A = "11111111-1111-1111-1111-111111111111"
UID_B = "22222222-2222-2222-2222-222222222222"


def main() -> int:
    fails = []

    # 1. round-trip
    tok_a = repo.mint_session(UID_A)
    owner = repo.session_owner(tok_a)
    ok1 = owner == UID_A
    print(f"1. round-trip  mint→owner == uid_A : {'OK' if ok1 else 'FAIL'}  (owner={owner})")
    if not ok1:
        fails.append("round-trip")

    # 2. forjados / manipulados → None (nunca autoriza)
    forged = ["", "garbage", tok_a + "x", "Bearer " + tok_a, tok_a[:-4] + "AAAA", "null"]
    forged_ok = all(repo.session_owner(f) is None for f in forged)
    print(f"2. forjado/manip → None             : {'OK' if forged_ok else 'FAIL'}  "
          f"({sum(repo.session_owner(f) is None for f in forged)}/{len(forged)} rechazados)")
    if not forged_ok:
        fails.append("forged")

    # 3. aislamiento: token de A no resuelve al uid de B
    tok_b = repo.mint_session(UID_B)
    iso_ok = (repo.session_owner(tok_a) == UID_A and repo.session_owner(tok_b) == UID_B
              and repo.session_owner(tok_a) != UID_B)
    print(f"3. aislamiento  A↛B                 : {'OK' if iso_ok else 'FAIL'}")
    if not iso_ok:
        fails.append("isolation")

    print()
    if fails:
        print(f"❌ FALLÓ: {fails}")
        return 1
    print("✅ TOKEN DE SESIÓN: round-trip + forjado-rechazado + aislamiento — invariante anti-IDOR OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
