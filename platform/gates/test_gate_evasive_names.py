#!/usr/bin/env python3
"""
test_gate_evasive_names.py — REGRESIÓN del bypass de money-touch por nombre evasivo
(hallazgo del security-reviewer, cierre Fase 2, 2026-06-15).

Bug: `_is_obvious_read` matcheaba los read-hints por SUBSTRING, y "count" ∈ "account",
así que `fund_account` / `account_debit` / `get_paid` clasificaban como LECTURA →
`auto-ejecuta` → una tool que mueve plata corría SIN OK. Confirmado con el MISMO
`build_enforced_gate` que usa el assembler de prod.

Cura: (1) read-hints por TOKEN COMPLETO (account ya no contiene el token 'count');
(2) raíces money de defensa-en-profundidad en recipe_enforcer (fund_/debit/_paid/…)
que caen a la regla MANDATORY (corre primero). money gana cualquier empate.

Este test corre contra el factory de PROD (build_enforced_gate) — el mismo path.
Run: python3 test_gate_evasive_names.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))

import recipe_enforcer as enf  # noqa: E402

_passed = 0
_failed = 0


def check(name, cond, detail=""):
    global _passed, _failed
    mark = "PASS" if cond else "FAIL"
    if cond:
        _passed += 1
    else:
        _failed += 1
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))


def _recipe():
    return {
        "schema_version": "v1",
        "meta": {"name": "Evasive Names", "nicho": "finanzas"},
        "model": {"primary": "x", "base_url": "http://127.0.0.1:0/v1",
                  "temperature": 0, "max_tokens": 64, "max_turns": 2},
        "belt": {"belt_ref": "x", "tool_filters": {}},
        "framing": {"inline": "t"}, "rag": {"enabled": False}, "keys": {},
        "gates": {"money_touch": "off", "send": "off"},  # peor caso: receta intenta apagar
    }


# ── 1. nombres money EVASIVOS caen a needs_ok por el factory de PROD ─────────────
def test_evasive_money_names_gated():
    gate = enf.build_enforced_gate(_recipe())
    evasive = ["fund_account", "account_debit", "get_paid", "deduct_balance",
               "topup_wallet", "debit_card_charge", "fundAccount", "creditCardPay"]
    for tool in evasive:
        d = gate.evaluate("broker", tool, {"amount": 100})
        check(f"1.x money evasivo '{tool}' → needs_ok (NO auto-ejecuta)",
              d.action == "needs_ok", f"{tool} → {d.action}/{d.level}")


# ── 2. los nombres money CLÁSICOS siguen gateados (no rompimos nada) ─────────────
def test_classic_money_still_gated():
    gate = enf.build_enforced_gate(_recipe())
    for tool in ["place_order", "transfer_funds", "wire_money", "buy_stock", "sell_all"]:
        d = gate.evaluate("broker", tool, {})
        check(f"2.x money clásico '{tool}' → needs_ok",
              d.action == "needs_ok", f"{tool} → {d.action}")


# ── 3. send EVASIVO sigue gateado (lección del bypass por nombre; f4-b5) ─────────
# El gate-first exige que NINGÚN verbo de envío auto-ejecute. No basta con send_*:
# dispatch_*/notify_*/post_*/forward_*/reply_all/broadcast/publicar/reenviar, y
# camelCase, TODOS deben caer a needs_ok. Si un nombre nuevo de envío se cuela como
# auto-ejecuta, este test es el que se pone rojo ANTES de cablear un conector.
def test_send_evasive_and_classic_gated():
    gate = enf.build_enforced_gate(_recipe())
    send_names = [
        # clásicos
        "send_message", "send_mail", "sendMessage", "send_sms", "send_email",
        # dispatch / notify (evasivos típicos)
        "dispatch_email", "dispatch_message", "dispatchEmail",
        "notify_user", "notify_team", "notifyUser",
        # post / publish / tweet (canales sociales)
        "post_message", "post_tweet", "postMessage", "publish_post", "tweet_status",
        # forward / reply / broadcast / deliver / transmit / outbound
        "forward_mail", "forward_to", "reply_all", "broadcast", "broadcast_alert",
        "deliver_email", "transmit_payload", "whatsapp_send", "email_send",
        "mail_send", "outbound_message",
        # español (verbos de envío)
        "enviar_correo", "mandar_mensaje", "difundir_alerta", "publicar_post", "reenviar_email",
    ]
    for tool in send_names:
        d = gate.evaluate("mailer", tool, {"to": "x@y.z", "body": "..."})
        check(f"3.x send evasivo '{tool}' → needs_ok",
              d.action == "needs_ok" and d.level == "confirma-siempre",
              f"{tool} → {d.action}/{d.level}")


# ── 3b. NO PARALIZAR la mensajería: LEER mensajes/chats no debe pedir OK ─────────
# El gate-first frena el ENVÍO, no la lectura. search_messages / get_message /
# list_chats / read_inbox son lecturas y deben auto-ejecutar (seguro pero no
# paralizado). DEUDA conocida: nombres con la raíz 'mail'/'email' (fetch_emails,
# list_emails) caen a needs_ok por conservadurismo del canal de correo — es el lado
# SEGURO (pide OK, nunca envía solo); se documenta como fricción de UX, no breach.
def test_message_reads_not_paralyzed():
    gate = enf.build_enforced_gate(_recipe())
    reads = ["search_messages", "get_message", "list_messages", "read_inbox",
             "get_thread", "list_chats"]
    for tool in reads:
        d = gate.evaluate("mailer", tool, {})
        check(f"3b.x lectura de mensajería '{tool}' → execute (no paraliza)",
              d.action == "execute", f"{tool} → {d.action}/{d.level}")


# ── 4. NO PARALIZAR: lecturas legítimas siguen auto-ejecutando ───────────────────
# "seguro pero no paralizado": una lectura benigna NO debe pedir OK.
def test_legit_reads_still_auto():
    gate = enf.build_enforced_gate(_recipe())
    reads = ["lookup_price", "get_financials", "list_orders", "search_filings",
             "get_company_facts", "fred_get_series", "read_data_from_excel",
             "getQuote", "view_balance"]
    for tool in reads:
        d = gate.evaluate("data", tool, {})
        # nota: 'view_balance' / 'get_balance' son lectura; si alguna raíz money las
        # gatea por conservadurismo, lo aceptamos (seguro), pero las puras de lectura
        # de datos NO deben pedir OK.
        check(f"4.x lectura legítima '{tool}' → execute (no paraliza)",
              d.action == "execute", f"{tool} → {d.action}/{d.level}")


# ── 5. el clasificador directo coincide (unidad pura) ────────────────────────────
def test_classifier_direct():
    check("5.1 suggests_money_touch('fund_account')", enf.suggests_money_touch("fund_account"))
    check("5.2 suggests_money_touch('get_paid')", enf.suggests_money_touch("get_paid"))
    check("5.3 suggests_money_touch('lookup_price') == False",
          not enf.suggests_money_touch("lookup_price"))
    check("5.4 suggests_money_touch('get_financials') == False",
          not enf.suggests_money_touch("get_financials"))


def main():
    print("=== regresión: bypass money por nombre evasivo (factory de PROD) ===\n")
    test_evasive_money_names_gated()
    test_classic_money_still_gated()
    test_send_evasive_and_classic_gated()
    test_message_reads_not_paralyzed()
    test_legit_reads_still_auto()
    test_classifier_direct()
    print(f"\n=== {_passed} passed, {_failed} failed ===")
    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()
