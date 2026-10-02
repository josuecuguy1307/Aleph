"""Contrato único para resultados de tools: error, causa y mensaje al modelo.

Los transportes preservan el contrato histórico de devolver texto. Mientras ese
contrato exista, todo consumidor debe preguntar aquí; no mantener listas locales.
La costura tampoco inventa una taxonomía: lee el vocabulario sellado de F1.
"""

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


_ERROR_PREFIXES = ("[mcp error", "[tool error", "[error", "error:", "[err")
# [Gate 4 · F5 · 5.2 · D5] `usuario` ENTRA, y no es un cuarto sinónimo de los otros tres.
#
# Los tres originales dicen QUIÉN FALLÓ. Un turno que alguien PARÓ no falló: se cortó, y el
# que lo cortó fue una persona apretando un botón. Firmarlo `aleph` diría que lo cortó la
# casa —una falla nuestra que hay que reportar— y firmarlo `conector` o `modelo` sería
# culpar a un tercero de una decisión del dueño.
#
# Es exactamente la misma doctrina que `turnos_http` escribió para el chat y que esta obra
# extiende a las obras: **quién causó el corte es parte del corte** (`turnos_http.py:37`).
# Sin este origen, el registro de una obra cancelada sería indistinguible de una caída.
_ORIGENES = frozenset({"modelo", "conector", "aleph", "usuario"})
ORIGEN_USUARIO = "usuario"


def _causas_f1() -> frozenset[str]:
    """Lee el vocabulario existente de F1, incluso bajo el loader por ruta.

    El backend carga este archivo con ``load_module_by_path``, sin agregar
    ``platform/assembler`` a ``sys.path``. Por eso primero reutilizamos el
    módulo ya importable y, si hace falta, cargamos *ese mismo* archivo hermano:
    no existe una tercera lista local de causas.
    """
    try:
        from errores_modelo import CAUSAS  # type: ignore[import-not-found]
        return frozenset(CAUSAS)
    except ImportError:
        module_name = "puppet_causas_costura_f1"
        module = sys.modules.get(module_name)
        if module is None:
            spec = importlib.util.spec_from_file_location(
                module_name, Path(__file__).with_name("errores_modelo.py"))
            if spec is None or spec.loader is None:
                raise RuntimeError("no se pudo leer el vocabulario F1")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        return frozenset(module.CAUSAS)


_CAUSAS_EXISTENTES = _causas_f1()
SIN_RED = "sin_red"
TIMEOUT = "timeout"
ERROR_UPSTREAM = "error_upstream"
PROVEEDOR_CAIDO = "proveedor_caido"
FALLA_DE_ALEPH = "falla_de_aleph"
FALLO_DESCONOCIDO = "fallo_desconocido"
GATE_BLOQUEADO = "gate_bloqueado"
ARGUMENTOS_INVALIDOS = "argumentos_invalidos"


@dataclass(frozen=True)
class CausaCostura:
    """Firma inmutable del fallo que cruza modelo, Sala y trayectoria."""

    causa: str
    origen: str
    reintentable: bool
    timeout_s: Optional[float]
    vencio_el_reloj: Optional[bool]
    detalle: str

    def __post_init__(self) -> None:
        if self.causa not in _CAUSAS_EXISTENTES:
            raise ValueError(f"causa fuera del vocabulario existente: {self.causa!r}")
        if self.origen not in _ORIGENES:
            raise ValueError(f"origen de costura inválido: {self.origen!r}")
        if not isinstance(self.reintentable, bool):
            raise ValueError("reintentable debe ser bool")
        if self.timeout_s is not None and (
                isinstance(self.timeout_s, bool) or not isinstance(self.timeout_s, (int, float))
                or self.timeout_s <= 0):
            raise ValueError("timeout_s debe ser positivo o None")
        if self.vencio_el_reloj is not None and not isinstance(self.vencio_el_reloj, bool):
            raise ValueError("vencio_el_reloj debe ser bool o None")
        if not isinstance(self.detalle, str):
            raise ValueError("detalle debe ser texto")

    def como_dict(self) -> dict:
        """Forma plana y serializable para record, evento y trayectoria."""
        out = {
            "causa": self.causa,
            "origen": self.origen,
            "reintentable": self.reintentable,
            "detalle": self.detalle,
        }
        if self.timeout_s is not None:
            out["timeout_s"] = float(self.timeout_s)
        if self.vencio_el_reloj is not None:
            out["vencio_el_reloj"] = self.vencio_el_reloj
        return out


def es_error_de_tool(texto: Any) -> bool:
    """True sólo para los prefijos de error que produce el runtime de tools."""
    return isinstance(texto, str) and texto.lstrip().lower().startswith(_ERROR_PREFIXES)


def texto_error_de_arguments(tool_name: str, detail: str) -> str:
    """Único texto D5 para arguments rechazados antes de ejecutar una tool."""
    return (f"[error: arguments inválidos para tool '{tool_name}': {detail}. "
            "La tool NO se ejecutó; reintenta la llamada con arguments JSON válidos.]")


