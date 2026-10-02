"""TICKET 2 · BORRADO DE CUENTA — soft-delete + revocación OAuth instantánea + purga
cero-huérfanas (probado, no razonado).

Contra la vara de la casa: HTTP real (TestClient sobre app.main.app COMPLETA — el
middleware que mata el acceso vive ahí) + Postgres real + disco real. Secuencia:

  §0  guard: JAMÁS contra la base compartida (exige PG_DB explícito ≠ puppet_ai).
  §1  SIEMBRA un usuario con vida completa: puppet, run+outputs+instrumentation+held,
      job encolado, chat+mensajes, knowledge, memorias (agente/compartida/cuenta),
      keys BYOK + OAuth con companions, billing, historial, instrucciones, archivos
      en disco (rag/, espacios/, run_outputs/, artifacts/, synth_belts/).
  §2  REVOCACIÓN instantánea (unidad, http_post stub): revoke_url del descriptor se
      LLAMA con los tokens y las filas OAuth mueren YA; la BYOK sobrevive congelada.
  §3  DELETE /v1/account (endpoint): acceso muere YA (401 account_deleted con el
      token viejo, Bearer y ?token=), fechas exactas, outbox escrito, copy honesto.
  §4  RE-LOGIN dentro de la ventana: reactivated:true, datos intactos, el token
      viejo vuelve a servir. OAuth NO volvió (irreversible).
  §5  PURGA día-30 (ventana forzada a ayer): login → account_purged (purga lazy) y
      CERO FILAS HUÉRFANAS — barrido dinámico por information_schema (toda tabla con
      user_id/owner_id) + todas las tablas hijas por los ids capturados + disco.
  §6  post-purga: registrar el mismo email da cuenta FRESCA (el email queda libre).

Correr:  cd product/backend && set -a && . ../../infra/.env && set +a && \
         PG_DB=puppet_ai_seguridad ./.venv/bin/python ../../qa/verify_borrado_cuenta.py
"""
from __future__ import annotations
import json, os, sys, uuid
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
for p in (str(_REPO / "platform"), str(_REPO / "product" / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

# §0 — guard de base: la purga borra de verdad; este verify exige base propia.
_pgdb = os.environ.get("PG_DB", "").strip()
if not _pgdb or _pgdb == "puppet_ai":
    print("✗ ABORT: seteá PG_DB a una base AISLADA (≠ puppet_ai). "
          "Este verify purga usuarios de verdad.")
    sys.exit(2)

from app.phase1 import repo, account_deletion  # noqa: E402
from app.main import app                        # noqa: E402  (middleware incluido)
from fastapi.testclient import TestClient       # noqa: E402

client = TestClient(app, raise_server_exceptions=False)

_fail = []
def ok(cond, label):
    print(("  ✓ " if cond else "  ✗ ") + label)
    if not cond: _fail.append(label)

_DATA = _REPO / "product" / "backend" / "data"
EMAIL = f"borrado-{uuid.uuid4().hex[:8]}@test.local"
PASSWORD = "secreta-123"

conn = repo.get_conn()

# ── §1 · SIEMBRA ───────────────────────────────────────────────────────────────
print("== 1 · siembra: un usuario con vida completa ==")
r = client.post("/v1/auth/register", json={"email": EMAIL, "password": PASSWORD})
assert r.status_code == 201, r.text
UID = r.json()["id"]
TOK = {"Authorization": f"Bearer {r.json()['session_token']}"}

def _sql(q, params=()):
    with conn.cursor() as cur:
        cur.execute(q, params)
        row = cur.fetchone() if cur.description else None
    conn.commit()
    return str(row[0]) if row else None

SPACE = f"sp-borrado-{uuid.uuid4().hex[:8]}"
puppet = repo.create_puppet(conn, owner_id=UID, name="borrame", nicho="general",
                            config={"schema_version": "v1"})
PID = puppet["id"]
RID = _sql("INSERT INTO runs (puppet_id, user_id, space_id, intent, status)"
           " VALUES (%s,%s,%s,'test','done') RETURNING id", (PID, UID, SPACE))
OUT_URI = f"product/backend/data/run_outputs/{RID}/salida.txt"
_sql("INSERT INTO outputs (run_id, kind, uri) VALUES (%s,'text',%s) RETURNING id", (RID, OUT_URI))
_sql("INSERT INTO instrumentation_logs (run_id, belt, trayectoria) VALUES (%s,'{}','[]') RETURNING id", (RID,))
HID = _sql("INSERT INTO held_actions (run_id, user_id, recipe, server, tool, args)"
           " VALUES (%s,%s,'{}','srv','send','{}') RETURNING id", (RID, UID))
JID = _sql("INSERT INTO job_queue (kind, status, user_id) VALUES ('puppet_run','queued',%s) RETURNING id", (UID,))
CHID = _sql("INSERT INTO chats (user_id, puppet_id, title) VALUES (%s,%s,'hilo') RETURNING id", (UID, PID))
_sql("INSERT INTO chat_messages (chat_id, role, content) VALUES (%s,'user','hola') RETURNING id", (CHID,))
KDID = _sql("INSERT INTO knowledge_docs (composition_id, doc_name) VALUES (%s,'doc.md') RETURNING id", (PID,))
_sql("INSERT INTO knowledge_chunks (composition_id, doc_id, chunk_ix, content)"
     " VALUES (%s,%s,0,'chunk') RETURNING id", (PID, KDID))
_sql("INSERT INTO agent_memories (puppet_id, content) VALUES (%s,'memoria del agente') RETURNING id", (PID,))
_sql("INSERT INTO shared_memories (composition_id, content) VALUES (%s,'memoria compartida') RETURNING id", (PID,))
_sql("INSERT INTO instructions (user_id, puppet_id, content) VALUES (%s,%s,'sé breve') RETURNING id", (UID, PID))
repo.add_account_memory(conn, owner_id=UID, content="vive en Quito", source="user", pinned=True)
_sql("INSERT INTO historial (user_id, event) VALUES (%s,'ran') RETURNING id", (UID,))
# billing (schema aparte — presente en esta base clonada)
_sql("INSERT INTO billing_ledger (user_id, run_id, seq, kind) VALUES (%s,%s,1,'llm') RETURNING seq", (UID, RID))
_sql("INSERT INTO billing_quota (user_id) VALUES (%s) RETURNING user_id", (UID,))
_sql("INSERT INTO billing_runs_ingested (run_id, user_id) VALUES (%s,%s) RETURNING run_id", (RID, UID))
_sql("INSERT INTO billing_stripe_events (event_id, user_id) VALUES (%s,%s) RETURNING event_id",
     (f"evt-{uuid.uuid4().hex[:8]}", UID))
# keys: BYOK (congelable) + DOS conectores OAuth (gmail tiene revoke_url; orcid no)
repo.upsert_key(conn, user_id=UID, provider="exa", secret="exa-key-frozen-1234")
repo.upsert_key(conn, user_id=UID, provider="gmail", secret="ya29.fake-access-token")
repo.upsert_key(conn, user_id=UID, provider="gmail__oauth",
                secret=json.dumps({"refresh_token": "1//fake-refresh", "expires_in": 3599}))
repo.upsert_key(conn, user_id=UID, provider="orcid", secret="orcid-access-tok")
repo.upsert_key(conn, user_id=UID, provider="orcid__oauth_partial",
                secret=json.dumps({"partial": True}))
# disco: rag/, run_outputs/, espacios/, artifacts/, synth_belts/
rag_dir = _DATA / "rag" / UID / "agente-x"; rag_dir.mkdir(parents=True, exist_ok=True)
(rag_dir / "doc.md").write_text("conocimiento", encoding="utf-8")
# ÍNDICE C1 self-hosted: knowledge.db keyed por composition_id (=puppet_id), NO por user_id
# (review HIGH). Debe purgarse igual — sin esto el corpus privado en texto plano sobrevive.
know_dir = _DATA / "rag" / PID; know_dir.mkdir(parents=True, exist_ok=True)
(know_dir / "knowledge.db").write_text("SQLite format 3\x00docs+chunks en texto plano", encoding="utf-8")
out_dir = _DATA / "run_outputs" / RID; out_dir.mkdir(parents=True, exist_ok=True)
(out_dir / "salida.txt").write_text("output real", encoding="utf-8")
esp_dir = _DATA / "espacios" / SPACE; esp_dir.mkdir(parents=True, exist_ok=True)
(esp_dir / "events.jsonl").write_text("{}\n", encoding="utf-8")
from app.phase1 import artifact_store
ART_SID = f"art-borrado-{uuid.uuid4().hex[:6]}"
artifact_store.claim_owner(ART_SID, UID)
synth_dir = _DATA / "synth_belts" / "u" / account_deletion._slug(UID) / "mi-mcp"
synth_dir.mkdir(parents=True, exist_ok=True)
(synth_dir / "credentials.enc").write_text("cifrado", encoding="utf-8")
ok(True, f"usuario {UID[:8]}… sembrado con {PID[:8]}…/{RID[:8]}…/{SPACE}")

# ── §2 · revocación instantánea (unidad con http_post stub) ─────────────────────
print("== 2 · revocación OAuth instantánea (best-effort HTTP + delete local YA) ==")
_revoke_calls = []
def _http_stub(url, form, timeout=20):
    _revoke_calls.append({"url": url, "token": form.get("token")})
    return 200, {}
rev = account_deletion.revoke_all_oauth(conn, UID, http_post=_http_stub)
gmail_calls = [c for c in _revoke_calls if "oauth2.googleapis.com" in c["url"]]
tokens_sent = {c["token"] for c in gmail_calls}
ok(len(gmail_calls) == 2 and tokens_sent == {"ya29.fake-access-token", "1//fake-refresh"},
   "gmail: revoke_url llamado con access Y refresh token")
ok("gmail" in rev["revoked"], "gmail figura revocado (el proveedor confirmó)")
ok("orcid" in rev["revoke_failed"] or "orcid" not in rev["revoked"],
   "orcid honesto: sin revoke_url no se declara revocado")
provs = {k["provider"] for k in repo.list_keys(conn, UID)}
ok(not ({"gmail", "gmail__oauth", "orcid", "orcid__oauth_partial"} & provs),
   "TODAS las filas OAuth (base+companions) borradas del vault YA")
ok("exa" in provs, "la BYOK no-OAuth sigue (congelada, no es OAuth)")
ok(not synth_dir.exists(), "vault filesystem del motor (synth_belts/u/<slug>) barrido")

# ── §2b · REORDEN (review): un revoke que LANZA no bloquea el soft-delete ──────
print("== 2b · resiliencia: revoke que explota NO impide matar el acceso ==")
# usuario aparte con una fila OAuth; http_post que lanza → revoke_all_oauth truena adentro
UID2 = client.post("/v1/auth/register", json={"email": f"reorden-{uuid.uuid4().hex[:6]}@t.local",
                                              "password": "x123456"}).json()["id"]
repo.upsert_key(conn, user_id=UID2, provider="gmail", secret="tok")
repo.upsert_key(conn, user_id=UID2, provider="gmail__oauth", secret=json.dumps({"refresh_token": "r"}))
def _http_boom(url, form, timeout=8): raise RuntimeError("proveedor caído")
out2 = account_deletion.delete_account(conn, UID2, http_post=_http_boom)
ok(out2 and out2.get("deleted") is True, "el borrado se completa aunque el revoke HTTP truene")
ok(repo.user_deleted_state(conn, UID2).get("deleted_at"), "soft-delete aplicado (acceso muerto) pese al fallo del revoke")
account_deletion.purge_user(conn, UID2, force=True)   # limpieza

# ── §3 · DELETE /v1/account: el acceso muere YA ─────────────────────────────────
print("== 3 · DELETE /v1/account (endpoint completo) ==")
r = client.request("DELETE", "/v1/account", headers=TOK)
body = r.json() if r.status_code == 200 else {}
ok(r.status_code == 200 and body.get("deleted") is True, "DELETE /v1/account → 200 deleted")
purge_at = body.get("purge_at") or ""
from datetime import datetime, timezone, timedelta
try:
    _delta = datetime.fromisoformat(purge_at) - datetime.now(timezone.utc)
    ok(timedelta(days=29) < _delta <= timedelta(days=30, minutes=5),
       f"purge_at exacto a +30 días ({body.get('purge_date')})")
except ValueError:
    ok(False, "purge_at parseable")
ok(body.get("purge_date", "") in body.get("copy", {}).get("es", ""),
   "el copy ES trae la fecha exacta")
ok("desconectadas" in body.get("copy", {}).get("es", ""),
   "el copy dice que las conexiones externas ya fueron desconectadas")
ok(body.get("jobs_cancelled", 0) >= 1, "el job encolado fue cancelado")
ok(body.get("mail_outbox") is True, "mail escrito al outbox")
outbox = _DATA / "outbox" / "mails.jsonl"
last_mail = json.loads(outbox.read_text(encoding="utf-8").strip().splitlines()[-1]) if outbox.exists() else {}
ok(last_mail.get("to") == EMAIL and last_mail.get("purge_at") == purge_at
   and last_mail.get("transport") == "logged",
   "outbox honesto: mismo destinatario, MISMA fecha, transport=logged (no finge envío)")
# acceso muerto YA — Bearer y ?token=
r2 = client.get("/v1/account/memories", headers=TOK)
det2 = (r2.json() or {}).get("detail", {}) if r2.status_code == 401 else {}
ok(r2.status_code == 401 and det2.get("error") == "account_deleted",
   "Bearer viejo → 401 account_deleted (middleware)")
ok(det2.get("purge_at") == purge_at, "el 401 trae el purge_at (copy de reactivación)")
tok_raw = TOK["Authorization"].split(" ", 1)[1]
r3 = client.get(f"/v1/spaces/{SPACE}/stream", params={"token": tok_raw})
ok(r3.status_code == 401, "camino ?token= (SSE) también muere → 401")
r3b = client.request("DELETE", "/v1/account", headers=TOK)
ok(r3b.status_code == 401, "el propio DELETE repetido con el token muerto → 401 (idempotencia vía puerta)")
st = repo.user_deleted_state(conn, UID)
ok(bool(st and st.get("deleted_at")), "users.deleted_at seteado (datos congelados, no borrados)")
n_puppets = _sql("SELECT count(*) FROM puppets WHERE owner_id = %s", (UID,))
ok(n_puppets == "1", "los datos SIGUEN (congelados): puppet intacto")

# ── §4 · re-login dentro de la ventana = reactivar intacto ──────────────────────
print("== 4 · re-login dentro de la ventana ==")
r = client.post("/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
b = r.json() if r.status_code == 200 else {}
ok(r.status_code == 200 and b.get("reactivated") is True, "login → 200 reactivated:true")
ok(repo.user_deleted_state(conn, UID).get("deleted_at") is None, "deleted_at limpio (cuenta viva)")
r = client.get("/v1/account/memories", headers=TOK)
ok(r.status_code == 200, "el token VIEJO vuelve a servir (reactivación intacta)")
provs = {k["provider"] for k in repo.list_keys(conn, UID)}
ok("exa" in provs and "gmail" not in provs,
   "BYOK sigue; el OAuth revocado NO volvió (irreversible)")

# ── §5 · purga día-30: cero filas huérfanas ─────────────────────────────────────
print("== 5 · purga total (ventana vencida) + CERO HUÉRFANAS ==")
r = client.request("DELETE", "/v1/account", headers=TOK)
assert r.status_code == 200, r.text
_sql("UPDATE users SET purge_after = now() - interval '1 day' WHERE id = %s RETURNING id", (UID,))
# login post-ventana → purga LAZY + respuesta honesta
r = client.post("/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
det = (r.json() or {}).get("detail", {}) if r.status_code == 401 else {}
ok(r.status_code == 401 and det.get("error") == "account_purged",
   "login post-ventana → 401 account_purged (purga lazy ejecutada)")
ok(repo.get_user(conn, UID) is None, "la fila users ya no existe")

# 5a — barrido DINÁMICO: toda tabla del schema con columna owner-like debe dar 0.
with conn.cursor() as cur:
    cur.execute("""
        SELECT c.table_name, c.column_name FROM information_schema.columns c
        JOIN information_schema.tables t ON t.table_name = c.table_name
             AND t.table_schema = 'public' AND t.table_type = 'BASE TABLE'
        WHERE c.table_schema = 'public' AND c.column_name IN ('user_id','owner_id')
    """)
    owner_cols = cur.fetchall()
orphans = []
with conn.cursor() as cur:
    for tbl, col in owner_cols:
        cur.execute(f"SELECT count(*) FROM {tbl} WHERE {col} = %s", (UID,))
        n = cur.fetchone()[0]
        if n:
            orphans.append(f"{tbl}.{col}={n}")
ok(not orphans, f"CERO huérfanas por owner en las {len(owner_cols)} tablas con user_id/owner_id"
   + (f" — FUGA: {orphans}" if orphans else ""))

# 5b — hijas por ids capturados (lo que un owner-scan no ve).
child_checks = [
    ("puppets", "id", PID), ("runs", "id", RID), ("runs", "puppet_id", PID),
    ("outputs", "run_id", RID), ("instrumentation_logs", "run_id", RID),
    ("held_actions", "id", HID), ("held_actions", "run_id", RID),
    ("job_queue", "id", JID),
    ("chats", "id", CHID), ("chat_messages", "chat_id", CHID),
    ("knowledge_docs", "composition_id", PID), ("knowledge_chunks", "composition_id", PID),
    ("agent_memories", "puppet_id", PID), ("shared_memories", "composition_id", PID),
    ("instructions", "puppet_id", PID),
    ("billing_ledger", "run_id", RID), ("billing_runs_ingested", "run_id", RID),
]
leaks = []
with conn.cursor() as cur:
    for tbl, col, val in child_checks:
        cur.execute(f"SELECT count(*) FROM {tbl} WHERE {col} = %s", (val,))
        if cur.fetchone()[0]:
            leaks.append(f"{tbl}.{col}")
ok(not leaks, "CERO huérfanas en tablas hijas por ids capturados"
   + (f" — FUGA: {leaks}" if leaks else ""))

# 5c — disco
ok(not (_DATA / "rag" / UID).exists(), "disco: data/rag/<uid> purgado")
ok(not (_DATA / "rag" / PID).exists(), "disco: índice C1 data/rag/<composition_id>/knowledge.db purgado (review HIGH)")
ok(not out_dir.exists(), "disco: data/run_outputs/<run> purgado")
ok(not esp_dir.exists(), "disco: data/espacios/<space> purgado")
ok(artifact_store.get_owner(ART_SID) is None, "disco: artifact del usuario purgado")
ok(not (_DATA / "synth_belts" / "u" / account_deletion._slug(UID)).exists(),
   "disco: synth_belts/u/<slug> purgado")

# ── §6 · el email queda libre ───────────────────────────────────────────────────
print("== 6 · post-purga: el email se puede registrar de cero ==")
r = client.post("/v1/auth/register", json={"email": EMAIL, "password": "otra-clave-9"})
fresh = r.json() if r.status_code == 201 else {}
ok(r.status_code == 201 and fresh.get("id") != UID, "registro fresco con el mismo email (id nuevo)")
if r.status_code == 201:
    # limpieza del usuario fresco de prueba
    account_deletion.purge_user(conn, fresh["id"], force=True)

conn.close()
print()
if _fail:
    print(f"✗ {len(_fail)} fallas:"); [print("   -", f) for f in _fail]; sys.exit(1)
print("✓ TICKET 2 VERDE: soft-delete + revocación instantánea + reactivación + purga cero-huérfanas")
