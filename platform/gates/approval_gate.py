#!/usr/bin/env python3
"""
PIEZA 1 — Gate de aprobación con vista previa.

Interceptor que se monta en el camino de tool-call del runtime del agente
(ToolRegistry.call). Ante una acción sensible — según la MATRIZ (config, no
hardcode) — PAUSA y produce el payload del CONTRATO DE UX del gate (Fase 13):

    (a) QUÉ va a hacer            -> en lenguaje de persona promedio
    (b) DÓNDE / a quién afecta
    (c) VISTA PREVIA del cambio/mensaje
    (d) requiere OK explícito     -> botón de OK

Niveles (de la matriz §4, copy oficial §2):
    auto-ejecuta · confirma-una-vez · confirma-siempre · prohibido-en-tier-average

PRINCIPIO RECTOR (persona usuaria, Fase 13 — SEGURO PERO NO PARALIZADO):
    la capacidad NUNCA se prohíbe (salvo tier); se ENVUELVE en protocolo de
    permiso + advertencia. El gate es PRODUCTO, no fricción.

PARAMETRIZABLE: la matriz entra como config. Cambiar de nicho = cambiar el
JSON, no este archivo. Cero constantes de finanzas acá.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Optional


# ── FAIL-CLOSED para tools DESCONOCIDAS (brecha 1 del review de 0014) ──────────
#
# El gate NUNCA puede caer a auto-ejecuta ante una tool sin regla en la matriz.
# El ataque probado en 0014 (dispatch_message / notify_user / mail_out /
# exfiltrate / upload_to) no matcheaba el substring de la regla `external-send`
# y caía al default_level=auto-ejecuta → AUTO-ENVIABA sin gate. Regla nueva
# (DECISIONS Fase 15, vinculante): toda desconocida cuyo nombre/efecto sugiera
# ESCRITURA/ENVÍO — y ante la duda TODA desconocida que no sea lectura obvia —
# cae a confirma-siempre. El default_level configurable solo puede ser MÁS
# estricto que esto; jamás auto-ejecuta para una desconocida-no-lectura.

# Verbos/raíces que delatan ESCRITURA, ENVÍO o EFECTO EXTERNO (mutación de estado
# fuera del proceso del agente). Cubren inglés y español. Substring, case-insensitive.
_WRITE_EFFECT_HINTS = (
    # envío / difusión / entrega
    "send", "dispatch", "notify", "mail", "email", "whatsapp", "sms", "post",
    "publish", "broadcast", "transmit", "deliver", "push", "share", "invite",
    # NB: el sustantivo "message"/"msg"/"dm" se quitó de la lista de ESCRITURA:
    # como substring paralizaba lecturas legítimas (search_messages, get_message,
    # list_dms). El ENVÍO se delata por el VERBO ("send"/"dispatch"/"notify"/"post"/
    # "reply"/"tweet"/"comment"), no por el objeto. Una tool de envío real siempre
    # trae el verbo (dispatch_message ⇒ "dispatch"); una lectura (search_messages)
    # no, y debe poder auto-ejecutar. Esto preserva "seguro pero no paralizado".
    "reply", "comment", "tweet", "call", "ping",
    # exfiltración / salida de datos
    "exfil", "leak", "export", "upload", "transfer", "forward", "relay",
    # escritura / mutación de estado
    "write", "update", "insert", "append", "add", "create", "delete", "remove",
    "drop", "set", "put", "patch", "edit", "modify", "save", "store", "commit",
    "execute", "run", "exec", "deploy", "install", "purchase", "buy", "sell",
    "pay", "transfer_funds", "wire", "charge", "refund", "revoke", "grant",
    "approve", "submit", "apply", "merge", "rename", "move", "copy", "sync",
    "enviar", "envio", "mandar", "borrar", "eliminar", "actualiz",
    "crear", "modificar", "guardar", "subir", "pagar", "transferir", "publicar",
)

# ── "escrib" NO puede ser substring pelado (integración tanda-P) ───────────────
# `escrib` ∈ `d-escrib-e`: `describe_table` —una LECTURA— caía a write-world y pedía
# permiso cada vez (falso positivo reportado por FIX-P4 §8.1). El único vocablo que
# genera la colisión es la familia `describ-` (describe/describir/redescribir), toda
# ella de lectura. Se exige por eso que la raíz NO venga precedida de 'd'.
#   escribir · escribe · db_escribir · sobrescribir · reescribir   → SÍ escritura
#   describe · describe_table · describir_tabla · sqlite_describe  → NO
# MANTENER EN SYNC con platform/gates/recipe_enforcer._ESCRIB_RE.
_ESCRIB_RE = re.compile(r"(?<!d)escrib")


def _suggests_escritura(tool: str) -> bool:
    """La raíz castellana de escritura, con la familia `describ-` excluida."""
    return _ESCRIB_RE.search((tool or "").lower()) is not None

# Verbos/raíces de LECTURA OBVIA — los únicos que pueden auto-ejecutar si no hay
# regla. Deben ser inequívocamente de solo-lectura. Se matchean por TOKEN COMPLETO
# (no substring): la brecha del review de Fase 2 fue que "count" ∈ "account" hacía
# que `fund_account` / `account_debit` pasaran como lectura → auto-ejecutaban money.
# Con match por token, "account" ya NO contiene el token de lectura "count".
_READ_ONLY_HINTS = frozenset({
    "get", "read", "list", "fetch", "search", "find", "query", "lookup",
    "view", "show", "describe", "inspect", "scan", "count", "check", "status",
    "echo", "preview", "render", "format", "parse", "validate",
    "leer", "buscar", "consultar", "ver", "mostrar", "listar", "obtener",
})

# ── A2 · CLASIFICACIÓN DE ACCIÓN × PERILLA DE AUTONOMÍA ────────────────────────
#
# La perilla de Autonomía (manual / balanceado / autónomo) es un CANDADO DE RUNTIME
# que vive DENTRO del gate: la receta no la puede editar para bajar el piso. Se aplica
# como MODIFICADOR post-clasificación. `money_touch` es piso INMUTABLE bajo TODA
# autonomía (ni 'autónomo' lo afloja). Tabla:
#
#     clase        | manual | balanceado(def) | autónomo
#     -------------|--------|-----------------|---------
#     read         | auto   | auto            | auto
#     write-local  | HOLD   | auto            | auto
#     write-world  | HOLD   | HOLD            | auto      (send / escritura externa no-money)
#     money_touch  | HOLD   | HOLD            | HOLD      (piso duro, invariante §3.5)
#
# `money_touch` se decide con un espejo INDEPENDIENTE de recipe_enforcer.MONEY_TOUCH_HINTS
# (defensa en profundidad: una tool evasiva tiene que esquivar AMBAS listas). Ídem send.
# MANTENER EN SYNC con platform/gates/recipe_enforcer.py {MONEY_TOUCH_HINTS, SEND_HINTS}.

_MONEY_HINTS = (
    "pay", "payment", "transfer", "wire", "remit", "charge", "refund",
    "buy", "sell", "trade", "place_order", "execute_order", "submit_order",
    "cancel_order", "settle", "settlement", "withdraw", "deposit", "checkout",
    "purchase", "subscribe_paid", "payout", "disburse",
    "fund_", "debit", "_paid", "get_paid", "deduct", "credit_card", "topup", "top_up",
    "batch_update_cells", "update_cells", "add_rows", "write_to_sheet",
    "pagar", "transferir", "transferencia", "girar", "cobrar", "reembolsar",
    "comprar", "vender", "liquidar", "retirar", "depositar", "debitar", "acreditar",
)

_SEND_HINTS = (
    "send", "sendmail", "send_message", "send_mail", "sendmessage",
    "post_message", "dispatch", "notify", "broadcast", "publish", "deliver",
    "transmit", "tweet", "whatsapp", "sms", "reply_all", "forward_mail",
    "email_send", "mail_send", "outbound",
    "enviar", "envio_", "_envio", "mandar", "difundir", "publicar", "reenviar",
)

# NOTA (A2 · review adversarial): NO hay lista de "cómputo local por nombre". Los verbos
# de cómputo (run/exec/execute/compute/add/sub…) son AMBIGUOS por substring —
# `run_command`=shell, `execute_transaction`=plata, `add_webhook`=externo — y clasificarlos
# 'write-local' auto-ejecutaba tools peligrosas bajo la perilla DEFAULT. `write-local` ahora
# SÓLO llega por declaración explícita (belt.action_classes / rule / forged kind).

# Verbos que delatan MUTACIÓN EXTERNA (crear/editar/borrar recursos afuera del proceso):
# PRs, issues, deploys, escrituras remotas. PISO write-world (antes de `declared`, así una
# receta no puede degradarlos a lectura/local). Substring, case-insensitive.
_EXTERNAL_WRITE_HINTS = (
    "create", "insert", "delete", "remove", "drop", "update", "patch", "edit",
    "modify", "write", "store", "commit", "merge", "deploy", "install",
    "submit", "apply", "grant", "revoke", "rename", "move", "sync", "upload",
    "export", "forward", "relay", "share", "invite", "post", "put", "set",
    "borrar", "eliminar", "actualiz", "crear", "modificar", "guardar", "subir",
)
# "escrib" sale de la tupla y entra por `_suggests_escritura` (ver _ESCRIB_RE): como
# substring pelado convertía `describe_table` en mutación externa.

# Perilla de Autonomía: los tres valores válidos. Ausente → 'balanceado' (default de
# producto). Un valor no reconocido → 'manual' (el MÁS estricto): fail-safe.
_AUTONOMY_LEVELS = ("manual", "balanceado", "autonomo")

# Tabla clase × autonomía → disposición ('hold' = NEEDS_OK | 'execute' = auto-ejecuta).
# money_touch se cortocircuita ANTES de la tabla (piso), pero la fila queda por claridad.
_POLICY: dict[str, dict[str, str]] = {
    "read":        {"manual": "execute", "balanceado": "execute", "autonomo": "execute"},
    "write-local": {"manual": "hold",    "balanceado": "execute", "autonomo": "execute"},
    "write-world": {"manual": "hold",    "balanceado": "hold",    "autonomo": "execute"},
    # Código arbitrario conserva autoridad de host hasta que exista un jail medido.
    # Ninguna perilla de producto puede convertir esa autoridad en auto-ejecución.
    "code_exec":   {"manual": "hold",    "balanceado": "hold",    "autonomo": "hold"},
    "money_touch": {"manual": "hold",    "balanceado": "hold",    "autonomo": "hold"},
}

# Ejecución de código arbitrario. Es un PISO independiente de declaraciones de belts
# o recetas: cambiar `run_python` a `read`/`write-local` jamás debe degradarlo.
_CODE_EXEC_HINTS = (
    "run_python", "run_shell", "run_code", "run_command", "run_script",
    "run_bash", "run_javascript", "run_js", "execute_code", "exec_code",
    "eval_code", "code_exec", "shell_exec", "aleph_run_code", "insert_execute_code",
    "execute_cell", "stata_run",
)


def _suggests_code_exec(tool: str) -> bool:
    t = (tool or "").lower()
    return any(h in t for h in _CODE_EXEC_HINTS)


def _norm_autonomy(value) -> str:
    """Normaliza la perilla. None/'' → 'balanceado' (default de producto). Un valor
    no reconocido (typo, inyección) → 'manual' (el MÁS estricto): jamás afloja por
    accidente. Es el candado que la receta no puede sobornar con basura."""
    if value is None or value == "":
        return "balanceado"
    v = str(value).strip().lower()
    return v if v in _AUTONOMY_LEVELS else "manual"


def _suggests_money(tool: str) -> bool:
    """¿El nombre delata que TOCA PLATA? (espejo independiente del enforcer)."""
    t = (tool or "").lower()
    return any(h in t for h in _MONEY_HINTS)


def _suggests_send(tool: str) -> bool:
    """¿El nombre delata que MANDA AFUERA? (espejo independiente del enforcer)."""
    t = (tool or "").lower()
    return any(h in t for h in _SEND_HINTS)


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _tokens(name: str) -> list[str]:
    """Parte un nombre de tool en TOKENS: separa por no-alfanumérico Y por
    camelCase (insertando un corte antes de una mayúscula que sigue a minúscula/
    dígito). 'fund_account' → [fund, account]; 'lookupPrice' → [lookup, price]."""
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name or "")
    return [m.group(0).lower() for m in _TOKEN_RE.finditer(s)]


def _suggests_write_or_send(tool: str) -> bool:
    """¿El nombre de la tool sugiere escritura/envío/efecto externo? (substring,
    conservador HACIA gatear — acá un falso positivo solo significa 'pregunta', seguro)."""
    t = (tool or "").lower()
    return any(h in t for h in _WRITE_EFFECT_HINTS) or _suggests_escritura(t)


def _is_obvious_read(tool: str) -> bool:
    """¿El nombre es inequívocamente de SOLO LECTURA? Requiere un TOKEN COMPLETO de
    lectura (no substring) y NINGUNA pista de escritura/envío. Ante la duda → False
    (cae a fail-closed = confirma-siempre). 'get_and_send' → False (tiene 'send')."""
    if not (_READ_ONLY_HINTS & set(_tokens(tool))):
        return False
    return not _suggests_write_or_send(tool)


# ── Decisión del gate ─────────────────────────────────────────────────────────

class GateDecision:
    """Resultado de evaluar una acción contra la matriz."""

    EXECUTE = "execute"          # auto-ejecuta, o confirma-* ya aprobado
    NEEDS_OK = "needs_ok"        # confirma-siempre / confirma-una-vez sin OK aún
    BLOCKED = "blocked"          # prohibido-en-tier-average

    def __init__(self, action: str, level: str, payload: Optional[dict] = None,
                 reason: str = "", action_class: Optional[str] = None):
        self.action = action          # EXECUTE | NEEDS_OK | BLOCKED
        self.level = level            # nombre del nivel de la matriz
        self.payload = payload or {}  # contrato de UX (qué/dónde/preview/ok) o motivo de bloqueo
        self.reason = reason
        # A2 · clase de acción resuelta (read/write-local/write-world/money_touch), para
        # la bitácora. None en returns pre-clasificación (BLOCKED / fail-closed de config).
        self.action_class = action_class

    def __repr__(self) -> str:
        return f"GateDecision({self.action}, level={self.level!r}, class={self.action_class!r})"


# ── El gate ───────────────────────────────────────────────────────────────────

class ApprovalGate:
    """
    Evalúa cada tool-call contra la matriz y devuelve una GateDecision.

    Estado de sesión: recuerda qué acciones 'confirma-una-vez' ya fueron
    aprobadas en esta sesión (no se vuelve a preguntar). 'confirma-siempre'
    pregunta cada vez por diseño.

    El gate NO ejecuta la tool: solo decide e instrumenta el payload. Quien
    lo monta (el runtime) decide cómo recolectar el OK del usuario.
    """

    # Nivel al que cae TODA tool desconocida que no sea lectura obvia. Es el
    # piso de seguridad: nunca por debajo de "pregunta cada vez". Configurable
    # vía matrix["fail_closed_level"], pero el motor NUNCA lo deja en auto-ejecuta.
    FAIL_CLOSED_LEVEL = "confirma-siempre"

    def __init__(self, matrix: dict, *,
                 bound_args: Optional[dict] = None,
                 sandbox_available: bool = True,
                 autonomy: Optional[str] = None,
                 preview_renderer: Optional[Callable[[str, str, dict, dict], str]] = None):
        self.matrix = matrix
        self.levels = matrix.get("levels", {})
        # MURALLA PREMIUM · vocabulario del gate: SOLO 'premium' desbloquea un level premium-gated.
        # Default 'average' (gateable) = fail-closed. El tier lo IMPONE build_enforced_gate desde la
        # CUENTA (allowlist basico/tecnico→'premium'); acá nunca se confía en recipe.tier.
        self.tier = matrix.get("tier", "average")
        # Nivel fail-closed para desconocidas-que-escriben/desconocidas-no-lectura.
        self.fail_closed_level = matrix.get("fail_closed_level", self.FAIL_CLOSED_LEVEL)
        # default_level: SOLO se usa cuando la desconocida es una LECTURA OBVIA.
        # Si la config trae default_level=auto-ejecuta, eso solo aplica a lecturas;
        # jamás a una desconocida que sugiere escritura/envío (esas van fail-closed).
        self.default_level = matrix.get("default_level", "auto-ejecuta")
        self.rules = matrix.get("rules", [])
        # bound_args: valores atados al CREAR el agente (ej. spreadsheet_id declarado).
        # El gate rechaza toda llamada cuyo destino != el id atado (lista blanca de uno).
        self.bound_args = bound_args or {}
        self.sandbox_available = sandbox_available
        # ── A2 · perilla de Autonomía (candado runtime; la receta NO la baja) ──
        # Prioridad: kwarg explícito > matrix["autonomy"] > default 'balanceado'.
        self.autonomy = _norm_autonomy(autonomy if autonomy is not None
                                       else matrix.get("autonomy"))
        self._preview_renderer = preview_renderer or _default_preview
        self._approved_once: set = set()   # claves de acciones confirma-una-vez ya OK

    # ── API pública ──

    @classmethod
    def from_config(cls, path: str, **kwargs) -> "ApprovalGate":
        matrix = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(matrix, **kwargs)

    def evaluate(self, server: str, tool: str, arguments: dict) -> GateDecision:
        """Decide qué hacer ante una acción, SIN ejecutarla."""
        rule = self._match_rule(server, tool)
        level_name = self._resolve_level(rule, tool)
        level = self.levels.get(level_name, {})

        # 0) FAIL-CLOSED de último recurso: si una desconocida cayó al nivel
        # fail-closed pero la matriz NO definió ese nivel (config rota), forzamos
        # NEEDS_OK igual — la duda nunca ejecuta sola.
        if rule is None and not self._is_known_safe(tool) and not level.get("requires_ok") \
                and not level.get("blocked"):
            payload = self._build_ux_payload(None, self.fail_closed_level,
                                             self.levels.get(self.fail_closed_level, {}),
                                             server, tool, arguments)
            payload["leyenda"] = payload.get("leyenda") or "Tu agente te pregunta cada vez, antes de hacerlo."
            return GateDecision(GateDecision.NEEDS_OK, self.fail_closed_level, payload=payload)

        # 1) ¿prohibido en este tier? FAIL-CLOSED: bloquea salvo que el tier sea EXACTAMENTE
        # 'premium' (un tier desconocido/mal escrito → bloquea, nunca abre — SEV crítico si abriera).
        if level.get("blocked") and self.tier != "premium":
            return GateDecision(
                GateDecision.BLOCKED, level_name,
                payload={"motivo": level.get("copy", "No disponible en tu cuenta."),
                         "tier": self.tier},
                reason=level.get("copy", ""),
            )

        # 1b) tier_block dinámico: ej. enviar SIN vista previa, o código SIN sandbox.
        # FAIL-CLOSED: correr código sin caja es un privilegio premium; bloquea salvo que el
        # tier sea EXACTAMENTE 'premium' (desconocido/mal escrito → bloquea, nunca abre).
        if rule:
            tb = rule.get("tier_block", {})
            if tb.get("when_no_sandbox") and not self.sandbox_available and self.tier != "premium":
                return GateDecision(
                    GateDecision.BLOCKED, "prohibido-en-tier-average",
                    payload={"motivo": "Tu cuenta básica no puede correr código sin caja de seguridad.",
                             "regla": tb.get("reason", "")},
                    reason=tb.get("reason", ""),
                )

        # 1c) lista blanca de uno: el destino atado al crear el agente manda
        bind = rule.get("bind_arg") if rule else None
        if bind:
            arg_name = bind["arg"]
            bound_key = bind["to"]
            expected = self.bound_args.get(bound_key)
            actual = arguments.get(arg_name)
            if expected is not None and actual is not None and actual != expected:
                return GateDecision(
                    GateDecision.BLOCKED, level_name,
                    payload={"motivo": (
                        "Tu agente intentó tocar un destino que no autorizaste al crearlo. "
                        f"Lo armaste para «{expected}», pero pidió «{actual}». Lo frenamos."
                    ), "esperado": expected, "intentado": actual},
                    reason="destino fuera de la lista blanca de uno",
                )

        # 2) A2 · CLASIFICACIÓN DE ACCIÓN × PERILLA DE AUTONOMÍA ─────────────────
        # Se aplica DESPUÉS de resolver el nivel y DESPUÉS de todos los BLOCKED
        # (tier/sandbox/bind ya devolvieron arriba). La perilla es autoritativa para
        # el par auto/hold del camino no-bloqueado; `money_touch` es piso inmutable.
        action_class = self.classify_action(
            server, tool, arguments,
            rule.get("action_class") if rule else None,
        )

        # 2a) money_touch y code_exec = PISOS DUROS: SIEMPRE NEEDS_OK, bajo TODA
        # autonomía. code_exec mantiene autoridad de host mientras no haya un jail
        # medido; una aprobación NO se presenta como aislamiento.
        # 'autónomo' lo baja), y ANTES de once_per_session (un money aprobado-una-vez
        # NO puede auto-pasar). Invariante §3.5 viva en el interceptor.
        if action_class in ("money_touch", "code_exec"):
            payload = self._build_ux_payload(rule, level_name, level, server, tool, arguments)
            payload["accion_clase"] = action_class
            payload["autonomia"] = self.autonomy
            return GateDecision(GateDecision.NEEDS_OK, level_name, payload=payload,
                                action_class=action_class)

        # 2b) resto de clases: la tabla decide según la perilla.
        disposition = _POLICY.get(action_class, _POLICY["write-world"]).get(self.autonomy, "hold")

        if disposition == "execute":
            # La perilla concede. Es AUTORITATIVA sobre el nivel de la matriz para el
            # camino no-money/no-bloqueado: 'autónomo' relaja un write-world que la
            # matriz tenía en confirma-siempre (ese es el sentido de la perilla).
            return GateDecision(GateDecision.EXECUTE, level_name, action_class=action_class)

        # disposition == "hold": pero respetar confirma-una-vez ya aprobado en la sesión.
        if level.get("once_per_session") and self._once_key(server, tool) in self._approved_once:
            return GateDecision(GateDecision.EXECUTE, level_name, action_class=action_class)

        payload = self._build_ux_payload(rule, level_name, level, server, tool, arguments)
        payload["accion_clase"] = action_class
        payload["autonomia"] = self.autonomy
        return GateDecision(GateDecision.NEEDS_OK, level_name, payload=payload,
                            action_class=action_class)

    def grant_ok(self, server: str, tool: str) -> None:
        """Registra el OK del usuario. Para confirma-una-vez, no se vuelve a pedir."""
        level_name = self._level_for(server, tool)
        level = self.levels.get(level_name, {})
        if level.get("once_per_session"):
            self._approved_once.add(self._once_key(server, tool))

    # ── internos ──

    def _match_rule(self, server: str, tool: str) -> Optional[dict]:
        for rule in self.rules:
            m = rule.get("match", {})
            srv = m.get("server", "*")
            if srv != "*" and srv != server:
                continue
            tools = m.get("tools")
            if tools is not None and tool not in tools:
                # no está en la lista exacta; probar substring
                contains = m.get("tool_name_contains")
                if not (contains and any(c in tool.lower() for c in contains)):
                    continue
            elif tools is None:
                contains = m.get("tool_name_contains")
                if contains and not any(c in tool.lower() for c in contains):
                    continue
            return rule
        return None

    def _level_for(self, server: str, tool: str) -> str:
        rule = self._match_rule(server, tool)
        return self._resolve_level(rule, tool)

    def _resolve_level(self, rule: Optional[dict], tool: str) -> str:
        """
        Nivel efectivo de una tool. FAIL-CLOSED para desconocidas (brecha 1):

          • con regla en la matriz   -> el nivel de la regla (la matriz manda).
          • sin regla + LECTURA obvia -> default_level (puede ser auto-ejecuta).
          • sin regla + escribe/envía
            o sin regla + NO es lectura obvia (ante la duda)
                                       -> fail_closed_level (confirma-siempre).

        El default_level configurable JAMÁS aplica a una desconocida que no sea
        lectura obvia: esas caen al piso de seguridad, no al default permisivo.
        """
        if rule is not None:
            return rule["level"]
        if self._is_known_safe(tool):
            return self.default_level
        return self.fail_closed_level

    @staticmethod
    def _is_known_safe(tool: str) -> bool:
        """Solo una LECTURA OBVIA (y no-escritura) es 'segura' sin regla."""
        return _is_obvious_read(tool)

    def classify_action(self, server: str, tool: str, arguments: dict,
                        declared: Optional[str] = None) -> str:
        """
        Clasifica una acción en {read, write-local, write-world, code_exec,
        money_touch} para
        que la perilla de Autonomía decida auto/hold. PISOS PRIMERO (money, luego
        send) para que un `declared` del belt NUNCA pueda bajar el piso de seguridad;
        recién después el declarado manda para el resto (autoritativo no-money); y al
        final la heurística por nombre, con fail-closed a write-world.

        `declared`: la clase que declara el belt/catálogo o la regla de la matriz
        (`rule["action_class"]`). Incluye la `kind` del forged-MCP: 'write' = escritura
        a la API real ⇒ write-world; 'read' ⇒ read.

        ⚠ NO existe heurística de "cómputo local por nombre": un nombre de verbo de
        cómputo (`run`, `exec`, `execute`, `compute`…) es AMBIGUO — `run_command` es un
        shell remoto, `execute_transaction` mueve plata, `run_deploy` publica. Adivinar
        'write-local' por esos substrings auto-ejecutaba tools mundo/plata bajo la
        perilla DEFAULT ('balanceado'). Por eso: `write-local` SÓLO llega por DECLARACIÓN
        explícita; todo lo no-declarado que no sea lectura obvia cae a write-world
        (fail-closed = gatea bajo manual/balanceado; sólo 'autónomo' lo deja pasar).
        """
        name = (tool or "").lower()

        # 0) PISO code-exec: gana incluso sobre declaraciones adversarias `read` o
        #    `write-local`. Mientras la implementación conserve autoridad de host,
        #    el código arbitrario nunca auto-ejecuta.
        if _suggests_code_exec(name):
            return "code_exec"

        # 1) PISO money (gana sobre TODO, incluido declared: defensa en profundidad).
        if _suggests_money(name):
            return "money_touch"

        # 2) PISO send/externo (el belt no puede degradar un envío a lectura/local).
        if _suggests_send(name):
            return "write-world"

        # 3) PISO mutación-externa: verbos que INEQUÍVOCAMENTE tocan afuera
        #    (crear/borrar/deploy/publicar/otorgar…). Va ANTES de `declared` — es un piso,
        #    no una heurística de respaldo — para que una receta (potencialmente adversaria)
        #    NO pueda declarar 'read'/'write-local' a un create_pr / delete_repo / deploy y
        #    auto-ejecutarlo. Los verbos de cómputo (run/exec) NO están acá: son ambiguos y
        #    caen a fail-closed (write-world) salvo declaración explícita de write-local.
        if any(h in name for h in _EXTERNAL_WRITE_HINTS) or _suggests_escritura(name):
            return "write-world"

        # 4) DECLARADO (autoritativo SÓLO para el medio ambiguo que no cayó a un piso:
        #    read / write-local / write-world). Un declared 'read'/'write-local' sobre un
        #    nombre mundo/plata/send ya fue interceptado por los pisos 1-3 y jamás llega acá.
        if declared:
            d = str(declared).strip().lower()
            if d in ("money", "money_touch", "money-touch"):
                return "money_touch"
            if d in ("write-world", "write_world", "world", "send", "external"):
                return "write-world"
            if d in ("write-local", "write_local", "local"):
                return "write-local"
            if d == "read":
                return "read"
            # forged-MCP kind:'write' = escritura a la API real (toca el mundo).
            if d == "write":
                return "write-world"

        # 5) lectura obvia (token completo, sin pista de escritura) → read.
        if _is_obvious_read(tool):
            return "read"

        # 6) FAIL-CLOSED: cualquier no-lectura, no-declarada, sin verbo-externo claro
        #    (incluye run_command / execute_* / cómputo-por-nombre) → write-world. NO se
        #    adivina 'write-local': un nombre de cómputo puede ser un shell remoto. La
        #    duda gatea bajo manual/balanceado; sólo 'autónomo' la deja pasar.
        return "write-world"

    @staticmethod
    def _once_key(server: str, tool: str) -> str:
        return f"{server}:{tool}"

    def _build_ux_payload(self, rule: Optional[dict], level_name: str, level: dict,
                          server: str, tool: str, arguments: dict) -> dict:
        if rule is None:
            # Tool DESCONOCIDA caída a fail-closed: copy honesto, sin jerga.
            # No afirmamos qué hace exactamente (no la conocemos); avisamos que
            # parece tocar algo afuera/escribir y por eso pedimos OK.
            what = "hacer algo que no reconocemos y que parece escribir o enviar afuera"
            where = "un destino fuera de tu espacio de solo-lectura"
            preview_kind = "accion"
        else:
            what = rule.get("what", f"usar la herramienta {tool}")
            where = rule.get("where", "tu espacio de trabajo")
            preview_kind = rule.get("preview_kind", "accion")
        # vista previa del cambio/mensaje, sin jerga, sin valores de secretos
        preview = self._preview_renderer(preview_kind, tool, arguments, self.bound_args)
        return {
            # (a) QUÉ va a hacer
            "que_va_a_hacer": what,
            # (b) DÓNDE / a quién afecta
            "donde_afecta": where,
            # (c) VISTA PREVIA del cambio/mensaje
            "vista_previa": preview,
            # (d) requiere OK explícito
            "requiere_ok": True,
            "boton_ok": "OK, hazlo",
            "boton_cancelar": "No, cancela",
            # copy oficial del nivel (§2 del threat-model)
            "nivel": level_name,
            "leyenda": level.get("copy", ""),
        }


# ── Render por defecto de la vista previa (sin jerga, secret-safe) ─────────────

def _default_preview(kind: str, tool: str, arguments: dict, bound_args: dict) -> str:
    """
    Vista previa en lenguaje de persona promedio. NUNCA muestra valores de
    credenciales (el scrubber es la red de seguridad; acá ni los pedimos).
    """
    if kind == "celdas":
        sid = arguments.get("spreadsheet_id") or bound_args.get("spreadsheet_id") or "tu hoja"
        rng = arguments.get("range") or arguments.get("sheet") or "la pestaña indicada"
        n = _count_cells(arguments)
        cuantas = f"{n} celdas" if n else "algunas celdas"
        return f"Va a escribir {cuantas} en «{rng}» de tu Google Sheet ({sid})."
    if kind == "mensaje":
        dest = arguments.get("to") or arguments.get("recipient") or arguments.get("chat") or "el destinatario"
        body = (arguments.get("body") or arguments.get("text") or arguments.get("message") or "").strip()
        snippet = (body[:280] + "…") if len(body) > 280 else body
        return f"Le va a mandar a «{dest}»:\n\n{snippet}"
    if kind == "codigo-host":
        code = (arguments.get("code") or arguments.get("source") or "").strip()
        snippet = (code[:400] + "…") if len(code) > 400 else code
        return ("Va a correr este código con la autoridad del proceso de Aleph; "
                "no hay aislamiento de sistema operativo:\n\n" + snippet)
    if kind == "codigo":
        code = (arguments.get("code") or arguments.get("source") or "").strip()
        snippet = (code[:400] + "…") if len(code) > 400 else code
        return f"Va a correr este código en el cuaderno aislado:\n\n{snippet}"
    if kind == "archivo":
        fp = arguments.get("filepath") or arguments.get("path") or arguments.get("filename") or "un archivo nuevo"
        return f"Va a guardar el resultado en: {fp}"
    if kind == "conexion":
        return "Va a guardar tu credencial cifrada. El modelo nunca ve su valor; solo la usa la herramienta."
    return f"Acción: {tool} con {len(arguments)} parámetros."


def _count_cells(arguments: dict) -> int:
    data = arguments.get("data") or arguments.get("values") or arguments.get("cells")
    if isinstance(data, list):
        total = 0
        for row in data:
            total += len(row) if isinstance(row, (list, tuple)) else 1
        return total
    return 0
