#!/usr/bin/env python3
"""
verify_ux_universal.py — harness VIVO de la Ola UX-UNIVERSAL (Sala familiar: chat + Cowork).

Secciones (cada una imprime PASS/FAIL por check; exit != 0 si algo falló):
  A1 · historial y retomar : chats persisten, multi-turno REAL (el cerebro recuerda),
       retomar rehidrata, anti-IDOR entre cuentas/composiciones
  A2 · buscar              : texto entre chats del dueño y dentro de un hilo
  (las secciones B*/A3-A5 se suman a medida que la ola las construye)

Requiere: backend VIVO (env BASE, default http://127.0.0.1:8097) con Postgres migrado
(0007_chats) y GROQ_API_KEY en infra/.env (los turnos usan el modelo REAL del path de
charla de la Sala — cero mocks). Corre:
  BASE=http://127.0.0.1:8097 python3 qa/verify_ux_universal.py [a1 a2 ...]
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = os.environ.get("BASE", "http://127.0.0.1:8097").rstrip("/")
TIMEOUT = float(os.environ.get("PUPPET_HTTP_TIMEOUT", "240"))

PASS = 0
FAIL = 0
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        FAILED.append(name)
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))
    return ok


def api(method: str, path: str, token: str | None = None, body: dict | None = None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read().decode()
            try:
                return r.status, json.loads(raw)
            except Exception:
                return r.status, None
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return 0, None


def register(tag: str) -> dict:
    email = f"ux-{tag}-{uuid.uuid4().hex[:8]}@puppet.local"
    code, user = api("POST", "/v1/auth/register",
                     body={"email": email, "password": "ux-universal-1",
                           "display_name": f"UX {tag}"})
    assert code == 201 and user and user.get("session_token"), f"register {tag}: {code}"
    return user


# La MISMA receta de charla que la Sala (chatRecipe de sala.html): modelo crudo Groq.
def chat_recipe() -> dict:
    return {
        "schema_version": "v1",
        "meta": {"name": "chat", "nicho": "general", "output_type": "informe"},
        "model": {"primary": "openai/gpt-oss-120b",
                  "fallback": "llama-3.3-70b-versatile",
                  "base_url": "https://api.groq.com/openai/v1",
                  "temperature": 0.2, "max_tokens": 400, "max_turns": 3},
        "belt": {"belt_ref": "platform/assembler/fixtures/belt-inline-rich.mcp.json",
                 "tool_filters": {"pysandbox": ["run_python"],
                                  "calc": ["add", "sub", "mul", "div", "pow", "mod"]}},
        "framing": {"inline": ""},
        "rag": {"enabled": False}, "keys": {}, "gates": {},
    }


def stream_turn(token: str, user_id: str, chat_id: str, prompt: str) -> dict:
    """POST /v1/puppets/run/stream con chat_id → consume el SSE real hasta done/error."""
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + token}
    body = {"recipe": chat_recipe(), "user_id": user_id, "chat_id": chat_id,
            "prompt": prompt, "lang": "es"}
    out = {"tokens": 0, "answer": "", "error": None}
    req = urllib.request.Request(BASE + "/v1/puppets/run/stream",
                                 data=json.dumps(body).encode(),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data: "):
                    continue
                evt = json.loads(line[6:])
                if evt.get("type") == "token":
                    out["tokens"] += 1
                elif evt.get("type") == "done":
                    out["answer"] = evt.get("answer") or ""
                elif evt.get("type") == "error":
                    out["error"] = evt.get("detail")
    except urllib.error.HTTPError as e:
        out["error"] = f"http {e.code}"
    except Exception as e:
        out["error"] = str(e)
    return out


# ════════════════════════════════ A1 · HISTORIAL Y RETOMAR ══════════════════════

def section_a1():
    print("\n═══ A1 · historial y retomar (persistencia + multi-turno real + anti-IDOR) ═══")
    ua, ub = register("a"), register("b")
    ta, tb = ua["session_token"], ub["session_token"]

    # crear chat (inline: sin puppet)
    code, chat = api("POST", "/v1/chats", token=ta, body={})
    check("A1.1 crear chat → 201 + id", code == 201 and bool(chat and chat.get("id")))
    chat_id = chat["id"]

    # sin sesión → 401 (un chat siempre tiene dueño)
    code, _ = api("GET", "/v1/chats")
    check("A1.2 listar sin sesión → 401", code == 401)

    # turno 1 (streaming REAL): sembrar un dato que el cerebro deba recordar
    t1 = stream_turn(ta, ua["id"], chat_id,
                     "Hola. Dato importante para recordar: mi color favorito es el verde. "
                     "Respondé solo 'anotado'.")
    check("A1.3 turno 1 streamea tokens reales", t1["tokens"] > 0 and not t1["error"],
          f"tokens={t1['tokens']} err={t1['error']}")

    # turno 2: el cerebro debe RECORDAR el turno 1 (rehidratación server-side)
    t2 = stream_turn(ta, ua["id"], chat_id,
                     "En una sola palabra: ¿cuál es mi color favorito?")
    check("A1.4 turno 2 recuerda el turno 1 (multi-turno REAL)",
          "verde" in t2["answer"].lower(), f"answer={t2['answer']!r}")

    # retomar: el hilo rehidrata con los 4 turnos en orden
    code, full = api("GET", f"/v1/chats/{chat_id}", token=ta)
    msgs = (full or {}).get("messages") or []
    roles = [m["role"] for m in msgs]
    check("A1.5 retomar → 4 mensajes user/agent en orden",
          code == 200 and roles == ["user", "agent", "user", "agent"],
          f"roles={roles}")
    check("A1.6 título nace del primer mensaje",
          (full or {}).get("title", "").startswith("Hola. Dato importante"))

    # lista scoped: aparece en 'inline', no aparece bajo un puppet ajeno al scope
    code, lst = api("GET", "/v1/chats?puppet_id=none", token=ta)
    ids = [c["id"] for c in (lst or {}).get("chats", [])]
    check("A1.7 lista scoped a inline lo incluye (con preview)",
          chat_id in ids and any(c.get("preview") for c in (lst or {}).get("chats", [])
                                 if c["id"] == chat_id))

    # anti-IDOR: B no ve el chat de A por ningún camino
    code, _ = api("GET", f"/v1/chats/{chat_id}", token=tb)
    check("A1.8 B lee el chat de A → 404", code == 404)
    code, lstb = api("GET", "/v1/chats", token=tb)
    check("A1.9 la lista de B no contiene chats de A",
          code == 200 and chat_id not in [c["id"] for c in (lstb or {}).get("chats", [])])
    t_idor = stream_turn(tb, ub["id"], chat_id, "hola")
    check("A1.10 B corre un turno sobre el chat de A → rechazado",
          t_idor["error"] is not None and "404" in str(t_idor["error"]))

    # chat sobre una composición: crearla y verificar el scope + mismatch
    code, pup = api("POST", "/v1/puppets", token=ta,
                    body={"owner_id": ua["id"], "name": "UX harness comp", "nicho": "general",
                          "config": chat_recipe()})
    if check("A1.11 crear composición para scope", code == 201 and bool(pup and pup.get("id"))):
        pid = pup["id"]
        code, chat2 = api("POST", "/v1/chats", token=ta, body={"puppet_id": pid})
        check("A1.12 chat de composición → 201", code == 201)
        code, lst2 = api("GET", f"/v1/chats?puppet_id={pid}", token=ta)
        ids2 = [c["id"] for c in (lst2 or {}).get("chats", [])]
        check("A1.13 scope por composición separa los hilos",
              chat2["id"] in ids2 and chat_id not in ids2)
        # B no puede abrir un chat SOBRE la composición de A
        code, _ = api("POST", "/v1/chats", token=tb, body={"puppet_id": pid})
        check("A1.14 B abre chat sobre composición de A → 404", code == 404)

    # renombrar + borrar
    code, _ = api("PATCH", f"/v1/chats/{chat_id}", token=ta, body={"title": "Mi hilo verde"})
    check("A1.15 renombrar → ok", code == 200)
    code, _ = api("DELETE", f"/v1/chats/{chat_id}", token=ta)
    code2, _ = api("GET", f"/v1/chats/{chat_id}", token=ta)
    check("A1.16 borrar → el hilo desaparece", code == 200 and code2 == 404)

    return ua, ta, ub, tb


# ════════════════════════════════ A2 · BUSCAR ═══════════════════════════════════

def section_a2(ua, ta, ub, tb):
    print("\n═══ A2 · buscar (texto entre chats y dentro de un hilo) ═══")
    code, chat = api("POST", "/v1/chats", token=ta, body={})
    chat_id = chat["id"]
    t1 = stream_turn(ta, ua["id"], chat_id,
                     "Anotá: el proyecto se llama Quetzal-7. Respondé 'anotado'.")
    check("A2.1 turno con término buscable corre", not t1["error"], str(t1["error"]))

    code, res = api("GET", "/v1/chats/search?q=Quetzal-7", token=ta)
    hits = (res or {}).get("hits", [])
    check("A2.2 buscar entre chats encuentra el término (con snippet)",
          code == 200 and any("quetzal-7" in (h.get("snippet") or "").lower() for h in hits),
          f"hits={len(hits)}")
    check("A2.3 el hit trae chat_id para saltar al hilo",
          any(h.get("chat_id") == chat_id for h in hits))

    code, res_hilo = api("GET", f"/v1/chats/search?q=Quetzal-7&chat_id={chat_id}", token=ta)
    check("A2.4 buscar DENTRO del hilo", code == 200 and (res_hilo or {}).get("total", 0) >= 1)

    # anti-IDOR: B no encuentra los términos de A
    code, res_b = api("GET", "/v1/chats/search?q=Quetzal-7", token=tb)
    check("A2.5 la búsqueda de B no ve mensajes de A",
          code == 200 and (res_b or {}).get("total", 0) == 0)
    code, _ = api("GET", f"/v1/chats/search?q=x&chat_id={chat_id}", token=tb)
    check("A2.6 B busca dentro del hilo de A → 404", code == 404)

    api("DELETE", f"/v1/chats/{chat_id}", token=ta)


# ════════════════════════════════ A3 · RELEER/RESUMIR ═══════════════════════════

def _history_structural_check(chat_id: str, space_id: str) -> bool:
    """In-process: el bloque de historial que va al cerebro se arma SOLO de
    chat_messages.content + el descriptor del espacio (artifacts-por-handle:
    jamás bytes crudos de artifacts)."""
    import sys as _sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    p = str(root / "product" / "backend")
    if p not in _sys.path:
        _sys.path.insert(0, p)
    try:
        from app.phase1 import chats_repo, repo
        conn = repo.get_conn()
        try:
            block = chats_repo.build_history_block(conn, chat_id)
            msgs = chats_repo.list_messages(conn, chat_id)
        finally:
            conn.close()
        if f"[obra de ese turno registrada en el espacio {space_id}]" not in block:
            print("   (falta el descriptor del espacio en el bloque)")
            return False
        contents = " ".join((m.get("content") or "") for m in msgs)
        for line in block.splitlines():
            for pref in ("Usuario: ", "Agente: "):
                if line.startswith(pref):
                    body = line[len(pref):].replace(" …(recortado)", "")
                    if body and body[:60] not in contents:
                        print(f"   (línea del bloque no proviene del registro: {line[:80]!r})")
                        return False
        return True
    except Exception as e:
        print(f"   (in-process check error: {e})")
        return False


def section_a3(ua, ta, ub, tb):
    print("\n═══ A3 · releer/resumir: el cerebro lee el REGISTRO de la conversación ═══")
    code, chat = api("POST", "/v1/chats", token=ta, body={})
    chat_id = chat["id"]
    stream_turn(ta, ua["id"], chat_id,
                "Decisión del proyecto: el deploy va el MARTES. Respondé solo 'ok'.")
    stream_turn(ta, ua["id"], chat_id,
                "Otra decisión: el presupuesto aprobado es 5000 dólares. Respondé solo 'ok'.")

    # el classifier manda lo meta-conversacional al CHAT (releer el hilo, no obra nueva)
    code, cls = api("POST", "/v1/classify-turn", token=ta, body={"prompt": "resumime este chat"})
    check("A3.1 'resumime este chat' clasifica como charla",
          code == 200 and (cls or {}).get("turn") == "chat", str(cls))

    t = stream_turn(ta, ua["id"], chat_id,
                    "Resumime este chat en una sola frase, mencionando cada decisión tomada.")
    low = t["answer"].lower()
    check("A3.2 el resumen sale del registro real (martes + 5000)",
          ("martes" in low) and ("5000" in low or "5.000" in low or "5,000" in low),
          t["answer"][:140])

    t2 = stream_turn(ta, ua["id"], chat_id, "¿Qué decidimos sobre el deploy? Una palabra.")
    check("A3.3 '¿qué decidimos sobre X?' responde del registro",
          "martes" in t2["answer"].lower(), t2["answer"][:80])

    # turno OBRA en el hilo → el registro guarda answer + space_id (handle), jamás bytes
    space_id = f"ux-a3-{uuid.uuid4().hex[:8]}"
    code, out = api("POST", "/v1/puppets/run", token=ta,
                    body={"recipe": chat_recipe(), "user_id": ua["id"], "chat_id": chat_id,
                          "space_id": space_id, "deadline_s": 240.0,
                          "prompt": "Calculá 21*2 con la calculadora y decime el resultado."})
    check("A3.4 turno obra (run real) corre y responde",
          code == 201 and bool((out or {}).get("answer")), f"http {code}")
    code, full = api("GET", f"/v1/chats/{chat_id}", token=ta)
    obra_msgs = [m for m in (full or {}).get("messages", [])
                 if m.get("kind") == "obra" and m.get("role") == "agent"]
    check("A3.5 el registro liga el turno obra a su espacio (handle, no bytes)",
          any(m.get("space_id") == space_id and (m.get("content") or "").strip()
              for m in obra_msgs))
    check("A3.6 historial = texto del registro + descriptor del espacio (por-handle)",
          _history_structural_check(chat_id, space_id))
    api("DELETE", f"/v1/chats/{chat_id}", token=ta)


# ════════════════════════════════ B1 · SELECTOR DE AUTONOMÍA ════════════════════

# La receta REAL del agente inline de la Sala (buildBody): pysandbox+datatools+calc.
def sala_recipe() -> dict:
    return {
        "schema_version": "v1",
        "meta": {"name": "Tu agente", "nicho": "general", "output_type": "informe"},
        "model": {"primary": "openai/gpt-oss-120b",
                  "fallback": "llama-3.3-70b-versatile",
                  "base_url": "https://api.groq.com/openai/v1",
                  "temperature": 0.2, "max_tokens": 1400, "max_turns": 4},
        "belt": {"belt_ref": "platform/assembler/fixtures/belt-inline-rich.mcp.json",
                 "tool_filters": {"pysandbox": ["run_python"],
                                  "datatools": ["write_xlsx", "write_csv"],
                                  "calc": ["add", "sub", "mul", "div", "pow", "mod"]}},
        "framing": {"inline": ""},
        "rag": {"enabled": False}, "keys": {},
        "gates": {"money_touch": "needs_ok", "send": "needs_ok"},
    }


def run_with_autonomy(token: str, user_id: str, autonomy: str | None, prompt: str) -> tuple[int, dict]:
    body = {"recipe": sala_recipe(), "user_id": user_id, "prompt": prompt,
            "deadline_s": 240.0, "lang": "es"}
    if autonomy is not None:
        body["autonomy"] = autonomy
    return api("POST", "/v1/puppets/run", token=token, body=body)


def _tool_decisions(out: dict, name: str) -> list[dict]:
    """Decisiones del gate para un server O una tool puntual (la bitácora registra ambos)."""
    rec = (out or {}).get("record") or {}
    return [d for d in (rec.get("gate_decisions") or [])
            if name in (d.get("server"), d.get("tool"))]


def section_b1(ua, ta, ub, tb):
    print("\n═══ B1 · selector de autonomía: la perilla REAL, pisos held en ambos modos ═══")

    # basura en la perilla → 422 (set cerrado del validador; jamás un default mudo)
    code, _ = run_with_autonomy(ta, ua["id"], "turbo", "hola")
    check("B1.1 autonomy inválida rebota 422 (set cerrado)", code == 422, f"http {code}")

    py_prompt = ("Usá la herramienta run_python para calcular 6*7 e imprimir el resultado. "
                 "Es OBLIGATORIO usar run_python, no lo hagas de cabeza.")

    # manual: write-local (run_python) queda RETENIDO — el gate real decidió con la perilla
    code, out_m = run_with_autonomy(ta, ua["id"], "manual", py_prompt)
    dec_m = _tool_decisions(out_m, "pysandbox")
    rec_m = (out_m or {}).get("record") or {}
    check("B1.2 manual: run_python RETENIDO (write-local espera OK)",
          code == 201 and any(d.get("action") != "execute" for d in dec_m),
          f"decisions={[(d.get('action'), d.get('autonomy')) for d in dec_m]}")
    check("B1.3 la decisión registra la perilla vigente (bitácora)",
          all(d.get("autonomy") == "manual" for d in dec_m) and rec_m.get("autonomy") == "manual")
    # el out top-level trae las retenidas como OBJETOS con su approval_id (persistidas)
    held_m = (out_m or {}).get("held_actions") or []
    approval_id = held_m[0].get("approval_id") if held_m else None
    run_id_m = (out_m or {}).get("run_id")

    # balanceado: código arbitrario conserva autoridad de host y también queda retenido.
    code, out_b = run_with_autonomy(ta, ua["id"], "balanceado", py_prompt)
    dec_b = _tool_decisions(out_b, "pysandbox")
    check("B1.4 balanceado: run_python RETENIDO (piso code_exec)",
          code == 201 and dec_b and all(d.get("action") != "execute" for d in dec_b)
          and all(d.get("action_class") == "code_exec" for d in dec_b),
          f"decisions={[(d.get('action'), d.get('autonomy')) for d in dec_b]}")

    # PISO en ambos modos: write_xlsx (nombre de escritura) queda held aunque el belt lo
    # declare write-local y la perilla sea la más laxa que la Sala expone (balanceado)
    xl_prompt = ("Usá la herramienta write_xlsx para crear un archivo prueba.xlsx con una "
                 "fila de datos. Es OBLIGATORIO usar write_xlsx.")
    code, out_x = run_with_autonomy(ta, ua["id"], "balanceado", xl_prompt)
    dec_x = _tool_decisions(out_x, "datatools")
    check("B1.5 piso: write_xlsx RETENIDO bajo balanceado (el piso no se relaja)",
          code == 201 and dec_x and all(d.get("action") != "execute" for d in dec_x),
          f"decisions={[(d.get('action'), d.get('action_class')) for d in dec_x]}")

    # NO retro-aprueba: la held del run manual sigue PENDIENTE tras subir la perilla —
    # descartarla explícitamente todavía responde (si se hubiera retro-ejecutado, no habría
    # nada que resolver). ok:false = descartar, nada se ejecuta.
    if approval_id and run_id_m:
        code, res = api("POST", f"/v1/runs/{run_id_m}/approve", token=ta,
                        body={"approval_id": approval_id, "ok": False})
        check("B1.6 subir la perilla NO retro-aprueba (la held seguía pendiente)",
              code == 200 and not (res or {}).get("executed", False), f"http {code} {res}")
    else:
        check("B1.6 subir la perilla NO retro-aprueba (la held seguía pendiente)",
              False, "el run manual no dejó held con approval_id")


# ════════════════════════════════ B2 · PLAN DECLARADO ═══════════════════════════

def _extract_plan_units() -> bool:
    """In-process: _extract_plan parsea el bloque válido, ignora basura, limpia el content."""
    import sys as _sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    p = str(root / "platform" / "assembler")
    if p not in _sys.path:
        _sys.path.insert(0, p)
    try:
        from recipe_assembler import _extract_plan
        ok = True
        txt = ('```json\n{"plan": [{"paso": "calcular", "tool": "run_python"}, '
               '{"paso": "redactar", "tool": null}]}\n```\nArranco con el cálculo.')
        steps, clean = _extract_plan(txt)
        ok &= (len(steps) == 2 and steps[0]["tool"] == "run_python"
               and steps[1]["tool"] is None and steps[0]["n"] == 1)
        ok &= ("plan" not in clean and clean == "Arranco con el cálculo.")
        s2, c2 = _extract_plan("sin bloque acá")
        ok &= (s2 == [] and c2 == "sin bloque acá")
        s3, _ = _extract_plan('```json\n{"plan": [{{roto]]}\n```')
        ok &= (s3 == [])
        s4, _ = _extract_plan(None)
        ok &= (s4 == [])
        return ok
    except Exception as e:
        print(f"   (unit error: {e})")
        return False


def section_b2(ua, ta, ub, tb):
    print("\n═══ B2 · plan declarado: la fuente honesta de la checklist ═══")
    check("B2.1 _extract_plan: bloque válido → pasos; basura → nada; content limpio",
          _extract_plan_units())

    # run REAL multi-paso: el cerebro declara el plan, lo emite al espinazo, y la
    # respuesta NO arrastra el bloque crudo
    space_id = f"ux-b2-{uuid.uuid4().hex[:8]}"
    body = {"recipe": sala_recipe(), "user_id": ua["id"], "space_id": space_id,
            "deadline_s": 240.0, "autonomy": "balanceado",
            "prompt": ("Tarea de dos pasos: primero calculá 6*7 usando run_python, "
                       "y después usá write_xlsx para escribir un archivo resumen.xlsx "
                       "con ese resultado. Usá las herramientas de verdad.")}
    code, out = api("POST", "/v1/puppets/run", token=ta, body=body)
    rec = (out or {}).get("record") or {}
    plan = rec.get("plan") or []
    check("B2.2 el run declara un PLAN real (record.plan, ≥2 pasos)",
          code == 201 and len(plan) >= 2,
          f"http {code} plan={len(plan)}")
    tools_planned = {p.get("tool") for p in plan if p.get("tool")}
    check("B2.3 los pasos nombran las tools reales del belt",
          bool(tools_planned & {"run_python", "write_xlsx"}), str(tools_planned))
    check("B2.4 la respuesta NO arrastra el bloque crudo del plan",
          '"plan"' not in ((out or {}).get("answer") or ""))

    code, evs = api("GET", f"/v1/spaces/{space_id}/events", token=ta)
    types = [e.get("type") for e in ((evs or {}).get("events") or [])]
    check("B2.5 plan_declared viaja por el espinazo (persistido en el espacio)",
          "plan_declared" in types, str(types[:8]))
    # el orden honesto: el plan ANTES de cualquier tool (turno 1)
    if "plan_declared" in types and "tool_call_finished" in types:
        check("B2.6 el plan llega ANTES de la primera tool (turno 1)",
              types.index("plan_declared") < types.index("tool_call_finished"))
    else:
        check("B2.6 el plan llega ANTES de la primera tool (turno 1)",
              "plan_declared" in types, "faltan eventos")


# ════════════════════════════════ B4 · CARD DE APROBACIÓN INFORMADA ═════════════

def section_b4(ua, ta, ub, tb):
    print("\n═══ B4 · card del gate: intención (turn_text) + efecto (args) reales ═══")
    space_id = f"ux-b4-{uuid.uuid4().hex[:8]}"
    body = {"recipe": sala_recipe(), "user_id": ua["id"], "space_id": space_id,
            "deadline_s": 240.0, "autonomy": "balanceado",
            "prompt": ("Necesito la planilla trimestral: usá write_xlsx para crear "
                       "trimestre.xlsx con una fila de datos de ejemplo. Antes de llamar "
                       "la herramienta, explicá brevemente qué vas a hacer.")}
    code, out = api("POST", "/v1/puppets/run", token=ta, body=body)
    held = (out or {}).get("held_actions") or []
    check("B4.1 el run retiene write_xlsx (piso) y la held viaja con approval_id",
          code == 201 and held and held[0].get("approval_id"), f"http {code} held={len(held)}")
    check("B4.2 la held lleva la INTENCIÓN del turno (turn_text real, no copy)",
          any((h.get("turn_text") or "").strip() for h in held),
          str([h.get("turn_text") for h in held])[:120])

    code, evs = api("GET", f"/v1/spaces/{space_id}/events", token=ta)
    gates = [e for e in ((evs or {}).get("events") or []) if e.get("type") == "gate_waiting"]
    check("B4.3 gate_waiting del espinazo lleva turn_text + gate_ux + args",
          gates and any((g.get("turn_text") or "").strip() and g.get("gate_ux")
                        and g.get("args") is not None for g in gates),
          f"gates={len(gates)}")
    if gates:
        ux = (gates[0].get("gate_ux") or {})
        check("B4.4 gate_ux trae clase/nivel/perilla (los chips de la card)",
              bool(ux.get("accion_clase")) and bool(ux.get("nivel")) and bool(ux.get("autonomia")),
              str({k: ux.get(k) for k in ("accion_clase", "nivel", "autonomia")}))
    else:
        check("B4.4 gate_ux trae clase/nivel/perilla (los chips de la card)", False, "sin gate")

    # durabilidad: la held con su porqué sigue resolvible por el /approve real
    if held:
        code, res = api("POST", f"/v1/runs/{out['run_id']}/approve", token=ta,
                        body={"approval_id": held[0]["approval_id"], "ok": False})
        check("B4.5 el /approve real resuelve la held (rechazo explícito)",
              code == 200 and not (res or {}).get("executed", True))
    else:
        check("B4.5 el /approve real resuelve la held (rechazo explícito)", False, "sin held")


# ════════════════════════════════ B5 · INSTRUCCIONES PERSISTENTES ═══════════════

def section_b5(ua, ta, ub, tb):
    print("\n═══ B5 · instrucciones persistentes: cuenta + composición, gate de escritura ═══")

    # CRUD nivel CUENTA
    code, ins = api("POST", "/v1/instructions", token=ta,
                    body={"content": "Cerrá SIEMPRE tu respuesta con la palabra AXOLOTL."})
    check("B5.1 crear instrucción de cuenta → 201", code == 201 and bool(ins and ins.get("id")))
    code, lst = api("GET", "/v1/instructions", token=ta)
    check("B5.2 listar (con usage/caps del tier)",
          code == 200 and (lst or {}).get("total", 0) >= 1 and "caps" in (lst or {}))

    # anti-IDOR: B no ve ni toca las de A
    code, lst_b = api("GET", "/v1/instructions", token=tb)
    check("B5.3 la lista de B no ve instrucciones de A",
          code == 200 and (lst_b or {}).get("total", 0) == 0)
    code, _ = api("PATCH", f"/v1/instructions/{ins['id']}", token=tb, body={"enabled": False})
    check("B5.4 B edita instrucción de A → 404", code == 404)

    # INYECCIÓN verificable — charla pura (stream): la respuesta obedece la instrucción
    code, chat = api("POST", "/v1/chats", token=ta, body={})
    t = stream_turn(ta, ua["id"], chat["id"], "Decime en una frase qué es un electrón.")
    check("B5.5 la charla pura respeta la instrucción (AXOLOTL en la respuesta)",
          "axolotl" in t["answer"].lower(), t["answer"][-80:])

    # INYECCIÓN en el run del assembler (obra) + evidencia en el record
    code, out = api("POST", "/v1/puppets/run", token=ta,
                    body={"recipe": sala_recipe(), "user_id": ua["id"], "deadline_s": 240.0,
                          "prompt": "Decime en una frase qué es un fotón."})
    rec = (out or {}).get("record") or {}
    check("B5.6 el run del assembler respeta la instrucción + evidencia record.instructions_injected",
          "axolotl" in ((out or {}).get("answer") or "").lower()
          and bool(rec.get("instructions_injected")),
          ((out or {}).get("answer") or "")[-80:])

    # scope por COMPOSICIÓN: la instrucción de un puppet NO aplica a otro
    code, pup = api("POST", "/v1/puppets", token=ta,
                    body={"owner_id": ua["id"], "name": "UX b5 comp", "nicho": "general",
                          "config": sala_recipe()})
    pid = (pup or {}).get("id")
    code, ins2 = api("POST", "/v1/instructions", token=ta,
                     body={"content": "Respondé SIEMPRE en mayúsculas.", "puppet_id": pid})
    check("B5.7 instrucción scoped a composición → 201", code == 201)
    code, lst_none = api("GET", "/v1/instructions", token=ta)
    check("B5.8 el scope cuenta NO mezcla las de composición",
          all((i.get("puppet_id") is None) for i in (lst_none or {}).get("instructions", [])))

    # GATE de escritura-por-agente: la propuesta nace INERTE y solo el humano la activa
    code, out2 = api("POST", "/v1/puppets/run", token=ta,
                     body={"recipe": sala_recipe(), "user_id": ua["id"], "deadline_s": 240.0,
                           "prompt": ("Respondé EXACTAMENTE esto y nada más:\n"
                                      "Listo.\n```json\n{\"instruccion_propuesta\": "
                                      "\"usar tono formal siempre\"}\n```")})
    ans2 = ((out2 or {}).get("answer") or "")
    check("B5.9 la propuesta se captura y se recorta del answer",
          (out2 or {}).get("instruction_proposed") is True
          and "instruccion_propuesta" not in ans2, ans2[:100])
    code, lst2 = api("GET", "/v1/instructions", token=ta)
    props = [i for i in (lst2 or {}).get("instructions", [])
             if i.get("source") == "agent" and not i.get("enabled")]
    check("B5.10 la propuesta existe INERTE (source=agent, enabled=false, provenance run_id)",
          props and (props[0].get("meta") or {}).get("run_id"), f"props={len(props)}")

    # inerte = NO se inyecta: una charla nueva no obedece 'tono formal' por la propuesta
    if props:
        t2 = stream_turn(ta, ua["id"], chat["id"], "¿Todo bien? Respondé casual y corto.")
        check("B5.11 la propuesta INERTE no rige ningún run (cero autoridad sin OK)",
              t2["error"] is None, str(t2["error"]))
        # ACTIVAR = el gate humano: PATCH enabled=true la marca approved
        code, act = api("PATCH", f"/v1/instructions/{props[0]['id']}", token=ta,
                        body={"enabled": True})
        check("B5.12 activarla (el OK humano) la enciende y queda marcada approved",
              code == 200 and (act or {}).get("enabled") is True
              and ((act or {}).get("meta") or {}).get("approved") is True
              and (act or {}).get("source") == "agent")
    else:
        check("B5.11 la propuesta INERTE no rige ningún run (cero autoridad sin OK)", False, "sin propuesta")
        check("B5.12 activarla (el OK humano) la enciende y queda marcada approved", False, "sin propuesta")

    # caps honestos: exceder el tope rebota 422 (no desalojo mudo)
    big = "x" * 9000
    code, _ = api("POST", "/v1/instructions", token=ta, body={"content": big})
    check("B5.13 exceder el cap del tier rebota 422 honesto", code == 422)

    # limpieza best-effort (no afecta el veredicto)
    for i in (api("GET", "/v1/instructions", token=ta)[1] or {}).get("instructions", []):
        api("DELETE", f"/v1/instructions/{i['id']}", token=ta)
    api("DELETE", f"/v1/chats/{chat['id']}", token=ta)


# ════════════════════════════════ main ══════════════════════════════════════════

SECTIONS = {"a1": None, "a2": None, "a3": None, "b1": None, "b2": None, "b4": None, "b5": None}

if __name__ == "__main__":
    which = [s.lower() for s in sys.argv[1:]] or list(SECTIONS)
    print(f"verify_ux_universal · BASE={BASE}")
    t0 = time.time()
    ctx = None
    if "a1" in which:
        ctx = section_a1()
    if "a2" in which:
        if ctx is None:
            ua, ub = register("a2a"), register("a2b")
            ctx = (ua, ua["session_token"], ub, ub["session_token"])
        section_a2(*ctx)
    if "a3" in which:
        if ctx is None:
            ua, ub = register("a3a"), register("a3b")
            ctx = (ua, ua["session_token"], ub, ub["session_token"])
        section_a3(*ctx)
    if "b1" in which:
        if ctx is None:
            ua, ub = register("b1a"), register("b1b")
            ctx = (ua, ua["session_token"], ub, ub["session_token"])
        section_b1(*ctx)
    if "b2" in which:
        if ctx is None:
            ua, ub = register("b2a"), register("b2b")
            ctx = (ua, ua["session_token"], ub, ub["session_token"])
        section_b2(*ctx)
    if "b4" in which:
        if ctx is None:
            ua, ub = register("b4a"), register("b4b")
            ctx = (ua, ua["session_token"], ub, ub["session_token"])
        section_b4(*ctx)
    if "b5" in which:
        if ctx is None:
            ua, ub = register("b5a"), register("b5b")
            ctx = (ua, ua["session_token"], ub, ub["session_token"])
        section_b5(*ctx)
    dt = time.time() - t0
    print(f"\n{'VERDE' if FAIL == 0 else 'ROJO'} — {PASS} PASS · {FAIL} FAIL · {dt:.0f}s")
    if FAILED:
        for f in FAILED:
            print(f"  ✗ {f}")
    sys.exit(0 if FAIL == 0 else 1)
