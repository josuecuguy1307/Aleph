#!/usr/bin/env python3
"""
tests_safety.py — pruebas REALES de la capa de safety (stdlib, sin red, sin mocks).

Corre como script (`python platform/safety/tests_safety.py`) o bajo pytest. Aísla todo
estado en un DATA_ROOT temporal (no toca data/ de verdad) y fija límites chicos por env
ANTES de importar la capa, para ejercitar rate-limit/blast-radius rápido.

Cubre las TRES barras de la directiva T9:
  DONE-BAR 1: el recon rechaza una URL interna.
  DONE-BAR 2: un write masivo se puede frenar (blast-radius + kill-switch).
  DONE-BAR 3: un nicho legal-gated pide humano (y medicina-en-prod se bloquea).
"""
from __future__ import annotations

import os
import tempfile
import urllib.request

# ── aislar estado + límites chicos ANTES de importar la capa ──────────────────
os.environ["ALEPH_DATA_ROOT"] = tempfile.mkdtemp(prefix="aleph-safety-test-")
os.environ["ALEPH_RECON_RATE_MAX"] = "3"
os.environ["ALEPH_RECON_RATE_WINDOW_S"] = "3600"
os.environ["ALEPH_WRITE_BLAST_MAX"] = "5"
os.environ["ALEPH_WRITE_BLAST_WINDOW_S"] = "600"
os.environ.pop("ALEPH_SAFETY_ALLOW_PRIVATE_TARGETS", None)
os.environ.pop("ALEPH_INSPECT_ALLOWLIST", None)

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # .../platform

from safety import audit_log, guards, kill_switch, legal_gates, privacy, url_guard
from safety.guards import SafetyBlocked
from safety.url_guard import UrlBlocked


# ── DONE-BAR 1 · anti-SSRF ────────────────────────────────────────────────────

BLOCKED_URLS = [
    "http://169.254.169.254/latest/meta-data/",   # AWS metadata — el blanco #1
    "http://169.254.169.254/",
    "http://100.100.100.200/",                     # Alibaba metadata
    "http://localhost/admin",                      # resuelve a loopback
    "http://127.0.0.1:6379/",                      # redis local
    "http://127.0.0.1/",
    "http://[::1]:8080/",                          # loopback v6
    "http://10.0.0.5/internal",                    # LAN privada
    "http://192.168.1.1/",
    "http://172.16.0.10/",
    "http://[::ffff:127.0.0.1]/",                  # v4-mapped loopback (no esquiva)
    "file:///etc/passwd",                          # esquema prohibido
    "gopher://127.0.0.1:6379/_INFO",               # esquema prohibido
    "http://user:pass@evil.example.com/",          # credenciales embebidas
    "ftp://internal/",
]

PUBLIC_OK = [
    "http://93.184.216.34/",        # example.com (IP pública literal, sin DNS)
    "https://1.1.1.1/",             # cloudflare
    "https://8.8.8.8/",             # google dns
]


def test_ssrf_blocks_internal():
    for u in BLOCKED_URLS:
        ok, reason = url_guard.is_safe(u)
        assert not ok, f"DEBÍA bloquear {u!r} (no lo hizo)"
        try:
            url_guard.assert_inspectable(u)
            raise AssertionError(f"assert_inspectable NO levantó para {u!r}")
        except UrlBlocked:
            pass


def test_ssrf_allows_public_literals():
    for u in PUBLIC_OK:
        ok, reason = url_guard.is_safe(u)
        assert ok, f"DEBÍA permitir {u!r} pero lo bloqueó por {reason!r}"


def test_local_fixture_flag_allows_loopback_only():
    # el fixture benigno (loopback) pasa SOLO con allow_local_fixture
    ok, _ = url_guard.is_safe("http://127.0.0.1:8091/", allow_local_fixture=True)
    assert ok, "loopback fixture debía permitirse con allow_local_fixture"
    # pero metadata NUNCA, ni con el flag
    ok2, _ = url_guard.is_safe("http://169.254.169.254/", allow_local_fixture=True)
    assert not ok2, "metadata NO debe permitirse ni con allow_local_fixture"


def test_public_opener_rejects_initial_private_url_before_open(monkeypatch):
    def no_debe_abrir(*_args, **_kwargs):
        raise AssertionError("el transporte no debe recibir una URL privada")

    monkeypatch.setattr(url_guard._PUBLIC_OPENER, "open", no_debe_abrir)
    try:
        url_guard.open_public_url("http://127.0.0.1:6379/models", timeout=1)
        raise AssertionError("open_public_url debía bloquear loopback")
    except UrlBlocked as exc:
        assert exc.reason == "loopback"


