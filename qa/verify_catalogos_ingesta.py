#!/usr/bin/env python3
"""Vara viva: corpus real del registro → entradas limpias con contrato exacto.

══ [H7 · 2026-08-08] POR QUÉ ESTABA ROJA EN MAIN, Y POR QUÉ NO ERA UN BUG ═══════════════
Medida sobre main @ 1242dba, esta vara moría con un traceback crudo:

    AssertionError: rechazo inesperado para ac.tandem/docs-mcp:
    [{'veredicto': 'no_confiable', 'causa': 'sin_prueba_de_origen'}]

Es una vara **VIVA**: `calibration.fetch_latest()` va al registro MCP real por red. Su
invariante era «si un candidato pasa el corte de score, `clean_ranked` lo acepta» — y eso
no es cierto contra un mundo que se mueve: el corte mide PARECIDO al producto, y
`sin_prueba_de_origen` mide PROCEDENCIA. Son dos filtros distintos. `ac.tandem/docs-mcp`
apareció en el registro pareciéndose lo suficiente y sin prueba de origen: el filtro
haciendo exactamente su trabajo.

El arreglo NO es aflojar la aserción, es distinguir dos cosas que estaban juntas:
  · rechazo con causa **declarada** por el router (`CAUSE_UNPROVEN`) → se CUENTA y se
    reporta en el veredicto. Es el producto funcionando.
  · rechazo con causa que el router no declara → sigue siendo `AssertionError`. Ahí sí
    hay algo que nadie previó.
Y para que no vuelva a ser un verde barato: si la procedencia se come a la mayoría, la
vara se pone roja. Un filtro que no deja pasar casi nada tampoco está bien.

  ══ LO QUE ESE GUARD DESTAPÓ — Y POR QUÉ ESTA VARA SIGUE ROJA ═══════════════════════
  Con los dos contadores puestos, la corrida completa contra el registro vivo midió:

      16.782 sin prueba de origen  +  1.843 no oficiales   vs   5 entradas limpias

  O sea **5 de 18.630**. El traceback de `ac.tandem/docs-mcp` no era «apareció un
  candidato nuevo»: era el PRIMERO de dieciséis mil. Sin el guard, contar los rechazos
  declarados habría dejado esta vara en VERDE midiendo cinco entradas y llamando
  «funcionando» a un filtro que descarta el 99,97 % del corpus.

  Eso ya no es higiene de varas: es una pregunta de producto —¿el filtro de procedencia
  se rompió, o el registro MCP público se llenó de servidores sin verificar?— y se
  contesta midiendo `catalog_ingest_router`, no tocando esta vara. **Queda DECLARADA
  fuera de la Fase 1**, roja y con el número a la vista en vez de un traceback en el
  primer caso. Lo que sí se arregló acá: la vara ya no escribe en el árbol (H2), su
  rojo dice QUÉ pasó, y el guard impide que alguien la «arregle» aflojándola.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _path in (_ROOT / "platform", _ROOT / "product" / "backend", _ROOT / "qa"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import calibrar_registro_scores as calibration  # noqa: E402
from app.phase1 import catalog_ingest_router as ingest  # noqa: E402
from inspection import mcp_matcher, mcp_registry  # noqa: E402

_OFFICIAL_META = "io.modelcontextprotocol.registry/official"
_NON_LATIN = re.compile(r"[\uac00-\ud7af\u3040-\u30ff\u3400-\u9fff]")


def _visible(entry: dict) -> str:
    return json.dumps({
        "nombre": entry["nombre"],
        "descripcion_1linea": entry["descripcion_1linea"],
        "checklist": entry["checklist"],
    }, ensure_ascii=False)


def verify(raw_entries: list[dict], pages: int) -> dict:
    cleaned: list[dict] = []
    rejected_by_cut = 0
    without_runnable_form = 0
    inactive = 0
    not_latest = 0
    without_product_identity = 0
    #: [H7] rechazos con la causa que el router DECLARA (`sin_prueba_de_origen`). No son
    #: sorpresas: son el filtro de procedencia trabajando sobre un registro vivo.
    sin_prueba_de_origen: list[str] = []
    #: [H7] aceptados por el router pero NO como oficiales: entran como comunidad. Esta
    #: vara mide el corpus oficial, así que quedan afuera contados, no rompen.
    sin_procedencia_oficial: list[str] = []
    measured_scores: list[float] = []
    for raw in raw_entries:
        meta = ((raw.get("_meta") or {}).get(_OFFICIAL_META)) or {}
        if meta.get("status") != "active":
            inactive += 1
            continue
        if not meta.get("isLatest"):
            not_latest += 1
            continue
        candidate = mcp_registry._candidate(raw)  # type: ignore[attr-defined]
        if candidate is None:
            continue
        if candidate.get("vendor_kind") not in {"dns", "github_org"}:
            continue
        query = calibration._product_query(candidate)  # type: ignore[attr-defined]
        if not query:
            without_product_identity += 1
            continue
        scored = mcp_matcher.score_candidate(query, candidate)
        measured_scores.append(float(scored["score"]))
        if float(scored["score"]) < ingest.OFFICIAL_MIN_SCORE:
            rejected_by_cut += 1
            continue
        if ingest._classify_type(candidate) is None:
            without_runnable_form += 1
            continue
        accepted, rejected = ingest.clean_ranked(query, [scored])
        if rejected:
            # El corte mide PARECIDO; la procedencia se mide aparte. Pasar uno no promete
            # el otro. Una causa declarada se cuenta; una que nadie declaró sigue rompiendo.
            causas = {r.get("causa") for r in rejected}
            if causas == {ingest.CAUSE_UNPROVEN}:
                sin_prueba_de_origen.append(str(candidate.get("name")))
                continue
            raise AssertionError(
                f"rechazo con causa NO declarada para {candidate.get('name')}: {rejected}")
        if len(accepted) != 1 or not ingest.valid_entry(accepted[0]):
            raise AssertionError(f"schema inválido para {candidate.get('name')}")
        if accepted[0]["official"] is not True:
            # [H7] La MISMA lección, del otro lado del `if`: el router puede ACEPTAR un
            # candidato sin marcarlo oficial (entra como comunidad). Medido el 2026-08-08:
            # `agency.goji/goji`. Esta vara verifica el corpus OFICIAL, así que ése no es
            # su objeto: se cuenta y se sale. No es un bug — es procedencia, otra vez.
            sin_procedencia_oficial.append(str(candidate.get("name")))
            continue
        visible = _visible(accepted[0])
        if ingest._RAW_JARGON.search(visible):
            raise AssertionError(f"jerga cruda visible en {candidate.get('name')}: {visible}")
        if _NON_LATIN.search(visible):
            raise AssertionError(f"escritura sin normalizar en {candidate.get('name')}: {visible}")
        cleaned.append(accepted[0])

    if not cleaned:
        raise AssertionError("el corpus real no produjo entradas limpias")
    # [H7] El corolario del arreglo: contar las exclusiones por procedencia NO puede
    # volverse una excusa para que no pase nadie. Si se comen a la mayoría, es rojo — una
    # vara que excluye su objeto hasta quedarse sin nada que medir es un verde mentiroso.
    _por_procedencia = sin_prueba_de_origen + sin_procedencia_oficial
    if len(_por_procedencia) > len(cleaned):
        raise AssertionError(
            f"ROJO · el filtro de procedencia dejó afuera a la mayoría del corpus: "
            f"{len(sin_prueba_de_origen)} sin prueba de origen + "
            f"{len(sin_procedencia_oficial)} no oficiales vs {len(cleaned)} limpias "
            f"({100 * len(cleaned) / max(1, len(cleaned) + len(_por_procedencia)):.2f}% pasa). "
            f"Primeros: {_por_procedencia[:5]}. "
            f"Esto NO se arregla en la vara: se mide `catalog_ingest_router` "
            f"(¿filtro roto o registro lleno de servidores sin verificar?)")
    if rejected_by_cut:
        raise AssertionError(
            f"el corte {ingest.OFFICIAL_MIN_SCORE} dejó afuera "
            f"{rejected_by_cut} official medidos"
        )
    if any(set(entry) != ingest.ENTRY_KEYS for entry in cleaned):
        raise AssertionError("una entrada agregó o perdió claves del contrato")
    return {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "source": "https://registry.modelcontextprotocol.io/v0/servers?version=latest",
        "pages": pages,
        "raw_entries": len(raw_entries),
        "inactive": inactive,
        "not_latest": not_latest,
        "without_product_identity": without_product_identity,
        "official_without_runnable_form": without_runnable_form,
        "sin_prueba_de_origen": sin_prueba_de_origen,
        "sin_procedencia_oficial": sin_procedencia_oficial,
        "clean_entries": len(cleaned),
        "schema_keys": sorted(ingest.ENTRY_KEYS),
        "official_cut": ingest.OFFICIAL_MIN_SCORE,
        "community_cut": ingest.COMMUNITY_MIN_SCORE,
        "official_product_score_min": min(measured_scores) if measured_scores else None,
        "official_product_score_max": max(measured_scores) if measured_scores else None,
        "raw_jargon_visible_matches": 0,
        "non_latin_visible_matches": 0,
        "sample": cleaned[:12],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-entries", type=int)
    # [H2] Los dos destinos por defecto eran archivos COMMITEADOS
    # (`reports/step5/registro-{limpio,calibracion}.json`): correr la vara los reescribía
    # con la medición del día y ensuciaba el `git status`. Ahora van a un temporal, y
    # actualizar el reporte del árbol es un acto explícito.
    _tmp = Path(tempfile.gettempdir())
    parser.add_argument("--al-arbol", action="store_true",
                        help="escribir los reportes en reports/step5/ (acto explícito)")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--calibration-output", type=Path, default=None)
    args = parser.parse_args()
    _dir = (_ROOT / "reports" / "step5") if args.al_arbol else _tmp
    if args.output is None:
        args.output = _dir / f"registro-limpio{'' if args.al_arbol else f'-{os.getpid()}'}.json"
    if args.calibration_output is None:
        args.calibration_output = _dir / (
            f"registro-calibracion{'' if args.al_arbol else f'-{os.getpid()}'}.json")
    raw, pages = calibration.fetch_latest(
        page_size=100,
        timeout=20,
        max_entries=args.max_entries,
    )
    measured = calibration.calibrate(raw, pages=pages, page_size=100)
    measured_cut = measured["calibration"]["official_recommended_cutoff"]
    if measured_cut != ingest.OFFICIAL_MIN_SCORE:
        raise AssertionError(
            f"el corte productivo {ingest.OFFICIAL_MIN_SCORE} no coincide con "
            f"la medición viva {measured_cut}"
        )
    args.calibration_output.parent.mkdir(parents=True, exist_ok=True)
    args.calibration_output.write_text(
        json.dumps(measured, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    result = verify(raw, pages)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _proc = result["sin_prueba_de_origen"] + result["sin_procedencia_oficial"]
    print(
        "VERDE · "
        f"{result['raw_entries']} manifests reales → "
        f"{result['clean_entries']} entradas limpias · "
        "schema exacto · jerga visible 0"
        + (f" · {len(_proc)} afuera por procedencia declarada "
           f"({', '.join(_proc[:3])})" if _proc else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
