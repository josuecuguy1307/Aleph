"""
loop/validator.py — Capa 4 · EL CANDADO (§4).

La única capa que toca la verdad: llama CADA candidata contra el software vivo y
parte VERIFIED de FAILED. No miente — es el árbitro.

  • READ (§7): se LLAMA de verdad (GET vivo con el sample_call concreto). 2xx + cuerpo
    CON FORMA ⇒ VerifiedTool(verified_by="200-OK+schema-match", sample_response=snippet)
    y MINA la respuesta por recursos nuevos ⇒ FRONTIER (paginación + sub-recursos por id).
  • WRITE (§7): NO se ejecuta JAMÁS (mutaría data real). Se verifica por FORMA —
    schema (estático) → dry-run (GET validate declarado) → OPTIONS (preflight: el
    endpoint existe y `Allow` acepta el método). VerifiedTool(verified_by=
    "schema|dry-run|OPTIONS", NUNCA "200-OK"). NO expande frontera (no hubo respuesta
    que minar). El MCP forjado lo emite GATED (gate humano antes de tocar el mundo).

Toda falla pasa por la tabla §5 (FailureClass.from_symptom) → la clase trae el
nivel y el MOVE; el detalle viaja al sintetizador para no repetir el error.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

_PLATFORM = Path(__file__).resolve().parents[2]
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection import contracts as C  # noqa: E402
from inspection.loop.live_http import HttpResult, LiveHTTP  # noqa: E402

_SNIPPET = 900
_PATH_PARAM = re.compile(r"\{([^}]+)\}")
_MAX_FRONTIER_PER_TOOL = 6
# §7 · métodos que MUTAN el mundo. Un write con uno de estos NO se ejecuta jamás para
# validar — se verifica por forma (schema/OPTIONS/dry-run).
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# DELETE identifica el recurso por path → no exige cuerpo; los demás escriben un cuerpo.
_BODYLESS_WRITE = {"DELETE"}

# señales de que un sobre de error en-banda es TRANSITORIO/gated (no una alucinación):
# rate-limit, pacing, endpoint premium. Una función con este mensaje PUEDE existir.
_TRANSIENT_MARKERS = (
    "rate limit", "per day", "per minute", "higher api call", "premium",
    "subscribe", "thank you for using",
)


def classify_soft_envelope(body, soft_error: set, soft_notice: set) -> str:
    """'error' | 'notice' | '' para un body JSON. COMPARTIDO por el validador (Capa 4)
    y la sesión (Capa 1) — la misma regla decide en ambos lados.

      '' (vacío)  → hay clave de DATOS → respuesta real (no es un sobre de error).
      'notice'    → sobre que es SOLO error/aviso PERO transitorio/gated (rate-limit,
                    premium): la operación puede existir; no es alucinación.
      'error'     → sobre que es SOLO error permanente ("Invalid API call", "does not
                    exist"): la función/param no existe → la alucinación cae acá.
    """
    if not (soft_error or soft_notice) or not isinstance(body, dict) or not body:
        return ""
    keys = {str(k).lower() for k in body.keys()}
    if not (keys <= (soft_error | soft_notice)):     # hay clave de datos → real
        return ""
    msg = " ".join(str(v) for v in body.values()).lower()
    if any(t in msg for t in _TRANSIENT_MARKERS):
        return "notice"
    if (keys & soft_notice) and not (keys & soft_error):
        return "notice"
    return "error"


class LiveValidator:
    """Capa 4 contra software vivo. Satisface el Protocol C.Validator.

    `soft_error_keys`/`soft_notice_keys`: GENÉRICO para APIs que señalan errores
    EN BANDA (HTTP 200 + un body que es solo `{"Error Message": …}` / `{"Note": …}`,
    como Alpha Vantage). Un 200 cuyo body es SOLO claves de error/aviso (sin ninguna
    clave de datos) NO es una tool verificada — es un fallo disfrazado. Vacío () →
    comportamiento idéntico al de una API que usa status HTTP (TMDB): no dispara."""

    def __init__(self, http: LiveHTTP, *,
                 soft_error_keys: Sequence[str] = (),
                 soft_notice_keys: Sequence[str] = (),
                 ledger: Any = None,
                 guard: Any = None):
        self._http = http
        self._soft_error = {k.lower() for k in soft_error_keys}
        self._soft_notice = {k.lower() for k in soft_notice_keys}
        # cap DURO por-call: si el ledger se agota a mitad de un batch, el candado PARA
        # (no sobrepasa el budget §6). None → sin límite (lock self-test aislado).
        self._ledger = ledger
        # §7 · guard anti-SSRF para los fetches de VERIFICACIÓN de writes (OPTIONS/dry-run).
        # Fail-closed por default (PublicHTTPGuard: solo https a hosts públicos). La rama
        # READ NO lo usa (sigue byte-equivalente); solo el camino write nuevo lo consulta
        # ANTES de cualquier fetch (la directiva: SSRF guard antes de tocar el target).
        if guard is None:
            from inspection.loop.guard import PublicHTTPGuard
            guard = PublicHTTPGuard()
        self._guard = guard

    def _soft_envelope(self, body) -> str:
        """Delega en la función compartida classify_soft_envelope (la MISMA regla que usa
        la sesión). Vacío () → no dispara (APIs que usan status HTTP, como TMDB)."""
        return classify_soft_envelope(body, self._soft_error, self._soft_notice)

    def validate(self, session: C.Session, candidates: Sequence[C.CandidateTool]) -> C.Validation:
        base = session.base_url.rstrip("/")
        verified: list[C.VerifiedTool] = []
        failed: list[C.FailedTool] = []
        frontier: list[C.FrontierLead] = []

        for cand in candidates:
            # cap DURO §6: si no queda budget de calls, PARÁ (no sobrepases el techo).
            if self._ledger is not None and not self._ledger.can_make_call():
                break
            if cand.kind is C.ToolKind.WRITE:
                # §7: el write NO se ejecuta NUNCA. Se verifica por FORMA (schema → dry-run
                # → OPTIONS), sin tocar el mundo, y NO expande frontera (no hubo respuesta
                # que minar). El veredicto entra verbatim — verified o failed.
                outcome = self._verify_write(base, cand)
                if isinstance(outcome, C.VerifiedTool):
                    verified.append(outcome)      # SIN self._mine: el write no se ejecutó.
                else:
                    failed.append(outcome)
                continue

            url, missing = self._resolve_url(base, cand)
            if missing:
                # no hay con qué llamarla → es un defecto de FORMA (400-like) → resynth.
                failed.append(C.FailedTool(
                    candidate=cand, failure=C.FailureClass.BAD_SHAPE,
                    detail=f"sample_call sin valores para path params: {missing}"))
                continue

            res = self._http.get(url, _query_of(cand))
            verdict = self._judge(res)
            # [T-4 · re-observe auth-scheme] Si el token venía como QUERY (forma=token
            # default) y el endpoint REAL responde 401/403, el esquema puede estar mal:
            # muchas APIs (InvenTree, GitHub, Notion) exigen el token en HEADER. En vez de
            # dropear (el fallo histórico T-4), re-observamos UNA vez con header y, si
            # autentica, ADOPTAMOS header para el resto del run. Sin esto, header-token
            # era inconstruible por la UI simple (solo inyecta query).
            if verdict == "401_403" and self._maybe_switch_to_header(url, cand):
                res = self._http.get(url, _query_of(cand))
                verdict = self._judge(res)
            if verdict == "verified":
                vt = C.VerifiedTool(
                    candidate=cand,
                    verified_by="200-OK+schema-match",
                    sample_response=(res.text or "")[:_SNIPPET],
                )
                verified.append(vt)
                frontier.extend(self._mine(cand, res, base))
            else:
                fc = C.FailureClass.from_symptom(verdict)
                soft = self._soft_envelope(res.json) if res.ok else ""
                where = (f"200+sobre-de-{soft}-en-banda" if soft else f"HTTP {res.status}")
                inband = ""
                if soft and isinstance(res.json, dict):
                    inband = " · " + json.dumps(res.json, ensure_ascii=False)[:200]
                failed.append(C.FailedTool(
                    candidate=cand, failure=fc,
                    detail=f"{where} en {res.url_redacted}"
                           + (f" · {res.reason}" if res.reason else "")
                           + inband + f" → move={fc.move}"))

        return C.Validation(verified=tuple(verified), failed=tuple(failed),
                            frontier=tuple(_dedup_frontier(frontier)))

    def switched_headers(self) -> dict:
        """[T-4] Si la validación conmutó a header (re-observe), los headers de auth REALES
        con que se verificaron las tools — para que el forge spec los declare (no query).
        {} si nunca conmutó (la sesión ya traía la auth correcta)."""
        if getattr(self, "_auth_switched", False):
            return dict(getattr(self._http, "_session_headers", {}) or {})
        return {}

    # ── [T-4 · re-observe] query-auth 401 → probar header, adoptar si autentica ──
    def _maybe_switch_to_header(self, url: str, cand: C.CandidateTool) -> bool:
        """Un intento acotado: si la sesión inyecta el token en QUERY y el endpoint dio
        401/403, probá el MISMO GET con el token en header (Token/Bearer). Si uno da <400,
        reemplazá self._http por la variante header (el resto del run va por header) y
        devolvé True. Fail-safe: cualquier problema → False (dropea como antes)."""
        http = self._http
        secret = getattr(http, "_secret", "") or ""
        # solo aplica si HAY secreto en query y NO hay ya headers de sesión (forma 2/3)
        if not secret or getattr(http, "_session_headers", None):
            return False
        if getattr(self, "_auth_switched", False):
            return False
        for template in ("Token {token}", "Bearer {token}"):
            if self._ledger is not None and not self._ledger.can_make_call():
                break
            try:
                probe = LiveHTTP(
                    secret="", auth_param="",
                    timeout=getattr(http, "_timeout", 15.0),
                    ledger=self._ledger,
                    min_interval=getattr(http, "_min_interval", 0.0),
                    headers={"Authorization": template.format(token=secret)},
                )
                res = probe.get(url, _query_of(cand))
            except Exception:
                continue
            if res.ok and res.status not in (401, 403):
                self._http = probe
                self._auth_switched = True
                return True
        return False

    # ── resolución de la URL concreta a llamar ─────────────────────────────────
    def _resolve_url(self, base: str, cand: C.CandidateTool) -> tuple[str, list[str]]:
        sample = (cand.input_schema or {}).get("x-sample-call") or {}
        path_params = sample.get("path_params") or {}
        path = cand.endpoint
        missing: list[str] = []
        for name in _PATH_PARAM.findall(cand.endpoint):
            if name in path_params and path_params[name] not in (None, ""):
                path = path.replace("{" + name + "}", str(path_params[name]))
            else:
                missing.append(name)
        return base + path, missing

    # ── §7 · VERIFICAR un WRITE sin ejecutarlo (schema → dry-run → OPTIONS) ─────
    def _verify_write(self, base: str, cand: C.CandidateTool):
        """Devuelve VerifiedTool (verified_by ∈ schema|dry-run|OPTIONS) o FailedTool.
        LÍNEA DURA: jamás se emite el método mutante (POST/PUT/PATCH/DELETE) contra el
        target — solo OPTIONS (preflight, no muta) y un dry-run GET declarado a un
        endpoint de validación. NO se mina frontera (no se ejecutó)."""
        url, missing = self._resolve_url(base, cand)
        if missing:
            return C.FailedTool(
                candidate=cand, failure=C.FailureClass.BAD_SHAPE,
                detail=f"sample_call sin valores para path params: {missing} → move=resynth_shape")

        # 1 · SCHEMA (estático, cero red, cero mutación): ¿la candidata declara una forma
        #     coherente? Sin esto, ni vale la pena preflightear.
        shape_ok, shape_why = self._write_shape_ok(cand)
        if not shape_ok:
            return C.FailedTool(
                candidate=cand, failure=C.FailureClass.BAD_SHAPE,
                detail=f"write sin forma coherente: {shape_why} → move=resynth_shape")

        # 2 · DRY-RUN (opt-in): si la candidata declara un endpoint validate/dry-run, se
        #     prueba con un GET (no muta). Es el modo más fuerte: la API validó la request.
        dr = self._try_dry_run(base, cand)
        if dr is not None:
            return dr

        # 3 · OPTIONS (preflight SSRF-guardado): existe el endpoint y acepta el método.
        verdict = self._guard.check(url)
        if not getattr(verdict, "allowed", False):
            return C.FailedTool(
                candidate=cand, failure=C.FailureClass.FORBIDDEN,
                detail=f"OPTIONS bloqueado por SSRF guard: {getattr(verdict, 'reason', '')} "
                       f"→ move={C.FailureClass.FORBIDDEN.move}")
        res = self._http.options(url)
        allow = {m.upper() for m in (res.allow or ())}
        method = (cand.method or "").upper()

        if res.status == 0:
            return self._write_failed(cand, "timeout_5xx", f"OPTIONS sin transporte en {res.url_redacted}"
                                      + (f" · {res.reason}" if res.reason else ""))
        if res.status == 404:
            return self._write_failed(cand, "404", f"OPTIONS 404 — endpoint inexistente en {res.url_redacted}")
        if res.status in (401, 403) and not allow:
            return self._write_failed(cand, "401_403", f"OPTIONS {res.status} — fuera de scope de la credencial")
        if allow:
            if method in allow:
                return C.VerifiedTool(candidate=cand, verified_by="OPTIONS", sample_response=None)
            return self._write_failed(
                cand, "404",
                f"OPTIONS Allow={sorted(allow)} NO incluye {method} → el write declarado no existe")
        # endpoint alcanzable pero sin anunciar Allow → confirmamos solo la FORMA declarada.
        # Honesto: verified_by='schema' (no afirmamos que el método se aceptó en red).
        return C.VerifiedTool(candidate=cand, verified_by="schema", sample_response=None)

    def _write_failed(self, cand: C.CandidateTool, symptom: str, detail: str) -> C.FailedTool:
        fc = C.FailureClass.from_symptom(symptom)
        return C.FailedTool(candidate=cand, failure=fc, detail=detail + f" → move={fc.move}")

    def _write_shape_ok(self, cand: C.CandidateTool) -> tuple[bool, str]:
        """SCHEMA: ¿la write declara un payload coherente? POST/PUT/PATCH exigen un cuerpo
        (sample_call.body no vacío) o un input_schema con properties; DELETE se identifica
        por el path (cuerpo opcional). Puro estático: no toca red, no muta nada."""
        method = (cand.method or "").upper()
        if method not in _WRITE_METHODS:
            return False, f"método {method!r} no es de escritura"
        if method in _BODYLESS_WRITE:
            return True, "delete por path (sin cuerpo)"
        sample = (cand.input_schema or {}).get("x-sample-call") or {}
        body = sample.get("body")
        has_body = isinstance(body, dict) and len(body) > 0
        props = ((cand.input_schema or {}).get("properties") or {})
        has_props = isinstance(props, dict) and len(props) > 0
        if has_body or has_props:
            return True, "cuerpo declarado"
        return False, f"{method} sin cuerpo ni properties declaradas"

    def _try_dry_run(self, base: str, cand: C.CandidateTool):
        """DRY-RUN opt-in: la candidata declara `x-dry-run.validate_path` → un endpoint de
        VALIDACIÓN que se prueba con GET (no muta). Si responde 2xx con forma → VerifiedTool
        verified_by='dry-run'. Si no hay declaración o no valida → None (cae a OPTIONS).
        SSRF-guardado igual que OPTIONS."""
        dr = (cand.input_schema or {}).get("x-dry-run")
        if not isinstance(dr, dict):
            return None
        vpath = dr.get("validate_path")
        if not vpath:
            return None
        url = base.rstrip("/") + vpath
        verdict = self._guard.check(url)
        if not getattr(verdict, "allowed", False):
            return None
        res = self._http.get(url, dr.get("query") or {})
        if res.ok and res.has_shape:
            return C.VerifiedTool(candidate=cand, verified_by="dry-run",
                                  sample_response=(res.text or "")[:_SNIPPET])
        return None

    # ── el veredicto del candado → "verified" | símbolo §5 ─────────────────────
    def _judge(self, res: HttpResult) -> str:
        if res.ok:
            # ERROR EN BANDA primero (APIs que 200ean todo, p.ej. Alpha Vantage):
            # un body que es SOLO error/aviso NO es una tool — es un fallo disfrazado.
            soft = self._soft_envelope(res.json)
            if soft == "error":
                return "404"             # función/param inexistente → NOT_FOUND (la alucinación cae acá)
            if soft == "notice":
                return "timeout_5xx"     # rate-limit / premium-only → transitorio
            if res.has_shape:
                return "verified"
            return "200_schema"          # 200 hueco / forma ausente → SCHEMA_MISMATCH
        if res.status == 404:
            return "404"
        if res.status == 400 or res.status == 422:
            return "400"
        if res.status in (401, 403):
            return "401_403"
        if res.status == 0 or res.status >= 500 or res.status == 429:
            return "timeout_5xx"
        return "400"                     # otro 4xx inesperado → re-sintetizar shape

    # ── minería de la respuesta de un read VERIFICADO → FRONTIER ───────────────
    def _mine(self, cand: C.CandidateTool, res: HttpResult, base: str) -> list[C.FrontierLead]:
        leads: list[C.FrontierLead] = []
        body = res.json
        root = _resource_root(cand.endpoint)   # "/movie/popular" → "/movie"
        base_path = _path_of(base)             # ".../3" → "/3" (a recortar de los leads)

        # 1 · PAGINACIÓN (pegable, exacta): hay más páginas → siguiente. El lead es
        #     RELATIVO al base_url (le quitamos el prefijo del base para no duplicarlo).
        if isinstance(body, dict):
            page = _as_int(body.get("page"))
            total = _as_int(body.get("total_pages"))
            if page and total and page < total:
                rel = _strip_prefix(_path_of(res.url_redacted.split("?")[0]), base_path)
                leads.append(C.FrontierLead(
                    hint=rel + f"?page={page + 1}",
                    kind="pagination", source_tool=cand.name))

        # 2 · SUB-RECURSOS por id (pegable, genérico): item de lista → detalle.
        for rid in _collect_ids(body)[:_MAX_FRONTIER_PER_TOOL]:
            if root:
                leads.append(C.FrontierLead(
                    hint=f"{root}/{rid}", kind="subresource", source_tool=cand.name))
        return leads


# ── helpers de forma (genéricos, NO TMDB-específicos) ───────────────────────────
def _query_of(cand: C.CandidateTool) -> dict:
    sample = (cand.input_schema or {}).get("x-sample-call") or {}
    q = sample.get("query") or {}
    return {k: v for k, v in q.items() if v not in (None, "")} if isinstance(q, dict) else {}


def _resource_root(endpoint: str) -> str:
    segs = [s for s in (endpoint or "").split("/") if s and not s.startswith("{")]
    return "/" + segs[0] if segs else ""


def _path_of(url: str) -> str:
    from urllib.parse import urlparse
    return urlparse(url).path or url


def _strip_prefix(path: str, prefix: str) -> str:
    """Quita el prefijo del base_url de un path absoluto → endpoint relativo."""
    if prefix and prefix != "/" and path.startswith(prefix):
        rel = path[len(prefix):]
        return rel if rel.startswith("/") else "/" + rel
    return path


def _as_int(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _collect_ids(body: Any) -> list[Any]:
    """IDs de items de lista (results[].id / items[].id / lista de dicts con id).
    Genérico: no asume nombres TMDB; solo busca colecciones de objetos con `id`."""
    ids: list[Any] = []
    if isinstance(body, dict):
        for key in ("results", "items", "data", "parts", "cast", "crew"):
            arr = body.get(key)
            if isinstance(arr, list):
                for el in arr:
                    if isinstance(el, dict) and _is_idish(el.get("id")):
                        ids.append(el["id"])
    elif isinstance(body, list):
        for el in body:
            if isinstance(el, dict) and _is_idish(el.get("id")):
                ids.append(el["id"])
    # dedup preservando orden
    seen, out = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def _is_idish(v: Any) -> bool:
    return isinstance(v, int) or (isinstance(v, str) and v.isdigit())


def _dedup_frontier(leads: list[C.FrontierLead]) -> list[C.FrontierLead]:
    seen, out = set(), []
    for ld in leads:
        if ld.hint not in seen:
            seen.add(ld.hint)
            out.append(ld)
    return out
