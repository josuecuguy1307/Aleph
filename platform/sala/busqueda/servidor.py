#!/usr/bin/env python3
"""servidor.py — LA BÚSQUEDA WEB DE LA SALA, SIN LA CARA DE VANE.
[Gate 4 · Fase 6 · §6.a.bis]

QUÉ ES ESTO, Y QUÉ NO ES
------------------------
Es **código de Aleph** —por eso vive en `platform/` y no en `third_party/`— y es el
gemelo exacto de `platform/sala/research/servidor.py`: la cáscara mínima que le da al
motor la forma que el pack sabe levantar y que la Sala sabe pintar.

    --port <n>            el pack elige el puerto (`platform/workspaces/pack.py:474`)
    GET  /health          la señal de salud que el pack sondea (`pack.py:122-127`)
    POST /buscar          NDJSON: los estados en vivo, y al final la respuesta con fuentes
    POST /cancelar        la cancelación cooperativa

**La cara de Vane no se monta.** Este servidor habla con su `/api/chat` por loopback y
traduce; nadie navega a su puerto. La cara es la Sala.

POR QUÉ HACE FALTA, teniendo a Vane ahí al lado
------------------------------------------------
Porque el pack no puede hablar el dialecto de Vane. Tres razones medidas, no supuestas:

1. **`sources` no es opcional aunque el schema diga que sí.** Ver el bloque de abajo: es
   el defecto que se llevó una sesión entera.
2. **Los `providerId` son UUIDs que cambian.** Los acuña la costura en cada `enter`
   (`config.py:armar`, que preserva los previos); el llamante no puede hardcodearlos, y
   Vane rechaza con «Invalid provider id» cualquiera que no esté en SU config.
3. **El cable de Vane no es el de la casa.** Emite bloques + parches RFC-6902; la Sala
   habla NDJSON de sobres. `etapas.py` es la traducción y necesitaba quién la llamara.

⚠️⚠️ `sources: ["web"]` — LA LÍNEA QUE NO SE PUEDE BORRAR
-----------------------------------------------------------
`third_party/vane/src/app/api/chat/route.ts:40` declara

    sources: z.array(z.string()).optional().default([])

y `researcher/actions/search/webSearch.ts:84-86` habilita la acción de búsqueda **sólo**
si `config.sources.includes('web')`. Con el default vacío el investigador arma **cero
herramientas**, el modelo no tiene con qué buscar, y el turno **igual termina bien**: 200,
`messageEnd`, y una respuesta cortés explicando que los resultados vinieron vacíos.

**Sin error. Sin fuentes. Sin una sola señal de que faltó algo.** No es un rojo mudo: es
un VERDE mudo, que es peor. La vara `verify_busqueda_servidor.py` lo ataja con un caso
dedicado, y por eso `_SOURCES` es una constante y no un parámetro con default: un default
es exactamente lo que produjo el defecto.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

_AQUI = Path(__file__).resolve().parent
if str(_AQUI) not in sys.path:
    sys.path.insert(0, str(_AQUI))
if str(_AQUI.parents[1]) not in sys.path:
    sys.path.insert(0, str(_AQUI.parents[1]))

from local_pack_auth import guard_post  # noqa: E402

import etapas as _etapas          # noqa: E402

#: LO QUE HACE QUE BUSQUE. Ver el ⚠️⚠️ del docstring.
_SOURCES = ["web"]

#: El modo del motor. `speed` = 2 iteraciones (`researcher/index.ts:16-20`).
_MODO = "speed"

#: Copy de cada causa. Regla sellada: ninguna causa llega a una superficie sin copy.
_COPY = {
    "consulta_vacia": "Hace falta algo que buscar.",
    "motor_no_responde": "El buscador no contestó.",
    "motor_sin_config": "El buscador no recibió su configuración.",
    "motor_sin_modelo": "El buscador no tiene un cerebro configurado.",
    "motor_fallo": "La búsqueda falló.",
    "obra_cancelada": "Búsqueda cancelada.",
    "sin_fuentes": "La búsqueda no encontró fuentes.",
    "cuerpo_invalido": "La Sala mandó un pedido que no se entiende.",
    "ruta_desconocida": "Ese camino no existe en la búsqueda.",
}

_OBRAS: dict[str, dict] = {}
_LOCK = threading.Lock()


class _Cancelada(BaseException):
    """Hereda de `BaseException` por lo mismo que su gemela en `research/servidor.py`:
    el `except Exception` de `ThreadingMixIn.process_request_thread` NO debe atraparla."""


def _espacio_nuevo(obra_id: str) -> str:
    """Debe matchear `^[A-Za-z0-9._:-]{1,120}$` (`platform/artifacts/provenance.py:53`)."""
    return f"space-sala-busqueda-{obra_id}"


# ── el motor, del otro lado del loopback ──────────────────────────────────────
def _url_motor() -> str:
    u = os.environ.get("ALEPH_VANE_URL", "").strip()
    if not u:
        raise _MotorError("motor_sin_config", "falta ALEPH_VANE_URL")
    return u.rstrip("/")


class _MotorError(Exception):
    def __init__(self, causa: str, detalle: str = ""):
        self.causa, self.detalle = causa, detalle
        super().__init__(f"{causa}: {detalle}" if detalle else causa)


def _proveedores() -> tuple[dict, dict]:
    """Los dos proveedores que la costura escribió, leídos DEL MOTOR y no del archivo.

    Se preguntan por `/api/providers` en vez de parsear `data/config.json` a propósito:
    el que manda es el que el motor cargó. Si la costura escribió algo que el motor no
    aceptó, esto lo ve y el archivo no.
    """
    try:
        with urllib.request.urlopen(_url_motor() + "/api/providers", timeout=20) as r:
            provs = json.load(r).get("providers") or []
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise _MotorError("motor_no_responde", f"{type(e).__name__}") from None
    chat = emb = None
    for p in provs:
        if not chat and (p.get("chatModels") or []):
            chat = p
        if not emb and (p.get("embeddingModels") or []):
            emb = p
    if not chat or not emb:
        raise _MotorError("motor_sin_modelo",
                          f"chat={bool(chat)} embeddings={bool(emb)}")
    return chat, emb


def _cuerpo_chat(consulta: str, chat: dict, emb: dict, chat_id: str) -> dict:
    return {
        "message": {"chatId": chat_id, "messageId": uuid.uuid4().hex[:16],
                    "content": consulta},
        "optimizationMode": _MODO,
        # ⚠️ NO TOCAR sin leer el ⚠️⚠️ del docstring: sin esto la búsqueda no busca y
        # el turno sale VERDE igual.
        "sources": list(_SOURCES),
        "chatModel": {"providerId": chat["id"], "key": chat["chatModels"][0]["key"]},
        "embeddingModel": {"providerId": emb["id"],
                           "key": emb["embeddingModels"][0]["key"]},
    }


# ── el servidor ───────────────────────────────────────────────────────────────
class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, formato: str, *args: Any) -> None:      # noqa: A002
        if os.environ.get("ALEPH_BUSQUEDA_DEBUG"):
            super().log_message(formato, *args)

    def do_GET(self) -> None:                                     # noqa: N802
        if self.path.split("?")[0] == "/health":
            self._json(200, {"ok": True, "motor": "vane"})
            return
        self._json(404, {"error": "ruta_desconocida", "detail": self.path,
                         "copy": _COPY["ruta_desconocida"]})

    def do_POST(self) -> None:                                    # noqa: N802
        if not guard_post(self):
            return
        ruta = self.path.split("?")[0]
        try:
            cuerpo = self._leer_json()
            if cuerpo is None:
                return
            if ruta == "/buscar":
                self._buscar(cuerpo)
            elif ruta == "/cancelar":
                self._cancelar(cuerpo)
            else:
                self._json(404, {"error": "ruta_desconocida", "detail": ruta,
                                 "copy": _COPY["ruta_desconocida"]})
        except _Cancelada:
            return

    # ── la obra ───────────────────────────────────────────────────────────────
    def _buscar(self, cuerpo: dict) -> None:
        consulta = str(cuerpo.get("query") or cuerpo.get("consulta") or "").strip()
        if not consulta:
            self._json(400, {"error": "consulta_vacia", "copy": _COPY["consulta_vacia"]})
            return

        obra_id = uuid.uuid4().hex[:16]
        espacio = _espacio_nuevo(obra_id)
        with _LOCK:
            if _OBRAS:
                self._json(429, {"error": "capacidad_ocupada",
                                 "copy": "Ya hay una búsqueda activa. Espera o cancélala."})
                return
            _OBRAS[obra_id] = {"cancelar": False}

        t0 = time.time()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            self._linea({"tipo": "abre", "obra_id": obra_id, "espacio": espacio})
            chat, emb = _proveedores()
            traductor = _etapas.Traductor()
            for ev in self._cable(_cuerpo_chat(consulta, chat, emb, obra_id), obra_id):
                for sobre in traductor.consumir(ev):
                    self._linea({"tipo": "estado", **sobre})

            texto = traductor.texto
            fuentes = traductor.fuentes
            self._decir({
                "tipo": "respuesta",
                "texto": texto,
                "fuentes": fuentes,
                # El sha256 del texto, igual que el informe de Research: es lo que el
                # pasaporte del artefacto ancla.
                "sha256": hashlib.sha256(texto.encode("utf-8")).hexdigest(),
                # SIN FUENTES SE DICE, no se disimula. Una respuesta de búsqueda web sin
                # bibliografía es una señal, no un hueco que se rellena (mismo criterio
                # que el `never_filled` de `platform/artifacts/bridge.py`).
                **({} if fuentes else {"aviso": "sin_fuentes",
                                       "copy": _COPY["sin_fuentes"]}),
            })
        except _MotorError as e:
            self._decir({"tipo": "fallo", "causa": e.causa,
                         "copy": _COPY.get(e.causa, _COPY["motor_fallo"]),
                         "detalle": e.detalle})
        except _Cancelada:
            self._decir({"tipo": "fallo", "causa": "obra_cancelada",
                         "copy": _COPY["obra_cancelada"]})
        except Exception as e:                                     # noqa: BLE001
            self._decir({"tipo": "fallo", "causa": "motor_fallo",
                         "copy": _COPY["motor_fallo"],
                         "detalle": f"{type(e).__name__}: {e}"[:300]})
        finally:
            with _LOCK:
                _OBRAS.pop(obra_id, None)
            self._decir({"tipo": "cierra", "obra_id": obra_id,
                         "ms": int((time.time() - t0) * 1000)})
            self._fin_chunked()

    def _cable(self, cuerpo: dict, obra_id: str):
        """El NDJSON de Vane, línea por línea, mientras la obra siga viva."""
        pedido = urllib.request.Request(
            _url_motor() + "/api/chat",
            data=json.dumps(cuerpo, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        try:
            respuesta = urllib.request.urlopen(pedido, timeout=900)
        except urllib.error.HTTPError as e:
            raise _MotorError("motor_fallo", e.read()[:200].decode(errors="replace")) from None
        except (urllib.error.URLError, OSError) as e:
            raise _MotorError("motor_no_responde", type(e).__name__) from None
        with respuesta:
            for cruda in respuesta:
                with _LOCK:
                    if (_OBRAS.get(obra_id) or {}).get("cancelar"):
                        raise _Cancelada()
                linea = cruda.decode("utf-8", errors="replace").strip()
                if not linea:
                    continue
                try:
                    yield json.loads(linea)
                except ValueError:
                    continue          # una línea rota del motor no tumba el turno

    def _cancelar(self, cuerpo: dict) -> None:
        obra_id = str(cuerpo.get("obra_id") or "").strip()
        with _LOCK:
            viva = obra_id in _OBRAS
            if viva:
                _OBRAS[obra_id]["cancelar"] = True
        self._json(200, {"ok": True, "cancelada": viva})

    # ── plomería (gemela de research/servidor.py) ─────────────────────────────
    def _leer_json(self) -> Optional[dict]:
        try:
            n = int(self.headers.get("Content-Length") or 0)
            cuerpo = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, OSError):
            self._json(400, {"error": "cuerpo_invalido", "copy": _COPY["cuerpo_invalido"]})
            return None
        if not isinstance(cuerpo, dict):
            self._json(400, {"error": "cuerpo_invalido", "copy": _COPY["cuerpo_invalido"]})
            return None
        return cuerpo

    def _json(self, codigo: int, cuerpo: dict) -> None:
        crudo = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(crudo)))
        self.end_headers()
        self.wfile.write(crudo)

    def _linea(self, obj: dict) -> None:
        crudo = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            self.wfile.write(b"%x\r\n" % len(crudo))
            self.wfile.write(crudo)
            self.wfile.write(b"\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            raise _Cancelada() from None

    def _decir(self, obj: dict) -> None:
        """`_linea` para el desenlace: si el cable ya está roto, no es una causa."""
        try:
            self._linea(obj)
        except _Cancelada:
            pass
        except OSError:
            pass

    def _fin_chunked(self) -> None:
        try:
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--port", type=int, required=True)
    args = ap.parse_args(argv)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), _Handler)
    srv.daemon_threads = True
    print(f"Aleph Búsqueda: servidor en 127.0.0.1:{args.port} motor={os.environ.get('ALEPH_VANE_URL','?')}",
          flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
