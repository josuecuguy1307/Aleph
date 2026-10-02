"""ndjson_http.py — LA PLOMERÍA DE LOS MOTORES DE LA SALA, EXTRAÍDA.
[Gate 4 · Fase 6 · §6.a · el gatillo de 6.b: «si aparece la tercera copia, extraelo»]

POR QUÉ EXISTE, MEDIDO Y NO SUPUESTO
------------------------------------
Hay DOS motores locales que hablan el mismo dialecto con la Sala —búsqueda y research— y
los dos traen la misma plomería: leer un JSON del pedido, contestar un JSON, empujar líneas
NDJSON por un cuerpo `chunked`, y distinguir «el cable se cortó» de «hubo un error». El
propio código lo sabía: `platform/sala/busqueda/servidor.py:277` rotula ese bloque
**«plomería (gemela de research/servidor.py)»**.

browser use sería la TERCERA copia. Y antes de escribirla se midió la segunda:

    plomería de búsqueda   41 líneas de código
    plomería de research   54 líneas de código
    **23 líneas distintas** (diff sin comentarios, 2026-08-18)

**Las gemelas ya divergieron**, y la divergencia no es cosmética:

  · `research` maneja el cuerpo vacío (`return {}`) y atrapa `UnicodeDecodeError`.
    `busqueda` no: un POST sin cuerpo entra a `json.loads(b"{}")` por el `or`, y un byte
    inválido cae por `ValueError` sin decir que fue de encoding. **research está mejor.**
  · `busqueda` contesta `{"error": …, "copy": _COPY[…]}`. **`research` contesta
    `{"error": …, "detail": …}` SIN `copy`** (`research/servidor.py:237,240`) — aunque su
    propio `_COPY` declara la clave en `:78` y nunca la usa. Eso es una causa llegando a una
    superficie sin copy, que es una regla SELLADA de esta casa. **busqueda está mejor.**

O sea: cada copia arregló la mitad que la otra no, y ninguna de las dos tiene las dos
mitades. Ése es exactamente el costo de la segunda copia, cobrado. Este módulo es la unión.

⚠️ LOS DOS ORIGINALES TODAVÍA NO LO USAN, y es a propósito: `platform/sala/` está tomado
por la sesión de Deep Research (§6.f, sin mergear). Adoptarlo es **un import por archivo** y
queda declarado como deuda con el diff medido arriba. Lo que este módulo evita HOY es que la
tercera copia nazca.

QUÉ NO HACE: no conoce búsqueda, ni research, ni el navegador. No abre red de salida, no lee
config, no sabe qué es una obra. Recibe un handler de `http.server` y le presta cuatro
métodos. Sólo stdlib.
"""
from __future__ import annotations

import json
from typing import Any, Optional


class Cancelada(BaseException):
    """El cable se cortó o el usuario paró la obra.

    Hereda de `BaseException` A PROPÓSITO y las dos gemelas ya lo hacían por la misma razón,
    escrita en las dos: el `except Exception` de `ThreadingMixIn.process_request_thread`
    **no debe atraparla** — si la atrapa, el motor sigue trabajando para nadie."""


class PlomeriaNDJSON:
    """Mixin para un `BaseHTTPRequestHandler`. Los nombres son los de las dos gemelas, así
    que adoptarlo en ellas es agregar la clase a las bases y borrar los métodos."""

    #: `causa -> copy`. Lo pisa cada motor con el suyo. La clase base trae la única causa
    #: que la plomería puede producir sola, porque **ninguna causa llega a una superficie
    #: sin copy** — y la copia de research la declaraba y no la usaba.
    COPY: dict = {"cuerpo_invalido": "La Sala mandó un pedido que no se entiende."}

    # ── entrada ───────────────────────────────────────────────────────────────────────
    def _leer_json(self) -> Optional[dict]:
        """El cuerpo del pedido. `{}` si vino vacío, `None` si ya se contestó el 400.

        LA UNIÓN DE LAS DOS: el cuerpo vacío y `UnicodeDecodeError` vienen de research;
        `copy` viene de búsqueda. Y va `copy` **y** `detail`: el primero es para el usuario
        y el segundo para quien depura — tenerlos separados es lo que permite que el copy
        no mute cuando cambia el error."""
        try:
            n = int(self.headers.get("Content-Length") or 0)          # type: ignore[attr-defined]
        except ValueError:
            n = 0
        crudo = self.rfile.read(n) if n > 0 else b""                  # type: ignore[attr-defined]
        if not crudo:
            return {}
        try:
            cuerpo = json.loads(crudo.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as e:
            self._mal_cuerpo(str(e))
            return None
        if not isinstance(cuerpo, dict):
            self._mal_cuerpo("se esperaba un objeto")
            return None
        return cuerpo

    def _mal_cuerpo(self, detalle: str) -> None:
        self._json(400, {"error": "cuerpo_invalido",
                         "copy": self.COPY.get("cuerpo_invalido",
                                               PlomeriaNDJSON.COPY["cuerpo_invalido"]),
                         "detail": detalle})

    # ── salida ────────────────────────────────────────────────────────────────────────
    def _json(self, codigo: int, cuerpo: dict) -> None:
        crudo = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)                                    # type: ignore[attr-defined]
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(crudo)))
        self.end_headers()
        self.wfile.write(crudo)                                       # type: ignore[attr-defined]

    def _linea(self, obj: dict) -> None:
        """Una línea NDJSON, en un chunk propio, empujada al cable.

        DURANTE el turno se usa ésta, y **debe** levantar `Cancelada`: un cable roto es la
        señal de que el usuario se fue y hay que parar el motor — no seguir gastando."""
        crudo = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            self.wfile.write(b"%x\r\n" % len(crudo))                  # type: ignore[attr-defined]
            self.wfile.write(crudo)
            self.wfile.write(b"\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            raise Cancelada() from None

    def _decir(self, obj: dict) -> None:
        """`_linea` para el DESENLACE (informe · fallo · cierra). Si el cable ya está roto,
        no es una causa: levantar acá taparía la causa real o dejaría el terminador chunked
        sin escribir."""
        try:
            self._linea(obj)
        except Cancelada:
            pass

    def _fin_chunked(self) -> None:
        try:
            self.wfile.write(b"0\r\n\r\n")                            # type: ignore[attr-defined]
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, formato: str, *args: Any) -> None:          # noqa: A002, N802
        """Silencio: el log del motor es el NDJSON, no el access log de `http.server`."""


__all__ = ["PlomeriaNDJSON", "Cancelada"]
