#!/usr/bin/env python3
"""
cli.py — entrypoint del motor de inspección.

    recon <url> <intent> [opciones]

Por defecto abre un Chromium headed y espera que el HUMANO demuestre la acción
(tipea, hace click, apretá ENTER al terminar). Con --demo se corre una
demostración scripted reproducible. Imprime el ObservedAction (request aislada +
schema de campos variables) y el HAR filtrado en JSON.

Ejemplos:
  python platform/inspection/cli.py recon https://app.ejemplo.com "registrar asistencia" --headed
  python platform/inspection/cli.py recon https://app.ejemplo.com "registrar asistencia" \
      --demo platform/inspection/fixtures/demos/attendance.py:demo \
      --login-url https://app.ejemplo.com/login --ready-url /dashboard --storage-key app.ejemplo.com
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
from pathlib import Path

# bootstrap: poné platform/ en el path para importar el paquete `inspection`
_PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(_PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_DIR))

from inspection.bridge import SpaceEmitter
from inspection.observe.correlate import correlate
from inspection.observe.recorder import record_demonstration
from inspection.observe.synthesize import synthesize_capability
from inspection.session.cloud import CloudSession


def _load_demo(spec: str):
    """'ruta/al/archivo.py:func' → callable."""
    if ":" not in spec:
        raise SystemExit("--demo debe ser 'ruta.py:funcion'")
    path, func = spec.rsplit(":", 1)
    p = Path(path).resolve()
    if not p.exists():
        raise SystemExit(f"--demo: no existe {p}")
    mspec = importlib.util.spec_from_file_location("aleph_demo_mod", p)
    mod = importlib.util.module_from_spec(mspec)
    mspec.loader.exec_module(mod)
    fn = getattr(mod, func, None)
    if fn is None:
        raise SystemExit(f"--demo: {p} no define {func}")
    return fn


async def _run(args) -> int:
    ready_when = {}
    if args.ready_url:
        ready_when = {"url": args.ready_url}
    elif args.ready_selector:
        ready_when = {"selector": args.ready_selector}

    session = CloudSession(
        login_url=args.login_url,
        ready_when=ready_when,
        wait_human=bool(args.login_url) and not ready_when,
        headless=not args.headed,
        storage_key=args.storage_key,
        channel=args.channel,
    )
    demo = _load_demo(args.demo) if args.demo else None

    # --space: emite el ciclo de vida al Cuarto en vivo (mismo canal SSE que el run)
    emitter = SpaceEmitter(args.space, public=True, claim=True) if args.space else None

    async def on_phase(phase, info):
        if emitter is None:
            return
        if phase == "detectado":
            emitter.software_detectado(label=info.get("label") or info.get("host") or "Software",
                                       host=info.get("host", ""), url=info.get("url", ""),
                                       title=info.get("title", ""))
        elif phase == "analizando":
            emitter.inspeccion_analizando(requests=info.get("requests"))

    ctx = await session.provide_context()
    try:
        bundle = await record_demonstration(
            ctx, intent=args.intent, target_url=args.url,
            demo=demo, settle_ms=args.settle, with_a11y=not args.no_a11y,
            on_event=on_phase,
        )
        action = correlate(bundle, top_n=args.top)
        if emitter is not None:
            p = action.primary_request
            emitter.accion_observada(method=p.method if p else None, path=p.path if p else None,
                                     fields=[f.name for f in action.field_schema if f.variable])
            cap = synthesize_capability(action)
            emitter.tool_sintetizada(label=cap["label"], category=cap["category"], fields=cap["params"])
            emitter.close()
            print(f"[recon] emití el ciclo al space '{args.space}' (Cuarto: ?recon={args.space})")
    finally:
        await ctx.aclose()

    out = json.dumps(action.to_dict(), indent=2, ensure_ascii=False, default=str)
    if args.out:
        Path(args.out).write_text(out, encoding="utf-8")
        print(f"[recon] ObservedAction escrito en {args.out}")
    else:
        print(out)
    return 0 if action.primary_request is not None else 2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="recon", description="Motor de inspección de contexto (capas 1→3)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("recon", help="inspecciona una acción demostrada en un software web")
    r.add_argument("url", help="URL del target a inspeccionar")
    r.add_argument("intent", help="qué acción se va a demostrar, p.ej. 'registrar asistencia'")
    r.add_argument("--demo", help="demostración scripted 'archivo.py:func' (si falta: humano + ENTER)")
    r.add_argument("--headed", action="store_true", help="navegador visible (default headless)")
    r.add_argument("--login-url", help="URL de login si el target requiere auth")
    r.add_argument("--ready-url", help="substring de URL que indica login terminado")
    r.add_argument("--ready-selector", help="selector CSS que indica login terminado")
    r.add_argument("--storage-key", help="clave para guardar/reusar el storage_state cifrado")
    r.add_argument("--channel", help="canal de browser, p.ej. 'chrome'")
    r.add_argument("--settle", type=int, default=2000, help="ms de espera de red por fase (default 2000)")
    r.add_argument("--top", type=int, default=6, help="cuántos candidatos mostrar en el HAR filtrado")
    r.add_argument("--no-a11y", action="store_true", help="no capturar el árbol de accesibilidad")
    r.add_argument("--space", help="emite el ciclo de vida a este space → el Cuarto lo anima (?recon=<space>)")
    r.add_argument("--out", help="escribir el ObservedAction a un archivo en vez de stdout")
    args = ap.parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
