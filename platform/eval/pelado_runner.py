#!/usr/bin/env python
"""PELADO runner — mismo modelo, mismo prompt, SIN tools (EVAL-FRAMEWORK-SPEC §2).

El archivo de entrada NO se oculta: se renderiza como TEXTO y se le da al modelo
junto al prompt de la tarea (que falle por CAPACIDAD, no por privarlo del input).
Una sola llamada de chat sin `tools`. Se guarda el transcript crudo y se intenta
materializar cualquier artifact (xlsx) que el modelo logre producir — un modelo
pelado solo puede emitir texto, así que típicamente NO podrá escribir el binario.
Luego el MISMO checker mecánico del task-set decide COMPLETÓ.

Uso: pelado_runner.py --config config.yaml --task T5 --model qwen3-8b
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml
from openpyxl import load_workbook

HERE = Path(__file__).resolve().parent

# MISMO system prompt que el equipado salvo que se le AVISA que no tiene tools y que
# debe entregar el resultado en su respuesta. Mantenemos el rol/altura idénticos para
# que la brecha medida sea de CAPACIDAD-CON-vs-SIN-equipo, no de instrucción distinta.
SYSTEM_PROMPT = (
    "You are an autonomous analyst agent. The task input is provided to you below as "
    "text (the spreadsheet contents are rendered inline). You do NOT have any tools: "
    "no file system, no Python execution, no ability to open or write files. Produce "
    "the complete deliverable directly in your reply, as fully as you can from your own "
    "capability. If the deliverable is a spreadsheet, describe its sheets, the exact "
    "live formulas, the conditional-formatting rules, the F/U labels and the bridge "
    "text in full."
)


def render_fixture_as_text(xlsx_path):
    wb = load_workbook(xlsx_path, data_only=True)
    lines = [f"### CONTENIDO DEL ARCHIVO {xlsx_path.name} (renderizado como texto):"]
    for sn in wb.sheetnames:
        ws = wb[sn]
        lines.append(f"\n--- Hoja: {sn} ---")
        for row in ws.iter_rows(values_only=True):
            lines.append("\t".join("" if v is None else str(v) for v in row))
    return "\n".join(lines)


def chat_no_tools(lane, model_id, messages, max_tokens):
    key = os.environ.get(lane["api_key_env"], "")
    body = {"model": model_id, "messages": messages,
            "temperature": 0.1, "max_tokens": max_tokens}  # SIN 'tools'
    r = requests.post(lane["base_url"].rstrip("/") + "/chat/completions",
                      headers={"Authorization": f"Bearer {key}"},
                      json=body, timeout=600)
    r.raise_for_status()
    return r.json()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(HERE / "config.yaml"))
    ap.add_argument("--task", required=True)
    ap.add_argument("--model", required=True)
    a = ap.parse_args()

    cfg = yaml.safe_load(Path(a.config).read_text())
    cfg["python_bin"] = str((HERE / cfg["python_bin"]).absolute())
    taskset_path = (HERE / cfg["taskset"]).resolve()
    taskset_dir = taskset_path.parent
    ts = yaml.safe_load(taskset_path.read_text())
    fixtures_root = (taskset_dir / ts["fixtures_root"]).resolve()

    task = next(t for t in ts["tasks"] if t["id"] == a.task)
    model = next(m for m in cfg["models"] if m["name"] == a.model)
    # mismo selector de carril que el runner (primer carril sano con mapping)
    lane = None
    for L in cfg["lanes"]:
        if L["name"] not in model["lane_ids"]:
            continue
        hurl = L.get("health_url")
        if hurl:
            try:
                requests.get(hurl, timeout=4)
            except Exception:
                continue
        lane = L
        break
    if lane is None:
        raise RuntimeError("sin carril vivo")
    model_id = model["lane_ids"][lane["name"]]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_dir = HERE / cfg.get("workdir_root", "runs") / f"PELADO-{a.task}-{stamp}"
    workdir = run_dir / model["name"] / task["id"]
    workdir.mkdir(parents=True)

    fixture = fixtures_root / task["fixtures"][0]
    rendered = render_fixture_as_text(fixture)
    user_content = task["prompt"] + "\n\n" + rendered
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content}]

    t0 = time.time()
    resp = chat_no_tools(lane, model_id, messages, cfg["limits"]["max_output_tokens"])
    wall = round(time.time() - t0, 1)
    u = resp.get("usage") or {}
    msg = resp["choices"][0]["message"]
    content = msg.get("content") or ""

    # transcript crudo
    (workdir / "pelado_response.md").write_text(content)
    (workdir / "pelado_prompt.txt").write_text(user_content)

    # MISMO checker mecánico: el pelado no pudo escribir varianzas.xlsx (sin tools),
    # así que el artifact no existe → COMPLETÓ = NO. Se ejecuta igual para honestidad.
    import subprocess
    checker = taskset_dir / task["checker"]
    chk = subprocess.run([cfg["python_bin"], str(checker), str(workdir)],
                         capture_output=True, text=True, timeout=120)
    try:
        diag = json.loads(chk.stdout.strip().splitlines()[-1])
    except Exception:
        diag = {"raw": chk.stdout[-300:]}

    result = {"model": model["name"], "task": task["id"], "lane": lane["name"],
              "modo": "PELADO_sin_tools", "modelo_servido": resp.get("model"),
              "completo": chk.returncode == 0, "wall_s": wall,
              "tokens_in": u.get("prompt_tokens", 0),
              "tokens_out": u.get("completion_tokens", 0),
              "respuesta_chars": len(content), "checker": diag}
    (run_dir / "results.json").write_text(json.dumps([result], indent=2, ensure_ascii=False))
    print(json.dumps(result, ensure_ascii=False))
    print(str(run_dir), file=sys.stderr)


if __name__ == "__main__":
    main()
