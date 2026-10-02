"""
account_deletion.py — BORRADO DE CUENTA (ticket 2 · sprint pre-launch, owner: seguridad).

Tres movimientos, en este orden de severidad:

  1. SOFT-DELETE (reversible)  — `delete_account`: el acceso muere YA (el middleware de
     main.py bloquea toda sesión de una cuenta con deleted_at), los datos se CONGELAN
     hasta purge_after (= deleted_at + 30 días, fecha EXACTA persistida). Re-login con
     credenciales dentro de la ventana → reactivación intacta (router.auth_login).

  2. REVOCACIÓN OAuth INSTANTÁNEA (irreversible aun dentro de la ventana) — parte del
     mismo `delete_account`: los tokens OAuth se revocan CONTRA EL PROVEEDOR (best-effort,
     data-driven vía oauth.revoke_url del onboarding object) y se BORRAN del vault
     Postgres (fila base + companions __oauth/__oauth_partial) y del vault filesystem
     del motor (data/synth_belts/u/<slug(user_id)>/ — credenciales de MCPs forjados y
     sesiones browser). La reversibilidad NO alcanza a las conexiones externas: si el
     usuario vuelve, RE-CONECTA. Las BYOK no-OAuth (keys pegadas) quedan CONGELADAS como
     el resto de los datos.

  3. PURGA TOTAL día 30 (irreversible) — `purge_user` / `purge_expired`: borra TODO lo
     del usuario en Postgres (con deletes explícitos para las tablas que el CASCADE no
     cubre: runs/job_queue son ON DELETE SET NULL; billing_runs_ingested y
     billing_stripe_events no tienen FK) y en disco (rag/, run_outputs/, espacios/,
     artifacts/, synth_belts/). El done-bar es el test de CERO filas huérfanas
     (test_account_deletion.py + qa/verify_borrado_cuenta.py).

MAIL honesto: no existe SMTP en el stack → outbox durable en data/outbox/mails.jsonl con
`transport: "logged"` (no finge envío) + el MISMO copy vuelve en la respuesta del API:
fecha exacta de purga y la línea "tus conexiones externas ya fueron desconectadas".

Tensión registrada (decisión del ticket): la purga borra también instrumentation_logs
(vía runs) y las filas billing_* del usuario — "purga total cascadeada" manda sobre el
data flywheel y sobre auditoría de pagos (pre-launch: no hay pagos reales todavía).
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from app.phase1 import repo

_REPO_ROOT = Path(__file__).resolve().parents[4]


def _raiz_de_recursos() -> Path:
    """Raíz de lo que VIAJA en el bundle. Dev: la raíz del árbol. Congelado: `_MEIPASS`.

    ⚠️ [OBRA 6d] `catalog/connectors/onboarding` viaja en el bundle, pero este módulo vive en
    el PYZ: `parents[4]` cae fuera de `_MEIPASS` y `_onboarding()` devolvía `{}` en silencio.
    Lo destapó el guard de clase al auditarlo contra el árbol de main antes de mergear.

    El MISMO dato ya lo leen bien `motor_verdad._onboarding_dir()` y
    `credential_broker._oauth_cfg()`, los dos con `resource_root()`. Eran tres lectores del
    mismo directorio y uno miraba a otro lado.
    """
    try:
        import aleph_paths
        return aleph_paths.resource_root()
    except Exception:                    # noqa: BLE001 — dev suelto sin `platform` en el path
        return _REPO_ROOT


_ONB_DIR = _raiz_de_recursos() / "catalog" / "connectors" / "onboarding"
def _dir_datos(nombre: str) -> Path:
    """`<data_root>/<nombre>` — el dir de datos del USUARIO, no el árbol.
    ⚠️ EL BUNDLE ES SÓLO LECTURA (CLAUDE.md · clase ya pagada en synth_belts, el pin
    del sello y la caché del resolver). Bajo PyInstaller `_REPO_ROOT` cae dentro de
    `_MEIPASS`, el temp que se borra al cerrar: lo que se escriba ahí NO existe en el
    arranque siguiente. Todo lo que se ESCRIBE va al dir de datos del usuario.
    Cae al árbol sólo si `aleph_paths` no se puede importar (dev suelto): en frozen siempre
    resuelve, porque `aleph_paths` viaja en el bundle.
    """
    try:
        import aleph_paths
        return aleph_paths.data_root() / nombre
    except Exception:                    # noqa: BLE001
        return _REPO_ROOT / "product" / "backend" / "data" / nombre

_OUTBOX = _dir_datos("outbox") / "mails.jsonl"
_DATA = _REPO_ROOT / "product" / "backend" / "data"
_SYNTH_BELTS = _DATA / "synth_belts"


# ── helpers ──────────────────────────────────────────────────────────────────────

def _es_cliente() -> bool:
    """El rol, vía la capa canónica (repo ya cachea el módulo de db)."""
    return repo._dbmod().es_cliente()


def _slug(s: str) -> str:
    """Mismo slug que platform/inspection/contracts.py usa para el namespace del vault
    filesystem (u/<slug(user_id)>) — duplicado a propósito: importar el motor de
    inspección desde acá arrastraría su árbol entero para una regex de 2 líneas."""
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s or "").strip("-").lower()
    return s or "x"


def _onboarding(provider: str) -> dict:
    p = _ONB_DIR / f"{provider}.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _oauth_flow():
    from app.phase1.connectors_router import _oauth
    return _oauth()


def _oauth_env() -> dict:
    from app.phase1.connectors_router import _oauth_env as env_fn
    return env_fn()


def _safe_roots() -> list[str]:
    """Raíces bajo las que _rmtree tiene permiso de borrar: data/ del backend + la raíz de
    los índices RAG self-hosted (honra PUPPET_RAG_DIR, que puede caer FUERA de data/ — sin
    esto el índice de Conocimiento quedaría huérfano con un override de env)."""
    roots = [str(_DATA.resolve())]
    try:
        from app.phase1 import knowledge_store
        roots.append(str(Path(knowledge_store.rag_dir_root()).resolve()))
    except Exception:
        pass
    return roots


def _rmtree(path: Path) -> bool:
    """rm -rf defensivo: SOLO borra dentro de una raíz segura (data/ o la raíz RAG), jamás fuera."""
    try:
        resolved = path.resolve()
        rp = str(resolved)
        if not any(rp == r or rp.startswith(r + "/") for r in _safe_roots()):
            return False
        if resolved.exists():
            shutil.rmtree(resolved, ignore_errors=True)
            return True
    except OSError:
        pass
    return False


def _rag_root() -> Path:
    """Raíz de los índices RAG self-hosted (para purgar knowledge.db por composición)."""
    try:
        from app.phase1 import knowledge_store
        return Path(knowledge_store.rag_dir_root())
    except Exception:
        return _DATA / "rag"


# ── copy honesto (el mail y la respuesta del API comparten texto) ────────────────

def _deletion_copy(purge_after_iso: str) -> dict:
    d = (purge_after_iso or "")[:10]
    return {
        "es": ("Tu cuenta fue desactivada y tus datos quedaron congelados. "
               f"El {d} se borran de forma definitiva e irreversible. "
               "Si vuelves a iniciar sesión antes de esa fecha, tu cuenta se reactiva "
               "tal como la dejaste. Tus cuentas conectadas por OAuth (Google, Slack, etc.) "
               "ya fueron desconectadas de forma permanente: si vuelves, tendrás que "
               "volver a conectarlas."),
        "en": ("Your account was deactivated and your data is frozen. "
               f"On {d} it will be permanently and irreversibly deleted. "
               "If you log back in before that date, your account reactivates "
               "exactly as you left it. Your OAuth-connected accounts (Google, Slack, etc.) "
               "were permanently disconnected: if you return, you will need to reconnect them."),
        "purge_date": d,
        "purge_at": purge_after_iso,
    }


def _write_outbox_mail(email: str, copy: dict) -> dict:
    """Outbox durable y honesto: transport='logged' — acá NO hay SMTP; cuando exista,
    este JSONL es la cola a drenar. Nunca bloquea el borrado si el disco falla."""
    mail = {
        "to": email,
        "template": "account_deletion",
        "subject_es": "Tu cuenta de Aleph: borrado programado para el " + copy["purge_date"],
        "subject_en": "Your Aleph account: deletion scheduled for " + copy["purge_date"],
        "body_es": copy["es"],
        "body_en": copy["en"],
        "purge_at": copy["purge_at"],
        "transport": "logged",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        _OUTBOX.parent.mkdir(parents=True, exist_ok=True)
        with _OUTBOX.open("a", encoding="utf-8") as f:
            f.write(json.dumps(mail, ensure_ascii=False) + "\n")
        mail["written"] = True
    except OSError:
        mail["written"] = False
    return mail


# ── revocación OAuth instantánea ─────────────────────────────────────────────────

def _oauth_base_providers(providers: list[str]) -> set[str]:
    """Conectores OAuth del usuario: base con companion __oauth/__oauth_partial, o cuyo
    onboarding object declara auth_method=oauth (cubre el caso access-token-sin-refresh)."""
    names = set(providers)
    bases: set[str] = set()
    for p in names:
        if p.endswith(repo._OAUTH_COMPANION_SUFFIX) or p.endswith(repo._OAUTH_PARTIAL_SUFFIX):
            continue
        if (f"{p}{repo._OAUTH_COMPANION_SUFFIX}" in names
                or f"{p}{repo._OAUTH_PARTIAL_SUFFIX}" in names
                or _onboarding(p).get("auth_method") == "oauth"):
            bases.add(p)
    return bases


def revoke_all_oauth(conn, user_id: str, *,
                     http_post: Optional[Callable] = None) -> dict[str, list[str]]:
    """Revoca TODO lo OAuth del usuario, AHORA: (a) best-effort contra el proveedor
    (revoke_url data-driven; sin revoke_url o red caída NO bloquea), (b) DELETE local
    inmediato de base + companions, (c) barrido del vault filesystem del motor.
    Devuelve {revoked, revoke_failed, removed_local} — honesto: 'revoked' es solo lo
    que el proveedor confirmó; lo local SIEMPRE se borra."""
    flow = _oauth_flow()
    env = _oauth_env()
    providers = [k.get("provider") for k in repo.list_keys(conn, user_id)]
    bases = _oauth_base_providers(providers)

    revoked: list[str] = []
    revoke_failed: list[str] = []
    removed_local: list[str] = []
    kwargs = {"http_post": http_post} if http_post is not None else {}

    for base in sorted(bases):
        cfg = (_onboarding(base).get("oauth") or {})
        cid, csec = flow.client_creds(cfg, env)
        # tokens a revocar: access (fila base) + refresh (companion JSON)
        tokens: list[str] = []
        access = repo.get_key(conn, user_id, base)
        if access:
            tokens.append(access)
        companion_raw = repo.get_key(conn, user_id, f"{base}{repo._OAUTH_COMPANION_SUFFIX}")
        if companion_raw:
            try:
                rt = (json.loads(companion_raw) or {}).get("refresh_token")
                if rt:
                    tokens.append(rt)
            except (json.JSONDecodeError, AttributeError):
                pass
        ok_any = False
        for tok in tokens:
            res = flow.revoke_token(cfg, token=tok, client_id=cid, client_secret=csec, **kwargs)
            ok_any = ok_any or bool(res.get("ok"))
        if tokens:
            (revoked if ok_any else revoke_failed).append(base)
        # sin tokens (p.ej. solo quedaba el marker parcial) no hay nada que revocar
        # afuera — el borrado local de abajo es el único movimiento.

        # borrado local INMEDIATO e incondicional (la parte irreversible del ticket)
        for prov in (base,
                     f"{base}{repo._OAUTH_COMPANION_SUFFIX}",
                     f"{base}{repo._OAUTH_PARTIAL_SUFFIX}"):
            if repo.delete_key(conn, user_id, prov):
                removed_local.append(prov)

    # vault filesystem del motor de inspección: credenciales de MCPs forjados + sesiones
    # browser cifradas viven bajo u/<slug(user_id)>/ — se van YA, junto con los OAuth.
    _rmtree(_SYNTH_BELTS / "u" / _slug(user_id))

    return {"revoked": revoked, "revoke_failed": revoke_failed,
            "removed_local": removed_local}


# ── movimiento 1+2: pedido de borrado ────────────────────────────────────────────

def delete_account(conn, user_id: str, *,
                   http_post: Optional[Callable] = None) -> Optional[dict[str, Any]]:
    """Ejecuta el pedido de borrado: soft-delete (mata el acceso YA) + revocación OAuth
    instantánea + cancela jobs pendientes + outbox del mail honesto. Idempotente (segunda
    llamada conserva las fechas del primer pedido). None si el user no existe.

    ORDEN (review MEDIUM): el soft-delete va PRIMERO — el corte de acceso NO puede depender de
    que la revocación OAuth tenga éxito. La revocación descifra tokens y pega HTTP a proveedores;
    si eso lanzara (decrypt roto, red caída), el acceso IGUAL ya murió. La revocación es
    best-effort y va aislada en try/except: jamás bloquea el borrado."""
    user = repo.get_user(conn, user_id)
    if user is None:
        return None

    # 1) SOFT-DELETE PRIMERO: el acceso muere YA, pase lo que pase con la revocación.
    marked = repo.soft_delete_user(conn, user_id)
    if marked is None:
        return None

    # 2) REVOCACIÓN OAuth instantánea (irreversible) — aislada: un fallo NO revierte el borrado.
    try:
        revocation = revoke_all_oauth(conn, user_id, http_post=http_post)
    except Exception:
        try:
            conn.rollback()   # la revocación envenenó la txn (p.ej. delete_key a mitad) → sanear
        except Exception:
            pass
        revocation = {"revoked": [], "revoke_failed": ["<error>"], "removed_local": []}

    # jobs pendientes/corriendo del usuario: no arrancan ni renacen con la cuenta muerta
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE job_queue SET status = 'dead', error = 'account_deleted',"
            " finished_at = now() WHERE user_id = %s AND status IN ('queued','running')",
            (user_id,),
        )
        jobs_cancelled = cur.rowcount
        cur.execute(
            "INSERT INTO historial (user_id, event, detail) VALUES (%s, %s, %s)",
            (user_id, "account_delete_requested",
             json.dumps({"purge_after": marked.get("purge_after"),
                         "oauth_revoked": revocation["revoked"],
                         "oauth_revoke_failed": revocation["revoke_failed"]})),
        )
    conn.commit()

    copy = _deletion_copy(marked.get("purge_after") or "")
    mail = _write_outbox_mail(user.get("email") or "", copy)
    return {
        "deleted": True,
        "deleted_at": marked.get("deleted_at"),
        "purge_at": marked.get("purge_after"),
        "purge_date": copy["purge_date"],
        "oauth_revoked": revocation["revoked"],
        "oauth_revoke_failed": revocation["revoke_failed"],
        "jobs_cancelled": jobs_cancelled,
        "copy": {"es": copy["es"], "en": copy["en"]},
        "mail_outbox": mail.get("written", False),
    }


# ── movimiento 3: purga total día 30 ─────────────────────────────────────────────

def purge_user(conn, user_id: str, *, force: bool = False) -> dict[str, Any]:
    """Purga TOTAL e irreversible de un usuario. Exige cuenta en soft-delete (guard:
    jamás purga una cuenta activa) salvo force=True (solo tests). El orden importa:
    primero se CAPTURAN ids/uris (desaparecen con los DELETE), después los deletes
    explícitos de lo que el CASCADE no cubre, al final DELETE users (cascadea el resto)
    y el barrido de disco."""
    state = repo.user_deleted_state(conn, user_id)
    if state is None:
        return {"purged": False, "reason": "no_user"}
    if state.get("deleted_at") is None and not force:
        return {"purged": False, "reason": "not_deleted"}

    counts: dict[str, int] = {}
    with conn.cursor() as cur:
        # billing_schema.sql va APARTE de las migraciones — en una DB sin billing esas
        # tablas no existen y el DELETE reventaría la transacción entera.
        # [Casa 2 · 2.4] `information_schema` es de Postgres; en SQLite el catálogo es
        # `sqlite_master`. El traductor NO lo caza (no es un PG-ismo de _NO_TRADUCIBLE):
        # pasaría y fallaría en ejecución con `no such table: information_schema.tables`.
        # En el cliente las tablas billing_* del plano de control normalmente NO existen
        # (billing_schema.sql no se aplica) → lista vacía → el loop de DELETE se saltea.
        if _es_cliente():
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
                " AND name IN ('billing_runs_ingested','billing_stripe_events')"
            )
        else:
            cur.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
                " AND table_name IN ('billing_runs_ingested','billing_stripe_events')"
            )
        billing_tables = [r[0] for r in cur.fetchall()]
        # ── captura ANTES de borrar ──
        cur.execute("SELECT id FROM puppets WHERE owner_id = %s", (user_id,))
        puppet_ids = [str(r[0]) for r in cur.fetchall()]
        # runs a purgar = SÓLO los del propio usuario (review LOW): un run de OTRO usuario sobre
        # un puppet nuestro es data ajena — el CASCADE de puppets le hará SET NULL su puppet_id,
        # pero NO lo borramos. (Un run del dueño siempre lleva su user_id = el runner.)
        cur.execute("SELECT id, space_id FROM runs WHERE user_id = %s", (user_id,))
        rows = cur.fetchall()
        run_ids = [str(r[0]) for r in rows]
        space_ids = sorted({str(r[1]) for r in rows if r[1]})
        cur.execute("SELECT uri FROM outputs WHERE run_id = ANY(%s::uuid[])", (run_ids,))
        output_uris = [r[0] for r in cur.fetchall() if r[0]]

        # ── deletes explícitos (lo que el CASCADE de users NO cubre) ──
        # runs.user_id y job_queue.user_id son ON DELETE SET NULL → quedarían huérfanas;
        # billing_runs_ingested / billing_stripe_events no tienen FK.
        cur.execute("DELETE FROM runs WHERE id = ANY(%s::uuid[])", (run_ids,))
        counts["runs"] = cur.rowcount          # cascadea outputs, instrumentation_logs,
        #                                        held_actions(run_id); job_queue.run_id→NULL
        cur.execute("DELETE FROM job_queue WHERE user_id = %s", (user_id,))
        counts["job_queue"] = cur.rowcount
        cur.execute("DELETE FROM held_actions WHERE user_id = %s", (user_id,))
        counts["held_actions"] = cur.rowcount  # residuo de runs ya purgados antes
        for tbl in billing_tables:
            cur.execute(f"DELETE FROM {tbl} WHERE user_id = %s", (user_id,))
            counts[tbl] = cur.rowcount
        # ── el resto cascadea desde users: puppets(→agent/shared memories, knowledge,
        #    chats→messages, instructions), keys, historial, account_memories, billing_* ──
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        counts["users"] = cur.rowcount
    conn.commit()

    # ── disco (después del commit: si la tx falla, no borramos archivos de una cuenta viva) ──
    disk: list[str] = []
    if _rmtree(_DATA / "rag" / user_id):          # RAG legacy (rag_store.py): data/rag/<user_id>/
        disk.append(f"rag/{user_id}")
    # ÍNDICE DE CONOCIMIENTO C1 self-hosted (review HIGH): un knowledge.db por COMPOSICIÓN, keyed por
    # puppet_id bajo rag_dir_root()/<composition_id>/ — NO por user_id. El CASCADE de Postgres NO lo
    # cubre (en modo self_hosted las tablas knowledge_* están vacías; la data cruda vive en el sqlite
    # de disco). Se barre por los puppet_ids capturados, en la raíz que honra PUPPET_RAG_DIR.
    _ragroot = _rag_root()
    for pid in puppet_ids:
        if _rmtree(_ragroot / pid):
            disk.append(f"rag/{pid}")
    if _rmtree(_SYNTH_BELTS / "u" / _slug(user_id)):
        disk.append(f"synth_belts/u/{_slug(user_id)}")
    for rid in run_ids:
        if _rmtree(_DATA / "run_outputs" / rid):
            disk.append(f"run_outputs/{rid}")
    for uri in output_uris:
        p = Path(uri)
        p = p if p.is_absolute() else (_REPO_ROOT / uri)
        try:
            resolved = p.resolve()
            if str(resolved).startswith(str(_DATA.resolve()) + "/") and resolved.is_file():
                resolved.unlink(missing_ok=True)
                disk.append(str(resolved.relative_to(_DATA)))
        except OSError:
            pass
    # espacios: solo si NINGÚN run vivo de otro usuario sigue apuntando al space
    with conn.cursor() as cur:
        for sid in space_ids:
            cur.execute("SELECT 1 FROM runs WHERE space_id = %s LIMIT 1", (sid,))
            if cur.fetchone() is None and _rmtree(_DATA / "espacios" / sid):
                disk.append(f"espacios/{sid}")
    # artifacts: sesiones cuyo owner (meta) era este usuario
    try:
        from app.phase1 import artifact_store
        # [Gate 4 · Fase 2] art_root() es función (aleph_paths decide por rol). Con la
        # constante vieja este purge habría borrado el DIRECTORIO EQUIVOCADO tras la
        # mudanza del almacén — el borrado de cuenta tiene que seguir al almacén.
        art_root = Path(artifact_store.art_root())
        if art_root.exists():
            for f in art_root.iterdir():
                sid = f.stem
                try:
                    if artifact_store.get_owner(sid) == user_id:
                        f.unlink(missing_ok=True)
                        disk.append(f"artifacts/{f.name}")
                except Exception:
                    continue
    except Exception:
        pass

    return {"purged": True, "user_id": user_id, "counts": counts,
            "puppet_ids": puppet_ids, "run_ids": run_ids, "space_ids": space_ids,
            "disk_removed": disk}


def purge_expired(conn) -> list[dict[str, Any]]:
    """Purga todas las cuentas cuya ventana venció. Idempotente; se llama desde el
    runner periódico (main.py lifespan), el CLI y lazy desde el login post-ventana."""
    results = []
    for user in repo.list_purge_due(conn):
        results.append(purge_user(conn, user["id"]))
    return results


if __name__ == "__main__":
    # CLI operativo:  cd product/backend &&
    #   ./.venv/bin/python -m app.phase1.account_deletion            → purga lo vencido
    #   ./.venv/bin/python -m app.phase1.account_deletion --user ID  → purga UNA cuenta
    #                                                                  (exige soft-delete)
    import argparse

    ap = argparse.ArgumentParser(description="Purga día-30 del borrado de cuenta")
    ap.add_argument("--user", help="purgar SOLO este user_id (debe estar en soft-delete)")
    args = ap.parse_args()
    c = repo.get_conn()
    try:
        out = purge_user(c, args.user) if args.user else purge_expired(c)
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    finally:
        c.close()
