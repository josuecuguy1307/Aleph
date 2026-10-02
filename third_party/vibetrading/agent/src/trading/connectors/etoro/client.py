"""HTTP transport and path builders for the eToro Public API.

Paper-vs-live is structural: ``profile == "paper"`` routes to ``/demo`` API
paths; live profiles use production paths on the same host. eToro uses one API
key pair for both environments — the configured profile selects paths, not
different credentials.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urljoin

import requests

from src.config.paths import get_runtime_root

logger = logging.getLogger(__name__)

CONFIG_FILENAME = "etoro.json"
BASE_URL = "https://public-api.etoro.com"
PAPER_GUARD = "path_separated_key_bound"

PROFILE_ENVIRONMENTS = {
    "paper": "paper",
    "live-readonly": "live",
    "live": "live",
}

READ_BACKOFF: tuple[float, ...] = (0.5, 1.5, 4.0)
MAX_READ_RETRIES = 3


class EtoroConfigError(RuntimeError):
    """Raised when eToro connector configuration is missing or invalid."""


class EtoroAPIError(RuntimeError):
    """Raised when eToro returns an auth, HTTP, network, or JSON error."""


Transport = Callable[..., requests.Response]


@dataclass(frozen=True)
class EtoroConfig:
    """eToro connector connection settings.

    Args:
        api_key: eToro Public API key (shared across demo and real paths).
        user_key: eToro user key (shared across demo and real paths).
        profile: ``paper``, ``live-readonly`` or ``live``.
        timeout: Network timeout in seconds.
        readonly: Always true for this layer unless trade profiles call writes.
    """

    api_key: str = ""
    user_key: str = ""
    profile: str = "paper"
    timeout: float = 15.0
    readonly: bool = True

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None = None) -> "EtoroConfig":
        """Build a config from a JSON-like mapping, normalizing the profile."""
        payload = dict(data or {})
        profile = str(payload.get("profile") or "paper").strip().lower()
        if profile not in PROFILE_ENVIRONMENTS:
            raise EtoroConfigError("profile must be 'paper', 'live-readonly' or 'live'")
        return cls(
            api_key=str(payload.get("api_key") or "").strip(),
            user_key=str(payload.get("user_key") or "").strip(),
            profile=profile,
            timeout=float(payload.get("timeout") or 15.0),
            readonly=bool(payload.get("readonly", True)),
        )

    def with_overrides(
        self,
        *,
        api_key: str | None = None,
        user_key: str | None = None,
        profile: str | None = None,
    ) -> "EtoroConfig":
        """Return a copy with CLI/tool overrides applied."""
        payload = asdict(self)
        if api_key is not None:
            payload["api_key"] = api_key
        if user_key is not None:
            payload["user_key"] = user_key
        if profile is not None:
            payload["profile"] = profile
        return EtoroConfig.from_mapping(payload)

    @property
    def environment(self) -> str:
        """Return ``paper`` or ``live`` for this profile."""
        return PROFILE_ENVIRONMENTS.get(self.profile, "paper")

    @property
    def is_paper(self) -> bool:
        """Return whether this profile targets demo API paths."""
        return self.environment == "paper"


_OVERRIDE_KEYS = ("api_key", "user_key", "profile")
_ENV_KEY_MAP = {
    "api_key": "ETORO_API_KEY",
    "user_key": "ETORO_USER_KEY",
}


def build_config(
    profile_config: Mapping[str, Any] | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> EtoroConfig:
    """Resolve config: saved file ← profile defaults ← CLI overrides."""
    base = asdict(load_config())
    for key, value in dict(profile_config or {}).items():
        if value is not None:
            base[key] = value
    cfg = EtoroConfig.from_mapping(base)
    clean = {k: v for k, v in dict(overrides or {}).items() if k in _OVERRIDE_KEYS and v not in (None, "")}
    return cfg.with_overrides(**clean) if clean else cfg


def config_path() -> Path:
    """Return the user-level eToro config path."""
    return get_runtime_root() / CONFIG_FILENAME


def load_config() -> EtoroConfig:
    """Load eToro settings from ``~/.vibe-trading/etoro.json`` and env fallbacks."""
    path = config_path()
    base: dict[str, Any] = {}
    if path.exists():
        try:
            base = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise EtoroConfigError(f"invalid eToro config at {path}: {exc}") from exc
    for field, env_name in _ENV_KEY_MAP.items():
        env_val = os.getenv(env_name, "").strip()  # noqa: env-gate — connector credential helper
        if env_val:
            base[field] = env_val
    if not base:
        return EtoroConfig()
    return EtoroConfig.from_mapping(base)


def save_config(config: EtoroConfig) -> Path:
    """Persist eToro settings with owner-only permissions."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def _missing_fields(cfg: EtoroConfig) -> list[str]:
    missing: list[str] = []
    if not cfg.api_key:
        missing.append("api_key")
    if not cfg.user_key:
        missing.append("user_key")
    return missing


