#!/usr/bin/env python3
"""
build_research_artifact.py — produce la MINI-REVIEW CITADA del belt RESEARCH usando los
servers REALES del belt (crossref_server + pysandbox_server) por JSON-RPC stdio. Datos de
literatura: Crossref vivo (DOIs reales). Números: pysandbox (código ejecutado, anti-fab).
Render final: pandoc (.md → .docx). Sin LLM — builder determinista para un artefacto limpio.

Salida → platform/assembler/fixtures/e2e/out/T1-research-belt/ :
         mini-review .md + .docx + evidence.json
"""
import json, subprocess, sys, pathlib, datetime

_FIX = pathlib.Path(__file__).resolve().parents[1]
CROSSREF = _FIX / "crossref_server.py"
PYSANDBOX = _FIX / "pysandbox_server.py"
# Destino local al propio dir de e2e (antes escribía en org/artifacts/, que salió del repo
# con la extracción de Puppet). No trepa a la raíz: el script es autocontenido.
OUT = pathlib.Path(__file__).resolve().parent / "out" / "T1-research-belt"
OUT.mkdir(parents=True, exist_ok=True)


def mcp(server: pathlib.Path, calls: list, env=None) -> list:
    msgs = [{"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}}]
    for i, c in enumerate(calls, 1):
        msgs.append({"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": c})
    inp = "\n".join(json.dumps(m) for m in msgs) + "\n"
    p = subprocess.run([sys.executable, str(server)], input=inp, capture_output=True, text=True, env=env, timeout=60)
    out = {}
    for ln in p.stdout.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            o = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if isinstance(o, dict) and "id" in o and "result" in o:
            r = o["result"]
            if isinstance(r, dict) and r.get("content"):
                try:
                    out[o["id"]] = json.loads(r["content"][0]["text"])
                except (json.JSONDecodeError, KeyError, IndexError):
                    out[o["id"]] = r["content"][0].get("text")
    return out


QUESTION = "¿Cuál es el panorama de la edición de bases (base editing) con CRISPR y qué tan citados están sus trabajos fundamentales?"

# 1) BÚSQUEDA REAL (Crossref vivo) ────────────────────────────────────────────
search = mcp(CROSSREF, [{"name": "search_works", "arguments": {"query": "CRISPR base editing", "rows": 5}}])
results = (search.get(1) or {}).get("results", [])
total_hits = (search.get(1) or {}).get("total_results")

# 2) METADATOS + CONTEO DE CITAS REAL por DOI (get_work vivo) ──────────────────
papers = []
for r in results:
    doi = r.get("doi")
    if not doi:
        continue
    w = mcp(CROSSREF, [{"name": "get_work", "arguments": {"doi": doi}}]).get(1) or {}
    if w.get("found"):
        papers.append({
            "title": w.get("title"), "doi": w.get("doi"), "authors": w.get("authors") or [],
            "year": w.get("year"), "container": w.get("container"), "url": w.get("url"),
            "citations": w.get("referenced_by_count"),
        })

# papers con conteo de citas real (para el cómputo)
cited = [p for p in papers if isinstance(p.get("citations"), int)]
cited.sort(key=lambda p: p["citations"], reverse=True)

# 3) CÓMPUTO REAL en el sandbox (todo número desde código ejecutado) ───────────
counts = [p["citations"] for p in cited]
code = (
    "import statistics as st, json\n"
    f"c = {counts}\n"
    "out = {'n': len(c), 'total': sum(c), 'max': max(c) if c else None,\n"
    "       'mean': round(st.mean(c),2) if c else None,\n"
    "       'median': st.median(c) if c else None}\n"
    "print(json.dumps(out))\n"
)
pyres = mcp(PYSANDBOX, [{"name": "run_python", "arguments": {"code": code}}], env={"PUPPET_WORKDIR": "/tmp"}).get(1) or {}
stats = json.loads(pyres["stdout"]) if pyres.get("ok") and pyres.get("stdout") else {}

# 4) VERIFICAR que el DOI más citado RESUELVE (cita verificada) ────────────────
top = cited[0] if cited else (papers[0] if papers else None)
verify = mcp(CROSSREF, [{"name": "get_work", "arguments": {"doi": top["doi"]}}]).get(1) if top else {}
doi_verified = bool(verify and verify.get("found") and verify.get("doi", "").lower() == (top["doi"].lower() if top else ""))

# 5) MINI-REVIEW CITADA (.md) ─────────────────────────────────────────────────
today = datetime.date(2026, 6, 16).isoformat()

def cite(p):
    auth = ", ".join(p["authors"][:3]) + (" et al." if len(p["authors"]) > 3 else "") if p["authors"] else "—"
    yr = p["year"] or "s.f."
    cont = f" *{p['container']}*." if p.get("container") else ""
    cstr = f" Citado {p['citations']} veces." if isinstance(p.get("citations"), int) else ""
    return f"{auth} ({yr}). {p['title']}.{cont} DOI: [{p['doi']}](https://doi.org/{p['doi']}).{cstr}"

lines = []
lines.append(f"# Mini-review: edición de bases con CRISPR\n")
lines.append(f"_Generada por el belt RESEARCH de Puppet AI — {today}._\n")
lines.append(f"**Pregunta.** {QUESTION}\n")
lines.append("## Hallazgos\n")
lines.append(
    f"Una búsqueda en Crossref para «CRISPR base editing» arroja **{total_hits:,} trabajos** indexados. "
    f"De una muestra de {len(papers)} con metadatos completos, {len(cited)} traen conteo de citas verificable. "
    "Todas las cifras de abajo provienen de código ejecutado en un sandbox Python sobre los conteos "
    "que devuelve la propia API de Crossref — no de una estimación del modelo.\n"
)
if stats:
    lines.append("## Cifras (computadas en sandbox, no estimadas)\n")
    lines.append(f"- Trabajos con citas medibles en la muestra: **{stats.get('n')}**")
    lines.append(f"- Citas totales acumuladas: **{stats.get('total')}**")
    lines.append(f"- Máximo de citas en un solo trabajo: **{stats.get('max')}**")
    lines.append(f"- Promedio de citas: **{stats.get('mean')}**")
    lines.append(f"- Mediana de citas: **{stats.get('median')}**\n")
if top:
    lines.append("## Trabajo más citado de la muestra\n")
    lines.append(f"{cite(top)}\n")
lines.append("## Referencias (todas con DOI verificable)\n")
for i, p in enumerate(cited or papers, 1):
    lines.append(f"{i}. {cite(p)}")
lines.append("")
lines.append("---")
lines.append(
    "\n_Procedencia: literatura vía Crossref MCP (keyless, api.crossref.org en vivo); "
    "cifras vía pysandbox MCP (subproceso aislado, stdlib); render vía pandoc 3.8. "
    "Anti-fabricación: ningún número fue escrito a mano — todos salen de `run_python`._"
)
md = "\n".join(lines)
md_path = OUT / "mini-review-crispr-base-editing.md"
md_path.write_text(md, encoding="utf-8")

# 6) RENDER .docx con pandoc ──────────────────────────────────────────────────
docx_path = OUT / "mini-review-crispr-base-editing.docx"
pd = subprocess.run(["pandoc", str(md_path), "-o", str(docx_path)], capture_output=True, text=True)
docx_ok = docx_path.exists() and docx_path.stat().st_size > 0

# 7) EVIDENCIA ────────────────────────────────────────────────────────────────
evidence = {
    "question": QUESTION,
    "crossref_total_hits": total_hits,
    "papers_sampled": len(papers),
    "papers_with_citations": len(cited),
    "computed_stats_from_sandbox": stats,
    "top_cited": top,
    "top_doi_verified_resolves": doi_verified,
    "artifact_md": str(md_path),
    "artifact_docx": str(docx_path),
    "docx_rendered": docx_ok,
    "pandoc_stderr": pd.stderr.strip() or None,
}
(OUT / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

print(json.dumps(evidence, ensure_ascii=False, indent=2))
print(f"\n.md  bytes: {md_path.stat().st_size}")
print(f".docx bytes: {docx_path.stat().st_size if docx_ok else 0}")
