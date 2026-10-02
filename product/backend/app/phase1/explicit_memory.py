#!/usr/bin/env python3
"""explicit_memory.py — Pieza 1 del sistema de memoria · CAPTURA EXPLÍCITA DETERMINISTA.

CONTEXTO (sonda 0, [[memoria-sonda0-sustrato]]): el destilado automático al cierre del run es
un JUICIO probabilístico (2da llamada al modelo con el escape "respondé NADA") → pinnea de forma
NO determinista (~17% en ráfaga). Está BIEN que el distill IMPLÍCITO sea flaky. Pero cuando el
usuario pide EXPLÍCITAMENTE "recordá esto" / "guardá estos datos", la captura NO puede depender de
ese juicio: debe ser DETERMINISTA y VERBATIM.

Esta pieza es la frontera: un detector PURO (sin LLM) que reconoce una DIRECTIVA de captura
explícita en el pedido del usuario y devuelve el contenido a guardar tal cual. El executor lo
persiste con source='user', pinned=True — que el READ path (probado sólido en la sonda 0) recupera
en sesiones frías, y que enforce_memory_caps RETIENE por encima de lo destilado (user > agent).

DISEÑO conservador (precisión > recall): sólo dispara ante un VERBO imperativo de captura + un
conector deíctico (esto/eso/que/:/estos datos …) + un payload no vacío. NO dispara ante pedidos de
RECALL ("recordame la premisa", "¿te acordás?", "recordarme X") — esos RECUPERAN, no guardan.
Ante la duda, NO captura (mejor perder una captura ambigua que ensuciar la memoria con una pregunta).
"""
from __future__ import annotations

import re
from typing import Optional

# Tope de caracteres del contenido capturado (alineado con el ceiling por-tier del runtime; el
# executor igual re-enforza caps por bytes/entradas). Un pedido explícito puede ser algo más largo
# que un ítem destilado, pero no un pato entero.
MAX_CAPTURE_CHARS = 600

# Verbos imperativos de CAPTURA (voseo rioplatense + estándar ES + EN). Deliberadamente NO incluye
# "acordate"/"recordame"/"remind" (ambiguos con recordatorio/recall). [ticket 24] suma el SUBJUNTIVO
# "recuerde/recuerdes" ("quiero que recuerdes esto: X" = captura); NO suma "recuerdas" (tú-presente =
# recall: "¿recuerdas el trato?").
_VERB = r"(?:record[áa]|recuerd(?:es|e|a)|guard[áa]|guarda|anot[áa]|anota|apunt[áa]|apunta|remember|save|note|keep\s+in\s+mind)"

# Conector deíctico que debe seguir al verbo (con espacio en medio) para que sea una directiva de
# captura con payload. El ':' cuenta como conector directo. Los multi-palabra van PRIMERO y todos
# llevan \b final: si no, "esto" comería el prefijo de "estos datos" (alternación ordenada) y el
# payload arrancaría en "s datos: …".
_CONNECTOR = (
    r"(?:"
    r"estos?\s+datos?|este\s+dato|lo\s+siguiente|lo\s+de(?:l)?"      # ES multi-palabra (primero)
    r"|the\s+following"                                              # EN multi-palabra
    r"|esto|eso|que"                                                 # ES cortos
    r"|this|that"                                                    # EN cortos
    r")\b"
)

# [ticket 24] Filler/deíctico opcional entre el verbo y el conector/':' — formas naturales enterradas
# ("recordá BIEN esto: X", "recordá UNA COSA: X", "recordá POR LAS DUDAS que X"). Whitelist acotado
# (no "\w+ genérico") para no relajar la precisión hacia payloads-basura.
_FILLER = r"(?:bien|una\s+cosa|una\s+cosita|algo(?:\s+importante)?|por\s+las?\s+dudas?)"

