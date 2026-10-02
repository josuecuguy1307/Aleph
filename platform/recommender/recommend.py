#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Recomendador v0 de la Guía — nicho FINANZAS.

Qué hace: toma una intención del usuario en español libre y devuelve un ranking
de PIEZAS del catálogo real (7 servers de catalog/belts/finanzas.md + 10 kits de
catalog/templates/finanzas/) con score y razón legible por pieza.

v0 HONESTO — declarado explícito:
  * Scoring 100% DETERMINÍSTICO, stdlib puro. NADA de LLM ni embeddings.
  * Evidencia = keywords/capacidades DECLARADAS en el catálogo (cada keyword
    cita su fuente: sección del belt o framing/config del kit).
  * PRIOR = co-ocurrencia de servers en los kits del catálogo
    (PRODUCT-V2-DESIGN: "el catálogo es el PRIOR del recomendador").
    Con n=1 usuario, el prior es CURADO, no aprendido — y se dice así.
  * Las piezas gateadas rankean con su FRICCIÓN VISIBLE (penalidad chica,
    declarada en la razón: solo reordena empates, no esconde piezas).
  * Kits code-exec T02/T04/T08: NO DISPONIBLES por decisión vinculante 0014
    (sandbox actual = blocklist estática derrotable; sin confinamiento OS-level).
    Se muestran aparte, sin rankear, y NO propagan prior.
  * Si nada supera el umbral, la respuesta es honesta: "el catálogo no cubre
    esta intención" + lista de términos sin cobertura. NUNCA inventa piezas.

Uso:
    python3 recommend.py "quiero analizar filings de empresas"
    python3 recommend.py --json "..."          # salida JSON
    python3 recommend.py --top N "..."         # default 5
