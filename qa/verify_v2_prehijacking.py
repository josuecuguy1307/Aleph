"""verify_v2_prehijacking.py — el ataque de pre-registro, cerrado. CONTRACT-AUTH-v2.

EL ATAQUE (encontrado al cablear el front de v2, no reportado por nadie):

  1. El atacante registra `victima@gmail.com` por /v1/auth/register — que NO verifica
     el email — con una contraseña que él elige.
  2. La víctima entra después con Google, con su dirección real.
  3. Si el alta perezosa reclamara la cuenta a ciegas por email, el `auth_uid` de la
     víctima quedaría ligado a la cuenta del ATACANTE, que sigue sabiendo la contraseña.
  4. Desde ahí el atacante entra cuando quiera y ve todo lo de la víctima.

Es *pre-hijacking* clásico. La cuenta se entrega al que llegó primero.

EL CIERRE: sólo se reclama una cuenta SIN `password_hash`. Con contraseña, la sesión de
Supabase se rechaza (None) y el usuario tiene un camino honesto: entrar con su
contraseña y vincular el proveedor desde ajustes.

    ./product/backend/.venv/bin/python qa/verify_v2_prehijacking.py
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "platform"))
sys.path.insert(0, str(ROOT / "product" / "backend"))

for line in (ROOT / ".env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from app.phase1 import repo            # noqa: E402
from auth import supabase_jwt as sj    # noqa: E402

ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✓ {label}")
    else:
        fail += 1
        print(f"  ✗ {label}  {detail}")


def main():
    conn = repo.get_conn()
    creadas = []

    def _limpiar():
        for uid in creadas:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM users WHERE id = %s::uuid", (uid,))
        conn.commit()

    try:
        # ── EL ATAQUE ─────────────────────────────────────────────────────────
        email_victima = f"victima-{uuid.uuid4().hex[:8]}@gmail.com"
        atacante = repo.register_user(conn, email_victima, "la-clave-del-atacante")
        creadas.append(atacante["id"])
        print(f"  [atacante registró {email_victima} con SU contraseña]")

        auth_uid_victima = str(uuid.uuid4())   # el id que Google le daría a la víctima
        resultado = sj.resolver_cuenta(conn, auth_uid_victima, repo, email=email_victima)

        check("la sesión del proveedor NO se liga a una cuenta con contraseña ajena",
              resultado is None,
              f"RECLAMÓ la cuenta del atacante (id={resultado}) → pre-hijacking VIVO")

        with conn.cursor() as cur:
            cur.execute("SELECT auth_uid FROM users WHERE id = %s::uuid", (atacante["id"],))
            au = cur.fetchone()[0]
        check("  → y la cuenta del atacante NO quedó marcada con el auth_uid ajeno",
              au is None, f"auth_uid={au}")

        # ── EL CAMINO LEGÍTIMO SIGUE FUNCIONANDO ──────────────────────────────
        email_nuevo = f"nuevo-{uuid.uuid4().hex[:8]}@gmail.com"
        auth_uid_nuevo = str(uuid.uuid4())
        uid = sj.resolver_cuenta(conn, auth_uid_nuevo, repo, email=email_nuevo)
        check("un email SIN cuenta previa → alta limpia y ligada", bool(uid))
        if uid:
            creadas.append(uid)
            with conn.cursor() as cur:
                cur.execute("SELECT auth_uid, tier FROM users WHERE id = %s::uuid", (uid,))
                au2, tier = cur.fetchone()
            check("  → con el auth_uid correcto", str(au2) == auth_uid_nuevo)
            check("  → y nace FREE (el tier no viene del proveedor)", tier == "free")

        # el mismo proveedor otra vez → misma cuenta, sin duplicar
        uid2 = sj.resolver_cuenta(conn, auth_uid_nuevo, repo, email=email_nuevo)
        check("segundo login del mismo usuario → la MISMA cuenta", uid2 == uid)

        # ── cuenta legacy SIN contraseña sí se reclama (no rompe la migración) ──
        email_legacy = f"legacy-{uuid.uuid4().hex[:8]}@gmail.com"
        legacy = repo.get_or_create_user(conn, email_legacy)   # sin password_hash
        creadas.append(legacy["id"])
        auth_uid_legacy = str(uuid.uuid4())
        uid3 = sj.resolver_cuenta(conn, auth_uid_legacy, repo, email=email_legacy)
        check("una cuenta legacy SIN contraseña SÍ se reclama (no se duplica)",
              uid3 == legacy["id"], f"dio {uid3!r} vs {legacy['id']!r}")

        # ── H2 · EL ATAQUE QUE SOBREVIVÍA AL GATE DE password_hash ────────────
        # El hueco que la auditoría de superficie marcó y este archivo NO cubría: una
        # cuenta SIN contraseña pero YA LIGADA a otro auth_uid. Pasa el gate de arriba
        # (no hay password_hash que la proteja), el UPDATE no matchea ninguna fila
        # (auth_uid ya no es NULL)... y antes se devolvía el id igual.
        #
        # Cómo llega a existir esa fila sin /v1/auth/register: el atacante se registra en
        # SUPABASE con el email de la víctima (Supabase emite JWT aunque el email no esté
        # confirmado) y hace UN request cualquiera. Eso crea el alta perezosa ligada a su
        # auth_uid, sin contraseña. El gate de H1 no lo toca: no pasó por nuestro registro.
        email_robado = f"robado-{uuid.uuid4().hex[:8]}@gmail.com"
        auth_uid_atacante = str(uuid.uuid4())
        victima_row = repo.get_or_create_user(conn, email_robado)   # sin password_hash
        creadas.append(victima_row["id"])
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET auth_uid = %s::uuid WHERE id = %s::uuid",
                        (auth_uid_atacante, victima_row["id"]))
        conn.commit()
        print(f"  [atacante ya ligó {email_robado} a SU auth_uid, sin contraseña]")

        auth_uid_real = str(uuid.uuid4())            # el Google real de la víctima
        robada = sj.resolver_cuenta(conn, auth_uid_real, repo, email=email_robado)
        check("H2 · cuenta sin contraseña YA ligada a otro auth_uid → None (0 filas ⇒ no se entrega)",
              robada is None,
              f"ENTREGÓ la cuenta del atacante (id={robada}) → pre-hijacking VIVO")

        with conn.cursor() as cur:
            cur.execute("SELECT auth_uid FROM users WHERE id = %s::uuid", (victima_row["id"],))
            au3 = cur.fetchone()[0]
        check("  → y el auth_uid del atacante quedó intacto (no se pisó en silencio)",
              str(au3) == auth_uid_atacante, f"auth_uid={au3}")

        # …pero el DUEÑO legítimo de esa fila sigue entrando: 0 filas afectadas y el
        # auth_uid ya es el suyo (la carrera de dos requests del mismo primer login).
        propia = sj.resolver_cuenta(conn, auth_uid_atacante, repo, email=email_robado)
        check("  → el dueño real de la fila SÍ entra (0 filas + auth_uid propio ≠ rechazo)",
              propia == victima_row["id"], f"dio {propia!r} vs {victima_row['id']!r}")

        # ── sin email no se inventa nada ──────────────────────────────────────
        check("sin email y sin auth_uid conocido → None (no inventa cuentas)",
              sj.resolver_cuenta(conn, str(uuid.uuid4()), repo, email=None) is None)

    finally:
        _limpiar()
        conn.close()
        print("\n[cuentas de sonda eliminadas]")

    print(f"\n{ok}/{ok + fail} verdes")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
