"""test_repair_escalada.py — R5 · EL AUTO-AJUSTE Y LA ESCALADA CON TRAZA.

Lo que se fija:

  1. **el ajuste de versión es AUTOMÁTICO y sin botón** (corrección sellada): la receta es
     territorio de Aleph. `servidor_incompatible` no lleva botón, y repair corrige solo;
  2. **UN intento, sin loops**: la segunda muerte no vuelve a ajustar;
  3. si el ajuste **alcanza** → no hay escalada y queda la nota del `[?]`;
     si **no alcanza** → escalada con la traza completa;
  4. la traza pasa por el **scrubber**: un server que imprime su llave en el stderr no la
     filtra a la card;
  5. **JAMÁS al catálogo** y UPDATE a la fila — los candados de R4, intactos;
  6. la lápida limpia el ajuste: una entidad desconectada no queda con uno pendiente.

    python3 -m pytest platform/inspection/test_repair_escalada.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_AQUI = Path(__file__).resolve().parent
_RAIZ = _AQUI.parents[1]
for _p in (_RAIZ / "platform", _RAIZ / "platform/inspection", _RAIZ / "platform/assembler",
           _RAIZ / "platform/gates", _RAIZ / "product/backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import repair as R                                          # noqa: E402
import repair_clasificar as RC                              # noqa: E402


class _Registro:
    """Un registro falso: una fila, y anota qué se le escribió."""

    def __init__(self, args=None, version="1.4.0", command="npx"):
        self.fila = {"entity_id": "coingecko", "command": command,
                     "args": args if args is not None else ["-y", "@coingecko/coingecko-mcp"],
                     "server_info": {"name": "cg", "version": version} if version else None}
        self.escrituras = []

    def leer(self, user_id, entity_id):
        return dict(self.fila) if entity_id == "coingecko" else None

    def escribir(self, user_id, entity_id, args, nota):
        self.escrituras.append({"user_id": user_id, "entity_id": entity_id,
                                "args": list(args), "nota": dict(nota)})
        self.fila["args"] = list(args)


def _repair(reg=None):
    rp = R.Repair(reloj=lambda: 1000.0, jitter=lambda a, b: 0.0)
    if reg is not None:
        rp.poner_ganchos_de_receta(reg.leer, reg.escribir)
    return rp


def _muerte_incompatible(**kw):
    ev = {"clave": "u1|coingecko|h1", "user_id": "u1", "entity_id": "coingecko",
          "huella": "h1", "disparador": "EOF", "murio_por_eof": True,
          "causa": "servidor_incompatible",
          "stderr": "Traceback…\nModuleNotFoundError: No module named 'x'",
          "exit_code": None, "exit_code_fuente": "no expuesto: stdio_client",
          "vivio_s": 0.4, "timeouts": [], "rpc_timeout_s": 30.0}
    ev.update(kw)
    return ev


# ══════════════════════════════════════════════════════════════════════════════════
# 1 · EL AJUSTE ES AUTOMÁTICO, SIN BOTÓN
# ══════════════════════════════════════════════════════════════════════════════════

def test_repair_corrige_la_receta_SOLO():
    """La receta es territorio de Aleph: no se pide permiso para arreglar lo nuestro."""
    reg = _Registro(version="1.4.0")
    rp = _repair(reg)
    v = rp.observar(_muerte_incompatible())
    assert v.causa == RC.SERVIDOR_INCOMPATIBLE and not v.es_temporal
    assert len(reg.escrituras) == 1, "no corrigió la receta"
    esc = reg.escrituras[0]
    assert esc["args"] == ["-y", "@coingecko/coingecko-mcp@1.4.0"]
    assert esc["nota"]["a"] == "1.4.0"


def test_el_veredicto_de_esa_causa_NO_trae_boton():
    """R2 la clasifica permanente; R5 le saca el botón. El usuario no ve trámite."""
    v = RC.clasificar("servidor_incompatible")
    assert not v.es_temporal
    # la UI la manda a SIN_BOTON — eso lo fija `test_repair_boton.py`; acá se fija que repair
    # no la ofrezca como acción del usuario tampoco.
    assert v.boton == RC.B_FIJAR_VERSION, (
        "el veredicto conserva el NOMBRE de la acción (repair la usa); lo que no hay es card")


def test_si_el_ajuste_ALCANZA_no_hay_escalada():
    reg = _Registro(version="1.4.0")
    rp = _repair(reg)
    rp.observar(_muerte_incompatible())
    assert rp.estado()["eventos"]["ajustes_aplicados"] == 1
    assert rp.escalacion_de("u1", "coingecko") is None, "escaló habiendo arreglado"


def test_queda_la_nota_para_el_interrogante():
    reg = _Registro(version="1.4.0")
    rp = _repair(reg)
    rp.observar(_muerte_incompatible())
    nota = rp.nota_de_ajuste("u1", "coingecko")
    assert nota and nota["a"] == "1.4.0" and nota["ts"] > 0


def test_sin_ajuste_no_hay_nota():
    """El usuario no tiene por qué enterarse de lo que no pasó."""
    rp = _repair(_Registro(version=None))
    rp.observar(_muerte_incompatible())
    assert rp.nota_de_ajuste("u1", "coingecko") is None


# ══════════════════════════════════════════════════════════════════════════════════
# 2 · UN INTENTO, SIN LOOPS
# ══════════════════════════════════════════════════════════════════════════════════

def test_un_solo_intento_de_auto_ajuste():
    """Una corrección automática que se repite deja de ser una corrección y pasa a ser un
    bucle con permisos de escritura."""
    reg = _Registro(version="1.4.0")
    rp = _repair(reg)
    rp.observar(_muerte_incompatible())
    rp.observar(_muerte_incompatible(clave="u1|coingecko|h2", huella="h2"))
    rp.observar(_muerte_incompatible(clave="u1|coingecko|h3", huella="h3"))
    assert len(reg.escrituras) == 1, f"ajustó {len(reg.escrituras)} veces"
    assert rp.estado()["eventos"]["ajustes_intentados"] == 1


def test_la_segunda_muerte_ESCALA_en_vez_de_reajustar():
    reg = _Registro(version="1.4.0")
    rp = _repair(reg)
    rp.observar(_muerte_incompatible())
    assert rp.escalacion_de("u1", "coingecko") is None
    rp.observar(_muerte_incompatible(clave="u1|coingecko|h2"))
    esc = rp.escalacion_de("u1", "coingecko")
    assert esc is not None, "la segunda vez tiene que escalar"
    assert "no hay segundo ajuste" in esc["por_que_paro"]


# ══════════════════════════════════════════════════════════════════════════════════
# 3 · CUANDO EL AJUSTE NO ALCANZA → ESCALADA CON TRAZA
# ══════════════════════════════════════════════════════════════════════════════════

def test_sin_version_buena_escala_con_su_motivo():
    rp = _repair(_Registro(version=None))
    rp.observar(_muerte_incompatible())
    esc = rp.escalacion_de("u1", "coingecko")
    assert esc and "a ciegas" in esc["por_que_paro"]
    assert esc["ajuste_automatico"]["intentado"] is True
    assert esc["ajuste_automatico"]["aplicado"] is False


def test_sin_ganchos_al_registro_lo_REPORTA_y_no_revienta():
    rp = _repair(None)                                    # sin ganchos
    v = rp.observar(_muerte_incompatible())
    assert v is not None
    assert rp.estado()["eventos"]["ajustes_sin_datos"] >= 1
    assert rp.escalacion_de("u1", "coingecko") is not None


def test_la_traza_lleva_TODO_lo_del_diseno():
    """§5.3: por qué empezó · qué se intentó · por qué paró · lo crudo."""
    rp = _repair(_Registro(version=None))
    rp.observar(_muerte_incompatible())
    esc = rp.escalacion_de("u1", "coingecko")
    for k in ("por_que_empezo", "por_que_paro", "causa", "clase", "ajuste_automatico",
              "crudo", "ts", "entity_id"):
        assert k in esc, f"a la traza le falta {k}"
    crudo = esc["crudo"]
    for k in ("stderr", "exit_code", "exit_code_fuente", "murio_por_eof", "vivio_s",
              "timeouts", "rpc_timeout_s"):
        assert k in crudo, f"al crudo le falta {k}"
    assert crudo["exit_code"] is None and crudo["exit_code_fuente"], (
        "`exit_code` viaja como None CON su motivo: no se inventa un cero")


def test_una_sola_escalada_por_entidad():
    """La card muestra una, no una pila. La última gana: es la que describe el ahora."""
    rp = _repair(_Registro(version=None))
    for h in ("h1", "h2", "h3"):
        rp.observar(_muerte_incompatible(clave=f"u1|coingecko|{h}", huella=h))
    escs = [e for e in rp.estado()["escalaciones"] if e["entity_id"] == "coingecko"]
    assert len(escs) == 1, f"quedaron {len(escs)} escaladas de la misma entidad"


# ══════════════════════════════════════════════════════════════════════════════════
# 4 · EL SCRUBBER: LA TRAZA NO FILTRA UNA LLAVE
# ══════════════════════════════════════════════════════════════════════════════════

_LLAVE = "sk-ant-api03-ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ"


def test_la_traza_no_publica_una_llave_que_el_server_imprimio():
    """El caso real: un server que escribe su token en el arranque. La traza va a una card
    que el usuario ve y probablemente copia."""
    rp = _repair(_Registro(version=None))
    rp.observar(_muerte_incompatible(
        stderr=f"arrancando con ANTHROPIC_API_KEY={_LLAVE}\nModuleNotFoundError: x"))
    esc = rp.escalacion_de("u1", "coingecko")
    limpio = esc["crudo"]["stderr"]
    # ⚠️ LAS TRES ASERCIONES SON NECESARIAS, y la primera versión sólo tenía la del medio —
    # que pasaba SIN QUE NADA SE HUBIERA REDACTADO: `.scrub()` devuelve un `ScrubReport`, no
    # un string, y el repr de ese objeto no contiene la llave. Un verde falso en el test de
    # una fuga es lo peor que puede salir de un test.
    assert isinstance(limpio, str), f"el stderr no es texto: {type(limpio).__name__}"
    assert _LLAVE not in limpio and _LLAVE not in str(esc), "LA TRAZA FILTRÓ LA LLAVE"
    assert "ModuleNotFoundError" in limpio, (
        "redactó de más: la traza quedó inservible y el humano no puede diagnosticar nada")


def test_el_scrubber_deja_constancia_de_que_corrio():
    rp = _repair(_Registro(version=None))
    rp.observar(_muerte_incompatible(stderr="algo pasó"))
    crudo = rp.escalacion_de("u1", "coingecko")["crudo"]
    assert crudo.get("scrubber", "").startswith("ok"), (
        f"no se sabe si el scrubber corrió: {crudo.get('scrubber')!r}")
    assert isinstance(crudo["stderr"], str)


def test_sin_scrubber_se_recorta_en_vez_de_publicar_crudo(monkeypatch):
    """Perder la traza es malo; filtrar una llave es peor."""
    import builtins
    real = builtins.__import__

    def _sin_gates(nombre, *a, **k):
        if nombre == "scrubber":
            raise ImportError("no disponible a propósito")
        return real(nombre, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _sin_gates)
    limpio = R._limpiar_traza({"stderr": f"clave={_LLAVE}"})
    assert limpio["stderr"] == ""
    assert "no disponible" in limpio["scrubber"]


# ══════════════════════════════════════════════════════════════════════════════════
# 5 · LOS CANDADOS DE R4, INTACTOS
# ══════════════════════════════════════════════════════════════════════════════════

def test_el_auto_ajuste_solo_escribe_args_y_la_nota():
    reg = _Registro(version="1.4.0")
    _repair(reg).observar(_muerte_incompatible())
    esc = reg.escrituras[0]
    assert set(esc) == {"user_id", "entity_id", "args", "nota"}


def test_no_ajusta_lo_que_ya_esta_pineado():
    """El negativo de R4, ahora por el camino automático: un pin que falla es ESCALADA, no
    otro pin."""
    reg = _Registro(args=["-y", "@coingecko/coingecko-mcp@1.4.0"], version="1.3.0")
    rp = _repair(reg)
    rp.observar(_muerte_incompatible())
    assert reg.escrituras == []
    esc = rp.escalacion_de("u1", "coingecko")
    assert esc and "ya está fijado" in esc["por_que_paro"]


def test_no_ajusta_un_comando_que_no_es_npx_ni_uvx():
    reg = _Registro(command="python3", args=["/ruta/server.py"], version="1.0.0")
    rp = _repair(reg)
    rp.observar(_muerte_incompatible())
    assert reg.escrituras == []


def test_el_ajuste_cierra_el_breaker_viejo():
    """La receta cambió ⇒ huella nueva. Si el breaker viejo no se cierra, el proceso nuevo
    nace bloqueado por el estado del viejo: «se ajustó y sigue sin andar»."""
    reg = _Registro(version="1.4.0")
    rp = _repair(reg)
    rp._breakers[("u1", "coingecko")] = R._Breaker(estado=R.ABIERTO,
                                                   abierto_hasta=float("inf"))
    rp.observar(_muerte_incompatible())
    assert "u1|coingecko" not in rp.estado()["breakers"]


# ══════════════════════════════════════════════════════════════════════════════════
# 6 · LA LÁPIDA
# ══════════════════════════════════════════════════════════════════════════════════

def test_la_lapida_limpia_el_ajuste_pendiente():
    """Una entidad que el usuario desconectó no queda con un auto-ajuste esperándola: si la
    vuelve a conectar, repair tiene que poder ayudarla de nuevo."""
    reg = _Registro(version=None)
    rp = _repair(reg)
    rp.observar(_muerte_incompatible())
    assert rp.estado()["ajustes"], "tendría que haber quedado el intento"
    rp.observar({"clave": "u1|coingecko|h1", "user_id": "u1", "entity_id": "coingecko",
                 "disparador": "LAPIDA"})
    assert rp.estado()["ajustes"] == {}
