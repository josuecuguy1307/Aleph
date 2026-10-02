#!/usr/bin/env python3
"""
multiagente.py — EL CONTRATO DE EJECUCIÓN MULTIAGENTE (F1 · CADENA).

Spec canónica: `docs/multiagente.md`. Contrato hermano (no lo reemplaza, lo extiende de
forma aditiva): `CONTRACT-RECIPE-v1-FROZEN.md`.

── QUÉ ES ──────────────────────────────────────────────────────────────────────
Un globo ES un Aleph cuyas piezas son Alephs; un Aleph solo es un globo de uno. Este
módulo toma una receta con `modo` + `belt.agent_refs[]` + `belt.agent_links[]` y la
convierte en un PLAN ordenado de eslabones, y después lo CORRE.

**CERO ENTIDADES NUEVAS.** No hay tabla nueva ni grafo paralelo: todo sale de la receta.

── QUÉ *NO* HACE (invariante portante) ─────────────────────────────────────────
NO define un ciclo de vida de run nuevo. **Los sub-runs son runs NORMALES**: este módulo
recibe el runner INYECTADO (`run_puppet_e2e`) y lo llama una vez por salto. Lo único que
agrega es el ENLACE POR CAMPO (`enlazar(...)`) y la LATENCIA MEDIDA. Si algún día esto
necesitara tocar `executor.run_puppet_e2e`, el diseño está mal — no el executor.

Mismo patrón de inyección que `delegation.py` (runner inyectado para no ciclar el import
recipe_assembler↔delegation), y por el mismo motivo.

── DELEGAR ≠ ENTREGAR ──────────────────────────────────────────────────────────
  · `delegar`  (delegar-y-vuelve)  — A llama a B, B responde, **el control VUELVE a A**.
                                     Es lo que YA existe: `delegation.py` (B es una tool de A).
  · `entregar` (entregar-y-suelta) — A termina, ENTREGA su salida a B y **SUELTA**.
                                     El control NO vuelve. Es el eslabón de CADENA.
No son intercambiables, y por eso el cable lleva TIPO además de DIRECCIÓN.

── VOCABULARIO SELLADO (docs/multiagente.md §0.3) ──────────────────────────────
  · **ARCO**    = las acciones radiales de una pieza en el Cuarto (UI).
  · **ABANICO** = el modo fan-out del multiagente (`modo: "abanico"`).
Jamás se cruzan.

stdlib-only + `belt_resolver` (hermano de este directorio). Sin red, sin DB, sin framework:
lo mismo que permite que `validar_forma()` lo llame el validador del backend sin acoplarlo.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

# ── EL ENUM DE MODOS ────────────────────────────────────────────────────────────
#: Los CUATRO modos que el schema declara. Un `modo` fuera de acá es error de validación.
MODOS = ("cadena", "orquesta", "oficina", "abanico")

#: Lo que el motor CORRE HOY. Los otros tres viven en el schema y se RECHAZAN con causa —
#: nunca con un silencio ni con un fallback a cadena (eso sería mentir sobre qué corrió).
MODOS_IMPLEMENTADOS = ("cadena",)

#: Los dos tipos de cable agente↔agente. Ver el docstring de arriba.
TIPOS_CABLE = ("delegar", "entregar")

#: El cable es un objeto de CLAVES CERRADAS, y ese cierre es PORTANTE: es lo que impide
#: que alguien declare a mano un campo que el motor DERIVA (p.ej. `nucleo`, §2.3 del doc).
CLAVES_CABLE = frozenset({"from", "to", "tipo"})

#: Centinela para el Aleph padre (el globo) como extremo de un cable. Válido a nivel FORMA;
#: en `cadena` se RECHAZA (el pedido entra por el primer eslabón, no por el globo).
NUCLEO = "nucleo"

#: Guard de recursión del anidamiento fractal. Alineado con `delegation.MAX_DEPTH` a
#: propósito: son el mismo presupuesto de profundidad visto desde dos formas distintas.
MAX_PROFUNDIDAD = 3


# ── ERRORES — todos con CAUSA legible por máquina + DETALLE legible por humano ───

class MultiagenteError(Exception):
    """Base. `causa` es el código estable (lo asierta la vara / lo rutea la UI);
    `detalle` es la frase que un humano lee. FALLO VISIBLE, JAMÁS MUDO."""

    causa = "multiagente_error"

    def __init__(self, detalle: str, *, causa: Optional[str] = None, extra: Optional[dict] = None):
        if causa:
            self.causa = causa
        self.detalle = detalle
        self.extra = extra or {}
        super().__init__(f"[{self.causa}] {detalle}")

    def as_dict(self) -> dict:
        return {"causa": self.causa, "detalle": self.detalle, **self.extra}


class ModoNoImplementado(MultiagenteError):
    """El modo existe en el schema pero el motor todavía no lo corre."""
    causa = "modo_no_implementado"


class CadenaInvalida(MultiagenteError):
    """La cadena declarada no es una cadena (bucle, bifurcación, repetido, suelta)."""
    causa = "cadena_invalida"


class RecursionExcedida(MultiagenteError):
    """El anidamiento fractal pasó la profundidad máxima o se mordió la cola."""
    causa = "multiagente_profundidad"


# ── EL PLAN ─────────────────────────────────────────────────────────────────────

@dataclass
class Eslabon:
    """Un eslabón de la cadena. `nucleo` y `entrega` son **DERIVADOS por el motor**
    (§2.3 del doc): no se eligen, no se declaran, y el set cerrado de claves del cable
    es lo que hace imposible declararlos."""
    orden: int
    slug: str
    agent_ref: str
    nucleo: bool                       # DERIVADO: primero o último ⇒ hay decisión
    entrega: bool                      # DERIVADO: el último ENTREGA al humano
    recipe: Optional[dict] = None      # la receta hija, si se planificó con resolución
    recipe_path: Optional[str] = None  # path canónico (huella para el guard de ciclos)
    subplan: Optional["Plan"] = None   # anidamiento fractal: este eslabón ES otra cadena

    def as_dict(self) -> dict:
        return {
            "orden": self.orden,
            "slug": self.slug,
            "agent_ref": self.agent_ref,
            "nucleo": self.nucleo,
            "entrega": self.entrega,
            "anidado": self.subplan is not None,
            "sub_eslabones": len(self.subplan.eslabones) if self.subplan else 0,
        }


@dataclass
class Plan:
    modo: str
    eslabones: list[Eslabon] = field(default_factory=list)
    cables: list[dict] = field(default_factory=list)   # los cables EFECTIVOS
    cables_derivados: bool = False                     # True = salieron del orden de declaración
    profundidad: int = 0

    def as_dict(self) -> dict:
        return {
            "modo": self.modo,
            "eslabones": [e.as_dict() for e in self.eslabones],
            "cables": self.cables,
            "cables_derivados": self.cables_derivados,
            "profundidad": self.profundidad,
            "largo": len(self.eslabones),
        }


# ── LECTURA DE LA RECETA (pura; sin filesystem) ─────────────────────────────────

def modo_de(recipe: Any) -> Optional[str]:
    """El `modo` declarado, o None. Ausente/null ⇒ el comportamiento de HOY, byte por byte."""
    if not isinstance(recipe, dict):
        return None
    m = recipe.get("modo")
    return m if isinstance(m, str) and m else None


def _belt(recipe: Any) -> dict:
    b = recipe.get("belt") if isinstance(recipe, dict) else None
    return b if isinstance(b, dict) else {}


def slug_de(agent_ref: str) -> str:
    """'catalog/agents/agent-<uuid>.config.json' -> 'agent-<uuid>'. MISMA derivación que
    `belt_resolver._slug_from_agent_ref` — se replica acá (3 líneas) para que este módulo
    siga siendo usable SIN filesystem, que es lo que permite que el validador lo llame."""
    name = Path(str(agent_ref)).name
    for suf in (".config.json", ".json"):
        if name.endswith(suf):
            return name[: -len(suf)]
    return name


def agent_refs_de(recipe: Any) -> list[str]:
    refs = _belt(recipe).get("agent_refs")
    return [r for r in refs if isinstance(r, str) and r.strip()] if isinstance(refs, list) else []


def piezas_aleph(recipe: Any) -> list[dict]:
    """LA PROYECCIÓN: qué piezas tipo `aleph` tiene este Aleph.

    Existe para que la FASE 2 dibuje EXACTAMENTE lo que el motor considera una pieza
    aleph — una sola respuesta a "¿qué alephs tiene este aleph?", nunca dos. Es el
    equivalente de `atoms_router` para las piezas herramienta.
    """
    return [{"id": slug_de(r), "type": "aleph", "ref": r, "slug": slug_de(r)}
            for r in agent_refs_de(recipe)]


def cables_declarados(recipe: Any) -> list:
    c = _belt(recipe).get("agent_links")
    return c if isinstance(c, list) else []


# ── VALIDACIÓN — pura, sin filesystem. La llama el validador Y el motor. ────────

def _err(causa: str, detalle: str, **extra) -> dict:
    return {"causa": causa, "detalle": detalle, **extra}


def validar_forma(recipe: Any) -> list[dict]:
    """TODA la validación de §3 del doc, SIN tocar el filesystem.

    Devuelve una lista de `{causa, detalle, ...}` (vacía = válido). No lanza: el caller
    decide si eso es un 422 del validador o un rechazo del motor — pero los DOS ven
    exactamente los mismos errores, porque es la misma función. Una prohibición que
    viviera sólo en la UI no sería una prohibición: sería un consejo que un POST saltea.
    """
    errores: list[dict] = []
    if not isinstance(recipe, dict):
        return [_err("receta_invalida", "la receta debe ser un objeto JSON")]

    # ── modo: enum cerrado. Ausente/null ⇒ nada que validar (back-compat total). ──
    modo_raw = recipe.get("modo")
    if modo_raw is not None:
        if not isinstance(modo_raw, str) or modo_raw not in MODOS:
            errores.append(_err(
                "modo_invalido",
                f"modo debe ser uno de {list(MODOS)} o null; recibido {modo_raw!r}"))

    # ── agent_links[]: forma. Se valida SIEMPRE que esté (aun con modo null): un cable
    #    malformado guardado hoy es una bomba para la fase 2, que lo va a dibujar.
    crudos = cables_declarados(recipe)
    if _belt(recipe).get("agent_links") is not None and not isinstance(
            _belt(recipe).get("agent_links"), list):
        errores.append(_err("cable_invalido",
                            "belt.agent_links, si está presente, debe ser una lista de cables"))
        crudos = []

    slugs = [slug_de(r) for r in agent_refs_de(recipe)]
    conocidos = set(slugs) | {NUCLEO}
    cables: list[dict] = []
    for i, c in enumerate(crudos):
        if not isinstance(c, dict):
            errores.append(_err("cable_invalido",
                                f"belt.agent_links[{i}] debe ser objeto {{from, to, tipo}}"))
            continue
        sobrantes = sorted(set(c.keys()) - CLAVES_CABLE)
        if sobrantes:
            # CIERRE PORTANTE: `nucleo`/`entrega` son DERIVADOS (§2.3). Que este set sea
            # cerrado es lo que hace IMPOSIBLE declararlos a mano.
            errores.append(_err(
                "cable_clave_no_permitida",
                f"belt.agent_links[{i}] tiene claves no permitidas {sobrantes}: "
                f"el cable es {{from, to, tipo}} y nada más "
                f"(núcleo/entrega los DERIVA el motor, no se eligen)"))
        for extremo in ("from", "to"):
            v = c.get(extremo)
            if not v or not isinstance(v, str):
                errores.append(_err("cable_invalido",
                                    f"belt.agent_links[{i}].{extremo} requerido (slug string no vacío)"))
            elif v not in conocidos:
                errores.append(_err(
                    "cable_extremo_desconocido",
                    f"belt.agent_links[{i}].{extremo}='{v}' no es un aleph declarado en "
                    f"belt.agent_refs[] (conocidos: {sorted(slugs)}) ni el centinela '{NUCLEO}'"))
        tipo = c.get("tipo")
        if tipo not in TIPOS_CABLE:
            errores.append(_err(
                "cable_tipo_invalido",
                f"belt.agent_links[{i}].tipo debe ser uno de {list(TIPOS_CABLE)} "
                f"(delegar-y-vuelve | entregar-y-suelta); recibido {tipo!r}"))
        if isinstance(c.get("from"), str) and c.get("from") == c.get("to"):
            errores.append(_err("cadena_ciclo",
                                f"belt.agent_links[{i}] va de '{c.get('from')}' a sí mismo"))
        cables.append(c)

    # Si la FORMA ya está rota, la estructura no se mide (mediría sobre basura).
    if errores:
        return errores

    modo = modo_de(recipe)
    if modo is None:
        return []

    if modo not in MODOS_IMPLEMENTADOS:
        return [_err("modo_no_implementado",
                     f"el modo «{modo}» todavía no corre",
                     modo=modo, implementados=list(MODOS_IMPLEMENTADOS))]

    return _validar_cadena(slugs, cables)


def _validar_cadena(slugs: list[str], cables: list[dict]) -> list[dict]:
    """La estructura de §3: repetido · núcleo como eslabón · tipo · bifurcación · bucle ·
    desconectada. Cada rechazo NOMBRA a los culpables — un "cadena inválida" pelado no
    le sirve a nadie."""
    errores: list[dict] = []

    if not slugs:
        return [_err("cadena_vacia",
                     "modo 'cadena' sin alephs: belt.agent_refs[] está vacío. "
                     "Una cadena de cero eslabones no tiene por dónde entrar el pedido.")]

    # (4) EL MISMO ALEPH DOS VECES — F1 lo RECHAZA por simplicidad. Ver doc §3.1:
    # queda anotado como PREGUNTA ABIERTA a persona usuaria, no como ley.
    vistos: set[str] = set()
    repetidos: list[str] = []
    for s in slugs:
        if s in vistos:
            repetidos.append(s)
        else:
            vistos.add(s)
    if repetidos:
        return [_err(
            "cadena_aleph_repetido",
            f"el mismo aleph aparece más de una vez en la cadena: {sorted(set(repetidos))}. "
            f"F1 lo rechaza por simplicidad — falta decidir si son dos instancias o la misma "
            f"pasando dos veces, cómo se lo direcciona si el slug ya no es único, y qué pasa "
            f"con su memoria. Rechazar es lo único que no inventa producto.",
            repetidos=sorted(set(repetidos)))]

    cables_efectivos, derivados = _cables_efectivos(slugs, cables)

    # (5) en CADENA todo cable es `entregar`: delegar-y-vuelve no es un eslabón de cadena.
    for c in cables_efectivos:
        if c["tipo"] != "entregar":
            errores.append(_err(
                "cadena_tipo_invalido",
                f"el cable {c['from']}→{c['to']} es «{c['tipo']}» (delegar-y-vuelve): en una "
                f"cadena el control NO vuelve, todo eslabón «entrega y suelta». "
                f"Un padre que delega y recupera el control es modo 'orquesta' (todavía no corre).",
                cable=c))

    # el centinela del globo no es un eslabón de la cadena
    for c in cables_efectivos:
        for extremo in ("from", "to"):
            if c[extremo] == NUCLEO:
                errores.append(_err(
                    "cadena_nucleo_en_cable",
                    f"el cable {c['from']}→{c['to']} usa el centinela '{NUCLEO}': en cadena el "
                    f"pedido entra por el PRIMER eslabón y el globo no es un eslabón.",
                    cable=c))
    if errores:
        return errores

    # (2) BIFURCACIÓN — grado > 1 en cualquiera de los dos sentidos
    sal: dict[str, list[str]] = {s: [] for s in slugs}
    ent: dict[str, list[str]] = {s: [] for s in slugs}
    for c in cables_efectivos:
        sal[c["from"]].append(c["to"])
        ent[c["to"]].append(c["from"])
    for s in slugs:
        if len(sal[s]) > 1:
            errores.append(_err(
                "cadena_bifurcacion",
                f"'{s}' entrega a {len(sal[s])} alephs ({sorted(sal[s])}): eso es una "
                f"BIFURCACIÓN, no una cadena. Abrir un pedido a varios a la vez es el modo "
                f"'abanico' (todavía no corre).",
                slug=s, salidas=sorted(sal[s])))
        if len(ent[s]) > 1:
            errores.append(_err(
                "cadena_bifurcacion",
                f"'{s}' recibe de {len(ent[s])} alephs ({sorted(ent[s])}): en una cadena cada "
                f"eslabón tiene UNA entrada. Recomponer varias entradas es el modo 'orquesta' "
                f"(todavía no corre).",
                slug=s, entradas=sorted(ent[s])))
    if errores:
        return errores

    # (1) BUCLE — con grado de salida ≤ 1 el grafo es funcional: hay ciclo sii al seguir
    # sucesores desde algún nodo se revisita uno del MISMO recorrido.
    global_visto: set[str] = set()
    for inicio in slugs:
        if inicio in global_visto:
            continue
        camino, actual = [], inicio
        en_camino: set[str] = set()
        while actual is not None and actual not in global_visto:
            if actual in en_camino:
                ciclo = camino[camino.index(actual):]
                return [_err("cadena_ciclo",
                             f"los cables forman un BUCLE: {' → '.join(ciclo + [actual])}. "
                             f"Una cadena no se muerde la cola.",
                             ciclo=ciclo)]
            camino.append(actual)
            en_camino.add(actual)
            actual = sal[actual][0] if sal[actual] else None
        global_visto |= en_camino

    # (3) UN camino que los cubra a TODOS: una fuente, un sumidero, y el recorrido completo
    fuentes = [s for s in slugs if not ent[s]]
    sumideros = [s for s in slugs if not sal[s]]
    if len(fuentes) != 1 or len(sumideros) != 1:
        return [_err(
            "cadena_desconectada",
            f"los cables no arman UNA cadena: hay {len(fuentes)} eslabón(es) de entrada "
            f"({sorted(fuentes)}) y {len(sumideros)} de salida ({sorted(sumideros)}). "
            f"Una cadena tiene exactamente uno de cada uno.",
            fuentes=sorted(fuentes), sumideros=sorted(sumideros))]

    orden = _recorrer(fuentes[0], sal)
    if len(orden) != len(slugs):
        return [_err(
            "cadena_desconectada",
            f"la cadena desde '{fuentes[0]}' recorre {len(orden)} de {len(slugs)} alephs "
            f"({sorted(set(slugs) - set(orden))} quedan sueltos). Todo aleph declarado tiene "
            f"que ser parte de la cadena.",
            sueltos=sorted(set(slugs) - set(orden)))]
    return []


def _cables_efectivos(slugs: list[str], cables: list[dict]) -> tuple[list[dict], bool]:
    """Los cables que MANDAN + si fueron derivados.

    `agent_links[]` presente y no vacío ⇒ manda tal cual. Ausente o `[]` ⇒ la cadena es el
    ORDEN DE DECLARACIÓN de `agent_refs[]`. En los dos casos hay UNA respuesta a "¿cuál es
    la cadena?" — que es justamente el punto de reportar siempre los efectivos.
    """
    if cables:
        return ([{"from": c["from"], "to": c["to"], "tipo": c["tipo"]} for c in cables], False)
    return ([{"from": a, "to": b, "tipo": "entregar"} for a, b in zip(slugs, slugs[1:])], True)


def _recorrer(inicio: str, sal: dict[str, list[str]]) -> list[str]:
    """Camino desde `inicio` siguiendo sucesores. Sin ciclos (ya descartados) termina."""
    orden, actual, tope = [], inicio, len(sal) + 1
    while actual is not None and len(orden) < tope:
        orden.append(actual)
        actual = sal[actual][0] if sal.get(actual) else None
    return orden


# ── PLANIFICACIÓN — acá SÍ se toca el filesystem (resuelve las recetas hijas) ────

def planificar(
    recipe: dict,
    repo_root: Any,
    *,
    _profundidad: int = 0,
    _ancestros: Sequence[str] = (),
) -> Plan:
    """Valida + resuelve + DERIVA. Planifica el ÁRBOL ENTERO antes de gastar un solo token:
    una cadena demasiado profunda o que se muerde la cola falla ACÁ, con causa, y no a la
    mitad del tercer salto con medio run pagado.

    Lanza ModoNoImplementado / CadenaInvalida / RecursionExcedida.
    """
    modo = modo_de(recipe)
    if modo is None:
        raise CadenaInvalida("la receta no declara `modo`: no hay cadena que planificar",
                             causa="modo_ausente")
    if modo not in MODOS:
        raise CadenaInvalida(f"modo debe ser uno de {list(MODOS)}; recibido {modo!r}",
                             causa="modo_invalido")
    if modo not in MODOS_IMPLEMENTADOS:
        raise ModoNoImplementado(f"el modo «{modo}» todavía no corre",
                                 extra={"modo": modo,
                                        "implementados": list(MODOS_IMPLEMENTADOS)})

    errores = validar_forma(recipe)
    if errores:
        e0 = errores[0]
        raise CadenaInvalida(e0["detalle"], causa=e0["causa"],
                             extra={"errores": errores})

    refs = agent_refs_de(recipe)
    slugs = [slug_de(r) for r in refs]
    ref_por_slug = dict(zip(slugs, refs))
    cables, derivados = _cables_efectivos(slugs, cables_declarados(recipe))
    sucesor = {c["from"]: c["to"] for c in cables}
    sal = {s: ([sucesor[s]] if s in sucesor else []) for s in slugs}
    fuente = next(s for s in slugs if s not in {c["to"] for c in cables})
    orden_slugs = _recorrer(fuente, sal)

    ultimo = len(orden_slugs) - 1
    plan = Plan(modo=modo, cables=cables, cables_derivados=derivados, profundidad=_profundidad)

    for i, slug in enumerate(orden_slugs):
        # DERIVADO, no elegido: primero y último tienen decisión (interpretan / entregan);
        # el del medio no — su salida va a UN solo lugar, fijado por la cadena.
        esl = Eslabon(orden=i, slug=slug, agent_ref=ref_por_slug[slug],
                      nucleo=(i == 0 or i == ultimo), entrega=(i == ultimo))
        _resolver_hijo(esl, repo_root, _profundidad=_profundidad, _ancestros=_ancestros)
        plan.eslabones.append(esl)
    return plan


def _resolver_hijo(esl: Eslabon, repo_root: Any, *, _profundidad: int,
                   _ancestros: Sequence[str]) -> None:
    """Resuelve el agent_ref a su receta + aplica el GUARD DE RECURSIÓN, y si la hija es a
    su vez una cadena, planifica el sub-plan (anidamiento fractal)."""
    from belt_resolver import AgentResolutionError, resolve_agent_ref  # hermano de este dir

    try:
        resuelto = resolve_agent_ref(esl.agent_ref, Path(repo_root))
    except AgentResolutionError as exc:
        raise CadenaInvalida(
            f"el eslabón '{esl.slug}' no resuelve a una receta guardada: {exc}",
            causa="aleph_no_resuelve", extra={"slug": esl.slug, "agent_ref": esl.agent_ref})

    # HUELLA = PATH CANÓNICO (mismo criterio que delegation.canonical_fingerprint): dos
    # agentes DISTINTOS con el mismo meta.name NO son un ciclo; dos refs al MISMO archivo SÍ.
    try:
        huella = str(Path(resuelto.recipe_path).resolve())
    except Exception:  # noqa: BLE001
        huella = str(resuelto.recipe_path)
    esl.recipe = resuelto.recipe
    esl.recipe_path = huella

    if huella in _ancestros:
        cadena_txt = " → ".join([*(Path(a).name for a in _ancestros), Path(huella).name])
        raise RecursionExcedida(
            f"anidamiento CIRCULAR: el aleph '{esl.slug}' ya está en su propia ascendencia "
            f"({cadena_txt}). Un globo no puede contenerse a sí mismo.",
            causa="multiagente_ciclo_de_alephs",
            extra={"slug": esl.slug, "ascendencia": [str(a) for a in _ancestros]})

    if modo_de(resuelto.recipe) is None:
        return  # eslabón hoja: un aleph normal. Se corre como run normal.

    # ANIDAMIENTO FRACTAL: la hija ES otra cadena.
    # Misma forma exacta que `delegation.py` (RIEL #2, `depth + 1 > MAX_DEPTH` con la raíz
    # en 0): la raíz es profundidad 0 y se admiten MAX_PROFUNDIDAD niveles debajo. Que sean
    # el mismo número Y la misma comparación es lo que hace honesto decir que están alineados.
    if _profundidad + 1 > MAX_PROFUNDIDAD:
        raise RecursionExcedida(
            f"anidamiento DEMASIADO PROFUNDO: '{esl.slug}' abriría la profundidad "
            f"{_profundidad + 1} y el máximo es {MAX_PROFUNDIDAD}.",
            causa="multiagente_profundidad",
            extra={"slug": esl.slug, "profundidad": _profundidad + 1,
                   "max": MAX_PROFUNDIDAD})
    esl.subplan = planificar(resuelto.recipe, repo_root,
                             _profundidad=_profundidad + 1,
                             _ancestros=tuple(_ancestros) + (huella,))


# ── LA CORRIDA ──────────────────────────────────────────────────────────────────

def correr_cadena(
    recipe: dict,
    prompt: str,
    *,
    runner: Callable[..., dict],
    repo_root: Any,
    plan: Optional[Plan] = None,
    enlazar: Optional[Callable[..., None]] = None,
    on_salto: Optional[Callable[[dict], None]] = None,
    _profundidad: int = 0,
    _ancestros: Sequence[str] = (),
) -> dict:
    """Corre la CADENA. El pedido entra por el PRIMERO · cada eslabón hace lo suyo y SUELTA
    · el último ENTREGA.

    `runner(recipe, prompt, eslabon)` → dict con al menos `{ok, answer, run_id, error}`.
    Es **el runner de siempre** (`executor.run_puppet_e2e`), inyectado: cada salto es un
    run NORMAL. Este módulo no define ciclo de vida propio.

    `enlazar(run_id=…, orden=…, latencia_ms=…)` estampa el ENLACE POR CAMPO sobre la fila
    del salto DESPUÉS de que cerró. Opcional (sin DB, la cadena corre igual).

    La ENTRADA del eslabón N+1 es la SALIDA del N, **verbatim**. No se le agrega framing
    inventado: qué hacer con eso lo dice el `framing` de la receta hija.
    """
    plan = plan or planificar(recipe, repo_root,
                              _profundidad=_profundidad, _ancestros=_ancestros)

    t0_total = time.perf_counter()
    saltos: list[dict] = []
    entrada = prompt
    respuesta = ""
    ok = True
    error: Optional[dict] = None

    for esl in plan.eslabones:
        t0 = time.perf_counter()
        if esl.subplan is not None:
            sub = correr_cadena(esl.recipe, entrada, runner=runner, repo_root=repo_root,
                                plan=esl.subplan, enlazar=enlazar, on_salto=on_salto,
                                _profundidad=_profundidad + 1,
                                _ancestros=tuple(_ancestros) + (esl.recipe_path or "",))
            salida, salto_ok = sub.get("respuesta", ""), bool(sub.get("ok"))
            run_id, salto_err, anidado = None, sub.get("error"), sub
        else:
            out = runner(esl.recipe, entrada, esl) or {}
            salida = out.get("answer") or ""
            salto_ok = bool(out.get("ok"))
            run_id = out.get("run_id")
            salto_err = out.get("error")
            anidado = None
        # LA LATENCIA POR SALTO — el primer dato PROPIO (doc §4.2). Medida, no citada.
        latencia_ms = int(round((time.perf_counter() - t0) * 1000))

        salto = {
            "orden": esl.orden,
            "slug": esl.slug,
            "agent_ref": esl.agent_ref,
            "run_id": run_id,
            "nucleo": esl.nucleo,       # DERIVADO
            "entrega": esl.entrega,     # DERIVADO
            "anidado": anidado is not None,
            "latencia_ms": latencia_ms,
            "ok": salto_ok,
            "error": salto_err,
            "entrada_chars": len(entrada or ""),
            "salida_chars": len(salida or ""),
        }
        if anidado is not None:
            salto["sub_cadena"] = {"saltos": anidado.get("saltos", []),
                                   "latencia_total_ms": anidado.get("latencia_total_ms")}
        saltos.append(salto)
        if on_salto:
            try:
                on_salto(salto)
            except Exception:  # noqa: BLE001 — narrar un salto jamás tumba la cadena
                pass
        if enlazar and run_id:
            try:
                enlazar(run_id=run_id, orden=esl.orden, latencia_ms=latencia_ms)
            except Exception:  # noqa: BLE001 — el enlace es registro, no camino crítico
                pass

        if not salto_ok:
            # UN ESLABÓN ROTO CORTA LA CADENA. Seguir sería entregarle basura al siguiente
            # y devolver una respuesta que nadie produjo: fallo visible, jamás mudo.
            ok = False
            error = {"causa": "cadena_eslabon_fallido",
                     "detalle": (f"el eslabón {esl.orden + 1}/{len(plan.eslabones)} "
                                 f"('{esl.slug}') falló: {salto_err or 'sin respuesta'}"),
                     "orden": esl.orden, "slug": esl.slug}
            break
        entrada = salida
        respuesta = salida

    return {
        "ok": ok,
        "modo": plan.modo,
        "respuesta": respuesta if ok else "",
        "saltos": saltos,
        "latencia_total_ms": int(round((time.perf_counter() - t0_total) * 1000)),
        "plan": plan.as_dict(),
        "error": error,
    }


__all__ = [
    "MODOS", "MODOS_IMPLEMENTADOS", "TIPOS_CABLE", "CLAVES_CABLE", "NUCLEO",
    "MAX_PROFUNDIDAD",
    "MultiagenteError", "ModoNoImplementado", "CadenaInvalida", "RecursionExcedida",
    "Eslabon", "Plan",
    "modo_de", "slug_de", "agent_refs_de", "piezas_aleph", "cables_declarados",
    "validar_forma", "planificar", "correr_cadena",
]
