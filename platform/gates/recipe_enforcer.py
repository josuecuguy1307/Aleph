#!/usr/bin/env python3
"""
recipe_enforcer.py — el PUENTE receta → matriz efectiva que HACE CUMPLIR la
INVARIANTE de seguridad no-negociable (RECIPE-SCHEMA §3.5, orden del founder
2026-06-15).

EL PROBLEMA QUE CIERRA
----------------------
El `ApprovalGate` (Fase 18, misión 0014) consume una MATRIZ. Hasta ahora esa
matriz era estática (`matrix.example.json`). Con el schema de receta v1 (anidado,
`belt_ref`, `gates` declarados) la receta del puppet trae su propia sección
`gates`:

    "gates": { "money_touch": "off", "send": "off" }   // ← la receta podría APAGARLOS

La INVARIANTE dice, textual:
  • el motor FUERZA money_touch/send "AUNQUE LA RECETA LOS OMITA O LOS PONGA OFF".
  • la receta puede AGREGAR gates (más estrictos), NUNCA QUITAR los mandatorios.
  • default FAIL-CLOSED para tools desconocidas que escriben/mandan (lección Fase 18).

Este módulo es ese motor. NO confía en la receta para decidir si un money-touch /
send se gatea: deriva la matriz efectiva por CLASIFICACIÓN de la tool en Security,
y planta las reglas mandatorias SIEMPRE, pisando cualquier intento de la receta de
desactivarlas. La receta solo puede subir el piso, jamás bajarlo.

CONTRATO
--------
`recipe_to_matrix(recipe, base_matrix=None) -> dict`
    Devuelve una matriz lista para `ApprovalGate(matrix)`. Garantías:
      1. SIEMPRE existe una regla mandatoria de money_touch en `confirma-siempre`.
      2. SIEMPRE existe una regla mandatoria de send/external en `confirma-siempre`.
      3. Ambas se plantan PRIMERO (ganan el match) y son inmunes a `recipe["gates"]`.
      4. `default_level` para desconocidas se queda en el piso fail-closed que el
         gate ya aplica; este módulo NUNCA lo afloja.
      5. La receta puede AGREGAR reglas extra (vía `recipe["gates"]["extra_rules"]`),
         pero esas se anexan DESPUÉS de las mandatorias — no pueden eclipsarlas.

`MONEY_TOUCH_HINTS` / `SEND_HINTS`
    La clasificación de Security (qué tool toca plata, qué tool manda). Substring,
    case-insensitive. Es la fuente de verdad del gate, no la receta.

Este módulo es PURO (sin I/O salvo leer un base_matrix opcional) — testeable en
aislamiento. Se monta sobre `approval_gate.ApprovalGate` sin tocarlo.
"""

from __future__ import annotations

import copy
import os
import re
from typing import Optional

# ── Clasificación de Security: qué delata MONEY-TOUCH y qué delata SEND ─────────
#
# Esto es lo que define un gate mandatorio, NO la receta. Si una tool matchea acá,
# se gatea — diga lo que diga `recipe["gates"]`. Substring, case-insensitive.

# Tocar PLATA: órdenes de mercado, transferencias, pagos, escrituras a hojas/ledgers
# financieros vivos. Cubre inglés y español.
#
# OJO (mismo cuidado que SEND): "order"/"orden" como substring matchea lecturas
# (`get_order_book`, `list_orders`). Usamos los VERBOS que ejecutan la orden
# (`place_order`, `execute_order`, `submit_order`, `cancel_order`), no el sustantivo.
MONEY_TOUCH_HINTS = (
    "pay", "payment", "remit", "charge", "refund",
    # "wire"/"transfer" DESNUDOS retirados: son homógrafos que matchean piezas que NO tocan
    # plata — `add_wire` (wire de esquemático KiCad) y `analyze_heat_transfer` (transferencia
    # de CALOR, física). Se exige el COMPUESTO que sí es dinero (mismo cuidado que "order"):
    # cubre los evasivos clásicos (wire_money, transfer_funds) sin cazar los homógrafos.
    "wire_transfer", "bank_transfer", "send_wire", "bank_wire", "wire_money",
    "money_transfer", "transfer_money", "transfer_funds", "funds_transfer",
    "buy", "sell", "trade", "place_order", "execute_order", "submit_order",
    "cancel_order", "settle", "settlement", "withdraw", "deposit", "checkout",
    "purchase", "subscribe_paid", "payout", "disburse",
    # defensa-en-profundidad (brecha del review de Fase 2): raíces money que un nombre
    # evasivo usaba para colarse como "lectura" (fund_account, account_debit, get_paid).
    # Acá substring es CONSERVADOR hacia gatear: un falso positivo solo pide OK. Una
    # tool money que matchee acá cae a la regla MANDATORY (corre PRIMERO) y se gatea
    # antes de que la clasificación de lectura siquiera se consulte.
    "fund_", "debit", "_paid", "get_paid", "deduct", "credit_card", "topup", "top_up",
    # escritura a hoja/ledger financiero vivo (lo ve el equipo/CFO al instante)
    "batch_update_cells", "update_cells", "add_rows", "write_to_sheet",
    # español (verbos que mueven plata, no el sustantivo "orden")
    "pagar", "transferir", "transferencia", "girar", "cobrar", "reembolsar",
    "comprar", "vender", "liquidar", "retirar", "depositar", "debitar", "acreditar",
)

