#!/usr/bin/env python
"""platform/eval — runner PARAMETRIZABLE del model-watch (clase PARAMETRIZABLE del ledger).

Cero nicho y cero modelo hardcodeado: task-set, modelos, carriles y límites vienen
TODOS de un config YAML. Produce la tabla modelo×tarea: completó (checker mecánico),
tokens, wall. La calidad 0-2 la asigna el juez DESPUÉS contra la rúbrica pre-escrita
del task-set (capa humana, no vive acá).

Uso:  .venv/bin/python runner.py --config config.yaml [--models a,b] [--tasks T1,T2]

Carriles: lista ordenada en config; se usa el primero cuyo health responde y que
tenga mapping para el modelo. API keys SIEMPRE por nombre de env var (api_key_env)
— jamás se imprimen ni se loguean. 429 → backoff serializado (el wall lo absorbe).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

HERE = Path(__file__).resolve().parent

SYSTEM_PROMPT = (
    "You are an autonomous analyst agent working inside a sandbox directory. "
    "The task fixtures are already in your working directory. You have tools to "
    "list files, read files, write files and run Python (pandas, openpyxl, "
    "statsmodels, matplotlib, nbformat available). Work step by step, VERIFY your "
    "output by re-reading or re-running it, and when the deliverable is written to "
    "disk call task_done. File paths are relative to the working directory. "
    "IMPORTANT: tool call arguments must be a valid JSON object — e.g. run_python "
    'takes {"code": "<python source as a JSON-escaped string>"}; never emit raw '
    "code outside the JSON string."
)

TOOLS = [
    {"type": "function", "function": {
        "name": "list_files", "description": "List files in the working directory.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a text file (first 6000 chars). Binary files (xlsx) must be inspected via run_python.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Write full text content to a file (overwrites).",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "run_python",
        "description": "Run Python code in the working directory. Returns stdout+stderr (truncated).",
        "parameters": {"type": "object", "properties": {
            "code": {"type": "string"}}, "required": ["code"]}}},
    {"type": "function", "function": {
        "name": "task_done",
        "description": "Signal that the deliverable is written to disk and verified.",
        "parameters": {"type": "object", "properties": {
            "summary": {"type": "string"}}, "required": ["summary"]}}},
]


def pick_lane(cfg, model):
    """Primer carril sano que tenga mapping para este modelo."""
    for lane in cfg["lanes"]:
        if lane["name"] not in model["lane_ids"]:
            continue
        hurl = lane.get("health_url")
        if hurl:
            try:
                requests.get(hurl, timeout=4)
            except Exception:
                continue
        return lane
    raise RuntimeError(f"sin carril vivo para {model['name']}")


def chat(lane, model_id, messages, limits):
    key = os.environ.get(lane["api_key_env"], "")
    body = {"model": model_id, "messages": messages, "tools": TOOLS,
            "temperature": 0.1, "max_tokens": limits["max_output_tokens"]}
    # timeout de request por turno: viene del config (CARRIL LOCAL qwen3:8b emite
    # <think> y un turno puede pasar 180s); default 180 conserva el comportamiento previo.
    req_to = limits.get("request_timeout", 180)
    for attempt in range(6):
        r = requests.post(lane["base_url"].rstrip("/") + "/chat/completions",
                          headers={"Authorization": f"Bearer {key}"},
                          json=body, timeout=req_to)
        if r.status_code == 429:           # rate limit → serializar con backoff real
            wait = min(60, 5 * 2 ** attempt)
            time.sleep(wait)
            continue
        if r.status_code >= 500:
            time.sleep(4)
            continue
        if r.status_code == 400 and "tool_use_failed" in r.text:
            # el modelo emitió una tool call malformada — fallo de GENERACIÓN,
            # no de request: regenerar (cuenta contra los mismos reintentos)
            time.sleep(2)
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
        return r.json()
    raise RuntimeError(f"sin respuesta tras reintentos (HTTP {r.status_code})")


def exec_tool(name, args, workdir, cfg):
    if name == "list_files":
        return "\n".join(sorted(p.name for p in workdir.iterdir()))
    if name == "read_file":
        p = (workdir / args["path"]).resolve()
        if workdir.resolve() not in p.parents and p != workdir.resolve():
            return "ERROR: path fuera del sandbox"
        try:
            return p.read_text(errors="replace")[:6000]
        except Exception as e:
            return f"ERROR: {e}"
    if name == "write_file":
        p = (workdir / args["path"]).resolve()
        if workdir.resolve() not in p.parents:
            return "ERROR: path fuera del sandbox"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(args["content"])
        return f"ok: {len(args['content'])} chars -> {args['path']}"
    if name == "run_python":
        code_f = workdir / "._snippet.py"
        code_f.write_text(args["code"])
        try:
            r = subprocess.run([cfg["python_bin"], str(code_f)], cwd=workdir,
                               capture_output=True, text=True,
                               timeout=cfg["limits"]["python_timeout"])
            out = (r.stdout + ("\n--stderr--\n" + r.stderr if r.stderr else ""))
            return out[:6000] or "(sin output, exit %d)" % r.returncode
        except subprocess.TimeoutExpired:
            return "ERROR: timeout de ejecución"
        finally:
            code_f.unlink(missing_ok=True)
    return "ERROR: tool desconocida"


def run_cell(cfg, model, task, taskset_dir, fixtures_root, run_dir):
    workdir = run_dir / model["name"] / task["id"]
    workdir.mkdir(parents=True, exist_ok=True)
    for fx in task["fixtures"]:
        shutil.copy2(fixtures_root / fx, workdir / fx)

    lane = pick_lane(cfg, model)
    model_id = model["lane_ids"][lane["name"]]
    limits = cfg["limits"]
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": task["prompt"]}]
    tokens = {"prompt": 0, "completion": 0}
    t0, turns, done, err, served = time.time(), 0, False, None, None

    while turns < limits["max_turns"] and time.time() - t0 < limits["wall_seconds"]:
        turns += 1
        try:
            resp = chat(lane, model_id, messages, limits)
        except Exception as e:
            err = str(e)[:200]
            break
        u = resp.get("usage") or {}
        tokens["prompt"] += u.get("prompt_tokens", 0)
        tokens["completion"] += u.get("completion_tokens", 0)
        served = resp.get("model", served)  # detecta sustitución por fallback del router
        msg = resp["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        clean = {"role": "assistant", "content": msg.get("content") or ""}
        if calls:  # re-enviar solo campos del schema OpenAI (extras rompen el gateway)
            clean["tool_calls"] = [
                {"id": tc["id"], "type": "function",
                 "function": {"name": tc["function"]["name"],
                              "arguments": tc["function"]["arguments"]}}
                for tc in calls]
        messages.append(clean)
        if not calls:
            messages.append({"role": "user", "content":
                             "Continue. Use tools; call task_done when the file is on disk."})
            continue
        for tc in calls:
            fname = tc["function"]["name"]
            try:
                fargs = json.loads(tc["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                fargs = {}
            if fname == "task_done":
                done = True
                result = "ok"
            else:
                result = exec_tool(fname, fargs, workdir, cfg)
            messages.append({"role": "tool", "tool_call_id": tc["id"],
                             "content": result})
        if done:
            break

    wall = round(time.time() - t0, 1)
    checker = taskset_dir / task["checker"]
    chk = subprocess.run([cfg["python_bin"], str(checker), str(workdir)],
                         capture_output=True, text=True, timeout=400)
    try:
        diag = json.loads(chk.stdout.strip().splitlines()[-1])
    except Exception:
        diag = {"raw": chk.stdout[-300:]}
    return {"model": model["name"], "task": task["id"], "lane": lane["name"],
            "modelo_servido": served,
            "completo": chk.returncode == 0, "turnos": turns, "wall_s": wall,
            "tokens_in": tokens["prompt"], "tokens_out": tokens["completion"],
            "agente_declaro_done": done, "error": err, "checker": diag,
            "calidad_0_2": None}  # la asigna el juez contra la rúbrica pre-escrita


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(HERE / "config.yaml"))
    ap.add_argument("--models", help="filtro: nombres separados por coma")
    ap.add_argument("--tasks", help="filtro: ids separados por coma")
    a = ap.parse_args()

    cfg = yaml.safe_load(Path(a.config).read_text())
    # OJO: sin .resolve() — el python del venv es symlink y resolverlo pierde el venv
    cfg["python_bin"] = str((HERE / cfg["python_bin"]).absolute())
    taskset_path = (HERE / cfg["taskset"]).resolve()
    taskset_dir = taskset_path.parent
    ts = yaml.safe_load(taskset_path.read_text())
    fixtures_root = (taskset_dir / ts["fixtures_root"]).resolve()

    models = cfg["models"]
    if a.models:
        keep = set(a.models.split(","))
        models = [m for m in models if m["name"] in keep]
    tasks = ts["tasks"]
    if a.tasks:
        keep = set(a.tasks.split(","))
        tasks = [t for t in tasks if t["id"] in keep]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_dir = HERE / cfg.get("workdir_root", "runs") / stamp
    run_dir.mkdir(parents=True)
    results = []
    for m in models:                       # serializado a propósito (free tier)
        for t in tasks:
            print(f">> {m['name']} × {t['id']}", file=sys.stderr)
            try:
                cell = run_cell(cfg, m, t, taskset_dir, fixtures_root, run_dir)
            except Exception as e:
                cell = {"model": m["name"], "task": t["id"], "completo": False,
                        "error": str(e)[:200], "wall_s": None,
                        "tokens_in": 0, "tokens_out": 0, "calidad_0_2": None}
            results.append(cell)
            (run_dir / "results.json").write_text(
                json.dumps(results, indent=2, ensure_ascii=False))

    # tabla markdown
    lines = ["| modelo | tarea | carril | completó | tokens in/out | wall s | turnos |",
             "|---|---|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['model']} | {r['task']} | {r.get('lane','-')} | "
                     f"{'SÍ' if r['completo'] else 'NO'} | "
                     f"{r['tokens_in']}/{r['tokens_out']} | {r['wall_s']} | "
                     f"{r.get('turnos','-')} |")
    (run_dir / "results.md").write_text("\n".join(lines) + "\n")
    print(str(run_dir))


if __name__ == "__main__":
    main()
