"""
method_brain.py — el CEREBRO como servicio de la pieza MÉTODO (structure /
propose_edit / adjust) + el congelador determinista guardar-desde-run.

Molde de la casa (BrainSynthesizer de platform/inspection/loop/synth.py):
resolver el alias 'brain' UNA vez vía platform/assembler/models.py, llamada
urllib con UA propio (Cloudflare banea el default), retry x3 con backoff SOLO
por transporte, parse robusto (fences → json.loads → slice), post-validación
campo-a-campo contra el objeto real, y fallo HONESTO (MethodBrainError con
kind tipado — JAMÁS un modelo barato fingiendo de cerebro ni un default que
mute el método del usuario).

`requires[]` sale en ESE MISMO pase de structure. Sus valores no son ids ni
marcas: se validan contra el vocabulario canónico que publica el clasificador
de capacidades 5a. Este módulo sólo lo CONSUME; no mantiene sinónimos ni una
segunda taxonomía.

Multimodal: imágenes viajan como data-URL en el content (el shim :8923 las
traduce a bloques Anthropic; OpenRouter/Opus las acepta nativo). PDF/Word van
como TEXTO vía rag_index.extract_text (el camino de la casa: pypdf/python-docx,
nunca el binario al modelo).
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Optional

from app.phase1 import methods_repo as mr

_REPO_ROOT = Path(__file__).resolve().parents[4]
try:
    import aleph_paths as _ap
except ImportError:
    sys.path.insert(0, str(_REPO_ROOT / "platform"))
    import aleph_paths as _ap
_tool_result_mod = _ap.load_module_by_path(
    "puppet_method_brain_tool_result",
    _ap.resource_root() / "platform" / "assembler" / "tool_result.py")
es_error_de_tool = _tool_result_mod.es_error_de_tool

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")


class MethodBrainError(Exception):
    """kind ∈ brain_unreachable (transporte, tras reintentos) · brain_invalid
    (respondió pero no rinde un método usable) · doc_invalid (el documento no
    rinde texto) · vocabulary_unavailable (5a no publicó vocabulario)."""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(detail or kind)
        self.kind = kind
        self.detail = detail or kind


def _resolve_brain():
    """(endpoint, model, key) del alias 'brain' — misma resolución que el motor.
    Import por sys.path normal (GOTCHA cuarto_guide: importlib con nombre
    sintético rompe el @dataclass de models.py)."""
    _asm = str(_REPO_ROOT / "platform" / "assembler")
    if _asm not in sys.path:
        sys.path.insert(0, _asm)
    import models as _models  # noqa: PLC0415
    rm = _models.resolve("brain")
    key = os.environ.get(rm.key_env) if rm.key_env else None
    return rm.base_url.rstrip("/") + "/chat/completions", rm.model, key


def _call_brain(messages: list[dict], *, max_tokens: int = 1600,
                lang: Optional[str] = None) -> tuple[str, str]:
    """(content, model_final). Retry x3 backoff SOLO por transporte."""
    endpoint, model, key = _resolve_brain()
    from app.phase1.stream_chat import _asm
    messages = _asm()._with_idioma_block(messages, lang)
    body = {"model": model, "messages": messages,
            "max_tokens": max_tokens, "temperature": 0}
    headers = {"content-type": "application/json", "user-agent": _UA}
    if key:
        headers["authorization"] = f"Bearer {key}"
    timeout = float(os.environ.get("PUPPET_HTTP_TIMEOUT", "150"))
    last_exc: Optional[Exception] = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(endpoint, data=json.dumps(body).encode(),
                                         headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
            content = (((data.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
            return content, str(data.get("model") or model)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    raise MethodBrainError("brain_unreachable",
                           f"el cerebro no respondió tras 3 intentos: {last_exc}")


def _slice_json(s: str, open_c: str, close_c: str) -> str:
    i = s.find(open_c)
    j = s.rfind(close_c)
    return s[i:j + 1] if (i != -1 and j != -1 and j > i) else ""


def _parse_json(content: str) -> Any:
    """fences → json directo → slice {..} → slice [..] — tolera prosa alrededor."""
    c = (content or "").strip()
    if c.startswith("```"):
        c = c.strip("`")
        nl = c.find("\n")
        if nl != -1:
            c = c[nl + 1:]
    for chunk in (c, _slice_json(c, "{", "}"), _slice_json(c, "[", "]")):
        if not chunk:
            continue
        try:
            return json.loads(chunk)
        except (json.JSONDecodeError, ValueError):
            continue
    return None


# ── structure: "traer mi proceso" (texto / PDF / Word / imagen) → draft ───────

_STRUCTURE_SYSTEM = {
    "es": (
        "Eres el estructurador de MÉTODOS de Aleph. El usuario trae SU proceso (texto "
        "pegado, un SOP, una checklist) y tú lo conviertes en un método: fases (4-6 "
        "máximo) con mini-pasos en lenguaje natural. REGLAS DURAS: (1) usa SOLO lo que "
        "está en el material — no inventes pasos que no estén ahí; (2) cada paso es una "
        "INTENCIÓN corta en el idioma del material; (3) marca checkpoint:true únicamente "
        "donde el material pida aprobación/revisión humana explícita; (4) emite requires "
        "como la lista de CAPACIDADES GENÉRICAS que el proceso necesita, tomadas LITERALMENTE "
        "del vocabulario permitido que viene al final; jamás nombres una marca, proveedor, "
        "conector, server o id (por ejemplo: «una fuente de filings SEC», no «EDGAR»). "
        "Si no necesita ninguna capacidad externa, requires es []. Responde SOLO un "
        "JSON: {\"name\": \"<nombre corto del método>\", \"steps\": [{\"text\": \"...\", "
        "\"phase\": \"<fase>\", \"checkpoint\": false}], \"requires\": [\"<capacidad "
        "canónica>\"]}"
    ),
    "en": (
        "You are Aleph's METHOD structurer. The user brings THEIR process (pasted text, "
        "an SOP, a checklist) and you turn it into a method: phases (4-6 max) with "
        "mini-steps in natural language. HARD RULES: (1) use ONLY what is in the "
        "material — never invent steps; (2) each step is a short INTENTION in the "
        "material's language; (3) set checkpoint:true only where the material explicitly "
        "asks for human approval/review; (4) emit requires as the GENERIC CAPABILITIES the "
        "process needs, copied LITERALLY from the allowed vocabulary appended below; never "
        "name a brand, provider, connector, server or id (for example, «a source of SEC "
        "filings», not «EDGAR»). If no external capability is needed, requires is []. "
        "Reply ONLY a JSON: {\"name\": \"<short method "
        "name>\", \"steps\": [{\"text\": \"...\", \"phase\": \"<phase>\", "
        "\"checkpoint\": false}], \"requires\": [\"<canonical capability>\"]}"
    ),
}


def _capability_contract(lang: str) -> tuple[str, list[str]]:
    """Prompt + vocabulario de 5a.

    Import lazy para no crear un ciclo method_brain↔method_match. La ausencia de
    declaraciones canónicas es un error tipado y fail-closed: jamás se convierte
    en [] porque eso pintaría verde a un método que todavía no fue clasificado.
    """
    try:
        from app.phase1 import method_match
        vocabulary = method_match.capability_vocabulary()
    except Exception as exc:
        raise MethodBrainError(
            "vocabulary_unavailable",
            f"el clasificador 5a no publicó vocabulario de capacidades: {type(exc).__name__}",
        )
    if not vocabulary:
        raise MethodBrainError(
            "vocabulary_unavailable",
            "el clasificador 5a no publicó vocabulario de capacidades",
        )
    label = "VOCABULARIO CANÓNICO PERMITIDO" if lang != "en" else "ALLOWED CANONICAL VOCABULARY"
    return _STRUCTURE_SYSTEM.get(lang, _STRUCTURE_SYSTEM["es"]) + \
        "\n\n" + label + ":\n- " + "\n- ".join(vocabulary), vocabulary


def _canonical_requires(raw: Any, vocabulary: list[str]) -> list[str]:
    """Valida contra 5a por capacidad↔capacidad; no conoce ids ni sinónimos."""
    if not isinstance(raw, list):
        raise MethodBrainError("brain_invalid", "requires debe ser una lista")
    by_fold = {str(c).strip().casefold(): str(c).strip() for c in vocabulary if str(c).strip()}
    out: list[str] = []
    for value in raw:
        key = str(value or "").strip().casefold()
        canonical = by_fold.get(key)
        if not canonical:
            raise MethodBrainError(
                "brain_invalid",
                f"capacidad fuera del vocabulario 5a: {str(value or '')[:120]!r}",
            )
        if canonical not in out:
            out.append(canonical)
    return out


def structure_draft(*, text: Optional[str] = None, filename: Optional[str] = None,
                    mime: Optional[str] = None, data_b64: Optional[str] = None,
                    lang: str = "es") -> dict:
    """Draft de Method desde el material del usuario. Devuelve el draft SIN id
    (el editor decide guardarlo). Lanza MethodBrainError honesto si el cerebro
    no responde o el material no rinde."""
    user_content: Any
    material = (text or "").strip()
    if data_b64:
        try:
            blob = base64.b64decode(data_b64)
        except Exception:
            raise MethodBrainError("doc_invalid", "data_b64 no es base64 válido")
        if (mime or "").startswith("image/"):
            # imagen RAW al cerebro como data-URL (shim/OpenRouter la ven)
            parts: list[dict] = []
            prompt_txt = material or ("Estructura el proceso de esta imagen."
                                      if lang != "en" else
                                      "Structure the process in this image.")
            parts.append({"type": "text", "text": prompt_txt})
            parts.append({"type": "image_url", "image_url": {
                "url": f"data:{mime};base64,{data_b64}"}})
            user_content = parts
        else:
            from app.phase1 import rag_index
            try:
                doc_text = rag_index.extract_text(filename, mime, blob)
            except rag_index.RagIngestError as exc:
                raise MethodBrainError("doc_invalid", str(exc))
            user_content = (material + "\n\n" if material else "") + doc_text[:24000]
    elif material:
        user_content = material[:24000]
    else:
        raise MethodBrainError("doc_invalid", "no llegó ni texto ni archivo")

    system, vocabulary = _capability_contract(lang)
    content, model_final = _call_brain([
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ], lang=lang)
    obj = _parse_json(content)
    if not isinstance(obj, dict):
        raise MethodBrainError("brain_invalid", "la respuesta del cerebro no es JSON")
    draft = mr.normalize_method(obj)
    draft["steps"] = [s for s in draft["steps"] if s.get("text")]
    if not draft["steps"]:
        raise MethodBrainError("brain_invalid", "el cerebro no extrajo ningún paso")
    draft["requires"] = _canonical_requires(obj.get("requires"), vocabulary)
    if not draft["name"]:
        draft["name"] = (filename or "Mi método").rsplit(".", 1)[0][:60]
    draft.pop("id", None)   # el draft nunca viaja con id (el editor lo borra igual)
    draft["source"] = {"kind": "structure", "model": model_final}
    return draft


_REQUIRES_BACKFILL_SYSTEM = {
    "es": (
        "Extrae ÚNICAMENTE las capacidades externas que este método necesita para poder "
        "cumplirse. Devuelve SOLO {\"requires\":[...]}. Cada valor debe copiarse LITERALMENTE "
        "del vocabulario canónico permitido. Capacidad genérica, jamás marca, proveedor, "
        "conector, server ni id. Si no necesita ninguna, devuelve requires:[]."
    ),
    "en": (
        "Extract ONLY the external capabilities this method needs in order to run. Reply "
        "ONLY {\"requires\":[...]}. Every value must be copied LITERALLY from the allowed "
        "canonical vocabulary. Use generic capabilities, never brands, providers, connectors, "
        "servers or ids. If it needs none, return requires:[]."
    ),
}


def extract_requires(method: dict, *, lang: str = "es") -> list[str]:
    """Backfill legado, una vez: Method sin `requires` → lista canónica de 5a.

    No se usa para `structure_draft`: ahí requires viaja en el mismo pase. El
    caller persiste el resultado para que un método existente no vuelva a pasar
    por el extractor en cada lectura.
    """
    _system, vocabulary = _capability_contract(lang)
    label = "VOCABULARIO CANÓNICO PERMITIDO" if lang != "en" else "ALLOWED CANONICAL VOCABULARY"
    prompt = _REQUIRES_BACKFILL_SYSTEM.get(lang, _REQUIRES_BACKFILL_SYSTEM["es"]) + \
        "\n\n" + label + ":\n- " + "\n- ".join(vocabulary)
    base = mr.normalize_method(method)
    payload = {
        "name": base.get("name") or "",
        "steps": [
            {"text": s.get("text") or "", "phase": s.get("phase") or ""}
            for s in (base.get("steps") or [])
        ],
    }
    content, _model = _call_brain([
        {"role": "system", "content": prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ], max_tokens=700, lang=lang)
    obj = _parse_json(content)
    if not isinstance(obj, dict):
        raise MethodBrainError("brain_invalid", "el extractor de requires no devolvió JSON")
    return _canonical_requires(obj.get("requires"), vocabulary)


# ── propose_edit / adjust: "editar conversando" → pasos NUEVOS completos ─────

_EDIT_SYSTEM = {
    "es": (
        "Eres el editor conversacional de MÉTODOS de Aleph. Recibes el método actual "
        "(JSON) y una instrucción del dueño. Devuelves los pasos NUEVOS COMPLETOS (no un "
        "diff): la lista entera de steps tras aplicar la instrucción. REGLAS DURAS: "
        "(1) preserva el campo `id` de los pasos que NO cambian; (2) pasos nuevos van "
        "SIN id; (3) no borres pasos que la instrucción no pide borrar; (4) si la "
        "instrucción no se puede aplicar a este método, devuelve {\"error\": \"<por qué, "
        "corto>\"}. Responde SOLO un JSON: {\"summary\": \"<qué cambiaste, 1 línea>\", "
        "\"steps\": [{\"id\": \"...\", \"text\": \"...\", \"phase\": \"...\", "
        "\"checkpoint\": false, \"executor\": null}]}"
    ),
    "en": (
        "You are Aleph's conversational METHOD editor. You receive the current method "
        "(JSON) and an instruction from the owner. You return the COMPLETE NEW steps "
        "(not a diff): the whole steps list after applying the instruction. HARD RULES: "
        "(1) preserve the `id` of steps that do NOT change; (2) new steps carry NO id; "
        "(3) never delete steps the instruction did not ask to delete; (4) if the "
        "instruction cannot apply to this method, reply {\"error\": \"<why, short>\"}. "
        "Reply ONLY a JSON: {\"summary\": \"<what you changed, 1 line>\", \"steps\": "
        "[{\"id\": \"...\", \"text\": \"...\", \"phase\": \"...\", \"checkpoint\": "
        "false, \"executor\": null}]}"
    ),
}


def propose_edit(method: dict, instruction: str, *, lang: str = "es") -> dict:
    """{summary, steps} — pasos nuevos completos, validados contra el método REAL.
    Default NO-MUTAR: cualquier duda ⇒ MethodBrainError (el front no aplica nada)."""
    instruction = (instruction or "").strip()
    if not instruction:
        raise MethodBrainError("brain_invalid", "instrucción vacía")
    base = mr.normalize_method(method)
    payload = {"method": {"name": base.get("name"),
                          "phases": mr.named_phases(base),
                          "steps": base.get("steps")},
               "instruction": instruction}
    content, _model = _call_brain([
        {"role": "system", "content": _EDIT_SYSTEM.get(lang, _EDIT_SYSTEM["es"])},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ], lang=lang)
    obj = _parse_json(content)
    if not isinstance(obj, dict):
        raise MethodBrainError("brain_invalid", "la respuesta del cerebro no es JSON")
    if obj.get("error"):
        raise MethodBrainError("brain_invalid", str(obj["error"])[:300])
    steps_raw = obj.get("steps")
    if not isinstance(steps_raw, list) or not steps_raw:
        # una propuesta vacía sería un "borrá todo" lavado — rechazo honesto
        raise MethodBrainError("brain_invalid", "el cerebro no devolvió pasos")
    known_ids = set(mr.steps_by_id(base).keys())
    used_ids: set[str] = set()
    steps: list[dict] = []
    for s in steps_raw:
        ns = mr.normalize_step(s)
        if not ns["text"]:
            continue
        # anti-alucinación: solo un id que EXISTE en el método real (y no está
        # repetido en la propuesta) conserva identidad; el resto se re-acuña
        if ns["id"] not in known_ids or ns["id"] in used_ids:
            ns["id"] = mr.normalize_step({})["id"]
        used_ids.add(ns["id"])
        steps.append(ns)
    if not steps:
        raise MethodBrainError("brain_invalid", "los pasos propuestos vinieron vacíos")
    return {"summary": str(obj.get("summary") or "")[:300], "steps": steps}


# ── guardar-desde-run: DETERMINISTA (el plan del run ES el método, ORDEN §3) ──

def freeze_from_run(events: list[dict], *, run_id: str, intent: Optional[str],
                    lang: str = "es") -> dict:
    """Congela el plan/las tools REALES del run como draft de Method. Cero LLM:
    plan_declared (si existe) manda; si no, la secuencia de tool_call_finished
    ok. Lanza MethodBrainError('run_sin_material') si el run no rinde pasos."""
    plan_steps: list[dict] = []
    tool_steps: list[dict] = []
    for ev in events:
        if ev.get("run_id") not in (None, run_id):
            continue
        if ev.get("type") == "plan_declared" and not plan_steps:
            for p in ev.get("steps") or []:
                txt = str((p.get("paso") if isinstance(p, dict) else p) or "").strip()
                if txt:
                    plan_steps.append({"text": txt,
                                       "executor": (p.get("tool") if isinstance(p, dict) else None) or None})
        elif ev.get("type") == "tool_call_finished" and ev.get("status") == "ok":
            result = str(ev.get("result") or "")
            if es_error_de_tool(result):
                continue
            tool = str(ev.get("tool") or ev.get("tool_raw") or "").strip()
            if not tool:
                continue
            # dedupe consecutivo: N llamadas seguidas a la misma tool = 1 paso
            if tool_steps and tool_steps[-1].get("executor") == tool:
                continue
            verb = "Usar" if lang != "en" else "Use"
            tool_steps.append({"text": f"{verb} {tool}", "executor": tool})
    steps = plan_steps or tool_steps
    if not steps:
        raise MethodBrainError("run_sin_material",
                               "el run no declaró plan ni tuvo tool-calls con evidencia")
    name = ("Método de: " if lang != "en" else "Method from: ") + \
           ((intent or "").strip()[:60] or run_id[:8])
    draft = mr.normalize_method({"name": name, "steps": steps})
    draft["source"] = {"kind": "from_run", "run_id": run_id}
    return draft