# Directiva completa: (verbo)(espacio)(conector)(opcional :,)(payload). El ':' puede ir pegado al
# verbo (record[áa] :) o después del conector (estos datos:). El payload es todo hasta fin de LÍNEA
# (una directiva de captura vive en una línea; una tarea de follow-up en otra línea NO se captura).
_DIRECTIVE = re.compile(
    r"(?<![\wáéíóúñ])"                       # borde izq (no en medio de palabra: evita 'grabar'→'guarda'? n/a, pero seguro)
    r"(?:por\s+favor[,\s]+)?"
    r"(?P<verb>" + _VERB + r")"
    r"(?:"
    r"\s*[:]\s*"                                                     # verbo + ':' directo  → "recordá: X"
    r"|"
    r"(?:\s+" + _FILLER + r")?\s+" + _CONNECTOR + r"\s*[:,]?\s*"     # verbo (+ filler)? + conector → "recordá (bien) esto: X"
    r"|"
    r"\s+" + _FILLER + r"\s*[:]\s*"                                  # verbo + filler + ':'  → "recordá una cosa: X"
    r")"
    r"(?P<payload>[^\n\r]+)",
    re.IGNORECASE,
)

# [ticket 24] Directiva ANAFÓRICA: el hecho va ANTES de un "recordá esto/eso" que cierra el mensaje
# ("…el grillete GY-24-004 quedó en cuarentena. recordá esto."). La extracción forward-only del
# _DIRECTIVE dejaba payload vacío → caía al destilador (source='agent'). Acá capturamos hacia ATRÁS:
# el deíctico apunta al texto previo, con SÓLO una cola trivial permitida (puntuación + "ok/dale/
# seguimos…"). `before` es greedy (última ocurrencia). El hecho = la última ORACIÓN de `before`.
_ANAPHORIC = re.compile(
    r"(?P<before>.*)"
    r"(?<![\wáéíóúñ])(?:por\s+favor[,\s]+)?"
    r"(?P<verb>" + _VERB + r")"
    r"\s+(?:esto|eso|this|that|lo\s+anterior|lo\s+de\s+arriba)\b"
    r"[\s.,;:!?¿¡]*"
    r"(?:(?:ok|okay|okey|dale|porfa|gracias|listo|seguimos|sigamos|segu[ií]|entonces)\b[\s.,;:!?¿¡]*)*"
    r"$",
    re.IGNORECASE | re.DOTALL,
)

# [ticket 24] Un payload FORWARD que es SÓLO cola conversacional trivial ("¿ok?", "porfa", "dale",
# ".") NO es un hecho: "…el mínimo es 6. recordá esto, ¿ok?" hacía que el forward capturara "¿ok?"
# y el anafórico nunca corriera. Si el payload matchea esto → se trata como vacío → cae al anafórico.
_TRIVIAL_TAIL = re.compile(
    r"^[\s.,;:!?¿¡'\"“”`]*"
    r"(?:ok(?:ay|ey)?|dale|porfa|por\s+favor|gracias|listo|seguimos|sigamos|segu[ií]|entonces|s[ií]|ya|no)?"
    r"[\s.,;:!?¿¡'\"“”`]*$",
    re.IGNORECASE,
)

# Formas de RECALL a excluir SIEMPRE (recuperan, no guardan). Si el pedido es SÓLO recall (y no hay
# también una directiva de captura), no capturamos. Enclíticos: recordame/recordarme/recuérdame.
_RECALL_ENCLITIC = re.compile(
    r"(?<![\wáéíóúñ])(?:record[áa]me|recordarme|recu[eé]rdame|remind\s+me)",
    re.IGNORECASE,
)


