"""Read-only symbol-search tool: resolve a name/ticker to symbols + market.

Backed by four frozen, IP-throttled public-API clients so the agent never
hits a provider un-throttled and never re-implements transport plumbing:

* :mod:`backtest.loaders.eastmoney_client` — Eastmoney's free suggest endpoint
  matches Chinese/English names and tickers across A-shares (.SH/.SZ/.BJ),
  Hong Kong (.HK) and U.S. (.US) listings, each carrying a fully-qualified
  ``secid`` already in ``<market>.<code>`` form.
* :mod:`backtest.loaders.yahoo_client` — Yahoo's v1 search endpoint matches
  global tickers/company names (US, HK, Canada, crypto, indices, FX, ...).
* :mod:`backtest.loaders.sec_edgar_client` — the SEC company-tickers table
  enriches a resolved U.S. equity ticker with its zero-padded CIK.
* :mod:`backtest.loaders.okx` — the OKX SPOT instrument table names the crypto
  pairs this project can actually fetch (``BTC-USDT``), which no equity source
  knows. [Aleph]

The tool fans out across these sources, normalizes every hit into one compact
candidate row in the project's symbol convention, de-duplicates by symbol, and
caps the payload. A single failing source never aborts the others; its error is
recorded under ``sources`` and the surviving candidates still return.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from backtest.loaders import eastmoney_client, okx, sec_edgar_client, yahoo_client
from src.agent.tools import BaseTool

logger = logging.getLogger(__name__)

# Eastmoney's free, no-auth suggest endpoint (the same one the quote site calls)
# returns multi-market candidates under ``QuotationCodeTable.Data`` with a
# ready-made ``QuoteID`` secid. Requests route through the frozen, throttled
# Eastmoney client; this is just the documented endpoint URL + query shape.
_EASTMONEY_SUGGEST_URL = "https://searchapi.eastmoney.com/api/suggest/get"

# Eastmoney market-number -> our symbol suffix. Anything else is left unmapped
# (those candidates are skipped rather than emitted with a wrong suffix).
_EASTMONEY_SUFFIX_BY_MARKET: Dict[str, str] = {
    "1": "SH",   # Shanghai
    "0": "SZ",   # Shenzhen / Beijing share the 0 prefix on Eastmoney
    "116": "HK",
    "105": "US",  # NASDAQ
    "106": "US",  # NYSE
    "107": "US",  # AMEX
}

# Coarse market label for the candidate row, keyed by symbol suffix.
_MARKET_BY_SUFFIX: Dict[str, str] = {
    "SH": "cn",
    "SZ": "cn",
    "BJ": "cn",
    "HK": "hk",
    "US": "us",
}

# Hard caps so a broad query cannot bloat the envelope.
_MAX_LIMIT = 25
_DEFAULT_LIMIT = 10
# Per-source fan-out ceiling before de-dup/merge keeps each provider bounded.
_PER_SOURCE_CAP = 25

# Sentinel for "no U.S. candidate, SEC was not consulted" so the caller can omit
# the ``sec_edgar`` source entry entirely.
_NO_US = "__no_us__"

# [Aleph · Gate 4 · F6-FINANZAS] SÓLO PARES CONTRA USDT.
#
# No es una preferencia: es lo único que el motor sabe ir a buscar. `src/market_data.py`
# rutea a OKX con `^[A-Z]+-USDT$` y `_market_hooks._detect_market` llama «crypto» a
# `X-USDT`, `X/USDT` y `X-USD`; un `BTC-USDC` resuelto caería en el default `tushare`,
# que es de acciones chinas. Emitir un par que nadie puede pedir sería cambiar un pozo
# por otro: se resuelve la identidad y después no hay velas. De los 1.383 instrumentos
# spot vivos, 395 cotizan contra USDT.
_OKX_QUOTE = "USDT"
# Un prefijo es una apuesta, no una coincidencia; va con tope corto y sólo cuando no
# hubo ninguna exacta.
_OKX_PREFIX_CAP = 5
_OKX_PREFIX_MIN_LEN = 3


class SymbolSearchTool(BaseTool):
    """Resolve a company name or ticker fragment to candidate symbols."""

    name = "search_symbol"
    description = (
        "Resolve a company name or ticker fragment to candidate trading symbols "
        "with their market, in the project's symbol convention (A-shares "
        "600519.SH, Hong Kong 00700.HK, U.S. AAPL.US, Canada TD.TO/PNG.V, plus "
        "crypto spot pairs BTC-USDT, plus index/FX from "
        "Yahoo). Searches Eastmoney (China/HK/US names and tickers), OKX (crypto "
        "spot pairs, by ticker: 'BTC', 'btc/usdt' and 'BTC-USDT' all resolve to "
        "BTC-USDT) and Yahoo "
        "(global) and, for U.S. equities, attaches the SEC CIK. Use this to turn "
        "an ambiguous name into a concrete symbol before calling get_market_data "
        'or get_sec_filings. Example: search_symbol(query="apple", limit=5).'
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Free-text company name or ticker fragment to resolve, e.g. "
                    "'apple', '贵州茅台', '茅台', 'AAPL', '00700'. Chinese and "
                    "English both accepted."
                ),
            },
            "limit": {
                "type": "integer",
                "description": (
                    f"Maximum number of merged candidates to return "
                    f"(1-{_MAX_LIMIT}). Defaults to {_DEFAULT_LIMIT}."
                ),
                "default": _DEFAULT_LIMIT,
            },
        },
        "required": ["query"],
    }
    repeatable = True

    def execute(self, **kwargs: Any) -> str:
        """Fan out across providers and return a merged candidate envelope.

        Args:
            **kwargs: ``query`` (str, required free-text name/ticker) and
                ``limit`` (int, optional; clamped to ``1.._MAX_LIMIT``).

        Returns:
            A JSON envelope string. On success:
            ``{"ok": true, "market": "multi", "source": "symbol_search",
            "data": {"query": str, "count": int, "candidates": [...],
            "sources": {<name>: "ok"|<error>}}}``. On failure (only when the
            query itself is invalid):
            ``{"ok": false, "error": str}``.
        """
        query = str(kwargs.get("query") or "").strip()
        if not query:
            return _error("'query' is required and must be a non-empty string")

        limit = _clamp_limit(kwargs.get("limit", _DEFAULT_LIMIT))

        candidates: List[Dict[str, Any]] = []
        sources: Dict[str, str] = {}

        em_hits, sources["eastmoney"] = _search_eastmoney(query)
        candidates.extend(em_hits)

        # [Aleph] OKX va ANTES que Yahoo a propósito: con `limit=5`, «BTC» traía
        # BTC-USD, BTC=F, GBTC, BTCY.US y BTCS.US, y el par que sí se puede pedir
        # quedaba fuera del corte. Para consultas de acciones esta fuente devuelve
        # cero (medido con «apple», «AAPL», «茅台», «GBTC»), así que no le saca el
        # lugar a nadie.
        okx_hits, sources["okx"] = _search_okx(query)
        candidates.extend(okx_hits)

        yh_hits, sources["yahoo"] = _search_yahoo(query)
        candidates.extend(yh_hits)

        merged = _fold_unfetchable_spellings(_merge_candidates(candidates))
        merged, sources["sec_edgar"] = _enrich_us_cik(merged)
        if sources["sec_edgar"] == _NO_US:
            del sources["sec_edgar"]
        merged = merged[:limit]

        return json.dumps(
            {
                "ok": True,
                "market": "multi",
                "source": "symbol_search",
                "data": {
                    "query": query,
                    "count": len(merged),
                    "candidates": merged,
                    "sources": sources,
                },
            },
            ensure_ascii=False,
        )


def _clamp_limit(value: Any) -> int:
    """Coerce a requested count into the supported ``1.._MAX_LIMIT`` range."""
    try:
        n = int(value)
    except (TypeError, ValueError, OverflowError):
        return _DEFAULT_LIMIT
    return max(1, min(n, _MAX_LIMIT))


def _search_eastmoney(query: str) -> tuple[List[Dict[str, Any]], str]:
    """Query Eastmoney's suggest endpoint and normalize the candidates.

    Args:
        query: Free-text name or ticker fragment.

    Returns:
        ``(candidates, status)`` where ``status`` is ``"ok"`` on success or a
        short error string when the source failed (candidates is then empty).
    """
    try:
        payload = eastmoney_client.get_json(
            _EASTMONEY_SUGGEST_URL,
            params={"input": query, "type": "14", "count": str(_PER_SOURCE_CAP)},
        )
    except Exception as exc:  # noqa: BLE001 - one source failing is non-fatal
        logger.warning("eastmoney suggest failed for %r: %s", query, exc)
        return [], f"eastmoney search failed: {exc}"

    rows = _eastmoney_data_rows(payload)
    candidates = [c for c in (_eastmoney_candidate(r) for r in rows) if c is not None]
    return candidates, "ok"


def _eastmoney_data_rows(payload: Any) -> List[Dict[str, Any]]:
    """Extract the ``QuotationCodeTable.Data`` rows from a suggest payload."""
    if not isinstance(payload, dict):
        return []
    table = payload.get("QuotationCodeTable")
    if not isinstance(table, dict):
        return []
    data = table.get("Data")
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def _eastmoney_candidate(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map one Eastmoney suggest row to a normalized candidate, or ``None``.

    Eastmoney rows carry ``QuoteID`` (``<market>.<code>``), ``Code``, ``Name``,
    ``MktNum`` and ``SecurityTypeName``. A row whose market we cannot map to a
    project suffix is dropped rather than emitted with a wrong symbol.

    Args:
        row: One ``QuotationCodeTable.Data`` element.

    Returns:
        A candidate dict, or ``None`` when the row is unusable.
    """
    quote_id = row.get("QuoteID")
    market = ""
    code = str(row.get("Code") or "").strip()
    if isinstance(quote_id, str) and "." in quote_id:
        market, _, qid_code = quote_id.partition(".")
        code = code or qid_code.strip()
    else:
        market = str(row.get("MktNum") or "").strip()
    suffix = _EASTMONEY_SUFFIX_BY_MARKET.get(market)
    if not suffix or not code:
        return None

    symbol = _format_symbol(code, suffix)
    if symbol is None:
        return None
    name = str(row.get("Name") or "").strip() or None
    sec_type = str(row.get("SecurityTypeName") or "").strip() or None
    return {
        "symbol": symbol,
        "name": name,
        "market": _MARKET_BY_SUFFIX.get(suffix, suffix.lower()),
        "type": sec_type,
        "source": "eastmoney",
    }


