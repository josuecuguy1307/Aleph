"""ORDEN 3 · Recall RELEVANTE por run (READ-path) — selección pura, sin red ni BYOK.

El problema: hoy el recall vuelca TODAS las memorias pineadas al framing. No escala (500 entradas
en técnico ahogan la ventana y diluyen lo pertinente). Este módulo selecciona SÓLO lo que entra:

  • PERICIA (kind='skill'): SIEMPRE viaja — es lo del oficio, útil en cualquier sesión con el usuario.
  • EPISÓDICA (kind='episodica' o SIN kind → fail-safe episódica): top-k RELEVANTE al pedido actual
    por relevancia LÉXICA (overlap de tokens salientes). Lo no-pertinente NO entra.
  • MEMORIA DE CUENTA (Sistema 2): se ORDENA por relevancia (para que, si el byte-budget trunca,
    sobreviva lo pertinente) pero NO se dropea al escala actual — un hecho de IDENTIDAD del usuario
    ("habla español") no debe caerse por no matchear léxicamente un pedido de cálculo. La
    minimización LOSSY de cuenta (distinguir identidad-siempre de contextual) es refinamiento futuro
    (necesita un sub-tipo de hecho de cuenta); ver invariante #4 en aleph-memoria-diseno.md.

Determinista y $0 (léxico puro): la recuperación de memoria es FUNCIONAL en free, como A3/C1-self_hosted
(NO premium-gated). Embeddings quedan como mejora futura (reusar el path RAG con BYOK) — el léxico es
el piso confiable sin depender de una key.
"""
from __future__ import annotations
import re
from typing import Any, Optional

# k por defecto de episódica que entra al framing. La pericia (skill) NO se capa acá (viaja toda);
# el byte-budget de _build_pinned_memory es el techo duro final para ambos.
EPISODIC_TOPK = 8

# FIX ticket 26 · tope de "skills" que viajan por run. El distiller sobre-marca meta/redundante como
# kind='skill' (~120/día); sin tope, la marea ahoga el byte-budget y expulsa los hechos de dominio.
# Se conservan los top-N MÁS RELEVANTES al pedido (+ siempre la captura explícita del usuario, aparte).
_SKILL_CAP = 12

# Stopwords ES (voseo incluido) + EN: se descartan del scoring para que el overlap mida tokens
# SALIENTES (nombres, cifras, términos), no conectores. Lista corta a propósito (precisión sobre
# exhaustividad): un stopword de más sólo baja levemente una señal, no rompe la selección.
_STOPWORDS = frozenset("""
que como para por con los las una unos unas del este esta esto estos estas ese esa eso esos esas
aquel pero más muy sin sobre entre cuando donde quien cual cuales porque segun tras hacia hasta
desde ante bajo cabe contra durante mediante versus vos vas tenes queres podes hacelo dale
the and for with that this these those from into onto your you are was were will would have has
had not but out its our their them they then than what when where which who whom whose how why
about your yours mine ours also just very much more most some any all can could should
""".split())

_TOKEN_RE = re.compile(r"[0-9a-záéíóúñü]+")


def _salient_tokens(text: Any) -> set:
    """Tokens salientes (minúsculas, ≥3 chars, no-stopword) de un texto. Devuelve un SET (presencia,
    no frecuencia): una memoria no gana relevancia por repetir una palabra. Robusto a no-str."""
    if not isinstance(text, str) or not text:
        return set()
    return {t for t in _TOKEN_RE.findall(text.lower()) if len(t) >= 3 and t not in _STOPWORDS}


def _relevance(req_tokens: set, content: Any) -> int:
    """Score léxico = nº de tokens salientes COMPARTIDOS entre el pedido y el contenido. Simple,
    determinista, sin sesgo de longitud fuerte (set-overlap, no conteo). 0 = sin overlap."""
    if not req_tokens:
        return 0
    return len(req_tokens & _salient_tokens(content))


