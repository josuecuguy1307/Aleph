"""
loop/synth.py — Capa 3 · el Sintetizador · Opus 4.8 REAL vía shim.

Opus propone: "vi estos endpoints/campos confirmados + esta respuesta cruda →
estas tools de lectura tienen sentido" → CANDIDATES. Tres cosas que lo hacen
honesto y útil al candado:

  • CEREBRO REAL: llama Opus 4.8 por el shim OpenAI-compat (models.resolve('brain'),
    :8923 con PUPPET_BRAIN_SHIM=1). Mide tokens reales contra el budget (§6).
  • NO REPITE ERRORES: recibe los FAILED (con su clase §5) y los endpoints ya
    VERIFIED; el prompt le prohíbe re-proponerlos.
  • CANDIDATA EJECUTABLE: cada propuesta trae un `sample_call` concreto (path/query)
    tomado de ids/frontera CONFIRMADOS, para que el candado pueda LLAMARLA de verdad.

DEGRADADO HONESTO: si el shim no responde (502/timeout/no-200), `last.degraded=True`
y devuelve () — el cerebro es el sintetizador; no se mete un modelo barato a fingir
de cerebro. El engine surfacea `degraded:true` en el evento (no silencio).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

_PLATFORM = Path(__file__).resolve().parents[2]
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection import contracts as C  # noqa: E402

try:
    from assembler import models as _models  # type: ignore
except Exception:  # pragma: no cover — el resolver de modelos es opcional
    _models = None


_SYSTEM = """\
Eres la CAPA 3 (sintetizador) de un motor que forja un MCP desde una API REST cruda,
a partir de evidencia viva. Tu trabajo: proponer TOOLS candidatas para esta API,
basándote en las capacidades CONFIRMED y en la respuesta cruda observada. Una capa
validadora llamará CADA candidata de lectura contra el software vivo; las de
escritura se verifican POR FORMA sin ejecutarse jamás. Las que fallen vuelven a ti
como FAILED — NO las repitas.

REGLAS DURAS:
- La MAYORÍA de las tools deben ser GET (lectura). PERO en CADA vuelta propón también
  2-4 tools de ESCRITURA (POST/PUT/PATCH) que un usuario del software necesitaría para
  operar (crear/ajustar registros, cambiar estados, crear órdenes). Proponelas AUNQUE
  la evidencia no muestre esos endpoints — una API REST estándar suele aceptar POST en
  sus recursos y PATCH en sus items; la validación las confirma o descarta POR FORMA,
  sin ejecutarlas jamás contra el software (no muta nada). Marca su method real — el
  motor las emite GATED (piden OK humano). Nada de DELETE salvo que la evidencia lo
  pida explícito.
- Propón endpoints PLAUSIBLES y explora la superficie: varía recursos y
  sub-recursos. Está BIEN arriesgar candidatas inciertas — el candado las filtra.
- SONDEO DEL BORDE (clave): un loop de descubrimiento debe empujar más allá de lo
  que ya conoce. En CADA vuelta incluye 1-2 candidatas de SONDEO en el límite de la
  API — sub-recursos o variantes MENOS comunes de los que no estás seguro/a. Si no
  existen, el candado las descarta: eso es lo ESPERADO y útil (así se mapea la
  frontera real del software, no la de tu memoria). No las omitas por miedo a fallar.
- Cada tool DEBE traer un `sample_call` CONCRETO y llamable AHORA, con valores
  reales tomados de los ids/campos que ves en la evidencia (no inventes ids si hay
  reales en la frontera/observación).
- No re-propongas un endpoint que ya está en VERIFIED ni en FAILED.

