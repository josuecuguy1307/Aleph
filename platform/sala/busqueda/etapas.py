"""etapas.py — EL ADAPTADOR: los bloques de Vane → los estados en vivo de LA SALA.
[Gate 4 · Fase 6 · §6.a.bis]

POR QUÉ EXISTE
--------------
§6.a.bis lo sella: **«su UI NO se monta … La cara ES la Sala: el pipeline se rinde EN la
línea de razonamiento — "buscando X → leyendo Y → 8 resultados"»**. El motor ya emite todo
lo necesario; lo que falta es la traducción. Esto es la traducción, y es **pura**: entra un
evento del cable, sale lo que la Sala pinta. No hace red, no toca disco.

LA PUERTA ES `/api/chat`, Y ESO NO ES UN DETALLE
-------------------------------------------------
Vane expone **dos** puertas y la que documenta es la que no sirve:

- `POST /api/search` — la documentada (`third_party/vane/docs/API/SEARCH.md`). Le pasa al
  investigador **una sesión descartable**:
  `third_party/vane/src/lib/agents/search/api.ts:31` →
  `researcher.research(SessionManager.createSession(), …)`. Todo el progreso se emite a una
  sesión que nadie escucha. Por esta puerta **no hay** «buscando → leyendo».
- `POST /api/chat` — la que usa su propia cara, y la que Aleph usa
  (`third_party/vane/src/app/api/chat/route.ts:159-211`). Emite bloques y **parches
  RFC-6902** sobre esos bloques. Ahí está el pipeline entero.

EL CABLE, tal cual sale (`route.ts:161-210`)
---------------------------------------------
NDJSON, una línea por objeto:

    {"type":"block",       "block":{…}}
    {"type":"updateBlock", "blockId":"…", "patch":[…]}   ← RFC-6902
    {"type":"researchComplete"}
    {"type":"messageEnd"}
    {"type":"error", "data":…}

El truco del formato: el bloque `research` **se emite una vez, vacío**, y después CRECE por
parches sobre `/data/subSteps` (`third_party/vane/src/lib/agents/search/researcher/index.ts:39-45`
lo emite; `actions/search/baseSearch.ts:29-35` lo va parchando). O sea: **el estado en vivo
no viaja en los eventos, viaja en el bloque acumulado**. Por eso este módulo mantiene los
bloques y aplica los parches — sin eso, un `updateBlock` suelto no dice nada.

CONTRATO EN DOS LUGARES, declarado
-----------------------------------
Los 9 estados de la Sala están congelados en `product/app/design/sala-v2/agui/estados.js:27-37`
(JS del frontend). Acá se replican como constantes. Es un contrato en dos lugares y se
declara como tal: si divergen, esta tabla es la que miente y hay que arreglarla.
"""
from __future__ import annotations

from typing import Any, Optional

# ── Los estados de la Sala (estados.js:27-37) ─────────────────────────────────
QUIETO = "quieto"
PENSANDO = "pensando"
PREPARANDO = "preparando"
EJECUTANDO = "ejecutando"
RECIBIENDO = "recibiendo"
INTERPRETANDO = "interpretando"
FINAL = "final"
FALLO = "fallo"

# ── Las etapas gruesas que §6.a.bis nombra ────────────────────────────────────
PLANIFICANDO = "planificando"
BUSCANDO = "buscando"
LEYENDO = "leyendo"
RESPONDIENDO = "respondiendo"
TERMINANDO = "terminando"
FALLANDO = "fallando"

#: Los 6 subpasos del bloque `research`, medidos en
#: `third_party/vane/src/lib/types.ts:68-98`. La cuarta columna es el nombre del campo que
#: trae la carga: **no son iguales y confundirlos pinta la línea vacía** — `searching` trae
#: `searching: string[]` (las consultas) mientras que `search_results` y `reading` traen
#: `reading: Chunk[]`, y `upload_searching` trae `queries`, y `upload_search_results` trae
#: `results`. Cuatro nombres distintos para la misma idea.
SUBPASOS: dict[str, tuple[str, str, str, str]] = {
    # tipo                    → (etapa,        estado,        copy,                                  campo)
    "reasoning":                (PLANIFICANDO, PENSANDO,      "Pensando cómo buscarlo…",             "reasoning"),
    "searching":                (BUSCANDO,     EJECUTANDO,    "Buscando: {items}",                   "searching"),
    "search_results":           (BUSCANDO,     RECIBIENDO,    "{n} resultados",                      "reading"),
    "reading":                  (LEYENDO,      RECIBIENDO,    "Leyendo {items}",                     "reading"),
    "upload_searching":         (BUSCANDO,     EJECUTANDO,    "Buscando en tus archivos: {items}",   "queries"),
    "upload_search_results":    (LEYENDO,      RECIBIENDO,    "{n} pasajes de tus archivos",         "results"),
}