def detect_capture(prompt: str) -> Optional[str]:
    """Devuelve el contenido a guardar VERBATIM si el pedido contiene una directiva de captura
    explícita; None si no hay ninguna (o si es un pedido de recall). Puro y determinista."""
    if not isinstance(prompt, str) or not prompt.strip():
        return None

    for m in _DIRECTIVE.finditer(prompt):
        # Excluir el caso en que el match cae sobre un enclítico de recall (record[áa]me…): el
        # verbo del match no debe ser el arranque de "recordame". Chequeo posicional.
        vstart = m.start("verb")
        tail = prompt[vstart:vstart + 12].lower()
        if _RECALL_ENCLITIC.match(tail):
            continue
        payload = (m.group("payload") or "").strip()
        # Limpiar comillas envolventes y puntuación de cierre suelta.
        payload = payload.strip().strip('"“”\'`').strip()
        payload = payload.rstrip(" .;,")
        if len(payload) < 2 or _TRIVIAL_TAIL.match(payload):
            continue          # sin contenido inline o sólo cola trivial → probá la forma ANAFÓRICA
        return payload[:MAX_CAPTURE_CHARS].strip()
    # forward vacío → ¿directiva ANAFÓRICA ("…<hecho>. recordá esto.")? el hecho va ANTES del verbo.
    return _anaphoric_capture(prompt)


def _anaphoric_capture(prompt: str) -> Optional[str]:
    """Captura hacia ATRÁS: "…<hecho>. recordá esto." → devuelve <hecho> (la última oración previa).
    Sólo dispara si el mensaje CIERRA con el deíctico (cola trivial permitida) — si hay un pedido
    real después, no es anafórico. PURO. Excluye el enclítico de recall (recordame…)."""
    m = _ANAPHORIC.search(prompt)
    if not m:
        return None
    vstart = m.start("verb")
    if _RECALL_ENCLITIC.match(prompt[vstart:vstart + 12].lower()):
        return None
    before = (m.group("before") or "").strip()
    if not before:
        return None
    # última ORACIÓN (partir SÓLO por fin de oración . ! ? y saltos — NO por comas: un hecho lleva
    # comas internas, "…por óxido, no usarlo hasta nueva inspección" es UN hecho).
    parts = [p.strip() for p in re.split(r"[.!?\n\r]+", before) if p.strip()]
    if not parts:
        return None
    fact = parts[-1].strip().strip('"“”\'`').rstrip(" .;,").strip()
    if len(fact) < 6:
        return None          # muy corto para ser un hecho → no capturamos (conservador)
    return fact[:MAX_CAPTURE_CHARS].strip()


# ═══════════════════════════════════════════════════════════════════════════════════════════
# PIEZA 2 · OLVIDO / CORRECCIÓN EXPLÍCITA — el inverso simétrico de la captura.
# El olvido es DESTRUCTIVO: un falso-positivo BORRA datos del usuario. Por eso el detector es
# EXTRA conservador (negación cerca del verbo → NO dispara; deíctico sin blanco → NO dispara) y el
# executor CAPEA (un match demasiado genérico que barrería TODO no se ejecuta). Determinismo: dado
# un pedido CLARO de olvido con blanco, el borrado es determinista; ante la duda, NO borra.
# ═══════════════════════════════════════════════════════════════════════════════════════════

# Negación que convierte un "olvido" en un KEEP ("no te olvides del deadline" = recordalo, NO borres).
_NEG_FORGET = re.compile(
    r"(?<![\wáéíóúñ])(?:no\s+(?:te\s+|se\s+)?(?:olvid|borr)|don'?t\s+forget|do\s+not\s+forget|never\s+forget)",
    re.IGNORECASE,
)

# OLVIDO TOTAL explícito → limpiar toda la memoria (equivale al botón 'limpiar' del panel).
_FORGET_ALL = re.compile(
    r"(?<![\wáéíóúñ])(?:"
    r"(?:olvid[áa](?:te|ate)?|borr[áa]|elimin[áa])\s+(?:todo|toda\s+(?:la\s+|mi\s+)?memoria|"
    r"todo\s+lo\s+que\s+(?:sab[eé]s|guardaste|te\s+dije|record[áa]s))"
    r"|forget\s+everything|clear\s+(?:my\s+|the\s+)?memory|delete\s+(?:all|everything)"
    r")",
    re.IGNORECASE,
)