# MANDAR afuera: email, mensajería, difusión. Cubre inglés y español.
#
# OJO (lección del falso positivo, par M002): las hints son VERBOS de envío, NO el
# sustantivo "message"/"mensaje"/"correo". Si pusiéramos "message" como substring,
# una LECTURA legítima como `search_messages` / `get_message` / `read_correo`
# caería al gate y PARALIZARÍA al agente de cowork (rompe "seguro pero no
# paralizado"). El envío se delata por el verbo (send/dispatch/notify…), no por el
# objeto. `send_message` ya matchea por "send"; `post_message` por "post".
SEND_HINTS = (
    "send", "sendmail", "send_message", "send_mail", "sendmessage",
    "post_message", "dispatch", "notify", "broadcast", "publish", "deliver",
    "transmit", "tweet", "whatsapp", "sms", "reply_all", "forward_mail",
    "email_send", "mail_send", "outbound",
    # español (verbos de envío, nunca el sustantivo "mensaje"/"correo")
    "enviar", "envio_", "_envio", "mandar", "difundir", "publicar", "reenviar",
)

# Default fail-closed: el piso para tools desconocidas. NUNCA por debajo de esto.
_FAIL_CLOSED_LEVEL = "confirma-siempre"

# Niveles estándar — copy oficial §2 del threat-model. Se incluyen siempre en la
# matriz efectiva para que el gate tenga las definiciones que necesita.
_STD_LEVELS = {
    "auto-ejecuta": {
        "copy": "Tu agente lo hace solo.",
        "requires_ok": False,
        "blocked": False,
    },
    "confirma-una-vez": {
        "copy": "Tu agente te avisa la primera vez y después sigue solo.",
        "requires_ok": True,
        "once_per_session": True,
        "blocked": False,
    },
    "confirma-siempre": {
        "copy": "Tu agente te pregunta cada vez, antes de hacerlo.",
        "requires_ok": True,
        "once_per_session": False,
        "blocked": False,
    },
    "prohibido-en-tier-average": {
        "copy": "Tu cuenta básica no puede hacer esto.",
        "requires_ok": False,
        "blocked": True,
    },
}


def suggests_money_touch(tool: str) -> bool:
    """¿El nombre de la tool delata que TOCA PLATA? (clasificación Security)."""
    t = (tool or "").lower()
    return any(h in t for h in MONEY_TOUCH_HINTS)


def suggests_send(tool: str) -> bool:
    """¿El nombre de la tool delata que MANDA AFUERA? (clasificación Security)."""
    t = (tool or "").lower()
    return any(h in t for h in SEND_HINTS)


# Verbos de MUTACIÓN EXTERNA inequívoca (crear/borrar/deploy/publicar/otorgar…). Espejo
# local (mismo patrón que MONEY/SEND) — el gate tiene su propia copia autoritativa
# (_EXTERNAL_WRITE_HINTS en classify_action, que es EL enforcement). Acá sólo evita EMITIR
# una regla 'auto-ejecuta' engañosa cuando la receta declara 'read'/'write-local' a un
# create_pr / delete_repo / deploy (review adversarial A2).
EXTERNAL_WRITE_HINTS = (
    "create", "insert", "delete", "remove", "drop", "update", "patch", "edit",
    "modify", "write", "store", "commit", "merge", "deploy", "install",
    "submit", "grant", "revoke", "rename", "upload", "publish", "post",
    "borrar", "eliminar", "actualiz", "crear", "modificar", "subir",
)

# "escrib" NO puede ir en la tupla: es substring de `d-escrib-e`, y convertía
# `describe_table` (LECTURA) en mutación externa. Espejo EXACTO de
# platform/gates/approval_gate._ESCRIB_RE — MANTENER EN SYNC.
#   escribir · sobrescribir · reescribir  → SÍ   ·   describe · describir → NO
ESCRIB_RE = re.compile(r"(?<!d)escrib")


def suggests_external_write(tool: str) -> bool:
    """¿El nombre delata MUTACIÓN EXTERNA inequívoca? Una receta NO puede degradar
    esto a lectura/local (el gate lo re-clasifica write-world por piso igual)."""
    t = (tool or "").lower()
    return any(h in t for h in EXTERNAL_WRITE_HINTS) or ESCRIB_RE.search(t) is not None


