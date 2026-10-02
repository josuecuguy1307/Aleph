#!/usr/bin/env python3
"""veredicto.py — UNA VARA QUE SALTEA SU OBJETO NO DICE «TODO VERDE».

══ [H4a · 2026-08-08] EL VERDE MENTIROSO, MEDIDO ══════════════════════════════════════
`verify_f4a.py` bajo el python del sistema cierra así:

    TODO VERDE  ·  3 salteado(s)

y los tres salteos son `litellm`: **la vía de producción**, el objeto entero de su obra 3.
La vara no midió el adaptador y dijo TODO VERDE igual. Peor: tres varas
(`verify_adaptador_litellm:489`, `verify_cli_slots:420`, `verify_cli_usage:389`) validan a
una hija con `ok("TODO VERDE" in r.stdout, …)`, así que el verde barato se propaga hacia
arriba sin que nadie lo vea.

  ══ LA REGLA ════════════════════════════════════════════════════════════════════════
  Hay salteos legítimos —una máquina sin el binario `claude` no puede probar el CLI, y
  eso no es un fallo de nadie— y hay salteos que se comen el objeto de la vara. La
  diferencia no la puede adivinar un contador: **la declara quien escribe el salteo**.

    · `saltear(...)`                → el veredicto lo dice, pero sigue siendo verde.
      Nunca más el string pelado `TODO VERDE`: `TODO VERDE (con N salteo(s) declarado(s))`.
      Así un `tail -1` no puede leer un verde limpio donde no lo hubo.

    · `saltear(..., critico=True)`  → `VERDE PARCIAL` y **exit 1**.
      Falla a propósito. Bajo el venv de producción `litellm` está instalado y no se
      saltea nada; si se saltea, es que se corrió con el intérprete equivocado, y eso es
      exactamente lo que hay que enterarse — no algo que perdonar.

Ley de la casa que esto aplica: «cuando un fixture simplifica el mundo, simplifica el bug
afuera». Un salteo es la forma más barata de simplificar el mundo.

USO — reemplaza el `print` + `sys.exit` del final:

    import veredicto
    raise SystemExit(veredicto.cerrar(_fallos, _salteados, _criticos))
"""
from __future__ import annotations

__all__ = ["texto", "cerrar", "es_verde_limpio"]


def texto(fallos: int, salteados: int = 0, criticos: int = 0) -> str:
    """La ÚLTIMA línea de la vara. Nunca miente por omisión."""
    if fallos:
        return f"{fallos} FALLO(S)" + (f"  ·  {salteados} salteado(s)" if salteados else "")
    if criticos:
        return (f"VERDE PARCIAL  ·  {criticos} salteo(s) DE SU OBJETO"
                + (f" de {salteados} salteado(s)" if salteados > criticos else "")
                + "  —  no se midió lo que esta vara existe para medir")
    if salteados:
        return f"TODO VERDE (con {salteados} salteo(s) declarado(s))"
    return "TODO VERDE"


def es_verde_limpio(salida: str) -> bool:
    """Para el padre que valida a una hija por su stdout: verde SIN salteos.

    `"TODO VERDE" in salida` daba True también con `TODO VERDE (con 3 salteo(s)…)`, que es
    justamente el caso que hay que atrapar. Acá se pide la línea entera.
    """
    return any(l.strip() == "TODO VERDE" for l in salida.splitlines())


def cerrar(fallos: int, salteados: int = 0, criticos: int = 0) -> int:
    """Imprime el veredicto y devuelve el exit code. Un salteo crítico SALE EN ROJO."""
    print(f"\n{texto(fallos, salteados, criticos)}")
    return 1 if (fallos or criticos) else 0