#: Los bloques de primer nivel (`types.ts:38-112`).
BLOQUES = frozenset({"text", "source", "suggestion", "widget", "research"})


class Traductor:
    """Mantiene los bloques del turno y traduce cada evento del cable.

    Con estado a propósito: el formato de Vane exige acumular. `consumir()` devuelve la
    lista de sobres a pintar por ese evento (puede ser vacía), en orden.
    """

    def __init__(self) -> None:
        self.bloques: dict[str, dict] = {}
        #: Lo último que se pintó, para no repetir la misma línea en cada parche.
        self._ultimo: Optional[tuple] = None
        #: Las fuentes del turno, que van al pasaporte del artefacto.
        self.fuentes: list[dict] = []
        #: El texto de la respuesta, acumulado.
        self.texto: str = ""

    # ── el cable ──────────────────────────────────────────────────────────────
    def consumir(self, ev: dict) -> list[dict]:
        """Traduce un evento y devuelve los sobres a pintar, ya **sin repeticiones**.

        El filtro va acá y no en el llamador a propósito: el formato de Vane parchea el
        mismo bloque muchas veces seguidas y varios parches producen la misma línea. Si
        esto fuera opcional, la primera pantalla que se olvide de llamarlo parpadea. Los
        estados terminales (`final`, `fallo`) nunca se filtran: que el cierre llegue dos
        veces es raro, que no llegue es peor.
        """
        salida: list[dict] = []
        for s in self._consumir(ev):
            clave = (s.get("etapa"), s.get("estado"), s.get("texto"))
            if clave == self._ultimo and s.get("estado") not in (FINAL, FALLO):
                continue
            self._ultimo = clave
            salida.append(s)
        return salida

    def _consumir(self, ev: dict) -> list[dict]:
        tipo = (ev or {}).get("type")
        if tipo == "block":
            return self._bloque(ev.get("block") or {})
        if tipo == "updateBlock":
            return self._parche(ev.get("blockId") or "", ev.get("patch") or [])
        if tipo == "researchComplete":
            return [self._sobre(RESPONDIENDO, INTERPRETANDO, "Redactando la respuesta…")]
        if tipo == "messageEnd":
            return [self._sobre(TERMINANDO, FINAL, "Listo.")]
        if tipo == "error":
            return [self._sobre(FALLANDO, FALLO, "La búsqueda falló.",
                                extra={"detalle": _texto(ev.get("data"))})]
        # Evento nuevo en el cable: no se traga en silencio.
        return [self._sobre(PLANIFICANDO, PENSANDO, str(tipo or "…"),
                            extra={"desconocido": True})]

    def _bloque(self, b: dict) -> list[dict]:
        bid = b.get("id")
        if not bid:
            return []
        self.bloques[bid] = b
        tipo = b.get("type")
        if tipo == "source":
            self.fuentes = _fuentes(b.get("data"))
            return [self._sobre(LEYENDO, RECIBIENDO, f"{len(self.fuentes)} fuentes citadas")]
        if tipo == "text":
            self.texto = _texto(b.get("data"))
            return [self._sobre(RESPONDIENDO, INTERPRETANDO, "Redactando la respuesta…")]
        if tipo == "research":
            return self._subpasos(b)
        if tipo in BLOQUES:
            return []                       # `suggestion` y `widget` no mueven la línea
        return [self._sobre(PLANIFICANDO, PENSANDO, f"bloque «{tipo}»",
                            extra={"desconocido": True})]

    def _parche(self, bid: str, patch: list) -> list[dict]:
        b = self.bloques.get(bid)
        if b is None:
            return []
        _aplicar(b, patch)
        if b.get("type") == "research":
            return self._subpasos(b)
        if b.get("type") == "text":
            self.texto = _texto(b.get("data"))
        return []

    # ── el bloque que crece ───────────────────────────────────────────────────
    def _subpasos(self, b: dict) -> list[dict]:
        pasos = ((b.get("data") or {}).get("subSteps")) or []
        if not pasos:
            return []
        return self._de_subpaso(pasos[-1])      # sólo el último: la línea muestra el AHORA

    def _de_subpaso(self, paso: dict) -> list[dict]:
        tipo = (paso or {}).get("type")
        fila = SUBPASOS.get(tipo or "")
        if fila is None:
            return [self._sobre(PLANIFICANDO, PENSANDO, f"paso «{tipo}»",
                                extra={"desconocido": True, "subpaso": tipo})]
        etapa, estado, plantilla, campo = fila
        carga = paso.get(campo)

        if tipo == "reasoning":
            texto = _recortar(_texto(carga)) or plantilla
            n, items = None, []
        elif isinstance(carga, list) and carga and isinstance(carga[0], dict):
            # Chunks: se cuentan y se nombra el primero, no se listan 20 títulos.
            items = [_titulo(c) for c in carga if _titulo(c)]
            n = len(carga)
            texto = plantilla.format(n=n, items=_lista(items))
        elif isinstance(carga, list):
            items = [str(x) for x in carga if str(x).strip()]
            n = len(items)
            texto = plantilla.format(n=n, items=_lista(items))
        else:
            items, n = [], None
            texto = plantilla.format(n=0, items="…")

        return [self._sobre(etapa, estado, texto,
                            extra={"subpaso": tipo, "n": n, "items": items[:8]})]

    # ── el sobre ──────────────────────────────────────────────────────────────
    def _sobre(self, etapa: str, estado: str, texto: str,
               extra: Optional[dict] = None) -> dict:
        s = {"etapa": etapa, "estado": estado, "texto": texto}
        if extra:
            s.update({k: v for k, v in extra.items() if v is not None})
        return s