# EJECUTAR CÓDIGO ARBITRARIO: run_python/run_shell/execute_code y cía. Es P1∧P3 sin importar
# el auth (un run_python "keyless" alcanza red/disco/lo que sea). VERBOS ESPECÍFICOS de exec,
# NO el prefijo "run_" pelado — que matchea run_erc / run_pipe_flow / run_fem_analysis
# (corridas de ANÁLISIS de dominio, no exec arbitrario) y los gatearía por error.
CODE_EXEC_HINTS = (
    "run_python", "run_shell", "run_code", "run_command", "run_script",
    "run_bash", "run_javascript", "run_js", "execute_code", "exec_code",
    "eval_code", "code_exec", "shell_exec", "insert_execute_code",
    "aleph_run_code", "execute_cell", "stata_run",
)


def suggests_code_exec(tool: str) -> bool:
    """¿El nombre delata EJECUCIÓN DE CÓDIGO ARBITRARIO? (run_python/execute_code…)."""
    t = (tool or "").lower()
    return any(h in t for h in CODE_EXEC_HINTS)


# ── GATE EFECTIVO de UNA PIEZA del catálogo ──────────────────────────────────────
# Fuente autoritativa del candado que el panel de Opciones muestra por átomo (no de la
# receta: eso es recipe_to_matrix). El criterio es P1∧P3 (toca afuera con efecto
# persistente) o exec arbitrario — JAMÁS la zona.
_GATE_LEVELS = ("money", "send", "write", "exec")


def gate_for_card(card: Optional[dict], tools=None, auth: str = "keyless") -> dict:
    """Candado efectivo de una card del catálogo → {"gated": bool, "level": str|None}.

      (1) OVERRIDE declarado por la card gana sobre el keyword-guess — espejo del override de
          `zone` (regla C3): la PRESENCIA de la clave `gate` = declarado. `gate` ∈ _GATE_LEVELS
          → ese nivel; `gate` None/desconocido → declarado SIN gate (pinneado, inmune al keyword).
      (2) Sin override, se infiere por el ALCANCE REAL de las tools (nunca por la zona).
    """
    if card is not None and "gate" in card:
        g = card.get("gate")
        if g in _GATE_LEVELS:
            return {"gated": True, "level": g}
        return {"gated": False, "level": None}
    tl = tools if tools is not None else ((card or {}).get("tools") or [])
    level = None
    if any(suggests_money_touch(t) for t in tl):
        level = "money"
    elif any(suggests_send(t) for t in tl):
        level = "send"
    elif any(suggests_code_exec(t) for t in tl):
        # exec arbitrario = candado SIEMPRE, sin importar el auth (corre lo que sea).
        level = "exec"
    elif auth != "keyless" and any(suggests_external_write(t) for t in tl):
        # escritura a una CUENTA EXTERNA. Sólo con auth != keyless: una escritura keyless va
        # al workdir del run (sandbox), no a la cuenta del usuario → no lleva candado.
        level = "write"
    return {"gated": level is not None, "level": level}


def classify_tools(tool_filters: dict) -> dict:
    """
    Recorre el subset curado de la receta (`belt.tool_filters`) y devuelve qué
    tools caen en money_touch y cuáles en send, POR CLASIFICACIÓN — no por lo que
    declare la receta. Útil para el preview del taller y para reglas explícitas.
    """
    money, send = [], []
    for server, tools in (tool_filters or {}).items():
        for tool in tools or []:
            if suggests_money_touch(tool):
                money.append((server, tool))
            if suggests_send(tool):
                send.append((server, tool))
    return {"money_touch": money, "send": send}


def _mandatory_rules() -> list:
    """
    Las DOS reglas mandatorias, plantadas SIEMPRE y PRIMERO (ganan el match).
    Capturan por substring de nombre de tool — independientes del server, de la
    receta y de `tool_filters`. Una tool que toque plata o mande SIEMPRE matchea
    una de estas antes que cualquier regla laxa que la receta haya intentado meter.
    """
    return [
        {
            "id": "MANDATORY-code-exec",
            "match": {"server": "*", "tool_name_contains": list(CODE_EXEC_HINTS)},
            "level": "confirma-siempre",
            "action_class": "code_exec",
            "what": "ejecutar código con autoridad sobre este equipo",
            "where": "el proceso y los recursos accesibles por la aplicación",
            "preview_kind": "codigo-host",
            "mandatory": True,
        },
        {
            "id": "MANDATORY-money-touch",
            "match": {"server": "*", "tool_name_contains": list(MONEY_TOUCH_HINTS)},
            "level": "confirma-siempre",
            # A2 · clase de acción: PISO inmutable de dinero. El gate la lee para que
            # ninguna perilla (ni 'autónomo') la baje; assert_invariant la ancla.
            "action_class": "money_touch",
            "what": "hacer algo que mueve o compromete tu dinero",
            "where": "tu cuenta, tu hoja financiera en vivo o el destinatario del pago",
            "preview_kind": "accion",
            "mandatory": True,
        },
        {
            "id": "MANDATORY-send",
            "match": {"server": "*", "tool_name_contains": list(SEND_HINTS)},
            "level": "confirma-siempre",
            # A2 · clase de acción: escritura al mundo (envío). 'balanceado' la gatea;
            # sólo 'autónomo' la deja pasar (nunca dinero).
            "action_class": "write-world",
            "what": "mandar algo afuera (correo, mensaje o difusión)",
            "where": "el destinatario que figura en el mensaje",
            "preview_kind": "mensaje",
            "mandatory": True,
        },
    ]


