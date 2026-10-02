"""
gate_shim.py — GATE OBLIGATORIO antes de la matriz completa (Opción C).

Corre 1 celda de finanzas con el brain = claude-code-opus (shim) y VERIFICA, contra el
entorno real, que:
  (a) el tool_call round-trippea por el HARNESS DE ALEPH — Aleph ejecuta worldbank_series
      contra el server real y devuelve un resultado REAL (no Claude Code internamente), y
  (b) model_final = la ruta Claude-Code-Opus (claude-code-opus-4.8).

Si el shim NO pasa los tool-calls limpio (no se ejecutó la tool, o el resultado no es real,
o model_final no es la ruta del shim) → ABORTA con exit 2 y reporta. NO finge.

Correr con PUPPET_OSS_DIRECT=0 para que un fallo del shim NO se enmascare con el OSS local.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import isolated_runner as ir   # noqa
import scorer as sc            # noqa
from cases import CASES        # noqa

EXPECT_MODEL = "claude-code-opus-4.8"


def main():
    case = CASES["finanzas"]
    print(f"[gate] corriendo finanzas con brain={EXPECT_MODEL} (shim claude -p Opus)…", flush=True)
    res = ir.run(case["recipe"], case["prompt"], model="claude-code", deadline_s=300)
    sco = sc.score(case, res)

    mf = res.get("model_final")
    tcs = res.get("tool_calls", []) or []
    wb = next((t for t in tcs if t.get("tool") == "worldbank_series"), None)
    wb_exec = bool(wb and wb.get("executed") and not wb.get("is_error"))
    real_result = (wb.get("result") if wb else "") or ""

    print("\n=== EVIDENCIA ===")
    print("ok:           ", res.get("ok"))
    print("model_final:  ", mf, "  (esperado:", EXPECT_MODEL + ")")
    print("error:        ", res.get("error"))
    print("tools ejec.:  ", [t["tool"] for t in tcs if t.get("executed")])
    print("worldbank result (real, de Aleph):", str(real_result)[:220])
    print("answer:       ", (res.get("answer") or "")[:240])
    print("score:        ", sco["status"], sco["verdict"], "axes=", sco["axes"])

    # criterios de gate
    checks = {
        "model_final == ruta shim": mf == EXPECT_MODEL,
        "worldbank EJECUTÓ por Aleph (real, sin error)": wb_exec,
        "resultado trae dato real (no vacío/no error)": bool(real_result) and "tool error" not in real_result.lower(),
        "answer grounded (cita el dato)": sco["axes"].get("grounding", 0) >= 1,
    }
    print("\n=== GATE CHECKS ===")
    ok = True
    for k, v in checks.items():
        print(f"  {'✅' if v else '❌'} {k}")
        ok = ok and v

    out = {"gate": "PASS" if ok else "FAIL", "model_final": mf, "checks": checks,
           "worldbank_result_head": str(real_result)[:300], "answer_head": (res.get("answer") or "")[:300],
           "score": sco}
    (HERE / "report" / "gate_shim_result.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))

    if ok:
        print("\n🟢 GATE PASS — tool round-trip por Aleph OK + model_final = ruta Claude-Code-Opus. "
              "Habilitada la matriz completa.")
        sys.exit(0)
    else:
        print("\n⛔ GATE FAIL — el shim NO pasó los tool-calls limpio. ABORTO la matriz (no finjo). "
              "Ver report/gate_shim_result.json.")
        sys.exit(2)


if __name__ == "__main__":
    main()
