#!/usr/bin/env python3
"""Vara del artefacto frozen para DOS CATÁLOGOS.

Levanta el sidecar onefile con raíces temporales, comprueba el piso curado desde
el endpoint del propio binario y ejecuta una ingesta viva del registro. Nunca usa
el puerto de la aplicación instalada.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PORTS = {25374}
ENTRY_KEYS = {
    "id", "nombre", "tipo", "descripcion_1linea", "official",
    "confianza", "checklist", "fuente",
}
RAW_VISIBLE_JARGON = re.compile(
    r"\b(?:model\s+context\s+protocol|manifest|json-?rpc|streamable-?http|"
    r"stdio|namespace|ownership|npx|pypi|uvx)\b",
    re.IGNORECASE,
)


def _free(port: int) -> bool:
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _request(url: str, *, body: dict | None = None, timeout: float = 25) -> bytes:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers = {
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
        }
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _wait_health(base: str, proc: subprocess.Popen, timeout: float = 90) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            output = proc.stdout.read().decode("utf-8", "replace") if proc.stdout else ""
            raise AssertionError(f"el frozen se cerró durante el arranque:\n{output[-2000:]}")
        try:
            _request(base + "/health", timeout=1.5)
            return
        except Exception:
            time.sleep(0.35)
    raise AssertionError("el frozen no respondió /health dentro de 90 s")


def _events(raw: bytes) -> list[dict[str, Any]]:
    events = []
    for line in raw.decode("utf-8", "replace").splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line.removeprefix("data: ")))
    return events


def _valid_entry(entry: dict) -> bool:
    return (
        isinstance(entry, dict)
        and set(entry) == ENTRY_KEYS
        and entry.get("tipo") in {"remoto", "paquete", "hibrido"}
        and isinstance(entry.get("official"), bool)
        and isinstance(entry.get("confianza"), (int, float))
        and set(entry.get("descripcion_1linea") or {}) == {"es", "en"}
        and set(entry.get("checklist") or {}) == {"es", "en"}
    )


def _visible(entry: dict) -> str:
    return json.dumps({
        "nombre": entry["nombre"],
        "descripcion_1linea": entry["descripcion_1linea"],
        "checklist": entry["checklist"],
    }, ensure_ascii=False)


def _expected_recommended_ids() -> set[str]:
    data = json.loads((ROOT / "catalog" / "recomendados.json").read_text(encoding="utf-8"))
    return {
        entry["id"]
        for entries in data.values()
        for entry in entries
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sidecar", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8305)
    args = parser.parse_args()
    if args.port in FORBIDDEN_PORTS:
        raise SystemExit(f"puerto prohibido: {args.port}")
    if not _free(args.port):
        raise SystemExit(f"el puerto {args.port} no está libre")
    if not args.sidecar.is_file():
        raise SystemExit(f"no existe el sidecar: {args.sidecar}")

    sandbox = Path(tempfile.mkdtemp(prefix="aleph-catalogos-frozen-"))
    proc: subprocess.Popen | None = None
    try:
        env = {
            **os.environ,
            "ALEPH_ROLE": "client",
            "ALEPH_DATA_DIR": str(sandbox / "data"),
            "TMPDIR": str(sandbox / "tmp"),
            "PUPPET_PORT": str(args.port),
            "PORT": str(args.port),
        }
        Path(env["TMPDIR"]).mkdir(parents=True)
        proc = subprocess.Popen(
            [str(args.sidecar), "--port", str(args.port)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        base = f"http://127.0.0.1:{args.port}"
        _wait_health(base, proc)

        local = json.loads(_request(base + "/v1/catalog/local").decode("utf-8"))
        local_items = local.get("items") or []
        local_ids = {entry.get("id") for entry in local_items}
        expected = _expected_recommended_ids()
        assert expected <= local_ids, (
            "el piso curado no viajó completo: "
            f"faltan {sorted(expected - local_ids)}"
        )
        assert all(_valid_entry(entry) for entry in local_items)

        events = _events(_request(
            base + "/v1/catalog/ingest",
            body={"query": "stripe", "locale": "es"},
            timeout=60,
        ))
        assert [event.get("etapa") for event in events] == [
            "leyendo", "limpiando", "clasificando", "veredicto",
        ]
        final = events[-1]
        assert final.get("ok") is True, final
        entries = final.get("entradas") or []
        assert entries and all(_valid_entry(entry) for entry in entries)
        visible = "\n".join(_visible(entry) for entry in entries)
        messages = "\n".join(
            str((event.get("mensaje") or {}).get(lang) or "")
            for event in events for lang in ("es", "en")
        )
        assert not RAW_VISIBLE_JARGON.search(visible + "\n" + messages)

        persisted = sandbox / "data" / "catalog" / "local.json"
        saved = json.loads(persisted.read_text(encoding="utf-8"))
        assert {entry["id"] for entry in entries} <= {entry["id"] for entry in saved}
        print(
            "VERDE · frozen :"
            f"{args.port} · piso={len(expected)} ids únicos · "
            f"ingesta={len(entries)} · etapas 4/4 · schema exacto · jerga visible 0"
        )
        return 0
    finally:
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        shutil.rmtree(sandbox, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