def recipe_to_matrix(recipe: dict, base_matrix: Optional[dict] = None) -> dict:
    """
    Deriva la matriz efectiva desde una receta v1 anidada, HACIENDO CUMPLIR la
    invariante §3.5. La receta NO puede apagar un gate mandatorio.

    Parameters
    ----------
    recipe : dict
        La receta v1 anidada (puede traer `gates` en off, omitirlos, o agregar).
    base_matrix : dict | None
        Matriz base opcional (ej. niveles/reglas comunes del nicho). Sus reglas se
        anexan DESPUÉS de las mandatorias, nunca antes — no pueden eclipsarlas.

    Returns
    -------
    dict : matriz lista para `ApprovalGate(matrix)`.
    """
    base = copy.deepcopy(base_matrix) if base_matrix else {}

    # Niveles: los estándar SIEMPRE presentes; la base puede agregar/ajustar copy,
    # pero no puede borrar las definiciones que el gate necesita.
    levels = dict(_STD_LEVELS)
    levels.update(base.get("levels", {}))
    # Re-asegurar que confirma-siempre NO fue degradado a no-requires_ok por la base.
    cs = levels.get("confirma-siempre", {})
    if not cs.get("requires_ok"):
        levels["confirma-siempre"] = dict(_STD_LEVELS["confirma-siempre"])

    # Reglas: PRIMERO las mandatorias (ganan el match), DESPUÉS lo de la base, y al
    # final cualquier `extra_rules` que la receta quiera AGREGAR (más estricto).
    rules = list(_mandatory_rules())

    # Reglas de la base, EXCEPTO cualquiera que pretenda redefinir un mandatorio a
    # un nivel más laxo (defensa: la base no puede colar un override permisivo).
    for r in base.get("rules", []):
        if r.get("id", "").startswith("MANDATORY-"):
            continue  # nunca se acepta una redefinición de un mandatorio desde fuera
        rules.append(r)

    # ── A2 · CLASE DE ACCIÓN DECLARADA POR EL BELT (gap 2: declarativa autoritativa) ──
    # La receta puede traer `belt.action_classes = { server: { tool: "read|write-local|
    # write-world" } }` — p.ej. poblado por la `kind` del forged-MCP ('write' ⇒ write-world).
    # Emitimos UNA regla por tool declarada, DESPUÉS de las mandatorias (mandatory-first
    # sigue ganando money/send). NUNCA aceptamos una clase que baje el piso: si el nombre
    # delata money/send, se ignora la declaración (la mandatoria la gatea igual, y el gate
    # re-clasifica por piso en classify_action). money_touch no se declara acá: es piso.
    _LEVEL_FOR_CLASS = {
        "read": "auto-ejecuta",
        "write-local": "auto-ejecuta",
        "write-world": "confirma-siempre",
    }
    belt = recipe.get("belt", {}) or {}
    for server_name, tool_map in (belt.get("action_classes", {}) or {}).items():
        if not isinstance(tool_map, dict):
            continue
        for tool_name, klass in tool_map.items():
            k = str(klass).strip().lower().replace("_", "-")
            if k not in _LEVEL_FOR_CLASS:
                continue  # money_touch (o basura) no se declara: el piso lo fuerza
            if (suggests_money_touch(tool_name) or suggests_send(tool_name)
                    or suggests_code_exec(tool_name)):
                continue  # el nombre delata piso → manda la mandatoria, no la declaración
            # PISO mutación-externa (review adversarial A2): una receta NO puede declarar
            # 'read'/'write-local' a un create_pr / delete_repo / deploy para auto-ejecutarlo.
            # Si el nombre delata efecto externo, ignoramos la declaración laxa y dejamos que
            # el gate lo clasifique write-world por piso (classify_action lo re-clasifica igual;
            # esto sólo evita emitir una regla 'auto-ejecuta' engañosa en la matriz).
            if k in ("read", "write-local") and suggests_external_write(tool_name):
                continue
            rules.append({
                "id": f"declared-{server_name}-{tool_name}",
                "match": {"server": server_name, "tools": [tool_name]},
                "level": _LEVEL_FOR_CLASS[k],
                "action_class": k,
                "what": f"usar {tool_name}",
            })

    # `recipe["gates"]` SOLO puede AGREGAR. Leemos extra_rules si las trae; las de
    # tipo money/send se fuerzan a confirma-siempre igual (no pueden venir laxas).
    recipe_gates = recipe.get("gates", {}) or {}
    for extra in recipe_gates.get("extra_rules", []) or []:
        er = dict(extra)
        er["id"] = "recipe-extra-" + str(er.get("id", len(rules)))
        # una extra que clasifique como money/send no puede ser más laxa que el piso
        contains = (er.get("match", {}) or {}).get("tool_name_contains", []) or []
        if any(suggests_money_touch(c) or suggests_send(c) or suggests_code_exec(c)
               for c in contains):
            er["level"] = "confirma-siempre"
        rules.append(er)

    # NOTA CLAVE sobre `recipe["gates"]["money_touch"]` / `["send"]`:
    # se IGNORAN para decidir si gatear. Da igual que digan "off". Las reglas
    # MANDATORY-* de arriba ya fuerzan el gate por clasificación de tool. La receta
    # declara para la UX del taller (mostrarlos), pero el ENFORCEMENT no las mira.
    # Si la receta los pone MÁS estrictos (ej. money_touch:"prohibido"), eso sí se
    # respeta como adición; se mapearía a un nivel bloqueante — fuera de scope v1
    # (hoy el piso es confirma-siempre, que ya es "pregunta cada vez").

    matrix = {
        "levels": levels,
        # default_level SOLO aplica a LECTURAS OBVIAS (el gate lo garantiza). Para
        # desconocidas-que-escriben el gate cae a fail_closed_level. No lo aflojamos.
        "default_level": base.get("default_level", "auto-ejecuta"),
        "fail_closed_level": _FAIL_CLOSED_LEVEL,
        "tier": base.get("tier", recipe.get("tier", "average")),
        "rules": rules,
        # A2 · perilla de Autonomía de la receta (candado runtime; el gate la aplica,
        # el piso money NO baja). El gate la lee del kwarg o de acá.
        "autonomy": recipe.get("autonomy"),
        "_derived_from_recipe": recipe.get("meta", {}).get("name", "?"),
        "_invariant": "money_touch+send+code_exec forced confirma-siempre regardless of recipe.gates (RECIPE-SCHEMA §3.5)",
    }
    return matrix


