#!/usr/bin/env python3
"""analizar_prompt.py — las cuentas del `grabador_prompt`, FUERA del turno.

Contesta las tres preguntas de la obra A:

  1. ¿QUÉ PESA cada salida de tool?
  2. ¿CUÁNTAS VECES se re-lee?
  3. ¿QUÉ FRACCIÓN del prompt es salida acumulada, contra catálogo, contra historial?

TRES DEFINICIONES, y se dicen las tres porque no son la misma cosa:

  · `catalogo`  = tokens del bloque que arma `prompt_bridge._tools_block`. Es el mismo
                  punto que ya se usó en la tanda anterior, así que los números se
                  pueden comparar sin traducir.
  · `salidas`   = suma de los tokens de cada línea `[Resultado de X]: …` tal como la
                  rinde `render_prompt`. Suma de PARTES.
  · `salidas_marginal` = tokens(prompt) − tokens(el mismo prompt con el contenido de
                  cada mensaje `tool` vaciado). Es un CONTRAFÁCTICO: cuánto más chico
                  sería el prompt si las salidas no pesaran.

  Las dos últimas miden lo mismo por caminos distintos. **Si no coinciden, una está
  mal** — y por eso se imprimen juntas: es el control de la propia herramienta. La
  tokenización no es aditiva (los bordes entre segmentos pueden fundir tokens), así que
  una diferencia de unos pocos tokens es esperable; una diferencia grande es un error.

  `resto` = total − catalogo − salidas. Se declara como RESIDUO, con nombre: ahí caen
  el system, los `[Usuario]`, los `[Vos]`, el andamiaje del render y la deriva de
  bordes. No se lo llama «historial» porque no es sólo historial.

EL RE-LEÍDO. La identidad de una salida es el hash de su contenido. Una salida que
aparece en N cruces se leyó N veces y se pagó N veces. `veces` es ese N; `tok_pagados`
es `tok × N`, que es lo que costó de verdad, contra `tok` que es lo que parece costar.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict

_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = os.path.dirname(os.path.dirname(_AQUI))

# El grabador de tools se dispara desde `_tools_block`; acá estamos ANALIZANDO, no
# midiendo, y un análisis que ensucia el archivo que analiza no sirve.
os.environ.pop("ALEPH_GRABAR_TOOLS", None)
os.environ.pop("ALEPH_GRABAR_PROMPT", None)

sys.path.insert(0, os.path.join(_RAIZ, "platform", "sala", "research", "lib"))
sys.path.insert(0, _AQUI)

import tiktoken  # noqa: E402

from cli_brain.prompt_bridge import _tools_block, render_prompt  # noqa: E402

_ENC = tiktoken.get_encoding("o200k_base")


def tok(s: str) -> int:
    return len(_ENC.encode(s or "", disallowed_special=()))


def _id2name(msgs: list) -> dict:
    """id de tool_call → nombre. Con un RESPALDO POR ORDEN, y hace falta.

    Las grabaciones de la primera corrida no guardaban el `id` del `tool_call`, así que
    el mapa quedaba vacío y todas las salidas se llamaban «herramienta» — un nombre que
    no discrimina y vuelve inútil la tabla del re-leído. El respaldo aprovecha que en
    estos harnesses cada mensaje `assistant` con llamadas es seguido por sus mensajes
    `tool` en el mismo orden: la k-ésima llamada emparejada con la k-ésima salida.
    Es una INFERENCIA, no una lectura, y por eso va SEGUNDA: si el id está, manda el id.
    """
    d = {}
    for m in msgs:
        for tc in (m.get("tool_calls") or []):
            if tc.get("id"):
                d[tc["id"]] = (tc.get("function") or {}).get("name", "tool")
    pedidas, salidas = [], []
    for m in msgs:
        for tc in (m.get("tool_calls") or []):
            pedidas.append((tc.get("function") or {}).get("name", "tool"))
        if m.get("role") == "tool":
            salidas.append(m.get("tool_call_id") or "")
    for k, tcid in enumerate(salidas):
        if tcid and tcid not in d and k < len(pedidas):
            d[tcid] = pedidas[k]
    return d


def _como_openai(fila: dict) -> list:
    """Los `mensajes` del grabador, de vuelta en forma OpenAI para poder re-renderizar."""
    out = []
    for m in fila.get("mensajes") or []:
        msg = {"role": m.get("rol"), "content": m.get("content")}
        if m.get("rol") == "tool":
            msg["name"] = m.get("name") or ""
            msg["tool_call_id"] = m.get("tool_call_id") or ""
        if m.get("tool_calls"):
            msg["tool_calls"] = [
                {"id": tc.get("id") or f"call_{i}", "type": "function",
                 "function": {"name": tc.get("name"), "arguments": tc.get("arguments")}}
                for i, tc in enumerate(m["tool_calls"])]
        out.append(msg)
    return out


def analizar_fila(fila: dict) -> dict:
    msgs = _como_openai(fila)
    tools = fila.get("tools") or []
    tc = fila.get("tool_choice")
    prompt = fila.get("prompt")
    if prompt is None:
        prompt = render_prompt(msgs, tools, tc)
        reconstruido = True
    else:
        reconstruido = False

    total = tok(prompt)
    catalogo = tok(_tools_block(tools, tc))

    id2n = _id2name(msgs)
    salidas, det = 0, []
    for m in fila.get("mensajes") or []:
        if m.get("rol") != "tool":
            continue
        nm = id2n.get(m.get("tool_call_id")) or m.get("name") or "herramienta"
        t = tok(f"[Resultado de {nm}]: {m.get('content') or ''}")
        salidas += t
        det.append({"name": nm, "tok": t, "chars": m.get("chars", 0),
                    "hash": m.get("hash", "")})

    vacios = []
    for m in msgs:
        mm = dict(m)
        if mm.get("role") == "tool":
            mm["content"] = ""
        vacios.append(mm)
    marginal = total - tok(render_prompt(vacios, tools, tc)) if det else 0

    return {
        "ts": fila.get("ts"), "toma": fila.get("toma"),
        "superficie": fila.get("superficie"), "paso": fila.get("paso"),
        "chat": fila.get("chat", ""), "turn": fila.get("turn", ""),
        "incremental": fila.get("incremental"),
        "n_tools": fila.get("n_tools", 0), "n_messages": fila.get("n_messages", 0),
        "reconstruido": reconstruido,
        "total": total, "catalogo": catalogo, "salidas": salidas,
        "salidas_marginal": marginal, "resto": total - catalogo - salidas,
        "detalle": det,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl")
    ap.add_argument("--toma", default="", help="borde | render (vacío = las dos)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    filas = []
    with open(a.jsonl, encoding="utf-8") as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            try:
                f = json.loads(ln)
            except Exception:
                continue
            if a.toma and f.get("toma") != a.toma:
                continue
            filas.append(analizar_fila(f))

    if not filas:
        print("sin filas", file=sys.stderr)
        return 2

    # ── el re-leído, por superficie ────────────────────────────────────────────────
    veces = defaultdict(lambda: defaultdict(int))
    peso = defaultdict(dict)
    for f in filas:
        vistos = set()
        for d in f["detalle"]:
            if not d["hash"] or d["hash"] in vistos:
                continue
            vistos.add(d["hash"])
            veces[f["superficie"]][d["hash"]] += 1
            peso[f["superficie"]][d["hash"]] = (d["tok"], d["name"])

    if a.json:
        print(json.dumps({"filas": filas,
                          "releido": {s: {h: {"veces": v, "tok": peso[s][h][0],
                                              "name": peso[s][h][1]}
                                          for h, v in d.items()}
                                      for s, d in veces.items()}},
                         ensure_ascii=False, indent=2))
        return 0

    por_sup = defaultdict(list)
    for f in filas:
        por_sup[f["superficie"]].append(f)

    for sup, fs in sorted(por_sup.items()):
        T = sum(f["total"] for f in fs)
        C = sum(f["catalogo"] for f in fs)
        S = sum(f["salidas"] for f in fs)
        M = sum(f["salidas_marginal"] for f in fs)
        R = T - C - S
        print(f"\n══ {sup} · {len(fs)} cruces · {T:,} tok de prompt en total")
        print(f"   catálogo  {C:>9,}  {100*C/T:5.1f}%")
        print(f"   SALIDAS   {S:>9,}  {100*S/T:5.1f}%   (marginal {M:,} · "
              f"deriva {S-M:+,})")
        print(f"   resto     {R:>9,}  {100*R/T:5.1f}%   (system+usuario+asistente+andamiaje)")
        print("   ── cruce por cruce ──")
        for f in fs:
            inc = "" if f["incremental"] is None else (
                " ·incremental" if f["incremental"] else " ·completa")
            print(f"     #{fs.index(f)+1:>2} tools={f['n_tools']:>3} msgs={f['n_messages']:>3}"
                  f"  total={f['total']:>7,}  cat={f['catalogo']:>6,}"
                  f"  salidas={f['salidas']:>7,}  resto={f['resto']:>6,}{inc}")
        rel = veces.get(sup) or {}
        if rel:
            print("   ── salidas re-leídas (identidad = hash del contenido) ──")
            pagado_total = 0
            for h, n in sorted(rel.items(), key=lambda kv: -peso[sup][kv[0]][0] * kv[1]):
                t, nm = peso[sup][h]
                pagado_total += t * n
                print(f"     {nm:<22} {t:>7,} tok × {n} vez(ces) = {t*n:>8,} pagados")
            unicos = sum(peso[sup][h][0] for h in rel)
            print(f"     {'TOTAL':<22} {unicos:>7,} tok únicos → {pagado_total:>8,} pagados"
                  f"  (×{pagado_total/unicos:.2f})" if unicos else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
