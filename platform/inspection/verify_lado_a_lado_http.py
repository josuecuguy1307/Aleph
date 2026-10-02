#!/usr/bin/env python3
"""verify_lado_a_lado_http.py — EL PRIMER CAMINO VIVO (Fase 2 · sesión 1 del SDK).

`byo-ai-exa-exa` es el caso real: la única entidad HTTP del registro, un MCP público
(`https://mcp.exa.ai/mcp`) con DOS tools. Acá se le pregunta lo mismo, en la misma corrida,
al **cliente viejo** (`mcp_http_client.MCPHttpClient`, 251 líneas de stdlib) y al **puente**
(`transporte_sdk.ClienteSdkHttp`, el SDK oficial adentro), y se comparan las respuestas.

NO SE MIGRA NADA. El producto sigue hablando por el cliente viejo. Esto es la evidencia
para decidir la migración en la sesión que viene, no la migración.

La comparación es de a pares y por dato, no «los dos anduvieron»:
  · serverInfo         debe ser IDÉNTICO — es el mismo server
  · tools              mismos nombres, mismos schemas, mismos `required`
  · web_fetch_exa      contenido DETERMINISTA (example.com, la constante neutra de la IANA):
                       se comparan los textos, no la forma
  · web_search_exa     no determinista por diseño: se compara la ESTRUCTURA y que ninguno
                       de los dos venga en error
  · protocolVersion    se espera que DIFIERAN, y se reporta con el número de cada uno

Correr (necesita el pin de esta sesión — `mcp==2.0.0`):
    /ruta/al/venv-con-mcp-2.0.0/bin/python platform/inspection/verify_lado_a_lado_http.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
if str(_AQUI) not in sys.path:
    sys.path.append(str(_AQUI))

URL = "https://mcp.exa.ai/mcp"          # el `url` que el registro tiene para byo-ai-exa-exa
NEUTRA = "https://example.com"          # constante neutra reservada por la IANA (CLAUDE.md §1b)

_fallos = 0


def ok(cond, nombre, detalle=""):
    global _fallos
    if cond:
        print(f"  ✓ {nombre}")
    else:
        _fallos += 1
        print(f"  ✗ {nombre}" + (f" — {detalle}" if detalle else ""))


def nota(texto):
    print(f"  · {texto}")


try:
    import importlib.metadata as _md
    _VER = _md.version("mcp")
except Exception as e:                                     # noqa: BLE001
    print(f"✗ el SDK no está instalado: {e}")
    sys.exit(1)
if _VER != "2.0.0":
    print(f"✗ mcp=={_VER}: esta vara mide contra el pin de la sesión (2.0.0). No sigo.")
    sys.exit(1)

from mcp_http_client import MCPHttpClient                  # noqa: E402  — el del producto
from transporte_sdk import ClienteSdkHttp                  # noqa: E402  — el puente

print(f"byo-ai-exa-exa · {URL}\ncliente viejo (stdlib) vs puente (mcp=={_VER})\n")

viejo = MCPHttpClient(URL)
nuevo = ClienteSdkHttp(URL)

try:
    # ── 1 · INITIALIZE ──────────────────────────────────────────────────────────────
    print("── 1 · initialize " + "─" * 60)
    iv = viejo.initialize()
    inv = nuevo.initialize()

    si_v = iv.get("serverInfo") or {}
    si_n = inv.get("serverInfo") or {}
    ok(si_v == si_n, "serverInfo IDÉNTICO en los dos", f"viejo={si_v}\n     nuevo={si_n}")
    nota(f"serverInfo: {si_v.get('name')} {si_v.get('version')}")

    pv_v, pv_n = iv.get("protocolVersion"), inv.get("protocolVersion")
    ok(pv_v and pv_n, "los dos negociaron una versión de protocolo")
    if pv_v != pv_n:
        nota(f"protocolVersion DIFIERE — viejo={pv_v} · puente={pv_n}. Esperado: el cliente "
             f"viejo pide {pv_v} clavado en una constante; el SDK negocia lo que el server "
             f"ofrezca. El registro persiste esto (`era`, `version_negociada`).")
    else:
        nota(f"protocolVersion coincide: {pv_v}")

    # ── 2 · TOOLS ───────────────────────────────────────────────────────────────────
    print("\n── 2 · tools/list " + "─" * 59)
    tv = {t["name"]: t for t in viejo.list_tools()}
    tn = {t["name"]: t for t in nuevo.list_tools()}
    ok(sorted(tv) == sorted(tn), f"MISMAS tools: {sorted(tv)}",
       f"viejo={sorted(tv)} nuevo={sorted(tn)}")
    ok(len(tv) == 2, "las 2 que el registro dice que tiene", str(len(tv)))
    for nombre in sorted(set(tv) & set(tn)):
        sv = tv[nombre].get("inputSchema") or {}
        sn = tn[nombre].get("inputSchema") or {}
        ok(sorted((sv.get("properties") or {})) == sorted((sn.get("properties") or {})),
           f"`{nombre}`: mismos parámetros {sorted((sv.get('properties') or {}))}")
        ok((sv.get("required") or []) == (sn.get("required") or []),
           f"`{nombre}`: mismos `required` {sv.get('required')}",
           f"viejo={sv.get('required')} nuevo={sn.get('required')}")
        ok(tv[nombre].get("description") == tn[nombre].get("description"),
           f"`{nombre}`: misma descripción")

    # ── 3 · UNA TOOL REAL, CONTENIDO DETERMINISTA ───────────────────────────────────
    print("\n── 3 · tools/call · web_fetch_exa sobre la constante neutra " + "─" * 16)
    args = {"urls": [NEUTRA], "maxCharacters": 400}
    rv = viejo.call_tool("web_fetch_exa", args)
    rn = nuevo.call_tool("web_fetch_exa", args)

    def _texto(res):
        return "\n".join(c.get("text", "") for c in (res.get("content") or [])
                         if c.get("type") == "text")

    txt_v, txt_n = _texto(rv), _texto(rn)
    ok(bool(txt_v) and bool(txt_n), "los dos devolvieron texto",
       f"viejo={len(txt_v)} chars · nuevo={len(txt_n)} chars")
    ok(txt_v == txt_n, "el CONTENIDO es idéntico, carácter por carácter",
       f"viejo[:80]={txt_v[:80]!r}\n     nuevo[:80]={txt_n[:80]!r}")
    ok("This domain is for use in documentation examples" in txt_v,
       "y es el contenido que example.com sirve de verdad (no un eco vacío)")
    ok(not rv.get("isError") and not rn.get("isError"), "ninguno vino en error")
    if sorted(rv) != sorted(rn):
        nota(f"claves del `result`: viejo={sorted(rv)} · puente={sorted(rn)} — el puente "
             f"serializa el modelo del SDK, que rellena `isError` con su default `false`; "
             f"el viejo devuelve el JSON crudo, donde la clave puede no venir. Mismo "
             f"significado, distinta forma: importa al re-cablear los diagnósticos.")

    # ── 4 · LA SEGUNDA TOOL ─────────────────────────────────────────────────────────
    print("\n── 4 · tools/call · web_search_exa (no determinista por diseño) " + "─" * 12)
    q = {"query": "modelcontextprotocol", "numResults": 1}
    sv_ = viejo.call_tool("web_search_exa", q)
    sn_ = nuevo.call_tool("web_search_exa", q)
    ok(bool(_texto(sv_)) and bool(_texto(sn_)),
       "los dos devolvieron resultados de búsqueda")
    ok(not sv_.get("isError") and not sn_.get("isError"), "ninguno vino en error")
    tipos_v = [c.get("type") for c in (sv_.get("content") or [])]
    tipos_n = [c.get("type") for c in (sn_.get("content") or [])]
    ok(tipos_v == tipos_n, f"misma estructura de `content`: {tipos_v}",
       f"viejo={tipos_v} nuevo={tipos_n}")

finally:
    print("\n── 5 · cierre " + "─" * 63)
    try:
        viejo.close()
        ok(viejo.session_id is None, "el cliente viejo cerró su sesión (DELETE best-effort)")
    except Exception as e:                                 # noqa: BLE001
        ok(False, "el cliente viejo cerró", str(e))
    try:
        nuevo.close()
        ok(True, "el puente cerró (el SDK manda el DELETE al salir del context manager)")
    except Exception as e:                                 # noqa: BLE001
        ok(False, "el puente cerró", str(e))

# ── 6 · LAS FORMAS DE ERROR (insumo del mapa · MAPA-ERRORES-SDK.md) ─────────────────
# El SDK aplasta la capa HTTP: tres fallas distintas llegan como el mismo `-32000`. Lo que
# el puente recupera del transporte —que es nuestro— tiene que alcanzar para el mismo
# diagnóstico tipado que hoy da el cliente viejo. Acá se prueba que alcanza.
print("\n── 6 · las formas de error " + "─" * 50)


def _falla(cls, url, **kw):
    try:
        c = cls(url, **kw)
        c.initialize()
        c.close()
        return None
    except Exception as e:                                 # noqa: BLE001
        return e


_DNS = "https://no-existe-jamas-aleph.example/mcp"
_CERRADO = "http://127.0.0.1:1/mcp"
_HTML = "https://example.com/"

e_dns_n = _falla(ClienteSdkHttp, _DNS, timeout=10)
e_cer_n = _falla(ClienteSdkHttp, _CERRADO, timeout=10)
e_405_v = _falla(MCPHttpClient, _HTML, timeout=15)
e_405_n = _falla(ClienteSdkHttp, _HTML, timeout=15)

ok(all(x is not None for x in (e_dns_n, e_cer_n, e_405_v, e_405_n)),
   "las cuatro fallas fallan (ninguna se cuela como éxito)")

ev_v = getattr(e_405_v, "evidencia", {}) or {}
ev_n = getattr(e_405_n, "evidencia", {}) or {}
ok(ev_v.get("http_status") == ev_n.get("http_status") == 405,
   "HTTP 405: el puente recupera el MISMO `http_status` que el cliente viejo",
   f"viejo={ev_v.get('http_status')} puente={ev_n.get('http_status')}")
nota("sin esto el SDK sólo diría `-32603 Server returned an error response`, y "
     "`diagnostico_conectores` no podría separar 401 (credencial) de 404 (URL) de 5xx.")

d_dns = (getattr(e_dns_n, "evidencia", {}) or {}).get("red_detalle", "")
d_cer = (getattr(e_cer_n, "evidencia", {}) or {}).get("red_detalle", "")
ok(bool(d_dns) and bool(d_cer) and d_dns != d_cer,
   "DNS y puerto cerrado quedan DISTINGUIBLES (el SDK da `-32000` para los dos)",
   f"dns={d_dns!r} cerrado={d_cer!r}")
nota(f"dns     → {d_dns}")
nota(f"cerrado → {d_cer}")

for e, nombre in ((e_dns_n, "DNS"), (e_cer_n, "puerto cerrado")):
    red = (getattr(e, "evidencia", {}) or {}).get("red", {})
    ok(red.get("online") is not True,
       f"{nombre}: la evidencia NO declara `online` — el server no contestó nada")
ok(ev_n.get("red", {}).get("online") is True,
   "HTTP 405: ahí sí `online`, porque el server contestó (aunque contestó mal)")


print(f"\n{'TODO VERDE' if _fallos == 0 else str(_fallos) + ' FALLO(S)'}")
sys.exit(0 if _fallos == 0 else 1)