def assert_invariant(matrix: dict, autonomy: Optional[str] = None) -> None:
    """
    Verificación dura: la matriz efectiva DEBE contener ambas reglas mandatorias
    en confirma-siempre, y ninguna regla previa puede eclipsarlas. La usa el
    arranque del runtime como guard fail-closed: si esto falla, el runtime NO sirve
    el puppet (mejor no levantar que levantar sin candado).

    `autonomy` (A2): bajo CUALQUIER perilla — incluida 'autonomo' — la regla de clase
    money_touch debe seguir resolviendo a un nivel requires_ok. La perilla vive en el
    gate y NO baja este piso; esto lo ancla en el arranque (fail-closed).
    """
    rules = matrix.get("rules", [])
    mand = [r for r in rules if r.get("mandatory")]
    ids = {r.get("id") for r in mand}
    assert "MANDATORY-money-touch" in ids, "falta el gate mandatorio money_touch"
    assert "MANDATORY-send" in ids, "falta el gate mandatorio send"
    assert "MANDATORY-code-exec" in ids, "falta el gate mandatorio code_exec"
    for r in mand:
        lvl = matrix["levels"].get(r["level"], {})
        assert lvl.get("requires_ok"), f"gate mandatorio {r['id']} no requiere OK"
    # las mandatorias deben ir ANTES que cualquier regla no-mandatoria que matchee
    # las mismas hints (si no, una laxa anterior ganaría el match).
    first_non_mand = next((i for i, r in enumerate(rules) if not r.get("mandatory")), len(rules))
    last_mand = max((i for i, r in enumerate(rules) if r.get("mandatory")), default=-1)
    assert last_mand < first_non_mand, "una regla no-mandatoria precede a las mandatorias (las eclipsaría)"

    # ── A2 · PISO DE DINERO INDEPENDIENTE DE LA PERILLA ──────────────────────────
    # La regla de clase money_touch existe y sigue en un nivel requires_ok, diga lo
    # que diga la autonomía. 'autonomo' relaja sends/writes NO-monetarios; JAMÁS dinero.
    money_rules = [r for r in mand if r.get("action_class") == "money_touch"]
    assert money_rules, "falta la regla mandatoria de CLASE money_touch (piso de dinero)"
    for r in money_rules:
        lvl = matrix["levels"].get(r["level"], {})
        assert lvl.get("requires_ok"), (
            f"la regla money_touch {r['id']} perdió requires_ok "
            f"(autonomia={autonomy!r}) — el piso de dinero se rompería")

    code_rules = [r for r in mand if r.get("action_class") == "code_exec"]
    assert code_rules, "falta la regla mandatoria de CLASE code_exec"
    for r in code_rules:
        lvl = matrix["levels"].get(r["level"], {})
        assert lvl.get("requires_ok"), f"la regla code_exec {r['id']} perdió requires_ok"