"""

import json
import sys
import unicodedata

# ---------------------------------------------------------------------------
# Parámetros del scoring (declarados, no mágicos)
# ---------------------------------------------------------------------------
W_PRIOR_KIT = 0.25      # kit hereda 25% del match directo de sus servers
W_PRIOR_SERVER = 0.25   # server hereda 25% del match directo de los kits que lo usan
W_COOC = 0.10           # server hereda 10% del match de servers con los que co-ocurre, por kit compartido
MIN_SCORE = 0.5         # piso de evidencia (directo+prior) para entrar al ranking
FRICTION_PENALTY = {    # solo reordena empates; visible en la razón
    "ninguna": 0.0,
    "infra-propia": 0.05,
    "key-gratis": 0.15,
    "cuenta-google": 0.30,
    "licencia": 0.40,
}
FRICTION_LABEL = {
    "ninguna": "ninguna (cero credenciales)",
    "infra-propia": "infra propia Puppet (Jupyter + JUPYTER_TOKEN, sin cuenta de tercero)",
    "key-gratis-av": "necesita key gratis Alpha Vantage (ALPHA_VANTAGE_API_KEY, ~1 min)",
    "key-gratis-fred": "necesita key gratis FRED (FRED_API_KEY, ~1 min)",
    "cuenta-google": "necesita conexión Google (service account / OAuth Google Cloud — decisión pendiente persona usuaria)",
    "licencia": "necesita licencia Stata 17+ del usuario (degradación disponible: Jupyter+statsmodels)",
}

STOPWORDS = {
    "quiero", "que", "me", "mi", "mis", "con", "de", "del", "en", "la", "el",
    "los", "las", "un", "una", "unos", "unas", "y", "o", "u", "a", "al", "por",
    "para", "sobre", "como", "necesito", "ayude", "ayuda", "ayudar", "hacer",
    "armar", "crear", "generar", "tener", "poder", "usar", "ser", "este",
    "esta", "estos", "estas", "se", "lo", "le", "es", "mas", "muy", "algo",
}


def norm(s):
    """minúsculas + sin acentos."""
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def variants(tok):
    """des-pluralización mínima en español por conjunto de variantes
    (reportes→{reportes,reporte,report}, acciones→{...,accion}): dos palabras
    matchean si sus conjuntos se intersecan."""
    v = {tok}
    if len(tok) > 3 and tok.endswith("s"):
        v.add(tok[:-1])
    if len(tok) > 4 and tok.endswith("es"):
        v.add(tok[:-2])
    return v


# ---------------------------------------------------------------------------
# CATÁLOGO — piezas reales. Cada keyword cita su fuente en el catálogo.
# Servers: catalog/belts/finanzas.md (§ indicado). Kits: config.json + framing.
# ---------------------------------------------------------------------------
SERVERS = {
    "excel-mcp-server": {
        "nombre": "Excel local (excel-mcp-server)",
        "fuente": "catalog/belts/finanzas.md §1 (test real ✓)",
        "friccion": ("ninguna", FRICTION_LABEL["ninguna"]),
        "code_exec": False,
        "keywords": {
            "excel": 3.0, "xlsx": 3.0, "planilla": 2.5, "hoja de calculo": 2.5,
            "formula": 2.0, "sumifs": 2.5, "workbook": 2.0, "libro": 1.0,
        },
    },
    "mcp-google-sheets": {
        "nombre": "Google Sheets (mcp-google-sheets)",
        "fuente": "catalog/belts/finanzas.md §2 (solo-spec: gate al arranque)",
        "friccion": ("cuenta-google", FRICTION_LABEL["cuenta-google"]),
        "code_exec": False,
        "keywords": {
            "sheets": 3.0, "google": 2.5, "spreadsheet": 2.5,
            "colaborativo": 2.0, "compartir": 2.0, "hoja compartida": 2.5,
        },
    },
    "mcp-stata": {
        "nombre": "Econometría Stata (mcp-stata)",
        "fuente": "catalog/belts/finanzas.md §3 (solo-spec: gate de licencia)",
        "friccion": ("licencia", FRICTION_LABEL["licencia"]),
        "code_exec": True,  # ejecuta código Stata — nota 0014 aplica a sus kits
        "keywords": {
            "stata": 3.0, "econometria": 3.0, "regresion": 2.5, "panel": 2.5,
            "efectos fijos": 2.5,
        },
    },
    "marketdata-mcp": {
        "nombre": "Datos de mercado Alpha Vantage (marketdata-mcp)",
        "fuente": "catalog/belts/finanzas.md §4 (test real ✓ init+tools/list)",
        "friccion": ("key-gratis", FRICTION_LABEL["key-gratis-av"]),
        "code_exec": False,
        "keywords": {
            "mercado": 2.5, "precio": 2.5, "cotizacion": 2.5, "accion": 2.0,
            "bolsa": 2.0, "ticker": 1.5, "tecnico": 1.5, "rsi": 2.0,
            "macd": 2.0, "divisa": 1.5,
        },
    },
    "sec-edgar-mcp": {
        "nombre": "Fundamentals SEC EDGAR (sec-edgar-mcp)",
        "fuente": "catalog/belts/finanzas.md §5 (test real ✓ end-to-end)",
        "friccion": ("ninguna", FRICTION_LABEL["ninguna"]),
        "code_exec": False,
        "keywords": {
            "filing": 3.0, "sec": 3.0, "edgar": 3.0, "10-k": 3.0, "10k": 3.0,
            "fundamental": 2.5, "estados financieros": 2.5, "balance": 2.0,
            "insider": 2.0, "empresa": 1.5,
        },
    },
    "fred-mcp-server": {
        "nombre": "Macro FRED (fred-mcp-server)",
        "fuente": "catalog/belts/finanzas.md §6 (test real ✓ init+tools/list)",
        "friccion": ("key-gratis", FRICTION_LABEL["key-gratis-fred"]),
        "code_exec": False,
        "keywords": {
            "macro": 3.0, "fred": 3.0, "inflacion": 2.5, "cpi": 2.5,
            "desempleo": 2.5, "tasa": 2.0, "serie economica": 2.5,
            "economia": 2.0, "pib": 2.0,
        },
    },
    "jupyter-mcp-server": {
        "nombre": "Data science Jupyter (jupyter-mcp-server)",
        "fuente": "catalog/belts/finanzas.md §7 (test real ✓ ejecución en kernel)",
        "friccion": ("infra-propia", FRICTION_LABEL["infra-propia"]),
        "code_exec": True,  # ejecuta código — nota 0014 aplica a sus kits
        "keywords": {
            "notebook": 3.0, "jupyter": 3.0, "python": 2.5,
            "data science": 2.5, "analisis de datos": 2.0, "reproducible": 1.5,
        },
    },
}

KITS = {
    "t01-cierre-mensual": {
        "nombre": "T01 — Cierre mensual que se reconcilia solo",
        "fuente": "catalog/templates/finanzas/t01-cierre-mensual/",
        "servers": ["excel-mcp-server"],
        "disponible": True,
        "keywords": {
            "cierre": 3.0, "mensual": 1.5, "contabilidad": 2.5, "contable": 2.5,
            "estado de resultados": 3.0, "niif": 2.5, "transaccion": 2.0,
            "gasto": 2.0, "finanzas personales": 2.0, "excel": 1.5,
        },
    },
    "t02-regresion-panel-stata": {
        "nombre": "T02 — Regresión de panel lista para el paper",
        "fuente": "catalog/templates/finanzas/t02-regresion-panel-stata/",
        "servers": ["mcp-stata"],
        "disponible": False,  # code-exec — vinculante 0014
        "keywords": {
            "regresion": 3.0, "panel": 2.5, "stata": 3.0, "econometria": 3.0,
            "efectos fijos": 2.5, "paper": 2.0,
        },
    },
    "t03-tabla-comparables": {
        "nombre": "T03 — Tabla de comparables con cita al filing",
        "fuente": "catalog/templates/finanzas/t03-tabla-comparables/",
        "servers": ["sec-edgar-mcp", "excel-mcp-server"],
        "disponible": True,
        "keywords": {
            "comparable": 3.0, "valuacion": 3.0, "multiplo": 2.5,
            "ebitda": 2.5, "filing": 1.5, "empresa": 1.5,
        },
    },
    "t04-brief-macro-fred": {
        "nombre": "T04 — Brief macro que no confunde MoM con YoY",
        "fuente": "catalog/templates/finanzas/t04-brief-macro-fred/",
        "servers": ["fred-mcp-server", "jupyter-mcp-server"],
        "disponible": False,  # code-exec (Jupyter) — vinculante 0014
        "keywords": {
            "macro": 2.5, "brief": 2.0, "inflacion": 2.0, "fred": 2.5,
            "notebook": 1.5,
        },
    },
    "t05-varianza-fp-a": {
        "nombre": "T05 — Varianza budget-vs-actual legible de un vistazo",
        "fuente": "catalog/templates/finanzas/t05-varianza-fp-a/",
        "servers": ["mcp-google-sheets"],
        "disponible": True,  # desbloqueado por review 0014 (camino money-touching verificado)
        "keywords": {
            "varianza": 3.0, "budget": 2.5, "presupuesto": 2.5, "fp&a": 3.0,
            "fpa": 3.0, "actual": 1.5, "sheets": 1.5,
        },
    },
    "t06-monitor-mercado": {
        "nombre": "T06 — Monitor de mercado que avisa cuando algo se mueve",
        "fuente": "catalog/templates/finanzas/t06-monitor-mercado/",
        "servers": ["marketdata-mcp", "excel-mcp-server"],
        "disponible": True,
        "keywords": {
            "mercado": 3.0, "monitor": 3.0, "reporte": 2.0, "accion": 2.0,
            "alerta": 2.0, "rsi": 2.0, "tecnico": 2.0, "seguimiento": 2.0,
        },
    },
    "t07-screener-fundamentals": {
        "nombre": "T07 — Screener de fundamentals que no alucina números",
        "fuente": "catalog/templates/finanzas/t07-screener-fundamentals/",
        "servers": ["sec-edgar-mcp", "excel-mcp-server"],
        "disponible": True,
        "keywords": {
            "screener": 3.0, "screening": 3.0, "filtrar empresa": 2.5,
            "fundamental": 2.5, "buy-side": 2.0, "empresa": 1.5,
        },
    },
    "t08-notebook-backtesting": {
        "nombre": "T08 — Backtest de estrategia que corre y muestra los números",
        "fuente": "catalog/templates/finanzas/t08-notebook-backtesting/",
        "servers": ["marketdata-mcp", "jupyter-mcp-server"],
        "disponible": False,  # code-exec (Jupyter) — vinculante 0014
        "keywords": {
            "backtest": 3.0, "backtesting": 3.0, "estrategia": 2.5,
            "trading": 2.5, "tradear": 2.5, "sharpe": 2.0, "quant": 2.0,
        },
    },
    "t09-resumen-filing-edgar": {
        "nombre": "T09 — Resumen del 10-K sin leer 200 páginas",
        "fuente": "catalog/templates/finanzas/t09-resumen-filing-edgar/",
        "servers": ["sec-edgar-mcp"],
        "disponible": True,
        "keywords": {
            "filing": 3.0, "10-k": 3.0, "10k": 3.0, "resumen": 2.5,
            "sec": 2.5, "edgar": 2.5, "analizar": 1.0, "empresa": 1.5,
            "equity research": 2.0,
        },
    },
    "t10-dashboard-macro": {
        "nombre": "T10 — Tablero macro en Excel que se actualiza con un comando",
        "fuente": "catalog/templates/finanzas/t10-dashboard-macro/",
        "servers": ["fred-mcp-server", "excel-mcp-server"],
        "disponible": True,
        "keywords": {
            "dashboard": 3.0, "tablero": 3.0, "macro": 2.5, "indicador": 2.0,
            "excel": 1.5, "serie": 1.5,
        },
    },
}

BLOCK_0014 = ("NO DISPONIBLE — vinculante 0014: kit code-exec; el sandbox actual "
              "(blocklist estática) no alcanza confinamiento OS-level. No rankea ni propaga prior.")


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------
def match_keywords(intent_norm, tokens, keywords):
    """Devuelve [(keyword, peso)] que matchean. Multi-palabra: substring sobre la
    intención normalizada. Una palabra: igualdad de token con stem mínimo."""
    hits = []
    tokvars = set()
    for t in tokens:
        tokvars |= variants(t)
    for kw, w in keywords.items():
        kwn = norm(kw)
        if " " in kwn:
            if kwn in intent_norm:
                hits.append((kw, w))
        else:
            if variants(kwn) & tokvars:
                hits.append((kw, w))
    return hits


def recommend(intent, top_n=5):
    intent_norm = norm(intent)
    raw_tokens = [t for t in "".join(c if c.isalnum() or c in "-&" else " "
                                     for c in intent_norm).split() if t]
    tokens = [t for t in raw_tokens if t not in STOPWORDS]

    # 1) match directo por pieza
    direct = {}     # pid -> score directo
    evidence = {}   # pid -> [(kw, w)]
    covered = set()
    for pid, piece in list(SERVERS.items()) + list(KITS.items()):
        hits = match_keywords(intent_norm, tokens, piece["keywords"])
        direct[pid] = sum(w for _, w in hits)
        evidence[pid] = hits
        for kw, _ in hits:
            for part in norm(kw).split():
                covered |= variants(part)
    uncovered = sorted({t for t in tokens if not (variants(t) & covered)})

    avail_kits = {k: v for k, v in KITS.items() if v["disponible"]}

    # 2) prior de co-ocurrencia (solo kits DISPONIBLES propagan)
    results = []
    for kid, kit in avail_kits.items():
        prior = W_PRIOR_KIT * sum(direct[s] for s in kit["servers"])
        prior_why = [SERVERS[s]["nombre"].split(" (")[0]
                     for s in kit["servers"] if direct[s] > 0]
        results.append(_mk_result(kid, "kit", kit, direct[kid], prior,
                                  evidence[kid], prior_why, kit_prior_kits=[]))

    for sid, srv in SERVERS.items():
        kits_with = [k for k, v in avail_kits.items() if sid in v["servers"]]
        prior = W_PRIOR_SERVER * sum(direct[k] for k in kits_with)
        prior_kits = [k for k in kits_with if direct[k] > 0]
        # co-ocurrencia server↔server vía kits compartidos
        cooc = 0.0
        cooc_why = []
        for oid in SERVERS:
            if oid == sid:
                continue
            shared = [k for k in kits_with if oid in avail_kits[k]["servers"]]
            if shared and direct[oid] > 0:
                cooc += W_COOC * direct[oid] * len(shared)
                cooc_why.append("co-ocurre con %s en %d kit(s): %s"
                                % (oid, len(shared), ", ".join(shared)))
        results.append(_mk_result(sid, "server", srv, direct[sid],
                                  prior + cooc, evidence[sid],
                                  [], kit_prior_kits=prior_kits,
                                  cooc_why=cooc_why))

    ranked = [r for r in results if r["evidencia_total"] >= MIN_SCORE]
    ranked.sort(key=lambda r: (-r["score"], -r["directo"],
                               r["penalidad_friccion"], r["id"]))
    ranked = ranked[:top_n]

    # 3) kits bloqueados que SÍ matchearon — se muestran, no rankean
    blocked = []
    for kid, kit in KITS.items():
        if not kit["disponible"] and direct[kid] > 0:
            blocked.append({
                "id": kid, "tipo": "kit", "nombre": kit["nombre"],
                "match_directo": round(direct[kid], 2),
                "matcheo": [kw for kw, _ in evidence[kid]],
                "estado": BLOCK_0014,
                "fuente": kit["fuente"],
            })

    return {
        "intencion": intent,
        "metodo": ("v0 determinístico SIN LLM: keywords declaradas del catálogo "
                   "+ prior de co-ocurrencia en kits (catálogo = prior, curado no aprendido)"),
        "terminos_analizados": tokens,
        "terminos_sin_cobertura": uncovered,
        "ranking": ranked,
        "no_disponibles_0014": blocked,
    }


def _mk_result(pid, tipo, piece, d, prior, hits, prior_servers,
               kit_prior_kits=None, cooc_why=None):
    if tipo == "kit":
        fclass = max((SERVERS[s]["friccion"][0] for s in piece["servers"]),
                     key=lambda c: FRICTION_PENALTY[c])
        flabel = "; ".join(sorted({SERVERS[s]["friccion"][1]
                                   for s in piece["servers"]
                                   if s != "excel-mcp-server" or len(piece["servers"]) == 1}))
        flabel = flabel or FRICTION_LABEL["ninguna"]
    else:
        fclass, flabel = piece["friccion"]
    pen = FRICTION_PENALTY[fclass]
    total = d + prior
    score = total - pen if total >= MIN_SCORE else total

    why = []
    if hits:
        why.append("matcheó " + ", ".join("'%s' (%.1f)" % (k, w) for k, w in hits))
    if tipo == "kit" and prior > 0 and prior_servers:
        why.append("prior: usa server(s) que matchearon directo: "
                   + ", ".join(prior_servers) + " (+%.2f)" % prior)
    if tipo == "server" and kit_prior_kits:
        why.append("prior: aparece en kit(s) que matchearon: "
                   + ", ".join(kit_prior_kits))
    if cooc_why:
        why.extend(cooc_why)
    if pen > 0:
        why.append("fricción visible: %s (−%.2f)" % (flabel, pen))
    elif tipo == "server" or fclass == "ninguna":
        why.append("fricción: " + flabel)
    if tipo == "server" and piece.get("code_exec"):
        why.append("NOTA: server de ejecución de código — sus kits están "
                   "bloqueados por vinculante 0014; uso directo requiere sandbox")

    return {
        "id": pid, "tipo": tipo, "nombre": piece["nombre"],
        "score": round(score, 2), "directo": round(d, 2),
        "prior": round(prior, 2), "penalidad_friccion": pen,
        "evidencia_total": round(total, 2),
        "friccion": flabel,
        "razon": "; ".join(why) if why else "sin evidencia",
        "fuente": piece["fuente"],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def render_text(out):
    L = []
    L.append("=" * 78)
    L.append("GUÍA v0 — RECOMENDADOR (nicho finanzas) — %s" % out["metodo"])
    L.append("INTENCIÓN: %s" % out["intencion"])
    L.append("términos analizados: %s" % (", ".join(out["terminos_analizados"]) or "—"))
    if out["terminos_sin_cobertura"]:
        L.append("términos SIN cobertura en el catálogo: %s  ← honesto: el catálogo "
                 "finanzas v0 no declara capacidades para esto"
                 % ", ".join(out["terminos_sin_cobertura"]))
    L.append("-" * 78)
    if out["ranking"]:
        L.append("RANKING (score = match directo + prior co-ocurrencia − fricción):")
        for i, r in enumerate(out["ranking"], 1):
            L.append("%2d. [%s] %s — score %.2f (directo %.2f + prior %.2f − fricción %.2f)"
                     % (i, r["tipo"], r["nombre"], r["score"], r["directo"],
                        r["prior"], r["penalidad_friccion"]))
            L.append("      porqué: %s" % r["razon"])
            L.append("      fuente: %s" % r["fuente"])
    else:
        L.append("SIN RECOMENDACIÓN: ninguna pieza del catálogo supera el umbral de "
                 "evidencia (%.2f)." % MIN_SCORE)
        L.append("El recomendador NO inventa piezas. El catálogo finanzas v0 no cubre "
                 "esta intención; queda registrada como señal para el flywheel.")
    if out["no_disponibles_0014"]:
        L.append("-" * 78)
        L.append("PIEZAS QUE MATCHEARON PERO NO ESTÁN DISPONIBLES (vinculante 0014):")
        for b in out["no_disponibles_0014"]:
            L.append("  · [kit] %s — match %.2f (%s)"
                     % (b["nombre"], b["match_directo"], ", ".join(b["matcheo"])))
            L.append("      %s" % b["estado"])
    L.append("=" * 78)
    return "\n".join(L)


def main(argv):
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    top_n = 5
    if "--top" in argv:
        i = argv.index("--top")
        top_n = int(argv[i + 1])
        del argv[i:i + 2]
    if not argv:
        print(__doc__)
        return 1
    out = recommend(" ".join(argv), top_n=top_n)
    print(json.dumps(out, ensure_ascii=False, indent=2) if as_json
          else render_text(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
