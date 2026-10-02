"""
observe/replay.py — la tool sintetizada, EJECUTABLE (con gate).

Toma el spec de synthesize_tool + los args que da el modelo y reconstruye la
request real (inyectando los parámetros variables en su lugar). Cierra el lazo
"demostración → herramienta que funciona": el agente la llama con valores nuevos
y la tool pega a la API real del software.

GUARD (de la directiva): writes NO se ejecutan sin gate explícito. Por eso:
  - call(execute=False)  → DRY-RUN: arma la request y la devuelve, NO la manda.
  - call(execute=True) en una tool write/send → exige allow_write=True (el gate;
    en prod, esto es el human-in-the-loop por Telegram). Reads (GET) se permiten.
La auth real (cookies/storage_state de la sesión) se reusará acá en la fase del
local-attach; hoy el replay va por http directo (suficiente para el target benigno).
"""
from __future__ import annotations

import copy
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional


class SynthesizedTool:
    def __init__(self, spec: dict[str, Any]):
        self.spec = spec
        self.name = spec["mcp_tool"]["name"]
        self.label = spec.get("label", self.name)
        self.category = spec.get("category", "read")
        self.input_schema = spec["mcp_tool"]["inputSchema"]

    @property
    def is_write(self) -> bool:
        return self.category in ("write", "send") or \
            self.spec["request"].get("method", "GET").upper() in ("POST", "PUT", "PATCH", "DELETE")

    def _validate_args(self, args: dict[str, Any]) -> None:
        missing = [k for k in self.input_schema.get("required", []) if k not in (args or {})]
        if missing:
            raise ValueError(f"faltan parámetros requeridos: {missing}")

    def build_request(self, args: dict[str, Any]) -> dict[str, Any]:
        """Reconstruye la request concreta inyectando los args en los param_slots."""
        self._validate_args(args)
        req = self.spec["request"]
        body = copy.deepcopy(req.get("body")) if req.get("body") is not None else None
        query = copy.deepcopy(req.get("query")) or {}
        for slot in self.spec.get("param_slots", []):
            name, loc, key = slot["name"], slot["location"], slot["key"]
            if name not in (args or {}):
                continue
            if loc in ("json", "form"):
                if body is None:
                    body = {}
                body[key] = args[name]
            elif loc == "query":
                query[key] = args[name]
        # rearmar la url con la query (posiblemente con params inyectados)
        url = req.get("url") or ""
        parts = urllib.parse.urlsplit(url)
        if query:
            url = urllib.parse.urlunsplit(
                (parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query), parts.fragment))
        headers = {}
        if body is not None:
            headers["Content-Type"] = (
                "application/x-www-form-urlencoded" if req.get("body_kind") == "form"
                else "application/json")
        return {"method": req.get("method", "GET"), "url": url, "headers": headers,
                "body": body, "body_kind": req.get("body_kind")}

    def call(self, args: dict[str, Any], *, execute: bool = False,
             allow_write: bool = False, timeout: float = 15.0,
             subject: Optional[str] = None) -> dict[str, Any]:
        built = self.build_request(args)
        if not execute:
            return {"dry_run": True, "request": built}
        if self.is_write and not allow_write:
            return {"refused": True, "reason": "write gateado — requiere gate explícito (allow_write)",
                    "request": built}
        # [T9-safety] ANTES de pegar a la API real: anti-SSRF sobre la URL reconstruida
        # (la request observada pudo apuntar a interno) + blast-radius/kill-switch si es
        # write. Capa encima del gate allow_write del core; solo puede RECHAZAR.
        try:
            import sys as _sys
            from pathlib import Path as _Path
            _plat = str(_Path(__file__).resolve().parents[2])   # .../platform
            if _plat not in _sys.path:
                _sys.path.insert(0, _plat)
            from safety.guards import guard_replay, SafetyBlocked   # additivo
            try:
                built["url"] = guard_replay(built["url"], subject=subject,
                                            is_write=self.is_write)
            except SafetyBlocked as sb:
                return {"refused": True, "reason": str(sb), "by": "safety",
                        "meta": getattr(sb, "meta", {}), "request": built}
        except ImportError:
            pass  # capa de safety ausente (build incompleto): el core sigue
        return {"dry_run": False, "request": built, "response": self._send(built, timeout)}

    @staticmethod
    def _send(built: dict[str, Any], timeout: float) -> dict[str, Any]:
        body = built.get("body")
        data = None
        if body is not None:
            if built.get("body_kind") == "form":
                data = urllib.parse.urlencode(body).encode("utf-8")
            else:
                data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            built["url"], data=data, method=built["method"], headers=built.get("headers", {}))
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                text = raw.decode("utf-8", "replace")
                parsed: Optional[Any] = None
                try:
                    parsed = json.loads(text)
                except (json.JSONDecodeError, ValueError):
                    pass
                return {"status": r.status, "json": parsed, "text": text[:2000]}
        except urllib.error.HTTPError as e:  # type: ignore[attr-defined]
            return {"status": e.code, "error": e.reason}
        except Exception as e:
            return {"status": None, "error": str(e)}