# ── FIX 26 (mem0) · SEÑAL DE ENTIDADES · el multi-señal sobre el ranking léxico ──────────────────
# El overlap léxico no distingue "el mínimo ES 6" (hecho con entidad) de "no tenés el mínimo" (meta):
# ambas comparten el token 'mínimo' y el hecho perdía por recencia/empate. Las ENTIDADES — seriales
# (GY-24-004, GYE-2024, M-047), números (6, 30), códigos — son la señal DURA de un hecho concreto.
# Dos boosts, aditivos sobre el score léxico (mejora, NO reemplaza el ranking del martes):
#   (a) ENTITY-MATCH: el pedido y la memoria comparten una entidad exacta → boost fuerte (el usuario
#       preguntó por "GY-24-004" y la memoria lo nombra: gana lejos).
#   (b) HARD-FACT: la memoria CONTIENE una entidad (número/serial) → es un hecho concreto, no una
#       meta-observación → bonus que la hace ganar SIEMPRE contra una meta en empate léxico.
_ENTITY_TOKEN_RE = re.compile(r"[a-záéíóúñü0-9]+(?:-[a-záéíóúñü0-9]+)*")
_ENTITY_MATCH_W = 4     # por entidad compartida pedido∩memoria (señal más fuerte)
_HARD_FACT_BONUS = 3    # la memoria trae ≥1 entidad concreta (supera el -2 de meta → hecho>meta siempre)


def _entities(text: Any) -> set:
    """Entidades DURAS de un texto: tokens que contienen un dígito (números, seriales, códigos:
    '6', '30', 'gy-24-004', 'gye-2024', 'm-047'). Set (presencia). Robusto a no-str."""
    if not isinstance(text, str) or not text:
        return set()
    out = set()
    for m in _ENTITY_TOKEN_RE.finditer(text.lower()):
        tok = m.group(0)
        if any(c.isdigit() for c in tok):
            out.add(tok)
    return out


def _entity_boost(req_entities: set, content: Any) -> int:
    """Boost multi-señal de una memoria vs el pedido: match exacto de entidades (fuerte) + presencia
    de entidad dura (hecho concreto). Aditivo sobre el score léxico. 0 si la memoria no trae entidad."""
    mem_ent = _entities(content)
    if not mem_ent:
        return 0
    b = _HARD_FACT_BONUS
    if req_entities:
        b += _ENTITY_MATCH_W * len(req_entities & mem_ent)
    return b


# ── FIX 26 (mem0/deep) · CAPA SEMÁNTICA OPT-IN · el refinamiento sobre el léxico+entidad ─────────
# El léxico no captura sinónimos/paráfrasis ("¿cuántos herrajes usables?" vs "quedan 5 grilletes").
# Cuando el dueño tiene key de embeddings (BYOK, la misma del RAG C1), sumamos coseno pedido↔memoria
# como señal. ADITIVO y OPT-IN: sin key / si el embed falla → sem_scores=None → el ranking cae al
# léxico+entidad (que YA funciona: Bitácora 4/4). Jamás bloquea ni rompe el recall.
_SEM_WEIGHT = 6.0   # coseno [0..1] escalado — señal fuerte, comparable al entity-match


def _cos(a: list, b: list) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    import math
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)); nb = math.sqrt(sum(y * y for y in b))
    return (dot / (na * nb)) if (na and nb) else 0.0


def compute_semantic_scores(request: Any, memories: list, *, embed_fn) -> Optional[dict]:
    """{idx: coseno(pedido, memoria)} usando `embed_fn(texts)->list[vec]` (embeddings BYOK del dueño).
    Devuelve None si no hay pedido, no hay memorias, o el embed falla/no-key → el caller cae al léxico.
    embed_fn es INYECTADO (testeable con mock; en prod = rag_index.embed_texts con la key BYOK)."""
    req = str(request or "").strip()
    if not req or not memories or embed_fn is None:
        return None
    try:
        texts = [req] + [str(m.get("content", "") or "") for m in memories]
        vecs = embed_fn(texts)
        if not vecs or len(vecs) != len(texts):
            return None
        q = vecs[0]
        return {i: max(0.0, _cos(q, vecs[i + 1])) for i in range(len(memories))}
    except Exception:
        return None