# ── RFC-6902, el subconjunto que Vane usa ─────────────────────────────────────
def _aplicar(obj: dict, patch: list) -> None:
    """Aplica los parches. Vane emite **sólo `replace`** sobre rutas que ya existen
    (`third_party/vane/src/lib/agents/search/researcher/index.ts:104-110`,
    `actions/search/baseSearch.ts:29-35,100-106,118-124`), y `add`/`remove` nunca aparecen
    en el árbol medido. Se implementan `replace` y `add`; lo que no se entiende **se
    ignora sin fingir**, porque un parche mal aplicado es peor que un parche no aplicado.
    """
    for p in patch or []:
        if not isinstance(p, dict):
            continue
        op = p.get("op")
        if op not in ("replace", "add"):
            continue
        ruta = str(p.get("path") or "")
        if not ruta.startswith("/"):
            continue
        partes = [t.replace("~1", "/").replace("~0", "~") for t in ruta[1:].split("/")]
        cur: Any = obj
        try:
            for t in partes[:-1]:
                cur = cur[int(t)] if isinstance(cur, list) else cur[t]
            ultimo = partes[-1]
            if isinstance(cur, list):
                if ultimo == "-":
                    cur.append(p.get("value"))
                else:
                    i = int(ultimo)
                    if op == "add":
                        cur.insert(i, p.get("value"))
                    else:
                        cur[i] = p.get("value")
            else:
                cur[ultimo] = p.get("value")
        except (KeyError, IndexError, TypeError, ValueError):
            continue


# ── plomería ──────────────────────────────────────────────────────────────────
def _texto(v: Any) -> str:
    return v if isinstance(v, str) else ("" if v is None else str(v))


def _titulo(c: Any) -> str:
    if not isinstance(c, dict):
        return ""
    m = c.get("metadata") if isinstance(c.get("metadata"), dict) else {}
    return _texto(m.get("title")).strip()


def _lista(items: list[str]) -> str:
    """Dos nombres y «y N más». Una línea de estado no es una lista."""
    items = [i for i in items if i]
    if not items:
        return "…"
    if len(items) <= 2:
        return " · ".join(items)
    return f"{items[0]} · {items[1]} y {len(items) - 2} más"


def _recortar(s: str, tope: int = 160) -> str:
    s = " ".join(s.split())
    return s if len(s) <= tope else s[: tope - 1].rstrip() + "…"


def _fuentes(crudo: Any) -> list[dict]:
    """`Chunk[]` → `{url, titulo}`, sin inventar ninguna y sin repetir."""
    salida: list[dict] = []
    vistas: set[str] = set()
    for c in (crudo or []):
        if not isinstance(c, dict):
            continue
        m = c.get("metadata") if isinstance(c.get("metadata"), dict) else {}
        url = _texto(m.get("url")).strip()
        if not url or url in vistas:
            continue
        vistas.add(url)
        salida.append({"url": url, "titulo": _texto(m.get("title")).strip()})
    return salida
