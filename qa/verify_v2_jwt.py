"""verify_v2_jwt.py — la verificación de JWT contra el JWKS REAL de Supabase.

CONTRACT-AUTH-v2. Prueba los caminos de RECHAZO contra la clave pública de verdad del
proyecto (no un fixture): un token firmado por otro, con `alg: none`, vencido, de otro
emisor, o con kid desconocido.

El caso POSITIVO (un token legítimo de Supabase verifica) necesita un token emitido por
ellos, y para eso hace falta un usuario confirmado — ver el final del archivo.

    ./product/backend/.venv/bin/python qa/verify_v2_jwt.py
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "platform"))
sys.path.insert(0, str(ROOT / "product" / "backend"))

for line in (ROOT / ".env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from auth import supabase_jwt as sj  # noqa: E402

ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✓ {label}")
    else:
        fail += 1
        print(f"  ✗ {label}  {detail}")


def _rechaza(label, token):
    try:
        sub = sj.verificar(token)
        check(label, False, f"ACEPTÓ un token que debía rechazar (sub={sub!r})")
    except sj.JWTInvalido:
        check(label, True)
    except Exception as e:
        check(label, False, f"lanzó {type(e).__name__} en vez de JWTInvalido: {e}")


def main():
    import jwt as pyjwt
    from cryptography.hazmat.primitives.asymmetric import ec

    base = os.environ["SUPABASE_URL"].rstrip("/")
    emisor = f"{base}/auth/v1"

    # ── el JWKS REAL del proyecto ──────────────────────────────────────────────
    keys = sj._traer_jwks(forzar=True)
    check("trae el JWKS real del proyecto", bool(keys), "no se pudo obtener")
    if keys:
        print(f"      alg={keys[0].get('alg')} kid={str(keys[0].get('kid'))[:12]}…")
        check("es asimétrico (no hace falta guardar ningún secreto compartido)",
              keys[0].get("kty") in ("EC", "RSA"))
    kid_real = (keys or [{}])[0].get("kid")

    # ── forma ──────────────────────────────────────────────────────────────────
    check("es_jwt() distingue un Fernet de un JWT",
          sj.es_jwt("eyJhbGciOiJFUzI1NiJ9.eyJzdWIiOiJ4In0.zzz")
          and not sj.es_jwt("gAAAAABhZ...") and not sj.es_jwt(""))

    ahora = int(time.time())
    clave_ajena = ec.generate_private_key(ec.SECP256R1())

    # ── RECHAZOS, contra el JWKS de verdad ─────────────────────────────────────
    _rechaza("firmado por OTRA clave (impostor) → rechazado",
             pyjwt.encode({"sub": "atacante", "iss": emisor, "exp": ahora + 3600},
                          clave_ajena, algorithm="ES256", headers={"kid": kid_real}))

    _rechaza("alg 'none' (el ataque clásico) → rechazado",
             pyjwt.encode({"sub": "atacante", "iss": emisor, "exp": ahora + 3600},
                          key="", algorithm="none"))

    _rechaza("VENCIDO → rechazado",
             pyjwt.encode({"sub": "alguien", "iss": emisor, "exp": ahora - 60},
                          clave_ajena, algorithm="ES256", headers={"kid": kid_real}))

    _rechaza("emisor AJENO (otro proyecto de Supabase) → rechazado",
             pyjwt.encode({"sub": "alguien", "iss": "https://otro.supabase.co/auth/v1",
                           "exp": ahora + 3600},
                          clave_ajena, algorithm="ES256", headers={"kid": kid_real}))

    _rechaza("kid desconocido → rechazado",
             pyjwt.encode({"sub": "alguien", "iss": emisor, "exp": ahora + 3600},
                          clave_ajena, algorithm="ES256", headers={"kid": "inventado"}))

    _rechaza("sin 'sub' → rechazado",
             pyjwt.encode({"iss": emisor, "exp": ahora + 3600},
                          clave_ajena, algorithm="ES256", headers={"kid": kid_real}))

    _rechaza("sin 'exp' (token eterno) → rechazado",
             pyjwt.encode({"sub": "alguien", "iss": emisor},
                          clave_ajena, algorithm="ES256", headers={"kid": kid_real}))

    _rechaza("basura → rechazado", "no.soy.un.jwt")
    _rechaza("vacío → rechazado", "")

    # ── la costura: session_owner tolera ambos formatos ────────────────────────
    from app.phase1 import repo
    check("session_owner(None) → None", repo.session_owner(None) is None)
    check("session_owner(basura) → None", repo.session_owner("no-soy-nada") is None)
    check("session_owner(JWT falso) → None (no explota)",
          repo.session_owner(pyjwt.encode({"sub": "x", "iss": emisor, "exp": ahora + 60},
                                          clave_ajena, algorithm="ES256",
                                          headers={"kid": kid_real})) is None)

    # el camino v1 sigue vivo: un Fernet legítimo resuelve igual que siempre
    os.environ.setdefault("PUPPET_DB_ENC_KEY", "")
    tok_v1 = repo.mint_session("11111111-2222-3333-4444-555555555555")
    check("Fernet de v1 SIGUE resolviendo (la transición no rompió el camino viejo)",
          repo.session_owner(tok_v1) == "11111111-2222-3333-4444-555555555555")

    # ── el caso POSITIVO ──────────────────────────────────────────────────────
    tok = Path("/tmp/v2_jwt.txt")
    if tok.exists() and tok.read_text().strip():
        try:
            sub = sj.verificar(tok.read_text().strip())
            check("TOKEN REAL de Supabase → verifica y da el sub", bool(sub))
            print(f"      sub={sub}")
        except Exception as e:
            check("TOKEN REAL de Supabase → verifica", False, str(e))
    else:
        print("\n  ⏸ CASO POSITIVO PENDIENTE: hace falta un JWT emitido por Supabase.")
        print("     Requiere un usuario CONFIRMADO — o la service_role key (Admin API),")
        print("     o completar un signup real. Los rechazos de arriba SÍ corren contra")
        print("     el JWKS real, pero 'rechaza todo' también lo cumpliría un verificador")
        print("     roto: sin el positivo, la prueba está a medias y se dice.")

    print(f"\n{ok}/{ok + fail} verdes")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