def _texto_para_clasificar(value: Any) -> str:
    """Normaliza sólo para decidir; nunca copia la entrada cruda a ``detalle``."""
    try:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace").lower()
        if isinstance(value, str):
            return value.lower()
    except Exception:  # noqa: BLE001 - el clasificador debe ser total
        pass
    return ""


def _dict_seguro(value: Any) -> dict:
    try:
        return dict(value) if isinstance(value, dict) else {}
    except Exception:  # noqa: BLE001 - diagnóstico ajeno nunca rompe el loop
        return {}


def _origen_de_diagnostico(diagnostico: dict, *, defecto: str) -> str:
    """Cierra valores viejos al enum de costura al LEERLOS, no al emitirlos."""
    try:
        valor = str(diagnostico.get("origen") or "").strip().lower()
    except Exception:  # noqa: BLE001
        valor = ""
    return {
        "cli": "modelo",
        "runtime": "modelo",
        "modelo": "modelo",
        "aleph": "aleph",
        "conector": "conector",
        "connector": "conector",
    }.get(valor, defecto)


def _timeout_medido(diagnostico: dict) -> tuple[Optional[float], Optional[bool]]:
    """Propaga el último timeout que el SDK midió; no deduce relojes del string."""
    try:
        timeouts = diagnostico.get("timeouts")
        if not isinstance(timeouts, list):
            return None, None
        for item in reversed(timeouts):
            if not isinstance(item, dict) or item.get("vencio_el_reloj") is not True:
                continue
            value = item.get("timeout_s")
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                continue
            return float(value), True
    except Exception:  # noqa: BLE001
        pass
    return None, None


def _diagnostico_indica_sin_red(diagnostico: dict) -> bool:
    """Respeta evidencia de red explícita antes de llamar al server «caído»."""
    try:
        if diagnostico.get("causa") == SIN_RED or diagnostico.get("sin_red") is True:
            return True
        red = diagnostico.get("red")
        if isinstance(red, dict) and red.get("disponible") is False:
            return True
        return diagnostico.get("red_ok") is False
    except Exception:  # noqa: BLE001
        return False


def _causa(causa: str, origen: str, reintentable: bool, detalle: str,
           *, timeout_s: Optional[float] = None,
           vencio_el_reloj: Optional[bool] = None) -> CausaCostura:
    return CausaCostura(causa, origen, reintentable, timeout_s, vencio_el_reloj, detalle)


def clasificar_error_de_tool(resultado: Any, diagnostico: Any = None, *,
                             stop_reason: Any = None) -> CausaCostura:
    """Clasificador total de la costura para todo resultado que no fue éxito.

    ``detalle`` es siempre una plantilla propia: ni el texto crudo de tool ni el
    diagnóstico (que podrían contener credenciales) cruzan esta frontera.
    """
    try:
        texto = _texto_para_clasificar(resultado)
        diag = _dict_seguro(diagnostico)
        if stop_reason == "deadline":
            return _causa(TIMEOUT, "aleph", True,
                          "El turno agotó su deadline antes de iniciar otra tool.",
                          vencio_el_reloj=True)
        if "arguments inválidos" in texto or "arguments invalidos" in texto:
            return _causa(ARGUMENTOS_INVALIDOS, "modelo", True,
                          "Los arguments de la llamada no pasaron la validación.")
        if "no está cableado" in texto or "no esta cableado" in texto:
            return _causa(FALLA_DE_ALEPH, "aleph", False,
                          "La tool pedida no está cableada en esta receta.")
        if texto.startswith("[gate:"):
            return _causa(GATE_BLOQUEADO, "aleph", False,
                          "El gate no autorizó ejecutar la tool.")
        if texto.lstrip().startswith("[mcp error"):
            timeout_s, vencio = _timeout_medido(diag)
            if vencio is True:
                return _causa(TIMEOUT, "conector", True,
                              "El servidor MCP agotó el reloj de la llamada.",
                              timeout_s=timeout_s, vencio_el_reloj=True)
            if _diagnostico_indica_sin_red(diag):
                return _causa(SIN_RED, "conector", True,
                              "No hubo red disponible para llegar al servidor MCP.")
            return _causa(PROVEEDOR_CAIDO, "conector", True,
                          "El servidor MCP no respondió a la llamada.")
        return _causa(FALLO_DESCONOCIDO,
                      _origen_de_diagnostico(diag, defecto="conector"), False,
                      "La tool devolvió un error que la costura no pudo clasificar.")
    except Exception:  # noqa: BLE001 - propiedad D2: toda entrada devuelve una causa válida
        return _causa(FALLO_DESCONOCIDO, "aleph", False,
                      "La costura no pudo clasificar el resultado de la tool.")


def sufijo_de_causa(causa: CausaCostura) -> str:
    """Contrato corto y estable que el modelo puede leer sin parsear texto humano."""
    return (f"[causa={causa.causa} origen={causa.origen} "
            f"reintentable={'si' if causa.reintentable else 'no'}]")


def resultado_de_error_para_modelo(texto: str, causa: CausaCostura) -> str:
    """Conserva el texto humano y le agrega una única firma máquina-legible."""
    return f"{texto}\n{sufijo_de_causa(causa)}"
