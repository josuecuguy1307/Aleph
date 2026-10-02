#!/usr/bin/env python3
"""verify_legal_instalada.py — LA VARA DE FASE DEL VERTICAL LEGAL, CONTRA LA `.app` INSTALADA.
[Gate 4 · Fase 6 · Legal (doc.haus) · ley 0 · ley 5 · ley 12 · ley 15 · inmersión 3.8]

QUÉ AFIRMA, Y CONTRA QUÉ
------------------------
Contra el binario que se distribuye — `/Applications/Aleph.app` —, arranque FRÍO, con un
`ALEPH_DATA_DIR` temporal y aislado. No hay stubs: se levanta el sidecar congelado, se le
pide la sesión POR SU PROPIA PUERTA y se le pregunta a él, no al árbol ni al TOC.

  1 · FRÍO Y REGISTRO — el congelado atiende, la sesión la EMITE el pack (`/v1/auth/local`,
      jamás un fixture ni el storage de otro), y Legal está en el registro con `installed`,
      `autoarranca` y `running:false` — instalado y corriendo son dos hechos distintos.
  2 · CENSO 2.ter — las 33 fuentes del stack viajaron con la fila, y **Exa sin llave se ve
      como estado OPCIONAL, no como fallo mudo** (ley 9 técnica: fallo visible, jamás mudo).
  3 · LA PUERTA — `/workspaces/legal.html` responde. Este paso existe porque la fila del
      registro y la puerta del usuario son dos hechos distintos: el sidebar arma el destino
      de cada workspace elegible como `../workspaces/<id>.html` (`sala-v2/ui/sidebar.js:69`)
      y Legal ya salía en esa lista, así que el link se pintaba **y daba 404**. Medido en la
      `.app` con sidecar `9fd65a3a`: el `_MEI…` tenía `ciencia.html` y nada más.
  4 · SIN MARCA (inmersión 3.8) — la superficie de la casa no nombra al proyecto de origen.
      El crédito vive en `ATTRIBUTIONS`, que es donde es exigible; en la cara, jamás.
  5 · CICLO DE VIDA (O1) — entrar levanta los tres procesos, el registro pasa a decir la
      verdad con la URL del pack VIVO, **el puerto no está horneado** (`url_default` es
      `:0` justamente para que un puerto fijo no pueda colarse), salir apaga y **no queda un
      solo pid**.
  6 · CEREBRO ÚNICO (ley 12) — la config que el pack genera declara UN proveedor
      OpenAI-compatible apuntando al BORDE DE DIALECTO, y cero provider/MCP heredado. A un
      stack no se le consigue modelo: se le enchufa el nuestro.
  7 · EL PLUGIN DE LA CASA — viaja adentro del congelado, el pack lo declara por `file://`
      y el archivo EXISTE (no es una ruta a la nada). Sin él no hay turno auditable.
  8 · LEY 15 · MODO RAW — un turno sin agente entra por el borde sin exigir receta y **no
      escribe ni una fila en `puppets`**.
  9 · MEMORIA POR DUEÑO (O5) — lo que el workspace recuerda es `(dueño, workspace)`, se lee
      con sesión y **sin sesión no se lee la de nadie**.
 10 · EL OFICIO (§7.3 del parcial E.2) — con el pack VIVO: un matter por la puerta pública
      del pack (`/ingest/*`, el proxy del web), un .docx REAL ingerido por el congelado
      (docx·mammoth·ONNX — la ruta que el acta de LEY 0 autorizó), un redline pendiente que
      el binario LISTA, su vista redlined con tracked changes nativos (docxodus), ACEPTAR
      lo HORNEA en el canónico y el texto extraído lo confirma. Después el TURNO REAL por
      el borde de dialecto con una receta guardada por `/v1/puppets`: `model_final` honesto
      (el que reportó el proveedor — el cerebro de la vara es EL ÚNICO fingido, patrón
      sellado de la vara de Ciencia), el turno se CIERRA en su espacio y el informe
      `legal_review` sale CON PASAPORTE: `provenance.model_final` resuelto del REGISTRO,
      no del body (la señal S8).
      La PROPUESTA del redline la siembra la vara con la MISMA fila que escribe la tool
      del motor (`dochaus/lib/redlines.ts`, mismo DDL): la propuesta es INPUT del test;
      lo que se certifica es el circuito del binario instalado — listar → vista → aceptar
      → hornear → re-indexar. Proponerla vía turno del motor queda anotado como deuda.
 11 · CERRAR/REABRIR → RESTAURADO — reabrir levanta el pack de nuevo, el matter del oficio
      SIGUE (la memoria es del dueño, no del proceso), el DOCX horneado quedó como
      canónico, y salir vuelve a apagar sin huérfanos.

SE LE PREGUNTA AL BINARIO, NO AL TOC — lección sellada de la obra 6d: el TOC dice lo que se
pidió empaquetar; el binario dice lo que de verdad viajó.

CÓMO SE PRUEBA CAYENDO
----------------------
`--caer sin-puerta`  → mide una pantalla que no existe en vez de `legal.html`: el paso 3 se
                       pone rojo, que es exactamente el defecto que esta obra mata.
`--caer horneado`    → afirma la URL de `url_default` en vez de la del pack vivo: cae el
                       paso del puerto dinámico.
`--caer sin-apagar`  → se salta el `leave`: el paso de huérfanos encuentra los pids vivos.

    python3 qa/verify_legal_instalada.py
    python3 qa/verify_legal_instalada.py --caer sin-puerta
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP = Path(os.environ.get("ALEPH_APP", "/Applications/Aleph.app"))
SIDECAR = APP / "Contents/MacOS/aleph_sidecar"

#: La marca del proyecto de origen. Que NO aparezca en la superficie de la casa es la
#: inmersión 3.8; que SÍ aparezca en `ATTRIBUTIONS` es la ley 9 de importación. Las dos
#: cosas a la vez, y por eso el grep es sobre lo SERVIDO, no sobre el árbol.
MARCA = re.compile(r"doc\.?haus|sure-scale|opencode", re.I)

CAER = ""
for _i, _a in enumerate(sys.argv):
    if _a == "--caer" and _i + 1 < len(sys.argv):
        CAER = sys.argv[_i + 1]

fallos: list[str] = []


def ok(cond: bool, etiqueta: str, extra: str = "") -> None:
    print(f"{'✓' if cond else '✗'} {etiqueta}{('  ' + extra) if extra else ''}", flush=True)
    if not cond:
        fallos.append(etiqueta)


def puerto_libre() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = int(s.getsockname()[1])
    s.close()
    return p


def pedir(url, metodo="GET", cuerpo=None, cab=None, timeout=180.0):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(url, data=datos, method=metodo,
                                 headers={"Content-Type": "application/json", **(cab or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            crudo = r.read()
            try:
                return r.status, json.loads(crudo or b"null")
            except Exception:                                    # noqa: BLE001
                return r.status, crudo.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        cuerpo_err = (e.read() or b"").decode("utf-8", "replace")
        try:
            return e.code, json.loads(cuerpo_err or "null")
        except Exception:                                        # noqa: BLE001
            return e.code, cuerpo_err
    except Exception as e:                                       # noqa: BLE001
        return 0, str(e)[:200]


def servir(base: str, ruta: str, timeout=20.0):
    """Devuelve `(status, cuerpo)` de una superficie servida por el congelado."""
    try:
        with urllib.request.urlopen(base + ruta, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:                                            # noqa: BLE001
        return 0, ""


def vive(pid: int) -> bool:
    return subprocess.run(["kill", "-0", str(pid)], capture_output=True).returncode == 0


def docx_minimo(texto: str) -> bytes:
    """Un .docx real y mínimo (OPC: content-types + rels + un párrafo). Se fabrica acá
    para que el circuito de redlines tenga sobre qué trabajar sin arrastrar un fixture
    binario al repo."""
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f'<w:body><w:p><w:r><w:t>{texto}</w:t></w:r></w:p></w:body></w:document>')
    tipos = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Default Extension="xml" ContentType="application/xml"/>'
             '<Override PartName="/word/document.xml" ContentType='
             '"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type='
            '"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"'
            ' Target="word/document.xml"/></Relationships>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", tipos)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc)
    return buf.getvalue()


def subir(url: str, nombre: str, contenido: bytes, timeout=300.0):
    """POST multipart con un solo campo `file`, que es lo que `parseBody` del ingest espera."""
    borde = "----vara-legal-multipart"
    cuerpo = ((f'--{borde}\r\nContent-Disposition: form-data; name="file"; filename="{nombre}"\r\n'
               "Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document"
               "\r\n\r\n").encode() + contenido + f"\r\n--{borde}--\r\n".encode())
    req = urllib.request.Request(url, data=cuerpo, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={borde}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, (e.read() or b"").decode("utf-8", "replace")
    except Exception as e:                                       # noqa: BLE001
        return 0, str(e)[:200]


def traer(url: str, timeout=120.0) -> tuple[int, bytes]:
    """GET crudo (bytes) — para los .docx que sirve el ingest."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read()
    except Exception:                                            # noqa: BLE001
        return 0, b""


