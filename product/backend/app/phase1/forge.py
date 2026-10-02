"""forge.py — LA FORJA (v1 · Fase 3).

De una INTENCIÓN en español (+ canvas actual) PROPONE un conjunto de piezas (átomos) del
catálogo REAL, cada una con su ZONA (lee=Fuentes · procesa=Mesa · saca/manda=Entrega),
marca qué necesita GATE (money/send) y qué necesita CONEXIÓN, y arma el recipe_patch
(belt_refs[] + tool_filters + keys) listo para componer.

Principios (plan):
  · PROPONE, NO commitea (decisión 5): el front muestra fantasmas; el usuario acepta/rechaza.
  · ANTI-TEATRO: SOLO propone ids del catálogo real (collect_atoms). Si el LLM alucina un id,
    se descarta; si no queda nada, cae al prior determinístico.
  · La FORJA asigna la zona (corrige defaults flojos del catálogo); el catálogo es solo pista.
  · El gate lo FUERZA el motor (recipe_enforcer §3.5); la forja lo SURFACEA (lo hace visible).

Su calidad se mide con el eval `catalog/evals/forge-tasks/` (gate de la Fase 3).
"""
from __future__ import annotations

import importlib.util as _ilu
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Optional

_REPO = Path(__file__).resolve().parents[4]
_GATES_DIR = _REPO / "platform" / "gates"
# Catálogo chico (~30 átomos): mandamos CASI todo al LLM (el prior solo ORDENA, no filtra).
# Un prior léxico débil no debe esconder la pieza correcta — el LLM elige con buenas descripciones.
_TOPK = 30

_STOP = {
    "que","de","la","el","los","las","un","una","unos","unas","y","o","u","a","al","del",
    "en","con","por","para","mi","mis","me","te","se","su","sus","lo","le","les","es","son",
    "quiero","necesito","hacer","haga","hace","cada","todo","todos","toda","sobre","como",
    "the","of","to","and","for","my","i","need","want","with","this","that",
}
_ZONES = ("fuentes", "mesa", "entrega")

_enf_mod = None
def _enf():
    global _enf_mod
    if _enf_mod is None:
        import aleph_paths
        _enf_mod = aleph_paths.load_module_by_path("puppet_enf_forge", _GATES_DIR / "recipe_enforcer.py")
    return _enf_mod


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return s.lower()


def _toks(s: str) -> set:
    return {t for t in re.split(r"[^a-z0-9]+", _norm(s)) if t and t not in _STOP and len(t) > 2}


def _atom_text(a: dict) -> str:
    return " ".join([a.get("label") or "", a.get("sub") or "", a.get("server") or "",
                     a.get("id") or "", " ".join(a.get("tools") or [])])


def _score(itoks: set, a: dict) -> float:
    atoks = _toks(_atom_text(a))
    if not atoks:
        return 0.0
    inter = itoks & atoks
    return len(inter) + 0.15 * len(inter & {t for t in itoks if len(t) > 5})


def _prior_rank(intent: str, atoms: list, k: int) -> list:
    itoks = _toks(intent)
    scored = [(a, _score(itoks, a)) for a in atoms]
    scored.sort(key=lambda x: x[1], reverse=True)
    top = [a for a, s in scored if s > 0][:k]
    # si el prior no matchea nada, mandamos una muestra diversa (1 por server) para que el LLM elija
    if not top:
        seen, top = set(), []
        for a in atoms:
            if a["server"] in seen:
                continue
            seen.add(a["server"]); top.append(a)
            if len(top) >= k:
                break
    return top


_SYS = (
    "Eres la FORJA de Aleph: armas el agente de una persona NO técnica eligiendo piezas de un "
    "catálogo. Te paso la intención y las piezas candidatas. Elige SOLO las piezas que el "
    "trabajo necesita (pocas y justas) y a cada una asígnale su ZONA según su rol:\n"
    "  fuentes = LEE del mundo (busca, consulta, descarga)\n"
    "  mesa    = PROCESA (calcula, transforma, redacta, analiza)\n"
    "  entrega = SACA al mundo (manda correo, escribe afuera, publica, exporta el resultado)\n"
    "Elige la pieza MÁS ESPECÍFICA al dominio del pedido: si hay una especializada, no uses una "
    "genérica (mira la descripción y las tools de cada pieza para decidir).\n"
    "Responde SOLO un JSON, sin nada más:\n"
    '{"blocks":[{"id":"<id del catálogo>","zone":"fuentes|mesa|entrega"}],'
    '"narration":"<1 línea en tu voz, máx 18 palabras, sin comillas>"}\n'
    "Los id DEBEN ser del catálogo (jamás inventes). Si nada sirve, devuelve blocks vacío."
)


