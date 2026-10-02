"""
mesa/proyeccion.py — la PROYECCIÓN evento→estación (función PURA).

Las 6 estaciones NO son un pipeline nuevo: son una vista sobre el MISMO stream de eventos
que el Motor B ya emite. Este módulo es el único lugar donde vive el mapeo, y se espeja
byte-por-byte en el front (mesa.state.js). Nada del wire se renombra acá — solo se clasifica.

    Encontrarlo → Entrar → Ver qué sabe hacer → Armar las herramientas → Probarlas → Equipar

Regla de oro: la estación NUNCA retrocede dentro de un intento (el stream avanza). Un `error`
no cambia de estación: se adhiere a la estación activa (ahí ocurrió la duda). Los eventos meta
de la Mesa (construccion.*, pregunta.*) no proyectan estación salvo `estacion.cambio`, que ES
la señal de transición que el runner emite.
"""
from __future__ import annotations

from typing import Optional

# Orden canónico. El índice (1..6) es parte del contrato (el riel lo usa para ordenar).
ESTACIONES: tuple[str, ...] = (
    "encontrarlo",
    "entrar",
    "ver",
    "armar",
    "probar",
    "equipar",
)

# Etiqueta humana ES (el front la traduce; esto es el fallback/servidor).
ETIQUETA_ES: dict[str, str] = {
    "encontrarlo": "Encontrarlo",
    "entrar": "Entrar",
    "ver": "Ver qué sabe hacer",
    "armar": "Armar las herramientas",
    "probar": "Probarlas",
    "equipar": "Equipar",
}

# Ícono del SET PROPIO (Lucide vendored, mismo estilo que cuarto.icons.js). CERO emoji de OS.
ICONO: dict[str, str] = {
    "encontrarlo": "search",
    "entrar": "key-round",
    "ver": "eye",
    "armar": "wrench",
    "probar": "flask-conical",
    "equipar": "plug",
}

# Evento (nombre EXACTO del contrato SSE) → estación que alimenta. Los que faltan no proyectan.
_EVENTO_ESTACION: dict[str, str] = {
    # 1 · Encontrarlo (resolver §0.5)
    "dispatch.iniciado": "encontrarlo",
    "resolver.buscando": "encontrarlo",
    "resolver.encontrado": "encontrarlo",
    "resolver.miss": "encontrarlo",
    # 2 · Entrar (Capa 1 · sesión, las 4 formas)
    "dispatch.forjando": "entrar",
    "forge.iniciado": "entrar",
    "sesion.ok": "entrar",
    "browser.session.iniciado": "entrar",
    "browser.fase": "entrar",
    "sesion.capturada": "entrar",
    # 3 · Ver qué sabe hacer (Capa 2 · observar)
    "observando": "ver",
    # 4 · Armar las herramientas (Capa 3 · sintetizar)
    "sintetizando": "armar",
    "tool.propuesta": "armar",
    # 5 · Probarlas (Capa 4 · el candado)
    "tool.validando": "probar",
    "tool.validada": "probar",
    "tool.descartada": "probar",
    # 6 · Equipar (Capa 5 · emitir + registrar)
    "mcp.forjado": "equipar",
    "mcp.equipado": "equipar",
    "cerrado": "equipar",
}


def indice(estacion: str) -> int:
    """1-based; 0 si desconocida."""
    try:
        return ESTACIONES.index(estacion) + 1
    except ValueError:
        return 0


def estacion_de(evento_tipo: str) -> Optional[str]:
    """La estación que un tipo de evento alimenta, o None si el evento no proyecta."""
    return _EVENTO_ESTACION.get(evento_tipo)


def avanzar(actual: Optional[str], evento_tipo: str) -> Optional[str]:
    """Dado el evento, devuelve la estación resultante SIN retroceder.

    `error` y los eventos meta no cambian de estación (devuelven `actual`). Una estación
    de índice menor que la actual tampoco retrocede (defensivo contra re-emisiones)."""
    destino = estacion_de(evento_tipo)
    if destino is None:
        return actual
    if actual is None:
        return destino
    return destino if indice(destino) >= indice(actual) else actual


__all__ = ["ESTACIONES", "ETIQUETA_ES", "ICONO", "indice", "estacion_de", "avanzar"]
