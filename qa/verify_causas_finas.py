#!/usr/bin/env python3
"""verify_causas_finas.py — LA VARA DEL COPY QUE MENTÍA. Una sola invocación.

    python3 qa/verify_causas_finas.py

EL DEFECTO NO ERA LA COMPROBACIÓN, ERA EL TEXTO. Medido antes de esta obra: de 20 piezas del
registro, 16 quedaban bien clasificadas y las 4 que fallaban estaban muertas de verdad. O sea
`_classify_equip_error` acertaba. Lo que mentía era lo que el usuario leía:

    «La pieza no pasó la comprobación: no respondió como su ficha dice que responde.»

Esa frase acusa a la ficha. Se la comía un dominio que no existe (donde no hubo ficha ni
servidor ni nada), un servicio caído (donde la ficha está impecable), una pieza que pide una
llave que nunca declaró, y una que arranca y no trae herramientas. **Cuatro mundos, una sola
frase, y la culpa siempre en el lugar equivocado.**

La evidencia para separarlos YA VIAJABA —`http_status`, `red`, `red_detalle`— y
`_classify_equip_error` la colapsaba; el SSE encima pisaba todo con un `detail` fijo.

Las cuatro causas, selladas por persona usuaria el 2026-08-07, en orden de qué tan lejos llegó el
intento — que es también el orden en que se descartan entre sí:

    servicio_inexistente     el nombre no resuelve — no hay a quién llamar   → sin salida
    servicio_no_responde     hay a quién llamar y no contesta                → reintentar
    credencial_no_declarada  contesta 401/403 y su ficha no declara llave    → pegar llave
    sin_herramientas         arranca, saluda, catálogo vacío                 → sin salida

Bloques:
  1 · cada causa sale de su evidencia, y sólo de la suya   (+ negativos y discriminantes)
  2 · la evidencia se PRODUCE de verdad (probe_mcp en vivo, no un dict a mano)
  3 · el frame y el cierre las tratan como lo que son: un fallo de la CURACIÓN
  4 · GUARD · las causas viejas no cambiaron de veredicto
  5 · el copy (qa/verify_causas_finas_front.mjs): ES/EN, salida, y nadie culpa a la ficha
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "platform"))
sys.path.insert(0, str(RAIZ / "product" / "backend"))

FALLOS: list[str] = []
RESULTADO: dict[str, object] = {}


def ok(nombre: str, cond: bool, detalle=None) -> bool:
    RESULTADO[nombre] = bool(cond)
    print(("✅ " if cond else "❌ ") + nombre + (f": {detalle}" if detalle is not None else ""))
    if not cond:
        FALLOS.append(nombre)
    return bool(cond)


def no_medible(nombre: str, motivo: str) -> None:
    RESULTADO[nombre] = "NO_MEDIBLE"
    print(f"⚪ {nombre}: NO MEDIBLE — {motivo}")
    FALLOS.append(f"{nombre} (no medible)")


# ── EL CLASIFICADOR DE ANTES ───────────────────────────────────────────────────────────
# El negativo no es un mock: es ESTE archivo con el cuerpo viejo de `_classify_equip_error`,
# el que colapsaba los cuatro mundos. Corre contra las MISMAS entradas y tiene que decir
# `curacion_rechazo` a todo — que es exactamente el defecto.
_CUERPO_VIEJO = '''
def _classify_equip_error(exc):
    name = type(exc).__name__
    msg = str(exc).lower()
    evidence = getattr(exc, "evidencia", None) or {}
    if evidence.get("http_status") in (401, 403):
        return "needs_credential", "curar"
    if name == "BYOValidationError":
        return "curacion_rechazo", "curar"
    if name == "ResolveError":
        if "credencial" in msg or "credential" in msg:
            return "needs_credential", "curar"
        return "curacion_rechazo", "curar"
    return "sin_red", "equipar"
'''


def _clasificador_de_antes():
    ns: dict = {}
    exec(compile(_CUERPO_VIEJO, "clasificador_de_antes", "exec"), ns)  # noqa: S102
    return ns["_classify_equip_error"]


def _err(mensaje: str = "el MCP no validó", **evidencia):
    """Un `BYOValidationError` REAL, de la clase real, con la evidencia que produce el
    curador. No una excepción de mentira: el clasificador discrimina por tipo."""
    from inspection.byo_mcp import BYOValidationError
    return BYOValidationError(mensaje, evidencia=evidencia)


# ══ 1 · CADA CAUSA SALE DE SU EVIDENCIA, Y SÓLO DE LA SUYA ════════════════════════════
def bloque_1() -> None:
    from app.phase1.catalog_equip_router import _classify_equip_error as clasificar
    antes = _clasificador_de_antes()

    # ── (a) EL SERVICIO NO EXISTE ───────────────────────────────────────────────────────
    dns = _err("no se pudo resolver el host del MCP (no-existe.invalid)",
               fallo="dns", host="no-existe.invalid")
    ok("1a_servicio_inexistente", clasificar(dns)[0] == "servicio_inexistente",
       {"ahora": clasificar(dns)[0]})
    ok("1a_negativo_antes_era_curacion_rechazo", antes(dns)[0] == "curacion_rechazo",
       {"antes": antes(dns)[0]})

    # RESPALDO · cuando la capa de safety resuelve el host por su cuenta, el guard tipado no
    # llega a correr y el fracaso aparece más abajo, ya hecho texto. Se lee igual.
    texto = _err("el MCP no validó: Connection closed", transporte_probado="http",
                 red_detalle="[Errno 8] nodename nor servname provided",
                 red={"consultada": True})
    ok("1a_tambien_por_el_texto_de_la_libc",
       clasificar(texto)[0] == "servicio_inexistente", {"ahora": clasificar(texto)[0]})

    # ── (b) EL SERVICIO NO RESPONDE ─────────────────────────────────────────────────────
    caido = _err(transporte_probado="http", red={"consultada": True},
                 red_detalle="[Errno 61] Connection refused")
    ok("1b_servicio_no_responde", clasificar(caido)[0] == "servicio_no_responde",
       {"ahora": clasificar(caido)[0]})
    roto = _err(transporte_probado="http", http_status=503,
                red={"consultada": True, "online": True})
    ok("1b_un_5xx_tambien_es_no_responde", clasificar(roto)[0] == "servicio_no_responde",
       {"ahora": clasificar(roto)[0]})
    ok("1b_negativo_antes_era_curacion_rechazo", antes(caido)[0] == "curacion_rechazo",
       {"antes": antes(caido)[0]})

    # ⚠️ DISCRIMINANTE, y es el que impide una mentira nueva: un proceso LOCAL que no arranca
    #    NO es «el servicio está caído». No hubo servicio. Cae al resto honesto.
    local = _err("el proceso local no completó el saludo por stdio",
                 exit_code=1, red={"consultada": False})
    ok("1b_discriminante_un_proceso_local_no_es_un_servicio_caido",
       clasificar(local)[0] == "curacion_rechazo", {"ahora": clasificar(local)[0]})

    # ── (c) PIDE UNA LLAVE QUE NO DECLARA ───────────────────────────────────────────────
    # ⚠️ LA DECLARACIÓN SALE DEL SPEC, NO DE LOS HEADERS. El primer intento la sacaba de
    #    `bool(headers)` y estaba mal de raíz: en la PRIMERA sonda nunca se mandan headers
    #    —no hay llave todavía—, así que TODO 401 legítimo se leía como «pide algo que no
    #    declara». Lo cazó `verify_entrar::6_401_visible`. Acá se mide con la decisión real.
    class _Dec:
        def __init__(self, needs):
            self.spec = {"transport": "http", "needs_credential": needs}

    el_401 = _err(transporte_probado="http", http_status=401,
                  red={"consultada": True, "online": True})
    ok("1c_credencial_no_declarada",
       clasificar(el_401, _Dec(False))[0] == "credencial_no_declarada",
       {"ahora": clasificar(el_401, _Dec(False))[0]})

    # ⚠️ EL DISCRIMINANTE QUE JUSTIFICA LA CAUSA NUEVA. El MISMO 401 —la misma excepción,
    #    byte por byte— con la llave DECLARADA en la ficha sigue siendo `needs_credential`:
    #    la ruta a Conectar de siempre. Sin este testigo, la causa nueva podría estar
    #    tragándose a la vieja y todo saldría verde igual. Es lo que pasó, y rojeó.
    ok("1c_discriminante_con_la_llave_declarada_sigue_siendo_needs_credential",
       clasificar(el_401, _Dec(True))[0] == "needs_credential",
       {"ahora": clasificar(el_401, _Dec(True))[0]})

    # FAIL-CLOSED · sin decisión no se acusa a nadie: se asume que la ficha SÍ la declara.
    ok("1c_sin_spec_no_se_acusa_a_la_pieza",
       clasificar(el_401)[0] == "needs_credential", {"ahora": clasificar(el_401)[0]})

    ok("1c_negativo_antes_los_dos_401_eran_iguales",
       antes(el_401)[0] == "needs_credential",
       {"antes": antes(el_401)[0], "nota": "el clasificador viejo no miraba la ficha"})

    # ── (d) NO DECLARA HERRAMIENTAS ─────────────────────────────────────────────────────
    vacio = _err("el proceso arrancó pero no expone herramientas MCP usables",
                 fallo="sin_herramientas", tools_publicadas=0)
    ok("1d_sin_herramientas", clasificar(vacio)[0] == "sin_herramientas",
       {"ahora": clasificar(vacio)[0]})
    ok("1d_negativo_antes_era_curacion_rechazo", antes(vacio)[0] == "curacion_rechazo",
       {"antes": antes(vacio)[0]})

    # ── (e) EL RESTO HONESTO SIGUE EXISTIENDO ───────────────────────────────────────────
    # Una causa nueva no puede tragarse todo: un fallo que no encaja en ninguna de las cuatro
    # tiene que seguir cayendo en `curacion_rechazo`. Si esto rojea, las cuatro están
    # sobre-capturando y la próxima causa desconocida saldría mal nombrada.
    raro = _err("la firma del server no coincide con la esperada")
    ok("1e_el_resto_honesto_sigue_siendo_curacion_rechazo",
       clasificar(raro)[0] == "curacion_rechazo", {"ahora": clasificar(raro)[0]})


# ══ 2 · LA EVIDENCIA SE PRODUCE DE VERDAD ═════════════════════════════════════════════
def bloque_2() -> None:
    """Que el clasificador sepa leer `fallo: "dns"` no prueba que alguien lo escriba. Acá se
    corre `probe_mcp` REAL contra un dominio que no existe y se mira su excepción."""
    from inspection.byo_mcp import BYOValidationError, probe_mcp

    # `.invalid` está RESERVADO por la RFC 2606 justamente para esto: no resuelve nunca, en
    # ninguna red, y no es de nadie. Constante neutra (contrato del repo §1).
    try:
        probe_mcp(transport="http", url="https://no-existe-jamas.invalid/mcp", timeout=8.0)
        levanto = None
    except BYOValidationError as e:
        levanto = e
    except Exception as e:  # noqa: BLE001
        levanto = e

    if levanto is None:
        no_medible("2_el_dns_muerto_produce_su_evidencia",
                   "el probe NO falló contra un dominio .invalid (¿hay un DNS que inventa?)")
        return
    if not isinstance(levanto, BYOValidationError):
        no_medible("2_el_dns_muerto_produce_su_evidencia",
                   f"levantó {type(levanto).__name__}, no BYOValidationError")
        return

    from app.phase1.catalog_equip_router import _classify_equip_error as clasificar
    ev = getattr(levanto, "evidencia", None) or {}
    causa = clasificar(levanto)[0]
    ok("2_el_dns_muerto_produce_su_evidencia", causa == "servicio_inexistente",
       {"causa": causa, "evidencia": {k: ev.get(k) for k in ("fallo", "host", "red_detalle")},
        "mensaje": str(levanto)[:90]})


# ══ 3 · EL FRAME Y EL CIERRE ══════════════════════════════════════════════════════════
def bloque_3() -> None:
    """Las cuatro rompen el MISMO paso de la línea («comprobar»), así que viajan como
    `curacion.rechazo` y cierran por `path: "curacion"`. Si salieran como `error` genérico,
    el viaje se cerraría en rojo con los tres pasos en gris: sin lugar del corte."""
    from app.phase1.catalog_equip_router import (_CAUSAS_DE_CREDENCIAL, _es_de_curacion,
                                                  _frame_de)

    cuatro = ["servicio_inexistente", "servicio_no_responde",
              "credencial_no_declarada", "sin_herramientas"]
    ok("3_las_cuatro_cierran_por_curacion", all(_es_de_curacion(c) for c in cuatro),
       {c: _es_de_curacion(c) for c in cuatro})

    # Tres de las cuatro se cuentan como rechazo. La de la llave NO: comparte puerta con
    # `needs_credential` —`curacion.necesita_credencial` + `next: "connect"`— porque las dos
    # se resuelven pegando una llave. Cambiarle el camino además del nombre le cobraría al
    # usuario un descuido de la pieza. Lo destapó `verify_entrar::6_401_visible`.
    ok("3_tres_viajan_como_rechazo",
       all(_frame_de(c) == "curacion.rechazo"
           for c in cuatro if c not in _CAUSAS_DE_CREDENCIAL),
       {c: _frame_de(c) for c in cuatro if c not in _CAUSAS_DE_CREDENCIAL})
    ok("3_la_de_la_llave_comparte_puerta_con_needs_credential",
       "credencial_no_declarada" in _CAUSAS_DE_CREDENCIAL
       and "needs_credential" in _CAUSAS_DE_CREDENCIAL,
       {"puerta": sorted(_CAUSAS_DE_CREDENCIAL)})
    # NEGATIVO · la puerta no se abrió de más: las otras tres NO piden llave.
    ok("3_negativo_las_otras_tres_no_piden_llave",
       not any(c in _CAUSAS_DE_CREDENCIAL for c in
               ("servicio_inexistente", "servicio_no_responde", "sin_herramientas")))
    ok("3_curacion_rechazo_sigue_siendo_de_curacion",
       _frame_de("curacion_rechazo") == "curacion.rechazo")
    # NEGATIVO · lo que NO es de curación sigue sin serlo. Un `sin_red` no rompió el paso de
    # comprobar: ni siquiera se llegó a probar la pieza.
    ok("3_negativo_sin_red_no_es_de_curacion",
       _frame_de("sin_red") == "error" and not _es_de_curacion("sin_red"),
       {"sin_red": _frame_de("sin_red")})

    # Y el router NO escribe prosa: el `detail` fijo que pisaba las cuatro se fue.
    fuente = (RAIZ / "product/backend/app/phase1/catalog_equip_router.py").read_text(encoding="utf-8")
    ok("3_el_router_ya_no_escribe_la_frase_fija",
       "La opción no pasó la comprobación" not in fuente,
       {"quedan": fuente.count("La opción no pasó la comprobación")})


# ══ 4 · GUARD · LAS CAUSAS VIEJAS NO SE MOVIERON ══════════════════════════════════════
def bloque_4() -> None:
    """El arreglo agrega ramas ANTES de las que ya existían. Si alguna de las viejas cambió
    de veredicto, es una regresión disfrazada de causa nueva."""
    from app.phase1.catalog_equip_router import _classify_equip_error as clasificar
    antes = _clasificador_de_antes()

    class ResolveError(Exception):
        pass

    casos = {
        "resolve_sin_credencial": ResolveError("no encontré el server"),
        "resolve_con_credencial": ResolveError("falta la credencial del proveedor"),
        "inesperado": RuntimeError("la base no respondió"),
        "byo_generico": _err("la firma del server no coincide"),
    }
    difs = {}
    for nombre, exc in casos.items():
        a, b = antes(exc), clasificar(exc)
        if a != b:
            difs[nombre] = {"antes": a, "ahora": b}
    ok("4_guard_las_causas_viejas_no_se_movieron", not difs, {"diferencias": difs})


# ══ 5 · EL COPY ═══════════════════════════════════════════════════════════════════════
def bloque_5() -> None:
    front = RAIZ / "qa" / "verify_causas_finas_front.mjs"
    if not front.exists():
        no_medible("5_el_copy", "falta qa/verify_causas_finas_front.mjs")
        return
    try:
        p = subprocess.run(["node", str(front)], cwd=str(RAIZ), capture_output=True,
                           text=True, timeout=120)
    except subprocess.TimeoutExpired:
        no_medible("5_el_copy", "el front no respondió en 120s")
        return
    linea = next((l for l in reversed(p.stdout.splitlines()) if l.startswith("{")), None)
    if linea is None:
        no_medible("5_el_copy", f"el front no emitió veredicto (rc={p.returncode}): "
                                f"{(p.stderr or p.stdout).strip()[-200:]}")
        return
    for nombre, v in json.loads(linea).items():
        ok(nombre, bool(v.get("ok")), {k: x for k, x in v.items() if k != "ok"})


def main() -> int:
    print("═" * 90)
    print("VARA · LAS CUATRO CAUSAS FINAS DEL RECHAZO")
    print("═" * 90)
    bloque_1()
    bloque_2()
    bloque_3()
    bloque_4()
    bloque_5()
    print("─" * 90)
    verdes = sum(1 for v in RESULTADO.values() if v is True)
    total = len(RESULTADO)
    print(f"{verdes}/{total} verdes" + (f" · FALLOS: {FALLOS}" if FALLOS else " · SIN FALLOS"))
    print(json.dumps(RESULTADO, ensure_ascii=False))
    return 1 if FALLOS else 0


if __name__ == "__main__":
    raise SystemExit(main())