# ── Factory de conveniencia: receta → ApprovalGate listo, invariante verificada ─

_TIER_UNSET = object()   # centinela: distingue "no pasaron account_tier" (CLI, back-compat) de "pasaron None" (anon → fail-closed)


def build_enforced_gate(recipe: dict, base_matrix=None, autonomy=None,
                        account_tier=_TIER_UNSET, **gate_kwargs):
    """
    De la RECETA a un `ApprovalGate` con la invariante §3.5 ya forzada y VERIFICADA.

    Es el punto de entrada que el runtime/assembler debe usar para construir el gate
    de un puppet a partir de su receta (`puppets.config`). Hace `assert_invariant`
    antes de devolver: si la matriz derivada no contiene los gates mandatorios,
    LANZA (fail-closed de arranque) — preferimos no levantar el puppet a levantarlo
    sin candado de money/send.

    `autonomy` (A2): la perilla de la receta (manual/balanceado/autonomo). Viaja al
    gate como CANDADO DE RUNTIME. La perilla decide auto/hold por clase de acción; el
    piso money NO baja bajo ninguna. Ausente → 'balanceado' (lo normaliza el gate).

    Importa `ApprovalGate` perezosamente para no acoplar este módulo puro al gate.
    """
    import importlib.util
    from pathlib import Path as _P
    _here = _P(__file__).resolve().parent
    import aleph_paths
    _ag = aleph_paths.load_module_by_path("puppet_approval_gate", _here / "approval_gate.py")

    # La perilla explícita gana; si no vino, usar la declarada en la receta.
    eff_autonomy = autonomy if autonomy is not None else recipe.get("autonomy")
    matrix = recipe_to_matrix(recipe, base_matrix=base_matrix)
    # ── MURALLA PREMIUM · el tier del gate es AUTORITATIVO DESDE LA CUENTA ────────────
    # recipe_to_matrix cae a base_matrix.tier o recipe.tier (editables por belt/cliente) →
    # trust-hole: un free que edita recipe.tier saltearía un level 'blocked'/'tier_block'.
    # Si el llamador server pasó account_tier (resuelto de la cuenta), IMPONE el vocabulario
    # del gate. FAIL-CLOSED POR ALLOWLIST: SOLO los dos tiers pagos conocidos → 'premium'; TODO
    # lo demás (free, None/anon, desconocido, mal escrito, incluso la palabra 'premium') → 'average'
    # (gateable). Un mapeo equivocado bloquea premium (molesto), nunca lo abre (te vacía el moat).
    # GOTCHA: NO pasar 'free' crudo al gate — self.tier=='average' es lo único que hoy bloquea; por
    # eso mapeamos acá. account_tier=None (anon) DEBE llegar y mapear a 'average', por eso el centinela
    # _TIER_UNSET (no None) marca "no pasaron nada" (CLI/back-compat). Ver tier_gate.gate_tier_for_account.
    if account_tier is not _TIER_UNSET:
        _at = str(account_tier or "").strip().lower()
        matrix["tier"] = "premium" if _at in ("basico", "tecnico") else "average"
    if eff_autonomy is not None:
        matrix["autonomy"] = eff_autonomy
    assert_invariant(matrix, autonomy=eff_autonomy)   # guard fail-closed: no gate / piso money roto => no puppet
    return _ag.ApprovalGate(matrix, autonomy=eff_autonomy, **gate_kwargs)


# ── FRONTERA · TECHOS DE RUNTIME POR TIER (Step 2 · A1) ─────────────────────────
# Hermana de la invariante de gates: así como una receta NO puede apagar el gate de
# money/send, tampoco puede SUBIR sus techos de loop por encima de los de su tier.
# Estos techos se aplican SERVER-SIDE (executor, path de prod) ANTES de correr el
# loop → una receta editada con max_turns=9999 se clampa al techo del tier. Un free
# jamás corre más turnos/tool-calls que los de free, edite lo que edite (el candado
# vive en el runtime, no en la UI). Tabla reutilizable: B1 (paralelismo por tier) lee
# de acá; C1 (docs por tier) lee de TIER_RAG_CAPS. Identificadores = free/basico/tecnico (premium=
# basico, pro=tecnico son alias de display; no se migra la tabla users).
# max_parallel (Step 2·B1) = cuántos sub-agentes corren A LA VEZ bajo un mismo padre.
# Es un candado de RUNTIME (delegation.run_children lo clampa en el choke point que TODO
# el árbol comparte): una receta editada NO lo sube. free=1 (un agente a la vez, se
# serializa con aviso honesto), basico(premium)=3, tecnico(pro)=10. Riela por _caps_ceiling
# igual que max_turns/max_tool_calls (runtime_caps_for_tier devuelve la fila entera).
# shared_bus (Step 2·B2) = ¿puede este tier CABLEAR el bus de memoria compartida entre >1
# agente del Cuarto? free=False (ve el cilindro pero no cablea el bus → PREMIUM), basico/
# tecnico=True. Riela por _caps_ceiling igual que max_parallel; el candado (reject honesto +
# upsell) vive en el runtime (recipe_assembler, seam de activación del bus), NO editable por
# receta: el tier sale de la CUENTA del dueño, no de recipe.tier (que es display).
TIER_RUNTIME_CAPS: dict[str, dict[str, object]] = {
    "free":    {"max_turns": 8,  "max_tool_calls": 40,  "max_parallel": 1,  "shared_bus": False},
    "basico":  {"max_turns": 20, "max_tool_calls": 150, "max_parallel": 3,  "shared_bus": True},
    "tecnico": {"max_turns": 40, "max_tool_calls": 400, "max_parallel": 10, "shared_bus": True},
}
_DEFAULT_TIER = "free"  # tier ausente/desconocido → el MÁS restrictivo. Nunca afloja.