def test_public_opener_revalidates_redirect_to_private():
    handler = url_guard._SafeRedirectHandler()
    req = urllib.request.Request("https://93.184.216.34/models")
    try:
        handler.redirect_request(req, None, 302, "Found", {},
                                 "http://169.254.169.254/latest/meta-data/")
        raise AssertionError("el redirect a metadata debía bloquearse")
    except UrlBlocked as exc:
        assert exc.reason == "cloud-metadata-ip"


def test_cross_origin_redirect_does_not_forward_connector_credentials():
    handler = url_guard._SafeRedirectHandler()
    req = urllib.request.Request(
        "https://93.184.216.34/models",
        headers={"Authorization": "Bearer secret", "x-api-key": "secret"},
    )
    redirected = handler.redirect_request(
        req, None, 302, "Found", {}, "https://1.1.1.1/models")
    assert not any(name.lower() in ("authorization", "x-api-key")
                   for name in redirected.headers)


def test_public_opener_rechecks_and_pins_dns_answer(monkeypatch):
    answers = iter([
        [(2, 1, 6, "", ("93.184.216.34", 80))],
        [(2, 1, 6, "", ("127.0.0.1", 80))],
    ])
    monkeypatch.setattr(url_guard.socket, "getaddrinfo",
                        lambda *_args, **_kwargs: next(answers))

    def no_debe_conectar(*_args, **_kwargs):
        raise AssertionError("no debe abrir socket después del cambio DNS")

    monkeypatch.setattr(url_guard.socket, "create_connection", no_debe_conectar)
    try:
        url_guard.open_public_url("http://rebind.example/models", timeout=1)
        raise AssertionError("la segunda respuesta DNS privada debía bloquearse")
    except UrlBlocked as exc:
        assert "loopback" in exc.reason


def test_guard_recon_raises_on_internal():
    try:
        guards.guard_recon("http://169.254.169.254/", subject="t-ssrf")
        raise AssertionError("guard_recon NO frenó la metadata")
    except SafetyBlocked as e:
        assert "ssrf_reason" in e.meta or "rate" in str(e).lower()


# ── DONE-BAR 1b · rate-limit ──────────────────────────────────────────────────

def test_recon_rate_limit():
    subj = "t-rate-unique"
    # RECON_RATE_MAX=3: 3 pasan (target público), el 4º se frena por cuota
    for i in range(3):
        guards.guard_recon("http://93.184.216.34/", subject=subj)
    try:
        guards.guard_recon("http://93.184.216.34/", subject=subj)
        raise AssertionError("el 4º recon debió frenarse por rate-limit")
    except SafetyBlocked as e:
        assert "rate" in str(e).lower()


# ── DONE-BAR 2 · blast-radius + kill-switch ──────────────────────────────────

def test_blast_radius_auto_trips():
    subj = "t-blast-unique"
    # WRITE_BLAST_MAX=5: 5 writes pasan; el 6º dispara auto-trip y se bloquea
    for i in range(5):
        guards.guard_replay("https://93.184.216.34/api", subject=subj, is_write=True)
    try:
        guards.guard_replay("https://93.184.216.34/api", subject=subj, is_write=True)
        raise AssertionError("el write masivo (6º) debió frenarse por blast-radius")
    except SafetyBlocked as e:
        assert "blast" in str(e).lower() or "kill" in str(e).lower()
    # y el kill-switch del usuario quedó trabado (sobrevive a futuros writes)
    assert kill_switch.is_tripped(subject=subj) is not None


def test_kill_switch_manual_then_reset():
    subj = "t-kill-unique"
    kill_switch.trip(f"user:{subj}", "prueba")
    try:
        guards.guard_agent_write(subj, tool="send_email")
        raise AssertionError("kill-switch trabado debió frenar el write")
    except SafetyBlocked:
        pass
    kill_switch.reset(f"user:{subj}")
    guards.guard_agent_write(subj, tool="send_email")  # ya no levanta


def test_reset_clears_blast_window():
    # tras un auto-trip por blast, el reset debe dar borrón y cuenta nueva (si no, el
    # contador sigue sobre el cap y el próximo write re-traba — regresión real).
    subj = "t-reset-blast"
    for _ in range(5):
        guards.guard_agent_write(subj, tool="x")
    try:
        guards.guard_agent_write(subj, tool="x")  # 6º → auto-trip
        raise AssertionError("debió auto-trabarse")
    except SafetyBlocked:
        pass
    kill_switch.reset(f"user:{subj}")
    # ahora N writes seguidos deben volver a pasar (ventana reseteada)
    for _ in range(5):
        guards.guard_agent_write(subj, tool="x")


