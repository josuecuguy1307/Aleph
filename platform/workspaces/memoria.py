"""memoria.py — CÓMO QUEDÓ CADA WORKSPACE, POR DUEÑO.
[Gate 4 · Fase 4 · obra O5 · ley 5 «abiertos muchos, montado uno» · ley técnica 4]

QUÉ RESUELVE
------------
La vara de esta fase pide que **volver a un workspace lo devuelva como quedó**, con
**memoria por-workspace de deltas** y **clave de dominio**. Hoy lo único que se recordaba
era el hilo, y se recordaba mal:

    localStorage["aleph_ws_chat_ciencia"]

Eso es una clave de **instalación**, no de dominio: el mismo navegador, para cualquier
cuenta que entre, ve el mismo hilo. Está declarado desde F3 como la deuda **D1**
(`workspaces/ciencia.html`), y esta obra la salda para los workspaces.

LA CLAVE ES `(dueño, workspace)` — LEY TÉCNICA 4
-----------------------------------------------
«Clave del snapshot = dominio, no UI». El dueño es quien abrió sesión; el workspace es el
id del registro. Ni el navegador, ni la pestaña, ni la pantalla entran en la clave: un
workspace se sigue sintiendo el mismo desde otra ventana, y dos cuentas en la misma máquina
**jamás** se ven la memoria (la fuga entre cuentas de Gate 2.5 costó 64 átomos ajenos; acá
se paga por adelantado con un `fail-closed`).

QUÉ ES UN «DELTA», Y QUÉ NO
---------------------------
Un delta es **lo que este usuario cambió en este workspace**: su hilo, su sesión de obras, y
lo que la pantalla del workspace declare como suyo. **No** es el estado interno del stack
heredado —eso es del stack, vive en sus datos y no se duplica acá (ley 0: su alimentación no
se toca)—, y **no** es la anatomía del workspace, que es fija (ley 1).

Por eso `deltas` es un diccionario abierto y `chat_id`/`sid` son campos con nombre: los dos
que la casa ya usa y sabe verificar. Un workspace que quiera recordar algo suyo lo mete en
`deltas` sin migración; el día que un campo se gane su lugar, se le pone nombre.

DÓNDE VIVE
----------
Un JSON por dueño bajo `aleph_paths.user_data_dir()`, con escritura atómica. No es la DB
porque no hay nada que consultar entre filas: se lee entero, se escribe entero, y es de
una sola persona. El día que haga falta cruzarlo con otra cosa, migra — y por eso lleva
`schema_version` LEÍDA, como manda el contrato de artefactos.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from typing import Any, Optional

_AQUI = Path(__file__).resolve().parent
if str(_AQUI.parent) not in sys.path:
    sys.path.insert(0, str(_AQUI.parent))

import aleph_paths as _ap                                   # noqa: E402

#: La versión va ADENTRO del dato y se LEE al cargar (ley técnica 2). Una versión que no se
#: lee es un comentario.
SCHEMA_VERSION = 1

_LOCK = threading.RLock()


class MemoriaError(Exception):
    """Causa tipada. Hoy sólo una: sin dueño no hay memoria."""

    def __init__(self, causa: str, detalle: str = ""):
        self.causa = causa
        self.detalle = detalle
        super().__init__(f"{causa}: {detalle}" if detalle else causa)


#: El copy de cada causa (regla sellada: ninguna causa llega a una superficie sin copy).
CAUSAS = {
    "sin_dueno": "No sé de quién es este workspace: hay que iniciar sesión.",
    "workspace_invalido": "Ese workspace no tiene un nombre que la casa pueda usar.",
    "ajuste_desconocido": "Ese ajuste no existe en esta casa.",
    "valor_invalido": "Ese ajuste no acepta ese valor.",
    "ambito_invalido": "Un ajuste es de toda la casa o de un espacio, no de otra cosa.",
}


def _seguro(valor: Any, largo: int = 120) -> Optional[str]:
    """Un id opaco o nada. Mismo criterio que `provenance.safe_ref`: lo que no tiene forma
    de id no se guarda ni se usa para armar una ruta de archivo."""
    s = str(valor or "").strip()
    if not s or len(s) > largo:
        return None
    if not all(c.isalnum() or c in "._:-" for c in s):
        return None
    # El mismo hueco que tenía `centro_modelos._slug_de_owner`, encontrado por la vara de
    # la fase 1: sin esta línea `..` pasa (el punto está permitido) y termina armando un
    # nombre de archivo `...json`. Un id es un id: lleva al menos un alfanumérico.
    if not any(c.isalnum() for c in s):
        return None
    return s


def _ruta(user_id: str) -> Path:
    d = _ap.user_data_dir() / "workspaces" / "memoria"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{user_id}.json"


def _leer(user_id: str) -> dict:
    p = _ruta(user_id)
    if not p.is_file():
        return {"schema_version": SCHEMA_VERSION, "workspaces": {}}
    try:
        datos = json.loads(p.read_text(encoding="utf-8"))
    except Exception:                                       # noqa: BLE001
        # Un archivo ilegible NO borra la memoria de nadie ni tumba la pantalla: se trata
        # como «todavía no hay memoria» y el próximo guardado lo reescribe entero.
        return {"schema_version": SCHEMA_VERSION, "workspaces": {}}
    if not isinstance(datos, dict) or not isinstance(datos.get("workspaces"), dict):
        return {"schema_version": SCHEMA_VERSION, "workspaces": {}}
    # LA VERSIÓN SE LEE. Hoy sólo hay una, y por eso lo único que corresponde es dejar el
    # gancho escrito y no fingir una migración que nadie escribió.
    if int(datos.get("schema_version") or 0) > SCHEMA_VERSION:
        raise MemoriaError("memoria_de_futuro",
                           "esta memoria la escribió una versión más nueva de Aleph")
    return datos


def _escribir(user_id: str, datos: dict) -> None:
    p = _ruta(user_id)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)                                      # atómico: nunca media memoria


# ── LA SUPERFICIE ───────────────────────────────────────────────────────────────────

def recordar(user_id: Optional[str], ws: str, *, chat_id: Optional[str] = None,
             sid: Optional[str] = None, deltas: Optional[dict] = None) -> dict:
    """Guarda cómo quedó `ws` para `user_id`. Devuelve la memoria completa de ese workspace.

    **Es un MERGE, no un reemplazo.** Una pantalla que sólo sabe el hilo no puede borrarle
    la sesión de obras a otra que sólo sabe eso: cada superficie manda lo suyo y la memoria
    conserva el resto. Mandar `null` en un campo lo deja como estaba; para borrar de verdad
    hay que mandar `""`, que es una decisión explícita del llamante.
    """
    dueno = _seguro(user_id)
    if not dueno:
        raise MemoriaError("sin_dueno", "la memoria de un workspace es de alguien")
    clave = _seguro(ws, 60)
    if not clave:
        raise MemoriaError("workspace_invalido", str(ws)[:40])
    with _LOCK:
        datos = _leer(dueno)
        actual = dict(datos["workspaces"].get(clave) or {})
        if chat_id is not None:
            actual["chat_id"] = _seguro(chat_id) if chat_id else None
        if sid is not None:
            actual["sid"] = _seguro(sid) if sid else None
        if deltas is not None:
            mezcla = dict(actual.get("deltas") or {})
            mezcla.update({k: v for k, v in deltas.items() if isinstance(k, str)})
            actual["deltas"] = mezcla
        datos["workspaces"][clave] = actual
        datos["schema_version"] = SCHEMA_VERSION
        _escribir(dueno, datos)
        return dict(actual)


def como_quedo(user_id: Optional[str], ws: str) -> dict:
    """Cómo quedó `ws` para `user_id`. Sin memoria devuelve `{}` — que no es un error: es un
    workspace al que todavía no entró nadie."""
    dueno = _seguro(user_id)
    if not dueno:
        raise MemoriaError("sin_dueno", "la memoria de un workspace es de alguien")
    clave = _seguro(ws, 60)
    if not clave:
        raise MemoriaError("workspace_invalido", str(ws)[:40])
    with _LOCK:
        return dict(_leer(dueno)["workspaces"].get(clave) or {})


def todos(user_id: Optional[str]) -> dict:
    """La memoria de TODOS los workspaces de este dueño. La usa el aplicador para saber
    dónde estuvo el usuario sin preguntarle a cada pantalla."""
    dueno = _seguro(user_id)
    if not dueno:
        raise MemoriaError("sin_dueno", "la memoria de un workspace es de alguien")
    with _LOCK:
        return dict(_leer(dueno)["workspaces"])


# ── LA PREFERENCIA (4.5) ────────────────────────────────────────────────────────────
# Vive en el MISMO archivo que la memoria y no en un almacén nuevo: es del mismo dueño, se
# lee en el mismo momento y se escribe con el mismo candado. Un segundo almacén para tres
# claves sería un segundo lugar donde arreglar el día que la clave de dominio cambie.
#
# La preferencia es POR TIPO DE ARTEFACTO, no global: «los informes ábrelos en Ciencia» es
# una decisión que el usuario puede tomar; «todo en Ciencia» le quita la casa.

def preferir(user_id: Optional[str], tipo: str, ws: Optional[str]) -> dict:
    """Graba (o borra, con `ws` vacío) a qué workspace va un tipo de artefacto."""
    dueno = _seguro(user_id)
    if not dueno:
        raise MemoriaError("sin_dueno", "una preferencia es de alguien")
    t = _seguro(tipo, 40)
    if not t:
        raise MemoriaError("tipo_invalido", str(tipo)[:40])
    destino = _seguro(ws, 60) if ws else None
    with _LOCK:
        datos = _leer(dueno)
        prefs = dict(datos.get("preferencias") or {})
        if destino:
            prefs[t] = destino
        else:
            prefs.pop(t, None)
        datos["preferencias"] = prefs
        _escribir(dueno, datos)
        return prefs


def preferencias(user_id: Optional[str]) -> dict:
    """`{tipo: workspace}` de este dueño. Sin dueño devuelve `{}` — una pantalla sin sesión
    no tiene preferencias, y eso no es un error que haya que mostrar."""
    dueno = _seguro(user_id)
    if not dueno:
        return {}
    with _LOCK:
        return dict(_leer(dueno).get("preferencias") or {})


def olvidar(user_id: Optional[str], ws: str) -> bool:
    """Borra la memoria de un workspace. Existe para que «empezar de cero» sea posible sin
    tocar un archivo a mano."""
    dueno = _seguro(user_id)
    clave = _seguro(ws, 60)
    if not dueno or not clave:
        return False
    with _LOCK:
        datos = _leer(dueno)
        if clave not in datos["workspaces"]:
            return False
        datos["workspaces"].pop(clave)
        _escribir(dueno, datos)
        return True


# ── LOS AJUSTES DE LA CASA ──────────────────────────────────────────────────────────
# [Convergencia · superficie 3 · fase 2]
#
# POR QUÉ ACÁ Y NO EN UN ALMACÉN NUEVO: por lo mismo que ya está escrito veinte líneas
# más arriba para `preferir`. Mismo dueño, mismo momento de lectura, mismo candado,
# misma escritura atómica 0600, misma `schema_version` LEÍDA. Un tercer almacén sería
# un tercer lugar donde arreglar el día que la clave de dominio cambie.
#
# LA CLAVE ES `(dueño, ámbito)`. El ámbito es `CASA` —toda la casa— o el id de un
# workspace. La precedencia NO la inventé acá: es la que ya recomienda
# `AUDITORIA-IMPACTO…md §5.2` en sus puntos 4 y 5 —**preferencia del workspace, y
# después default del sistema/usuario**—, aplicada a ajustes de interfaz en vez de a
# selección de modelo. Resolver es: el valor del espacio si está, si no el de la casa,
# si no el default declarado.
#
# EL VOCABULARIO ES CERRADO A PROPÓSITO. Un ajuste que no está declarado no se guarda:
# levanta `ajuste_desconocido`. Un almacén que acepta cualquier clave se vuelve un cajón
# de sastre y el día que alguien escriba `temaa` nadie se entera hasta que un usuario
# reporta que su ajuste no hace nada.
#
# QUÉ **NO** ESTÁ ACÁ, Y ES DELIBERADO: `tema` e `idioma`. Hoy su fuente es
# `localStorage` (`theme.js`, `i18n.js`) y meterlos ahora dejaría **dos escritores del
# mismo valor** — que es exactamente el riesgo que el plan marcó antes de la primera
# línea. Entran en la fase 1, el mismo día que se les da la vuelta al escritor, no antes.
# Mientras tanto hay UN solo escritor por ajuste, siempre.

#: El ámbito de «toda la casa». No es un workspace y por eso no puede colisionar con uno:
#: ningún workspace del registro se llama así.
CASA = "casa"

#: Los ajustes declarados. `de` dice de qué vertical se tomó el mecanismo — no es adorno:
#: es lo que permite volver a mirar el original cuando algo no cierra.
AJUSTES = {
    # [fase 1b] LOS VALORES SON LOS QUE YA ESTÁN EN DISCO. `theme.js` persiste
    # `light|dark|system` en `localStorage['aleph-theme']` e `i18n.js` persiste `es|en` en
    # `aleph-lang`. Traducirlos a castellano acá dejaría huérfano el valor guardado de cada
    # instalación que ya existe, y obligaría a una tabla de traducción entre la cara y el
    # almacén. El vocabulario de una preferencia lo fija quien ya la escribía.
    "tema":          {"valores": ("light", "dark", "system"), "default": "dark",
                      "de": "aleph"},
    "idioma":        {"valores": ("es", "en"), "default": "es", "de": "aleph"},
    # de Legal (`Settings.tsx:76`), la única de los seis que lo tiene. Es accesibilidad,
    # no oficio: por eso es de la casa y no de un espacio.
    "tamano_texto":  {"valores": ("compacto", "estandar", "grande"), "default": "estandar",
                      "de": "legal"},
    # de Educación. Es una INSTRUCCIÓN AL CEREBRO, no idioma de interfaz: alguien puede
    # querer la casa en castellano y que el modelo le conteste en inglés. `auto` = el que
    # tenga la interfaz, que es lo que pasa hoy sin este ajuste.
    "idioma_salida": {"valores": ("auto", "es", "en"), "default": "auto",
                      "de": "educacion"},
    # de Educación. La Sala también pinta bloques de código, así que es transversal.
    # mismo triple que `tema` a propósito: es el mismo eje conceptual y dos vocabularios
    # para «claro/oscuro/sistema» es una tabla de traducción esperando a existir.
    "tema_codigo":   {"valores": ("light", "dark", "system"), "default": "system",
                      "de": "educacion"},
    # de Oficina, y **el primero que de verdad es POR ESPACIO**. Los cinco de arriba son
    # transversales y su cara los marca `soloCasa`: valen para toda la instalación. Éste no:
    # «compactá el contexto solo» es una decisión del oficio de cada espacio, y el almacén ya
    # sabía resolverla —precedencia espacio > casa > default— desde la fase 2. Lo que faltaba
    # era una clave que la usara.
    #
    # QUIÉN LO LEE: `pack.py::_declarar_plugin_al_motor`, que lo escribe como
    # `compaction.auto` en el `opencode.json` que genera al ENTRAR. Por eso el default es
    # `si`: es el que ya tenía OpenWork (`settings-route.tsx:519`), y cambiarlo de callado al
    # migrar el control habría sido un cambio de conducta escondido en una mudanza de UI.
    "compactacion":  {"valores": ("si", "no"), "default": "si", "de": "oficina"},
    # ── LO QUE NO ESTÁ ACÁ, CENSADO Y NO OLVIDADO ───────────────────────────────────────
    # [rediseño · fase 4 · 4.5] El mockup pide ~29 filas repartidas en cinco secciones de
    # workspace. Medido stack por stack, **la mayoría no son ajustes: son SUPERFICIES**, y
    # una superficie no entra en una tabla de `{clave: valores}`.
    #
    #   Ciencia    Skills · Specialists · Compute · Sandbox · Permissions · Storage
    #              son `SettingsPanel` con `component: lazy(() => import("./Skills"))`
    #              (`settings/registry.ts:56-127`): paneles, cada uno con su propia UI.
    #   Finanzas   Agent · Runtime · Scheduled · Reports · Alpha Zoo · Correlation Matrix
    #              son PÁGINAS (`frontend/src/pages/Agent.tsx`, `Runtime.tsx`, …).
    #   Educación  Knowledge Base · Co-Writer · Learning Space son RUTAS
    #              (`web/app/(workspace)/co-writer`, `(utility)/knowledge`, `space`).
    #   Oficina    el propio doc dice «sin ajustes propios». Nada que traer.
    #
    # Traerlas acá sería reconstruir el panel de otro (su oficio, no nuestra piel) o
    # convertirlas en enlaces profundos al `<iframe>` — que es una función de NAVEGACIÓN
    # cross-origin, no un puente de config, y necesita un contrato por stack que hoy no
    # existe. Ninguna de las dos es esta fase.
    #
    # Las que SÍ son ajustes de verdad son las de Legal, y están abajo. De las suyas quedan
    # afuera **Attorney, Firm y House style**: son texto libre y este vocabulario es cerrado
    # (`valores` es una tupla). Un control cuyo valor no puede llegar al lector es la perilla
    # pintada de siempre; el día que el almacén sepa guardar un string arbitrario, entran.
    #
    # ── LEGAL · las perillas del estudio ────────────────────────────────────────────────
    # [rediseño · fase 4 · 4.1 y 4.2] Son cuatro y NO son de la casa: las lee el motor de
    # Legal. Su destino final es `$WORKSPACE_ROOT/.preferences/`, y ahí hay DOS archivos que
    # no se leen igual — por eso el puente no escribe el archivo, llama a su endpoint:
    #
    #   preferences.json  lo relee `dochaus/lib/research.ts:78-84` EN CADA LLAMADA
    #   drafting.md       lo monta `opencode.json` como `config.instructions` y el motor lo
    #                     relee EN CADA TURNO — y sólo lo re-renderiza
    #                     `writeDraftingPreferences` (`preferences.ts:66-67`)
    #
    # Escribir el JSON a mano dejaría las tres primeras cambiadas en pantalla y al modelo
    # obedeciendo el texto viejo: verde perfecto, cero efecto. Ver `puentes.py`.
    #
    # ⚠️ EL VOCABULARIO ES EL DE ELLOS, no una traducción. Los valores son los literales que
    # `DraftingPreferences` declara (`preferences.ts:16-41`): traducirlos acá obligaría a una
    # tabla de ida y vuelta y a que alguien la mantenga. Misma regla que `tema` e `idioma`,
    # que se guardan `light|dark|system` y `es|en` porque así los escribía quien ya los tenía.
    #
    # ── EL GRUPO, QUE ES LO QUE PIDE EL MOCKUP 38b ──────────────────────────────────────
    # [rediseño · Legal · el frame] El artboard no dibuja cuatro filas sueltas: dibuja
    # **Drafting** con sus ajustes ANIDADOS ADENTRO DE SU FILA, y `Research` como otra fila
    # del mismo grupo LEGAL. La hoja del estándar lo dice para todo Aleph: «los mini-ajustes
    # de cada sección se anidan dentro de su fila en lugar de mandarte a otra pantalla».
    #
    # `grupo` es el rótulo de la fila madre. Va acá y no en la pantalla por la misma razón
    # que el copy: una lista en el front se desincroniza el primer día. Sin `grupo`, la fila
    # se dibuja plana, como hasta hoy — los cinco ajustes de la casa no cambian.
    #
    # ⚠️ Y LO QUE FALTA DEL 38b SE DICE, NO SE FINGE. El artboard pone SEIS anidados bajo
    # Drafting; acá entran tres. Attorney, Firm y House style son TEXTO LIBRE y este
    # vocabulario es cerrado (`valores` es una tupla): un control cuyo valor no puede llegar
    # al lector es la perilla pintada de siempre. Y `Matter defaults` y `Approvals` no viven
    # en el backend de Legal sino en el `localStorage` de SU origen (`dochaus.prefs`, ver
    # `apps/web/src/prefs.ts`): no hay lector al que un puente HTTP pueda llegar, y el brief
    # de esta fase decidió converger la PUERTA, no el estado del backend del stack. Las tres
    # filas que sí gobiernan se pintan; las otras no se prometen.
    "legal_postura":       {"valores": ("client-favorable", "balanced", "conservative"),
                            "default": "balanced", "de": "legal", "lee_ws": ("legal",),
                            "campo": "posture", "grupo": "Drafting",
                            "titulo": "Postura", "sub": "Qué tan del lado del cliente redacta."},
    "legal_formalidad":    {"valores": ("formal", "plain"), "default": "formal",
                            "de": "legal", "lee_ws": ("legal",), "campo": "formality",
                            "grupo": "Drafting",
                            "titulo": "Formalidad", "sub": "Registro del texto que produce."},
    "legal_detalle":       {"valores": ("concise", "detailed"), "default": "concise",
                            "de": "legal", "lee_ws": ("legal",), "campo": "detail",
                            "grupo": "Drafting",
                            "titulo": "Detalle", "sub": "Cuánto desarrolla cada punto."},
    # Ésta es la de 4.2: su lector (`research.ts`) relee el JSON por llamada, así que aplica
    # desde la próxima búsqueda sin reiniciar nada.
    "legal_investigacion": {"valores": ("official", "open"), "default": "official",
                            "de": "legal", "lee_ws": ("legal",), "campo": "webResearch",
                            "grupo": "Research",
                            "titulo": "Investigación web",
                            "sub": "Sólo fuentes oficiales, o toda la web."},

}


def _ambito(valor: Optional[str]) -> str:
    """`CASA` o un id de workspace. Nada más — un ámbito libre volvería la precedencia
    imposible de razonar."""
    if valor is None or valor == "" or valor == CASA:
        return CASA
    clave = _seguro(valor, 60)
    if not clave:
        raise MemoriaError("ambito_invalido", str(valor)[:40])
    return clave


def declarados() -> dict:
    """El vocabulario, para que la cara no lo reimplemente. Devuelve
    `{clave: {valores, default, de}}` — la pantalla dibuja las opciones desde acá, no
    desde una lista suya que se desincroniza el primer día."""
    return {k: {"valores": list(v["valores"]), "default": v["default"], "de": v["de"],
                # [fase 4] El COPY viaja con el vocabulario. La regla de la casa es que
                # ninguna causa llega a una superficie sin copy; lo mismo vale para un
                # ajuste. Escribirlo en el front sería la lista que se desincroniza.
                "titulo": v.get("titulo") or k, "sub": v.get("sub") or "",
                # Qué espacios lo leen. Vacío = lo lee la casa.
                "lee_ws": list(v.get("lee_ws") or ()),
                # El nombre del campo EN EL DESTINO. Lo usa `puentes.py`; sin esto el puente
                # tendría su propia tabla de correspondencias y serían dos listas del mismo
                # hecho. `None` = no cruza a ningún stack.
                "campo": v.get("campo"),
                # El rótulo de la fila madre en la que este ajuste se anida (mockup 38b).
                # Vacío = fila plana, que es como se dibujaban todos hasta ahora.
                "grupo": v.get("grupo") or ""}
            for k, v in AJUSTES.items()}


def ajustes(user_id: Optional[str], ambito: Optional[str] = None) -> dict:
    """Los ajustes RESUELTOS para este dueño en este ámbito.

    Siempre devuelve las tres claves con un valor usable: si nadie eligió nada, el
    default declarado. Una pantalla nunca tiene que preguntarse «¿y si no está?».

    Sin dueño devuelve los defaults —no levanta—, por lo mismo que `preferencias`: una
    pantalla sin sesión no tiene ajustes, y eso no es un error que haya que mostrar.
    """
    amb = _ambito(ambito)
    dueno = _seguro(user_id)
    resuelto = {k: v["default"] for k, v in AJUSTES.items()}
    if not dueno:
        return resuelto
    with _LOCK:
        guardados = dict(_leer(dueno).get("ajustes") or {})
    # precedencia: primero la casa, después el espacio lo pisa (§5.2 · 4 gana sobre 5)
    for capa in (CASA, amb) if amb != CASA else (CASA,):
        for k, v in (guardados.get(capa) or {}).items():
            if k in AJUSTES and v in AJUSTES[k]["valores"]:
                resuelto[k] = v
    return resuelto


def ajustar(user_id: Optional[str], ambito: Optional[str],
            cambios: dict) -> dict:
    """Graba ajustes de este dueño en este ámbito. Devuelve los RESUELTOS después.

    **Es un MERGE, no un reemplazo** —igual que `recordar`—: una pantalla que sólo sabe
    el tamaño de texto no puede borrarle el tema de código a otra. Para volver un ajuste
    al default se manda `None`, que es una decisión explícita del llamante y no un campo
    que se olvidó de mandar.
    """
    dueno = _seguro(user_id)
    if not dueno:
        raise MemoriaError("sin_dueno", "un ajuste es de alguien")
    amb = _ambito(ambito)
    if not isinstance(cambios, dict) or not cambios:
        return ajustes(dueno, amb)
    for k, v in cambios.items():
        if k not in AJUSTES:
            raise MemoriaError("ajuste_desconocido", str(k)[:40])
        if v is not None and v not in AJUSTES[k]["valores"]:
            raise MemoriaError("valor_invalido", f"{k}={str(v)[:30]}")
    with _LOCK:
        datos = _leer(dueno)
        todos_amb = dict(datos.get("ajustes") or {})
        capa = dict(todos_amb.get(amb) or {})
        for k, v in cambios.items():
            if v is None:
                capa.pop(k, None)                           # volver al default
            else:
                capa[k] = v
        if capa:
            todos_amb[amb] = capa
        else:
            todos_amb.pop(amb, None)                        # no dejar ámbitos vacíos
        datos["ajustes"] = todos_amb
        datos["schema_version"] = SCHEMA_VERSION
        _escribir(dueno, datos)
    return ajustes(dueno, amb)
