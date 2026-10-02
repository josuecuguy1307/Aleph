#!/usr/bin/env python3
"""verify_exclusividad_terna — [LEY 12] el stack que se ajusta solo, ¿queda con NUESTRO cerebro?

QUÉ MIDE
---------
Finanzas no declara una LISTA de proveedores como los dos motores opencode: declara UNA
configuración de LLM, y su pantalla de ajustes la reescribe entera (`PUT /settings/llm`).
Ahí «otro cerebro» no aparece como un proveedor de más — son los MISMOS tres campos
apuntando a otro lado:

    provider · model_name · base_url

⚠️ LA TERNA COMPLETA, Y ESTO ESTÁ MEDIDO: el desvío mantuvo `provider = openai` y cambió
`model_name` y `base_url`. Una verificación que compare sólo el id del proveedor da verde
con el turno saliendo por la puerta de al lado. El caso 6 de esta vara es exactamente ése.

LAS DOS SITUACIONES, QUE NO SE REPARAN IGUAL
---------------------------------------------
· proceso NUEVO — nació leyendo el `.env` que el pack acaba de escribir: reparado por
  construcción. No hay nada que arreglar, sí hay algo que ANUNCIAR.
· proceso VIVO — no relee el archivo. `PUT /settings/llm` escribe el `.env` *y* muta el
  `os.environ` del proceso y le tira el cache (`reset_env_config`). Reescribir el archivo
  no lo mueve: la única reparación efectiva es el PUT del propio motor.

Y NO SE LE CREE AL 200 (caso 5): un motor que contesta 200 y no cambia nada tiene que salir
`sin_reparar`, no verde. Es la lección que Oficina pagó con `disabled-providers`.

Esta vara no necesita la `.app`: levanta un stack de mentira que habla ese contrato.

Uso:  python3 qa/verify_exclusividad_terna.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]
_TMP = tempfile.mkdtemp(prefix="vara-terna-")
os.environ["ALEPH_DATA_DIR"] = _TMP                       # antes de importar el pack
sys.path.insert(0, str(_RAIZ / "platform"))

from workspaces import pack                                # noqa: E402

_FALLOS: list[str] = []
BASE_ALEPH = "http://127.0.0.1:8330"
META = {"config_file": ".env", "brain_path": "/v1/workspaces/brain/openai",
        "cerebro_label": "Cerebro de Aleph", "brain_exclusivo": True,
        "brain_lectura": "settings_llm"}
NUESTRA = pack.terna_esperada(META, BASE_ALEPH)
AJENA = {"provider": "openai",                             # ← el id NO cambia. Ésa es la trampa
         "model_name": "gpt-5.3-chat-latest",
         "base_url": "https://api.openai.com/v1"}


def check(titulo: str, ok: bool, evidencia: str = "") -> None:
    print("   %s %-56s %s" % ("✅" if ok else "❌", titulo, evidencia))
    if not ok:
        _FALLOS.append(titulo)


class _StackDeMentira:
    """Habla `GET/PUT /settings/llm`. `sordo=True` contesta 200 y no cambia nada."""

    def __init__(self, terna: dict, sordo: bool = False):
        self.estado = dict(terna, temperature=0.0, timeout_seconds=120,
                           max_retries=2, reasoning_effort="")
        self.sordo = sordo
        self.puts: list[dict] = []
        vara = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *_a):                    # sin ruido en la vara
                pass

            def _responder(self):
                cuerpo = json.dumps(vara.estado).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(cuerpo)))
                self.end_headers()
                self.wfile.write(cuerpo)

            def do_GET(self):
                self._responder()

            def do_PUT(self):
                n = int(self.headers.get("Content-Length", 0))
                pedido = json.loads(self.rfile.read(n).decode() or "{}")
                vara.puts.append(pedido)
                if not vara.sordo:
                    vara.estado.update({k: pedido[k] for k in
                                        ("provider", "model_name", "base_url")
                                        if k in pedido})
                self._responder()

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return "http://127.0.0.1:%d" % self.srv.server_address[1]

    def cerrar(self):
        self.srv.shutdown()


def _escribir_env(ws: str, terna: dict) -> None:
    (pack._sub(ws, "data") / ".env").write_text(
        "LANGCHAIN_PROVIDER=%s\nLANGCHAIN_MODEL_NAME=%s\nOPENAI_BASE_URL=%s\n"
        % (terna["provider"], terna["model_name"], terna["base_url"]), encoding="utf-8")


def main() -> int:
    print("verify_exclusividad_terna · ¿el cerebro del stack sigue siendo el nuestro?\n")

    print("── A · leer la terna previa ANTES de pisarla ──")
    _escribir_env("w1", AJENA)
    leida = pack.terna_en_disco("w1", META)
    check("1 · el `.env` previo se lee entero (los tres campos)",
          leida == AJENA, str(leida))
    check("2 · sin `.env` no se inventa nada",
          pack.terna_en_disco("w_sin_env", META) is None)

    print("\n── B · la terna nuestra: nada que anunciar ──")
    s = _StackDeMentira(NUESTRA)
    parte = pack.exclusividad_por_terna("w2", META, url=s.url, base_aleph=BASE_ALEPH,
                                        previa=dict(NUESTRA), proceso_vivo=True)
    s.cerrar()
    check("3 · terna igual → ni desvío ni aviso",
          parte["desviada"] is False and not parte["reparada"], str(parte["desviada"]))

    print("\n── C · proceso NUEVO con desvío: reparado al nacer, y se dice ──")
    parte = pack.exclusividad_por_terna("w3", META, url="http://127.0.0.1:1",
                                        base_aleph=BASE_ALEPH, previa=dict(AJENA),
                                        proceso_vivo=False)
    check("4 · desvío detectado y reparado por la config al nacer",
          parte["desviada"] and parte["reparada"] and parte["como"] == "config_al_nacer",
          parte.get("como", ""))

    print("\n── D · proceso VIVO con desvío: PUT del propio motor, y relectura ──")
    s = _StackDeMentira(AJENA)
    parte = pack.exclusividad_por_terna("w4", META, url=s.url, base_aleph=BASE_ALEPH,
                                        previa=dict(AJENA), proceso_vivo=True)
    puts = list(s.puts)
    s.cerrar()
    check("5 · se reparó con `PUT /settings/llm` y la relectura lo confirma",
          parte["reparada"] and parte["como"] == "put_settings_llm",
          "put=%s despues=%s" % (parte.get("put_estado"), parte.get("despues")))
    check("6 · el PUT llevó la TERNA COMPLETA, no sólo el proveedor",
          len(puts) == 1 and all(puts[0].get(k) == NUESTRA[k] for k in NUESTRA),
          str({k: puts[0].get(k) for k in NUESTRA} if puts else {}))
    check("7 · y conservó los ajustes de generación del usuario (no son el cerebro)",
          bool(puts) and puts[0].get("timeout_seconds") == 120
          and puts[0].get("max_retries") == 2,
          str({k: puts[0].get(k) for k in ("temperature", "timeout_seconds",
                                           "max_retries")} if puts else {}))

    print("\n── E · el brazo que hace que esta vara pueda dar ROJO ──")
    s = _StackDeMentira(AJENA, sordo=True)                  # contesta 200 y no cambia nada
    parte = pack.exclusividad_por_terna("w5", META, url=s.url, base_aleph=BASE_ALEPH,
                                        previa=dict(AJENA), proceso_vivo=True)
    s.cerrar()
    check("8 · un 200 que no cambió nada sale SIN REPARAR, no verde",
          parte["sin_reparar"] and not parte["reparada"],
          "put=%s despues=%s" % (parte.get("put_estado"), parte.get("despues")))

    print("\n── F · el desvío que NO cambia el proveedor (el que se midió) ──")
    solo_modelo = dict(NUESTRA, model_name="gpt-5.3-chat-latest")
    s = _StackDeMentira(solo_modelo)
    parte = pack.exclusividad_por_terna("w6", META, url=s.url, base_aleph=BASE_ALEPH,
                                        previa=solo_modelo, proceso_vivo=True)
    s.cerrar()
    check("9 · `provider` idéntico y `model_name` distinto ⇒ DESVIADA",
          parte["desviada"] and parte["reparada"],
          "previa=%s" % solo_modelo["model_name"])

    print("\n══ VEREDICTO ══")
    if _FALLOS:
        for f in _FALLOS:
            print("  ❌ %s" % f)
        return 1
    print("  ✅ la terna se lee antes de pisarla, se repara donde corresponde, y el 200")
    print("     no cuenta como reparación.")
    print("  ⏳ LO QUE ESTA VARA NO MIDE: el stack REAL. El contrato está copiado de")
    print("     `settings_routes.py` (GET/PUT `/settings/llm`), pero quien contesta acá es")
    print("     un doble. Contra la `.app` se mide en la tanda siguiente.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