# ── FIX ACOTADO ticket 26 · HECHO-DE-DOMINIO vs META-OBSERVACIÓN ──────────────────────────────────
# El recall colapsaba a profundidad porque la marea de META-observaciones ("el usuario valora la
# honestidad", "prefiere español rioplatense", "no inventes datos") — capturadas ~5/turno — desplazaba
# los HECHOS DE DOMINIO (mínimo 6, GY-24-004 en cuarentena, la regla de Sofía) fuera del top-k por
# empate de score + recencia. Marcador léxico: una meta-observación habla de CÓMO comportarse / de las
# PREFERENCIAS del usuario, no de un hecho del mundo. Se DEGRADAN en el ranking (nunca se dropean: una
# preferencia sigue siendo útil, sólo pierde contra un hecho de dominio que matchea el pedido).
_META_MARKERS = frozenset("""
valora valorá prefiere preferís prefieres preferido preferencia preferencias estilo tono voseo
rioplatense honestidad honesto honesta honestas honestos inventes inventar inventás inventes fabricar
fabriques comunicación comunica escribe escribí redacta gusta agradece pide-que trato tuteo usted
directo directas comportamiento comportate actitud personalidad manera modo forma-de distinga distingas
distinguir explícitamente criterio opinión opinion juicio aclare aclarás matiz prefer prefers style
tone honesty honest communicate writes likes appreciates distinguish criterion opinion clarify
""".split())


def _is_meta(content: Any) -> bool:
    """¿La memoria es una META-observación del comportamiento/preferencia (vs un hecho de dominio)?
    Heurística léxica barata: contiene ≥2 marcadores meta. Umbral 2 para no marcar por casualidad un
    hecho de dominio que menciona 'honesto' de pasada."""
    toks = _salient_tokens(content)
    if not toks:
        return False
    return len(toks & _META_MARKERS) >= 2


def _meta_of(m: dict) -> bool:
    """¿La entrada es meta? Tag EXPLÍCITO kind='meta' (lo pone la consolidación) O la heurística de
    contenido. El tag persiste la decisión (auditable); la heurística cubre lo aún no consolidado."""
    if ((m.get("meta") or {}).get("kind")) == "meta":
        return True
    return _is_meta(m.get("content", ""))


# ── FIX ACOTADO ticket 26 · DEDUP GROSERO de near-duplicados (kind=None acumuladas) ───────────────
# 273 memorias/día incluían muchas casi-idénticas (el inventario destilado 3×, los códigos de status
# repetidos N veces). Dedup léxico al READ (no destructivo): dos memorias con solapamiento de tokens
# salientes ≥ umbral = duplicados; se conserva la MÁS RECIENTE (menor idx, la lista viene DESC). Achica
# el pool para que el top-k no se llene de variantes del mismo hecho.
def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    u = a | b
    return (len(a & b) / len(u)) if u else 0.0


def _dedup_keep_recent(cands: list, memories: list, *, thresh: float = 0.72) -> list:
    """cands = [(idx, score), …] ya ordenados por recencia posible. Colapsa near-duplicados por
    Jaccard de tokens salientes, conservando el de MENOR idx (más reciente). Estable y determinista."""
    kept: list = []
    kept_tok: list = []
    # recorrer de más-reciente (idx menor) a más-viejo para que el conservado sea el reciente
    for idx, score in sorted(cands, key=lambda it: it[0]):
        tk = _salient_tokens(memories[idx].get("content", ""))
        if any(_jaccard(tk, kt) >= thresh for kt in kept_tok):
            continue   # near-duplicado de uno ya conservado (más reciente) → se cae
        kept.append((idx, score)); kept_tok.append(tk)
    return kept


