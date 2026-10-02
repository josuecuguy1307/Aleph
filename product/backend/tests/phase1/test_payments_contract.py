"""test_payments_contract.py — EL §4-bis VUELTO EJECUTABLE.

    "Nada del resto del sistema importa el SDK de Dodo directo."
     — directiva Step 5, §1.4-bis (decisión cerrada)

Una regla que vive sólo en un MD se erosiona: el próximo que necesite un dato del
procesador va a importar el SDK donde le quede cómodo, y nadie se va a enterar hasta
que haya que cambiar de proveedor y aparezcan doce call-sites. Este test convierte la
regla en una condición de la suite: si alguien importa `dodopayments` fuera de su
adaptador, la regresión ENTERA se pone roja y dice exactamente dónde y por qué.

Vive en la suite de pytest (no en platform/) a propósito: tiene que correr SIEMPRE,
con la corrida normal de tests, sin que nadie se acuerde de invocarlo aparte.

EL ANTIPATRÓN ESTÁ VIVO EN EL ÁRBOL y es el ejemplo documentado: billing_router.py
importa el SDK de Stripe dentro del handler HTTP. Ese carril queda como estaba
(decisión de persona usuaria: intacto, ticket post-launch) — este test NO lo persigue; guarda
el carril nuevo para que no repita el error.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]

# `payments` vive en platform/, que no es un paquete instalado (mismo patrón que usa
# el resto del backend para cargar gates/).
_PLATFORM = str(REPO_ROOT / "platform")
if _PLATFORM not in sys.path:
    sys.path.insert(0, _PLATFORM)

#: El ÚNICO archivo de PRODUCCIÓN autorizado a importar el SDK de Dodo.
ADAPTADOR = REPO_ROOT / "platform" / "payments" / "dodo.py"

#: Excepciones EXPLÍCITAS, cada una con su motivo y su fecha de vencimiento.
#: Deliberadamente NO es una exclusión de `qa/` entera: un directorio excluido es un
#: agujero permanente por el que el acoplamiento vuelve sin que nadie lo note. Una
#: lista nominal obliga a que agregar una excepción sea una decisión visible en el diff.
#:
#: HOY ESTÁ VACÍA, y es el estado deseable. Tuvo una entrada (el harness de la llave
#: viva, que creaba el checkout con el SDK porque no había endpoint propio); P4 agregó
#: POST /v1/payments/checkout, el harness migró, y el test de vencimiento de abajo
#: avisó solo que la excepción sobraba. Así se supone que funciona: las excepciones
#: nacen con fecha de vencimiento y el arnés las cobra.
EXCEPCIONES: dict = {}

#: Dónde NO se busca: dependencias, entornos, cachés y el scratchpad de trabajo.
EXCLUIR_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache",
    "dist", "build", "backups",
}

#: `import dodopayments`, `from dodopayments import …`, `importlib…("dodopayments")`.
#: MULTILINE porque el import legítimo del adaptador está INDENTADO (vive dentro de
#: __init__, para que importar `base` no arrastre el SDK).
PATRON_SDK = re.compile(
    r"^\s*(?:from|import)\s+dodopayments\b|['\"]dodopayments['\"]", re.MULTILINE)


def _sin_comentarios(texto: str) -> list[str]:
    """Líneas de CÓDIGO: sin comentarios ni docstrings. La prosa que explica el diseño
    nombra a Dodo a propósito y no es una violación — lo que importa es qué IMPORTA
    el módulo, no de qué habla."""
    fuera, en_doc, delim = [], False, ""
    for linea in texto.splitlines():
        s = linea.strip()
        if en_doc:
            if delim in s:
                en_doc = False
            continue
        if s.startswith(('"""', "'''")):
            delim = s[:3]
            # docstring de una sola línea vs. bloque abierto
            if not (len(s) > 5 and s.endswith(delim)):
                en_doc = True
            continue
        if not s or s.startswith("#"):
            continue
        fuera.append(linea)
    return fuera


def _fuentes_python():
    for p in REPO_ROOT.rglob("*.py"):
        if any(part in EXCLUIR_DIRS for part in p.parts):
            continue
        yield p


def test_solo_el_adaptador_importa_el_sdk_de_dodo():
    """§4-bis: ningún archivo fuera de platform/payments/dodo.py toca el SDK."""
    infractores = []
    for path in _fuentes_python():
        if path == ADAPTADOR or path == Path(__file__) or path in EXCEPCIONES:
            continue
        try:
            texto = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "dodopayments" not in texto:
            continue  # atajo barato: el 99.9% de los archivos sale por acá
        for n, linea in enumerate(texto.splitlines(), 1):
            if PATRON_SDK.search(linea):
                infractores.append(f"{path.relative_to(REPO_ROOT)}:{n}: {linea.strip()}")

    assert not infractores, (
        "VIOLACIÓN DEL §4-bis — el SDK del procesador se importa fuera de su adaptador.\n"
        "El plano de control debe hablar la interfaz (platform/payments/base.py), no el SDK:\n"
        "cada import directo es un call-site más que hay que reescribir para cambiar de\n"
        "proveedor. Movelo detrás de ProcesadorDePagos.\n\n  "
        + "\n  ".join(infractores)
    )


