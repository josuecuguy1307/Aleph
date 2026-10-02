#!/usr/bin/env python3
"""
Wrapper MCP mínimo para verificación y conversión de unidades físicas.
Usa Pint (https://pint.readthedocs.io/) como motor dimensional.

Dos tools expuestas al agente tutor STEM-ES:
  - units_convert : convierte una cantidad numérica a otra unidad
  - units_check   : verifica si una expresión dimensional es coherente;
                    rechaza sumas de dimensiones incompatibles lanzando
                    DimensionalityError (isError=true en JSON-RPC)

Seguridad: NO se usa eval() de Python crudo. Todo parsing pasa por
pint.UnitRegistry().parse_expression(), que solo entiende cantidades
físicas, no ejecuta código arbitrario.
"""

from mcp.server.fastmcp import FastMCP
import pint

# ── registro de unidades Pint (singleton por proceso) ────────────────────────
ureg = pint.UnitRegistry()

# ── servidor MCP stdio ────────────────────────────────────────────────────────
mcp = FastMCP(
    name="units-pint",
    instructions="Verificación y conversión de unidades físicas con Pint (tutor STEM-ES v0)",
)


# ── tool 1: conversión de unidades ───────────────────────────────────────────
@mcp.tool()
def units_convert(value: float, from_unit: str, to_unit: str) -> str:
    """
    Convierte una cantidad numérica de una unidad a otra.

    Parámetros:
        value     : valor numérico (e.g. 60)
        from_unit : unidad de origen en notación Pint (e.g. "km/hour")
        to_unit   : unidad destino en notación Pint (e.g. "m/s")

    Devuelve: string con valor convertido y unidad destino.
    Lanza DimensionalityError si las unidades son incompatibles.

    Ejemplos:
        units_convert(60, "km/hour", "m/s")  -> "16.666667 meter / second"
        units_convert(1,  "kg",      "g")    -> "1000.0 gram"
    """
    # Construir Quantity con Pint (no eval crudo).
    # Lanzar excepciones directamente para que FastMCP devuelva isError=true.
    cantidad = ureg.Quantity(value, from_unit)
    convertida = cantidad.to(to_unit)
    # Redondear para presentación limpia (6 cifras significativas)
    valor_redondeado = round(convertida.magnitude, 6)
    return f"{valor_redondeado} {convertida.units}"


# ── tool 2: verificación dimensional de expresiones ──────────────────────────
@mcp.tool()
def units_check(expression: str) -> str:
    """
    Evalúa una expresión de unidades físicas y verifica su coherencia dimensional.

    Acepta: cantidades simples ("60 km/hour") o sumas/restas
    ("5 m/s + 3 m/s" es válida; "5 m/s + 3 kg" NO lo es).

    Parámetros:
        expression : string de la expresión a evaluar (e.g. "5 m/s + 3 kg")

    Devuelve:
        - Si es dimensionalmente coherente: resultado con unidades como string
        - Si NO lo es: lanza DimensionalityError -> FastMCP devuelve isError=true

    Adversarial central del wedge:
        units_check("5 m/s + 3 kg")
        -> isError=true, "Cannot convert from 'meter / second' ([length]/[time])
                          to 'kilogram' ([mass])"

    Seguridad: parsing exclusivamente via pint.UnitRegistry().parse_expression().
    No se usa eval() de Python ni builtins.
    """
    # Las excepciones de Pint (DimensionalityError, UndefinedUnitError) se
    # propagan sin capturar para que FastMCP las convierta en isError=true.
    resultado = _evaluar_expresion(expression)
    return f"{resultado}"


def _evaluar_expresion(expr_str: str):
    """
    Evalúa una expresión de cantidades Pint con soporte para suma y resta.

    Soporta:
        "60 km/hour"
        "5 m/s + 3 m/s"
        "5 m/s + 3 kg"   <- lanza DimensionalityError (comportamiento deseado)

    Estrategia: tokenizar por '+'/'-' de nivel superior (ignora '**'),
    parsear cada término con Pint, luego operar. Pint valida dimensiones
    al sumar/restar y lanza DimensionalityError si son incompatibles.
    """
    expr_str = expr_str.strip()
    terminos = _tokenizar_suma_resta(expr_str)

    if not terminos:
        raise ValueError(f"Expresión vacía o no parseable: {expr_str!r}")

    # Parsear y operar término a término
    signo0, tok0 = terminos[0]
    resultado = ureg.parse_expression(tok0.strip())
    if signo0 == "-":
        resultado = -resultado

    for signo, token in terminos[1:]:
        cantidad = ureg.parse_expression(token.strip())
        if signo == "+":
            resultado = resultado + cantidad   # DimensionalityError si dimensiones distintas
        else:
            resultado = resultado - cantidad

    return resultado


def _tokenizar_suma_resta(expr: str):
    """
    Divide la expresión en lista de (signo, token_str) para '+' y '-' de
    nivel superior. Ignora '**' (exponentes) para no confundirlos con operadores.

    Devuelve: [("+", "5 m/s"), ("+", "3 kg"), ...]
    El primer término siempre tiene signo "+".
    """
    result = []
    current = ""
    i = 0
    signo_actual = "+"

    # Signo explícito al inicio
    if expr and expr[0] in ("+", "-"):
        signo_actual = expr[0]
        i = 1

    while i < len(expr):
        ch = expr[i]
        # Saltar '**' completo para no confundirlo con operadores
        if ch == "*" and i + 1 < len(expr) and expr[i + 1] == "*":
            current += "**"
            i += 2
            continue
        # '+' o '-' como operador de nivel superior
        if ch in ("+", "-"):
            token = current.strip()
            if token:
                result.append((signo_actual, token))
            current = ""
            signo_actual = ch
            i += 1
            continue
        current += ch
        i += 1

    # Último token
    token = current.strip()
    if token:
        result.append((signo_actual, token))

    return result


# ── arranque del server en modo stdio ─────────────────────────────────────────
if __name__ == "__main__":
    mcp.run(transport="stdio")
