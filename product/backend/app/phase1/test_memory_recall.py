"""ORDEN 3 · Unit del recall relevante (puro, sin DB/red).
Correr: cd product/backend && ./.venv/bin/python -m pytest app/phase1/test_memory_recall.py -q
    o:  ./.venv/bin/python app/phase1/test_memory_recall.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from app.phase1.memory_recall import (select_relevant_memories, _salient_tokens, _relevance,
                                       _kind_of, EPISODIC_TOPK,
                                       cite_run_ids, annotate_cite_verification)

_fail = []
def ok(c, label):
    print(("  ✓ " if c else "  ✗ ") + label)
    if not c: _fail.append(label)

def M(content, kind=None, source="agent"):
    return {"content": content, "source": source, "meta": ({"kind": kind} if kind else {})}

def contents(sel):
    return [m["content"] for m in sel]

print("== tokenización y relevancia ==")
ok(_salient_tokens("El deadline de Nordvik es agosto") == {"deadline", "nordvik", "agosto"},
   "stopwords fuera, salientes dentro (es/de/el)")
ok(_salient_tokens(None) == set() and _salient_tokens(123) == set(), "no-str → set vacío")
ok(_relevance({"nordvik", "deadline"}, "el proyecto Nordvik vence pronto") == 1, "overlap = 1 (nordvik)")
ok(_relevance(set(), "cualquier cosa") == 0, "pedido sin tokens → score 0")
ok(_kind_of(M("x", "skill")) == "skill" and _kind_of(M("x")) == "episodica"
   and _kind_of(M("x", "ZZZ")) == "episodica", "kind fail-safe a episodica")

print("== AGENTE · skill SIEMPRE + episódica relevante · IRRELEVANTES (score 0) descartadas ==")
mems = [
    M("Prefiere respuestas en español con voseo", "skill"),         # 0 skill (siempre)
    M("Deadline del proyecto Nordvik: 30 de agosto", "episodica"),  # 1 relevante a 'Nordvik'
    M("Cliente Zephyr tiene oficina en Lima", "episodica"),         # 2 irrelevante (score 0)
    M("El servidor de pruebas es 10.0.0.5", "episodica"),           # 3 irrelevante (score 0)
]
sel = select_relevant_memories(mems, "¿cuál es el deadline de Nordvik?", k=EPISODIC_TOPK)
c = contents(sel)
ok("Prefiere respuestas en español con voseo" in c, "skill entra aunque NO matchee el pedido")
ok("Nordvik" in " ".join(c), "la episódica RELEVANTE (Nordvik) entra")
ok("Zephyr" not in " ".join(c) and "10.0.0.5" not in " ".join(c),
   "las episódicas IRRELEVANTES se DESCARTAN aunque k(8) > nº de episódicas (no es sólo cap por count)")
ok(len(c) == 2, "resultado = 1 skill + 1 episódica relevante")

print("== top-k acota cuando SOBRAN relevantes ==")
# CONTRATO NUEVO (ticket 26): el dedup grosero colapsa near-duplicados por overlap de tokens
# SALIENTES; por eso las 12 episódicas se hacen DISTINTAS (cada una con su propio término), si no
# el dedup las fusionaría (12 "informe Nordvik parte N" con el número <3chars filtrado = token-
# idénticas → 1). Con contenido distinto, el dedup las respeta y el top-k por k sigue acotando.
_temas = ["ventas", "costos", "riesgos", "cronograma", "personal", "logistica",
          "presupuesto", "calidad", "seguridad", "compras", "auditoria", "cierre"]
many = [M("skill x", "skill")] + [M(f"informe Nordvik seccion {t}", "episodica") for t in _temas]
selk = select_relevant_memories(many, "informe Nordvik", k=3)
ok(sum(1 for x in contents(selk) if "Nordvik" in x) == 3, "de 12 relevantes DISTINTAS, top-3 por k")
ok(any("skill" in x for x in contents(selk)), "skill no cuenta contra k")

print("== sin kind → episódica (fail-safe) y sujeta al filtro de relevancia ==")
mems2 = [M("dato de Marte", None), M("dato de Venus", None), M("dato de Marte otra vez", None)]
sel2 = select_relevant_memories(mems2, "contame de Marte", k=EPISODIC_TOPK)
ok(all("Marte" in x for x in contents(sel2)) and len(sel2) == 2, "sin-kind: matchean Marte, Venus fuera")

print("== pedido vacío / sin overlap → 0 episódicas (solo skill) para el AGENTE ==")
sel0 = select_relevant_memories(mems, "", k=EPISODIC_TOPK)
ok(contents(sel0) == ["Prefiere respuestas en español con voseo"],
   "pedido vacío → ninguna episódica matchea → sólo skill (no volcado por recencia)")

print("== captura EXPLÍCITA (source='user') SIEMPRE viaja (no se cae por relevancia) ==")
memu = [
    M("Prefiere voseo", "skill"),                                   # skill always
    M("Soy alérgico al maní", None, source="user"),                # captura explícita, irrelevante al pedido
    M("El cliente Zephyr está en Lima", "episodica"),              # episódica irrelevante → cae
]
selu = select_relevant_memories(memu, "recomendame un restaurante", k=EPISODIC_TOPK)
cu = " ".join(contents(selu))
ok("maní" in cu, "la captura explícita 'source=user' entra AUNQUE no matchee el pedido (promesa 'lo guardé')")
ok("Prefiere voseo" in cu, "skill sigue entrando")
ok("Zephyr" not in cu, "la episódica destilada irrelevante SÍ se cae")

print("== CUENTA · config REAL del executor (always_sources=(), drop_irrelevant=False): todo, reordenado ==")
# los hechos de cuenta son source='user'; el executor pasa always_sources=() para que se ORDENEN por
# relevancia (no que salten al frente por ser 'user') — así el byte-budget conserva lo tópico.
acct = [M("El usuario habla español", source="user"), M("Trabaja en logística", source="user"),
        M("Prefiere reportes cortos", source="user")]
sela = select_relevant_memories(acct, "resumen de logística", k=None, always_kinds=(),
                                always_sources=(), order="relevance", drop_irrelevant=False)
ok(len(sela) == 3, "cuenta: NADA se dropea (identidad no se cae por no matchear léxicamente)")
ok(contents(sela)[0] == "Trabaja en logística", "la más relevante primero (para truncado por budget)")
# y con pedido sin overlap alguno, cuenta sigue completa
selae = select_relevant_memories(acct, "xyz123 nada", k=None, always_kinds=(),
                                 always_sources=(), order="relevance", drop_irrelevant=False)
ok(len(selae) == 3, "cuenta con pedido sin overlap → igual entran las 3 (no lossy)")

print("== order='recency' FRONT-LOADEA los always (pericia DE DOMINIO/user) antes de la episódica ==")
# _build_pinned_memory trunca por orden de lista contra ~4096B; los always deben ir PRIMERO o una
# pericia vieja se cae por budget en favor de una episódica nueva. CONTRATO NUEVO (ticket 26): una
# pericia DE DOMINIO (un procedimiento del oficio) sí va primero; una PREFERENCIA de estilo NO es
# pericia de dominio — se DEMOTE al final (ver bloque siguiente). Acá el skill es de dominio.
memf = [
    M("Deadline Nordvik 30 ago", "episodica"),           # 0 episódica relevante (la más nueva)
    M("Otro dato de Nordvik", "episodica"),               # 1 episódica relevante
    M("Protocolo: revisar el torque cada 15 dias", "skill"),  # 2 pericia de DOMINIO (vieja) → PRIMERO
]
selrec = select_relevant_memories(memf, "Nordvik", k=EPISODIC_TOPK, order="recency")
ok(contents(selrec)[0].startswith("Protocolo"),
   "la PERICIA DE DOMINIO va PRIMERO aunque sea la más VIEJA (protección del byte-budget)")
ok(all("Nordvik" in c for c in contents(selrec)[1:]) and len(selrec) == 3,
   "luego la episódica relevante, en orden de recencia")

print("== ticket 26 · una PREFERENCIA de estilo (meta) se DEMOTE, no ahoga el hecho de dominio ==")
# El bug del Caso 3: el distiller marca preferencias/meta-observaciones como kind='skill' y, por
# "skill siempre viaja", front-loadeaban el budget expulsando los hechos. Ahora una meta (≥2
# marcadores: 'prefiere'+'voseo') va DESPUÉS de la episódica de dominio relevante.
memp = [
    M("El grillete GY-24-004 quedo en cuarentena", "episodica"),  # 0 hecho de dominio relevante
    M("Prefiere respuestas con voseo rioplatense", "skill"),       # 1 preferencia (meta) mal-marcada skill
]
selp = select_relevant_memories(memp, "grillete cuarentena", k=EPISODIC_TOPK, order="recency")
ok(contents(selp)[0].startswith("El grillete"),
   "el HECHO DE DOMINIO relevante va antes que la preferencia meta (no la ahoga)")
ok(any("voseo" in c for c in contents(selp)),
   "la preferencia NO se dropea — sólo se demote al final del budget")

print("== ticket 26 · VERIFICACIÓN DE LA CITA AL LEER (Copilot, puro) ==")
def MC(content, run_id=None, extra=None):
    meta = dict(extra or {})
    if run_id is not None:
        meta["cite"] = {"run_id": run_id, "from": "pedido de origen"}
    return {"content": content, "source": "agent", "meta": meta}

_mems = [MC("hecho real", "RUN-A"), MC("hecho colgado", "RUN-GHOST"),
         MC("sin cita"), MC("heredada", None, {"inherited": True, "origin_puppet": "abc123"})]
ok(cite_run_ids(_mems) == {"RUN-A", "RUN-GHOST"}, "cite_run_ids junta sólo los run_id citados (dedup, sin None)")
annotate_cite_verification(_mems, {"RUN-A"})   # sólo RUN-A existe
ok(_mems[0]["meta"]["cite"]["verified"] is True, "cita con run existente → verified=True")
ok(_mems[1]["meta"]["cite"]["verified"] is False, "cita con run inexistente → verified=False (colgada)")
ok("cite" not in _mems[2]["meta"], "memoria SIN cita → no se inventa una")
ok("verified" not in (_mems[3]["meta"].get("cite") or {}), "heredada sin run propio → no marca verified")
ok(annotate_cite_verification([], set()) == [] and cite_run_ids(None) == set(), "bordes: vacío/None fail-safe")

print("== bordes ==")
ok(select_relevant_memories([], "x", k=5) == [], "lista vacía → []")
ok(select_relevant_memories([M("a","skill")], "", k=0) == [M("a","skill")], "k=0 no toca skill (always)")

print(f"\n{'ALL GREEN' if not _fail else 'FAILS: ' + str(_fail)}  ({len(_fail)} fallos) · EPISODIC_TOPK={EPISODIC_TOPK}")
sys.exit(1 if _fail else 0)
