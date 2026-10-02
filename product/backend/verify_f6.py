#!/usr/bin/env python3
"""verify_f6.py — LA VARA DE F6-CIERRE. Las tres obras, medidas.

    product/backend/.venv/bin/python product/backend/verify_f6.py

  A · DISCOVERY  — el catálogo de la vía API sale del proveedor, no de una constante.
  B · USAGE      — el uso que el proveedor ya manda deja de tirarse.
  C · CANCELAR   — parar una vía HTTP cierra el socket, con su causa tipada.

⚠️ NO ANIDA. Corre sólo lo suyo (regla sellada: `aleph-varas-sin-anidar`). El chequeo
completo es UNA corrida de `qa/correr_varas.py`, aparte.

SIN RED EXTERNA. El corte se mide contra un **stub local** que streamea despacio y anota
cuántos chunks logró escribir: así «el socket se murió» es un número, no una impresión. El
discovery se mide con payloads con la FORMA real medida contra OpenRouter el 2026-08-05
(no inventada: pegada de la respuesta viva).
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.phase1 import modelos_discovery as disc      # noqa: E402
from app.phase1 import stream_chat as sc              # noqa: E402
from app.phase1 import turnos_http as th              # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
FALLOS: list[str] = []
_t0 = time.time()


def ok(cond: bool, texto: str) -> None:
    print(f"  {'✓' if cond else '❌'} {texto}")
    if not cond:
        FALLOS.append(texto)


def titulo(s: str) -> None:
    print(f"\n── {s} " + "─" * max(0, 76 - len(s)))


# ══════════════════════════════════════════════════════════════════════════════════
titulo("A1 · CENSO: la vía API no elige por constante")
# ══════════════════════════════════════════════════════════════════════════════════
# El guard mira el MÓDULO DE DISCOVERY, que es el único que ahora decide qué modelo se usa
# en la vía API. Un id nuevo hardcodeado acá sería exactamente la regresión que la obra A
# vino a impedir: volver a escribir en piedra algo que el proveedor cambia sin avisar.
_fuente_disc = (RAIZ / "product/backend/app/phase1/modelos_discovery.py").read_text(encoding="utf-8")


def _solo_codigo(src: str) -> str:
    """El fuente SIN docstrings ni comentarios.

    ⚠️ Esto NO es cosmética: la primera versión del guard salió roja por un id que estaba
    en la PROSA («_PICKER_HOSTEADO declaraba openai/gpt-4o»), citado justamente para
    explicar el problema que la obra resuelve. Un guard que no distingue lo que el
    programa HACE de lo que el programa CUENTA castiga documentar, y el castigo se paga
    borrando la explicación — que es lo último que uno quiere que pase.
    """
    import ast
    arbol = ast.parse(src)
    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            d = ast.get_docstring(nodo, clean=False)
            if d:
                src = src.replace(d, "")
    return "\n".join(l.split("#", 1)[0] if not l.lstrip().startswith("#") else ""
                     for l in src.splitlines())


_ids = re.findall(r'"([a-z0-9_-]+/[A-Za-z0-9._:-]+)"', _solo_codigo(_fuente_disc))
_ids_reales = [i for i in _ids if not i.startswith(("http", "application"))]
ok(set(_ids_reales) <= {disc.FALLBACK_DECLARADO},
   f"el ÚNICO id hardcodeado del discovery es el fallback declarado "
   f"({disc.FALLBACK_DECLARADO}) · encontrados: {sorted(set(_ids_reales)) or 'ninguno'}")
ok("FALLBACK_DECLARADO" in _fuente_disc and "suelo" in _fuente_disc.lower(),
   "y está NOMBRADO como fallback, con su motivo escrito (no un literal suelto)")

# ★ Y EL CATÁLOGO ESTÁ CABLEADO. Esto es lo que la primera corrida cazó de verdad: el
# módulo existía y `_PICKER_HOSTEADO["api.openrouter"]` seguía decretando su id. Un
# discovery que nadie llama es código muerto con buena documentación.
_src_cm = (RAIZ / "product/backend/app/phase1/centro_modelos.py").read_text(encoding="utf-8")
ok("_modelo_de_api(" in _src_cm and 'familia") or "") == "api"' in _src_cm,
   "★ el selector RESUELVE el modelo de las vías API por discovery, no por la constante")
# ⚠️ [F8 · obra 2] ESTA VARA AFIRMABA LA REGLA DE F6, QUE HOY ESTÁ SUPERADA — y por eso se
# DA VUELTA en vez de borrarse (misma decisión que obra 0 tomó con `verify_f4c:408`).
#
# F6 selló: «el id escrito entra como preferencia, no como decreto». Cierto y sigue siendo
# cierto. Lo que cambió es que **ahora hay DOS preferencias y no empatan**: la del usuario
# —persistida, explícita— le gana al id escrito, que baja a semilla del primer arranque.
# Chequear literalmente `preferido=declarado` habría exigido que el id escrito siguiera
# siendo el de mayor rango: una vara verde defendiendo lo contrario de la ley vigente.
ok("preferido=(eleccion or declarado)" in _src_cm,
   "★ el id escrito entra como PREFERENCIA y NO como decreto (F6) — y desde F8 con un "
   "rango por encima: la elección del usuario gana si sigue viva, y sólo si murió se "
   "re-elige del catálogo")
ok("eleccion" in _src_cm and '"usuario"' in _src_cm,
   "★ …y QUIÉN eligió viaja con la fila: «lo elegiste vos» y «lo elegimos nosotros» no son "
   "la misma frase, y sin este dato la superficie tendría que adivinarlo")


# ══════════════════════════════════════════════════════════════════════════════════
titulo("A2 · DISCOVERY: normaliza el catálogo REAL a la forma de §11")
# ══════════════════════════════════════════════════════════════════════════════════
# Forma REAL, medida contra openrouter.ai/api/v1/models el 2026-08-05.
CRUDO_OR = {
    "id": "qwen/qwen3.6-plus", "name": "Qwen: Qwen3.6 Plus",
    "context_length": 262144,
    "pricing": {"prompt": "0.0000004", "completion": "0.0000012"},
    "architecture": {"input_modalities": ["text", "image"]},
    "supported_parameters": ["tools", "reasoning", "temperature"],
}
n = disc.normalizar("openrouter", CRUDO_OR)
# ⚠️ [F9] LA FORMA CRECIÓ EN UNO, Y ES UNA DECISIÓN. Esta vara decía «§11 y NADA más», que
# es exactamente para lo que existe: que la forma no se ensanche por descuido. Se ensancha
# a propósito.
#
# El motivo: `capacidades` es una proyección CON PÉRDIDA. `whisper` (transcribe) y `orpheus`
# (habla) salen los dos con `capacidades=()`, así que desde ahí un rechazo sólo puede ser
# genérico — y la regla sellada por persona usuaria el 2026-08-07 es que cada motivo tenga SU copy,
# derivado de lo que el catálogo DECLARA. Sin `salidas` ese copy habría que inventarlo.
#
# Sigue siendo una lista CERRADA: se agrega el campo al set, no se afloja el chequeo.
ok(n is not None and set(n) == {"provider_id", "model_id", "label", "context",
                                "capacidades", "free", "salidas"},
   f"la forma es la de §11 + `salidas` (F9) y NADA más: {sorted(n or {})}")
ok(n["provider_id"] == "openrouter" and n["model_id"] == "qwen/qwen3.6-plus",
   "provider_id · model_id salen del crudo, no del nombre del archivo")
ok(n["context"] == 262144, f"context normalizado a entero: {n['context']}")
ok(set(n["capacidades"]) == {"texto", "vision", "tools", "razonamiento"},
   f"capacidades derivadas de modalidades+parámetros: {sorted(n['capacidades'])}")
ok(n["free"] is False, "con precio > 0 → free=False")

libre = disc.normalizar("openrouter", {"id": "openai/gpt-oss-20b:free",
                                       "pricing": {"prompt": "0", "completion": "0"}})
ok(libre["free"] is True, "con precio 0 → free=True")

# ★ `free` SE MIRA POR PRECIO, NO POR EL SUFIJO DEL NOMBRE. `:free` es una convención de
# OpenRouter que otros proveedores no usan, y un modelo puede ser gratis sin llamarse así.
sin_sufijo = disc.normalizar("groq", {"id": "meta/algo-gratis",
                                      "pricing": {"prompt": "0", "completion": "0"}})
ok(sin_sufijo["free"] is True,
   "★ gratis SIN el sufijo `:free` igual sale free=True — se mira el precio, no el nombre")
sin_precio = disc.normalizar("x", {"id": "a/b"})
ok(sin_precio["free"] is None,
   "★ y sin precios declarados free es None, NO False: «no sé» y «no es gratis» son "
   "distintos, y un False inventado escondería modelos gratis del selector")

ok(disc.normalizar("x", {"name": "sin id"}) is None,
   "una entrada sin `id` se descarta en vez de viajar rota")

# ★ LOS DOS FILTROS QUE SALIERON DE MIRAR EL CATÁLOGO REAL, no de imaginarlo. Sin ellos,
# «elegí el más grande» daba respuestas absurdas con toda la lógica correcta.
musica = disc.normalizar("openrouter", {
    "id": "google/lyria-3-clip-preview", "context_length": 1048576,
    "pricing": {"prompt": "0", "completion": "0"},
    "architecture": {"input_modalities": ["text", "image"],
                     "output_modalities": ["text", "audio"], "tokenizer": "Other"}})
ok("texto" not in musica["capacidades"],
   "★ un modelo que contesta con AUDIO no tiene capacidad `texto` — el de música declaraba "
   "1.048.576 de contexto y ganaba «el más grande gratis»")
router = disc.normalizar("openrouter", {
    "id": "openrouter/auto", "context_length": 2000000,
    "architecture": {"input_modalities": ["text"], "output_modalities": ["text", "image"],
                     "tokenizer": "Router"}})
ok("router" in router["capacidades"],
   "★ y un meta-router se marca como tal: declara 2.000.000 de contexto, pero elegirlo es "
   "delegar en la heurística de OTRO qué modelo corre, y `model_id` deja de decir qué corrió")

cat_sucio = {"provider_id": "openrouter", "fuente": "red", "modelos": [musica, router,
             {"provider_id": "openrouter", "model_id": "real/chat", "context": 128000,
              "capacidades": ["texto"], "free": True}]}
ok(disc.elegir(cat_sucio) == "real/chat",
   "★ con música y router en la lista, `elegir` igual devuelve el chat de verdad")


# ══════════════════════════════════════════════════════════════════════════════════
titulo("A3 · CADUCIDAD del caché y ELECCIÓN del catálogo vivo")
# ══════════════════════════════════════════════════════════════════════════════════
from app.phase1 import modelos_caducidad as cad       # noqa: E402
ok(cad.rancia("2020-01-01T00:00:00") is True, "un catálogo viejo se declara rancio")
ok(cad.rancia(None) is False,
   "y SIN catálogo previo no es rancio: «nunca se descubrió» tiene otro camino")

cat = {"provider_id": "openrouter", "fuente": "red", "descubierto_en": "2026-08-05T00:00:00",
       "modelos": [
           {"provider_id": "openrouter", "model_id": "chico/a", "context": 8192,
            "capacidades": ["texto"], "free": True},
           {"provider_id": "openrouter", "model_id": "grande/b", "context": 262144,
            "capacidades": ["texto"], "free": False},
           {"provider_id": "openrouter", "model_id": "medio/c", "context": 32768,
            "capacidades": ["texto"], "free": True},
       ]}
ok(disc.elegir(cat) == "grande/b", "elige el más grande servible (por context)")
ok(disc.elegir(cat, solo_gratis=True) == "medio/c",
   "con `solo_gratis` elige el más grande DE LOS GRATIS")
ok(disc.elegir(cat, preferido="chico/a") == "chico/a",
   "★ y el preferido del usuario GANA si sigue vivo: la elección de una persona no se la "
   "come una heurística")
ok(disc.elegir(cat, preferido="muerto/x") == "grande/b",
   "pero un preferido que ya no existe NO se respeta a ciegas: se vuelve a elegir")


# ══════════════════════════════════════════════════════════════════════════════════
titulo("A4 · UN ID QUE MURIÓ SALE TIPADO, jamás como 404 crudo")
# ══════════════════════════════════════════════════════════════════════════════════
c = disc.verificar_vigente("openrouter", "qwen/qwen3.6-plus:free", cat)
ok(c is not None and c["causa"] == "modelo_no_disponible",
   f"un id ausente del catálogo → causa `{(c or {}).get('causa')}` (el caso REAL de F6-bis)")
ok(c and c.get("re_descubrir") is True,
   "★ y la acción que ofrece es RE-DESCUBRIR, no «reintentá»: reintentar el mismo id "
   "muerto falla igual, y ofrecerlo sería mandar al usuario a chocar dos veces")
ok(c and c["evidencia"].get("catalogo_de") == "2026-08-05T00:00:00",
   "la evidencia dice DE CUÁNDO es el catálogo con el que se juzgó")
ok(disc.verificar_vigente("openrouter", "grande/b", cat) is None,
   "un id vivo no molesta a nadie")
ok(disc.verificar_vigente("openrouter", "loquesea", {"fuente": "ninguna", "modelos": []}) is None,
   "★ y SIN catálogo se CALLA: afirmar «ese modelo no existe» porque se cayó la red sería "
   "inventar un diagnóstico")


# ══════════════════════════════════════════════════════════════════════════════════
titulo("B · USAGE: el dato que llegaba y se tiraba, con el contrato de F2c")
# ══════════════════════════════════════════════════════════════════════════════════
u = sc._normalizar_uso({"prompt_tokens": 16, "completion_tokens": 34,
                        "total_tokens": 50, "cost": 0.0000715})
ok(u and u["total_tokens"] == 50 and u["tokens_medidos"] is True,
   f"el uso REAL de OpenRouter llega medido: {u}")
ok(u and abs(u["usd"] - 0.0000715) < 1e-12, "y el costo en USD viaja tal cual vino")
ok(sc._normalizar_uso({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}) is None,
   "★ un total en CERO no se reemite: un cero se lee «salió gratis», que es una "
   "afirmación. `None` jamás cero")
ok(sc._normalizar_uso({}) is None, "sin datos no hay evento de uso que inventar")
solo = sc._normalizar_uso({"total_tokens": 42})
ok(solo and solo["usd"] is None and solo["tokens_medidos"] is True,
   "tokens sin costo: medidos=True y usd=None (no un 0.0 fabricado)")

_src_sc = (RAIZ / "product/backend/app/phase1/stream_chat.py").read_text(encoding="utf-8")
ok('"stream_options"' in _src_sc and "include_usage" in _src_sc,
   "se PIDE `stream_options.include_usage` (los que la respetan la necesitan)")
ok("if not _is_cli_brain_endpoint(base_url):" in _src_sc.split("stream_options")[0][-200:],
   "★ y NO se le manda al cerebro CLI: ése ya publica su uso en su annex (F2c) y su "
   "payload no se toca")
_src_r = (RAIZ / "product/backend/app/phase1/router.py").read_text(encoding="utf-8")
ok('kind == "usage"' in _src_r and _src_r.index('kind == "usage"') < _src_r.index("full.append(tok)"),
   "★ el router intercepta `usage` ANTES del acumulador: si cayera al `full`, un JSON "
   "crudo terminaría adentro del texto que lee el usuario")
ok('"tokens_medidos": False' in _src_r,
   "y si el proveedor no manda nada se DECLARA no-medible en vez de callar")


# ══════════════════════════════════════════════════════════════════════════════════
titulo("C · CANCELACIÓN HTTP: parar cierra el socket (medido con stub)")
# ══════════════════════════════════════════════════════════════════════════════════
ESCRITOS = {"n": 0}
TOPE = 400


class _Stub(BaseHTTPRequestHandler):
    """SSE lento. Anota cuántos chunks LOGRÓ escribir: cuando el cliente cierra, el
    `write` revienta y el número se congela — así «el server deja de recibir consumo» es
    una medición y no una impresión."""

    protocol_version = "HTTP/1.1"

    def do_POST(self):                             # noqa: N802
        largo = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(largo)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        try:
            for i in range(TOPE):
                trozo = json.dumps({"choices": [{"delta": {"content": f"t{i} "}}]})
                datos = f"data: {trozo}\n\n".encode()
                self.wfile.write(f"{len(datos):X}\r\n".encode() + datos + b"\r\n")
                self.wfile.flush()
                ESCRITOS["n"] = i + 1
                time.sleep(0.05)
        except Exception:                          # noqa: BLE001 — el cliente cortó: esperado
            pass

    def log_message(self, *a):                     # silencio
        return


srv = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
PUERTO = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

eventos: list = []
error: list = []


def _consumir():
    try:
        for ev in sc._stream_openai(f"http://127.0.0.1:{PUERTO}/v1", "m", "k",
                                    "sys", "hola", 4096, 0.0):
            eventos.append(ev)
    except Exception as exc:                       # noqa: BLE001 — lo que sube es el veredicto
        error.append(exc)


h = threading.Thread(target=_consumir, daemon=True)
h.start()

# Esperar a que el turno esté en vuelo Y haya empezado a llegar texto.
tid = None
for _ in range(100):
    time.sleep(0.05)
    t = [e for e in eventos if e[0] == "turno"]
    if t and any(e[0] == "token" for e in eventos):
        tid = t[0][1]
        break

ok(tid is not None, f"la vía HTTP EMITE su `turno_id` (el canal que antes no existía): {tid}")
tokens_antes = sum(1 for e in eventos if e[0] == "token")
escritos_al_parar = ESCRITOS["n"]

res = th.detener(tid) if tid else {"resultado": "no_habia_turno"}
ok(res.get("resultado") == "turno_detenido",
   f"`detener` contesta con el vocabulario de F2d: {res.get('resultado')}")
ok(res.get("via") == "api", f"y dice por qué vía era el turno: {res.get('via')}")

h.join(timeout=10)
ok(not h.is_alive(), "el generador TERMINÓ (no quedó leyendo un socket muerto)")
ok(error and getattr(error[0], "causa", None) is not None
   and error[0].causa.causa == "turno_detenido",
   f"★ el corte sale TIPADO como `turno_detenido`, no como «se cortó la conexión»: "
   f"{getattr(error[0], 'causa', None) and error[0].causa.causa}")
ok(error and error[0].causa.reintentable is True,
   "★ y reintentable=True: no falló, lo pararon — esconder el botón de reintentar "
   "castigaría a alguien que sólo cambió de opinión")

time.sleep(0.6)                                    # que el stub choque con el socket muerto
escritos_final = ESCRITOS["n"]
ok(escritos_final < TOPE,
   f"★ EL SERVER DEJÓ DE RECIBIR CONSUMO: escribió {escritos_final} de {TOPE} chunks. "
   f"Parar cerró el socket de verdad — mientras siga abierto, el proveedor sigue "
   f"generando y, en las vías con costo, sigue cobrando")
ok(escritos_final - escritos_al_parar < 25,
   f"y se detuvo CERCA del pedido (escritos al parar: {escritos_al_parar} → "
   f"final: {escritos_final})")
ok(th.vivos() == [] or all(v["turno_id"] != tid for v in th.vivos()),
   "el registro quedó limpio: un id que sobrevive pararía un turno que no es")

# El otro final del vocabulario: parar algo que ya terminó NO es un error.
ok(th.detener("http-inexistente")["resultado"] == "no_habia_turno",
   "★ parar un turno que ya terminó da `no_habia_turno`, no un 4xx: apretar justo cuando "
   "llegaba la respuesta es lo normal, y un cartel rojo ahí convierte un final feliz en "
   "un fallo")

srv.shutdown()


# ══════════════════════════════════════════════════════════════════════════════════
print()
print("═" * 84)
if FALLOS:
    print(f"❌ {len(FALLOS)} ROJAS · {time.time() - _t0:.2f}s")
    for f in FALLOS:
        print(f"   ✗ {f}")
    sys.exit(1)
# [H3] La nota al pie va ARRIBA del veredicto: la última línea es la que se lee para
# decidir un merge.
print("     [invocación única del chequeo completo]  product/backend/.venv/bin/python qa/correr_varas.py")
print(f"TODO VERDE · {time.time() - _t0:.2f}s")