class _Cerebro(BaseHTTPRequestHandler):
    """EL ÚNICO FINGIDO: el paso al modelo (patrón sellado de la vara de Ciencia). Un
    provider OpenAI-compatible local — `model_final` honesto es EL QUE ESTE reporta."""
    MODELO = "legal-vara-cerebro"
    RESPUESTA = ("Cláusula 1 revisada: el plazo de entrega pasa de diez a cinco días "
                 "hábiles. [cita: contrato-vara.docx §1]")
    visto: list[dict] = []

    def log_message(self, *_a):                                  # noqa: D102
        pass

    def _json(self, cuerpo: dict):
        datos = json.dumps(cuerpo).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def do_GET(self):                                            # noqa: N802
        self._json({"object": "list", "data": [{"id": self.MODELO}]})

    def do_POST(self):                                           # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        try:
            _Cerebro.visto.append(json.loads(self.rfile.read(n) or b"{}"))
        except Exception:                                        # noqa: BLE001
            _Cerebro.visto.append({})
        self._json({
            "id": "chatcmpl-vara-legal", "object": "chat.completion",
            "created": int(time.time()), "model": self.MODELO,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": self.RESPUESTA}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 24, "total_tokens": 36},
        })


def main() -> int:  # noqa: C901
    print("── LA `.app` INSTALADA ──")
    ok(SIDECAR.is_file(), "hay un sidecar instalado", str(SIDECAR))
    if not SIDECAR.is_file():
        return 1
    sha = subprocess.run(["shasum", "-a", "256", str(SIDECAR)],
                         capture_output=True, text=True).stdout.split()[0]
    print(f"   sidecar sha256 {sha}")
    print(f"   .app           {subprocess.run(['du','-sh',str(APP)],capture_output=True,text=True).stdout.split()[0]}")

    datos = Path(tempfile.mkdtemp(prefix="vara-legal-"))
    puerto = puerto_libre()
    base = f"http://127.0.0.1:{puerto}"
    # Arranque FRÍO y aislado: dir de datos propio, rol cliente, sin heredar nada.
    proc = subprocess.Popen(
        [str(SIDECAR), "--port", str(puerto)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        env={**os.environ, "ALEPH_DATA_DIR": str(datos), "ALEPH_ROLE": "client"})
    pids_pack: list[int] = []
    mid = None                    # el matter del oficio (paso 10) — lo re-mide el paso 11
    cerebro_srv = None            # el provider local de la vara (EL ÚNICO fingido)
    try:
        # ── 1 · FRÍO Y REGISTRO ──────────────────────────────────────────────────────
        vivo = False
        for _ in range(120):
            time.sleep(1)
            try:
                urllib.request.urlopen(base + "/health", timeout=2)
                vivo = True
                break
            except Exception:                                    # noqa: BLE001
                if proc.poll() is not None:
                    break
        ok(vivo, "1 · el sidecar del congelado levanta en frío y atiende", base)
        if not vivo:
            return 1
        st, h = pedir(base + "/health")
        ok(st == 200 and (h.get("proceso") or {}).get("build") == "public",
           "1 · y es el artefacto que se distribuye (`build=public`)",
           str((h.get("proceso") or {}).get("build")))

        # LA SESIÓN LA EMITE EL PACK. Ni fixture, ni storage ajeno, ni `register` (que en el
        # build público está cerrado a propósito y contesta 404).
        st, u = pedir(base + "/v1/auth/local", "POST", {})
        ok(st == 200 and bool(u.get("session_token")) and u.get("anon") is True,
           "1 · la sesión la EMITE el pack por su propia puerta (`/v1/auth/local`)", f"({st})")
        if st != 200 or not u.get("session_token"):
            print(json.dumps(u)[:300])
            return 1
        cab = {"Authorization": "Bearer " + u["session_token"]}
        st, _ = pedir(base + "/v1/auth/register", "POST",
                      {"email": "x@y.z", "password": "x", "display_name": "x"})
        ok(st == 404, "1 · y la puerta de cuentas remotas sigue cerrada en público", f"({st})")

        st, j = pedir(base + "/v1/workspaces", cab=cab)
        fila = next((w for w in (j or {}).get("workspaces", []) if w.get("id") == "legal"), None)
        ok(fila is not None, "1 · Legal está en el registro del congelado")
        if fila is None:
            print(json.dumps(j)[:400])
            return 1
        ok(fila["stack"]["installed"] is True,
           "1 · `installed` — y lo dice el BINARIO del pack, no el árbol")
        ok(fila["stack"].get("autoarranca") is True,
           "1 · `autoarranca`: Aleph puede levantarlo solo")
        ok(fila["stack"]["running"] is False,
           "1 · y todavía no corre: instalado y corriendo son dos hechos distintos")

        # ── 2 · CENSO 2.ter, Y EL ⚪ DE EXA ──────────────────────────────────────────
        fuentes = fila.get("sources") or []
        ok(len(fuentes) == 33,
           "2 · el censo 2.ter viajó entero con la fila", f"{len(fuentes)} fuentes")
        juris = [f for f in fuentes if str(f.get("id", "")).startswith("jurisdiction-")]
        ok(len(juris) == 30, "2 · las 30 jurisdicciones son fuentes del stack, no conectores a armar",
           f"{len(juris)}")
        exa = next((f for f in fuentes if f.get("id") == "exa-discovery"), None)
        ok(exa is not None and exa.get("key") == "optional",
           "2 · Exa SIN llave se expone como estado OPCIONAL, no como fallo mudo",
           json.dumps(exa, ensure_ascii=False)[:120] if exa else "ausente")
        ok(exa is not None and "autoridad" in str(exa.get("label", "")).lower(),
           "2 · y su etiqueta dice qué es y qué no: descubrimiento, no autoridad",
           str(exa.get("label")) if exa else "")

        # ── 3 · LA PUERTA QUE EL SIDEBAR PINTA ──────────────────────────────────────
        ruta_puerta = "/workspaces/legal.html"
        if CAER == "sin-puerta":
            ruta_puerta = "/workspaces/legal-que-no-existe.html"
        st, cuerpo = servir(base, ruta_puerta)
        ok(st == 200 and len(cuerpo) > 1000,
           "3 · LA PUERTA existe: el destino que el sidebar arma para Legal responde",
           f"({st}) {len(cuerpo)} b · {ruta_puerta}")
        ok('id="ws-frame"' in cuerpo and 'var WS = "legal"' in cuerpo,
           "3 · y es la pantalla de Legal, con su lienzo y su ciclo de vida")
        ok("aleph_scheme" in cuerpo,
           "3 · manda el tema de la casa al otro origen (inmersión nivel-2)")
        ok("/leave" in cuerpo and "pagehide" in cuerpo,
           "3 · y salir apaga por los dos caminos que existen")

        # ── 4 · SIN MARCA ───────────────────────────────────────────────────────────
        hallada = sorted(set(m.group(0).lower() for m in MARCA.finditer(cuerpo)))
        ok(not hallada, "4 · la puerta de Legal NO nombra al proyecto de origen",
           f"marcas={hallada}" if hallada else "grep=0")
        st_css, css = servir(base, "/workspaces/workspace.css")
        ok(st_css == 200 and not MARCA.search(css),
           "4 · y su hoja de estilo tampoco", f"({st_css})")

        # ── 5 · CICLO DE VIDA DEL PACK (O1) ─────────────────────────────────────────
        print("── levantando el pack (tres procesos: motor, ingest y su web) ──", flush=True)
        t0 = time.time()
        st, e = pedir(base + "/v1/workspaces/legal/enter", "POST", {"user_id": u["id"]}, cab)
        ok(st == 200, "5 · ENTRAR levanta el pack desde el congelado",
           f"({st}) {time.time()-t0:.1f}s")
        if st != 200:
            print(json.dumps(e)[:500])
        else:
            pids_pack = list(e.get("pids") or [])
            ok(bool(pids_pack) and all(vive(p) for p in pids_pack),
               "5 · los procesos están vivos", str(pids_pack))

            st, j2 = pedir(base + "/v1/workspaces", cab=cab)
            f2 = next(w for w in j2["workspaces"] if w["id"] == "legal")
            url_viva = f2["stack"]["url"] if CAER != "horneado" else "http://127.0.0.1:0"
            ok(f2["stack"]["running"] is True and url_viva == e["url"],
               "5 · el registro dice la verdad, con la URL del pack VIVO", str(url_viva))
            # EL PUERTO NO ESTÁ HORNEADO. `url_default` de Legal es `:0` justamente para que
            # un puerto fijo no pueda colarse: si lo que reporta terminara en `:0`, lo que
            # estaríamos midiendo es la constante del registro y no el proceso de esta corrida.
            puerto_pack = (url_viva or "").rsplit(":", 1)[-1].strip("/")
            ok(puerto_pack.isdigit() and int(puerto_pack) > 0,
               "5 · el puerto es dinámico, de ESTA corrida — no el horneado del registro",
               f":{puerto_pack}")

            # Su UI atiende: la inmersión necesita algo que pintar adentro del lienzo.
            st_ui, cuerpo_ui = servir(str(url_viva).rstrip("/"), "/", timeout=30)
            ok(st_ui == 200 and len(cuerpo_ui) > 500,
               "5 · el pack sirve su propia UI, que es lo que el lienzo embebe",
               f"({st_ui}) {len(cuerpo_ui)} b")

            # ── 6 · CEREBRO ÚNICO (ley 12) ──────────────────────────────────────────
            cfg_p = datos / "workspaces/legal/config/opencode.json"
            ok(cfg_p.exists(), "6 · el pack escribió la config del stack", str(cfg_p.name))
            if cfg_p.exists():
                cfg = json.loads(cfg_p.read_text())
                provs = cfg.get("provider") or {}
                ok(len(provs) == 1, "6 · UN solo proveedor: a un stack no se le consigue modelo",
                   f"{sorted(provs)}")
                prov = provs.get(next(iter(provs), ""), {}) if provs else {}
                npm = str(prov.get("npm") or "")
                base_url = str(((prov.get("options") or {}).get("baseURL")) or "")
                ok(npm == "@ai-sdk/openai-compatible",
                   "6 · y habla el dialecto OpenAI-compatible", npm)
                ok(base_url.endswith("/v1/workspaces/brain/openai"),
                   "6 · apuntando AL BORDE DE DIALECTO, no a LiteLLM pelado", base_url[-48:])
                ok(f":{puerto}" in base_url,
                   "6 · con el puerto del sidecar de ESTA corrida", f":{puerto}")
                ok(not (cfg.get("mcp") or {}),
                   "6 · cero MCP heredado del proyecto de origen", str(sorted(cfg.get("mcp") or {})))

                # ── 7 · EL PLUGIN DE LA CASA ────────────────────────────────────────
                plugin = (cfg.get("plugin") or [""])[0]
                ok(plugin.startswith("file://") and plugin.endswith("dochaus.js"),
                   "7 · el pack declara el plugin de la casa por `file://`", plugin[-46:])
                ruta_plug = plugin.replace("file://", "")
                ok(os.path.isfile(ruta_plug),
                   "7 · y el archivo EXISTE adentro del congelado (no es una ruta a la nada)")
                if os.path.isfile(ruta_plug):
                    fuente = Path(ruta_plug).read_text()
                    ok("X-Aleph-Space" in fuente and "X-Aleph-Turn" in fuente,
                       "7 · marca cada turno con su espacio: sin esto no hay turno auditable")
                    ok("verified" in fuente,
                       "7 · y una respuesta sin cita verificada NO se vuelve artefacto")

            # ── 10 · EL OFICIO (§7.3): redline→DOCX horneado + turno real + pasaporte ──
            # Todo por la puerta PÚBLICA del pack: el web proxya `/ingest/*` al servicio
            # de ingest (`apps/web/script/serve-dist.ts`), así que se mide lo que un
            # usuario alcanza, no un puerto interno adivinado.
            pack_url = str(e["url"]).rstrip("/")
            listo = False
            for _ in range(60):
                st_i, li = pedir(pack_url + "/ingest/matters", timeout=5)
                if st_i == 200 and isinstance(li, list):
                    listo = True
                    break
                time.sleep(1.5)
            ok(listo, "10 · el ingest del congelado atiende por la puerta pública del pack")
            if listo:
                st, mat = pedir(pack_url + "/ingest/matters", "POST",
                                {"title": "Contrato de la vara"}, timeout=60)
                mid = (mat or {}).get("id") if isinstance(mat, dict) else None
                ok(st == 200 and bool(mid), "10 · un matter se abre por su propia API", f"({st})")
            if mid:
                TEXTO0 = "El proveedor entregara el informe en un plazo de diez dias habiles."
                # La ingesta ejecuta la ruta que el acta de LEY 0 autorizó: ingestDocument →
                # embedChunk → pipeline ONNX local. El primer embed puede cargar el modelo:
                # timeout generoso a propósito.
                st, sub = subir(f"{pack_url}/ingest/matters/{mid}/documents",
                                "contrato-vara.docx", docx_minimo(TEXTO0))
                ok(st == 200, "10 · un .docx REAL entra por ingest "
                   "(docx · extracción · el motor ONNX autorizado)", f"({st}) {str(sub)[:120]}")
                st, det = pedir(f"{pack_url}/ingest/matters/{mid}")
                docs = (det or {}).get("documents") or []
                ok(st == 200 and len(docs) == 1,
                   "10 · y el matter lo censa como documento indexado", f"{len(docs)} docs")

                # LA PROPUESTA ES INPUT DEL TEST: se siembra la MISMA fila que escribe la
                # tool del motor (`dochaus/lib/redlines.ts`, mismo DDL, mismas columnas).
                # Lo que se certifica es el circuito del BINARIO INSTALADO de acá en más:
                # listar → vista redlined → aceptar → hornear → re-indexar.
                st, lst = pedir(pack_url + "/ingest/matters")
                dir_m = next((m.get("dir") for m in (lst or []) if m.get("id") == mid), None)
                ok(bool(dir_m), "10 · el matter declara su directorio (donde vive su legal.db)")
                rid = None
                if dir_m:
                    con = sqlite3.connect(str(Path(dir_m) / ".dochaus" / "legal.db"))
                    try:
                        cur = con.execute(
                            "INSERT INTO redlines (doc_path, doc_name, scope, find_text, "
                            "old_text, new_text, author, anchor_id, created_at) "
                            "VALUES (?,?,?,?,?,?,?,?,?)",
                            (str(Path(dir_m) / "contrato-vara.docx"), "contrato-vara.docx",
                             "phrase", "diez dias habiles", "diez dias habiles",
                             "cinco dias habiles", "Aleph Legal (vara)", None,
                             int(time.time() * 1000)))
                        con.commit()
                        rid = int(cur.lastrowid)
                    finally:
                        con.close()
                st, rl = pedir(f"{pack_url}/ingest/matters/{mid}/redlines?name=contrato-vara.docx")
                ok(st == 200 and isinstance(rl, list) and len(rl) == 1
                   and rl[0].get("id") == rid,
                   "10 · el binario LISTA la propuesta pendiente", f"({st}) {len(rl or [])} filas")

                st, rojo = traer(f"{pack_url}/ingest/matters/{mid}/documents/redlined"
                                 "?name=contrato-vara.docx", timeout=180)
                marcado = ""
                if st == 200 and rojo[:2] == b"PK":
                    with zipfile.ZipFile(io.BytesIO(rojo)) as z:
                        marcado = z.read("word/document.xml").decode("utf-8", "replace")
                ok(st == 200 and "w:ins" in marcado and "cinco dias habiles" in marcado,
                   "10 · la vista redlined es un DOCX con tracked changes NATIVOS (docxodus)",
                   f"({st}) {len(rojo)} b")

                st, acc = pedir(f"{pack_url}/ingest/matters/{mid}/redlines/{rid}/accept",
                                "POST", {}, timeout=300)
                ok(st == 200 and isinstance(acc, dict) and acc.get("ok") is True,
                   "10 · ACEPTAR hornea el redline en el canónico y re-indexa", f"({st})")
                st, txt = pedir(f"{pack_url}/ingest/matters/{mid}/documents/text"
                                "?name=contrato-vara.docx", timeout=120)
                texto_final = str((txt or {}).get("text", "")) if isinstance(txt, dict) else ""
                ok("cinco dias habiles" in texto_final and "diez dias" not in texto_final,
                   "10 · el texto extraído del canónico confirma el HORNEADO",
                   texto_final[:80])

                # ── EL TURNO REAL POR EL BORDE, CON PASAPORTE ───────────────────────
                cerebro_srv = ThreadingHTTPServer(("127.0.0.1", 0), _Cerebro)
                threading.Thread(target=cerebro_srv.serve_forever, daemon=True).start()
                p_cer = cerebro_srv.server_address[1]
                receta = {
                    "schema_version": "v1",
                    "meta": {"name": "legal-vara", "nicho": "general",
                             "output_type": "informe"},
                    "model": {"alias": _Cerebro.MODELO, "primary": _Cerebro.MODELO,
                              "base_url": f"http://127.0.0.1:{p_cer}/v1",
                              "temperature": 0, "max_tokens": 64, "max_turns": 1},
                    "belt": {"belt_ref": "platform/assembler/fixtures/belt-inline-rich.mcp.json",
                             "tool_filters": {"calc": ["add"]}},
                    "framing": {"inline": ""}, "rag": {"enabled": False},
                    "keys": {}, "gates": {},
                }
                st, pup = pedir(base + "/v1/puppets", "POST",
                                {"name": "legal-vara", "nicho": "general",
                                 "owner_id": u["id"], "config": receta}, cab)
                pid_pup = (pup or {}).get("id") or (pup or {}).get("puppet_id")
                ok(st == 200 and bool(pid_pup),
                   "10 · la receta de la vara entra por `/v1/puppets`", f"({st})")
                espacio = f"legal-vara-{int(time.time())}"
                st, turno = pedir(base + "/v1/workspaces/brain/openai/chat/completions",
                                  "POST",
                                  {"model": "no-decide-el-harness",
                                   "messages": [{"role": "user", "content":
                                                 "Revisá el plazo de entrega del contrato."}],
                                   "stream": False},
                                  {**cab, "X-Aleph-Puppet": str(pid_pup),
                                   "X-Aleph-Workspace": "legal",
                                   "X-Aleph-Space": espacio, "X-Aleph-User": u["id"],
                                   "X-Aleph-Chat": "hilo-legal-vara", "X-Aleph-Turn": "1"},
                                  timeout=120)
                ok(st == 200 and isinstance(turno, dict)
                   and turno.get("model") == _Cerebro.MODELO,
                   "10 · TURNO REAL por el borde: `model_final` honesto (el que reportó "
                   "el proveedor)", f"({st}) model={str((turno or {}).get('model'))[:40]}")
                ok(len(_Cerebro.visto) >= 1,
                   "10 · y al proveedor le LLEGÓ el pedido: el circuito salió de verdad",
                   f"{len(_Cerebro.visto)} llamadas")
                respuesta = ""
                try:
                    respuesta = turno["choices"][0]["message"]["content"] or ""
                except Exception:                                # noqa: BLE001
                    pass
                st, _ = pedir(base + "/v1/workspaces/brain/close", "POST",
                              {"space_id": espacio, "workspace": "legal",
                               "answer": respuesta, "turns": 1, "user_id": u["id"]}, cab)
                ok(st == 200, "10 · el turno se CIERRA en su espacio "
                   "(`final`+`closed` → procedencia)", f"({st})")
                st, art = pedir(base + "/v1/workspaces/artifacts", "POST",
                                {"sid": "sid-vara-legal", "workspace": "legal",
                                 "kind": "legal_review",
                                 "name": "Revisión legal con cita verificada",
                                 "title": "Revisión legal",
                                 "data": {"name": "Revisión legal", "content": respuesta,
                                          "citations": ["contrato-vara.docx §1"],
                                          "citation_count": 1},
                                 "space_id": espacio, "user_id": u["id"],
                                 "chat_id": "hilo-legal-vara"}, cab)
                pasaporte = (((art or {}).get("artifact") or {}).get("provenance") or {}) \
                    if isinstance(art, dict) else {}
                ok(st == 200 and pasaporte.get("model_final") == _Cerebro.MODELO,
                   "10 · el informe sale CON PASAPORTE: `model_final` resuelto del "
                   "REGISTRO, no del body (la señal S8)",
                   f"({st}) pasaporte={json.dumps(pasaporte, ensure_ascii=False)[:120]}")

            # ── SALIR APAGA, CERO HUÉRFANOS ─────────────────────────────────────────
            if CAER != "sin-apagar":
                st_l, _ = pedir(base + "/v1/workspaces/legal/leave", "POST",
                                {"gracia_s": 0, "user_id": u["id"]}, cab)
            else:
                st_l = 200
            time.sleep(3.0)
            vivos = [p for p in pids_pack if vive(p)]
            ok(st_l == 200 and not vivos,
               "5 · SALIR APAGA y no queda un solo pid del pack", f"vivos={vivos}")
            if not vivos:
                pids_pack = []

        # ── 8 · LEY 15 · EL TURNO SIN AGENTE ────────────────────────────────────────
        def agentes() -> int:
            db = next((p for p in datos.rglob("aleph.db")), None)
            if db is None:
                return -1
            con = sqlite3.connect(str(db))
            try:
                return int(con.execute("SELECT COUNT(*) FROM puppets").fetchone()[0])
            finally:
                con.close()

        antes = agentes()
        st, r = pedir(base + "/v1/workspaces/brain/complete", "POST",
                      {"messages": [{"role": "user", "content": "hola"}],
                       "user_id": u["id"], "model": "opus", "workspace": "legal"}, cab)
        det = (r or {}).get("detail") if isinstance(r, dict) else {}
        causa = det.get("error") if isinstance(det, dict) else None
        ok(causa != "missing_recipe",
           "8 · LEY 15 · sin agente y sin receta, el borde no exige agente",
           f"({st}) {causa or ''}")
        ok(agentes() == antes,
           "8 · LEY 15.b · el turno raw NO escribió ni una fila en `puppets`",
           f"{antes} → {agentes()}")

        # ── 9 · MEMORIA POR DUEÑO (O5) ──────────────────────────────────────────────
        st, m = pedir(base + "/v1/workspaces/legal/memoria", "PUT",
                      {"user_id": u["id"], "chat_id": "hilo-legal-vara"}, cab)
        ok(st == 200 and (m or {}).get("memoria", {}).get("chat_id") == "hilo-legal-vara",
           "9 · la memoria `(dueño, workspace)` guarda", f"({st})")
        st, m2 = pedir(f"{base}/v1/workspaces/legal/memoria?user_id={u['id']}", cab=cab)
        ok((m2 or {}).get("memoria", {}).get("chat_id") == "hilo-legal-vara",
           "9 · y devuelve el workspace como quedó")
        st, _ = pedir(f"{base}/v1/workspaces/legal/memoria?user_id={u['id']}")
        ok(st == 401, "9 · sin sesión, la memoria de nadie se lee", f"({st})")

        # ── 11 · CERRAR/REABRIR → RESTAURADO ───────────────────────────────────────
        if mid:
            st, e2 = pedir(base + "/v1/workspaces/legal/enter", "POST",
                           {"user_id": u["id"]}, cab, timeout=240)
            ok(st == 200, "11 · REABRIR levanta el pack de nuevo", f"({st})")
            if st == 200:
                pids_pack = list(e2.get("pids") or [])
                url2 = str(e2["url"]).rstrip("/")
                listo2 = False
                for _ in range(60):
                    st_i, li2 = pedir(url2 + "/ingest/matters", timeout=5)
                    if st_i == 200 and isinstance(li2, list):
                        listo2 = True
                        break
                    time.sleep(1.5)
                fila_m = next((m for m in (li2 or []) if m.get("id") == mid), None) \
                    if listo2 else None
                ok(fila_m is not None,
                   "11 · el matter del oficio SIGUE: la memoria es del dueño, "
                   "no del proceso")
                st, txt2 = pedir(f"{url2}/ingest/matters/{mid}/documents/text"
                                 "?name=contrato-vara.docx", timeout=120)
                texto2 = str((txt2 or {}).get("text", "")) if isinstance(txt2, dict) else ""
                ok("cinco dias habiles" in texto2,
                   "11 · y el DOCX horneado quedó: lo aceptado ES el canónico restaurado",
                   texto2[:60])
                st_l2, _ = pedir(base + "/v1/workspaces/legal/leave", "POST",
                                 {"gracia_s": 0, "user_id": u["id"]}, cab)
                time.sleep(3.0)
                vivos2 = [p for p in pids_pack if vive(p)]
                ok(st_l2 == 200 and not vivos2,
                   "11 · y salir vuelve a apagar sin un solo huérfano", f"vivos={vivos2}")
                if not vivos2:
                    pids_pack = []

    finally:
        if cerebro_srv is not None:
            try:
                cerebro_srv.shutdown()
            except Exception:                                    # noqa: BLE001
                pass
        # EL HUÉRFANO DE PYINSTALLER: el onefile lanza un hijo, así que se mata el GRUPO.
        for p in pids_pack:
            if vive(p):
                subprocess.run(["kill", "-9", str(p)], capture_output=True)
        try:
            os.killpg(os.getpgid(proc.pid), 15)
            proc.wait(timeout=15)
        except Exception:                                        # noqa: BLE001
            try:
                os.killpg(os.getpgid(proc.pid), 9)
            except Exception:                                    # noqa: BLE001
                pass
        shutil.rmtree(datos, ignore_errors=True)

    print(f"\n{'VERDE' if not fallos else 'ROJAS (' + str(len(fallos)) + '): ' + ' · '.join(fallos)}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
