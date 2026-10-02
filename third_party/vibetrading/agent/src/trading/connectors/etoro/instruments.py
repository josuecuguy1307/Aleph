"""Instrument search and symbol resolution for eToro.

eToro Public API conventions (see eToro builders docs):
- Exact ticker lookup: ``GET /market-data/search?internalSymbolFull=BTC``
- Fuzzy discovery: ``GET /market-data/search?search=<query>&limit=<n>``
- Search responses use ``items[]`` with ``instrumentId`` (lowercase ``d``).
- Metadata enrichment: ``GET /market-data/instruments?instrumentIds=...``
"""

from __future__ import annotations

import re
from typing import Any

from src.trading.connectors.etoro.client import EtoroAPIError, EtoroConfig, make_client

# Common aliases → eToro ``internalSymbolFull`` tickers.
_SYMBOL_ALIASES: dict[str, str] = {
    "BITCOIN": "BTC",
    "ETHEREUM": "ETH",
    "XRP": "XRP",
    "DOGECOIN": "DOGE",
    "SOLANA": "SOL",
    "LITECOIN": "LTC",
}

# Aggregate / sentinel ids returned by fuzzy search — never tradable.
_INVALID_INSTRUMENT_IDS = frozenset({-100000})

_TICKER_RE = re.compile(r"^[A-Za-z0-9./_-]{1,24}$")


def _base_payload(cfg: EtoroConfig) -> dict[str, Any]:
    return {
        "profile": cfg.profile,
        "environment": cfg.environment,
        "paper_guard": "path_separated_key_bound",
    }


def search_instruments(
    query: str,
    config: EtoroConfig | None = None,
    *,
    limit: int = 10,
    mode: str = "auto",
) -> dict[str, Any]:
    """Search eToro instruments by ticker or free-text query.

    Args:
        query: Symbol (``BTC``, ``AAPL``) or discovery text (``bitcoin``, sector name).
        config: Optional connector config.
        limit: Max results (capped at 50).
        mode: ``auto`` (ticker → exact lookup then fuzzy), ``symbol`` (exact only),
            or ``discover`` (fuzzy ``search`` param only).
    """
    from src.trading.connectors.etoro.client import load_config

    cfg = config or load_config()
    token = str(query or "").strip()
    if not token:
        raise EtoroAPIError("search query is required")

    clean_limit = max(1, min(int(limit), 50))
    clean_mode = str(mode or "auto").strip().lower()
    if clean_mode not in ("auto", "symbol", "discover"):
        raise EtoroAPIError("mode must be 'auto', 'symbol', or 'discover'")

    rows: list[dict[str, Any]] = []
    lookup_mode = clean_mode
    if clean_mode == "auto":
        lookup_mode = "symbol" if _looks_like_ticker(token) else "discover"

    if lookup_mode == "symbol":
        rows = _search_by_symbol(cfg, token, limit=clean_limit)
        if not rows and clean_mode == "auto":
            rows = _search_by_text(cfg, token, limit=clean_limit)
    else:
        rows = _search_by_text(cfg, token, limit=clean_limit)

    normalized = [_normalize_instrument_row(item) for item in rows if isinstance(item, dict)]
    normalized = [row for row in normalized if row.get("instrument_id") is not None]
    canonical = _canonical_ticker(token)
    normalized.sort(
        key=lambda row: -_match_priority(
            row.get("raw") or {},
            canonical,
            canonical,
            token,
        ),
    )
    return {
        "status": "ok",
        **_base_payload(cfg),
        "query": token,
        "mode": lookup_mode,
        "instruments": normalized[:clean_limit],
    }


def resolve_instrument_id(symbol: str, cfg: EtoroConfig) -> int:
    """Resolve a user symbol to an eToro ``instrumentId`` for trading APIs."""
    token = str(symbol or "").strip()
    if not token:
        raise EtoroAPIError("symbol is required")
    if token.isdigit():
        instrument_id = int(token)
        if instrument_id in _INVALID_INSTRUMENT_IDS or instrument_id < 0:
            raise EtoroAPIError(f"invalid instrument id {instrument_id}")
        return instrument_id

    canonical = _canonical_ticker(token)
    candidates: list[tuple[int, int]] = []  # (priority, instrument_id)

    for lookup in _lookup_variants(token, canonical):
        for item in _search_by_symbol(cfg, lookup, limit=25):
            instrument_id = _instrument_id(item)
            if instrument_id is None:
                continue
            priority = _match_priority(item, lookup, canonical, token)
            if priority > 0:
                candidates.append((priority, instrument_id))

    if not candidates:
        for item in _search_by_text(cfg, canonical, limit=25):
            instrument_id = _instrument_id(item)
            if instrument_id is None:
                continue
            priority = _match_priority(item, canonical, canonical, token)
            if priority > 0:
                candidates.append((priority, instrument_id))

    if not candidates:
        raise EtoroAPIError(f"instrument not found for symbol {token!r}")

    candidates.sort(key=lambda pair: (-pair[0], pair[1]))
    return candidates[0][1]


