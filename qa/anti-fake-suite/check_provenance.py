#!/usr/bin/env python3
"""
check_provenance.py — Auditor de PROCEDENCIA de eventos de Puppet AI.

EL DETECTOR. El anti-norte del founder prohíbe el fake-live: widgets/eventos que
NO nacen de corridas reales (el falso-verde de 0009 fue un smoke con payload a
mano). Este auditor decide, sobre un events.jsonl, si los eventos tienen huellas
de haber salido de tool-calls REALMENTE ejecutados, o si fueron escritos a mano.

Formato de entrada (el real: product/workshop/widgets/fixtures/events-real.jsonl):
  línea 0  → {"_meta": {"generated_at", "generator", "source", "runs": [...]}}
  línea N  → {"kind":"tool_call","tool","tool_raw","verb_human","args",
              "result","status","ts":<epoch ms>,"run"}

Tolera también el formato de sesión (session.py events.jsonl): eventos con
"type" en {belt_ready, turn_started, tool_call_started, tool_call_finished,
final, closed} y "ts" en segundos float. Se normaliza a tool-calls.

SEÑALES de autenticidad (cada una vota AUTÉNTICO / SOSPECHOSO / N/A):

  S1  meta_provenance   — _meta presente con generator + source + comando
                          reproducible por corrida (campo "command").
  S2  ids_coherentes    — ids/runs coherentes: cada evento referencia un run
                          declarado en _meta; (sesión) call_id hex de 12, un
                          started por cada finished, session_id estable.
  S3  ts_monotonicos    — timestamps monótonos no-decrecientes Y *no* perfectamente
                          espaciados de punta a punta (el fake usa grilla regular;
                          lo real tiene jitter de wall-clock). Salto entre runs OK.
  S4  echo_consistente  — el server echo DEVUELVE SU INPUT: result == args.text.
                          Si rompe, el "result" fue inventado.
  S5  edgar_formato     — accession_number con formato SEC válido
                          (10-2-6 dígitos), CIK consistente, y si hay red:
                          se verifica contra data.sec.gov que el accession existe.
  S6  result_vs_server  — el result corresponde a la SHAPE del server: excel
                          devuelve JSON con range/cells o "Data written"; edgar
                          devuelve {"success":true,...}; echo devuelve texto plano.
  S7  correlacion       — (sesión) started→finished por call_id; (widget) cada
                          tool-call tiene su run en _meta.runs y n_events cuadra.
  S8  artefacto_vs_registro — [Gate 4 · Fase 2 · 2.5] con `--artifact`: lo que el
                          ARTEFACTO dice de sí mismo (model_final, ok, degraded,
                          tool_calls, tools, capture_quality) se RE-DERIVA de este
                          events.jsonl con el resolver del producto, y su
                          content_sha256 se recalcula. Señal de HECHO: no juzga la
                          forma del registro, cruza dos fuentes independientes.
                          N/A sin `--artifact` (el comportamiento de siempre).

Veredicto global: AUTÉNTICO si NINGUNA señal vota SOSPECHOSO. SOSPECHOSO si ≥1
vota en contra; se listan TODAS las razones. (Para la prueba de fuego el fake
debe disparar ≥2.)

Uso:
    python3 check_provenance.py <events.jsonl> [--net] [--json] [--artifact RUTA]
    --net       habilita la verificación online del accession contra data.sec.gov
    --json      emite el reporte como JSON (para tests); por defecto, texto humano.
    --artifact  archivo del almacén (sesión o artefacto suelto) → activa S8.

QUIÉN LO INVOCA: `qa/verify_procedencia_runner.py` — o sea, el carril de varas
(`qa/correr_varas.py` descubre todo `verify_*.py`). Hasta 2.5 este auditor
existía, discriminaba, y no lo corría NADIE.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


# ── formato SEC: accession 0001140361-26-023363 ──────────────────────────────
ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")
HEX12_RE = re.compile(r"^[0-9a-f]{12}$")
# [Gate 4 · Fase 2] Las TRES familias de call_id que los emisores REALES producen —
# medido: la vara de Fase 2 corrió un turno real vía cerebro BYO-CLI y este auditor
# lo acusó de falso porque sólo aceptaba hex-12 (el id propio del assembler). Un
# auditor que grita lobo ante lo real queda muerto. Familias: hex-12 (assembler) ·
# `call_…` (estilo OpenAI function-calling: shim CLI y proveedores compatibles) ·
# `toolu_…` (estilo Anthropic tool_use). Cualquier otra cosa sigue siendo sospechosa.
CALL_ID_RE = re.compile(r"^(?:[0-9a-f]{12}|call_[A-Za-z0-9_-]{8,}|toolu_[A-Za-z0-9_-]{8,})$")


@dataclass
class SignalResult:
    name: str
    verdict: str  # "AUTÉNTICO" | "SOSPECHOSO" | "N/A"
    reasons: list[str] = field(default_factory=list)

    @property
    def suspicious(self) -> bool:
        return self.verdict == "SOSPECHOSO"


# ── carga / normalización ─────────────────────────────────────────────────────

def load_jsonl(path: Path) -> tuple[Optional[dict], list[dict]]:
    """Devuelve (_meta_o_None, [eventos]). Acepta widget y sesión."""
    meta: Optional[dict] = None
    events: list[dict] = []
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    for ln, line in enumerate(raw_lines):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"línea {ln+1} no es JSON válido: {e}") from e
        if "_meta" in obj and ln == 0:
            meta = obj["_meta"]
            continue
        events.append(obj)
    return meta, events


def is_session_format(events: list[dict]) -> bool:
    return any("type" in e for e in events)


# ── S1 — meta_provenance ──────────────────────────────────────────────────────

def sig_meta_provenance(meta: Optional[dict], session: bool) -> SignalResult:
    s = SignalResult("S1 meta_provenance", "AUTÉNTICO")
    if session:
        # el events.jsonl de sesión no lleva _meta; la procedencia la da el
        # propio stream (belt_ready/closed). No es señal en contra: N/A.
        s.verdict = "N/A"
        s.reasons.append("formato sesión: sin _meta (procedencia = stream belt_ready→closed)")
        return s
    if not meta:
        s.verdict = "SOSPECHOSO"
        s.reasons.append("falta el header _meta de procedencia (línea 0)")
        return s
    missing = [k for k in ("generator", "source", "runs") if not meta.get(k)]
    if missing:
        s.verdict = "SOSPECHOSO"
        s.reasons.append(f"_meta sin campos de procedencia: {missing}")
    runs = meta.get("runs", []) or []
    no_cmd = [r.get("run", "?") for r in runs if not r.get("command")]
    if no_cmd:
        s.verdict = "SOSPECHOSO"
        s.reasons.append(f"corridas sin comando reproducible: {no_cmd}")
    # el source debe afirmar procedencia real (huella declarativa, no probatoria)
    src = (meta.get("source") or "").lower()
    if runs and "a mano" not in src and "run_once" not in src and "real" not in src:
        s.reasons.append("source no declara procedencia de corrida real (débil, no bloqueante)")
    if s.verdict == "AUTÉNTICO":
        s.reasons.append(f"_meta OK: generator={meta.get('generator')!r}, {len(runs)} corrida(s) con comando")
    return s


# ── S2 — ids_coherentes ───────────────────────────────────────────────────────

def sig_ids(meta: Optional[dict], events: list[dict], session: bool) -> SignalResult:
    s = SignalResult("S2 ids_coherentes", "AUTÉNTICO")
    if session:
        # session_id estable + call_id hex de 12 + un started por finished
        sids = {e.get("session_id") for e in events if "session_id" in e}
        bad_sid = [x for x in sids if not isinstance(x, str) or not HEX12_RE.match(x or "")]
        if bad_sid:
            s.verdict = "SOSPECHOSO"
            s.reasons.append(f"session_id no es hex-12: {bad_sid}")
        cids = [e.get("call_id") for e in events if e.get("type", "").startswith("tool_call")]
        bad_cid = [c for c in cids if not (isinstance(c, str) and CALL_ID_RE.match(c))]
        if bad_cid:
            s.verdict = "SOSPECHOSO"
            s.reasons.append(f"call_id fuera de las familias reales (hex-12 · call_… · toolu_…): {bad_cid}")
        if s.verdict == "AUTÉNTICO":
            s.reasons.append(f"session_id(s)={sorted(sids)} y call_ids de familia real OK")
        return s
    # widget: cada evento referencia un run declarado en _meta.runs
    declared = {r.get("run") for r in (meta.get("runs", []) if meta else [])}
    used = {e.get("run") for e in events if e.get("kind") == "tool_call"}
    orphan = sorted(u for u in used if u not in declared)
    if orphan:
        s.verdict = "SOSPECHOSO"
        s.reasons.append(f"eventos referencian runs NO declarados en _meta: {orphan}")
    # n_events declarado debe cuadrar con eventos por run
    if meta:
        per_run: dict[str, int] = {}
        for e in events:
            if e.get("kind") == "tool_call":
                per_run[e.get("run")] = per_run.get(e.get("run"), 0) + 1
        for r in meta.get("runs", []):
            rid = r.get("run")
            decl = r.get("n_events")
            got = per_run.get(rid, 0)
            if decl is not None and decl != got:
                s.verdict = "SOSPECHOSO"
                s.reasons.append(f"run {rid}: _meta declara n_events={decl} pero hay {got} eventos")
    if s.verdict == "AUTÉNTICO":
        s.reasons.append(f"todos los eventos referencian runs declarados ({sorted(used)}) y n_events cuadra")
    return s


# ── S3 — ts_monotonicos ───────────────────────────────────────────────────────

def _norm_ts(e: dict) -> Optional[float]:
    ts = e.get("ts")
    if ts is None:
        return None
    # widget: epoch ms (int grande); sesión: epoch s (float). Normalizamos a seg.
    if isinstance(ts, (int, float)) and ts > 1e11:  # > ~año 2001 en ms
        return ts / 1000.0
    return float(ts)


def sig_ts(events: list[dict], session: bool) -> SignalResult:
    s = SignalResult("S3 ts_monotonicos", "AUTÉNTICO")
    tss = [_norm_ts(e) for e in events]
    tss = [t for t in tss if t is not None]
    if len(tss) < 2:
        s.verdict = "N/A"
        s.reasons.append("menos de 2 timestamps: no se evalúa monotonía")
        return s
    # monotonía no-decreciente
    drops = [(i, tss[i - 1], tss[i]) for i in range(1, len(tss)) if tss[i] < tss[i - 1]]
    if drops:
        s.verdict = "SOSPECHOSO"
        s.reasons.append(f"timestamps NO monótonos: {len(drops)} retroceso(s), p.ej. {drops[0]}")

    # detección de grilla perfecta: deltas DENTRO de cada run/sesión.
    # lo real tiene jitter de wall-clock; el fake suele usar paso fijo.
    groups: dict[Any, list[float]] = {}
    for e, t in zip(events, [_norm_ts(e) for e in events]):
        if t is None:
            continue
        key = e.get("run") or e.get("session_id") or "_all"
        groups.setdefault(key, []).append(t)
    grid_runs = []
    for key, arr in groups.items():
        if len(arr) < 3:
            continue
        deltas = [round(arr[i] - arr[i - 1], 6) for i in range(1, len(arr))]
        # consecutivos por construcción del widget (ts = base+i) son delta=0.001s
        # eso NO es grilla sospechosa (es el aplanado de un mismo t0). La grilla
        # sospechosa es paso fijo GRANDE y uniforme (segundos perfectos).
        uniq = set(deltas)
        if len(uniq) == 1 and next(iter(uniq)) >= 1.0:
            grid_runs.append((key, next(iter(uniq))))
    if grid_runs:
        s.verdict = "SOSPECHOSO"
        for key, step in grid_runs:
            s.reasons.append(
                f"run/sesión {key!r}: deltas PERFECTAMENTE espaciados ({step}s constante) "
                f"— huella de ts escritos a mano, no de wall-clock real"
            )
    if s.verdict == "AUTÉNTICO":
        s.reasons.append(f"{len(tss)} timestamps monótonos con jitter de wall-clock (sin grilla perfecta)")
    return s


# ── S4 — echo_consistente ─────────────────────────────────────────────────────

def _tool_calls(events: list[dict], session: bool) -> list[dict]:
    """Normaliza a [{tool, tool_raw, args, result, run}]."""
    out = []
    if not session:
        for e in events:
            if e.get("kind") == "tool_call":
                out.append({
                    "tool": e.get("tool"),
                    "tool_raw": e.get("tool_raw"),
                    "args": e.get("args"),
                    "result": e.get("result"),
                    "run": e.get("run"),
                })
        return out
    # sesión: emparejar started/finished por call_id
    started: dict[str, dict] = {}
    for e in events:
        t = e.get("type", "")
        if t == "tool_call_started":
            started[e.get("call_id")] = e
        elif t == "tool_call_finished":
            cid = e.get("call_id")
            st = started.get(cid, {})
            args = st.get("args")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    pass
            out.append({
                "tool": e.get("tool"),
                "tool_raw": e.get("tool"),
                "args": args,
                "result": e.get("result"),
                "run": e.get("session_id"),
            })
    return out


def sig_echo(calls: list[dict]) -> SignalResult:
    s = SignalResult("S4 echo_consistente", "AUTÉNTICO")
    echo_calls = [c for c in calls if (c.get("tool") == "echo" or c.get("tool_raw") == "echo")]
    if not echo_calls:
        s.verdict = "N/A"
        s.reasons.append("no hay tool-calls de echo")
        return s
    checked = 0
    for c in echo_calls:
        args = c.get("args") or {}
        inp = args.get("text") if isinstance(args, dict) else None
        res = c.get("result")
        if inp is None:
            s.reasons.append("echo sin args.text — no verificable")
            continue
        checked += 1
        if (res or "").strip() != str(inp).strip():
            s.verdict = "SOSPECHOSO"
            s.reasons.append(
                f"echo NO devuelve su input: text={inp!r} pero result={res!r} "
                f"(el server echo SIEMPRE devuelve lo que recibe → result inventado)"
            )
    if s.verdict == "AUTÉNTICO" and checked:
        s.reasons.append(f"{checked} echo(s): result == input (el server devuelve su entrada)")
    return s


# ── S5 — edgar_formato (+ red opcional) ───────────────────────────────────────

def _extract_edgar(calls: list[dict]) -> list[dict]:
    """Parsea results de get_recent_filings/get_cik_by_ticker a dicts."""
    parsed = []
    for c in calls:
        if c.get("tool") != "secedgar" and c.get("tool_raw") not in (
            "get_recent_filings", "get_cik_by_ticker", "get_company_info"
        ):
            continue
        res = c.get("result")
        if not isinstance(res, str):
            continue
        # los results reales pueden venir truncados ("…"); parseamos lo que se pueda
        txt = res
        obj = None
        try:
            obj = json.loads(txt)
        except json.JSONDecodeError:
            # extraer accession/cik con regex aunque el JSON esté truncado
            obj = None
        parsed.append({"call": c, "obj": obj, "raw": txt})
    return parsed


def sig_edgar(calls: list[dict], net: bool) -> SignalResult:
    s = SignalResult("S5 edgar_formato", "AUTÉNTICO")
    edgar = _extract_edgar(calls)
    if not edgar:
        s.verdict = "N/A"
        s.reasons.append("no hay tool-calls de SEC EDGAR")
        return s

    # juntar accessions y CIKs de los results
    accessions: list[str] = []
    ciks: set[str] = set()
    declared_cik_arg: set[str] = set()
    for item in edgar:
        c = item["call"]
        args = c.get("args") or {}
        if isinstance(args, dict):
            for k in ("identifier", "cik"):
                if args.get(k):
                    declared_cik_arg.add(str(args[k]).lstrip("0") or "0")
        raw = item["raw"]
        for m in re.findall(r'"accession_number"\s*:\s*"([^"]+)"', raw):
            accessions.append(m)
        for m in re.findall(r'"cik"\s*:\s*"?(\d+)"?', raw):
            ciks.add(m.lstrip("0") or "0")

    if not accessions and not ciks:
        s.verdict = "N/A"
        s.reasons.append("calls de edgar sin accession ni cik parseables (¿result truncado?)")
        return s

    # formato de accession
    bad = [a for a in accessions if not ACCESSION_RE.match(a)]
    if bad:
        s.verdict = "SOSPECHOSO"
        s.reasons.append(f"accession_number con formato SEC INVÁLIDO: {bad}")

    # CIK del result debe casar con el CIK pedido (si lo hubo)
    if declared_cik_arg and ciks:
        mismatch = declared_cik_arg - ciks
        # solo marcamos si NINGÚN cik del result coincide con el pedido
        if declared_cik_arg and not (declared_cik_arg & ciks):
            s.verdict = "SOSPECHOSO"
            s.reasons.append(
                f"CIK incoherente: se pidió {sorted(declared_cik_arg)} "
                f"pero el result trae {sorted(ciks)}"
            )

    # verificación ONLINE (opcional): el accession debe existir en data.sec.gov.
    # Probamos los accessions REPORTADOS contra las filings recientes del CIK.
    # Si TODOS los que probamos están confirmados-ausentes (la SEC respondió 200 y
    # ninguno aparece), es huella fuerte de fake → SOSPECHOSO. Un error de red o
    # HTTP!=200 NO castiga (no concluyente).
    net_note = "red desactivada (--net para verificar contra data.sec.gov)"
    if net and accessions and s.verdict != "SOSPECHOSO":
        cik_for_url = sorted(ciks)[0] if ciks else None
        statuses = []
        notes = []
        # probamos hasta 3 accessions distintos para no martillar la SEC
        for acc in list(dict.fromkeys(accessions))[:3]:
            st, note = _verify_accession_online(acc, cik_for_url)
            statuses.append(st)
            notes.append(note)
        net_note = "; ".join(notes)
        confirmed = [a for a, st in zip(accessions, statuses) if st == "confirmed"]
        absent = [st for st in statuses if st == "absent"]
        any_conclusive = any(st in ("confirmed", "absent") for st in statuses)
        # SOSPECHOSO solo si la red fue concluyente y NINGUNO se confirmó y
        # al menos uno está confirmado-ausente.
        if any_conclusive and not confirmed and absent:
            s.verdict = "SOSPECHOSO"
            s.reasons.append(
                "verificación SEC: ningún accession reportado existe en las filings "
                "del CIK (confirmado-ausente vía data.sec.gov) — accession(s) inventado(s)"
            )
    elif net and accessions:
        net_note = "red activada pero el formato ya falló; no se consulta SEC"

    if s.verdict == "AUTÉNTICO":
        s.reasons.append(
            f"{len(accessions)} accession(s) con formato SEC válido "
            f"(p.ej. {accessions[0] if accessions else '—'}); CIK(s)={sorted(ciks)}; {net_note}"
        )
    else:
        s.reasons.append(net_note)
    return s


def _verify_accession_online(accession: str, cik: Optional[str]) -> tuple[str, str]:
    """Consulta data.sec.gov. Devuelve (status, nota) con status en
    {"confirmed","absent","inconclusive"}."""
    try:
        import requests
    except ImportError:
        return "inconclusive", "red: requests no disponible, no se verificó online"
    if not cik:
        return "inconclusive", "red: sin CIK para la URL de submissions; formato OK, no verificado"
    cik10 = cik.zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{cik10}.json"
    headers = {"User-Agent": "Puppet AI QA anti-fake (contact@example.invalid)"}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            return "inconclusive", f"red: SEC HTTP {r.status_code} para CIK{cik10}; no concluyente"
        data = r.json()
        recent = data.get("filings", {}).get("recent", {})
        accs = set(recent.get("accessionNumber", []))
        if accession in accs:
            return "confirmed", f"red: accession {accession} CONFIRMADO en SEC para CIK{cik10}"
        return "absent", (
            f"red: accession {accession} NO está en las {len(accs)} filings recientes "
            f"de CIK{cik10} (inventado o muy antiguo)"
        )
    except Exception as e:  # noqa: BLE001
        return "inconclusive", f"red: error consultando SEC ({type(e).__name__}: {e}); no concluyente"


# ── S6 — result_vs_server (shape del result según el server) ───────────────────

def sig_result_shape(calls: list[dict]) -> SignalResult:
    s = SignalResult("S6 result_vs_server", "AUTÉNTICO")
    checked = 0
    for c in calls:
        tool = c.get("tool")
        raw = c.get("tool_raw")
        res = c.get("result")
        if res is None:
            continue
        res_s = res if isinstance(res, str) else json.dumps(res)
        low = res_s.lower()

        if tool == "excel" or raw in (
            "create_workbook", "write_data_to_excel", "read_data_from_excel",
            "apply_formula", "create_worksheet", "format_range", "create_table",
        ):
            checked += 1
            if raw == "create_workbook":
                if "created workbook" not in low and "workbook" not in low:
                    s.verdict = "SOSPECHOSO"
                    s.reasons.append(f"create_workbook con result fuera de shape: {res_s[:80]!r}")
            elif raw == "write_data_to_excel":
                if "data written" not in low and "written" not in low:
                    s.verdict = "SOSPECHOSO"
                    s.reasons.append(f"write_data_to_excel sin 'Data written': {res_s[:80]!r}")
            elif raw == "read_data_from_excel":
                # el server real devuelve JSON con range/cells
                if "range" not in low or ("cells" not in low and "value" not in low):
                    s.verdict = "SOSPECHOSO"
                    s.reasons.append(
                        f"read_data_from_excel sin shape JSON range/cells: {res_s[:80]!r}"
                    )

        elif tool == "secedgar" or raw in ("get_cik_by_ticker", "get_recent_filings"):
            checked += 1
            # el server real devuelve {"success": true, ...}
            if '"success"' not in low:
                s.verdict = "SOSPECHOSO"
                s.reasons.append(
                    f"{raw}: result no tiene la shape del server EDGAR "
                    f'(falta "success"): {res_s[:80]!r}'
                )

        elif tool == "echo" or raw == "echo":
            checked += 1  # la consistencia profunda la hace S4; acá solo shape (texto plano)

    if s.verdict == "AUTÉNTICO":
        s.reasons.append(f"{checked} result(s) con la shape esperada de su server")
    return s


# ── S7 — correlacion started→finished / run↔meta ─────────────────────────────

def sig_correlation(meta: Optional[dict], events: list[dict], session: bool) -> SignalResult:
    s = SignalResult("S7 correlacion", "AUTÉNTICO")
    if session:
        started = {e.get("call_id") for e in events if e.get("type") == "tool_call_started"}
        finished = {e.get("call_id") for e in events if e.get("type") == "tool_call_finished"}
        only_started = started - finished
        only_finished = finished - started
        if only_finished:
            s.verdict = "SOSPECHOSO"
            s.reasons.append(f"tool_call_finished SIN su started (inventado): {sorted(only_finished)}")
        if only_started:
            # un started sin finished puede ser una corrida cortada; débil, no bloqueante
            s.reasons.append(f"started sin finished (¿corte?): {sorted(only_started)} (débil)")
        # ORDEN de belt_ready: sólo se juzga cuando el stream LO TRAE. [Gate 4 · Fase 2]
        # La vía run-e2e real NO emite belt_ready (medido en FASE1 §B.bis: la secuencia
        # real fue cost·tool_call_started·…·final·closed, sin belt_ready ni turn_started)
        # — exigirlo acusaba de falso a todo run real de la Sala. Lo que SÍ sigue siendo
        # imposible es un belt_ready DESPUÉS del primer tool_call: eso se mata igual.
        types_order = [e.get("type") for e in events]
        if "tool_call_started" in types_order and "belt_ready" in types_order:
            first_tool = types_order.index("tool_call_started")
            if "belt_ready" not in types_order[:first_tool]:
                s.verdict = "SOSPECHOSO"
                s.reasons.append("belt_ready aparece DESPUÉS del primer tool_call (orden imposible)")
        elif "tool_call_started" in types_order:
            s.reasons.append("sin belt_ready en el stream (la vía run-e2e no lo emite — débil, no bloqueante)")
        if s.verdict == "AUTÉNTICO":
            s.reasons.append(f"{len(finished)} finished, todos con started; orden de belt_ready coherente")
        return s
    # widget: cada run con tool-calls debe estar declarado y marcado ok
    if not meta:
        s.verdict = "N/A"
        s.reasons.append("sin _meta: no se puede correlacionar run↔corrida")
        return s
    runs_by_id = {r.get("run"): r for r in meta.get("runs", [])}
    used_runs = {e.get("run") for e in events if e.get("kind") == "tool_call"}
    for rid in sorted(used_runs):
        r = runs_by_id.get(rid)
        if r is None:
            s.verdict = "SOSPECHOSO"
            s.reasons.append(f"run {rid} con eventos pero SIN entrada en _meta.runs")
            continue
        if r.get("ok") is False:
            s.reasons.append(f"run {rid}: corrida marcada ok=false pero emitió eventos (revisar)")
    if s.verdict == "AUTÉNTICO":
        s.reasons.append(f"cada run con eventos ({sorted(used_runs)}) está declarado en _meta y ok")
    return s


# ── S8 — el ARTEFACTO contra el REGISTRO (señal de HECHO) ────────────────────
# [Gate 4 · Fase 2 · obra 2.5 — deuda D4: «+ señal-de-hecho adicional (hoy 2/7
#  miden hecho)»]
#
# Las 7 señales de arriba juzgan el events.jsonl mirándose a sí mismo: forma, ids,
# tiempos, coherencia. Dos miden un HECHO comprobable contra el mundo (S4: el echo
# devuelve su input; S5 con --net: el accession existe en la SEC). Esta agrega la
# tercera, y es la que el contrato de artefactos hizo posible: **el artefacto
# guarda su identidad adentro, y esa identidad se puede RE-DERIVAR del registro
# firmado**. Si el artefacto dice «modelo X, 3 tools» y el events.jsonl del espacio
# que él mismo referencia dice otra cosa, alguien escribió a mano de un lado.
#
# Es la auto-verificación contra lo vivo de doc-haus (§1.2 del contrato) aplicada
# al revés: no re-verifica el objetivo antes de mutar, re-verifica la AFIRMACIÓN
# antes de creerle. Y no se re-implementa el resolver: se importa el MISMO que el
# borde de escritura usa (platform/artifacts/provenance.py). Un auditor con su
# propia copia del resolver audita su copia, no el producto.


def _import_resolver():
    """El resolver de procedencia del producto, o None si `platform/` no está."""
    root = Path(__file__).resolve().parents[2]
    p = str(root / "platform")
    if p not in sys.path:
        sys.path.insert(0, p)
    try:
        from artifacts import provenance as _prov       # type: ignore
        return _prov
    except Exception:
        return None


def _artifacts_de(obj: Any) -> list[dict]:
    """Acepta un archivo de sesión del almacén (`{artifacts:[…]}`), una lista, o
    un artefacto suelto."""
    if isinstance(obj, dict) and isinstance(obj.get("artifacts"), list):
        return [a for a in obj["artifacts"] if isinstance(a, dict)]
    if isinstance(obj, list):
        return [a for a in obj if isinstance(a, dict)]
    if isinstance(obj, dict):
        return [obj]
    return []


def sig_artifact_vs_events(artifact_path: Optional[Path], events_path: Path) -> SignalResult:
    s = SignalResult("S8 artefacto_vs_registro", "N/A")
    if artifact_path is None:
        s.reasons.append("sin --artifact: no hay artefacto que cruzar contra este registro")
        return s
    try:
        obj = json.loads(Path(artifact_path).read_text(encoding="utf-8"))
    except Exception as e:
        s.verdict = "SOSPECHOSO"
        s.reasons.append(f"no se pudo leer el artefacto: {e}")
        return s

    arts = _artifacts_de(obj)
    if not arts:
        s.reasons.append("el archivo no contiene artefactos")
        return s

    prov_mod = _import_resolver()
    if prov_mod is None:
        s.reasons.append("no se pudo importar platform/artifacts/provenance.py — "
                         "sin el resolver del PRODUCTO no se cruza nada (no se improvisa uno)")
        return s

    resuelto = prov_mod._resolve_events(Path(events_path))
    if resuelto is None:
        s.verdict = "SOSPECHOSO"
        s.reasons.append("el registro no se pudo resolver (vacío/ilegible) y hay artefactos "
                         "que dicen venir de él")
        return s

    import hashlib
    espacio_del_archivo = Path(events_path).parent.name
    cruzados = 0
    for a in arts:
        aid = a.get("id") or "?"
        prov = a.get("provenance")

        # (a) INTEGRIDAD DEL CONTENIDO — un hecho, no una afirmación: el hash que el
        #     almacén estampó tiene que ser el del contenido que hoy está en el archivo.
        got = a.get("content_sha256")
        if isinstance(got, str) and got:
            calc = hashlib.sha256(str(a.get("content") or "").encode("utf-8")).hexdigest()
            cruzados += 1
            if calc != got:
                s.verdict = "SOSPECHOSO"
                s.reasons.append(f"[{aid}] content_sha256 no corresponde al contenido "
                                 f"(guardado {got[:12]}… vs real {calc[:12]}…)")

        if not isinstance(prov, dict):
            # legacy migrado: `provenance: null` ES la confesión honesta del contrato.
            s.reasons.append(f"[{aid}] sin bloque de procedencia (legacy migrado) — no se cruza")
            continue
        if prov.get("space_id") and prov["space_id"] != espacio_del_archivo:
            s.reasons.append(f"[{aid}] referencia otro espacio ({prov['space_id']}) — "
                             f"este registro es de {espacio_del_archivo}; no se cruza")
            continue
        if prov.get("resolved_from") != "events":
            s.reasons.append(f"[{aid}] procedencia declarada (resolved_from="
                             f"{prov.get('resolved_from')!r}) — no afirma hechos del registro")
            continue

        cruzados += 1
        for campo in ("model_final", "ok", "degraded", "tool_calls"):
            if prov.get(campo) != resuelto.get(campo):
                s.verdict = "SOSPECHOSO"
                s.reasons.append(f"[{aid}] {campo}: el artefacto dice {prov.get(campo)!r} y el "
                                 f"registro firmado dice {resuelto.get(campo)!r}")
        if sorted(prov.get("tools") or []) != sorted(resuelto.get("tools") or []):
            s.verdict = "SOSPECHOSO"
            s.reasons.append(f"[{aid}] tools: el artefacto dice {prov.get('tools')} y el "
                             f"registro {resuelto.get('tools')}")
        if prov.get("capture_quality") == "exact" and not resuelto.get("terminal_seen"):
            s.verdict = "SOSPECHOSO"
            s.reasons.append(f"[{aid}] se declara capture_quality=exact y el registro no tiene "
                             f"evento terminal (`closed`): afirma más de lo que el registro sostiene")
        # [Gate 4 · Fase 3 · 3.4 · ley 0] LO NACIDO EN UN STACK HEREDADO JAMÁS ES `exact`.
        # El borde de escritura lo topa en `declared` por construcción
        # (`platform/artifacts/provenance._cap_workspace`): Aleph midió el MODELO del
        # turno, pero la función que escribió el contenido corrió en el proceso del
        # stack, contra las fuentes del stack. Un `exact` acá no lo pudo producir el
        # borde — sólo una edición del JSON a mano. Es exactamente la clase de
        # falsificación que esta señal existe para nombrar.
        if prov.get("produced_by") == "workspace" and prov.get("capture_quality") == "exact":
            s.verdict = "SOSPECHOSO"
            s.reasons.append(
                f"[{aid}] producido por el workspace {prov.get('workspace') or '?'} y se "
                f"declara capture_quality=exact: Aleph no ejecutó esa función, el borde "
                f"topa esto en `declared` — el valor no salió del borde")

    if not cruzados:
        s.reasons.append("ningún artefacto tenía qué cruzar contra este registro")
        return s
    if s.verdict == "N/A":
        s.verdict = "AUTÉNTICO"
        s.reasons.append(f"{cruzados} cruce(s) artefacto↔registro coinciden "
                         f"(modelo, veredicto, conteo de tools, nombres y hash del contenido)")
    return s


# ── orquestación ──────────────────────────────────────────────────────────────

def audit(path: Path, net: bool = False, artifact: Optional[Path] = None) -> dict:
    meta, events = load_jsonl(path)
    session = is_session_format(events)
    calls = _tool_calls(events, session)

    signals = [
        sig_meta_provenance(meta, session),
        sig_ids(meta, events, session),
        sig_ts(events, session),
        sig_echo(calls),
        sig_edgar(calls, net),
        sig_result_shape(calls),
        sig_correlation(meta, events, session),
        sig_artifact_vs_events(artifact, path),
    ]

    suspicious = [s for s in signals if s.suspicious]
    global_verdict = "SOSPECHOSO" if suspicious else "AUTÉNTICO"
    reasons_global = []
    for s in suspicious:
        for r in s.reasons:
            reasons_global.append(f"[{s.name}] {r}")

    return {
        "file": str(path),
        "format": "session" if session else "widget",
        "n_events": len(events),
        "n_tool_calls": len(calls),
        "net": net,
        "signals": [
            {"name": s.name, "verdict": s.verdict, "reasons": s.reasons}
            for s in signals
        ],
        "n_suspicious_signals": len(suspicious),
        "global": global_verdict,
        "global_reasons": reasons_global,
    }


def render_text(report: dict) -> str:
    L = []
    L.append("=" * 72)
    L.append(f"PROCEDENCIA — {report['file']}")
    L.append(f"formato={report['format']}  eventos={report['n_events']}  "
             f"tool_calls={report['n_tool_calls']}  red={'on' if report['net'] else 'off'}")
    L.append("=" * 72)
    for s in report["signals"]:
        mark = {"AUTÉNTICO": "OK ", "SOSPECHOSO": "!! ", "N/A": "-- "}[s["verdict"]]
        L.append(f"[{mark}] {s['name']:22s} → {s['verdict']}")
        for r in s["reasons"]:
            L.append(f"          · {r}")
    L.append("-" * 72)
    g = report["global"]
    L.append(f"VEREDICTO GLOBAL: {g}   "
             f"(señales sospechosas: {report['n_suspicious_signals']})")
    if report["global_reasons"]:
        L.append("RAZONES:")
        for r in report["global_reasons"]:
            L.append(f"  - {r}")
    L.append("=" * 72)
    return "\n".join(L)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Auditor de procedencia de eventos (anti-fake).")
    ap.add_argument("events", help="ruta al events.jsonl")
    ap.add_argument("--net", action="store_true", help="verificar accession contra data.sec.gov")
    ap.add_argument("--json", action="store_true", help="emitir reporte JSON")
    ap.add_argument("--artifact", metavar="RUTA", default=None,
                    help="archivo del almacén de artefactos (sesión o artefacto suelto): "
                         "activa S8, que cruza lo que el artefacto DICE contra este registro")
    args = ap.parse_args(argv)

    path = Path(args.events)
    if not path.exists():
        print(f"ERROR: no existe {path}", file=sys.stderr)
        return 2
    artifact = Path(args.artifact) if args.artifact else None
    if artifact is not None and not artifact.exists():
        print(f"ERROR: no existe {artifact}", file=sys.stderr)
        return 2
    report = audit(path, net=args.net, artifact=artifact)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_text(report))
    # exit code: 0 si AUTÉNTICO, 1 si SOSPECHOSO (para CI)
    return 0 if report["global"] == "AUTÉNTICO" else 1


if __name__ == "__main__":
    sys.exit(main())