def _kind_of(m: dict) -> str:
    """kind de una entrada, fail-safe a 'episodica' (sin tag → no viaja sola → candidata a top-k)."""
    k = ((m.get("meta") or {}).get("kind") or "").strip().lower()
    return k if k in ("skill", "episodica") else "episodica"


def _is_confidential(m: dict) -> bool:
    """¿La entrada está marcada CONFIDENCIAL? Regla dura del MD: lo confidencial no cruza sesiones ni
    agentes y NO es mezclable — no aparece como pieza elegible en herencia ni composición. El marcador
    es `meta.confidential` (el hook estructural existe aunque hoy nada lo setee: quien lo marque —panel
    o destilador— hereda la barrera). Fail-safe: cualquier valor truthy excluye."""
    return bool((m.get("meta") or {}).get("confidential"))


def _project_of(m: dict) -> Optional[str]:
    """El 'proyecto' de una episódica = el run que la originó (meta.run_id). None si no lo lleva.
    Es la unidad que el selector de herencia ofrece como '+ proyecto X'."""
    rid = (m.get("meta") or {}).get("run_id")
    return str(rid) if rid else None


# ── TICKET 26 · VERIFICACIÓN DE LA CITA AL LEER (patrón Copilot) ────────────────────────────────
# La captura ya anota la fuente (meta.cite={run_id, from:excerpt}). Esto es la mitad de LECTURA:
# al surfacear una memoria (panel / recall), su cita no es texto guardado que podría ser stale o
# inventado — se VERIFICA que el run citado exista de verdad. Puro (recibe el set de runs que
# existen, calculado por repo.runs_exist en UNA query); el router lo cablea. Doble llave: el panel
# muestra ✓ (fuente auditable resuelve) o ⚠ (cita colgada), y un query prueba cite.verified.

def cite_run_ids(memories: list) -> set:
    """Los run_ids que citan las memorias (para verificarlos en batch). Set, sin duplicados."""
    out: set = set()
    for m in (memories or []):
        cite = (m.get("meta") or {}).get("cite")
        if isinstance(cite, dict) and cite.get("run_id"):
            out.add(str(cite["run_id"]))
    return out


def annotate_cite_verification(memories: list, existing_run_ids: set) -> list:
    """Marca `meta.cite.verified` = True/False según si el run citado existe. Muta in-place y
    devuelve la lista (encadenable). Sin cita → intacta (no inventa una). Una memoria HEREDADA
    puede no llevar cita de run propia; no se penaliza (verified sólo aplica si hay run_id)."""
    existing = existing_run_ids or set()
    for m in (memories or []):
        cite = (m.get("meta") or {}).get("cite")
        if not isinstance(cite, dict):
            continue
        rid = cite.get("run_id")
        if rid:
            cite["verified"] = str(rid) in existing
    return memories