def get_instrument_metadata(
    instrument_ids: list[int] | tuple[int, ...],
    config: EtoroConfig | None = None,
) -> dict[str, Any]:
    """Fetch display metadata for one or more instrument ids (batch ≤ 50)."""
    from src.trading.connectors.etoro.client import load_config

    cfg = config or load_config()
    ids = [int(i) for i in instrument_ids if int(i) not in _INVALID_INSTRUMENT_IDS and int(i) > 0]
    if not ids:
        raise EtoroAPIError("at least one valid instrument_id is required")
    if len(ids) > 50:
        raise EtoroAPIError("instrumentIds batch limit is 50")

    payload = make_client(cfg).request(
        "GET",
        "/api/v1/market-data/instruments",
        params={"instrumentIds": ",".join(str(i) for i in ids)},
        allow_retry=True,
    )
    items = _extract_metadata_items(payload)
    instruments = [_normalize_metadata_row(item) for item in items if isinstance(item, dict)]
    return {"status": "ok", **_base_payload(cfg), "instruments": instruments}


def _canonical_ticker(token: str) -> str:
    upper = token.strip().upper()
    return _SYMBOL_ALIASES.get(upper, upper)


def _looks_like_ticker(token: str) -> bool:
    return bool(_TICKER_RE.fullmatch(token.strip()))


def _lookup_variants(token: str, canonical: str) -> list[str]:
    upper = token.strip().upper()
    if upper != canonical:
        return [canonical]
    variants = [canonical]
    raw = token.strip()
    if raw and raw.upper() != canonical:
        variants.append(raw.upper())
    return variants


def _search_by_symbol(cfg: EtoroConfig, symbol: str, *, limit: int) -> list[dict[str, Any]]:
    payload = make_client(cfg).request(
        "GET",
        "/api/v1/market-data/search",
        params={"internalSymbolFull": symbol},
        allow_retry=True,
    )
    items = _extract_items(payload)
    return [item for item in items if isinstance(item, dict)]


def _search_by_text(cfg: EtoroConfig, query: str, *, limit: int) -> list[dict[str, Any]]:
    payload = make_client(cfg).request(
        "GET",
        "/api/v1/market-data/search",
        params={"search": query, "limit": limit},
        allow_retry=True,
    )
    items = _extract_items(payload)
    return [item for item in items if isinstance(item, dict)]


def _instrument_id(item: dict[str, Any]) -> int | None:
    for key in ("instrumentId", "instrumentID", "internalInstrumentId"):
        value = item.get(key)
        if value is None:
            continue
        try:
            instrument_id = int(value)
        except (TypeError, ValueError):
            continue
        if instrument_id in _INVALID_INSTRUMENT_IDS or instrument_id < 0:
            return None
        return instrument_id
    return None


def _symbol_full(item: dict[str, Any]) -> str:
    return str(
        item.get("internalSymbolFull")
        or item.get("symbolFull")
        or item.get("symbol")
        or ""
    ).strip()


def _display_name(item: dict[str, Any]) -> str:
    return str(
        item.get("internalInstrumentDisplayName")
        or item.get("instrumentDisplayName")
        or item.get("displayName")
        or ""
    ).strip()


def _match_priority(item: dict[str, Any], lookup: str, canonical: str, original: str) -> int:
    sym = _symbol_full(item).upper()
    display = _display_name(item).upper()
    lookup_u = lookup.upper()
    canonical_u = canonical.upper()
    original_u = original.upper()

    if sym == lookup_u or sym == canonical_u:
        return 100
    if sym == original_u:
        return 95
    if display == original_u or display == canonical_u:
        return 90
    if canonical_u in display and sym.startswith(canonical_u):
        return 50
    if lookup_u in sym:
        return 30
    return 0


def _normalize_instrument_row(item: dict[str, Any]) -> dict[str, Any]:
    instrument_id = _instrument_id(item)
    symbol = _symbol_full(item)
    display = _display_name(item)
    return {
        "instrument_id": instrument_id,
        "symbol": symbol or display,
        "display_name": display,
        "internal_symbol_full": item.get("internalSymbolFull") or item.get("symbolFull"),
        "is_buy_enabled": item.get("isBuyEnabled"),
        "is_tradable": item.get("isCurrentlyTradable"),
        "raw": item,
    }


def _normalize_metadata_row(item: dict[str, Any]) -> dict[str, Any]:
    instrument_id = _instrument_id(item)
    return {
        "instrument_id": instrument_id,
        "symbol": _symbol_full(item) or item.get("symbolFull"),
        "display_name": _display_name(item) or item.get("instrumentDisplayName"),
        "instrument_type_id": item.get("instrumentTypeID") or item.get("instrumentTypeId"),
        "exchange_id": item.get("exchangeID") or item.get("exchangeId"),
        "raw": item,
    }


def _extract_items(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("items", "data", "instruments", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _extract_metadata_items(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("instrumentDisplayDatas", "items", "data", "instruments"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []
