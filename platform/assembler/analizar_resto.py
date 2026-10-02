#!/usr/bin/env python3
"""analizar_resto.py — ABRIR LA BOLSA. De qué está hecho el 70 % que nadie desglosó.

`analizar_prompt.py` parte el prompt en tres: catálogo · salidas · **resto**. En Legal y
Ciencia el resto es el 70-71 % y toda la tanda de optimización peleó por el otro 29 %.
Esto abre ese resto.

════════════════════════════════════════════════════════════════════════════════
CÓMO SE MIDE CADA PIEZA, Y POR QUÉ ASÍ

`render_prompt` (prompt_bridge) arma exactamente esto:

    {head}\\n{bloque_de_tools}\\n\\n=== CONVERSACIÓN ===\\n{body}\\n\\nDá el PRÓXIMO PASO: {cola}

con `head` = los `system` pegados, y `body` = una línea por mensaje:
`[Usuario]: …` · `[Tú]: …` · `[Tú llamaste]: <function=…>…` · `[Resultado de …]: …`.

Así que las piezas del resto son **segmentos literales del texto**, y se miden dos veces
por caminos distintos:

  · SUMA DE PARTES — tokenizar cada segmento tal como se rinde.
  · CONTRAFÁCTICO — tokens(prompt) − tokens(el mismo prompt con esa pieza vaciada).

Se imprimen las dos. **Si no coinciden, una está mal.** La tokenización no es aditiva
(los bordes funden tokens), así que unos pocos tokens de deriva son física; una
diferencia grande es un error del instrumento.

`andamiaje` no se mide: se DEDUCE como el sobrante, y por eso se lo llama residuo y no
«andamiaje medido». Ahí caen los rótulos, los saltos de línea y la deriva de bordes.

════════════════════════════════════════════════════════════════════════════════
DE QUIÉN ES CADA PIEZA — la pregunta que decide todo

No se deduce leyendo código: se MIDE con las dos tomas del grabador.

    toma `borde`   = los `messages` **tal como los manda el stack**
    toma `render`  = lo que efectivamente cruzó al modelo

Un mensaje que está en `render` y no en `borde` **lo puso Aleph**. Un mensaje que está en
los dos es **del stack**. El andamiaje del render es de Aleph por construcción
(`prompt_bridge` es nuestro). El bloque de tools es formato de Aleph sobre contenido del
stack, y por eso se dice partido.

════════════════════════════════════════════════════════════════════════════════
ADENTRO DEL SYSTEM PROMPT

Los stacks escriben su system prompt con secciones marcadas (`<task>`, `<rules>`,
`<examples>`, `<limits>`, `<output>`, `<untrusted-documents>`…). Se parte por esas
marcas y se clasifica cada una en: OFICIO · REGLAS · EJEMPLOS · FORMATO · POLÍTICAS.
Lo que no cae en ninguna se dice `sin_clasificar` — **no se lo reparte a ojo**.

⚠️ EL PREÁMBULO DEL CLI NO ESTÁ ACÁ ADENTRO. Todo lo que mide este archivo es el prompt
que **Aleph** arma. El preámbulo lo agrega el CLI después, por dentro, y no cruza por
`render_prompt`. Se lo reporta como una CAPA aparte (ver `--capas`), nunca sumado.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict

_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = os.path.dirname(os.path.dirname(_AQUI))
os.environ.pop("ALEPH_GRABAR_TOOLS", None)
os.environ.pop("ALEPH_GRABAR_PROMPT", None)
sys.path.insert(0, os.path.join(_RAIZ, "platform", "sala", "research", "lib"))
sys.path.insert(0, _AQUI)

import tiktoken  # noqa: E402

from cli_brain.prompt_bridge import _tools_block, render_prompt  # noqa: E402

_ENC = tiktoken.get_encoding("o200k_base")

#: El relleno que `render_prompt` pone cuando NO hay ningún `system`. Está copiado
#: literal a propósito: si `prompt_bridge` lo cambiara, la deriva del control cruzado
#: lo delataría en vez de esconderlo.
_RELLENO_HEAD = "Eres un agente útil y honesto."


def tok(s: str) -> int:
    return len(_ENC.encode(s or "", disallowed_special=()))


# ── clasificación de las secciones del system prompt ─────────────────────────────
_FAMILIAS = [
    # ⚠️ CATÁLOGO va primero y existe porque los datos lo pidieron: el pedazo más
    # grande del system prompt de Ciencia es `<available-skills>` (1.990 tok), que NO
    # es oficio ni política — es un CATÁLOGO de capacidades, la misma forma que el
    # bloque de tools, escondido adentro del system. Meterlo en «políticas» habría
    # tapado el hallazgo más grande de esta obra.
    ("CATÁLOGO", r"skill|available|catalog|inventory|registry|toolbox"),
    ("EJEMPLOS", r"example|few.?shot|sample|muestra|demo"),
    ("FORMATO", r"output|format|response|answer.?style|shape|schema|salida|citation"),
    ("POLÍTICAS", r"polic|safety|untrusted|privileg|confidential|legal|refus|prohibit|"
                  r"limit|never|guardrail|boundar"),
    ("REGLAS", r"rule|constraint|requirement|must|checklist|criteri|regla"),
    ("OFICIO", r"task|role|you are|purpose|mission|objetivo|capab|tool|workflow|context"),
]
_SECCION = re.compile(r"<([a-zA-Z][a-zA-Z0-9_\-]{1,40})>", re.MULTILINE)


def _familia(nombre: str, cuerpo: str) -> str:
    """La familia de una sección. **EL NOMBRE MANDA SOBRE EL CUERPO.**

    La vara C3 cazó por qué: un `<rules>` cuyo cuerpo dice «Never invent a price»
    matcheaba `never` y salía clasificado como POLÍTICAS. El autor del stack ya dijo qué
    es esa sección cuando la nombró; el cuerpo es una pista de segunda, y sólo se mira
    cuando el nombre no dice nada.
    """
    n = (nombre or "").lower()
    for fam, patron in _FAMILIAS:
        if n and re.search(patron, n):
            return fam
    cuerpo = (cuerpo or "")[:400].lower()
    for fam, patron in _FAMILIAS:
        if re.search(patron, cuerpo):
            return fam
    return "sin_clasificar"


def partir_system(texto: str) -> list:
    """El system prompt, partido por sus propias marcas de sección.

    Lo que va ANTES de la primera marca se llama `(encabezado)` y se clasifica igual.
    Si el texto no tiene marcas, sale UNA sola pieza `sin_clasificar` — que es la verdad,
    no un reparto inventado.
    """
    marcas = list(_SECCION.finditer(texto or ""))
    if not marcas:
        return [{"seccion": "(sin marcas)", "familia": "sin_clasificar",
                 "chars": len(texto or ""), "tok": tok(texto)}]
    piezas = []
    if marcas[0].start() > 0:
        cab = texto[:marcas[0].start()]
        if cab.strip():
            piezas.append({"seccion": "(encabezado)",
                           "familia": _familia("", cab), "chars": len(cab),
                           "tok": tok(cab)})
    for i, m in enumerate(marcas):
        fin = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
        cuerpo = texto[m.start():fin]
        # una marca de cierre `</x>` inmediata no abre sección nueva
        if cuerpo.strip().startswith("</"):
            continue
        piezas.append({"seccion": m.group(1), "familia": _familia(m.group(1), cuerpo),
                       "chars": len(cuerpo), "tok": tok(cuerpo)})
    return piezas


# ── el andamiaje que el HARNESS mete adentro de un mensaje de usuario ────────────
_ANDAMIO_USR = re.compile(
    r"<system-reminder>.*?</system-reminder>|<env>.*?</env>|"
    r"<context>.*?</context>|<system>.*?</system>", re.DOTALL | re.IGNORECASE)


def partir_usuario(texto: str) -> tuple:
    """(lo que escribió la persona, lo que le pegó el harness alrededor).

    No es un detalle: en Ciencia el PRIMER mensaje de usuario son 3.969 chars de los
    cuales la pregunta real son 127. Contar todo eso como «pregunta del usuario» sería
    atribuirle a la persona el andamiaje del stack.
    """
    andamio = "".join(m.group(0) for m in _ANDAMIO_USR.finditer(texto or ""))
    humano = _ANDAMIO_USR.sub("", texto or "")
    return humano, andamio


def _como_openai(fila: dict) -> list:
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


def _id2name(msgs: list) -> dict:
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


def analizar_fila(fila: dict) -> dict:
    msgs = _como_openai(fila)
    tools = fila.get("tools") or []
    tc = fila.get("tool_choice")
    prompt = fila.get("prompt")
    if prompt is None:
        prompt = render_prompt(msgs, tools, tc)
    total = tok(prompt)
    catalogo = tok(_tools_block(tools, tc))
    id2n = _id2name(msgs)

    sistema = usuario_h = usuario_a = asis_txt = asis_marc = salidas = 0
    secciones, sistemas = [], []
    for m in msgs:
        rol = m.get("role")
        cont = m.get("content")
        cont = cont if isinstance(cont, str) else json.dumps(cont, ensure_ascii=False,
                                                             default=str)
        if rol == "system":
            sistema += tok(cont)
            sistemas.append(cont)
            secciones.extend(partir_system(cont))
        elif rol == "user":
            h, a = partir_usuario(cont)
            usuario_h += tok(f"[Usuario]: {h}")
            usuario_a += tok(a) if a else 0
        elif rol == "assistant":
            for t in (m.get("tool_calls") or []):
                fn = t.get("function") or {}
                asis_marc += tok(f"[Tú llamaste]: <function={fn.get('name')}>"
                                 f"{fn.get('arguments')}</function>")
            if cont:
                asis_txt += tok(f"[Tú]: {cont}")
        elif rol == "tool":
            nm = id2n.get(m.get("tool_call_id")) or m.get("name") or "herramienta"
            salidas += tok(f"[Resultado de {nm}]: {cont}")

    # contrafácticos: vaciar UNA pieza y volver a renderizar
    def _sin(rol_objetivo):
        """Contrafáctico: cuánto más chico sería el prompt sin esta pieza.

        ⚠️ EL SESGO QUE ESTO CORRIGE, y que cazó la vara B3: `render_prompt` hace
        `head = "\n".join(sys_parts) if sys_parts else "Eres un agente útil y honesto."`.
        Vaciar los `system` no deja el hueco vacío — **mete un texto de relleno**. Sin
        descontarlo, el contrafáctico del system sale 9 tokens corto SIEMPRE, y sobre un
        system chico eso es un 10 % de error. Se compensa sumando el relleno de vuelta.
        """
        v = []
        for m in msgs:
            mm = dict(m)
            if mm.get("role") == rol_objetivo:
                mm["content"] = ""
                if rol_objetivo == "assistant":
                    mm.pop("tool_calls", None)
            v.append(mm)
        d = total - tok(render_prompt(v, tools, tc))
        if rol_objetivo == "system":
            d += tok(_RELLENO_HEAD)
        return d

    resto = total - catalogo - salidas
    andamiaje = resto - sistema - usuario_h - usuario_a - asis_txt - asis_marc
    return {
        "ts": fila.get("ts"), "toma": fila.get("toma"),
        "superficie": fila.get("superficie"), "chat": fila.get("chat", ""),
        "n_tools": fila.get("n_tools", 0), "n_messages": fila.get("n_messages", 0),
        "total": total, "catalogo": catalogo, "salidas": salidas, "resto": resto,
        "sistema": sistema, "usuario_humano": usuario_h, "usuario_andamio": usuario_a,
        "asistente_texto": asis_txt, "asistente_marcadores": asis_marc,
        "andamiaje": andamiaje,
        "cf_sistema": _sin("system"), "cf_usuario": _sin("user"),
        "cf_asistente": _sin("assistant"),
        "secciones": secciones, "sistemas": sistemas,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl")
    ap.add_argument("--toma", default="render")
    ap.add_argument("--capas", action="store_true",
                    help="agrega la capa del CLI leyendo las filas toma=usage")
    a = ap.parse_args()

    filas, usos = [], []
    with open(a.jsonl, encoding="utf-8") as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            try:
                f = json.loads(ln)
            except Exception:
                continue
            if f.get("toma") == "usage":
                usos.append(f)
                continue
            if f.get("toma") != a.toma:
                continue
            filas.append(analizar_fila(f))
    if not filas:
        print("sin filas", file=sys.stderr)
        return 2

    por = defaultdict(list)
    for f in filas:
        por[f["superficie"]].append(f)

    for sup, fs in sorted(por.items()):
        T = sum(f["total"] for f in fs)
        print(f"\n{'═'*74}\n══ {sup} · {len(fs)} cruces · {T:,} tok que Aleph le manda al CLI")
        print(f"{'═'*74}")
        filas_tabla = [
            ("catálogo (tools)", "catalogo", "Aleph (formato) / stack (contenido)"),
            ("salidas de tools", "salidas", "stack"),
            ("── EL RESTO ──", None, ""),
            ("system prompt", "sistema", "stack"),
            ("pregunta del usuario", "usuario_humano", "persona"),
            ("andamio en el user", "usuario_andamio", "stack (harness)"),
            ("asistente · texto", "asistente_texto", "modelo"),
            ("asistente · marcadores", "asistente_marcadores", "Aleph (formato)"),
            ("andamiaje del render", "andamiaje", "ALEPH"),
        ]
        for etiqueta, campo, dueno in filas_tabla:
            if campo is None:
                print(f"   {etiqueta}")
                continue
            v = sum(f[campo] for f in fs)
            print(f"   {etiqueta:<24} {v:>8,}  {100*v/T:5.1f}%   {dueno}")
        R = sum(f["resto"] for f in fs)
        print(f"   {'(resto total)':<24} {R:>8,}  {100*R/T:5.1f}%")

        # control cruzado
        s_p = sum(f["sistema"] for f in fs); s_c = sum(f["cf_sistema"] for f in fs)
        u_p = sum(f["usuario_humano"] + f["usuario_andamio"] for f in fs)
        u_c = sum(f["cf_usuario"] for f in fs)
        print(f"\n   control cruzado (suma de partes vs contrafáctico):")
        print(f"     system    {s_p:>7,} vs {s_c:>7,}   deriva {s_p-s_c:+,}")
        print(f"     usuario   {u_p:>7,} vs {u_c:>7,}   deriva {u_p-u_c:+,}")

        # ¿crece o es fijo?
        print(f"\n   ¿crece con el historial?  (primer cruce → último)")
        con_tools = [f for f in fs if f["n_tools"]]
        ref = con_tools or fs
        for etiqueta, campo in (("system prompt", "sistema"),
                                ("pregunta+andamio user", "usuario_humano"),
                                ("asistente", "asistente_texto"),
                                ("andamiaje", "andamiaje")):
            a0, a1 = ref[0][campo], ref[-1][campo]
            tend = "FIJO" if a0 == a1 else ("crece" if a1 > a0 else "baja")
            print(f"     {etiqueta:<24} {a0:>7,} → {a1:>7,}   {tend}")

        # ── LOS SYSTEM PROMPTS DISTINTOS ────────────────────────────────────────
        # ⚠️ NO alcanza con abrir el del primer cruce: un stack manda VARIOS system
        # distintos (Ciencia tiene el del agente principal y el del auxiliar de
        # títulos, y son de tamaños muy distintos). Reportar uno solo y llamarlo «el
        # system prompt» sería medir una pieza y concluir sobre el sistema.
        distintos = {}
        for f in fs:
            for txt in f.get("sistemas") or []:
                h = str(hash(txt))
                d = distintos.setdefault(h, {"txt": txt, "cruces": 0})
                d["cruces"] += 1
        if distintos:
            print(f"\n   LOS SYSTEM PROMPT DISTINTOS ({len(distintos)} en esta conversación):")
            orden = sorted(distintos.values(), key=lambda d: -tok(d["txt"]) * d["cruces"])
            for d in orden:
                t = tok(d["txt"])
                print(f"\n     ▸ {t:,} tok × {d['cruces']} cruces = {t*d['cruces']:,} "
                      f"pagados   ({d['chars'] if 'chars' in d else len(d['txt']):,} chars)")
                print(f"       arranca: {d['txt'][:90].strip()!r}")
                fam = defaultdict(int)
                secs = []
                for sec in partir_system(d["txt"]):
                    fam[sec["familia"]] += sec["tok"]
                    secs.append((sec["seccion"], sec["tok"]))
                tt = sum(fam.values()) or 1
                for k, v in sorted(fam.items(), key=lambda kv: -kv[1]):
                    print(f"       {k:<16} {v:>6,}  {100*v/tt:5.1f}%")
                print("       secciones: " + ", ".join(
                    f"{k}={v}" for k, v in sorted(secs, key=lambda kv: -kv[1])[:10]))

    if a.capas and usos:
        print(f"\n{'═'*74}\n══ LAS DOS CAPAS — lo de Aleph y lo que el CLI agrega por dentro\n{'═'*74}")
        # EL APAREO ES POR TIEMPO, y es legítimo porque son secuenciales: cada `usage`
        # se emite al CERRAR la llamada que el cruce inmediatamente anterior armó. No
        # hay id común entre las dos tomas —el cruce se graba antes de que exista la
        # respuesta— así que el orden temporal es el único vínculo, y se dice.
        cruces = sorted([f for f in filas], key=lambda f: f["ts"] or 0)
        print(f"   {'':>3} {'prompt de Aleph':>16} {'total facturado':>16} "
              f"{'⇒ preámbulo CLI':>17} {'cache_read':>11}")
        tot_a = tot_c = 0
        for i, u in enumerate(sorted(usos, key=lambda x: x.get("ts") or 0)):
            us = u.get("usage") or {}
            previos = [f for f in cruces if (f["ts"] or 0) <= (u.get("ts") or 0)]
            nuestro = previos[-1]["total"] if previos else None
            cw = us.get("cache_write_tokens")
            cr = us.get("cache_read_tokens")
            facturado = (cw or 0) + (us.get("prompt_tokens") or 0)
            pre = (facturado - nuestro) if (nuestro is not None and cw) else None
            if nuestro is not None and pre is not None:
                tot_a += nuestro
                tot_c += pre
            print(f"   #{i+1:<2} {nuestro if nuestro is not None else '?':>16,} "
                  f"{facturado:>16,} {pre if pre is not None else '?':>17,} "
                  f"{cr if cr is not None else 'null':>11}")
        # ⚠️ EL APAREO POR TIEMPO SE ROMPE CON LLAMADAS CONCURRENTES, y cuando se rompe
        # hay que decirlo, no imprimir el número igual. La señal es inequívoca: un
        # «preámbulo» NEGATIVO significa que el `usage` que aparejé no es el de ese
        # cruce. Pasa en Ciencia (el single-flight tiene dos llamadas solapadas) y en
        # Oficina (el bucle del lector). El AGREGADO sí sobrevive —cada cruce tiene
        # exactamente un `usage`, así que las dos sumas son correctas aunque el
        # emparejamiento fila a fila no lo sea— y por eso se reporta uno y no el otro.
        negativos = sum(1 for i, u in enumerate(sorted(usos, key=lambda x: x.get("ts") or 0))
                        if True) and any(
            (((u.get("usage") or {}).get("cache_write_tokens") or 0)
             + ((u.get("usage") or {}).get("prompt_tokens") or 0)
             - (max([f for f in cruces if (f["ts"] or 0) <= (u.get("ts") or 0)],
                    key=lambda f: f["ts"], default={"total": 0})["total"])) < 0
            for u in usos)
        n_cruces, n_usos = len(cruces), len(usos)
        if negativos:
            print(f"\n   ⚠️  APAREO FILA A FILA **NO VÁLIDO** en esta corrida: hay "
                  f"«preámbulos» negativos, o sea que el `usage` que caí no es el del "
                  f"cruce de al lado. Motivo: llamadas CONCURRENTES (single-flight / "
                  f"bucle del lector) rompen el orden temporal, que es el único vínculo "
                  f"entre las dos tomas. Las filas de arriba NO se leen.")
        print(f"\n   {n_cruces} cruces · {n_usos} llamadas facturadas"
              + ("  (parean 1 a 1: el agregado vale)" if n_cruces == n_usos
                 else "  ⚠️ NO parean: ni el agregado vale"))
        if tot_a and n_cruces == n_usos:
            A = sum(f["total"] for f in cruces)
            B = sum(((u.get("usage") or {}).get("cache_write_tokens") or 0)
                    + ((u.get("usage") or {}).get("prompt_tokens") or 0) for u in usos)
            print(f"   AGREGADO (válido igual):  Aleph {A:,} ({100*A/B:.0f} % de lo "
                  f"facturado)  ·  lo que agrega el CLI {B-A:,} ({100*(B-A)/B:.0f} %)"
                  f"  ·  facturado {B:,}")
        lecturas = [u.get("usage", {}).get("cache_read_tokens") for u in usos]
        vivas = [x for x in lecturas if x]
        print(f"\n   ¿EL CACHÉ CUBRE ALGO?  cache_read > 0 en {len(vivas)} de "
              f"{len(lecturas)} llamadas."
              + ("  → NO cubre NADA: cada llamada ESCRIBE una entrada nueva y no lee "
                 "ninguna." if not vivas else ""))
    elif a.capas:
        print("\n   [NO MEDIBLE] no hay filas `toma=usage` en este archivo — motivo: el "
              "tap del usage no estaba puesto cuando se grabó.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