def _format_symbol(code: str, suffix: str) -> Optional[str]:
    """Render a bare code + suffix into the project symbol convention.

    HK codes are zero-padded to five digits to match the loader/secid scheme.

    Args:
        code: Bare instrument code (e.g. ``"600519"``, ``"700"``, ``"AAPL"``).
        suffix: One of ``SH``/``SZ``/``BJ``/``HK``/``US``.

    Returns:
        The formatted symbol (``"600519.SH"``, ``"00700.HK"``, ``"AAPL.US"``),
        or ``None`` when the code is empty.
    """
    code = code.strip().upper()
    if not code:
        return None
    if suffix == "HK":
        return f"{code.zfill(5)}.HK"
    return f"{code}.{suffix}"


def _search_yahoo(query: str) -> tuple[List[Dict[str, Any]], str]:
    """Query Yahoo's search endpoint and normalize the quote candidates.

    Args:
        query: Free-text name or ticker fragment.

    Returns:
        ``(candidates, status)`` where ``status`` is ``"ok"`` on success or a
        short error string when the source failed (candidates is then empty).
    """
    try:
        quotes = yahoo_client.search(query)
    except Exception as exc:  # noqa: BLE001 - one source failing is non-fatal
        logger.warning("yahoo search failed for %r: %s", query, exc)
        return [], f"yahoo search failed: {exc}"

    candidates: List[Dict[str, Any]] = []
    for quote in quotes[:_PER_SOURCE_CAP]:
        candidate = _yahoo_candidate(quote)
        if candidate is not None:
            candidates.append(candidate)
    return candidates, "ok"