def test_las_excepciones_siguen_existiendo_y_siguen_haciendo_falta():
    """Una excepción que ya no se usa es un agujero abierto por nada.

    Si un archivo exceptuado desapareció, o dejó de importar el SDK, la entrada tiene
    que BORRARSE de la lista — si no, mañana alguien crea un archivo con ese nombre y
    hereda un permiso que nadie le dio.
    """
    muertas = []
    for path, motivo in EXCEPCIONES.items():
        if not path.exists():
            muertas.append(f"{path.relative_to(REPO_ROOT)} — ya no existe ({motivo})")
        elif not PATRON_SDK.search(path.read_text(encoding="utf-8", errors="ignore")):
            muertas.append(
                f"{path.relative_to(REPO_ROOT)} — ya NO importa el SDK: la excepción "
                f"sobra, borrala ({motivo})")
    assert not muertas, (
        "Excepciones vencidas en la lista del §4-bis — borralas:\n  " + "\n  ".join(muertas))


def test_el_adaptador_realmente_importa_el_sdk():
    """Contra-prueba: si el adaptador dejara de importar el SDK, el test de arriba
    pasaría trivialmente para siempre y nadie se enteraría. Esto lo ancla."""
    assert ADAPTADOR.exists(), f"falta el adaptador: {ADAPTADOR}"
    assert PATRON_SDK.search(ADAPTADOR.read_text(encoding="utf-8")), (
        "platform/payments/dodo.py ya no importa el SDK: el test de contrato quedó "
        "vacío de contenido (pasaría siempre). Revisá si el adaptador se movió."
    )


def test_la_interfaz_no_importa_ningun_sdk():
    """base.py define el contrato: nunca importa el SDK de un procesador.

    Nombrar a Dodo en la PROSA es correcto y deseable (explica el diseño). Lo que la
    interfaz no puede hacer es depender del SDK — por eso se mide sobre el código,
    no sobre el texto.
    """
    codigo = _sin_comentarios(
        (REPO_ROOT / "platform" / "payments" / "base.py").read_text(encoding="utf-8"))
    assert not [l for l in codigo if "dodopayments" in l], \
        "base.py no puede importar el SDK de ningún procesador"


def test_el_registro_importa_el_adaptador_de_forma_PEREZOSA():
    """`from payments.dodo import …` tiene que estar DENTRO de get_procesador.

    Si subiera al tope del módulo, importar la interfaz arrastraría el SDK y el
    aislamiento se perdería en silencio: todo seguiría funcionando en dev (donde el
    SDK está instalado) y reventaría en un deploy sin la dependencia.
    """
    codigo = _sin_comentarios(
        (REPO_ROOT / "platform" / "payments" / "base.py").read_text(encoding="utf-8"))
    tope = [l for l in codigo if "payments.dodo" in l and not l.startswith((" ", "\t"))]
    assert not tope, (
        "base.py importa el adaptador concreto a nivel de MÓDULO; debe ser perezoso "
        f"(dentro de get_procesador):\n  " + "\n  ".join(tope))


def test_la_funcion_pura_de_tier_no_conoce_procesadores():
    """effects.py decide el tier: si dependiera de un procesador, la regla de negocio
    quedaría acoplada al proveedor de turno."""
    codigo = _sin_comentarios(
        (REPO_ROOT / "platform" / "payments" / "effects.py").read_text(encoding="utf-8"))
    assert not [l for l in codigo if "dodopayments" in l or "payments.dodo" in l], \
        "effects.py no puede depender del SDK ni del adaptador de ningún procesador"


@pytest.mark.parametrize("modulo", ["payments.base", "payments.effects"])
def test_interfaz_y_regla_importan_sin_el_sdk_instalado(modulo, monkeypatch):
    """El resto del backend tiene que poder importar la interfaz aunque el SDK del
    procesador NO esté instalado. Si `base` arrastrara el SDK, un deploy sin la
    dependencia se caería entero en vez de degradar en el borde."""
    import builtins
    import importlib
    import sys

    for m in list(sys.modules):
        if m.startswith("payments") or m.startswith("dodopayments"):
            sys.modules.pop(m, None)

    real_import = builtins.__import__

    def _sin_sdk(name, *a, **kw):
        if name == "dodopayments" or name.startswith("dodopayments."):
            raise ImportError("simulado: SDK no instalado")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _sin_sdk)
    importlib.import_module(modulo)  # no debe lanzar