# OLVIDO CON BLANCO → borrar las memorias que mencionan <target>. El blanco arranca tras un
# conector ("lo del/de/que guardaste sobre", "eso de", "la memoria de/sobre", "que", EN "about"…).
_FORGET_MATCH = re.compile(
    r"(?<![\wáéíóúñ])(?:olvid[áa](?:te|ate)?|borr[áa]|elimin[áa]|quit[áa])\s+"
    r"(?:lo\s+(?:del?\s+|de\s+la\s+|que\s+(?:guardaste|te\s+dije|sab[eé]s)\s+(?:sobre\s+|de\s+|del?\s+))"
    r"|eso\s+de\s+|la\s+memoria\s+(?:de\s+|sobre\s+)|que\s+)"
    r"(?P<target>[^\n\r]+)"
    r"|(?:forget|delete|remove)\s+(?:about\s+|what\s+you\s+(?:saved|know)\s+about\s+"
    r"|the\s+memory\s+(?:about|of)\s+)(?P<target2>[^\n\r]+)",
    re.IGNORECASE,
)


def detect_forget(prompt: str) -> Optional[dict]:
    """Devuelve {'mode':'all'} | {'mode':'match','target':str} | None. PURO y conservador: una
    negación ('no te olvides…') NUNCA dispara olvido; un deíctico sin blanco ('olvidá eso') tampoco
    (no hay blanco determinista). El executor aplica el CAP anti-barrido."""
    if not isinstance(prompt, str) or not prompt.strip():
        return None
    if _NEG_FORGET.search(prompt):
        return None                     # hay una negación de olvido → tratamos el pedido como KEEP
    if _FORGET_ALL.search(prompt):
        return {"mode": "all"}
    m = _FORGET_MATCH.search(prompt)
    if m:
        target = (m.group("target") or m.group("target2") or "").strip()
        target = target.strip('"“”\'`').rstrip(" .;,").strip()
        if len(target) >= 3:
            return {"mode": "match", "target": target[:MAX_CAPTURE_CHARS]}
    return None


# CORRECCIÓN: SÓLO el marcador explícito con dos-puntos "corregí: <nuevo>" / "corrección: <nuevo>"
# / "correction: <new>". Deliberadamente NO "corregí <x>" sin dos-puntos (eso es una TAREA:
# "corregí este código") ni "en realidad …" (casual, altísimo falso-positivo). Precisión > recall:
# una corrección de memoria es un acto DELIBERADO y marcado.
_CORRECTION_LEAD = re.compile(
    r"(?<![\wáéíóúñ])(?:correg[íi]|correcci[óo]n|correction)\s*:\s*(?P<rest>[^\n\r]+)",
    re.IGNORECASE,
)
# Dentro del clause, "…, no <viejo>" (ES) o "… not <old>" (EN) → el valor contradicho a olvidar.
_CORRECTION_OLD = re.compile(r",?\s+(?:no|not)\s+(?P<old>[^\n\r,.;]+)$", re.IGNORECASE)


def detect_correction(prompt: str) -> Optional[dict]:
    """Devuelve {'new': str, 'old': Optional[str]} | None. 'new' = el hecho corregido a GUARDAR
    (verbatim, se agrega como memoria nueva que supera a la vieja por recencia); 'old' = valor
    contradicho a olvidar si el clause '…, no <viejo>' lo nombra. PURO. Requiere el marcador
    explícito 'corregí:/corrección:/correction:' (no dispara ante 'corregí <tarea>' casual)."""
    if not isinstance(prompt, str) or not prompt.strip():
        return None
    m = _CORRECTION_LEAD.search(prompt)
    if not m:
        return None
    rest = (m.group("rest") or "").strip().strip('"“”\'`').rstrip(" .;,").strip()
    if len(rest) < 2:
        return None
    old = None
    new = rest
    om = _CORRECTION_OLD.search(rest)
    if om:
        old = (om.group("old") or "").strip().strip('"“”\'`').strip()
        old = old if len(old) >= 3 else None
        new = rest[:om.start()].rstrip(" ,.;").strip() or rest    # el hecho corregido, sin el '…, no <viejo>'
    if len(new) < 2:
        return None
    return {"new": new[:MAX_CAPTURE_CHARS], "old": old}
