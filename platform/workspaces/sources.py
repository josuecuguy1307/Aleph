"""sources.py — EL CENSO DE FUENTES DE CADA STACK HEREDADO.
[Gate 4 · Fase 3 · ley 2.ter, sellada 2026-08-08 · ley 0]

POR QUÉ EXISTE — la ley, en una frase: **jamás registro doble.**

Un stack heredado se alimenta solo (ley 0): trae sus propias fuentes de datos, y Aleph
suele tener conectores hacia varias de las MISMAS fuentes públicas en su cinturón. Esa
redundancia **no es un error que haya que unificar**: son dos tuberías con dos trabajos
distintos —la del stack pinta sus paneles, la del cinturón audita artefactos con
provenance— y unificarlas rompería la ley 0 (el stack dejaría de valer sin Aleph).

Lo que sí es un error es que nadie la VEA. Sin este censo:
  · El Cuarto/Conectores ofrecen «conectá X» a alguien que ya lo tiene adentro de su
    workspace, y el usuario arma un conector para nada.
  · El agente recomienda a ciegas en vez de decir la verdad: «tu workspace ya trae X;
    ¿querés ADEMÁS el MCP del cinturón para que YO lo use en artefactos auditados?».

Este archivo es ese inventario, declarado y con evidencia `archivo:línea` del árbol
importado — no una lista de memoria. Cada fila dice qué es (`kind`), si necesita llave, y
dónde vive en el código del stack.

ESTADO HOY: **el catálogo tiene su primer inquilino de verdad — Ciencia.** La Fase 3 lo
estrenó con las 15 fuentes de un stack heredado y la cosecha sacó ese stack entero; el
registro quedó vacío, esperando. Lo llena OpenScience con sus **42 conectores científicos**,
cada uno medido con su `archivo:línea` del árbol importado (`third_party/openscience/`).

POR QUÉ ESTAS 42 FILAS IMPORTAN MÁS QUE LAS 15 ANTERIORES: el cinturón de Aleph alcanza
varias de estas MISMAS fuentes públicas —arXiv, PubMed, Crossref y compañía son destinos
obvios de un conector de investigación—. Sin este censo, el Cuarto le ofrecería al usuario
«conectá arXiv» cuando su workspace de Ciencia ya lo trae adentro, y el agente
recomendaría a ciegas en vez de decir la verdad: «tu workspace ya trae arXiv; ¿querés
ADEMÁS el MCP del cinturón para que YO lo use en artefactos auditados?».

QUÉ NO ES: no es un catálogo de conectores de Aleph, no se equipa, no se ejecuta desde
acá. Es una FOTO declarativa de lo que el stack ya trae, para que las superficies de la
casa dejen de ofrecer lo que ya está puesto.
"""
from __future__ import annotations

from typing import Any

#: Clases de fuente. `data` = alimenta el dominio del stack (ley 0: no se toca).
#: `alert` = destino de salida que configura el usuario, no del proyecto ajeno.
#: `tool` = una PUERTA que el stack expone (un MCP suyo, un CLI suyo). No es una fuente de
#: datos: es una forma de usarlo. Se censa por la misma razón que las fuentes —para que
#: nadie construya por afuera algo que el stack ya trae— y se distingue porque la pregunta
#: que contesta es otra: no «¿ya tengo este dato?» sino «¿ya tengo esta manija?».
KINDS = ("data", "alert", "tool")

# Los 30 packs de jurisdicción son fuentes internas del stack, no conectores que
# Aleph deba ofrecer de nuevo. Cada prompt contiene la jerarquía y URLs oficiales;
# la allowlist técnica que los cerca está en `lib/research.ts:12-55`.
_LEGAL_JURISDICTIONS = (
    "AE", "AU", "AU-NSW", "AU-VIC", "CA", "CA-BC", "CA-ON", "CA-QC", "CH", "DE",
    "EU", "EW", "FR", "HK", "IE", "IN", "NIR", "NL", "NZ", "SCT", "SG", "US",
    "US-CA", "US-DE", "US-FL", "US-IL", "US-MA", "US-NY", "US-TX", "ZA",
)

