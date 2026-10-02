"""modelos_checklist.py — EL CHECKLIST VIVO DE MODELOS. (Gate 2 · F4c · obra 4)

Los verbos completándose uno por uno mientras se prueba un modelo, en vez de un spinner
mudo. Gemelo del `POST /v1/conexiones/checklist` de Gate 1: **mismos nombres de evento,
mismo orden, misma forma** — para que la superficie pueda reusar el cliente SSE que ya
existe (`conectores/fuentes.js::checklistEnVivo`) en vez de tener un segundo dialecto.

    fila.inicio        → los verbos que se VAN a correr, ANTES de correr ninguno
    requisito.probando → cuál está corriendo ahora
    requisito.resultado→ su veredicto, con causa TIPADA si falló
    fila.cerrada       → el desenlace

══ LOS VERBOS SON LOS REALES ════════════════════════════════════════════════════════

La lección está escrita en el molde y se calca sin adornos: «dibujar seis pasos donde el
sistema corre cuatro sería una animación, no un estado — y una animación que no corresponde
a nada es peor que un spinner: miente con más detalle».

Por eso la secuencia **se DERIVA de la vía**, y cada vía corre los suyos:

    local → runtime vivo · modelo descargado · prueba de inferencia
    cli   → binario presente · sesión activa · prueba de inferencia
    api   → llave presente · endpoint responde · prueba de inferencia

`incluido` corre sólo la prueba: no hay nada que el usuario tenga que traer, así que
enumerar «autenticar» sería inventarle un trámite.

══ SE DETIENE EN EL CULPABLE ════════════════════════════════════════════════════════

Al primer verbo que falla, la fila cierra ahí con su causa. Los que no llegaron a correr
salen como `pendiente`, **no como fallados**: decir que falló algo que nunca se intentó es
la misma clase de mentira que el checklist viene a matar. Y jamás verde parcial: si el
verbo N falló, no hay N+1 en verde.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Iterator, Optional

#: Los verbos, con su título en el idioma del usuario. Cerrado a propósito: agregar uno es
#: una decisión de producto, no un efecto colateral de una vía nueva.
VERBOS = {
    "runtime":    {"es": "Runtime vivo", "en": "Runtime up"},
    "descargado": {"es": "Modelo descargado", "en": "Model downloaded"},
    "binario":    {"es": "Programa instalado", "en": "Program installed"},
    "sesion":     {"es": "Sesión activa", "en": "Session active"},
    "llave":      {"es": "Llave guardada", "en": "Key stored"},
    "endpoint":   {"es": "El proveedor responde", "en": "Provider responds"},
    "prueba":     {"es": "Prueba de inferencia", "en": "Inference test"},
}

#: Qué verbos corre cada vía. LA SECUENCIA ES LA REAL — ver el docstring.
SECUENCIA = {
    "local":    ["runtime", "descargado", "prueba"],
    "cli":      ["binario", "sesion", "prueba"],
    "api":      ["llave", "endpoint", "prueba"],
    "incluido": ["prueba"],
}


def verbos_de(via: str) -> list:
    """Los verbos de esta vía, con título. Vía desconocida → sólo la prueba.

    No se inventa una secuencia para una vía que no conocemos: se corre lo único que
    siempre aplica (¿contesta?) y se dice. Enumerar pasos que no vamos a correr sería la
    animación que el molde prohíbe.
    """
    return [{"id": v, "titulo": VERBOS[v]["es"]} for v in SECUENCIA.get(via, ["prueba"])]


def correr(fila: dict, *, sondas: Optional[dict] = None,
           ahora: Optional[Callable[[], float]] = None) -> Iterator[dict]:
    """Genera los eventos del checklist de UN modelo. Puro salvo las sondas que se le pasen.

    `sondas` es `{verbo: callable() -> (ok, causa, detalle)}`. Lo que no tenga sonda se
    resuelve con lo que la FILA ya declara —que fue medido río arriba— en vez de inventar
    una medición nueva. Un checklist que re-mide todo desde cero es más lento y no más
    honesto.
    """
    reloj = ahora or time.time
    via = fila.get("familia") or fila.get("via") or ""
    ref = fila.get("ref") or fila.get("slug") or ""
    verbos = verbos_de(via)
    sondas = sondas or {}

    yield {"tipo": "fila.inicio", "ref": ref, "via": via,
           "verbos": verbos, "ts": reloj()}

    # Lo que la fila YA declara, por verbo. Es la medición de río arriba, no una nueva.
    declarado = {
        "runtime": (fila.get("causa") != "sin_runtime", "sin_runtime"),
        # [F7] `instalado is False` MANDA: un candidato de Hugging Face llega con
        # `local:true` («corre en tu máquina») e `instalado:false` («no está todavía»).
        # Leer sólo `local` daba por descargado lo que no se bajó nunca.
        "descargado": (fila.get("instalado") is not False
                       and bool(fila.get("local") or fila.get("descargado")),
                       "modelo_no_disponible"),
        "binario": (bool(fila.get("servicio_cli")), "cli_no_instalado"),
        "sesion": (bool(fila.get("sesion_cli")), "sin_sesion"),
        "llave": (bool(fila.get("hay_llave")), "falta_key"),
        "endpoint": (fila.get("estado") != "roto", fila.get("causa") or "error_upstream"),
        "prueba": (fila.get("estado") == "probado", fila.get("causa") or "fallo_desconocido"),
    }

    fallo = None
    hechos = 0
    for v in verbos:
        vid = v["id"]
        if fallo is not None:
            # NO se corre: se DECLARA pendiente. Decir que falló algo que nunca se intentó
            # es la misma mentira que este checklist viene a matar.
            yield {"tipo": "requisito.resultado", "ref": ref, "verbo": vid,
                   "estado": "pendiente", "ts": reloj()}
            continue
        yield {"tipo": "requisito.probando", "ref": ref, "verbo": vid,
               "titulo": v["titulo"], "ts": reloj()}
        if vid in sondas:
            try:
                ok, causa, detalle = sondas[vid]()
            except Exception as exc:                   # noqa: BLE001 — una sonda rota no cuelga la fila
                ok, causa, detalle = False, "falla_de_aleph", type(exc).__name__
        else:
            ok, causa = declarado.get(vid, (False, "fallo_desconocido"))
            detalle = None
        if ok:
            hechos += 1
            yield {"tipo": "requisito.resultado", "ref": ref, "verbo": vid,
                   "estado": "ok", "detalle": detalle, "ts": reloj()}
        else:
            fallo = {"verbo": vid, "causa": causa, "detalle": detalle}
            yield {"tipo": "requisito.resultado", "ref": ref, "verbo": vid,
                   "estado": "fallo", "causa": causa, "detalle": detalle, "ts": reloj()}

    # EL DESENLACE. `hechos` dice hasta dónde se llegó: es el dato que hace útil al
    # checklist («llegó a la sesión y ahí murió»), y perderlo lo deja en un spinner con
    # más pasos.
    yield {"tipo": "fila.cerrada", "ref": ref, "via": via,
           "ok": fallo is None, "hechos": hechos, "de": len(verbos),
           "causa": (fallo or {}).get("causa"), "verbo_culpable": (fallo or {}).get("verbo"),
           "ts": reloj()}


def sse(eventos: Iterator[dict]) -> Iterator[str]:
    """Eventos → líneas SSE, con el MISMO formato que el checklist de conectores."""
    import json as _json
    for ev in eventos:
        yield "data: " + _json.dumps(ev, ensure_ascii=False) + "\n\n"


__all__ = ["VERBOS", "SECUENCIA", "verbos_de", "correr", "sse"]
