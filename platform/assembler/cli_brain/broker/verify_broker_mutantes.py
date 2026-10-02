#!/usr/bin/env python3
"""verify_broker_mutantes.py — ¿las varas del broker pueden dar ROJO?

Copia `platform/` a un temporal, le rompe UNA cosa por vez, y corre las varas contra la
copia rota. **Cada mutante tiene que morir.** Si una vara pasa en verde con el código roto,
esa vara no mide eso y hay que decirlo.

⚠️ `PYTHONDONTWRITEBYTECODE=1` en los hijos: sin eso, un `.pyc` del árbol sano puede
sobrevivir a la copia y el mutante corre… sin mutar.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_PLATFORM = Path(__file__).resolve().parents[3]
B = "assembler/cli_brain/broker"

MUTANTES = [
    ("M1 · el dueño deja de salir de la clave: todos comparten uno solo",
     f"{B}/vocabulario.py",
     '''    partes = c.split(":")
    if len(partes) >= 4 and partes[1].strip() and partes[1].strip() != "-":
        return partes[1].strip()
    return c''',
     '''    return "todos"''',
     "V5", "verify_broker", "--solo grok"),

    # ⚠️ M2 quedó SIN SENTIDO al apagarse la jaula por decisión del dueño: «arrancar sin
    # sandbox» es ahora el comportamiento NORMAL, no el roto. Se re-apunta a lo que sí sigue
    # siendo un defecto: que la config del sandbox NO entre en la huella, porque entonces un
    # proceso arrancado con jaula se reusaría para un turno que la pidió apagada (y al revés).
    ("M2 · el `sandbox` sale de la huella de config (reusaría un proceso con la jaula equivocada)",
     f"{B}/vocabulario.py",
     '''def huella_de_config''',
     '''def huella_de_config_DESACTIVADA''',
     "V4", "verify_broker", "--solo codex"),

    ("M3 · el pool no separa por dueño en la clave",
     f"{B}/vocabulario.py",
     '''        base = f"{self.forma}|{self.provider_id}|{self.dueno}|{self.huella_config}"''',
     '''        base = f"{self.forma}|{self.provider_id}|{self.huella_config}"''',
     "V5/C2", "verify_vocabulario", ""),

    ("M4 · `apagar_todo` saca del pool pero NO cierra los procesos",
     f"{B}/pool.py",
     '''        try:
            v.adaptador.cerrar()
        except Exception:                                   # noqa: BLE001
            pass''',
     '''        pass''',
     "V6", "verify_broker", "--solo grok"),

    ("M5 · grok arranca SIN `--agent-profile` (21,7k → 32,9k tokens)",
     f"{B}/grok_acp.py",
     '''        perfil = (self.cfg.get("perfil") or "").strip()
        if perfil:
            argv += ["--agent-profile", perfil]     # ← sin esto, 21,7k → 32,9k tokens''',
     '''        pass''',
     "V3b", "verify_broker", "--solo grok"),

    ("M6 · el usage se normaliza antes del ledger (el ledger queda ciego)",
     f"{B}/claude_streamjson.py",
     '''            usage_bruto=dict(u),          # crudo: `usage_del_cli` conoce sus nombres''',
     '''            usage_bruto={"prompt_tokens": u.get("input_tokens")},''',
     "V3", "verify_broker", "--solo claude"),

    ("M7 · el broker se saltea el fail-closed de exec_events",
     "assembler/cli_brain/base.py",
     '''                    if _res.ok and _res.exec_events > 0:''',
     '''                    if False and _res.ok and _res.exec_events > 0:''',
     "V4b", "verify_broker", "--solo codex"),

    ("M8 · la huella ignora la config (dos jaulas distintas, un solo proceso)",
     f"{B}/vocabulario.py",
     '''    return hashlib.sha256(
        json.dumps(cfg, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()[:32]''',
     '''    return "siempre-la-misma"''',
     "C3", "verify_vocabulario", ""),

    ("M9 · la Session deja de comprobar el dueño (cruce silencioso)",
     f"{B}/pool.py",
     '''        if ses.dueno != harness.dueno:''',
     '''        if False and ses.dueno != harness.dueno:''',
     "C-pool", "verify_pool", ""),
]


def main() -> int:
    print("=" * 74)
    print("MUTANTES DEL BROKER — cada uno tiene que MATAR a su vara")
    print("=" * 74)
    vivos = []
    for i, (titulo, rel, viejo, nuevo, caso, vara, args) in enumerate(MUTANTES, 1):
        tmp = tempfile.mkdtemp(prefix=f"mut-broker-{i}-")
        dest = os.path.join(tmp, "platform")
        shutil.copytree(_PLATFORM, dest,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        objetivo = os.path.join(dest, rel)
        src = open(objetivo).read()
        if src.count(viejo) != 1:
            print(f"\n{titulo}\n  ⚠️  NO SE PUDO APLICAR ({src.count(viejo)} coincidencias) "
                  f"— mutante inválido, no cuenta como muerto")
            vivos.append(titulo + "  [no aplicable]")
            shutil.rmtree(tmp, ignore_errors=True)
            continue
        open(objetivo, "w").write(src.replace(viejo, nuevo))
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
                   PUPPET_CLI_EVENTOS=os.path.join(tmp, "eventos.jsonl"),
                   PUPPET_CLI_BROKER_LIBRO=os.path.join(tmp, "libro.jsonl"))
        cmd = [sys.executable, "-m", f"assembler.cli_brain.broker.{vara}"]
        if args:
            cmd += args.split()
        r = subprocess.run(cmd, cwd=dest, capture_output=True, text=True, timeout=1800,
                           env=env)
        salida = r.stdout + r.stderr
        rojas = [l.strip() for l in salida.splitlines() if l.strip().startswith("❌")]
        print(f"\n{titulo}")
        print(f"  rompe [{caso}] · vara={vara} {args} · exit={r.returncode} · "
              f"rojas={len(rojas)}")
        for l in rojas[:3]:
            print(f"      {l[:150]}")
        if r.returncode != 0:
            print("  ✅ MUTANTE MUERTO")
        else:
            print("  ❌ MUTANTE VIVO — la vara pasó en verde con el código roto")
            vivos.append(titulo)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + "-" * 74)
    print(f"{len(MUTANTES) - len(vivos)}/{len(MUTANTES)} mutantes muertos")
    for v in vivos:
        print(f"   VIVO: {v}")
    return 1 if vivos else 0


if __name__ == "__main__":
    sys.exit(main())