Responde EXCLUSIVAMENTE un JSON válido con esta forma (sin texto alrededor, sin ```):
{"tools": [
  {"name": "get_movie_details",
   "endpoint": "/movie/{movie_id}",
   "method": "GET",
   "description": "Detalle de una película por id.",
   "input_schema": {"type":"object","properties":{"movie_id":{"type":"integer"}},"required":["movie_id"]},
   "sample_call": {"path_params": {"movie_id": 550}, "query": {"language": "en-US"}}}
]}
Devuelve entre 3 y 8 tools por vuelta."""


@dataclass
class SynthOutcome:
    """Lo que el engine lee tras una vuelta de síntesis (la firma del Protocol solo
    devuelve la tupla; el detalle vive acá)."""
    degraded: bool = False
    model: str = ""
    reason: str = ""
    raw: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    proposed: int = 0


class BrainSynthesizer:
    """Capa 3 con cerebro real. Satisface el Protocol C.Synthesizer."""

    def __init__(self, base_host: str, *, ledger: Any = None, max_tokens: int = 1800,
                 timeout: float = 90.0, alias: str = "brain", shape_hint: str = ""):
        self._base_host = base_host
        self._ledger = ledger
        self._max_tokens = max_tokens
        self._timeout = timeout
        self._alias = alias
        # GENÉRICO: pista de la FORMA del target (p.ej. AV es despacho-por-query: todo
        # va a /query y la operación la elige `function`). Vacío → API REST por path (TMDB).
        self._shape_hint = shape_hint
        self._dispatch_param = ""        # lo fija el engine (set_dispatch_param)
        self.last = SynthOutcome()
        # resolución del cerebro (Opus vía shim) — 1 sola vez.
        if _models is not None:
            rm = _models.resolve(alias)
            self._endpoint = rm.base_url.rstrip("/") + "/chat/completions"
            self._model = rm.model
            self._key = os.environ.get(rm.key_env) if rm.key_env else None
        else:  # fallback al shim por env directo
            base = os.environ.get("PUPPET_BRAIN_SHIM_BASE_URL", "http://127.0.0.1:8923/v1")
            self._endpoint = base.rstrip("/") + "/chat/completions"
            self._model = os.environ.get("PUPPET_BRAIN_SHIM_MODEL", "claude-opus-4.8")
            self._key = None

    def set_dispatch_param(self, dispatch_param: str) -> None:
        self._dispatch_param = dispatch_param or ""

    def synthesize(
        self,
        confirmed: Sequence[C.Capability],
        observation: C.Observation,
        failed: Sequence[C.FailedTool],
    ) -> tuple[C.CandidateTool, ...]:
        user = self._build_user_prompt(confirmed, observation, failed)
        # RETRY: un blip transitorio del shim (cold start del proxy, timeout puntual) NO
        # debe matar el run. Reintenta 2 veces con backoff corto; recién si TODOS fallan
        # se declara degraded (honesto: el cerebro de verdad no responde). Una caída
        # SOSTENIDA (puerto muerto) agota los reintentos rápido y degrada igual.
        last_exc: Optional[Exception] = None
        data = None
        for attempt in range(3):
            try:
                data = self._call_brain(user)
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < 2:
                    import time as _t
                    _t.sleep(1.5 * (attempt + 1))
        if data is None:
            self.last = SynthOutcome(degraded=True, model=self._model,
                                     reason=f"brain no respondió tras 3 intentos: {last_exc}")
            return ()

        usage = data.get("usage") or {}
        pt = int(usage.get("prompt_tokens") or 0)
        ct = int(usage.get("completion_tokens") or 0)
        if self._ledger is not None:
            self._ledger.add_tokens(pt + ct)
        content = (((data.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
        tools = self._parse_tools(content)
        cands = self._to_candidates(tools, confirmed, failed)
        self.last = SynthOutcome(degraded=False, model=data.get("model") or self._model,
                                 raw=content[:4000], prompt_tokens=pt, completion_tokens=ct,
                                 proposed=len(cands))
        return cands

    # ── prompt ────────────────────────────────────────────────────────────────
    def _build_user_prompt(self, confirmed, observation, failed) -> str:
        conf = [{"endpoint": c.endpoint, "method": c.method, "fields": list(c.fields)[:16],
                 "evidence": c.evidence} for c in confirmed][:30]
        fail = [{"endpoint": f.candidate.endpoint, "name": f.candidate.name,
                 "class": f.failure.name, "symptom": f.failure.symptom,
                 "move": f.failure.move, "detail": f.detail[:200]} for f in failed][:40]
        obs = {
            "mode": observation.capability_map.get("mode"),
            "passive": observation.passive,
        }
        # evidencia cruda recortada (snippets) — lo que el cerebro REALMENTE vio.
        cm = observation.capability_map
        if "probes" in cm:
            obs["probes"] = {k: {"status": v.get("status"), "shape": v.get("shape"),
                                 "snippet": (v.get("snippet") or "")[:700]}
                             for k, v in cm["probes"].items()}
        else:
            obs["probed"] = cm.get("probed")
            obs["status"] = cm.get("status")
            obs["snippet"] = (cm.get("snippet") or "")[:900]

        payload = {
            "api_base": self._base_host,           # host SIN secreto
            "auth": "api_key va en el query string (no lo incluyas tú; la capa de red lo inyecta)",
            "CONFIRMED": conf,
            "OBSERVATION": obs,
            "FAILED_no_repetir": fail,
        }
        hint = (f"\n\nFORMA DE LA API (importante): {self._shape_hint}" if self._shape_hint else "")
        return ("Contexto del loop (JSON):\n" + json.dumps(payload, ensure_ascii=False)
                + hint + "\n\nPropón las próximas tools candidatas — lecturas (GET) y también "
                         "las escrituras (POST/PUT/PATCH) que esta API claramente soporta y un "
                         "usuario necesitaría (crear/ajustar registros, cambiar estados, crear "
                         "órdenes); marca el method real de cada una.")

    # ── llamada al cerebro ──────────────────────────────────────────────────────
    def _call_brain(self, user: str) -> dict:
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": user},
            ],
            "max_tokens": self._max_tokens,
            "temperature": 0,
        }
        headers = {
            "content-type": "application/json",
            # Cloudflare (delante de Groq/OpenRouter) 403ea el UA por defecto de urllib
            # ("Python-urllib/x"). Un UA de navegador pasa. El shim local no lo necesita.
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        }
        if self._key:
            headers["authorization"] = f"Bearer {self._key}"
        req = urllib.request.Request(self._endpoint, data=json.dumps(body).encode(),
                                     headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            return json.loads(resp.read().decode())

    # ── parseo robusto ──────────────────────────────────────────────────────────
    @staticmethod
    def _parse_tools(content: str) -> list[dict]:
        content = (content or "").strip()
        if content.startswith("```"):
            content = content.strip("`")
            nl = content.find("\n")
            if nl != -1:
                content = content[nl + 1:]
        # intento directo
        for chunk in (content, _slice_json(content, "{", "}"), _slice_json(content, "[", "]")):
            if not chunk:
                continue
            try:
                obj = json.loads(chunk)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(obj, dict) and isinstance(obj.get("tools"), list):
                return obj["tools"]
            if isinstance(obj, list):
                return obj
        return []

    def _to_candidates(self, tools: list[dict], confirmed, failed) -> tuple[C.CandidateTool, ...]:
        seen_bad = {tool_signature(f.candidate, self._dispatch_param) for f in failed}
        out: list[C.CandidateTool] = []
        for t in tools:
            if not isinstance(t, dict):
                continue
            endpoint = str(t.get("endpoint") or "").strip()
            name = str(t.get("name") or "").strip()
            if not endpoint.startswith("/") or not name:
                continue
            schema = t.get("input_schema") or {"type": "object", "properties": {}}
            if isinstance(schema, dict) and isinstance(t.get("sample_call"), dict):
                schema = dict(schema)
                schema["x-sample-call"] = t["sample_call"]
            _method = str(t.get("method") or "GET").upper()
            cand = C.CandidateTool(
                name=_slug(name),
                # H-P2-01 (Caso 3): el synth proponía TODO como READ aunque el método fuera
                # POST/PATCH — el kind sale del método real; WRITE viaja al camino §7
                # (verificación por forma, emisión GATED, jamás se ejecuta al validar).
                kind=(C.ToolKind.WRITE if _method in ("POST", "PUT", "PATCH", "DELETE")
                      else C.ToolKind.READ),
                endpoint=endpoint,
                method=_method,
                input_schema=schema if isinstance(schema, dict) else {},
                description=str(t.get("description") or "")[:300],
                derived_from=tuple(c.endpoint for c in list(confirmed)[:4]),
            )
            if tool_signature(cand, self._dispatch_param) in seen_bad:
                continue  # el cerebro no debe repetir un FAILED; lo filtramos por firma
            out.append(cand)
        return tuple(out)


def tool_signature(cand: C.CandidateTool, dispatch_param: str = "") -> str:
    """IDENTIDAD de una tool para dedup. Normalmente = su endpoint (TMDB: cada tool
    es un path distinto). Pero en APIs de DESPACHO-POR-QUERY (Alpha Vantage: TODO va a
    /query y la operación la nombra `function`) el endpoint es el MISMO para todas →
    el dedup colapsaría. Con `dispatch_param` la firma incluye el valor de despacho
    (`/query#function=GLOBAL_QUOTE`), así dos funciones distintas no colisionan."""
    if dispatch_param:
        q = (cand.input_schema or {}).get("x-sample-call", {})
        q = q.get("query", {}) if isinstance(q, dict) else {}
        val = q.get(dispatch_param) if isinstance(q, dict) else None
        if val not in (None, ""):
            return f"{cand.endpoint}#{dispatch_param}={val}"
    return cand.endpoint


def _slice_json(s: str, open_c: str, close_c: str) -> str:
    i = s.find(open_c)
    j = s.rfind(close_c)
    return s[i:j + 1] if (i != -1 and j != -1 and j > i) else ""


def _slug(text: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "_" for c in (text or "tool"))
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_") or "tool"