def select_relevant_memories(memories: list, request: Any, *, k: Optional[int] = EPISODIC_TOPK,
                             always_kinds: tuple = ("skill",),
                             always_sources: tuple = ("user",),
                             order: str = "recency", drop_irrelevant: bool = True,
                             sem_scores: Optional[dict] = None) -> list:
    """Selecciona qué memorias entran al framing de ESTE run.

    - Entran SIEMPRE (sin filtro de relevancia): las de kind ∈ `always_kinds` (p.ej. 'skill') Y las
      de source ∈ `always_sources` (p.ej. 'user'). Esto último preserva la promesa de la captura
      EXPLÍCITA ("recordá esto", source='user', pinned) y de los writes del panel: lo que el usuario
      pidió recordar a propósito NO se cae por no matchear léxicamente el pedido actual.
    - Del resto (episódica destilada por el agente / sin-kind):
        · si `drop_irrelevant` (default, uso AGENTE): se descartan las de score 0 (SIN overlap léxico
          con el pedido — no son "relevantes al pedido"); de las que SÍ matchean, las top-k por score
          (empates → recencia). Esto es lo que evita el volcado: 200 episódicas de otros proyectos NO
          entran si no matchean el pedido actual.
        · si NO `drop_irrelevant` (uso CUENTA): se conservan TODAS (score 0 incluido) — un hecho de
          identidad no se cae por no matchear léxicamente; `order='relevance'` sólo las REORDENA para
          que, si el byte-budget trunca, sobreviva lo pertinente.
    - `k`: tope de episódicas que entran (None = sin tope). `order`: 'recency' (orden original,
      más-nuevo-primero, el que espera _build_pinned_memory) | 'relevance' (más-relevante-primero).

    Puro y determinista. `memories` se asume created_at DESC (como list_memories/list_account_memories).
    """
    if not memories:
        return []
    req = _salient_tokens(request)
    req_ent = _entities(request)   # FIX 26 (mem0) · entidades del pedido para el boost multi-señal
    always_idx: list = []       # user-source + skill "de dominio" (viajan siempre, front del budget)
    always_meta_idx: list = []  # FIX 26 · skills marcados que son META-observaciones → al FINAL
    cand: list = []             # (idx, score) episódica candidata
    for i, m in enumerate(memories):
        _is_always = _kind_of(m) in always_kinds or (m.get("source") in always_sources)
        if _is_always:
            # FIX ticket 26 · el distiller sobre-marca meta-observaciones como kind='skill' (129/302);
            # todas bypaseaban relevancia Y front-loadeaban el budget, expulsando los hechos de dominio.
            # Una captura EXPLÍCITA del usuario (source) NUNCA es meta (es su llave dura) → siempre front.
            if drop_irrelevant and (m.get("source") not in always_sources) and _meta_of(m):
                always_meta_idx.append(i)
            else:
                always_idx.append(i)
        else:
            score = _relevance(req, m.get("content", ""))
            # RESCATE SEMÁNTICO: una memoria SIN overlap léxico pero con alta similitud de embeddings
            # (paráfrasis/sinónimo) NO se descarta cuando hay señal semántica (opt-in BYOK). Umbral
            # 0.35 de coseno = claramente relacionada. Sin sem_scores → comportamiento léxico intacto.
            _sem_i = (float(sem_scores.get(i, 0.0)) if sem_scores else 0.0)
            if drop_irrelevant and score <= 0 and _sem_i < 0.35:
                continue   # ni léxico ni semántico → no relevante a ESTE run → no entra
            cand.append((i, score))
    # FIX ticket 26 · (b) DEDUP GROSERO de los pools (near-duplicados: inventario destilado 3×, códigos
    # de status repetidos N×) — sólo uso AGENTE; el path de CUENTA conserva todo tal cual.
    if drop_irrelevant:
        cand = _dedup_keep_recent(cand, memories)
        always_idx = [i for i, _ in _dedup_keep_recent([(i, 0) for i in always_idx], memories)]
        always_meta_idx = [i for i, _ in _dedup_keep_recent([(i, 0) for i in always_meta_idx], memories)]
        # FIX ticket 26 · el distiller genera ~120 "skills" → recencia sola entierra el skill RELEVANTE
        # al pedido bajo skills recientes irrelevantes (el budget corta por orden). Ordenar los skills
        # por RELEVANCIA al pedido (los que matchean primero) preserva "skill siempre viaja" PERO hace
        # que el budget conserve el skill pertinente. Empate → recencia (idx ASC). La captura del
        # usuario (source) mantiene su prioridad: se re-ancla al frente abajo.
        _user_first = {i for i in always_idx if memories[i].get("source") in always_sources}
        always_idx.sort(key=lambda i: (0 if i in _user_first else 1,
                                       -(_relevance(req, memories[i].get("content", ""))
                                         + _entity_boost(req_ent, memories[i].get("content", ""))), i))
        # FIX ticket 26 · CAP DE SKILLS: "skill siempre viaja" asumía POCOS skills; con el distiller
        # marcando ~120, todos juntos ahogan el budget de 4KB. Se conservan la captura del usuario
        # (siempre) + los top-_SKILL_CAP skills MÁS RELEVANTES al pedido (ya ordenados por relevancia
        # arriba). Un skill sin relación con ESTE pedido no viaja hoy (viajará cuando un pedido lo
        # matchee). Preserva "el skill pertinente siempre está"; corta la marea irrelevante que
        # expulsaba los hechos de dominio del byte-budget.
        _keep, _n_skill = [], 0
        for i in always_idx:
            if i in _user_first:
                _keep.append(i); continue
            if _n_skill < _SKILL_CAP:
                _keep.append(i); _n_skill += 1
        always_idx = _keep
    # FIX ticket 26 · (a) RANKING domain>meta dentro de la episódica también (por si un meta se coló sin
    # kind='skill'): score efectivo resta 2 a una meta. Empates → recencia (idx ASC).
    def _eff(it):
        idx, score = it
        c = memories[idx].get("content", "")
        # multi-señal (mem0): léxico + boost por entidad (hecho concreto/serial) − penalidad meta
        # + coseno semántico OPT-IN (BYOK; None → cae al léxico+entidad, que ya funciona).
        base = score + _entity_boost(req_ent, c) - (2 if _meta_of(memories[idx]) else 0)
        if sem_scores:
            base += _SEM_WEIGHT * float(sem_scores.get(idx, 0.0))
        return base
    cand.sort(key=lambda it: (-_eff(it), it[0]))
    picked = cand if k is None else cand[:max(0, int(k))]
    if order == "relevance":
        # always primero (prioridad máxima), luego candidatos por score DESC, y las META-skills AL FINAL
        # (el budget las corta primero — FIX 26). recencia desempata.
        ranked = [(i, float("inf")) for i in always_idx] + [(i, s) for i, s in picked]
        ranked.sort(key=lambda it: (-it[1], it[0]))
        return [memories[i] for i, _ in ranked] + [memories[i] for i in always_meta_idx]
    # 'recency': orden que espera _build_pinned_memory (trunca por ORDEN contra un byte-budget fijo ~4096B).
    # FIX ticket 26 · el ORDEN es lo que sobrevive el budget → hechos de DOMINIO primero:
    #   1) always_idx = captura explícita del usuario + skills DE DOMINIO (front absoluto)
    #   2) picked = episódica elegida (top-k relevante, meta ya penalizada)
    #   3) always_meta_idx = "skills" que son meta-observaciones del comportamiento → ÚLTIMO (el budget
    #      los descarta antes que a un hecho de dominio). Antes iban mezclados al frente y ahogaban todo.
    picked_idx = sorted(i for i, _ in picked)   # recencia (idx ASC)
    return [memories[i] for i in (always_idx + picked_idx + always_meta_idx)]