def public_config(cfg: EtoroConfig) -> dict[str, Any]:
    return {
        "profile": cfg.profile,
        "environment": cfg.environment,
        "readonly": cfg.readonly,
        "timeout": cfg.timeout,
        "api_key_configured": bool(cfg.api_key),
        "user_key_configured": bool(cfg.user_key),
        "paper_guard": PAPER_GUARD,
    }


def execution_root(cfg: EtoroConfig) -> str:
    return "/api/v2/trading/execution/demo" if cfg.is_paper else "/api/v2/trading/execution"


def execution_v1_root(cfg: EtoroConfig) -> str:
    return "/api/v1/trading/execution/demo" if cfg.is_paper else "/api/v1/trading/execution"


def info_root(cfg: EtoroConfig) -> str:
    return "/api/v1/trading/info/demo" if cfg.is_paper else "/api/v1/trading/info"


def trade_history_root(cfg: EtoroConfig) -> str:
    return "/api/v1/trading/info/trade/demo" if cfg.is_paper else "/api/v1/trading/info/trade"


def aggregate_portfolio_path(cfg: EtoroConfig) -> str:
    return f"{info_root(cfg)}/aggregate-portfolio"


def positions_root(cfg: EtoroConfig) -> str:
    return "/api/v2/trading/demo" if cfg.is_paper else "/api/v2/trading"


def copy_root(cfg: EtoroConfig) -> str:
    return "/api/v2/trading/copy/demo" if cfg.is_paper else "/api/v2/trading/copy"


class EtoroClient:
    """Thin REST client for eToro Public API."""

    def __init__(self, cfg: EtoroConfig, transport: Transport | None = None):
        self.cfg = cfg
        self._transport = transport or requests.request

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        request_id: str | None = None,
        allow_retry: bool = False,
    ) -> Any:
        missing = _missing_fields(self.cfg)
        if missing:
            raise EtoroConfigError(f"missing {', '.join(missing)}")

        req_id = (request_id or str(uuid.uuid4())).strip()
        url = urljoin(BASE_URL + "/", path.lstrip("/"))
        headers = {
            "x-api-key": self.cfg.api_key,
            "x-user-key": self.cfg.user_key,
            "x-request-id": req_id,
            "Accept": "application/json",
        }
        if json_body is not None:
            headers["Content-Type"] = "application/json"

        attempts = MAX_READ_RETRIES if allow_retry else 1
        backoff = READ_BACKOFF
        last_exc: Exception | None = None

        for attempt in range(attempts):
            try:
                response = self._transport(
                    method.upper(),
                    url,
                    headers=headers,
                    params=dict(params or {}),
                    json=json_body,
                    timeout=self.cfg.timeout,
                )
            except requests.RequestException as exc:
                last_exc = exc
                if allow_retry and attempt + 1 < attempts:
                    time.sleep(backoff[min(attempt, len(backoff) - 1)])
                    continue
                raise EtoroAPIError(f"network error: {exc}") from exc

            if response.status_code == 429 and allow_retry and attempt + 1 < attempts:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else backoff[min(attempt, len(backoff) - 1)]
                time.sleep(delay)
                continue

            if response.status_code >= 400:
                detail = _response_error_body(response)
                raise EtoroAPIError(f"HTTP {response.status_code}: {detail}")

            if not response.content:
                return {}
            try:
                return response.json()
            except ValueError as exc:
                raise EtoroAPIError(f"invalid JSON response: {exc}") from exc

        if last_exc is not None:
            raise EtoroAPIError(f"network error: {last_exc}")
        raise EtoroAPIError("request failed without response")


def _build_default_client(cfg: EtoroConfig) -> EtoroClient:
    """Build the production HTTP client for one eToro configuration."""
    return EtoroClient(cfg)


_default_client_factory: Callable[[EtoroConfig], EtoroClient] = _build_default_client


def make_client(cfg: EtoroConfig) -> EtoroClient:
    """Build the REST client for a config (tests may override via ``set_client_factory``)."""
    return _default_client_factory(cfg)


def set_client_factory(
    factory: Callable[[EtoroConfig], EtoroClient] | None = None,
) -> None:
    """Override or reset the connector client factory (used by unit tests)."""
    global _default_client_factory
    _default_client_factory = factory or _build_default_client


def _response_error_body(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return (response.text or "").strip()[:500]
    if isinstance(payload, dict):
        for key in ("errorMessage", "message", "detail", "error"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return json.dumps(payload)[:500]
