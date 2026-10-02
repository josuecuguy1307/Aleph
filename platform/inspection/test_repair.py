"""test_repair.py — R3 · LA POLÍTICA TEMPORAL, SOBRE HECHOS DETERMINISTAS.

**Ni un `sleep` en todo el archivo.** El reloj y el jitter de `Repair` son inyectables
justamente para esto: lo que se gatea son CONTEOS —intentos permitidos, ciclos agotados,
aperturas del breaker— que son hechos exactos. El reloj real se reporta en la vara viva
(`verify_repair_temporal.py`), nunca acá.

Lo que se fija:

  1. la curva: `min(BASE*2^(n-1), TOPE)` y el jitter acotado a ±25 %;
  2. **dos muertes y revive → se arregla callado**: el 2º pedido pasa, sin botón y sin pedir
     credencial;
  3. el que muere siempre AGOTA (tope de intentos o tope de tiempo) y termina bloqueado;
  4. el breaker abre a los N ciclos, dura, medio-abre con UN intento, cierra en verde y
     ESCALA tras 3 medio-abiertos en rojo;
  5. **el breaker CORTO** cuando R2 marcó `sospecha_de_cuelgue`;
  6. **JAMÁS se pide credencial por un temporal** — sobre todas las causas temporales;
  7. la lápida y el cambio de huella cierran lo que haya abierto;
  8. sin perilla, repair no decide nada.

    python3 -m pytest platform/inspection/test_repair.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_AQUI = Path(__file__).resolve().parent
_RAIZ = _AQUI.parents[1]
for _p in (_RAIZ / "platform", _RAIZ / "platform/inspection", _RAIZ / "platform/assembler",
           _RAIZ / "product/backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import repair as R                                          # noqa: E402
import repair_clasificar as RC                              # noqa: E402


class Reloj:
    """Un reloj que sólo avanza cuando se lo pide un test. Sin esto, medir un breaker de
    5 minutos costaría 5 minutos."""

    def __init__(self, t=1000.0):
        self.t = float(t)

    def __call__(self) -> float:
        return self.t

    def avanzar(self, s: float) -> None:
        self.t += float(s)


def _repair(jitter=0.0):
    """Repair con reloj falso y jitter FIJO: dos corridas dan exactamente lo mismo."""
    rl = Reloj()
    return R.Repair(reloj=rl, jitter=lambda a, b: jitter), rl


def _muerte(clave="u1|github|abc123", **kw):
    ev = {"clave": clave, "user_id": clave.split("|")[0], "entity_id": clave.split("|")[1],
          "huella": clave.split("|")[2], "disparador": "EOF", "murio_por_eof": True}
    ev.update(kw)
    return ev


# ══════════════════════════════════════════════════════════════════════════════════
# 1 · LA CURVA (§3.1)
# ══════════════════════════════════════════════════════════════════════════════════

def test_la_curva_es_la_del_diseno():
    rp, _ = _repair()
    assert [rp.espera(n) for n in (1, 2, 3, 4, 5)] == [1.0, 2.0, 4.0, 8.0, 16.0]


def test_la_curva_topea():
    rp, _ = _repair()
    assert rp.espera(20) == R.TOPE_S


@pytest.mark.parametrize("j", [-0.25, -0.1, 0.0, 0.1, 0.25])
def test_el_jitter_queda_acotado(j):
    rp, _ = _repair(jitter=j)
    assert 1.0 * 0.75 <= rp.espera(1) <= 1.0 * 1.25


def test_el_jitter_nunca_da_una_espera_negativa():
    rp, _ = _repair(jitter=-5.0)          # jitter absurdo a propósito
    assert rp.espera(3) >= 0.0


def test_base_y_topes_son_los_del_diseno():
    assert (R.BASE_S, R.TOPE_S, R.JITTER) == (1.0, 30.0, 0.25)
    assert (R.MAX_INTENTOS, R.MAX_TOTAL_S, R.VENTANA_S) == (5, 90.0, 120.0)


# ══════════════════════════════════════════════════════════════════════════════════
# 2 · SE ARREGLA CALLADO
# ══════════════════════════════════════════════════════════════════════════════════

def test_sin_muertes_el_pedido_pasa_derecho():
    rp, _ = _repair()
    assert rp.permitir("u1", "github", "u1|github|abc123").pasa


def test_dos_muertes_y_revive_se_arregla_CALLADO():
    """El caso que el §10 pide textual: muere dos veces, revive, y nadie se enteró."""
    rp, rl = _repair()
    clave = "u1|github|abc123"
    rp.observar(_muerte(clave))                       # 1ª muerte: el reconnect-once del dueño
    p1 = rp.permitir("u1", "github", clave)
    assert p1.pasa and p1.intento == 1

    rl.avanzar(1.0)
    rp.observar(_muerte(clave))                       # 2ª: disparador R1
    p2 = rp.permitir("u1", "github", clave)
    assert p2.pasa, f"el 2º intento tendría que pasar tras el backoff: {p2}"
    # y nada de esto produjo un botón ni una escalada
    est = rp.estado()
    assert est["eventos"]["escalados"] == 0
    assert est["eventos"]["breakers_abiertos"] == 0


def test_durante_el_backoff_ESPERA_y_no_bloquea_al_llamante():
    """`ESPERAR` es «todavía no», no un sleep dentro de `pedir()`."""
    rp, rl = _repair()
    clave = "u1|github|abc123"
    rp.observar(_muerte(clave))
    assert rp.permitir("u1", "github", clave).pasa          # consume el intento 1
    p = rp.permitir("u1", "github", clave)                  # enseguida otra vez
    assert p.decision == R.ESPERAR and p.faltan_s > 0
    rl.avanzar(1.1)
    assert rp.permitir("u1", "github", clave).pasa


# ══════════════════════════════════════════════════════════════════════════════════
# 3 · EL QUE MUERE SIEMPRE, AGOTA
# ══════════════════════════════════════════════════════════════════════════════════

def _agotar_un_ciclo(rp, rl, clave="u1|github|abc123", tope=None, entidad="github"):
    """Consume el ciclo entero por TOPE DE INTENTOS.

    ⚠️ Avanza el reloj EXACTAMENTE la espera de cada intento y ni un segundo más. La primera
    versión avanzaba `TOPE_S + 1` (31 s) por vuelta y el ciclo se agotaba por TIEMPO a los
    90 s, antes de llegar al 5º intento — o sea que medía el otro tope. Los dos son duros y
    gana el que llega primero; para probar uno hay que no disparar el otro.
    """
    tope = tope or R.MAX_INTENTOS
    rp.observar(_muerte(clave))
    for n in range(1, tope + 1):
        assert rp.permitir(clave.split("|")[0], entidad, clave).pasa, f"intento {n}"
        rl.avanzar(rp.espera(n) + 0.01)
    return rp.permitir(clave.split("|")[0], entidad, clave)


def test_agota_por_TOPE_DE_INTENTOS():
    rp, rl = _repair()
    p = _agotar_un_ciclo(rp, rl)
    assert p.decision == R.BLOQUEADO
    assert rp.estado()["eventos"]["ciclos_agotados"] == 1
    assert rp.estado()["ciclos"]["u1|github|abc123"]["intentos"] == R.MAX_INTENTOS


def test_agota_por_TOPE_DE_TIEMPO_aunque_queden_intentos():
    """Los dos topes son duros y el que llegue primero manda."""
    rp, rl = _repair()
    clave = "u1|github|abc123"
    rp.observar(_muerte(clave))
    assert rp.permitir("u1", "github", clave).pasa           # intento 1, arranca el reloj
    rl.avanzar(R.MAX_TOTAL_S + 1)
    p = rp.permitir("u1", "github", clave)
    assert p.decision == R.BLOQUEADO and "90s" in p.motivo
    assert rp.estado()["ciclos"][clave]["intentos"] == 1     # sobraban intentos


# ══════════════════════════════════════════════════════════════════════════════════
# 4 · EL BREAKER (§3.3)
# ══════════════════════════════════════════════════════════════════════════════════

def _agotar_ciclos(rp, rl, n, clave_base="u1|github|h", tope=None):
    """n ciclos agotados de la MISMA entidad, cada uno con su huella (el breaker es por
    entidad+usuario, los ciclos son por conexión)."""
    for i in range(n):
        _agotar_un_ciclo(rp, rl, f"{clave_base}{i}", tope=tope)
        rl.avanzar(1)


def test_el_breaker_abre_a_los_N_ciclos():
    rp, rl = _repair()
    _agotar_ciclos(rp, rl, R.CICLOS_PARA_ABRIR)
    est = rp.estado()
    assert est["eventos"]["breakers_abiertos"] == 1
    assert est["breakers"]["u1|github"]["estado"] == R.ABIERTO
    assert rp.permitir("u1", "github", "u1|github|nueva").decision == R.BLOQUEADO


def test_el_breaker_de_un_usuario_NO_alcanza_a_otro():
    """Nunca por entidad sola: sería dejar que la llave vencida de uno le abra el breaker a
    todos — la fuga del §2.1 con otra ropa."""
    rp, rl = _repair()
    _agotar_ciclos(rp, rl, R.CICLOS_PARA_ABRIR)
    assert rp.permitir("u1", "github", "u1|github|x").decision == R.BLOQUEADO
    assert rp.permitir("u2", "github", "u2|github|x").pasa


def test_el_breaker_dura_y_despues_MEDIO_ABRE_con_un_intento():
    rp, rl = _repair()
    _agotar_ciclos(rp, rl, R.CICLOS_PARA_ABRIR)
    rl.avanzar(R.BREAKER_ABIERTO_S - 30)      # holgura: los ciclos ya consumieron reloj
    assert rp.permitir("u1", "github", "u1|github|z").decision == R.BLOQUEADO
    rl.avanzar(60)
    p = rp.permitir("u1", "github", "u1|github|z")
    assert p.pasa and "medio-abierto" in p.motivo
    assert rp.estado()["breakers"]["u1|github"]["estado"] == R.MEDIO_ABIERTO


def test_el_medio_abierto_en_VERDE_lo_cierra():
    rp, rl = _repair()
    _agotar_ciclos(rp, rl, R.CICLOS_PARA_ABRIR)
    rl.avanzar(R.BREAKER_ABIERTO_S + 1)
    assert rp.permitir("u1", "github", "u1|github|z").pasa    # el intento de prueba
    rp.cerrar_breaker("u1", "github", motivo="anduvo")        # verde ⇒ cierra
    assert "u1|github" not in rp.estado()["breakers"]
    assert rp.permitir("u1", "github", "u1|github|z").pasa


def test_tres_medio_abiertos_en_ROJO_escalan():
    rp, rl = _repair()
    _agotar_ciclos(rp, rl, R.CICLOS_PARA_ABRIR)
    for i in range(R.MEDIO_ABIERTO_MAX):
        rl.avanzar(R.BREAKER_ABIERTO_S + 1)
        _agotar_un_ciclo(rp, rl, f"u1|github|re{i}")
    est = rp.estado()
    assert est["breakers"]["u1|github"]["escalado"] is True
    assert est["eventos"]["escalados"] == 1
    assert est["escalaciones"][0]["entity_id"] == "github"
    # y ya no se reabre solo: queda esperando acción humana
    rl.avanzar(R.BREAKER_ABIERTO_S * 10)
    assert rp.permitir("u1", "github", "u1|github|x").decision == R.BLOQUEADO


def test_el_breaker_CORTO_para_un_server_colgado():
    """R2 marca `sospecha_de_cuelgue` cuando el proceso VIVE y no contesta. Un server trabado
    no se destraba esperando: se le paga menos paciencia, y eso es medible."""
    rp, rl = _repair()
    colgado = _muerte("u1|colgado|h0", murio_por_eof=False)   # vive y no contesta
    v = RC.clasificar_muerte(colgado)
    assert v.señales.get("sospecha_de_cuelgue") is True, "R2 tiene que marcarlo"

    rp.observar(colgado)
    for n in range(1, R.MAX_INTENTOS_CUELGUE + 1):
        assert rp.permitir("u1", "colgado", "u1|colgado|h0").pasa
        rl.avanzar(rp.espera(n) + 0.01)
    assert rp.permitir("u1", "colgado", "u1|colgado|h0").decision == R.BLOQUEADO
    assert rp.estado()["ciclos"]["u1|colgado|h0"]["intentos"] == R.MAX_INTENTOS_CUELGUE
    assert R.MAX_INTENTOS_CUELGUE < R.MAX_INTENTOS, "el corto tiene que ser MÁS corto"


def test_el_breaker_corto_abre_con_menos_ciclos():
    rp, rl = _repair()
    for i in range(R.CICLOS_PARA_ABRIR_CUELGUE):
        clave = f"u1|colgado|h{i}"
        rp.observar(_muerte(clave, murio_por_eof=False))
        for n in range(1, R.MAX_INTENTOS_CUELGUE + 1):
            rp.permitir("u1", "colgado", clave)
            rl.avanzar(rp.espera(n) + 0.01)
        rp.permitir("u1", "colgado", clave)
        rl.avanzar(1)
    assert rp.estado()["breakers"]["u1|colgado"]["estado"] == R.ABIERTO
    assert R.CICLOS_PARA_ABRIR_CUELGUE < R.CICLOS_PARA_ABRIR


# ══════════════════════════════════════════════════════════════════════════════════
# 5 · LA REGLA SELLADA: JAMÁS CREDENCIAL POR TEMPORAL (§3.5)
# ══════════════════════════════════════════════════════════════════════════════════

def test_ningun_camino_temporal_produce_un_boton_de_credencial():
    """Sobre TODAS las causas temporales, y en los tres momentos del ciclo."""
    _CRED = {RC.B_RECONECTAR, RC.B_REVISAR_LLAVE, RC.B_CONECTAR}
    for causa in sorted(RC._REINTENTABLES_GATE2 | {"sin_respuesta", "error_upstream"}):
        rp, rl = _repair()
        clave = f"u1|{causa}|h"
        v = rp.observar(_muerte(clave, causa=causa))
        if v is None or not v.es_temporal:
            continue
        assert v.boton not in _CRED, f"{causa}: veredicto temporal con botón {v.boton}"
        for n in range(1, R.MAX_INTENTOS + 2):
            rp.permitir("u1", causa, clave)
            rl.avanzar(rp.espera(n) + 0.01)
        for esc in rp.estado()["escalaciones"]:
            assert "llave" not in esc["motivo"] and "credencial" not in esc["motivo"]


def test_un_permanente_no_consume_ni_un_intento():
    """Reintentar un 401 sólo gasta."""
    rp, _ = _repair()
    clave = "u1|zotero|h"
    v = rp.observar(_muerte(clave, causa="key_invalida"))
    assert v is not None and not v.es_temporal
    assert clave not in rp.estado()["ciclos"]
    assert rp.permitir("u1", "zotero", clave).pasa           # R4 se ocupa; R3 no frena


# ══════════════════════════════════════════════════════════════════════════════════
# 6 · LO QUE NO ES UN FALLO, Y LO QUE CIERRA
# ══════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("disp", ["LAPIDA", "OCIOSIDAD", "LRU", "CIERRE"])
def test_lo_que_no_es_un_fallo_no_abre_ciclo(disp):
    rp, _ = _repair()
    assert rp.observar(_muerte("u1|github|h", disparador=disp)) is None
    assert rp.estado()["ciclos"] == {}
    assert rp.estado()["eventos"]["no_fallos"] == 1


def test_la_lapida_cierra_el_breaker_abierto():
    """Una entidad que el usuario desconectó no puede quedar con un breaker esperándola."""
    rp, rl = _repair()
    _agotar_ciclos(rp, rl, R.CICLOS_PARA_ABRIR)
    assert rp.estado()["breakers"]["u1|github"]["estado"] == R.ABIERTO
    rp.observar(_muerte("u1|github|h9", disparador="LAPIDA"))
    assert "u1|github" not in rp.estado()["breakers"]


def test_el_boton_del_usuario_cierra_el_breaker():
    rp, rl = _repair()
    _agotar_ciclos(rp, rl, R.CICLOS_PARA_ABRIR)
    assert rp.cerrar_breaker("u1", "github", motivo="el usuario apretó el botón") is True
    assert rp.permitir("u1", "github", "u1|github|x").pasa


def test_una_huella_nueva_no_hereda_el_ciclo_viejo():
    """§3.3(d): si el usuario arregla la receta, la huella cambia y un ciclo agotado sobre la
    vieja no puede bloquear la nueva — o sería «arreglé la llave y sigue sin andar»."""
    rp, rl = _repair()
    vieja = "u1|github|VIEJA"
    _agotar_un_ciclo(rp, rl, vieja)
    assert rp.permitir("u1", "github", vieja).decision == R.BLOQUEADO
    rp.olvidar_huella(vieja)
    assert rp.permitir("u1", "github", "u1|github|NUEVA").pasa


def test_una_muerte_vieja_resetea_el_ciclo():
    """Fuera de la ventana, la muerte vuelve a ser gratis (el reconnect-once del dueño)."""
    rp, rl = _repair()
    clave = "u1|github|h"
    rp.observar(_muerte(clave))
    rp.permitir("u1", "github", clave)
    rl.avanzar(R.VENTANA_S + 1)
    rp.observar(_muerte(clave))
    assert rp.estado()["ciclos"][clave]["intentos"] == 0, "el contador tenía que resetearse"


# ══════════════════════════════════════════════════════════════════════════════════
# 7 · LA PERILLA Y EL CABLEADO
# ══════════════════════════════════════════════════════════════════════════════════

def test_la_perilla_esta_apagada_por_default():
    import os as _os
    previo = _os.environ.pop("ALEPH_REPAIR", None)
    try:
        assert R.encendido() is False
    finally:
        if previo is not None:
            _os.environ["ALEPH_REPAIR"] = previo


def test_sin_perilla_no_se_cablea_nada():
    import os as _os
    import dueno as D
    previo = _os.environ.pop("ALEPH_REPAIR", None)
    try:
        D._reset_para_tests()
        assert R.cablear(D) is False
        assert D.actual()._guardia is None and D.actual()._suscriptores == []
    finally:
        if previo is not None:
            _os.environ["ALEPH_REPAIR"] = previo


def test_con_perilla_se_cablean_las_dos_puntas():
    import os as _os
    import dueno as D
    previo = _os.environ.get("ALEPH_REPAIR")
    _os.environ["ALEPH_REPAIR"] = "on"
    try:
        D._reset_para_tests()
        R._reset_para_tests()
        assert R.cablear(D) is True
        assert D.actual()._guardia is not None, "falta el guardia (R3)"
        assert D.actual()._suscriptores, "falta el suscriptor (R1)"
    finally:
        if previo is None:
            _os.environ.pop("ALEPH_REPAIR", None)
        else:
            _os.environ["ALEPH_REPAIR"] = previo
        D._reset_para_tests()


def test_un_guardia_roto_no_deja_al_producto_sin_conexiones():
    """Falla hacia el lado conocido: si el guardia explota, se levanta como antes de R3."""
    import dueno as D
    D._reset_para_tests()
    d = D.actual()

    def _explota(*a, **k):
        raise RuntimeError("boom del guardia")

    d.poner_guardia(_explota)
    # no se llega a spawnear nada real: alcanza con que NO levante DuenoError por el guardia
    try:
        d.pedir("noexiste", spec={"command": "/bin/false", "args": [], "env": {},
                                  "cwd": None, "rpc_timeout": 1})
    except D.DuenoError as e:
        assert "lo frenó repair" not in str(e), f"el guardia roto frenó el spawn: {e}"
    finally:
        d.apagar_todo(motivo="fin del test")