# ── ORDEN 4 · HERENCIA — qué memoria del AGENTE es ELEGIBLE al reusarlo en una sesión/composición
# nueva. Es la ELECCIÓN del usuario (selector [solo pericia] [+ proyecto X] [elegir entradas]), y
# corre ANTES de select_relevant_memories: acota el conjunto elegible; después el recall relevante
# elige dentro de ese conjunto lo pertinente al pedido. FRONTERA (precisión de persona usuaria): esto opera
# SÓLO sobre memoria de AGENTE (agent_memories). La memoria de CUENTA (Sistema 2) NO es heredable ni
# elegible acá — es otra tabla, otro read-path (framing del dueño, _depth==0), y jamás cruza usuarios;
# el selector de herencia no puede arrastrar un hecho de cuenta hacia un agente que luego se comparta.

def apply_inheritance(memories: list, policy: Any) -> list:
    """Acota el estante del AGENTE al conjunto ELEGIBLE según la herencia elegida. Puro, determinista.

    - `policy` None/ausente → SIN herencia: NO se acota (continuación del MISMO agente; el recall
      relevante decide). Distinto de reusar: el default 'sólo pericia' NO es de todo run — lo aplica
      el path de reuso/composición pasando una política EXPLÍCITA. (Igual se saca lo confidencial.)
    - `'skill_only'` (o `{'episodic': 'none'}`, o un dict SIN selección de episódica) → SÓLO
      kind='skill'. Éste es el default del selector al reusar: "pericia sí, episódica no".
    - `{'projects': [run_id, ...]}` → skill + episódica de esos proyectos (meta.run_id).
    - `{'entries': [mem_id, ...]}` → skill + esas entradas por id.
    - combinaciones → unión.

    INVARIANTE en TODA política: lo CONFIDENCIAL (meta.confidential) queda fuera — no es mezclable.
    La memoria de CUENTA nunca llega a esta función (se lee por su propio camino).
    """
    if not memories:
        return []
    if policy is None:
        # continuación normal: no acota, pero lo confidencial nunca viaja igual.
        return [m for m in memories if not _is_confidential(m)]

    only_skill = False
    projects: set = set()
    entries: set = set()
    if isinstance(policy, str):
        only_skill = policy.strip().lower() in (
            "skill_only", "skill", "solo_pericia", "pericia", "only_skill")
    elif isinstance(policy, dict):
        _ep = str(policy.get("episodic") or "").strip().lower()
        if _ep in ("none", "no", "ninguna") or policy.get("skill_only"):
            only_skill = True
        projects = {str(x) for x in (policy.get("projects") or []) if x}
        entries = {str(x) for x in (policy.get("entries") or []) if x}
        # herencia DECLARADA sin ninguna selección de episódica = 'sólo pericia' (default duro del MD).
        if not only_skill and not projects and not entries:
            only_skill = True
    else:
        # forma desconocida → fail-safe al más restrictivo: sólo pericia.
        only_skill = True

    out: list = []
    for m in memories:
        if _is_confidential(m):
            continue                      # nunca mezclable, ni la pericia si estuviera marcada
        # La captura EXPLÍCITA del usuario ("recordá esto" / el panel, source='user') viaja bajo
        # herencia COMO la pericia — jamás se cae por elegir 'solo pericia'. Espeja el invariante
        # always_sources=('user',) de select_relevant_memories: lo que el usuario guardó a propósito
        # es su llave dura (doble-llave), no "experiencia episódica auto-aprendida" que se pueda podar
        # por política. Sin esto, un 'skill_only' persistido en la receta borra el "recordá esto" de
        # TODO run del agente (apply_inheritance corre ANTES del recall, así que always_sources ya no
        # alcanza a rescatarlo). Lo distingue de source='agent' (destilado), que sí es podable.
        if str(m.get("source") or "").lower() == "user":
            out.append(m)
            continue
        if _kind_of(m) == "skill":
            out.append(m)                 # la PERICIA (destilada como skill) siempre viaja bajo herencia
            continue
        if only_skill:
            continue                      # episódica destilada excluida por 'solo pericia'
        pid = _project_of(m)
        mid = str(m.get("id") or "")
        if (pid and pid in projects) or (mid and mid in entries):
            out.append(m)                 # episódica elegida por proyecto o por entrada
    return out


def group_shelf(memories: list) -> dict:
    """El ESTANTE del agente agrupado para el SELECTOR de herencia/composición: pericia / proyectos
    (episódica por run_id) / sueltas (episódica sin proyecto). Excluye lo CONFIDENCIAL (no elegible).
    Puro — el endpoint sólo lo serializa. NO incluye jamás memoria de cuenta (recibe sólo A3)."""
    skill: list = []
    loose: list = []
    projects: dict = {}
    for m in memories:
        if _is_confidential(m):
            continue
        if _kind_of(m) == "skill":
            skill.append(m)
        else:
            pid = _project_of(m)
            if pid:
                projects.setdefault(pid, []).append(m)
            else:
                loose.append(m)
    return {"skill": skill, "projects": projects, "loose": loose}