def runtime_caps_for_tier(tier: Optional[str]) -> dict[str, object]:
    """Techos de runtime (max_turns, max_tool_calls, max_parallel, shared_bus) del tier.
    Desconocido → free."""
    return dict(TIER_RUNTIME_CAPS.get((tier or "").strip().lower(),
                                      TIER_RUNTIME_CAPS[_DEFAULT_TIER]))


def bus_allowed_for_tier(tier: Optional[str]) -> bool:
    """¿El tier permite CABLEAR el bus de memoria compartida entre >1 agente? (Step 2·B2).
    free=False (premium-gated), basico/tecnico=True. Desconocido → free (fail-closed = sin bus)."""
    return bool(runtime_caps_for_tier(tier).get("shared_bus", False))


# ── Step 2 · A3 · FRONTERA de MEMORIA por-agente (entradas + bytes) por TIER ─────
# Mismo candado que TIER_RUNTIME_CAPS: se aplica SERVER-SIDE en el write-path de la
# memoria (destilado al cierre del run + write directo del panel) → un agente free
# jamás guarda más de 20 entradas / 8 KB, edite lo que edite su receta. Evita memoria
# infinita que infle el contexto; lo viejo se desaloja ('destilado de las viejas').
# FREE es funcional (memoria = parte de 'agente serio', no se capa): 20 entradas es
# memoria útil. PREMIUM (basico/tecnico) sube el techo. NO editable por receta.
TIER_MEMORY_CAPS: dict[str, dict[str, int]] = {
    "free":    {"max_entries": 20,  "max_bytes": 8192},     # 8 KB
    "basico":  {"max_entries": 100, "max_bytes": 65536},    # 64 KB
    "tecnico": {"max_entries": 500, "max_bytes": 262144},   # 256 KB
}


def memory_caps_for_tier(tier: Optional[str]) -> dict[str, int]:
    """Techo de memoria (max_entries, max_bytes) del tier. Desconocido → free (el más
    restrictivo). La receta NO puede subirlo: es frontera de runtime, como los loops."""
    return dict(TIER_MEMORY_CAPS.get((tier or "").strip().lower(),
                                     TIER_MEMORY_CAPS[_DEFAULT_TIER]))


# ── ORDEN 2 · FRONTERA de MEMORIA DE CUENTA (Sistema 2) — hechos sobre la PERSONA por TIER ──
# La cuenta guarda POCOS hechos estables sobre el usuario (idioma, preferencias, contexto, cómo
# reportarle), NO el volumen de aprendizajes por-agente. Por eso el techo es MÁS CHICO que A3:
# una cuenta con cientos de "hechos sobre la persona" sería ruido, no memoria. Es FUNCIONAL en
# free (leer al usuario como quien es no es premium); PREMIUM sube el techo. Fail-closed:
# desconocido → free. NO editable por receta (frontera de runtime, sale de users.tier).
TIER_ACCOUNT_MEMORY_CAPS: dict[str, dict[str, int]] = {
    "free":    {"max_entries": 15,  "max_bytes": 6144},      # 6 KB
    "basico":  {"max_entries": 60,  "max_bytes": 32768},     # 32 KB
    "tecnico": {"max_entries": 200, "max_bytes": 131072},    # 128 KB
}


def account_memory_caps_for_tier(tier: Optional[str]) -> dict[str, int]:
    """Techo de memoria de CUENTA (max_entries, max_bytes) del tier. Desconocido → free (el más
    restrictivo). La receta NO puede subirlo: frontera de runtime, sale de users.tier server-side."""
    return dict(TIER_ACCOUNT_MEMORY_CAPS.get((tier or "").strip().lower(),
                                             TIER_ACCOUNT_MEMORY_CAPS[_DEFAULT_TIER]))