def _yahoo_candidate(quote: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map one Yahoo search quote to a normalized candidate, or ``None``.

    Yahoo carries US tickers bare, HK tickers as ``0700.HK``, and Canadian
    listings with ``.TO`` / ``.V`` suffixes. We translate those into the project
    convention (``AAPL.US`` / ``00700.HK`` / ``TD.TO`` / ``PNG.V``) and leave
    other instruments (crypto, indices, FX) on their native Yahoo symbol.

    Args:
        quote: One element of Yahoo search's ``quotes`` list.

    Returns:
        A candidate dict, or ``None`` when the quote has no symbol.
    """
    raw_symbol = str(quote.get("symbol") or "").strip()
    if not raw_symbol:
        return None
    symbol, market = _from_yahoo_symbol(raw_symbol, quote)
    name = (
        str(quote.get("shortname") or quote.get("longname") or "").strip() or None
    )
    return {
        "symbol": symbol,
        "name": name,
        "market": market,
        "type": str(quote.get("quoteType") or "").strip().lower() or None,
        "exchange": str(quote.get("exchange") or "").strip() or None,
        "source": "yahoo",
    }


def _from_yahoo_symbol(raw_symbol: str, quote: Dict[str, Any]) -> tuple[str, str]:
    """Translate a Yahoo symbol into the project convention + market label.

    Args:
        raw_symbol: The Yahoo-side symbol (e.g. ``AAPL``, ``0700.HK``,
            ``TD.TO``, ``PNG.V``, or ``BTC-USD``).
        quote: The full Yahoo quote, used to distinguish a bare US equity from a
            crypto/index instrument via ``quoteType``.

    Returns:
        ``(symbol, market)`` in the project convention.
    """
    upper = raw_symbol.upper()
    if upper.endswith(".HK"):
        base = raw_symbol[: -len(".HK")].lstrip("0") or "0"
        return f"{base.zfill(5)}.HK", "hk"
    if upper.endswith((".TO", ".V")):
        return upper, "ca"
    quote_type = str(quote.get("quoteType") or "").strip().upper()
    if quote_type == "EQUITY" and "." not in raw_symbol and "-" not in raw_symbol:
        return f"{upper}.US", "us"
    # Crypto, indices, FX, ETFs on non-HK exchanges: keep Yahoo's native symbol.
    return raw_symbol, "global"


def _search_okx(query: str) -> tuple[List[Dict[str, Any]], str]:
    """Match the query against OKX's SPOT instrument table.

    Args:
        query: Free-text ticker or pair fragment.

    Returns:
        ``(candidates, status)`` where ``status`` is ``"ok"`` on success or a
        short error string when the source failed (candidates is then empty).
    """
    try:
        instruments = okx.spot_instruments()
    except Exception as exc:  # noqa: BLE001 - one source failing is non-fatal
        logger.warning("okx instruments failed for %r: %s", query, exc)
        return [], f"okx search failed: {exc}"
    return _okx_matches(query, instruments), "ok"


def _okx_normalize(query: str) -> str:
    """Fold a free-text crypto query into OKX's ``BASE-QUOTE`` spelling.

    ``"btc/usdt"``, ``"btc usdt"`` and ``"BTC-USDT"`` all fold to ``BTC-USDT``;
    a bare ``"btc"`` folds to ``BTC``.

    Args:
        query: The raw user/model query.

    Returns:
        The upper-cased, dash-separated form.
    """
    return "-".join(query.split()).upper().replace("/", "-")


def _okx_matches(
    query: str, instruments: List[Dict[str, str]]
) -> List[Dict[str, Any]]:
    """Select the instruments a query names, exact hits first.

    Three spellings count as exact: the full pair (``BTC-USDT``), the glued form
    (``BTCUSDT``), and the bare base currency (``BTC``). Prefix hits are only
    considered when nothing matched exactly — otherwise ``"eth"`` would drag
    ``ETHFI``/``ETHW`` along behind the pair the caller actually meant.

    Args:
        query: Free-text ticker or pair fragment.
        instruments: Rows from :func:`backtest.loaders.okx.spot_instruments`.

    Returns:
        Candidate rows in the project convention (possibly empty).
    """
    wanted = _okx_normalize(query)
    glued = wanted.replace("-", "")
    exact: List[Dict[str, str]] = []
    prefix: List[Dict[str, str]] = []
    for row in instruments:
        base = str(row.get("baseCcy") or "").strip().upper()
        quote = str(row.get("quoteCcy") or "").strip().upper()
        inst_id = str(row.get("instId") or "").strip().upper()
        if quote != _OKX_QUOTE or not base or not inst_id:
            continue
        if inst_id == wanted or base + quote == glued or base == wanted:
            exact.append(row)
        elif len(wanted) >= _OKX_PREFIX_MIN_LEN and base.startswith(wanted):
            prefix.append(row)

    chosen = exact if exact else prefix[:_OKX_PREFIX_CAP]
    chosen = sorted(chosen, key=lambda r: str(r.get("instId") or ""))
    return [_okx_candidate(row) for row in chosen]


def _okx_candidate(row: Dict[str, str]) -> Dict[str, Any]:
    """Map one OKX instrument row to a normalized candidate.

    OKX publishes no display name, so the name is derived from the pair itself
    rather than invented: the row states what it is, a spot pair on OKX.

    Args:
        row: One :func:`backtest.loaders.okx.spot_instruments` element.

    Returns:
        A candidate dict in the same shape the other sources emit.
    """
    base = str(row.get("baseCcy") or "").strip().upper()
    quote = str(row.get("quoteCcy") or "").strip().upper()
    return {
        "symbol": str(row.get("instId") or "").strip().upper(),
        "name": f"{base}/{quote} spot",
        "market": "crypto",
        "type": "spot",
        "exchange": "OKX",
        "source": "okx",
    }


def _es_bajable_como_cripto(symbol: str) -> bool:
    """Say whether this project could actually fetch bars for ``symbol``.

    Asks the engine's own routing rather than guessing: the source
    ``detect_source`` picks must belong to the crypto fallback chain, otherwise
    the symbol degrades down some other market's chain and never reaches a
    loader that knows the asset.

    Args:
        symbol: A candidate symbol (e.g. ``"BTC-USD"``).

    Returns:
        ``True`` when the symbol routes to a crypto-capable loader.
    """
    # Import local: `market_data` es la capa de arriba y esto corre una vez por consulta.
    from backtest.loaders.registry import FALLBACK_CHAINS
    from src.market_data import detect_source

    return detect_source(symbol) in (FALLBACK_CHAINS.get("crypto") or [])


def _fold_unfetchable_spellings(
    candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Fold other spellings of a crypto asset into the pair we can actually fetch.

    [Aleph · Gate 4 · F6-FINANZAS] DOS DELETREOS DEL MISMO ACTIVO SON UN EMPATE.

    MEDIDO al agregar la fuente de OKX: «BTC» pasaba de `locked` a `ambiguous`, porque
    `grounding._choose_candidate` marca como exacto todo candidato cuya BASE coincide con
    la consulta, y ahora había dos —``BTC-USDT`` y ``BTC-USD``—. Un empate no fija nada, y
    `ambiguous` no lo deshace la mitigación: el turno moría igual, sólo que más temprano.
    Con «ETH» el empate era contra ``ETH-CAD``.

    De esos deletreos sólo uno se puede bajar, y el criterio no se adivina: se le pregunta
    al ruteo del motor. ``detect_source("BTC-USD")`` devuelve ``tushare`` —acciones
    chinas— porque ningún patrón cubre ``X-USD``, y ``tushare`` NO está en la cadena de
    respaldo de cripto (``okx · binance · ccxt · yfinance · local``), así que nunca degrada
    hasta un loader que sepa el activo.

    Sólo se pliega un deletreo de la MISMA base para la que ya hay par contra USDT, y no
    se esconde nada: el que sale queda anotado en ``aliases`` del que queda.

    Args:
        candidates: Merged candidate rows (left unmodified).

    Returns:
        New candidate rows with the unfetchable duplicate spellings folded in.
    """
    pares = {
        str(c.get("symbol") or "").upper()[: -len("-USDT")]
        for c in candidates
        if c.get("source") == "okx"
        and str(c.get("symbol") or "").upper().endswith("-USDT")
    }
    if not pares:
        return candidates

    plegados: Dict[str, List[str]] = {}
    sobreviven: List[Dict[str, Any]] = []
    for candidate in candidates:
        symbol = str(candidate.get("symbol") or "").upper()
        base, sep, quote = symbol.partition("-")
        if (
            sep
            and quote
            and quote != _OKX_QUOTE
            and base in pares
            and not _es_bajable_como_cripto(symbol)
        ):
            plegados.setdefault(f"{base}-{_OKX_QUOTE}", []).append(symbol)
            continue
        sobreviven.append(candidate)

    if not plegados:
        return candidates
    return [
        {**c, "aliases": plegados[str(c.get("symbol") or "").upper()]}
        if str(c.get("symbol") or "").upper() in plegados
        else c
        for c in sobreviven
    ]


def _merge_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """De-duplicate candidates by symbol, preserving first-seen order.

    When two sources resolve the same symbol the first hit wins and the second
    source name is appended to a ``also_from`` list so provenance is not lost.

    Args:
        candidates: Raw candidates from every source, in fan-out order.

    Returns:
        A de-duplicated candidate list (immutable inputs are copied, not mutated).
    """
    by_symbol: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for candidate in candidates:
        symbol = candidate.get("symbol")
        if not symbol:
            continue
        if symbol not in by_symbol:
            by_symbol[symbol] = dict(candidate)
            order.append(symbol)
            continue
        existing = by_symbol[symbol]
        other = candidate.get("source")
        if other and other != existing.get("source"):
            also = list(existing.get("also_from") or [])
            if other not in also:
                also.append(other)
            merged = dict(existing)
            merged["also_from"] = also
            # Backfill a missing name from the duplicate hit.
            if not merged.get("name") and candidate.get("name"):
                merged["name"] = candidate["name"]
            by_symbol[symbol] = merged
    return [by_symbol[sym] for sym in order]


def _enrich_us_cik(
    candidates: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], str]:
    """Return new candidates with a SEC CIK attached to U.S.-equity rows.

    Only ``.US`` equity symbols are looked up; the SEC table maps bare tickers
    to a zero-padded 10-digit CIK. A lookup failure stops further lookups and is
    reported via the status; resolved CIKs found before it still apply.

    Args:
        candidates: Merged candidate rows (left unmodified).

    Returns:
        ``(new_candidates, status)`` where ``status`` is :data:`_NO_US` when no
        U.S. equity was present, ``"ok"`` on a clean pass, or a short error
        string when a SEC lookup failed.
    """
    has_us = any(
        isinstance(c.get("symbol"), str) and c["symbol"].upper().endswith(".US")
        for c in candidates
    )
    if not has_us:
        return candidates, _NO_US

    status = "ok"
    out: List[Dict[str, Any]] = []
    for candidate in candidates:
        symbol = candidate.get("symbol")
        if status == "ok" and isinstance(symbol, str) and symbol.upper().endswith(".US"):
            ticker = symbol[: -len(".US")]
            try:
                cik = sec_edgar_client.cik_for(ticker)
            except Exception as exc:  # noqa: BLE001 - enrichment failure is non-fatal
                logger.warning("sec cik_for failed for %s: %s", ticker, exc)
                status = f"sec lookup failed: {exc}"
                out.append(candidate)
                continue
            if cik:
                out.append({**candidate, "cik": cik})
                continue
        out.append(candidate)
    return out, status


def _error(message: str) -> str:
    """Render a failure envelope as a JSON string."""
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)