def test_global_kill_blocks_everyone():
    kill_switch.trip("global", "incidente")
    try:
        guards.guard_agent_write("cualquiera", tool="x")
        raise AssertionError("kill global debió frenar a todos")
    except SafetyBlocked:
        pass
    finally:
        kill_switch.reset("global")


# ── DONE-BAR 3 · gates legales por nicho ──────────────────────────────────────

def test_legal_ingenieria_requires_human():
    d = legal_gates.enforce({"meta": {"nicho": "ingenieria"}}, env="prod")
    assert d["allow"] is True
    assert d["require_human"] is True
    assert d["notice"]


def test_legal_medicina_blocked_in_prod():
    prod = legal_gates.enforce({"meta": {"nicho": "medicina"}}, env="prod")
    assert prod["allow"] is False, "medicina en prod debe bloquearse (HIPAA)"
    dev = legal_gates.enforce({"meta": {"nicho": "medicina"}}, env="dev")
    assert dev["allow"] is True and dev["require_human"] is True


def test_legal_finanzas_notice():
    d = legal_gates.enforce({"meta": {"nicho": "finanzas"}}, env="prod")
    assert d["allow"] is True
    assert "asesoría" in (d["notice"] or "").lower()


def test_legal_aliases_and_default():
    assert legal_gates.enforce({"meta": {"nicho": "Ingeniería"}})["require_human"] is True
    assert legal_gates.enforce({"meta": {"nicho": "engineering"}})["require_human"] is True
    # nicho sin obligación → abierto
    assert legal_gates.enforce({"meta": {"nicho": "demo-test"}})["require_human"] is False


# ── audit chain + privacy ─────────────────────────────────────────────────────

def test_audit_chain_intact():
    audit_log.record("test.event", subject="t", target="x", decision="allow", k=1)
    ok, err = audit_log.verify_chain()
    assert ok, f"cadena de auditoría rota: {err}"


def test_audit_chain_detects_tamper():
    audit_log.record("test.pre", subject="t", decision="allow")
    p = Path(os.environ["ALEPH_DATA_ROOT"]) / "safety" / "audit.jsonl"
    original = p.read_text("utf-8")          # snapshot para restaurar (no contaminar otros tests)
    try:
        lines = original.splitlines()
        assert lines, "no hay audit para manipular"
        # manipular la primera línea (cambiar el target) sin recomputar el hash
        import json
        first = json.loads(lines[0])
        first["target"] = "MANIPULADO"
        lines[0] = json.dumps(first, ensure_ascii=False)
        p.write_text("\n".join(lines) + "\n", "utf-8")
        ok, err = audit_log.verify_chain()
        assert not ok, "la verificación NO detectó la manipulación"
    finally:
        p.write_text(original, "utf-8")      # restaurar la cadena íntegra


def test_privacy_purge_dryrun_and_apply():
    data_root = Path(os.environ["ALEPH_DATA_ROOT"])
    # sembrar un space + un run output a mano (ids provistos, sin DB)
    sid, rid = "recon-pvtest", "run-pvtest"
    (data_root / "espacios" / sid).mkdir(parents=True, exist_ok=True)
    (data_root / "espacios" / sid / "events.jsonl").write_text("{}\n", "utf-8")
    (data_root / "run_outputs" / rid).mkdir(parents=True, exist_ok=True)
    (data_root / "run_outputs" / rid / "obra.xlsx").write_text("x", "utf-8")

    dry = privacy.purge_user("u-pv", space_ids=[sid], run_ids=[rid], apply=False)
    assert (data_root / "espacios" / sid).exists(), "dry-run NO debe borrar"
    assert dry["apply"] is False

    done = privacy.purge_user("u-pv", space_ids=[sid], run_ids=[rid], apply=True)
    assert not (data_root / "espacios" / sid).exists(), "apply debió borrar el space"
    assert not (data_root / "run_outputs" / rid).exists(), "apply debió borrar el run"
    assert done["apply"] is True


def test_privacy_contained_refuses_outside():
    # no debe borrar fuera de DATA_ROOT
    rec = privacy._rm(Path("/etc/hosts"), apply=True)
    assert rec.get("refused") == "fuera-de-data-root"
    assert Path("/etc/hosts").exists()


# ── runner sin pytest ─────────────────────────────────────────────────────────

def _run_all() -> int:
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  ✗ {t.__name__}: {type(exc).__name__}: {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed  (DATA_ROOT={os.environ['ALEPH_DATA_ROOT']})")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