# ── Step 2 · C1 · FRONTERA de RAG (átomo Conocimiento) — docs + bytes por TIER ──
# La frontera del RAG NO es free/premium (como B2): es DÓNDE VIVE EL ÍNDICE. El deploy
# es local-first, single-user hoy → el corpus vive en el Postgres LOCAL = el disco del
# propio usuario → nunca sale de su máquina. Por eso `self_hosted` (DEFAULT, path de
# prod) NO tiene tope: la recuperación RAG es FUNCIONAL en free (como la memoria A3, NO
# premium-gated como B2). El tope solo entra si Aleph corre la DB (`hosted`, multi-tenant
# futuro): ahí Aleph paga el storage → se capa por MB sobre el tier de la CUENTA. El modo
# NO es editable por receta (sale de PUPPET_RAG_STORAGE_MODE, runtime); recipe.tier es
# display-only, el candado sale de repo.get_user(user_id).tier. Un free con receta editada
# a 'tecnico' NO sube el tope de su cuenta. Fail-closed: tier desconocido → free.
TIER_RAG_CAPS: dict[str, dict[str, int]] = {
    "free":    {"max_docs": 30,   "max_bytes": 30_000_000},      # 30 docs / 30 MB
    "basico":  {"max_docs": 300,  "max_bytes": 500_000_000},     # 300 docs / 500 MB
    "tecnico": {"max_docs": 3000, "max_bytes": 5_000_000_000},   # 3000 docs / 5 GB
}


def rag_storage_mode() -> str:
    """Modo de almacenamiento del índice RAG (runtime, NO editable por receta).
    `self_hosted` (DEFAULT) = corpus en el Postgres local del usuario → sin tope.
    `hosted` = Aleph corre la DB → se capa por tier de la cuenta.

    SINGLE SOURCE OF TRUTH: normaliza (.strip().lower()) para que TODO consumidor
    vea el valor canónico. knowledge_store.get_store normaliza al elegir HostedStore;
    si acá devolviéramos crudo, 'Hosted'/' hosted ' escribirían al Postgres de Aleph
    pero rag_caps_for_tier (raw != 'hosted') devolvería None = SIN TOPE (cap bypass)."""
    return os.getenv("PUPPET_RAG_STORAGE_MODE", "self_hosted").strip().lower()


def rag_caps_for_tier(tier: Optional[str],
                      storage_mode: Optional[str] = None) -> Optional[dict[str, int]]:
    """Techo de RAG (max_docs, max_bytes) según el modo de almacenamiento.

    • `self_hosted` (o cualquier modo != 'hosted') → None = SIN TOPE (no-op): el índice
      vive en el disco del propio usuario, la recuperación es funcional en free.
    • `hosted` → la fila del tier de la CUENTA (fail-closed a free si es desconocido):
      Aleph paga el storage, se capa por MB. La receta NO puede subirlo (es runtime)."""
    # Normaliza defensivamente el override local igual que get_store, por si un caller
    # pasa storage_mode crudo ('Hosted'/' hosted '): sin esto un override casing-distinto
    # escaparía el tope mientras el store SÍ escribe al Postgres de Aleph.
    mode = (storage_mode or rag_storage_mode() or "").strip().lower()
    if mode != "hosted":
        return None
    return dict(TIER_RAG_CAPS.get((tier or "").strip().lower(),
                                  TIER_RAG_CAPS[_DEFAULT_TIER]))


def clamp_runtime_caps(model_cfg: Optional[dict], tier: Optional[str]) -> dict:
    """COPIA de model_cfg con max_turns/max_tool_calls CLAMPADOS al techo del tier.

    Reglas (SOLO baja, nunca sube):
      • max_turns      = min(lo pedido por la receta [o el default 8], techo del tier).
      • max_tool_calls = la receta puede pedir 0 ('sin techo'), pero el tier lo IMPONE
        → el efectivo es el techo del tier; si la receta pide un número, gana el MENOR.
    No muta el input; entradas basura caen al techo del tier (fail-closed hacia el piso)."""
    caps = runtime_caps_for_tier(tier)
    cfg = dict(model_cfg) if isinstance(model_cfg, dict) else {}

    _req_turns = cfg.get("max_turns")
    try:
        _req_turns = int(_req_turns) if _req_turns is not None else caps["max_turns"]
    except (TypeError, ValueError):
        _req_turns = caps["max_turns"]
    cfg["max_turns"] = max(1, min(_req_turns, caps["max_turns"]))

    _req_calls = cfg.get("max_tool_calls")
    try:
        _req_calls = (int(_req_calls) if _req_calls not in (None, 0, "0")
                      else caps["max_tool_calls"])
    except (TypeError, ValueError):
        _req_calls = caps["max_tool_calls"]
    cfg["max_tool_calls"] = max(1, min(_req_calls, caps["max_tool_calls"]))
    return cfg