#: workspace → fuentes que su stack YA TRAE. Cada fila se escribe MIDIENDO el árbol
#: importado: `evidence` es `archivo:línea` del stack, jamás una lista de memoria.
#:
#: **`also_in_belt`** marca las que Aleph TAMBIÉN alcanza desde su cinturón. Las dos
#: quedan y ninguna se apaga: son dos tuberías con dos trabajos distintos —la del stack
#: pinta sus paneles, la del cinturón audita artefactos con provenance— y unificarlas
#: rompería la ley 0. Lo que este campo habilita es DECIRLO en vez de esconderlo.
CATALOG: dict[str, list[dict[str, Any]]] = {
    "legal": [
        {"id": f"jurisdiction-{code.lower()}", "label": f"Jurisdicción {code}", "kind": "data", "key": "none",
         "domains": [], "evidence": f"third_party/dochaus/dochaus/jurisdiction/{code}/prompt.md:1"}
        for code in _LEGAL_JURISDICTIONS
    ] + [
        {"id": "courtlistener", "label": "CourtListener", "kind": "data", "key": "optional",
         "domains": ["www.courtlistener.com"], "evidence": "third_party/dochaus/dochaus/tool/case-law.ts:3-15"},
        {"id": "exa-discovery", "label": "Exa (descubrimiento, no autoridad)", "kind": "data", "key": "optional",
         "domains": ["api.exa.ai"], "evidence": "third_party/dochaus/dochaus/tool/web-search.ts:3-25"},
        {"id": "matter-local", "label": "Matter local y citas verificadas", "kind": "data", "key": "none",
         "domains": [], "evidence": "third_party/dochaus/dochaus/tool/search-document.ts:8-24"},
    ],
    "ciencia": [
        # ── chemistry ─────────────────────────────────────────────────────────
        {"id": "bindingdb", "label": "BindingDB", "kind": "data", "key": "none",
         "domains": ["bindingdb.org", "www.bindingdb.org"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/chemistry/bindingdb.ts:12"},
        {"id": "chebi", "label": "ChEBI", "kind": "data", "key": "none",
         "domains": ["www.ebi.ac.uk"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/chemistry/chebi.ts:10"},
        {"id": "chembl", "label": "ChEMBL", "kind": "data", "key": "none",
         "domains": ["www.ebi.ac.uk"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/chemistry/chembl.ts:10"},
        {"id": "gtopdb", "label": "Guide to Pharmacology", "kind": "data", "key": "none",
         "domains": ["www.guidetopharmacology.org"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/chemistry/gtopdb.ts:10"},
        {"id": "pubchem", "label": "PubChem", "kind": "data", "key": "none",
         "domains": ["pubchem.ncbi.nlm.nih.gov"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/chemistry/pubchem.ts:11"},
        {"id": "surechembl", "label": "SureChEMBL", "kind": "data", "key": "none",
         "domains": ["www.surechembl.org"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/chemistry/surechembl.ts:11"},
        # ── genomics ──────────────────────────────────────────────────────────
        {"id": "clinvar", "label": "ClinVar", "kind": "data", "key": "none",
         "domains": ["www.ncbi.nlm.nih.gov"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/genomics/clinvar.ts:33"},
        {"id": "dbsnp", "label": "dbSNP", "kind": "data", "key": "none",
         "domains": ["www.ncbi.nlm.nih.gov"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/genomics/dbsnp.ts:32"},
        {"id": "ensembl", "label": "Ensembl", "kind": "data", "key": "none",
         "domains": ["rest.ensembl.org", "www.ensembl.org"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/genomics/ensembl.ts:9"},
        {"id": "eutils", "label": "NCBI E-utilities", "kind": "data", "key": "none",
         "domains": ["eutils.ncbi.nlm.nih.gov", "www.ncbi.nlm.nih.gov"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/genomics/eutils.ts:6"},
        {"id": "gnomad", "label": "gnomAD", "kind": "data", "key": "none",
         "domains": ["gnomad.broadinstitute.org"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/genomics/gnomad.ts:9"},
        {"id": "mygene", "label": "MyGene", "kind": "data", "key": "none",
         "domains": ["mygene.info"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/genomics/mygene.ts:9"},
        {"id": "myvariant", "label": "MyVariant", "kind": "data", "key": "none",
         "domains": ["myvariant.info"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/genomics/myvariant.ts:9"},
        {"id": "ncbi-gene", "label": "NCBI Gene", "kind": "data", "key": "none",
         "domains": ["www.ncbi.nlm.nih.gov"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/genomics/ncbi-gene.ts:27"},
        {"id": "ucsc", "label": "UCSC Genome Browser", "kind": "data", "key": "none",
         "domains": ["api.genome.ucsc.edu", "genome.ucsc.edu"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/genomics/ucsc.ts:5"},
        # ── literature ────────────────────────────────────────────────────────
        {"id": "arxiv", "label": "arXiv", "kind": "data", "key": "none",
         "domains": ["arxiv.org", "export.arxiv.org"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/literature/arxiv.ts:12", "also_in_belt": True},
        {"id": "biorxiv", "label": "bioRxiv", "kind": "data", "key": "none",
         "domains": ["api.biorxiv.org", "www.biorxiv.org"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/literature/biorxiv.ts:16"},
        {"id": "crossref", "label": "Crossref", "kind": "data", "key": "none",
         "domains": ["api.crossref.org", "doi.org", "www.crossref.org"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/literature/crossref.ts:12", "also_in_belt": True},
        {"id": "europepmc", "label": "Europe PMC", "kind": "data", "key": "none",
         "domains": ["europepmc.org", "www.ebi.ac.uk"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/literature/europepmc.ts:13"},
        {"id": "openalex", "label": "OpenAlex", "kind": "data", "key": "opcional (OPENALEX_API_KEY)",
         "domains": ["api.openalex.org", "openalex.org"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/literature/openalex.ts:15", "also_in_belt": True},
        {"id": "pubmed", "label": "PubMed", "kind": "data", "key": "none",
         "domains": ["eutils.ncbi.nlm.nih.gov", "pubmed.ncbi.nlm.nih.gov"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/literature/pubmed.ts:13", "also_in_belt": True},
        {"id": "semantic-scholar", "label": "Semantic Scholar", "kind": "data", "key": "opcional (SEMANTIC_SCHOLAR_API_KEY)",
         "domains": ["api.semanticscholar.org", "www.semanticscholar.org"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/literature/semantic-scholar.ts:13", "also_in_belt": True},
        # ── omics ─────────────────────────────────────────────────────────────
        {"id": "arrayexpress", "label": "ArrayExpress", "kind": "data", "key": "none",
         "domains": ["www.ebi.ac.uk"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/omics/arrayexpress.ts:14"},
        {"id": "depmap", "label": "DepMap", "kind": "data", "key": "none",
         "domains": ["depmap.org"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/omics/depmap.ts:19"},
        {"id": "expression-atlas", "label": "Expression Atlas", "kind": "data", "key": "none",
         "domains": ["www.ebi.ac.uk"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/omics/expression-atlas.ts:16"},
        {"id": "geo", "label": "GEO", "kind": "data", "key": "none",
         "domains": ["eutils.ncbi.nlm.nih.gov", "www.ncbi.nlm.nih.gov"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/omics/geo.ts:15"},
        {"id": "gtex", "label": "GTEx", "kind": "data", "key": "none",
         "domains": ["gtexportal.org"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/omics/gtex.ts:15"},
        {"id": "hpa", "label": "Human Protein Atlas", "kind": "data", "key": "none",
         "domains": ["www.proteinatlas.org"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/omics/hpa.ts:14"},
        {"id": "single-cell-atlas", "label": "Single Cell Expression Atlas", "kind": "data", "key": "none",
         "domains": ["www.ebi.ac.uk"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/omics/single-cell-atlas.ts:14"},
        # ── pathways ──────────────────────────────────────────────────────────
        {"id": "biogrid", "label": "BioGRID", "kind": "data", "key": "none",
         "domains": ["thebiogrid.org", "webservice.thebiogrid.org"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/pathways/biogrid.ts:18"},
        {"id": "intact", "label": "IntAct", "kind": "data", "key": "none",
         "domains": ["www.ebi.ac.uk"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/pathways/intact.ts:26"},
        {"id": "kegg", "label": "KEGG", "kind": "data", "key": "none",
         "domains": ["rest.kegg.jp", "www.kegg.jp"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/pathways/kegg.ts:5"},
        {"id": "opentargets", "label": "Open Targets", "kind": "data", "key": "none",
         "domains": ["api.platform.opentargets.org", "platform.opentargets.org"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/pathways/opentargets.ts:17"},
        {"id": "reactome", "label": "Reactome", "kind": "data", "key": "none",
         "domains": ["reactome.org"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/pathways/reactome.ts:20"},
        {"id": "string-db", "label": "STRING", "kind": "data", "key": "none",
         "domains": ["string-db.org"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/pathways/string-db.ts:26"},
        {"id": "wikipathways", "label": "WikiPathways", "kind": "data", "key": "none",
         "domains": ["www.wikipathways.org"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/pathways/wikipathways.ts:23"},
        # ── proteins ──────────────────────────────────────────────────────────
        {"id": "alphafold", "label": "AlphaFold DB", "kind": "data", "key": "none",
         "domains": ["alphafold.ebi.ac.uk"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/proteins/alphafold.ts:4"},
        {"id": "interpro", "label": "InterPro", "kind": "data", "key": "none",
         "domains": ["www.ebi.ac.uk"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/proteins/interpro.ts:5"},
        {"id": "pdbe", "label": "PDBe", "kind": "data", "key": "none",
         "domains": ["www.ebi.ac.uk"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/proteins/pdbe.ts:4"},
        {"id": "rcsb-pdb", "label": "RCSB PDB", "kind": "data", "key": "none",
         "domains": ["data.rcsb.org", "files.rcsb.org", "search.rcsb.org", "www.rcsb.org"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/proteins/rcsb-pdb.ts:4"},
        {"id": "sifts", "label": "SIFTS", "kind": "data", "key": "none",
         "domains": ["www.ebi.ac.uk"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/proteins/sifts.ts:5"},
        {"id": "uniprot", "label": "UniProt", "kind": "data", "key": "none",
         "domains": ["rest.uniprot.org", "www.uniprot.org"],
         "evidence": "third_party/openscience/backend/cli/src/science/connectors/proteins/uniprot.ts:4"},
    ],
    # [Gate 4 · F6-diseño · 2.ter] No son conectores de catálogo: Diseño usa sus
    # archivos y puede traer UNA URL explícita al contexto. La URL conserva su tubería
    # porque compone el diseño; el cinturón también puede fetcharla con provenance.
    "diseno": [
        {"id": "archivos-del-diseno", "label": "Archivos locales del diseño", "kind": "data", "key": "none",
         "domains": [],
         "evidence": "third_party/codesign/apps/desktop/src/main/prompt-context.ts:18"},
        {"id": "url-de-referencia", "label": "URL de referencia elegida", "kind": "data", "key": "none",
         "domains": [], "also_in_belt": True,
         "evidence": "third_party/codesign/apps/desktop/src/main/prompt-context.ts:90"},
    ],
    # Educación no trae una cuenta ni una fuente encendida de fábrica, pero sí conserva
    # estas fuentes OPCIONALES detrás de herramientas del tutor. Se censan para que el
    # Cuarto no las vuelva invisibles ni las ofrezca como si el stack no pudiera usarlas.
    # El modelo no figura aquí: la única fuente de modelo es el borde de Aleph y su perfil
    # custom materializado por el pack, no un conector propio de DeepTutor.
    "educacion": [
        {"id": "brave-search", "label": "Brave Search", "kind": "data",
         "key": "requerida", "domains": ["api.search.brave.com"],
         "evidence": "third_party/deeptutor/deeptutor/services/search/providers/brave.py:16-41"},
        {"id": "duckduckgo", "label": "DuckDuckGo", "kind": "data", "key": "none",
         "domains": ["duckduckgo.com"],
         "evidence": "third_party/deeptutor/deeptutor/services/search/providers/duckduckgo.py:14-66"},
        {"id": "jina-search", "label": "Jina Search/Reader", "kind": "data",
         "key": "opcional", "domains": ["s.jina.ai", "r.jina.ai"],
         "evidence": "third_party/deeptutor/deeptutor/services/search/providers/jina.py:4-77"},
        {"id": "perplexity-search", "label": "Perplexity Search", "kind": "data",
         "key": "requerida", "domains": ["api.perplexity.ai"],
         "evidence": "third_party/deeptutor/deeptutor/services/search/providers/perplexity.py:22-52"},
        {"id": "searxng", "label": "SearXNG (host elegido por dueño)", "kind": "data",
         "key": "none", "domains": [],
         "evidence": "third_party/deeptutor/deeptutor/services/search/providers/searxng.py:18-27"},
        {"id": "serper", "label": "Serper", "kind": "data", "key": "requerida",
         "domains": ["google.serper.dev"],
         "evidence": "third_party/deeptutor/deeptutor/services/search/providers/serper.py:34-86"},
        {"id": "tavily", "label": "Tavily", "kind": "data", "key": "requerida",
         "domains": ["api.tavily.com"],
         "evidence": "third_party/deeptutor/deeptutor/services/search/providers/tavily.py:27-94"},
        {"id": "arxiv", "label": "arXiv", "kind": "data", "key": "none",
         "domains": ["arxiv.org", "export.arxiv.org"],
         "evidence": "third_party/deeptutor/deeptutor/tools/paper_search_tool.py:13-94", "also_in_belt": True},
        {"id": "web-fetch", "label": "Web fetch (URL explícita)", "kind": "data",
         "key": "none", "domains": [],
         "evidence": "third_party/deeptutor/deeptutor/tools/web_fetch.py:72-261"},
        {"id": "github", "label": "GitHub", "kind": "data", "key": "opcional (gh)",
         "domains": ["api.github.com", "github.com"],
         "evidence": "third_party/deeptutor/deeptutor/tools/github_query.py:66-228"},
    ],
    # ── [Gate 4 · F6-FINANZAS] EL SEGUNDO INQUILINO ───────────────────────────
    # Las 23 fuentes de mercado del stack + las 6 no-OHLCV de sus tools. `also_in_belt`
    # marca las TRES que el cinturón de Aleph también alcanza (EDGAR, Yahoo/yfinance,
    # FRED): las dos tuberías quedan y ninguna se apaga — la del stack pinta sus paneles
    # y sus factores PIT-safe, la del cinturón audita artefactos con provenance.
    # Las otras 26 el cinturón NO las tiene, y ése es el argumento más fuerte de la ley 0
    # en este vertical: A-share, HK, KRX, NSE/BSE, cripto spot y perps, forex/metales.
    "finanzas": [
        # ── China A-share ─────────────────────────────────────────────────────
        {"id": "eastmoney", "label": "Eastmoney 东方财富", "kind": "data", "key": "none",
         "domains": ["push2.eastmoney.com", "push2his.eastmoney.com", "datacenter-web.eastmoney.com",
                     "searchapi.eastmoney.com", "reportapi.eastmoney.com", "fundf10.eastmoney.com"],
         "evidence": "third_party/vibetrading/agent/backtest/loaders/eastmoney_loader.py:52"},
        {"id": "mootdx", "label": "mootdx 通达信 (TCP directo)", "kind": "data", "key": "none",
         "domains": [], "evidence": "third_party/vibetrading/agent/backtest/loaders/mootdx_loader.py:3"},
        {"id": "tencent", "label": "Tencent 腾讯财经", "kind": "data", "key": "none",
         "domains": ["web.ifzq.gtimg.cn"], "evidence": "third_party/vibetrading/agent/backtest/loaders/tencent_loader.py:7"},
        {"id": "sina", "label": "Sina 新浪财经", "kind": "data", "key": "none",
         "domains": ["stock.finance.sina.com.cn", "vip.stock.finance.sina.com.cn"],
         "evidence": "third_party/vibetrading/agent/backtest/loaders/sina_loader.py:9"},
        {"id": "akshare", "label": "AKShare", "kind": "data", "key": "none",
         "domains": [], "evidence": "third_party/vibetrading/agent/backtest/loaders/akshare_loader.py:3"},
        {"id": "baostock", "label": "BaoStock (TCP)", "kind": "data", "key": "none",
         "domains": ["baostock.com"], "evidence": "third_party/vibetrading/agent/backtest/loaders/baostock_loader.py:3"},
        {"id": "tushare", "label": "Tushare Pro", "kind": "data", "key": "opcional",
         "domains": ["tushare.pro"], "evidence": "third_party/vibetrading/agent/backtest/loaders/tushare.py:117"},
        {"id": "iwencai", "label": "iWenCai 问财", "kind": "data", "key": "opcional",
         "domains": ["www.iwencai.com"], "evidence": "third_party/vibetrading/agent/src/tools/iwencai_tool.py:1"},
        # ── EE.UU. e internacional ────────────────────────────────────────────
        {"id": "yfinance", "label": "yfinance", "kind": "data", "key": "none", "also_in_belt": True,
         "domains": ["query1.finance.yahoo.com", "query2.finance.yahoo.com", "fc.yahoo.com"],
         "evidence": "third_party/vibetrading/agent/backtest/loaders/yfinance_loader.py:230"},
        {"id": "yahoo", "label": "Yahoo Finance (cliente directo)", "kind": "data", "key": "none",
         "also_in_belt": True, "domains": ["query1.finance.yahoo.com", "query2.finance.yahoo.com"],
         "evidence": "third_party/vibetrading/agent/backtest/loaders/yahoo_loader.py:174"},
        {"id": "stooq", "label": "Stooq (EOD CSV)", "kind": "data", "key": "none",
         "domains": ["stooq.com"], "evidence": "third_party/vibetrading/agent/backtest/loaders/stooq_loader.py:4"},
        {"id": "sec_edgar", "label": "SEC EDGAR", "kind": "data", "key": "none", "also_in_belt": True,
         "domains": ["www.sec.gov", "data.sec.gov", "efts.sec.gov"],
         "evidence": "third_party/vibetrading/agent/backtest/loaders/sec_edgar_client.py:1"},
        {"id": "fred", "label": "FRED (St. Louis Fed)", "kind": "data", "key": "requerida",
         "also_in_belt": True, "domains": ["api.stlouisfed.org"],
         "evidence": "third_party/vibetrading/agent/src/tools/fred_macro_tool.py:33"},
        {"id": "finnhub", "label": "Finnhub", "kind": "data", "key": "requerida",
         "domains": ["finnhub.io"], "evidence": "third_party/vibetrading/agent/backtest/loaders/finnhub_loader.py:3"},
        {"id": "alphavantage", "label": "Alpha Vantage", "kind": "data", "key": "requerida",
         "domains": ["www.alphavantage.co"], "evidence": "third_party/vibetrading/agent/backtest/loaders/alphavantage_loader.py:11"},
        {"id": "tiingo", "label": "Tiingo", "kind": "data", "key": "requerida",
         "domains": ["api.tiingo.com"], "evidence": "third_party/vibetrading/agent/backtest/loaders/tiingo_loader.py:5"},
        {"id": "fmp", "label": "Financial Modeling Prep", "kind": "data", "key": "requerida",
         "domains": ["financialmodelingprep.com"], "evidence": "third_party/vibetrading/agent/backtest/loaders/fmp_loader.py:9"},
        # ── Asia (HK / Corea / India) ─────────────────────────────────────────
        {"id": "futu", "label": "Futu OpenD (local)", "kind": "data", "key": "terminal local",
         "domains": ["www.futunn.com"], "evidence": "third_party/vibetrading/agent/backtest/loaders/futu.py:110"},
        {"id": "longbridge", "label": "Longbridge / LongPort OpenAPI", "kind": "data", "key": "requerida",
         "domains": [], "evidence": "third_party/vibetrading/agent/backtest/loaders/longbridge.py:69"},
        {"id": "pykrx", "label": "pykrx (KOSPI/KOSDAQ)", "kind": "data", "key": "none",
         "domains": ["regulation.krx.co.kr"], "evidence": "third_party/vibetrading/agent/backtest/loaders/pykrx_loader.py:4"},
        {"id": "india_broker", "label": "Shoonya / Dhan (NSE·BSE, sólo lectura)", "kind": "data",
         "key": "login de broker", "domains": ["api.shoonya.com", "api.dhan.co"],
         "evidence": "third_party/vibetrading/agent/backtest/loaders/india_broker_loader.py:119"},
        # ── Cripto y forex ────────────────────────────────────────────────────
        {"id": "okx", "label": "OKX", "kind": "data", "key": "none",
         "domains": ["www.okx.com"], "evidence": "third_party/vibetrading/agent/backtest/loaders/okx.py:59"},
        {"id": "binance", "label": "Binance (spot + USD-M perps)", "kind": "data", "key": "none",
         "domains": ["api.binance.com", "testnet.binance.vision"],
         "evidence": "third_party/vibetrading/agent/backtest/loaders/binance_loader.py:24"},
        {"id": "ccxt", "label": "ccxt (100+ exchanges)", "kind": "data", "key": "none",
         "domains": [], "evidence": "third_party/vibetrading/agent/backtest/loaders/ccxt_loader.py:185"},
        {"id": "mt5", "label": "MetaTrader 5 (terminal local)", "kind": "data", "key": "terminal local",
         "domains": [], "evidence": "third_party/vibetrading/agent/backtest/loaders/mt5_loader.py:171"},
        {"id": "polymarket", "label": "Polymarket (mercados de predicción)", "kind": "data", "key": "none",
         "domains": ["gamma-api.polymarket.com", "clob.polymarket.com"],
         "evidence": "third_party/vibetrading/agent/src/tools/prediction_market_tool.py:9"},
        # ── Investigación y archivos propios ──────────────────────────────────
        {"id": "arxiv", "label": "arXiv", "kind": "data", "key": "none",
         "domains": ["export.arxiv.org", "arxiv.org"],
         "evidence": "third_party/vibetrading/agent/src/tools/research_papers_tool.py:5"},
        {"id": "openalex", "label": "OpenAlex", "kind": "data", "key": "none",
         "domains": ["api.openalex.org", "openalex.org"],
         "evidence": "third_party/vibetrading/agent/src/tools/research_papers_tool.py:20"},
        {"id": "local", "label": "Archivos propios (CSV · Parquet · DuckDB)", "kind": "data", "key": "none",
         "domains": [], "evidence": "third_party/vibetrading/agent/backtest/loaders/local_loader.py:220"},
    ],

    # ══ OFICINA (OpenWork + OfficeCLI + gws) ════════════════════════════════════════
    # [Gate 4 · F6-oficina · ley 2.ter] EL CENSO DONDE LA LEY MÁS SE NOTA. Las 42 filas
    # de Ciencia solapan con el cinturón en fuentes PÚBLICAS y sin llave; acá el solape es
    # con las tres fuentes MÁS personales que Aleph conecta —Gmail, Calendar y Drive, que
    # ya viven en `catalog/connectors/onboarding/`— y encima las dos tuberías piden OAuth
    # a la MISMA cuenta del usuario. Es justo el caso donde «unifiquemos» suena razonable
    # y sería un error: son dos tuberías con dos trabajos, y la del stack tiene que
    # seguir funcionando con el cinturón apagado (ley 0).
    #
    # Cómo se leen las dos: la del STACK (gws) es la mano del workspace —el agente de
    # Oficina manda un mail porque el usuario se lo pidió adentro de su workspace—; la del
    # CINTURÓN (los conectores de Gate 1) es para que Aleph use esa fuente en artefactos
    # auditados con provenance. Ninguna se apaga; lo que este censo habilita es que el
    # Cuarto no ofrezca «conectá Gmail» a alguien que ya lo tiene adentro, y que el agente
    # lo diga en vez de recomendar a ciegas.
    "oficina": [
        # ── [F2 · C] EL DUPLICADO DE GOOGLE, DECLARADO ─────────────────────────────
        # Hay DOS caminos al mismo servicio y hasta ahora sólo uno estaba censado:
        #
        #   1. `gws-*` (las cuatro de abajo) — MCP stdio, distribución oficial, que trae
        #      Aleph. Sus skills viven en `third_party/gws/`.
        #   2. `google-workspace` — la extensión que trae OFICINA, con su propio flujo de
        #      OAuth (`openwork/apps/server/src/extensions/google-workspace.ts`).
        #
        # POR LEY 0 LA REDUNDANCIA SE HACE VISIBLE, NO SE UNIFICA: el órgano del inquilino
        # es de su oficio y no se le extirpa. Lo que estaba mal era que el duplicado no
        # figuraba, y un censo que muestra un camino donde hay dos no es un censo.
        #
        # ⚠️ SU CREDENCIAL NO ESTÁ CABLEADA, Y NO POR OLVIDO. Medido:
        #   · el `client_id` cae a un horneado del fabricante si nadie lo pone
        #     (`GOOGLE_WORKSPACE_DESKTOP_CLIENT_ID`, `google-workspace.ts:306`), y el propio
        #     stack sabe distinguirlo: `customClient = clientId !== …DESKTOP_CLIENT_ID`.
        #   · el `client_secret` NO tiene respaldo, y sin él el flujo aborta (`:311`).
        #   · pero `:311` acepta una ALTERNATIVA — `…_TOKEN_BROKER_URL` — y con el broker
        #     el secret deja de faltar.
        #
        # Y ahí está la razón de que no se cablee acá: un `client_secret` ES un secreto, y
        # `pack.py:939` dice que por el entorno viajan RUTAS, no secretos. El broker es una
        # RUTA, así que es el único de los dos caminos que respeta la regla de la casa. Cuál
        # de los dos se usa es decisión del dueño (un broker es un servicio que hay que
        # tener), y el `client_id` —que es público en OAuth— ya llega sin tocar nada: el
        # hijo hereda el entorno del sidecar (`ServidorDePack.start`, `env={**os.environ,
        # **self._env}`).
        {"id": "google-workspace-oficina", "label": "Google Workspace (extensión de Oficina)",
         "kind": "data", "key": "oauth",
         "domains": ["oauth2.googleapis.com", "www.googleapis.com",
                     "gmail.googleapis.com", "calendar.googleapis.com"],
         # Duplica a las cuatro `gws-*` de abajo. Se declara para que el duplicado se VEA.
         "duplica": ["gws-gmail", "gws-calendar", "gws-docs", "gws-sheets"],
         "evidence": "third_party/openwork/apps/server/src/extensions/google-workspace.ts:19-22,305-313"},
        # ── manos cloud: gws (Apache-2.0, release v0.22.5, sólo 4 skills) ──────────
        # Ó11 gobierna envío/borrado/eventos: ver la puerta en `platform/gates/`.
        {"id": "gws-gmail", "label": "Gmail (gws)", "kind": "data", "key": "oauth",
         "domains": ["gmail.googleapis.com", "www.googleapis.com"], "also_in_belt": True,
         "belt_connector": "catalog/connectors/onboarding/gmail.json",
         "evidence": "third_party/gws/skills/gws-gmail/SKILL.md:2"},
        {"id": "gws-calendar", "label": "Google Calendar (gws)", "kind": "data", "key": "oauth",
         "domains": ["calendar.googleapis.com", "www.googleapis.com"], "also_in_belt": True,
         "belt_connector": "catalog/connectors/onboarding/google_calendar.json",
         "evidence": "third_party/gws/skills/gws-calendar/SKILL.md:2"},
        {"id": "gws-docs", "label": "Google Docs (gws)", "kind": "data", "key": "oauth",
         "domains": ["docs.googleapis.com", "www.googleapis.com"], "also_in_belt": True,
         # Drive es el conector del cinturón que alcanza los mismos archivos; no hay uno
         # de Docs por separado, y declararlo como si lo hubiera sería inventar catálogo.
         "belt_connector": "catalog/connectors/onboarding/google_drive.json",
         "evidence": "third_party/gws/skills/gws-docs/SKILL.md:2"},
        {"id": "gws-sheets", "label": "Google Sheets (gws)", "kind": "data", "key": "oauth",
         "domains": ["sheets.googleapis.com", "www.googleapis.com"], "also_in_belt": True,
         "belt_connector": "catalog/connectors/onboarding/google_drive.json",
         "evidence": "third_party/gws/skills/gws-sheets/SKILL.md:2"},

        # ── manos locales: OfficeCLI (Apache-2.0, release v1.0.143) ────────────────
        # Sin dominios A PROPÓSITO: no sale a la red, opera archivos del disco. Va en el
        # censo igual porque la pregunta que el censo contesta —«¿esto ya lo tengo?»— vale
        # lo mismo para una fuente local, y porque sin la fila el Cuarto podría ofrecer un
        # conector de planillas a alguien que ya tiene la mano puesta.
        {"id": "officecli", "label": "Office local (OfficeCLI)", "kind": "data", "key": "none",
         "domains": [], "also_in_belt": False,
         "evidence": "third_party/officecli/bin"},
    ],

    # ── [Gate 4 · Fase 6 · §6.f] LA SALA · DEEP RESEARCH — no es un vertical ──────────
    #
    # `sala_research` no se dibuja en el menú (`router.py`, campo `oculto`), pero SUS
    # FUENTES SÍ TIENEN QUE ESTAR ACÁ, y por la razón exacta por la que este archivo
    # existe: `already_covered()` barre el CATÁLOGO ENTERO, no la lista visible. Sin estas
    # filas, El Cuarto le ofrecería a alguien «conectá arXiv» cuando el modo de
    # investigación de su propia Sala ya lo trae adentro.
    #
    # Las 32 filas se midieron sobre el árbol importado —una por archivo
    # `web_search_engines/engines/search_engine_*.py`, con la línea de su clase—, y el
    # campo `key` sale de lo que el propio motor declara en sus settings
    # (`third_party/ldr/src/local_deep_research/defaults/*.json`, clave
    # `search.engine.web.<motor>.requires_api_key`) para los **21 que lo declaran**; los
    # 11 restantes se clasificaron por lo que su API es, y eso queda dicho acá en vez de
    # escondido.
    #
    # Las marcadas `also_in_belt` (arXiv · OpenAlex · PubMed · Semantic Scholar ·
    # Wikipedia) son en su mayoría las mismas que Ciencia ya declaró: dos tuberías al
    # mismo lugar, y ninguna se apaga — la redundancia ES la ley 0 funcionando, y este
    # campo la hace decible en vez de invisible.
    "sala_research": [
        {"id": "arxiv", "label": "arXiv", "kind": "data", "key": "none",
         "domains": ['arxiv.org', 'export.arxiv.org'], "evidence": "third_party/ldr/src/local_deep_research/web_search_engines/engines/search_engine_arxiv.py:12", "also_in_belt": True},
        {"id": "brave", "label": "Brave Search", "kind": "data", "key": "required",
         "domains": ['api.search.brave.com'], "evidence": "third_party/ldr/src/local_deep_research/web_search_engines/engines/search_engine_brave.py:12"},
        {"id": "collection", "label": "Colecciones locales (RAG)", "kind": "data", "key": "none",
         "domains": [], "evidence": "third_party/ldr/src/local_deep_research/web_search_engines/engines/search_engine_collection.py:22"},
        {"id": "ddg", "label": "DuckDuckGo", "kind": "data", "key": "none",
         "domains": ['duckduckgo.com'], "evidence": "third_party/ldr/src/local_deep_research/web_search_engines/engines/search_engine_ddg.py:11"},
        {"id": "elasticsearch", "label": "Elasticsearch propio", "kind": "data", "key": "optional",
         "domains": [], "evidence": "third_party/ldr/src/local_deep_research/web_search_engines/engines/search_engine_elasticsearch.py:14"},
        {"id": "exa", "label": "Exa", "kind": "data", "key": "required",
         "domains": ['api.exa.ai'], "evidence": "third_party/ldr/src/local_deep_research/web_search_engines/engines/search_engine_exa.py:12"},
        {"id": "github", "label": "GitHub", "kind": "data", "key": "required",
         "domains": ['api.github.com'], "evidence": "third_party/ldr/src/local_deep_research/web_search_engines/engines/search_engine_github.py:19"},
        {"id": "google-pse", "label": "Google Programmable Search", "kind": "data", "key": "required",
         "domains": ['www.googleapis.com'], "evidence": "third_party/ldr/src/local_deep_research/web_search_engines/engines/search_engine_google_pse.py:15"},
        {"id": "guardian", "label": "The Guardian", "kind": "data", "key": "required",
         "domains": ['content.guardianapis.com'], "evidence": "third_party/ldr/src/local_deep_research/web_search_engines/engines/search_engine_guardian.py:13"},
        {"id": "gutenberg", "label": "Project Gutenberg", "kind": "data", "key": "none",
         "domains": ['gutendex.com'], "evidence": "third_party/ldr/src/local_deep_research/web_search_engines/engines/search_engine_gutenberg.py:15"},
        {"id": "library", "label": "Biblioteca local (RAG)", "kind": "data", "key": "none",
         "domains": [], "evidence": "third_party/ldr/src/local_deep_research/web_search_engines/engines/search_engine_library.py:24"},
        {"id": "mojeek", "label": "Mojeek", "kind": "data", "key": "required",
         "domains": ['api.mojeek.com'], "evidence": "third_party/ldr/src/local_deep_research/web_search_engines/engines/search_engine_mojeek.py:11"},
        {"id": "nasa-ads", "label": "NASA ADS", "kind": "data", "key": "required",
         "domains": ['api.adsabs.harvard.edu'], "evidence": "third_party/ldr/src/local_deep_research/web_search_engines/engines/search_engine_nasa_ads.py:14"},
        {"id": "openalex", "label": "OpenAlex", "kind": "data", "key": "none",
         "domains": ['api.openalex.org'], "evidence": "third_party/ldr/src/local_deep_research/web_search_engines/engines/search_engine_openalex.py:14", "also_in_belt": True},
        {"id": "openlibrary", "label": "Open Library", "kind": "data", "key": "none",
         "domains": ['openlibrary.org'], "evidence": "third_party/ldr/src/local_deep_research/web_search_engines/engines/search_engine_openlibrary.py:16"},
        {"id": "paperless", "label": "Paperless-ngx propio", "kind": "data", "key": "optional",
         "domains": [], "evidence": "third_party/ldr/src/local_deep_research/web_search_engines/engines/search_engine_paperless.py:21"},
        {"id": "pubchem", "label": "PubChem", "kind": "data", "key": "none",
         "domains": ['pubchem.ncbi.nlm.nih.gov'], "evidence": "third_party/ldr/src/local_deep_research/web_search_engines/engines/search_engine_pubchem.py:15"},
        {"id": "pubmed", "label": "PubMed", "kind": "data", "key": "none",
         "domains": ['eutils.ncbi.nlm.nih.gov'], "evidence": "third_party/ldr/src/local_deep_research/web_search_engines/engines/search_engine_pubmed.py:15", "also_in_belt": True},
        {"id": "retriever", "label": "Retriever inyectado", "kind": "data", "key": "none",
         "domains": [], "evidence": "third_party/ldr/src/local_deep_research/web_search_engines/engines/search_engine_retriever.py:15"},
        {"id": "scaleserp", "label": "ScaleSERP", "kind": "data", "key": "required",
         "domains": ['api.scaleserp.com'], "evidence": "third_party/ldr/src/local_deep_research/web_search_engines/engines/search_engine_scaleserp.py:12"},
        {"id": "searxng", "label": "SearXNG (el metabuscador de la Sala)", "kind": "data", "key": "none",
         "domains": [], "evidence": "third_party/ldr/src/local_deep_research/web_search_engines/engines/search_engine_searxng.py:27"},
        {"id": "semantic-scholar", "label": "Semantic Scholar", "kind": "data", "key": "none",
         "domains": ['api.semanticscholar.org'], "evidence": "third_party/ldr/src/local_deep_research/web_search_engines/engines/search_engine_semantic_scholar.py:16", "also_in_belt": True},
        {"id": "serpapi", "label": "SerpAPI", "kind": "data", "key": "required",
         "domains": [], "evidence": "third_party/ldr/src/local_deep_research/web_search_engines/engines/search_engine_serpapi.py:11"},
        {"id": "serper", "label": "Serper", "kind": "data", "key": "required",
         "domains": ['google.serper.dev'], "evidence": "third_party/ldr/src/local_deep_research/web_search_engines/engines/search_engine_serper.py:12"},
        {"id": "sofya", "label": "Sofya", "kind": "data", "key": "required",
         "domains": ['sofya.co'], "evidence": "third_party/ldr/src/local_deep_research/web_search_engines/engines/search_engine_sofya.py:27"},
        {"id": "stackexchange", "label": "Stack Exchange", "kind": "data", "key": "none",
         "domains": ['api.stackexchange.com'], "evidence": "third_party/ldr/src/local_deep_research/web_search_engines/engines/search_engine_stackexchange.py:18"},
        {"id": "tavily", "label": "Tavily", "kind": "data", "key": "required",
         "domains": ['api.tavily.com'], "evidence": "third_party/ldr/src/local_deep_research/web_search_engines/engines/search_engine_tavily.py:12"},
        {"id": "tinyfish", "label": "TinyFish", "kind": "data", "key": "required",
         "domains": ['api.search.tinyfish.ai'], "evidence": "third_party/ldr/src/local_deep_research/web_search_engines/engines/search_engine_tinyfish.py:13"},
        {"id": "wayback", "label": "Wayback Machine", "kind": "data", "key": "none",
         "domains": ['archive.org'], "evidence": "third_party/ldr/src/local_deep_research/web_search_engines/engines/search_engine_wayback.py:14"},
        {"id": "wikinews", "label": "Wikinews", "kind": "data", "key": "none",
         "domains": ['wikinews.org'], "evidence": "third_party/ldr/src/local_deep_research/web_search_engines/engines/search_engine_wikinews.py:47"},
        {"id": "wikipedia", "label": "Wikipedia", "kind": "data", "key": "none",
         "domains": ['en.wikipedia.org'], "evidence": "third_party/ldr/src/local_deep_research/web_search_engines/engines/search_engine_wikipedia.py:26", "also_in_belt": True},
        {"id": "zenodo", "label": "Zenodo", "kind": "data", "key": "none",
         "domains": ['zenodo.org'], "evidence": "third_party/ldr/src/local_deep_research/web_search_engines/engines/search_engine_zenodo.py:17"},
        # ── lo que el motor expone y NO es una fuente, sino una PUERTA ────────────────
        # Su servidor MCP viaja entero y no se tocó. No es la puerta de la Sala —es stdio
        # (`mcp/server.py:1053`) y ciego al progreso (`:367-368`)— pero es una puerta
        # legítima para que un agente lo use como tool. Se censa para que nadie la vuelva
        # a construir por afuera creyendo que no existe.
        {"id": "ldr-mcp", "label": "Deep Research por MCP (8 tools, stdio)", "kind": "tool", "key": "none",
         "domains": [], "evidence": "third_party/ldr/src/local_deep_research/mcp/server.py:353"},
    ],

    # ── [Gate 4 · Fase 6 · §6.a.bis] LA SALA · BÚSQUEDA BASE — tampoco es un vertical ──
    #
    # Pocas filas y muy distintas entre sí, porque este motor no colecciona fuentes: tiene
    # UNA grande (el metabuscador, que adentro alcanza cientos de motores y por eso se
    # censa como una sola cosa: lo que Aleph puede decir es «ya tenés metabúsqueda», no
    # enumerar los 245 de SearXNG) y unas pocas chicas de sus widgets.
    "sala_busqueda": [
        # La grande. Va por proceso aparte —es AGPL— y por eso su `domains` está vacío: no
        # sale a un dominio, sale a un vecino en loopback que el pack levanta.
        {"id": "searxng", "label": "SearXNG (metabúsqueda, proceso vecino)", "kind": "data", "key": "none",
         "domains": [], "evidence": "third_party/vane/src/lib/searxng.ts:21-27"},
        # El fetch de página completa: keyless y transversal, como pide §6.a.bis. No es un
        # dominio: es la capacidad de ir a buscar CUALQUIER página citada y leerla.
        {"id": "scraper", "label": "Lectura de página completa (Readability + navegador)", "kind": "data", "key": "none",
         "domains": [], "evidence": "third_party/vane/src/lib/scraper.ts:1-16"},
        # Las chicas: los widgets. Son dominio del stack (LEY 0) y son keyless.
        {"id": "open-meteo", "label": "Open-Meteo (clima)", "kind": "data", "key": "none",
         "domains": ["api.open-meteo.com"],
         "evidence": "third_party/vane/src/lib/agents/search/widgets/weatherWidget.ts:109"},
        {"id": "nominatim", "label": "Nominatim / OpenStreetMap (geocodificación)", "kind": "data", "key": "none",
         "domains": ["nominatim.openstreetmap.org"],
         "evidence": "third_party/vane/src/lib/agents/search/widgets/weatherWidget.ts:89"},
        {"id": "yahoo-finance", "label": "Yahoo Finance (cotizaciones)", "kind": "data", "key": "none",
         "domains": ["query1.finance.yahoo.com", "query2.finance.yahoo.com"],
         "evidence": "third_party/vane/src/lib/agents/search/widgets/stockWidget.ts:3"},
        # Los embeddings del reranker: corren LOCALES, autorizados por el dueño con el
        # precedente ONNX de Legal (motor del stack, no cerebro). Se censa el hecho de que
        # la PRIMERA corrida baja los pesos de Hugging Face — un cabo suelto declarado, no
        # escondido (ver `platform/sala/busqueda/config.py`).
        {"id": "hf-embeddings", "label": "Embeddings locales del reranker (pesos desde Hugging Face en la 1ª corrida)",
         "kind": "data", "key": "none", "domains": ["huggingface.co", "cdn-lfs.huggingface.co"],
         "evidence": "third_party/vane/src/lib/models/providers/transformers/transformerEmbedding.ts:27-30"},
    ],
}


def sources(workspace: str) -> list[dict[str, Any]]:
    return list(CATALOG.get((workspace or "").strip().lower(), []))


def domains(workspace: str) -> tuple:
    """Todos los dominios que el stack ya alcanza. Lo usa quien quiera comprobar que un
    conector nuevo no duplica algo que ya está adentro."""
    out: list[str] = []
    for f in sources(workspace):
        for d in f.get("domains", []):
            if d not in out:
                out.append(d)
    return tuple(out)


def already_covered(domain: str) -> list[dict[str, Any]]:
    """¿Qué workspace ya trae este dominio? Vacío = nadie lo trae.

    Ésta es la consulta que hace visible la ley: antes de ofrecer un conector, se
    pregunta acá y se dice la verdad en vez de proponer lo que ya está puesto."""
    d = (domain or "").strip().lower()
    if not d:
        return []
    hits = []
    for ws, filas in CATALOG.items():
        for f in filas:
            if any(d == x.lower() or d.endswith("." + x.lower()) for x in f.get("domains", [])):
                hits.append({"workspace": ws, **f})
    return hits


def as_json(workspace: str | None = None) -> dict:
    if workspace:
        ws = workspace.strip().lower()
        return {"workspaces": {ws: sources(ws)}}
    return {"workspaces": {ws: filas for ws, filas in CATALOG.items()}}


__all__ = ["KINDS", "CATALOG", "sources", "domains", "already_covered", "as_json"]