def _llm_select(intent: str, cands: list, key: str) -> Optional[dict]:
    import urllib.request
    cat = "\n".join(
        f'- id="{a["id"]}" ({a.get("label")}): {a.get("sub") or a.get("server")}'
        f' · tools: {",".join((a.get("tools") or [])[:4])}'
        f'{" [necesita conexión]" if a.get("atom")=="conexion" else ""}'
        for a in cands
    )
    body = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "system", "content": _SYS},
                     {"role": "user", "content": f"Intención: {intent[:1200]}\n\nCatálogo:\n{cat}"}],
        "max_tokens": 380, "temperature": 0, "stream": False,
    }
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key,
                 "User-Agent": "puppet-forge/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            obj = json.loads(r.read().decode("utf-8", "replace"))
        txt = (obj.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
        i, j = txt.find("{"), txt.rfind("}")
        return json.loads(txt[i:j + 1]) if i != -1 and j != -1 else None
    except Exception:
        return None


def _block_from_atom(a: dict, zone: str) -> dict:
    return {
        "id": "blk-" + a["id"], "atom": a.get("atom", "tool"), "card_id": a["id"],
        "label": a.get("label") or a["server"], "ref": a["server"], "tools": a.get("tools") or [],
        "zone": zone if zone in _ZONES else a.get("zone", "mesa"),
        "belt_ref": a.get("belt_ref"), "connector": a.get("connector"), "auth": a.get("auth", "keyless"),
        "state": a.get("state"),
    }


def _is_gated(tools: list) -> bool:
    enf = _enf()
    try:
        return any(enf.suggests_send(t) or enf.suggests_money_touch(t) for t in (tools or []))
    except Exception:
        return False


def _assemble(blocks: list) -> dict:
    """blocks → recipe_patch (belt_refs/tool_filters/keys) + listas de gate/conexión surfaceadas."""
    belt_refs, tf, keys = [], {}, {}
    gates_surfaced, needs_connection = [], []
    for b in blocks:
        if b.get("belt_ref") and b["belt_ref"] not in belt_refs:
            belt_refs.append(b["belt_ref"])
        if b.get("ref"):
            tf[b["ref"]] = sorted(set((tf.get(b["ref"]) or []) + (b.get("tools") or [])))
        if b.get("atom") == "conexion" and b.get("connector"):
            keys[b["connector"]] = {"byok_ref": "keys:" + b["connector"]}
            needs_connection.append(b["connector"])
        if b.get("zone") == "entrega" or _is_gated(b.get("tools")):
            gates_surfaced.append(b["ref"])
    return {
        "recipe_patch": {"belt": {"belt_refs": belt_refs, "tool_filters": tf},
                         "keys": keys},
        "gates_surfaced": sorted(set(gates_surfaced)),
        "needs_connection": sorted(set(needs_connection)),
    }


def propose(intent: str, current_canvas: Optional[dict] = None,
            owner: Optional[str] = None) -> dict:
    from app.phase1.atoms_router import collect_atoms
    # EL DUEÑO, PORQUE LA FORJA PROPONE PIEZAS REALES. Sin él sólo vería el catálogo de la
    # caja — y con la raíz entera (lo de antes) podía proponerle a una cuenta una pieza que
    # trajo OTRA, que es la fuga vestida de sugerencia.
    atoms = collect_atoms(set(), owner=owner)
    by_id = {a["id"]: a for a in atoms}
    cands = _prior_rank(intent, atoms, _TOPK)

    key = ""
    try:
        from app.phase1 import stream_chat
        key = stream_chat._asm()._resolve_cognition_key(stream_chat._REPO)
    except Exception:
        key = ""

    picked, source = None, "fallback"
    if key:
        picked = _llm_select(intent, cands, key)
        if picked is not None:
            source = "llm"

    blocks = []
    if picked and isinstance(picked.get("blocks"), list):
        for sel in picked["blocks"]:
            a = by_id.get((sel or {}).get("id"))   # anti-teatro: solo ids reales
            if a:
                blocks.append(_block_from_atom(a, (sel or {}).get("zone")))
    narration = (picked or {}).get("narration", "") if picked else ""

    if not blocks:   # fallback determinístico: top del prior (1-2 piezas)
        source = "fallback"
        for a in cands[:2]:
            blocks.append(_block_from_atom(a, a.get("zone", "mesa")))
        if blocks and not narration:
            narration = "Te propongo " + ", ".join(b["label"] for b in blocks) + "."

    # de-dup por id
    seen, uniq = set(), []
    for b in blocks:
        if b["id"] in seen:
            continue
        seen.add(b["id"]); uniq.append(b)
    blocks = uniq

    asm = _assemble(blocks)
    narration = (narration or "").strip() or ("Puse " + ", ".join(b["label"] for b in blocks) + "." if blocks else "No encontré una pieza para eso.")
    return {
        "proposal": {"blocks": blocks, "recipe_patch": asm["recipe_patch"]},
        "gates_surfaced": asm["gates_surfaced"],
        "needs_connection": asm["needs_connection"],
        "narration": narration,
        "source": source,
    }
