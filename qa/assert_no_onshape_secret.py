#!/usr/bin/env python3
"""Gate de build: el client_secret local de Onshape no puede viajar.

Lee el valor sólo para compararlo byte-a-byte; jamás lo imprime. Además rechaza
el nombre del archivo privado dentro del artefacto.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _files(target: Path):
    if target.is_file():
        yield target
    elif target.is_dir():
        yield from (p for p in target.rglob("*") if p.is_file())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", action="append", required=True)
    parser.add_argument(
        "--local-config",
        default=os.path.expanduser("~/.aleph/onshape.local.json"),
    )
    args = parser.parse_args()

    secret = b""
    config = Path(args.local_config)
    if config.is_file():
        try:
            value = json.loads(config.read_text(encoding="utf-8")).get("client_secret")
            if value:
                secret = str(value).encode("utf-8")
        except Exception:
            print("✗ no pude leer el JSON privado de Onshape", file=sys.stderr)
            return 2

    failures: list[str] = []
    scanned = 0
    for raw_target in args.target:
        target = Path(raw_target)
        if not target.exists():
            failures.append(f"target ausente: {target}")
            continue
        for path in _files(target):
            scanned += 1
            if path.name.lower() == "onshape.local.json":
                failures.append(f"archivo privado empaquetado: {path}")
                continue
            if not secret:
                continue
            try:
                if secret in path.read_bytes():
                    failures.append(f"client_secret encontrado: {path}")
            except OSError:
                failures.append(f"no pude inspeccionar: {path}")

    if failures:
        print("✗ GATE OAuth: el artefacto no es distribuible", file=sys.stderr)
        for failure in failures:
            print("  - " + failure, file=sys.stderr)
        return 1
    if not secret:
        # ⚠️ VERDE VACÍO, DICHO EN VOZ ALTA. Sin el archivo privado no hay valor contra el
        # cual comparar: lo único que corrió fue el chequeo de NOMBRE. Decir
        # «client_secret ausente» acá sería afirmar algo que no se midió — el fallo mudo
        # que el contrato del repo prohíbe. El gate no falla (una máquina de build limpia
        # legítimamente no tiene el archivo), pero no se atribuye una verificación que no hizo.
        print(f"⚠ GATE OAuth: NO se comparó ningún valor — {config} no existe. "
              f"Sólo se verificó que el archivo privado no viaje "
              f"({scanned} archivos inspeccionados).")
        return 0
    print(f"✓ GATE OAuth: client_secret ausente ({scanned} archivos inspeccionados)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
